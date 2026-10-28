#!/usr/bin/env bash
# Build VTM in Release mode and record the toolchain used.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/third_party/VTM"
BUILD="$SRC/build"
JOBS="${JOBS:-$(nproc)}"

[[ -d "$SRC" ]] || { echo "Run scripts/fetch_vtm.sh first" >&2; exit 1; }

cmake -S "$SRC" -B "$BUILD" -DCMAKE_BUILD_TYPE=Release
cmake --build "$BUILD" -j "$JOBS"

{
  echo "date: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "compiler: $(${CXX:-c++} --version | head -1)"
  echo "cmake: $(cmake --version | head -1)"
  echo "cpu: $(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2- | sed 's/^ //')"
} > "$ROOT/third_party/VTM_BUILD_INFO"

echo "Binaries:"
ls -1 "$SRC/bin" 2>/dev/null || find "$SRC/bin" -maxdepth 3 -type f -name '*App*' 2>/dev/null
