#!/usr/bin/env python3
"""Run a sampled subset of benchmarks and write raw artifact outputs."""

from __future__ import annotations

import argparse
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = REPO_ROOT / "output"
DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_CVC5_BINARY = REPO_ROOT / "cvc5" / "build" / "bin" / "cvc5"
DEFAULT_ETHOS_BINARY = REPO_ROOT / "ethos" / "build" / "src" / "ethos"
BASE_CVC5_ARGS = ["--enum-inst", "--safe-mode=safe"]
CVC5_RUNS = [
    ("cvc5-solve.txt", []),
    ("cvc5-solve-proof.txt", ["--check-proofs"]),
    ("cvc5-proof-gen.txt", ["--dump-proofs"]),
    ("cvc5-solve-proofs-stats.txt", ["--check-proofs", "--stats-internal"]),
]
PROOF_START = b"unsat\n(\n"
PROOF_END = b"\n)\n"


@dataclass
class CommandResult:
    returncode: int
    timed_out: bool
    stdout: bytes
    stderr: bytes


def log(message: str) -> None:
    print(message, flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sample benchmarks and write cvc5/Ethos raw outputs."
    )
    parser.add_argument(
        "sample_size",
        type=int,
        help="Number of benchmarks to sample. Use 0 to run all matching benchmarks.",
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
        default=DEFAULT_OUTPUT_DIR,
        help="Output directory to recreate on each run.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="Random seed used when sampling benchmarks.",
    )
    parser.add_argument(
        "--status",
        default="unsat",
        help="Comma-separated benchmark statuses to sample from, or 'any'. Default: unsat.",
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


def parse_status_filter(raw_status: str) -> set[str] | None:
    if raw_status.strip().lower() == "any":
        return None
    statuses = {part.strip().lower() for part in raw_status.split(",") if part.strip()}
    if not statuses:
        raise ValueError("Status filter was empty. Use 'any' or provide one or more statuses.")
    return statuses


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


def ensure_default_binaries() -> tuple[Path, Path]:
    cvc5_exists = DEFAULT_CVC5_BINARY.is_file()
    ethos_exists = DEFAULT_ETHOS_BINARY.is_file()
    if cvc5_exists and ethos_exists:
        return DEFAULT_CVC5_BINARY.resolve(), DEFAULT_ETHOS_BINARY.resolve()

    missing = []
    if not cvc5_exists:
        missing.append("cvc5")
    if not ethos_exists:
        missing.append("ethos")
    log(f"[setup] Missing repo-local binaries: {', '.join(missing)}")

    jobs = os.cpu_count() or 4
    jobs_arg = f"-j{jobs}"
    if not cvc5_exists and not ethos_exists:
        run_setup_command(
            [str((REPO_ROOT / "build_all.sh").resolve()), jobs_arg],
            f"[setup] Building cvc5 and ethos with ./build_all.sh {jobs_arg}",
        )
    elif not cvc5_exists:
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
    cvc5_binary_arg: Path | None, ethos_binary_arg: Path | None
) -> tuple[Path, Path]:
    explicit_cvc5 = resolve_explicit_binary(cvc5_binary_arg, "cvc5")
    explicit_ethos = resolve_explicit_binary(ethos_binary_arg, "ethos")
    default_cvc5 = None
    default_ethos = None
    if explicit_cvc5 is None or explicit_ethos is None:
        default_cvc5, default_ethos = ensure_default_binaries()
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


