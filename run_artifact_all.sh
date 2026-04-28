#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${SCRIPT_DIR}"
DEFAULT_OUTPUT_ROOT="${REPO_ROOT}/output"
DEFAULT_DATA_DIR="${REPO_ROOT}/data"
DEFAULT_TIMEOUT_SECONDS="60"

usage() {
  cat <<'EOF'
Usage: ./run_artifact_all.sh N [options]

Run the full artifact workflow:
1. run_artifact_subset.py
2. summarize_artifact_output.py
3. summarize_rule_counts.py
4. generate_artifact_table.py

Arguments:
  N                           Number of benchmarks to sample per category.

Options:
  --bench-root PATH           Benchmark root directory.
  --benchmark-list PATH       Optional file listing benchmarks to run.
  --output-dir PATH           Raw benchmark output directory.
                              Default: ./output/N
  --seed N                    Random seed for benchmark sampling. Default: 0
  -j N, --jobs N              Number of benchmark workers. Default: 1
  --timeout SECONDS           Per-benchmark timeout. Default: 60
  --delete-proofs             Delete cvc5-proof-gen.txt after the Ethos step.
  --cvc5-binary PATH          Optional cvc5 binary path.
  --ethos-binary PATH         Optional ethos binary path.
  -h, --help                  Show this help message.
EOF
}

log() {
  printf '%s\n' "$1"
}

resolve_path() {
  python3 -c 'import pathlib, sys; print(pathlib.Path(sys.argv[1]).resolve())' "$1"
}

run_step() {
  local name="$1"
  shift
  log "[$name] Running: $*"
  "$@"
}

if [[ $# -eq 0 ]]; then
  usage
  exit 2
fi

if [[ "$1" == "-h" || "$1" == "--help" ]]; then
  usage
  exit 0
fi

sample_size=""
bench_root=""
benchmark_list=""
output_dir=""
seed="0"
jobs="1"
timeout_seconds="${DEFAULT_TIMEOUT_SECONDS}"
delete_proofs="false"
cvc5_binary=""
ethos_binary=""

sample_size="$1"
shift

if ! [[ "${sample_size}" =~ ^[0-9]+$ ]]; then
  printf 'Sample size must be a non-negative integer.\n' >&2
  exit 2
fi

output_dir="${DEFAULT_OUTPUT_ROOT}/${sample_size}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --bench-root)
      [[ $# -ge 2 ]] || { printf 'Missing value for %s\n' "$1" >&2; exit 2; }
      bench_root="$2"
      shift 2
      ;;
    --benchmark-list)
      [[ $# -ge 2 ]] || { printf 'Missing value for %s\n' "$1" >&2; exit 2; }
      benchmark_list="$2"
      shift 2
      ;;
    --output-dir)
      [[ $# -ge 2 ]] || { printf 'Missing value for %s\n' "$1" >&2; exit 2; }
      output_dir="$2"
      shift 2
      ;;
    --seed)
      [[ $# -ge 2 ]] || { printf 'Missing value for %s\n' "$1" >&2; exit 2; }
      seed="$2"
      shift 2
      ;;
    -j|--jobs)
      [[ $# -ge 2 ]] || { printf 'Missing value for %s\n' "$1" >&2; exit 2; }
      jobs="$2"
      shift 2
      ;;
    --timeout)
      [[ $# -ge 2 ]] || { printf 'Missing value for %s\n' "$1" >&2; exit 2; }
      timeout_seconds="$2"
      shift 2
      ;;
    --delete-proofs)
      delete_proofs="true"
      shift
      ;;
    --cvc5-binary)
      [[ $# -ge 2 ]] || { printf 'Missing value for %s\n' "$1" >&2; exit 2; }
      cvc5_binary="$2"
      shift 2
      ;;
    --ethos-binary)
      [[ $# -ge 2 ]] || { printf 'Missing value for %s\n' "$1" >&2; exit 2; }
      ethos_binary="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown argument: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if ! [[ "${jobs}" =~ ^[1-9][0-9]*$ ]]; then
  printf '--jobs must be a positive integer.\n' >&2
  exit 2
fi

if ! [[ "${seed}" =~ ^-?[0-9]+$ ]]; then
  printf '--seed must be an integer.\n' >&2
  exit 2
fi

if ! python3 -c 'import sys; sys.exit(0 if float(sys.argv[1]) > 0 else 1)' "${timeout_seconds}"; then
  printf '--timeout must be a positive number.\n' >&2
  exit 2
fi

output_dir="$(resolve_path "${output_dir}")"
data_dir="$(resolve_path "${DEFAULT_DATA_DIR}")/${sample_size}"
summary_csv="${data_dir}/summary.csv"
rule_counts_csv="${data_dir}/rule-counts.csv"
table_markdown="${data_dir}/summary-table.md"

run_subset_cmd=(
  "${REPO_ROOT}/run_artifact_subset.py"
  "${sample_size}"
  "-j" "${jobs}"
  "--output-dir" "${output_dir}"
  "--seed" "${seed}"
  "--timeout" "${timeout_seconds}"
)
if [[ -n "${bench_root}" ]]; then
  run_subset_cmd+=("--bench-root" "$(resolve_path "${bench_root}")")
fi
if [[ -n "${benchmark_list}" ]]; then
  run_subset_cmd+=("--benchmark-list" "$(resolve_path "${benchmark_list}")")
fi
if [[ -n "${cvc5_binary}" ]]; then
  run_subset_cmd+=("--cvc5-binary" "$(resolve_path "${cvc5_binary}")")
fi
if [[ -n "${ethos_binary}" ]]; then
  run_subset_cmd+=("--ethos-binary" "$(resolve_path "${ethos_binary}")")
fi
if [[ "${delete_proofs}" == "true" ]]; then
  run_subset_cmd+=("--delete-proofs")
fi

summarize_output_cmd=(
  "${REPO_ROOT}/summarize_artifact_output.py"
  "--output-dir" "${output_dir}"
  "--csv" "${summary_csv}"
)

summarize_rules_cmd=(
  "${REPO_ROOT}/summarize_rule_counts.py"
  "--output-dir" "${output_dir}"
  "--csv" "${rule_counts_csv}"
)

generate_table_cmd=(
  "${REPO_ROOT}/generate_artifact_table.py"
  "--csv" "${summary_csv}"
  "--markdown" "${table_markdown}"
)

run_step "subset" "${run_subset_cmd[@]}"
run_step "summary" "${summarize_output_cmd[@]}"
run_step "rules" "${summarize_rules_cmd[@]}"
run_step "table" "${generate_table_cmd[@]}"

log "[done] Full artifact workflow complete"
printf 'Generated outputs:\n'
printf -- '- Raw benchmark outputs: %s\n' "${output_dir}"
printf -- '- Benchmark summary CSV: %s\n' "${summary_csv}"
printf -- '- Rule-count summary CSV: %s\n' "${rule_counts_csv}"
printf -- '- Markdown summary table: %s\n' "${table_markdown}"
