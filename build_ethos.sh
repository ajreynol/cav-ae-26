#!/usr/bin/env bash
#
# Configure and build ethos as a static binary.
#
# Usage: ./build_ethos.sh [-jN] [extra configure.sh args]
#
# Default configure flags: release --static
# -jN sets the parallel build level (default: $(nproc)).
# Any other arguments are forwarded to ethos's configure.sh.

set -e -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ETHOS_DIR="$SCRIPT_DIR/ethos"

JOBS="$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)"
EXTRA_ARGS=()
for arg in "$@"; do
  case "$arg" in
    -j)        echo "build_ethos: -j requires a number (use -jN)" >&2; exit 1 ;;
    -j*)       JOBS="${arg#-j}" ;;
    *)         EXTRA_ARGS+=("$arg") ;;
  esac
done

CONFIG_ARGS=(release --static "${EXTRA_ARGS[@]}")

echo "[build_ethos] Configuring ethos in $ETHOS_DIR with: ${CONFIG_ARGS[*]}"
cd "$ETHOS_DIR"
./configure.sh "${CONFIG_ARGS[@]}"

BUILD_DIR="$ETHOS_DIR/build"
echo "[build_ethos] Building ethos in $BUILD_DIR with -j$JOBS"
cd "$BUILD_DIR"
make -j"$JOBS"

echo "[build_ethos] Done. Build directory: $BUILD_DIR"
