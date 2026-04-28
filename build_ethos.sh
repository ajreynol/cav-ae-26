#!/usr/bin/env bash
#
# Configure and build ethos as a static binary.
#
# Usage: ./build_ethos.sh [-jN] [extra configure.sh args]
#
# Default configure flags: release --static
# On macOS, Ethos's CMake already avoids forcing unsupported fully-static
# system linking while still preferring static libraries where applicable.
# The script also tries to locate GMP automatically, first from the repo-local
# cvc5 dependency build and then from common Homebrew locations.
# -jN sets the parallel build level (default: $(nproc)).
# Any other arguments are forwarded to ethos's configure.sh.

set -e -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ETHOS_DIR="$SCRIPT_DIR/ethos"
CVC5_DEPS_DIR="$SCRIPT_DIR/cvc5/build/deps"

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

if [[ " ${CONFIG_ARGS[*]} " != *" -DGMP_INCLUDE_DIR="* ]] && [[ " ${CONFIG_ARGS[*]} " != *" -DGMP_LIBRARIES="* ]]; then
  GMP_INCLUDE_DIR=""
  GMP_LIBRARY=""

  if [ -f "$CVC5_DEPS_DIR/include/gmp.h" ] && [ -f "$CVC5_DEPS_DIR/lib/libgmp.a" ]; then
    GMP_INCLUDE_DIR="$CVC5_DEPS_DIR/include"
    GMP_LIBRARY="$CVC5_DEPS_DIR/lib/libgmp.a"
    echo "[build_ethos] Using GMP from cvc5 deps: $GMP_INCLUDE_DIR, $GMP_LIBRARY"
  elif [ -f "/opt/homebrew/include/gmp.h" ] && [ -f "/opt/homebrew/lib/libgmp.dylib" ]; then
    GMP_INCLUDE_DIR="/opt/homebrew/include"
    GMP_LIBRARY="/opt/homebrew/lib/libgmp.dylib"
    echo "[build_ethos] Using GMP from Homebrew: $GMP_INCLUDE_DIR, $GMP_LIBRARY"
  elif [ -f "/opt/homebrew/include/gmp.h" ] && [ -f "/opt/homebrew/lib/libgmp.a" ]; then
    GMP_INCLUDE_DIR="/opt/homebrew/include"
    GMP_LIBRARY="/opt/homebrew/lib/libgmp.a"
    echo "[build_ethos] Using GMP from Homebrew: $GMP_INCLUDE_DIR, $GMP_LIBRARY"
  elif [ -f "/usr/local/include/gmp.h" ] && [ -f "/usr/local/lib/libgmp.dylib" ]; then
    GMP_INCLUDE_DIR="/usr/local/include"
    GMP_LIBRARY="/usr/local/lib/libgmp.dylib"
    echo "[build_ethos] Using GMP from /usr/local: $GMP_INCLUDE_DIR, $GMP_LIBRARY"
  elif [ -f "/usr/local/include/gmp.h" ] && [ -f "/usr/local/lib/libgmp.a" ]; then
    GMP_INCLUDE_DIR="/usr/local/include"
    GMP_LIBRARY="/usr/local/lib/libgmp.a"
    echo "[build_ethos] Using GMP from /usr/local: $GMP_INCLUDE_DIR, $GMP_LIBRARY"
  fi

  if [ -n "$GMP_INCLUDE_DIR" ] && [ -n "$GMP_LIBRARY" ]; then
    CONFIG_ARGS+=("-DGMP_INCLUDE_DIR=$GMP_INCLUDE_DIR" "-DGMP_LIBRARIES=$GMP_LIBRARY")
  fi
fi

echo "[build_ethos] Configuring ethos in $ETHOS_DIR with: ${CONFIG_ARGS[*]}"
cd "$ETHOS_DIR"
./configure.sh "${CONFIG_ARGS[@]}"

BUILD_DIR="$ETHOS_DIR/build"
echo "[build_ethos] Building ethos in $BUILD_DIR with -j$JOBS"
cd "$BUILD_DIR"
make -j"$JOBS"

echo "[build_ethos] Done. Build directory: $BUILD_DIR"
