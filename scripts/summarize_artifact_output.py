#!/usr/bin/env python3
"""Summarize artifact output directories into a CSV."""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = REPO_ROOT / "output"
DEFAULT_CSV_PATH = DEFAULT_OUTPUT_DIR / "summary.csv"
TIMING_MARKER = "\n[run_artifact_subset] elapsed_seconds="
TIMING_RE = re.compile(r"\[run_artifact_subset\] elapsed_seconds=([0-9]+(?:\.[0-9]+)?)")
PROOF_SIZE_RE = re.compile(
    r"^(?:finalProof::totalRuleCount|finalProofRuleCount)\s*=\s*(\d+)\s*$",
    re.MULTILINE,
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan ./output and summarize benchmark runs into a CSV."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Artifact output directory to scan.",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=DEFAULT_CSV_PATH,
        help="Destination CSV path.",
    )
    parser.add_argument(
        "--no-benchmark",
        action="store_true",
        help="Omit the benchmark-relative path column from the CSV.",
    )
    return parser.parse_args()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def split_body_and_time(text: str) -> tuple[str, float | None]:
    match = TIMING_RE.search(text)
    elapsed = float(match.group(1)) if match else None
    marker_index = text.find(TIMING_MARKER)
    if marker_index != -1:
        return text[:marker_index], elapsed
    return text, elapsed


def first_nonempty_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def parse_cvc5_status(path: Path) -> tuple[str, float | None]:
    body, elapsed = split_body_and_time(read_text(path))
    status = "unsat" if first_nonempty_line(body) == "unsat" else "cvc5-error"
    return status, elapsed


def parse_ethos_status(path: Path) -> tuple[str, float | None]:
    body, elapsed = split_body_and_time(read_text(path))
    normalized = body.lower()
    if re.search(r"(?m)^\s*correct\s*$", normalized):
        return "correct", elapsed
    if re.search(r"(?m)^\s*incomplete\s*$", normalized):
        return "incomplete", elapsed
    return first_nonempty_line(body), elapsed


def parse_proof_size(bench_dir: Path) -> str:
    stats_candidates = [
        bench_dir / "cvc5-solve-proofs-stats.txt",
        bench_dir / "cvc5-solve-proof-stats.txt",
    ]
    for stats_path in stats_candidates:
        if not stats_path.is_file():
            continue
        text = read_text(stats_path)
        match = PROOF_SIZE_RE.search(text)
        if match:
            return match.group(1)
    return ""


def combine_check_status(
    proof_gen_status: str, ethos_status_line: str
) -> str:
    if proof_gen_status != "unsat":
        return "cvc5-error"
    if ethos_status_line == "correct":
        return "unsat"
    if ethos_status_line == "incomplete":
        return "incomplete"
    return "ethos-error"


def format_time(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.6f}"


def iter_benchmark_dirs(output_dir: Path) -> list[Path]:
    bench_dirs = []
    for solve_path in sorted(output_dir.rglob("cvc5-solve.txt")):
        bench_dirs.append(solve_path.parent)
    return bench_dirs


def has_arith_theory(logic: str) -> bool:
    return any(marker in logic for marker in ARITH_MARKERS)


def has_string_theory(logic: str) -> bool:
    return "S" in logic and "SET" not in logic


def classify_benchmark_category(benchmark_rel: Path) -> str:
    logic = benchmark_rel.parts[0] if benchmark_rel.parts else ""
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


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    if not output_dir.is_dir():
        print(f"Output directory not found: {output_dir}", file=sys.stderr)
        return 2

    bench_dirs = iter_benchmark_dirs(output_dir)
    if not bench_dirs:
        print(f"No benchmark runs found under {output_dir}", file=sys.stderr)
        return 2

    args.csv.parent.mkdir(parents=True, exist_ok=True)

    headers = [
        "benchmark",
        "benchmark-category",
        "solve-status",
        "solve-time",
        "proof-status",
        "proof-time",
        "check-status",
        "check-time",
        "proof-size",
    ]
    if args.no_benchmark:
        headers = headers[1:]

    with args.csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)

        for bench_dir in bench_dirs:
            benchmark_rel = bench_dir.relative_to(output_dir)
            solve_status, solve_time = parse_cvc5_status(bench_dir / "cvc5-solve.txt")
            proof_status, proof_time = parse_cvc5_status(bench_dir / "cvc5-solve-proof.txt")
            proof_gen_status, proof_gen_time = parse_cvc5_status(bench_dir / "cvc5-proof-gen.txt")
            ethos_status_line, ethos_time = parse_ethos_status(bench_dir / "ethos-check.txt")
            check_status = combine_check_status(proof_gen_status, ethos_status_line)

            check_time_value: float | None
            if proof_gen_time is None and ethos_time is None:
                check_time_value = None
            else:
                check_time_value = (proof_gen_time or 0.0) + (ethos_time or 0.0)

            row = [
                str(benchmark_rel),
                classify_benchmark_category(benchmark_rel),
                solve_status,
                format_time(solve_time),
                proof_status,
                format_time(proof_time),
                check_status,
                format_time(check_time_value),
                parse_proof_size(bench_dir),
            ]
            if args.no_benchmark:
                row = row[1:]
            writer.writerow(row)

    print(f"Wrote summary CSV to {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
