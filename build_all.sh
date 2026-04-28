#!/usr/bin/env bash
#
# Configure and build both cvc5 and ethos by invoking the per-project
# build scripts. Both are built as static binaries; cvc5's dependencies
# are auto-downloaded.
#
# Usage: ./build_all.sh [-jN]
#
# -jN is forwarded to both per-project build scripts.

set -e -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

JOBS_ARG=()
for arg in "$@"; do
  case "$arg" in
    -j)        echo "build_all: -j requires a number (use -jN)" >&2; exit 1 ;;
    -j*)       JOBS_ARG=("$arg") ;;
    *)         echo "build_all: unknown argument '$arg'" >&2; exit 1 ;;
  esac
done

echo "[build_all] === Building cvc5 ==="
"$SCRIPT_DIR/build_cvc5.sh" "${JOBS_ARG[@]}"

echo "[build_all] === Building ethos ==="
"$SCRIPT_DIR/build_ethos.sh" "${JOBS_ARG[@]}"

echo "[build_all] === All builds complete ==="
