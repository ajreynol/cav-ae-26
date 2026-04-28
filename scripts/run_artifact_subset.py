#!/usr/bin/env python3
"""Run a sampled subset of benchmarks and write raw artifact outputs."""

from __future__ import annotations

import argparse
import concurrent.futures
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "output"
DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_CVC5_BINARY = REPO_ROOT / "cvc5" / "build" / "bin" / "cvc5"
DEFAULT_ETHOS_BINARY = REPO_ROOT / "ethos" / "build" / "src" / "ethos"
BASE_CVC5_ARGS = ["--enum-inst", "--safe-mode=safe"]
BENCHMARK_CATEGORIES = (
    "QF+UF",
    "QF+Arith",
    "QF+BV",
    "QF+Str",
    "Q+UF",
    "Q-UF",
)
ARITH_MARKERS = (
    "LIA",
    "NIA",
    "LRA",
    "NRA",
    "IDL",
    "RDL",
    "LIRA",
    "NIRA",
)
CVC5_RUNS = [
    ("cvc5-solve.txt", []),
    ("cvc5-solve-proof.txt", ["--check-proofs"]),
    ("cvc5-proof-gen.txt", ["--dump-proofs"]),
    ("cvc5-solve-proofs-stats.txt", ["--check-proofs", "--stats-internal"]),
]
PROOF_START = b"unsat\n(\n"
PROOF_END = b"\n)\n"
PROOF_GEN_METADATA_PREFIX = "[run_artifact_subset] proof_gen_"


@dataclass
class CommandResult:
    returncode: int
    timed_out: bool
    elapsed_seconds: float
    stdout: bytes
    stderr: bytes


def log(message: str) -> None:
    print(message, flush=True)


def default_output_dir(sample_size: int) -> Path:
    return DEFAULT_OUTPUT_ROOT / str(sample_size)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sample benchmarks and write cvc5/Ethos raw outputs."
    )
    parser.add_argument(
        "sample_size",
        type=int,
        help="Number of benchmarks to sample per category.",
    )
    parser.add_argument(
        "--bench-root",
        type=Path,
        default=None,
        help="Benchmark root directory. Defaults to ./benchmarks/smtlib-cav-26 if present.",
    )
    parser.add_argument(
        "--benchmark-list",
        type=Path,
        default=None,
        help="Optional file listing benchmarks to run, one per line.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Raw output directory to recreate on each run. Defaults to ./output/<sample_size>.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="Random seed used when sampling benchmarks.",
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=1,
        help="Number of benchmarks to process in parallel.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Per-benchmark timeout in seconds for each cvc5/Ethos invocation.",
    )
    parser.add_argument(
        "--delete-proofs",
        action="store_true",
        help="Delete cvc5-proof-gen.txt after the Ethos step finishes.",
    )
    parser.add_argument(
        "--cvc5-binary",
        type=Path,
        default=None,
        help="Optional path to cvc5. Defaults to the repo-local build.",
    )
    parser.add_argument(
        "--ethos-binary",
        type=Path,
        default=None,
        help="Optional path to ethos. Defaults to the repo-local build.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the selected benchmarks without running the tools.",
    )
    return parser.parse_args()


def detect_benchmark_root(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit.resolve()
    default_root = REPO_ROOT / "benchmarks" / "smtlib-cav-26"
    if default_root.is_dir():
        return default_root
    benchmarks_dir = REPO_ROOT / "benchmarks"
    if not benchmarks_dir.is_dir():
        raise FileNotFoundError(f"Could not find benchmarks under {benchmarks_dir}")
    child_dirs = sorted(path for path in benchmarks_dir.iterdir() if path.is_dir())
    if len(child_dirs) == 1:
        return child_dirs[0].resolve()
    return benchmarks_dir.resolve()


def resolve_explicit_binary(explicit: Path | None, tool_name: str) -> Path | None:
    if explicit is not None:
        resolved = explicit.resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"Could not find {tool_name} binary at {resolved}")
        return resolved
    return None


def run_setup_command(command: list[str], description: str) -> None:
    log(description)
    completed = subprocess.run(command, cwd=REPO_ROOT, check=False)
    if completed.returncode != 0:
        raise RuntimeError(
            f"Setup command failed with exit code {completed.returncode}: {' '.join(command)}"
        )


