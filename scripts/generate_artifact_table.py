#!/usr/bin/env python3
"""Generate a Markdown table from an artifact summary CSV."""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV_PATH = REPO_ROOT / "output" / "summary.csv"
DEFAULT_MARKDOWN_PATH = REPO_ROOT / "output" / "summary-table.md"
CATEGORY_ORDER = (
    "QF+UF",
    "QF+Arith",
    "QF+BV",
    "QF+Str",
    "Q+UF",
    "Q-UF",
)


@dataclass
class BenchmarkResult:
    category: str
    solve_status: str
    solve_time: float | None
    proof_status: str
    proof_time: float | None
    check_status: str
    check_time: float | None
    proof_size: int | None


@dataclass
class AggregateRow:
    label: str
    runs: int
    solve_successes: int
    solve_time_total: float
    proof_successes: int
    proof_time_total: float
    proof_ratio: float | None
    check_successes: int
    check_time_total: float
    check_ratio: float | None
    average_proof_size: float | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a Markdown summary table from output/summary.csv."
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=DEFAULT_CSV_PATH,
        help="Input CSV path.",
    )
    parser.add_argument(
        "--markdown",
        type=Path,
        default=DEFAULT_MARKDOWN_PATH,
        help="Output Markdown file path.",
    )
    parser.add_argument(
        "--title",
        default="Artifact summary by benchmark category",
        help="Heading to place above the Markdown table.",
    )
    return parser.parse_args()


def parse_float(value: str) -> float | None:
    stripped = value.strip()
    if not stripped:
        return None
    return float(stripped)


def parse_int(value: str) -> int | None:
    stripped = value.strip()
    if not stripped:
        return None
    return int(stripped)


def require_columns(fieldnames: list[str] | None, required: list[str]) -> None:
    if fieldnames is None:
        raise ValueError("CSV file is missing a header row")
    missing = [name for name in required if name not in fieldnames]
    if missing:
        raise ValueError(f"CSV file is missing required columns: {', '.join(missing)}")


def read_results(csv_path: Path) -> list[BenchmarkResult]:
    required = [
        "benchmark-category",
        "solve-status",
        "solve-time",
        "proof-status",
        "proof-time",
        "check-status",
        "check-time",
        "proof-size",
    ]
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        require_columns(reader.fieldnames, required)
        results = []
        for row in reader:
            results.append(
                BenchmarkResult(
                    category=row["benchmark-category"],
                    solve_status=row["solve-status"],
                    solve_time=parse_float(row["solve-time"]),
                    proof_status=row["proof-status"],
                    proof_time=parse_float(row["proof-time"]),
                    check_status=row["check-status"],
                    check_time=parse_float(row["check-time"]),
                    proof_size=parse_int(row["proof-size"]),
                )
            )
    return results


def sum_times(values: list[float | None]) -> float:
    return sum(value for value in values if value is not None)


def compute_ratio(numerator: float, denominator: float) -> float | None:
    if denominator <= 0.0:
        return None
    return numerator / denominator


def aggregate_rows(label: str, rows: list[BenchmarkResult]) -> AggregateRow:
    solve_rows = [row for row in rows if row.solve_status == "unsat"]
    proof_rows = [row for row in rows if row.proof_status == "unsat"]
    check_rows = [row for row in rows if row.check_status == "unsat"]

    common_proof_rows = [
        row
        for row in rows
        if row.solve_status == "unsat"
        and row.proof_status == "unsat"
        and row.solve_time is not None
        and row.proof_time is not None
    ]
    common_check_rows = [
        row
        for row in rows
        if row.solve_status == "unsat"
        and row.check_status == "unsat"
        and row.solve_time is not None
        and row.check_time is not None
    ]
    proof_size_values = [
        float(row.proof_size)
        for row in rows
        if row.proof_status == "unsat" and row.proof_size is not None
    ]

    solve_time_total = sum_times([row.solve_time for row in solve_rows])
    proof_time_total = sum_times([row.proof_time for row in proof_rows])
    check_time_total = sum_times([row.check_time for row in check_rows])
    proof_common_solve_time = sum_times([row.solve_time for row in common_proof_rows])
    proof_common_time = sum_times([row.proof_time for row in common_proof_rows])
    check_common_solve_time = sum_times([row.solve_time for row in common_check_rows])
    check_common_time = sum_times([row.check_time for row in common_check_rows])

    average_proof_size = None
    if proof_size_values:
        average_proof_size = sum(proof_size_values) / len(proof_size_values)

    return AggregateRow(
        label=label,
        runs=len(rows),
        solve_successes=len(solve_rows),
        solve_time_total=solve_time_total,
        proof_successes=len(proof_rows),
        proof_time_total=proof_time_total,
        proof_ratio=compute_ratio(proof_common_time, proof_common_solve_time),
        check_successes=len(check_rows),
        check_time_total=check_time_total,
        check_ratio=compute_ratio(check_common_time, check_common_solve_time),
        average_proof_size=average_proof_size,
    )


def format_count_time(count: int, total_time: float) -> str:
    return f"{count} / {total_time:.1f}"


def format_ratio(value: float | None) -> str:
    if value is None:
        return "--"
    return f"{value:.2f}"


def format_size(value: float | None) -> str:
    if value is None:
        return "--"
    return f"{value:.1f}"


def markdown_escape(text: str) -> str:
    replacements = {
        "\\": r"\\",
        "|": r"\|",
    }
    return "".join(replacements.get(char, char) for char in text)


def build_table_rows(results: list[BenchmarkResult]) -> list[AggregateRow]:
    by_category = {category: [] for category in CATEGORY_ORDER}
    extra_categories: dict[str, list[BenchmarkResult]] = {}
    for result in results:
        if result.category in by_category:
            by_category[result.category].append(result)
        else:
            extra_categories.setdefault(result.category, []).append(result)

    rows = [aggregate_rows(category, by_category[category]) for category in CATEGORY_ORDER]
    for category in sorted(extra_categories):
        rows.append(aggregate_rows(category, extra_categories[category]))
    rows.append(aggregate_rows("Overall", results))
    return rows


def render_markdown_table(rows: list[AggregateRow], title: str) -> str:
    lines = [
        f"# {title}",
        "",
        "| Category | # runs | Solve # / time | +Proof # / time | Ratio | +Check # / time | Ratio | Size |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows[:-1]:
        lines.append(render_table_line(row))
    lines.append(render_table_line(rows[-1], overall=True))
    lines.append("")
    return "\n".join(lines)


def render_table_line(row: AggregateRow, overall: bool = False) -> str:
    label = markdown_escape(row.label)
    if overall:
        label = f"**{label}**"
    return (
        f"| {label} | "
        f"{row.runs} | "
        f"{format_count_time(row.solve_successes, row.solve_time_total)} | "
        f"{format_count_time(row.proof_successes, row.proof_time_total)} | "
        f"{format_ratio(row.proof_ratio)} | "
        f"{format_count_time(row.check_successes, row.check_time_total)} | "
        f"{format_ratio(row.check_ratio)} | "
        f"{format_size(row.average_proof_size)} |"
    )


def main() -> int:
    args = parse_args()
    csv_path = args.csv.resolve()
    markdown_path = args.markdown.resolve()

    if not csv_path.is_file():
        print(f"CSV file not found: {csv_path}", file=sys.stderr)
        return 2

    try:
        results = read_results(csv_path)
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown = render_markdown_table(build_table_rows(results), args.title)
    markdown_path.write_text(markdown, encoding="utf-8")
    print(f"Wrote Markdown table to {markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
