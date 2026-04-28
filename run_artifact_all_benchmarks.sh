#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ $# -ne 0 ]]; then
  printf 'Usage: ./run_artifact_all_benchmarks.sh\n' >&2
  exit 2
fi

exec "${SCRIPT_DIR}/run_artifact_all.sh" 0 --timeout 600 --delete-proofs