def cvc5_has_statistics(binary: Path) -> bool:
    result = subprocess.run(
        [str(binary), "--show-config"],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        return False
    output = result.stdout.decode("utf-8", errors="replace").lower()
    return "statistics" in output and "yes" in output.partition("statistics")[2][:32]


def ensure_default_binaries(jobs: int) -> tuple[Path, Path]:
    cvc5_exists = DEFAULT_CVC5_BINARY.is_file()
    ethos_exists = DEFAULT_ETHOS_BINARY.is_file()
    cvc5_stats_ok = cvc5_exists and cvc5_has_statistics(DEFAULT_CVC5_BINARY)
    if cvc5_exists and ethos_exists and cvc5_stats_ok:
        return DEFAULT_CVC5_BINARY.resolve(), DEFAULT_ETHOS_BINARY.resolve()

    missing = []
    if not cvc5_exists:
        missing.append("cvc5")
    if not ethos_exists:
        missing.append("ethos")
    if cvc5_exists and not cvc5_stats_ok:
        missing.append("cvc5-with-statistics")
    log(f"[setup] Missing repo-local binaries: {', '.join(missing)}")

    build_jobs = jobs if jobs > 0 else (os.cpu_count() or 4)
    jobs_arg = f"-j{build_jobs}"
    if (not cvc5_exists or not cvc5_stats_ok) and not ethos_exists:
        run_setup_command(
            [str((REPO_ROOT / "build_all.sh").resolve()), jobs_arg],
            f"[setup] Building cvc5 and ethos with ./build_all.sh {jobs_arg}",
        )
    elif not cvc5_exists or not cvc5_stats_ok:
        run_setup_command(
            [str((REPO_ROOT / "build_cvc5.sh").resolve()), jobs_arg],
            f"[setup] Building cvc5 with ./build_cvc5.sh {jobs_arg}",
        )
    else:
        run_setup_command(
            [str((REPO_ROOT / "build_ethos.sh").resolve()), jobs_arg],
            f"[setup] Building ethos with ./build_ethos.sh {jobs_arg}",
        )

    if not DEFAULT_CVC5_BINARY.is_file():
        raise RuntimeError(f"Expected cvc5 binary was not produced at {DEFAULT_CVC5_BINARY}")
    if not DEFAULT_ETHOS_BINARY.is_file():
        raise RuntimeError(f"Expected ethos binary was not produced at {DEFAULT_ETHOS_BINARY}")
    return DEFAULT_CVC5_BINARY.resolve(), DEFAULT_ETHOS_BINARY.resolve()


def resolve_toolchain(
    cvc5_binary_arg: Path | None, ethos_binary_arg: Path | None, jobs: int
) -> tuple[Path, Path]:
    explicit_cvc5 = resolve_explicit_binary(cvc5_binary_arg, "cvc5")
    explicit_ethos = resolve_explicit_binary(ethos_binary_arg, "ethos")
    default_cvc5 = None
    default_ethos = None
    if explicit_cvc5 is None or explicit_ethos is None:
        default_cvc5, default_ethos = ensure_default_binaries(jobs)
    return (
        explicit_cvc5 if explicit_cvc5 is not None else default_cvc5,
        explicit_ethos if explicit_ethos is not None else default_ethos,
    )


def read_benchmark_list(list_path: Path, bench_root: Path) -> list[Path]:
    selected: list[Path] = []
    with list_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            path = Path(line)
            resolved = path.resolve() if path.is_absolute() else (bench_root / path).resolve()
            if not resolved.is_file():
                raise FileNotFoundError(f"Benchmark not found: {resolved}")
            selected.append(resolved)
    return selected


def has_arith_theory(logic: str) -> bool:
    return any(marker in logic for marker in ARITH_MARKERS)


def has_string_theory(logic: str) -> bool:
    return "S" in logic and "SET" not in logic


def classify_benchmark_category(bench_root: Path, bench_path: Path) -> str:
    rel_path = bench_path.relative_to(bench_root)
    logic = rel_path.parts[0] if rel_path.parts else ""
    if logic.startswith("QF_"):
        logic = logic[3:]
        if "BV" in logic:
            return "QF+BV"
        if has_string_theory(logic):
            return "QF+Str"
        if has_arith_theory(logic):
            return "QF+Arith"
        return "QF+UF"

    if logic.startswith("A") or "UF" in logic or "DT" in logic:
        return "Q+UF"
    return "Q-UF"


def select_benchmarks(
    bench_root: Path,
    sample_size: int,
    seed: int,
    benchmark_list: Path | None,
) -> list[Path]:
    if benchmark_list is not None:
        log(f"[benchmarks] Reading benchmark list from {benchmark_list}")
        benchmarks = read_benchmark_list(benchmark_list, bench_root)
        return sorted(benchmarks)

    log(f"[benchmarks] Scanning all .smt2 benchmarks under {bench_root}")
    candidates = sorted(path.resolve() for path in bench_root.rglob("*.smt2"))
    if not candidates:
        raise RuntimeError(f"No benchmarks matched under {bench_root}")
    log(f"[benchmarks] Found {len(candidates)} candidate benchmarks")

    categorized: dict[str, list[Path]] = {category: [] for category in BENCHMARK_CATEGORIES}
    for candidate in candidates:
        categorized[classify_benchmark_category(bench_root, candidate)].append(candidate)

    for category in BENCHMARK_CATEGORIES:
        log(f"[benchmarks] {category}: {len(categorized[category])} candidates")

    if sample_size == 0:
        selected: list[Path] = []
        for category in BENCHMARK_CATEGORIES:
            selected.extend(categorized[category])
        return sorted(selected)

    shortages = [
        f"{category} has only {len(categorized[category])} candidates"
        for category in BENCHMARK_CATEGORIES
        if len(categorized[category]) < sample_size
    ]
    if shortages:
        raise RuntimeError(
            "Not enough benchmarks to sample from every category:\n" + "\n".join(shortages)
        )

    rng = random.Random(seed)
    selected = []
    for category in BENCHMARK_CATEGORIES:
        selected.extend(rng.sample(categorized[category], sample_size))
    return sorted(selected)


def recreate_output_dir(output_dir: Path) -> None:
    dangerous = {REPO_ROOT.resolve(), REPO_ROOT.parent.resolve(), Path("/").resolve()}
    if output_dir.resolve() in dangerous:
        raise ValueError(f"Refusing to recreate dangerous output directory: {output_dir}")
    if output_dir.exists():
        if output_dir.is_dir():
            shutil.rmtree(output_dir)
        else:
            output_dir.unlink()
    output_dir.mkdir(parents=True, exist_ok=True)


def run_command(command: list[str], timeout_seconds: float) -> CommandResult:
    start = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
        )
        return CommandResult(
            returncode=completed.returncode,
            timed_out=False,
            elapsed_seconds=time.perf_counter() - start,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            returncode=124,
            timed_out=True,
            elapsed_seconds=time.perf_counter() - start,
            stdout=exc.stdout or b"",
            stderr=exc.stderr or b"",
        )


