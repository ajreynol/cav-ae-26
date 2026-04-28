#!/usr/bin/env python3
"""Run a sampled subset of benchmarks for artifact evaluation.

This script samples benchmarks from ./benchmarks, runs cvc5 in four modes, and
stores raw outputs under ./output while preserving the benchmark-relative file
layout.

Modes:
  A: base cvc5 run
  B: base cvc5 run + --check-proofs
  C: base cvc5 run + --dump-proofs, then check the proof in ethos
  D: same proof dump as C, then check it in ethos with statistics enabled

By default, we sample only benchmarks whose declared SMT-LIB status is
"unsat", since modes C and D require an UNSAT result in order to extract a CPC
proof for Ethos.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASE_CVC5_ARGS = ["--enum-inst", "--safe-mode=safe"]
DEFAULT_STATUS_FILTER = "unsat"
PROOF_START = b"unsat\n(\n"
PROOF_END = b"\n)\n"


@dataclass
class CommandResult:
    command: list[str]
    returncode: int
    elapsed_seconds: float
    timed_out: bool
    stdout: bytes
    stderr: bytes


@dataclass
class BenchmarkEntry:
    path: Path
    declared_status: str | None
    logic: str | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Sample benchmarks and store raw outputs for A/B/C/D artifact runs."
        )
    )
    parser.add_argument(
        "--bench-root",
        type=Path,
        default=None,
        help="Benchmark root directory. Defaults to ./benchmarks/smtlib-cav-26 if present.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "output",
        help="Directory where outputs are written.",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=10,
        help="Number of benchmarks to sample. Use 0 to run all filtered benchmarks.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="Random seed used when sampling benchmarks.",
    )
    parser.add_argument(
        "--status",
        default=DEFAULT_STATUS_FILTER,
        help=(
            "Comma-separated declared benchmark statuses to sample from "
            "(default: unsat). Use 'any' to disable status filtering."
        ),
    )
    parser.add_argument(
        "--benchmark-list",
        type=Path,
        default=None,
        help=(
            "Text file listing benchmarks to run, one path per line. Paths may be "
            "absolute or relative to the benchmark root."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=300.0,
        help="Per-command timeout in seconds.",
    )
    parser.add_argument(
        "--cvc5-binary",
        type=Path,
        default=None,
        help="Path to the cvc5 binary. Defaults to ./cvc5/build/bin/cvc5 or cvc5 on PATH.",
    )
    parser.add_argument(
        "--ethos-binary",
        type=Path,
        default=None,
        help="Path to the ethos binary. Defaults to ./ethos/build/src/ethos or ethos on PATH.",
    )
    parser.add_argument(
        "--extra-cvc5-arg",
        action="append",
        default=[],
        help="Additional cvc5 argument to append to every cvc5 invocation. Repeatable.",
    )
    parser.add_argument(
        "--extra-ethos-arg",
        action="append",
        default=[],
        help="Additional ethos argument to append to every ethos invocation. Repeatable.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the selected benchmarks and planned configuration without running tools.",
    )
    return parser.parse_args()


def find_binary(explicit: Path | None, repo_candidates: Iterable[Path], which_name: str) -> Path | None:
    if explicit is not None:
        return explicit.resolve()
    for candidate in repo_candidates:
        if candidate.is_file():
            return candidate.resolve()
    resolved = shutil.which(which_name)
    return Path(resolved).resolve() if resolved else None


def detect_benchmark_root(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit.resolve()
    default_root = REPO_ROOT / "benchmarks" / "smtlib-cav-26"
    if default_root.is_dir():
        return default_root
    benchmarks_dir = REPO_ROOT / "benchmarks"
    if not benchmarks_dir.is_dir():
        raise FileNotFoundError(
            f"Could not find a benchmark directory at {benchmarks_dir}"
        )
    child_dirs = sorted(path for path in benchmarks_dir.iterdir() if path.is_dir())
    if len(child_dirs) == 1:
        return child_dirs[0].resolve()
    return benchmarks_dir.resolve()


def parse_status_filter(raw_status: str) -> set[str] | None:
    lowered = raw_status.strip().lower()
    if lowered == "any":
        return None
    statuses = {part.strip().lower() for part in raw_status.split(",") if part.strip()}
    if not statuses:
        raise ValueError("Status filter was empty. Use 'any' or provide one or more statuses.")
    return statuses


def scan_benchmark_metadata(path: Path) -> tuple[str | None, str | None]:
    status = None
    logic = None
    status_re = re.compile(r"\(set-info\s+:status\s+([^\s\)]+)\)")
    logic_re = re.compile(r"\(set-logic\s+([^\s\)]+)\)")
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if logic is None:
                logic_match = logic_re.search(line)
                if logic_match:
                    logic = logic_match.group(1)
            if status is None:
                status_match = status_re.search(line)
                if status_match:
                    status = status_match.group(1).lower()
            if status is not None and logic is not None:
                break
    return status, logic


def load_benchmarks_from_list(list_path: Path, bench_root: Path) -> list[BenchmarkEntry]:
    selected = []
    with list_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            candidate = Path(line)
            path = candidate if candidate.is_absolute() else (bench_root / candidate)
            resolved = path.resolve()
            if not resolved.is_file():
                selected.append(BenchmarkEntry(resolved, None, None))
                continue
            status, logic = scan_benchmark_metadata(resolved)
            selected.append(BenchmarkEntry(resolved, status, logic))
    return selected


def select_benchmarks(
    bench_root: Path, status_filter: set[str] | None, sample_size: int, seed: int, benchmark_list: Path | None
) -> list[BenchmarkEntry]:
    if benchmark_list is not None:
        benchmarks = load_benchmarks_from_list(benchmark_list, bench_root)
        missing = [entry.path for entry in benchmarks if not entry.path.is_file()]
        if missing:
            missing_text = "\n".join(str(path) for path in missing[:10])
            raise FileNotFoundError(
                f"Benchmark list contains missing files:\n{missing_text}"
            )
        return benchmarks

    candidates: list[BenchmarkEntry] = []
    for path in sorted(bench_root.rglob("*.smt2")):
        declared_status, logic = scan_benchmark_metadata(path)
        if status_filter is not None and declared_status not in status_filter:
            continue
        candidates.append(BenchmarkEntry(path.resolve(), declared_status, logic))

    if not candidates:
        status_desc = "any" if status_filter is None else ",".join(sorted(status_filter))
        raise RuntimeError(
            f"No benchmarks matched under {bench_root} with status filter '{status_desc}'."
        )

    if sample_size == 0 or sample_size >= len(candidates):
        return candidates

    rng = random.Random(seed)
    return sorted(rng.sample(candidates, sample_size), key=lambda entry: str(entry.path))


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_bytes(path: Path, data: bytes) -> None:
    ensure_dir(path.parent)
    path.write_bytes(data)


def write_text(path: Path, data: str) -> None:
    ensure_dir(path.parent)
    path.write_text(data, encoding="utf-8")


def write_json(path: Path, data: object) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_command(command: list[str], cwd: Path, timeout_seconds: float) -> CommandResult:
    start = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
        )
        elapsed = time.perf_counter() - start
        return CommandResult(
            command=command,
            returncode=completed.returncode,
            elapsed_seconds=elapsed,
            timed_out=False,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
    except subprocess.TimeoutExpired as exc:
        elapsed = time.perf_counter() - start
        return CommandResult(
            command=command,
            returncode=124,
            elapsed_seconds=elapsed,
            timed_out=True,
            stdout=exc.stdout or b"",
            stderr=exc.stderr or b"",
        )


def save_command_result(out_dir: Path, prefix: str, result: CommandResult) -> dict[str, object]:
    stdout_path = out_dir / f"{prefix}.stdout.txt"
    stderr_path = out_dir / f"{prefix}.stderr.txt"
    write_bytes(stdout_path, result.stdout)
    write_bytes(stderr_path, result.stderr)
    meta = {
        "command": result.command,
        "returncode": result.returncode,
        "elapsed_seconds": result.elapsed_seconds,
        "timed_out": result.timed_out,
        "stdout_file": stdout_path.name,
        "stderr_file": stderr_path.name,
    }
    return meta


def benchmark_mode_dir(output_dir: Path, mode_name: str, rel_benchmark: Path) -> Path:
    return output_dir / mode_name / rel_benchmark.with_suffix("")


def build_ethos_proof(
    cvc5_stdout: bytes, cpc_signature: Path, cpc_expert_signature: Path | None
) -> tuple[bytes | None, str | None]:
    if not cvc5_stdout.startswith(PROOF_START) or not cvc5_stdout.endswith(PROOF_END):
        return None, "cvc5 output did not contain a CPC proof in the expected unsat wrapper"
    proof_body = cvc5_stdout[len(PROOF_START) : -len(PROOF_END)]
    proof_parts = [f'(include "{cpc_signature}")\n'.encode("utf-8")]
    if cpc_expert_signature is not None:
        proof_parts.append(f'(include "{cpc_expert_signature}")\n'.encode("utf-8"))
    proof_parts.append(proof_body)
    return b"".join(proof_parts), None


def run_mode_a(
    bench_path: Path,
    out_dir: Path,
    cvc5_binary: Path,
    cvc5_base_args: list[str],
    timeout_seconds: float,
) -> dict[str, object]:
    result = run_command([str(cvc5_binary), *cvc5_base_args, str(bench_path)], REPO_ROOT, timeout_seconds)
    meta = save_command_result(out_dir, "cvc5", result)
    meta["mode"] = "A-base"
    return meta


def run_mode_b(
    bench_path: Path,
    out_dir: Path,
    cvc5_binary: Path,
    cvc5_base_args: list[str],
    timeout_seconds: float,
) -> dict[str, object]:
    result = run_command(
        [str(cvc5_binary), *cvc5_base_args, "--check-proofs", str(bench_path)],
        REPO_ROOT,
        timeout_seconds,
    )
    meta = save_command_result(out_dir, "cvc5", result)
    meta["mode"] = "B-check-proofs"
    return meta


def run_dump_proofs(
    bench_path: Path,
    cvc5_binary: Path,
    cvc5_base_args: list[str],
    timeout_seconds: float,
) -> CommandResult:
    return run_command(
        [
            str(cvc5_binary),
            *cvc5_base_args,
            "--dump-proofs",
            "--proof-print-conclusion",
            str(bench_path),
        ],
        REPO_ROOT,
        timeout_seconds,
    )


def materialize_mode_c_or_d(
    out_dir: Path,
    cvc5_result: CommandResult,
    ethos_binary: Path,
    extra_ethos_args: list[str],
    timeout_seconds: float,
    cpc_signature: Path,
    cpc_expert_signature: Path | None,
    with_stats: bool,
) -> dict[str, object]:
    meta = {
        "mode": "D-ethos-stats" if with_stats else "C-ethos-check",
        "cvc5": save_command_result(out_dir, "cvc5", cvc5_result),
    }

    proof_bytes, proof_error = build_ethos_proof(
        cvc5_result.stdout, cpc_signature, cpc_expert_signature
    )
    if proof_bytes is None:
        meta["skipped"] = True
        meta["skip_reason"] = proof_error
        write_text(out_dir / "skip_reason.txt", proof_error or "proof generation skipped")
        return meta

    proof_path = out_dir / "proof.eo"
    write_bytes(proof_path, proof_bytes)
    ethos_args = [str(ethos_binary), *extra_ethos_args]
    if with_stats:
        ethos_args.append("--stats")
    ethos_args.append(str(proof_path))

    ethos_result = run_command(ethos_args, REPO_ROOT, timeout_seconds)
    meta["ethos"] = save_command_result(out_dir, "ethos", ethos_result)
    meta["proof_file"] = proof_path.name
    return meta


def main() -> int:
    args = parse_args()
    bench_root = detect_benchmark_root(args.bench_root)
    status_filter = parse_status_filter(args.status)
    benchmark_entries = select_benchmarks(
        bench_root=bench_root,
        status_filter=status_filter,
        sample_size=args.sample_size,
        seed=args.seed,
        benchmark_list=args.benchmark_list,
    )
    declared_rows = [
        {
            "benchmark": str(entry.path.relative_to(bench_root)),
            "declared_status": entry.declared_status or "",
            "logic": entry.logic or "",
        }
        for entry in benchmark_entries
    ]

    manifest = {
        "repo_root": str(REPO_ROOT),
        "benchmark_root": str(bench_root),
        "output_dir": str(args.output_dir.resolve()),
        "sample_size": args.sample_size,
        "selected_count": len(benchmark_entries),
        "seed": args.seed,
        "status_filter": args.status,
        "base_cvc5_args": DEFAULT_BASE_CVC5_ARGS,
        "extra_cvc5_args": args.extra_cvc5_arg,
        "extra_ethos_args": args.extra_ethos_arg,
        "timeout_seconds": args.timeout,
    }

    if args.dry_run:
        print(json.dumps(manifest, indent=2, sort_keys=True))
        for row in declared_rows:
            print(f"{row['benchmark']}\t{row['declared_status']}\t{row['logic']}")
        return 0

    cvc5_binary = find_binary(
        args.cvc5_binary,
        [REPO_ROOT / "cvc5" / "build" / "bin" / "cvc5"],
        "cvc5",
    )
    ethos_binary = find_binary(
        args.ethos_binary,
        [REPO_ROOT / "ethos" / "build" / "src" / "ethos"],
        "ethos",
    )
    if cvc5_binary is None:
        print(
            "Could not find a cvc5 binary. Use --cvc5-binary or build ./cvc5 first.",
            file=sys.stderr,
        )
        return 2
    if ethos_binary is None:
        print(
            "Could not find an ethos binary. Use --ethos-binary or build ./ethos first.",
            file=sys.stderr,
        )
        return 2

    output_dir = args.output_dir.resolve()
    ensure_dir(output_dir)

    cpc_signature = (REPO_ROOT / "cvc5" / "proofs" / "eo" / "cpc" / "Cpc.eo").resolve()
    cpc_expert = (REPO_ROOT / "cvc5" / "proofs" / "eo" / "cpc" / "expert" / "CpcExpert.eo").resolve()
    if not cpc_signature.is_file():
        print(
            f"Could not find CPC signature at {cpc_signature}.",
            file=sys.stderr,
        )
        return 2
    use_safe_mode = any(arg == "--safe-mode=safe" for arg in DEFAULT_BASE_CVC5_ARGS + args.extra_cvc5_arg)
    cpc_expert_signature = None if use_safe_mode or not cpc_expert.is_file() else cpc_expert

    cvc5_base_args = [*DEFAULT_BASE_CVC5_ARGS, *args.extra_cvc5_arg]
    manifest["cvc5_binary"] = str(cvc5_binary)
    manifest["ethos_binary"] = str(ethos_binary)
    manifest["cpc_signature"] = str(cpc_signature)
    manifest["cpc_expert_signature"] = str(cpc_expert_signature) if cpc_expert_signature else None

    write_json(output_dir / "manifest.json", manifest)
    write_text(
        output_dir / "selected_benchmarks.txt",
        "".join(f"{row['benchmark']}\n" for row in declared_rows),
    )

    summary_rows: list[dict[str, object]] = []

    for entry, metadata_row in zip(benchmark_entries, declared_rows):
        bench_path = entry.path
        rel_benchmark = Path(metadata_row["benchmark"])

        mode_a_dir = benchmark_mode_dir(output_dir, "A-base", rel_benchmark)
        mode_b_dir = benchmark_mode_dir(output_dir, "B-check-proofs", rel_benchmark)
        mode_c_dir = benchmark_mode_dir(output_dir, "C-ethos-check", rel_benchmark)
        mode_d_dir = benchmark_mode_dir(output_dir, "D-ethos-stats", rel_benchmark)

        ensure_dir(mode_a_dir)
        ensure_dir(mode_b_dir)
        ensure_dir(mode_c_dir)
        ensure_dir(mode_d_dir)

        row: dict[str, object] = {
            "benchmark": metadata_row["benchmark"],
            "declared_status": metadata_row["declared_status"],
            "logic": metadata_row["logic"],
        }

        meta_a = run_mode_a(bench_path, mode_a_dir, cvc5_binary, cvc5_base_args, args.timeout)
        write_json(mode_a_dir / "meta.json", meta_a)
        row["a_returncode"] = meta_a["returncode"]
        row["a_elapsed_seconds"] = meta_a["elapsed_seconds"]
        row["a_timed_out"] = meta_a["timed_out"]

        meta_b = run_mode_b(bench_path, mode_b_dir, cvc5_binary, cvc5_base_args, args.timeout)
        write_json(mode_b_dir / "meta.json", meta_b)
        row["b_returncode"] = meta_b["returncode"]
        row["b_elapsed_seconds"] = meta_b["elapsed_seconds"]
        row["b_timed_out"] = meta_b["timed_out"]

        dump_result = run_dump_proofs(
            bench_path=bench_path,
            cvc5_binary=cvc5_binary,
            cvc5_base_args=cvc5_base_args,
            timeout_seconds=args.timeout,
        )

        meta_c = materialize_mode_c_or_d(
            out_dir=mode_c_dir,
            cvc5_result=dump_result,
            ethos_binary=ethos_binary,
            extra_ethos_args=args.extra_ethos_arg,
            timeout_seconds=args.timeout,
            cpc_signature=cpc_signature,
            cpc_expert_signature=cpc_expert_signature,
            with_stats=False,
        )
        write_json(mode_c_dir / "meta.json", meta_c)
        row["c_cvc5_returncode"] = meta_c["cvc5"]["returncode"]
        row["c_cvc5_elapsed_seconds"] = meta_c["cvc5"]["elapsed_seconds"]
        row["c_skipped"] = meta_c.get("skipped", False)
        row["c_skip_reason"] = meta_c.get("skip_reason", "")
        row["c_ethos_returncode"] = (
            meta_c["ethos"]["returncode"] if "ethos" in meta_c else ""
        )
        row["c_ethos_elapsed_seconds"] = (
            meta_c["ethos"]["elapsed_seconds"] if "ethos" in meta_c else ""
        )

        meta_d = materialize_mode_c_or_d(
            out_dir=mode_d_dir,
            cvc5_result=dump_result,
            ethos_binary=ethos_binary,
            extra_ethos_args=args.extra_ethos_arg,
            timeout_seconds=args.timeout,
            cpc_signature=cpc_signature,
            cpc_expert_signature=cpc_expert_signature,
            with_stats=True,
        )
        write_json(mode_d_dir / "meta.json", meta_d)
        row["d_cvc5_returncode"] = meta_d["cvc5"]["returncode"]
        row["d_cvc5_elapsed_seconds"] = meta_d["cvc5"]["elapsed_seconds"]
        row["d_skipped"] = meta_d.get("skipped", False)
        row["d_skip_reason"] = meta_d.get("skip_reason", "")
        row["d_ethos_returncode"] = (
            meta_d["ethos"]["returncode"] if "ethos" in meta_d else ""
        )
        row["d_ethos_elapsed_seconds"] = (
            meta_d["ethos"]["elapsed_seconds"] if "ethos" in meta_d else ""
        )

        summary_rows.append(row)

    summary_path = output_dir / "summary.csv"
    fieldnames = [
        "benchmark",
        "declared_status",
        "logic",
        "a_returncode",
        "a_elapsed_seconds",
        "a_timed_out",
        "b_returncode",
        "b_elapsed_seconds",
        "b_timed_out",
        "c_cvc5_returncode",
        "c_cvc5_elapsed_seconds",
        "c_skipped",
        "c_skip_reason",
        "c_ethos_returncode",
        "c_ethos_elapsed_seconds",
        "d_cvc5_returncode",
        "d_cvc5_elapsed_seconds",
        "d_skipped",
        "d_skip_reason",
        "d_ethos_returncode",
        "d_ethos_elapsed_seconds",
    ]
    with summary_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(summary_rows)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
