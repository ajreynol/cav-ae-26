#!/usr/bin/env bash
#
# Configure and build cvc5 as a static binary with all dependencies
# auto-downloaded.
#
# Usage: ./build_cvc5.sh [-jN] [extra configure.sh args]
#
# Default configure flags: production --static --static-binary --auto-download
# -jN sets the parallel build level (default: $(nproc)).
# Any other arguments are forwarded to cvc5's configure.sh.

set -e -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CVC5_DIR="$SCRIPT_DIR/cvc5"

JOBS="$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)"
EXTRA_ARGS=()
for arg in "$@"; do
  case "$arg" in
    -j)        echo "build_cvc5: -j requires a number (use -jN)" >&2; exit 1 ;;
    -j*)       JOBS="${arg#-j}" ;;
    *)         EXTRA_ARGS+=("$arg") ;;
  esac
done

CONFIG_ARGS=(production --static --static-binary --auto-download "${EXTRA_ARGS[@]}")

echo "[build_cvc5] Configuring cvc5 in $CVC5_DIR with: ${CONFIG_ARGS[*]}"
cd "$CVC5_DIR"
./configure.sh "${CONFIG_ARGS[@]}"

BUILD_DIR="$CVC5_DIR/build"
echo "[build_cvc5] Building cvc5 in $BUILD_DIR with -j$JOBS"
cd "$BUILD_DIR"
make -j"$JOBS"

echo "[build_cvc5] Done. Binary: $BUILD_DIR/bin/cvc5"
