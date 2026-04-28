#!/usr/bin/env python3
"""Aggregate finalProof rule counts from artifact stats files into a CSV."""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = REPO_ROOT / "output"
DEFAULT_DATA_DIR = REPO_ROOT / "data"
STAT_BLOCK_RE = re.compile(
    r"(?P<name>finalProof::(?:dslRuleCount|ruleCount|theoryRewriteRuleCount))"
    r"\s*=\s*\{(?P<body>.*?)\}",
    re.DOTALL,
)
RULE_ENTRY_RE = re.compile(r"([A-Za-z0-9_-]+)\s*:\s*([0-9]+)")
EXCLUDED_MAIN_RULES = {"DSL_REWRITE", "THEORY_REWRITE"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Scan ./output and aggregate finalProof::ruleCount, "
            "finalProof::dslRuleCount, and "
            "finalProof::theoryRewriteRuleCount entries into a CSV."
        )
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
        default=None,
        help="Destination CSV path. Defaults to ./data/<output-subdir>/rule-counts.csv when scanning under ./output.",
    )
    return parser.parse_args()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def default_csv_path(output_dir: Path) -> Path:
    try:
        rel = output_dir.relative_to(DEFAULT_OUTPUT_DIR.resolve())
    except ValueError:
        return DEFAULT_DATA_DIR / "rule-counts.csv"
    if rel == Path("."):
        return DEFAULT_DATA_DIR / "rule-counts.csv"
    return DEFAULT_DATA_DIR / rel / "rule-counts.csv"


def iter_stats_files(output_dir: Path) -> list[Path]:
    return sorted(output_dir.rglob("cvc5-solve-proofs-stats.txt"))


def parse_rule_counts(stats_path: Path) -> Counter[str]:
    text = read_text(stats_path)
    counts: Counter[str] = Counter()
    for match in STAT_BLOCK_RE.finditer(text):
        stat_name = match.group("name")
        for rule_name, count_text in RULE_ENTRY_RE.findall(match.group("body")):
            if stat_name == "finalProof::ruleCount" and rule_name in EXCLUDED_MAIN_RULES:
                continue
            counts[rule_name] += int(count_text)
    return counts


def write_csv(destination: Path, counts: Counter[str]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    ordered_rows = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["rule", "count"])
        for rule_name, count in ordered_rows:
            writer.writerow([rule_name, count])


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    if not output_dir.is_dir():
        print(f"Output directory not found: {output_dir}", file=sys.stderr)
        return 2

    csv_path = args.csv.resolve() if args.csv is not None else default_csv_path(output_dir)

    stats_files = iter_stats_files(output_dir)
    if not stats_files:
        print(f"No stats files found under {output_dir}", file=sys.stderr)
        return 2

    total_counts: Counter[str] = Counter()
    missing_rule_count_files: list[Path] = []
    for stats_path in stats_files:
        file_counts = parse_rule_counts(stats_path)
        if not file_counts:
            missing_rule_count_files.append(stats_path)
            continue
        total_counts.update(file_counts)

    if not total_counts:
        print(
            "No finalProof::ruleCount, finalProof::dslRuleCount, or "
            f"finalProof::theoryRewriteRuleCount entries found under {output_dir}",
            file=sys.stderr,
        )
        return 2

    write_csv(csv_path, total_counts)
    print(f"Wrote rule-count CSV to {csv_path}")

    if missing_rule_count_files:
        print(
            "Skipped "
            f"{len(missing_rule_count_files)} stats files without finalProof rule-count stats",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
