#!/usr/bin/env python3
"""Generate a LaTeX table and optional PDF from an artifact summary CSV."""

from __future__ import annotations

import argparse
import csv
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV_PATH = REPO_ROOT / "output" / "summary.csv"
DEFAULT_TEX_PATH = REPO_ROOT / "output" / "summary-table.tex"
DEFAULT_PDF_PATH = REPO_ROOT / "output" / "summary-table.pdf"
CATEGORY_ORDER = (
    "QF+UF",
    "QF+Arith",
    "QF+BV",
    "QF+Str",
    "Q+UF",
    "Q-UF",
)
LATEX_ENGINES = ("pdflatex", "xelatex", "lualatex", "tectonic")


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
        description="Generate a LaTeX summary table from output/summary.csv."
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=DEFAULT_CSV_PATH,
        help="Input CSV path.",
    )
    parser.add_argument(
        "--tex",
        type=Path,
        default=DEFAULT_TEX_PATH,
        help="Output LaTeX file path.",
    )
    parser.add_argument(
        "--pdf",
        type=Path,
        default=DEFAULT_PDF_PATH,
        help="Output PDF path.",
    )
    parser.add_argument(
        "--caption",
        default="Artifact summary by benchmark category.",
        help="Table caption.",
    )
    parser.add_argument(
        "--label",
        default="tab:artifact-summary",
        help="LaTeX label for the table.",
    )
    parser.add_argument(
        "--engine",
        choices=LATEX_ENGINES,
        default=None,
        help="LaTeX engine to use. Defaults to the first available engine.",
    )
    parser.add_argument(
        "--tex-only",
        action="store_true",
        help="Only write the .tex file and skip PDF compilation.",
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


def latex_escape(text: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
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


def render_latex_table(rows: list[AggregateRow], caption: str, label: str) -> str:
    data_lines = []
    for row in rows[:-1]:
        data_lines.append(render_table_line(row))
    overall_line = render_table_line(rows[-1])
    body = "\n".join(data_lines)

    return f"""\\documentclass{{article}}
\\usepackage[margin=1in]{{geometry}}
\\usepackage{{booktabs}}
\\begin{{document}}
\\begin{{table}}[t]
\\centering
\\small
\\setlength{{\\tabcolsep}}{{4pt}}
\\begin{{tabular}}{{lrrrrrrr}}
\\toprule
Category & \\# runs & Solve \\# / time & +Proof \\# / time & Ratio & +Check \\# / time & Ratio & Size \\\\
\\midrule
{body}
\\midrule
{overall_line}
\\bottomrule
\\end{{tabular}}
\\caption{{{latex_escape(caption)}}}
\\label{{{latex_escape(label)}}}
\\end{{table}}
\\end{{document}}
"""


def render_table_line(row: AggregateRow) -> str:
    return (
        f"{latex_escape(row.label)} & "
        f"{row.runs} & "
        f"{format_count_time(row.solve_successes, row.solve_time_total)} & "
        f"{format_count_time(row.proof_successes, row.proof_time_total)} & "
        f"{format_ratio(row.proof_ratio)} & "
        f"{format_count_time(row.check_successes, row.check_time_total)} & "
        f"{format_ratio(row.check_ratio)} & "
        f"{format_size(row.average_proof_size)} \\\\"
    )


def detect_latex_engine(requested: str | None) -> str | None:
    if requested is not None:
        return shutil.which(requested)
    for engine in LATEX_ENGINES:
        resolved = shutil.which(engine)
        if resolved is not None:
            return resolved
    return None


def compile_pdf(tex_path: Path, pdf_path: Path, engine: str | None) -> None:
    resolved_engine = detect_latex_engine(engine)
    if resolved_engine is None:
        engine_list = ", ".join(LATEX_ENGINES)
        raise RuntimeError(
            "Could not find a LaTeX engine on PATH. "
            f"Tried: {engine_list}. The .tex file was still generated at {tex_path}."
        )

    tex_path = tex_path.resolve()
    pdf_path = pdf_path.resolve()
    tex_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    engine_name = Path(resolved_engine).name
    if engine_name == "tectonic":
        command = [
            resolved_engine,
            "--keep-logs",
            "--outdir",
            str(pdf_path.parent),
            str(tex_path),
        ]
    else:
        command = [
            resolved_engine,
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-output-directory",
            str(pdf_path.parent),
            str(tex_path),
        ]

    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"LaTeX compilation failed with {engine_name}:\n{completed.stdout}"
        )

    generated_pdf = pdf_path.parent / f"{tex_path.stem}.pdf"
    if not generated_pdf.is_file():
        raise RuntimeError(
            f"LaTeX compilation completed but did not produce {generated_pdf}"
        )
    if generated_pdf != pdf_path:
        shutil.copyfile(generated_pdf, pdf_path)


def main() -> int:
    args = parse_args()
    csv_path = args.csv.resolve()
    tex_path = args.tex.resolve()
    pdf_path = args.pdf.resolve()

    if not csv_path.is_file():
        print(f"CSV file not found: {csv_path}", file=sys.stderr)
        return 2

    try:
        results = read_results(csv_path)
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    tex_path.parent.mkdir(parents=True, exist_ok=True)
    latex = render_latex_table(build_table_rows(results), args.caption, args.label)
    tex_path.write_text(latex, encoding="utf-8")
    print(f"Wrote LaTeX table to {tex_path}")

    if args.tex_only:
        return 0

    try:
        compile_pdf(tex_path, pdf_path, args.engine)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(f"Wrote PDF table to {pdf_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