def find_candidates_with_rg(bench_root: Path, statuses: set[str]) -> list[Path] | None:
    if shutil.which("rg") is None:
        return None
    matches: set[Path] = set()
    for status in statuses:
        pattern = rf"\(set-info\s+:status\s+{re.escape(status)}\)"
        result = subprocess.run(
            ["rg", "-l", "--glob", "*.smt2", pattern, str(bench_root)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode not in (0, 1):
            return None
        for line in result.stdout.decode("utf-8", errors="replace").splitlines():
            if line:
                matches.add(Path(line).resolve())
    return sorted(matches)


def benchmark_has_status(path: Path, statuses: set[str]) -> bool:
    status_re = re.compile(r"\(set-info\s+:status\s+([^\s\)]+)\)")
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            match = status_re.search(line)
            if match:
                return match.group(1).lower() in statuses
    return False


def select_benchmarks(
    bench_root: Path,
    sample_size: int,
    seed: int,
    benchmark_list: Path | None,
    statuses: set[str] | None,
) -> list[Path]:
    if benchmark_list is not None:
        log(f"[benchmarks] Reading benchmark list from {benchmark_list}")
        benchmarks = read_benchmark_list(benchmark_list, bench_root)
        return sorted(benchmarks)

    if statuses is None:
        log(f"[benchmarks] Scanning all .smt2 benchmarks under {bench_root}")
        candidates = sorted(path.resolve() for path in bench_root.rglob("*.smt2"))
    else:
        log(
            f"[benchmarks] Selecting benchmarks with declared status in "
            f"{', '.join(sorted(statuses))} under {bench_root}"
        )
        candidates = find_candidates_with_rg(bench_root, statuses)
        if candidates is None:
            log("[benchmarks] ripgrep lookup unavailable, falling back to header scan")
            candidates = []
            for path in sorted(bench_root.rglob("*.smt2")):
                if benchmark_has_status(path, statuses):
                    candidates.append(path.resolve())

    if not candidates:
        raise RuntimeError(f"No benchmarks matched under {bench_root}")
    log(f"[benchmarks] Found {len(candidates)} candidate benchmarks")

    if sample_size == 0 or sample_size >= len(candidates):
        return candidates

    rng = random.Random(seed)
    return sorted(rng.sample(candidates, sample_size))


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


def run_command(command: list[str]) -> CommandResult:
    try:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=DEFAULT_TIMEOUT_SECONDS,
            check=False,
        )
        return CommandResult(
            returncode=completed.returncode,
            timed_out=False,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            returncode=124,
            timed_out=True,
            stdout=exc.stdout or b"",
            stderr=exc.stderr or b"",
        )


def write_stdout(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def benchmark_output_dir(output_dir: Path, bench_root: Path, bench_path: Path) -> Path:
    return output_dir / bench_path.relative_to(bench_root).with_suffix("")


def extract_ethos_proof(proof_output_path: Path, cpc_signature: Path) -> tuple[bytes | None, str | None]:
    proof_output = proof_output_path.read_bytes()
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
) -> tuple[bytes, str | None]:
    proof_output_path = bench_dir / "cvc5-proof-gen.txt"
    proof_bytes, error_text = extract_ethos_proof(proof_output_path, cpc_signature)
    if proof_bytes is None:
        return error_text.encode("utf-8"), error_text.strip()

    with tempfile.NamedTemporaryFile(suffix=".eo", delete=False) as handle:
        temp_path = Path(handle.name)
        handle.write(proof_bytes)

    try:
        result = run_command([str(ethos_binary), str(temp_path)])
    finally:
        temp_path.unlink(missing_ok=True)

    issue = None
    if result.returncode != 0 or result.timed_out or result.stderr:
        issue = (
            f"ethos-check.txt rc={result.returncode} "
            f"timeout={result.timed_out} stderr_bytes={len(result.stderr)}"
        )
    return result.stdout, issue


def main() -> int:
    args = parse_args()
    log(f"[start] Running artifact subset with sample size {args.sample_size}")
    bench_root = detect_benchmark_root(args.bench_root)
    log(f"[start] Benchmark root: {bench_root}")
    statuses = parse_status_filter(args.status)
    if statuses is None:
        log("[start] Status filter: any")
    else:
        log(f"[start] Status filter: {', '.join(sorted(statuses))}")

    if not args.dry_run:
        log("[setup] Ensuring repo-local cvc5 and ethos builds are available")
        cvc5_binary, ethos_binary = resolve_toolchain(
            args.cvc5_binary, args.ethos_binary
        )
        log(f"[setup] Using cvc5 binary: {cvc5_binary}")
        log(f"[setup] Using ethos binary: {ethos_binary}")

    benchmarks = select_benchmarks(
        bench_root=bench_root,
        sample_size=args.sample_size,
        seed=args.seed,
        benchmark_list=args.benchmark_list,
        statuses=statuses,
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

    output_dir = args.output_dir.resolve()
    log(f"[output] Recreating output directory {output_dir}")
    recreate_output_dir(output_dir)
    log(f"[benchmarks] Selected {len(benchmarks)} benchmarks")

    issues: list[str] = []
    for index, bench in enumerate(benchmarks, start=1):
        rel_bench = bench.relative_to(bench_root)
        log(f"[{index}/{len(benchmarks)}] {rel_bench}")
        bench_dir = benchmark_output_dir(output_dir, bench_root, bench)
        bench_dir.mkdir(parents=True, exist_ok=True)

        for output_name, extra_args in CVC5_RUNS:
            command = [str(cvc5_binary), *BASE_CVC5_ARGS, *extra_args, str(bench)]
            result = run_command(command)
            write_stdout(bench_dir / output_name, result.stdout)
            if result.returncode != 0 or result.timed_out or result.stderr:
                issues.append(
                    f"{rel_bench}: {output_name} rc={result.returncode} "
                    f"timeout={result.timed_out} stderr_bytes={len(result.stderr)}"
                )

        ethos_output, ethos_issue = run_ethos_check(bench_dir, ethos_binary, cpc_signature)
        write_stdout(bench_dir / "ethos-check.txt", ethos_output)
        if ethos_issue is not None:
            issues.append(f"{rel_bench}: {ethos_issue}")

    if issues:
        print("\nIssues seen while running benchmarks:", file=sys.stderr)
        for issue in issues:
            print(issue, file=sys.stderr)

    log("[done] Artifact subset run complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