def format_output_with_metadata(
    data: bytes, elapsed_seconds: float, returncode: int, timed_out: bool
) -> bytes:
    footer = (
        f"\n[run_artifact_subset] elapsed_seconds={elapsed_seconds:.6f} "
        f"returncode={returncode} timed_out={'true' if timed_out else 'false'}\n"
    ).encode("utf-8")
    if data.endswith(b"\n"):
        return data + footer
    return data + b"\n" + footer


def format_proof_gen_metadata(
    elapsed_seconds: float, returncode: int, timed_out: bool, status: str
) -> str:
    return (
        f"{PROOF_GEN_METADATA_PREFIX}elapsed_seconds={elapsed_seconds:.6f} "
        f"returncode={returncode} timed_out={'true' if timed_out else 'false'} "
        f"status={status}"
    )


def combine_streams(stdout: bytes, stderr: bytes) -> bytes:
    if not stdout:
        return stderr
    if not stderr:
        return stdout
    if stdout.endswith(b"\n"):
        return stdout + stderr
    return stdout + b"\n" + stderr


def write_stdout(
    path: Path,
    data: bytes,
    elapsed_seconds: float | None = None,
    returncode: int | None = None,
    timed_out: bool | None = None,
    extra_metadata_lines: list[str] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if elapsed_seconds is not None and returncode is not None and timed_out is not None:
        data = format_output_with_metadata(data, elapsed_seconds, returncode, timed_out)
    if extra_metadata_lines:
        if not data.endswith(b"\n"):
            data += b"\n"
        metadata_block = "".join(f"{line}\n" for line in extra_metadata_lines).encode("utf-8")
        data += metadata_block
    path.write_bytes(data)


def first_nonempty_line_bytes(data: bytes) -> str:
    text = data.decode("utf-8", errors="replace")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def cvc5_status_from_output(data: bytes, timed_out: bool) -> str:
    if timed_out:
        return "timeout"
    return "unsat" if first_nonempty_line_bytes(data) == "unsat" else "cvc5-error"


def benchmark_output_dir(output_dir: Path, bench_root: Path, bench_path: Path) -> Path:
    return output_dir / bench_path.relative_to(bench_root).with_suffix("")


def extract_ethos_proof(proof_output_path: Path, cpc_signature: Path) -> tuple[bytes | None, str | None]:
    proof_output = proof_output_path.read_bytes()
    marker = b"\n[run_artifact_subset] elapsed_seconds="
    marker_index = proof_output.find(marker)
    if marker_index != -1:
        proof_output = proof_output[:marker_index]
    if not proof_output.startswith(PROOF_START) or not proof_output.endswith(PROOF_END):
        return None, "failed to extract UNSAT proof from cvc5-proof-gen.txt\n"
    proof_body = proof_output[len(PROOF_START) : -len(PROOF_END)]
    proof = b"".join(
        [
            f'(include "{cpc_signature}")\n'.encode("utf-8"),
            proof_body,
        ]
    )
    return proof, None


def run_ethos_check(
    bench_dir: Path,
    ethos_binary: Path,
    cpc_signature: Path,
    timeout_seconds: float,
) -> tuple[bytes, str | None, float, int, bool]:
    proof_output_path = bench_dir / "cvc5-proof-gen.txt"
    proof_bytes, error_text = extract_ethos_proof(proof_output_path, cpc_signature)
    if proof_bytes is None:
        return error_text.encode("utf-8"), error_text.strip(), 0.0, 1, False

    with tempfile.NamedTemporaryFile(suffix=".cpc", delete=False) as handle:
        temp_path = Path(handle.name)
        handle.write(proof_bytes)

    try:
        result = run_command([str(ethos_binary), str(temp_path)], timeout_seconds)
    finally:
        temp_path.unlink(missing_ok=True)

    output_data = combine_streams(result.stdout, result.stderr)
    issue = None
    if result.returncode != 0 or result.timed_out:
        issue = (
            f"ethos-check.txt rc={result.returncode} "
            f"timeout={result.timed_out} stderr_bytes={len(result.stderr)}"
        )
    else:
        status_line = first_nonempty_line_bytes(output_data).lower()
        if status_line not in ("correct", "incomplete"):
            issue = f"ethos-check.txt unexpected_status={status_line!r}"
    return output_data, issue, result.elapsed_seconds, result.returncode, result.timed_out


def process_benchmark(
    bench_root: Path,
    bench: Path,
    output_dir: Path,
    cvc5_binary: Path,
    ethos_binary: Path,
    cpc_signature: Path,
    timeout_seconds: float,
    delete_proofs: bool,
) -> tuple[str, list[str]]:
    rel_bench = str(bench.relative_to(bench_root))
    bench_dir = benchmark_output_dir(output_dir, bench_root, bench)
    bench_dir.mkdir(parents=True, exist_ok=True)

    issues: list[str] = []
    proof_gen_metadata_line: str | None = None
    for output_name, extra_args in CVC5_RUNS:
        command = [str(cvc5_binary), *BASE_CVC5_ARGS, *extra_args, str(bench)]
        result = run_command(command, timeout_seconds)
        output_data = result.stdout
        if output_name == "cvc5-solve-proofs-stats.txt":
            output_data = combine_streams(result.stdout, result.stderr)
        output_elapsed_seconds = None
        output_returncode = None
        output_timed_out = None
        if output_name != "cvc5-solve-proofs-stats.txt":
            output_elapsed_seconds = result.elapsed_seconds
            output_returncode = result.returncode
            output_timed_out = result.timed_out
        write_stdout(
            bench_dir / output_name,
            output_data,
            elapsed_seconds=output_elapsed_seconds,
            returncode=output_returncode,
            timed_out=output_timed_out,
        )
        if output_name == "cvc5-proof-gen.txt":
            proof_gen_metadata_line = format_proof_gen_metadata(
                result.elapsed_seconds,
                result.returncode,
                result.timed_out,
                cvc5_status_from_output(output_data, result.timed_out),
            )
        first_line = first_nonempty_line_bytes(output_data)
        if result.returncode != 0 or result.timed_out or first_line != "unsat":
            issues.append(
                f"{rel_bench}: {output_name} rc={result.returncode} "
                f"timeout={result.timed_out} first_line={first_line!r}"
            )

    ethos_output, ethos_issue, ethos_elapsed_seconds, ethos_returncode, ethos_timed_out = run_ethos_check(
        bench_dir, ethos_binary, cpc_signature, timeout_seconds
    )
    write_stdout(
        bench_dir / "ethos-check.txt",
        ethos_output,
        elapsed_seconds=ethos_elapsed_seconds,
        returncode=ethos_returncode,
        timed_out=ethos_timed_out,
        extra_metadata_lines=[
            proof_gen_metadata_line
        ] if delete_proofs and proof_gen_metadata_line else None,
    )
    if ethos_issue is not None:
        issues.append(f"{rel_bench}: {ethos_issue}")
    if delete_proofs:
        (bench_dir / "cvc5-proof-gen.txt").unlink(missing_ok=True)

    return rel_bench, issues


def main() -> int:
    args = parse_args()
    if args.jobs < 1:
        print("--jobs must be at least 1", file=sys.stderr)
        return 2
    if args.timeout <= 0:
        print("--timeout must be greater than 0", file=sys.stderr)
        return 2
    log(f"[start] Running artifact subset with sample size {args.sample_size}")
    bench_root = detect_benchmark_root(args.bench_root)
    log(f"[start] Benchmark root: {bench_root}")
    log("[start] Using all benchmarks under the benchmark root")
    log(f"[start] Benchmark workers: {args.jobs}")
    log(f"[start] Per-benchmark timeout: {args.timeout:.1f}s")
    log(f"[start] Delete proof outputs: {'yes' if args.delete_proofs else 'no'}")

    if not args.dry_run:
        log("[setup] Ensuring repo-local cvc5 and ethos builds are available")
        cvc5_binary, ethos_binary = resolve_toolchain(
            args.cvc5_binary, args.ethos_binary, args.jobs
        )
        log(f"[setup] Using cvc5 binary: {cvc5_binary}")
        log(f"[setup] Using ethos binary: {ethos_binary}")

    benchmarks = select_benchmarks(
        bench_root=bench_root,
        sample_size=args.sample_size,
        seed=args.seed,
        benchmark_list=args.benchmark_list,
    )

    if args.dry_run:
        log(f"[benchmarks] Selected {len(benchmarks)} benchmarks")
        for bench in benchmarks:
            print(bench.relative_to(bench_root))
        return 0

    cpc_signature = (REPO_ROOT / "cvc5" / "proofs" / "eo" / "cpc" / "Cpc.eo").resolve()
    if not cpc_signature.is_file():
        print(f"Could not find CPC signature at {cpc_signature}.", file=sys.stderr)
        return 2

    output_dir = (
        args.output_dir.resolve()
        if args.output_dir is not None
        else default_output_dir(args.sample_size).resolve()
    )
    log(f"[output] Recreating output directory {output_dir}")
    recreate_output_dir(output_dir)
    log(f"[benchmarks] Selected {len(benchmarks)} benchmarks")

    issues: list[str] = []
    if args.jobs == 1:
        for index, bench in enumerate(benchmarks, start=1):
            rel_bench, bench_issues = process_benchmark(
                bench_root,
                bench,
                output_dir,
                cvc5_binary,
                ethos_binary,
                cpc_signature,
                args.timeout,
                args.delete_proofs,
            )
            log(f"[{index}/{len(benchmarks)}] {rel_bench}")
            issues.extend(bench_issues)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as executor:
            future_to_bench = {
                executor.submit(
                    process_benchmark,
                    bench_root,
                    bench,
                    output_dir,
                    cvc5_binary,
                    ethos_binary,
                    cpc_signature,
                    args.timeout,
                    args.delete_proofs,
                ): bench
                for bench in benchmarks
            }
            for index, future in enumerate(
                concurrent.futures.as_completed(future_to_bench), start=1
            ):
                rel_bench, bench_issues = future.result()
                log(f"[{index}/{len(benchmarks)}] {rel_bench}")
                issues.extend(bench_issues)

    if issues:
        print("\nIssues seen while running benchmarks:", file=sys.stderr)
        for issue in issues:
            print(issue, file=sys.stderr)

    log("[done] Artifact subset run complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
