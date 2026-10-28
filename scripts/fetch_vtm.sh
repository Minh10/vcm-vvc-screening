#!/usr/bin/env bash
# Fetch VTM at a pinned tag into third_party/VTM and record the exact commit.
set -euo pipefail

TAG="${VTM_TAG:-VTM-24.0}"
REPO="${VTM_REPO:-https://vcgit.hhi.fraunhofer.de/jvet/VVCSoftware_VTM.git}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$ROOT/third_party/VTM"

if [[ -d "$DEST/.git" ]]; then
  echo "VTM already present at $DEST"
else
  git clone --depth 1 --branch "$TAG" "$REPO" "$DEST"
fi

COMMIT="$(git -C "$DEST" rev-parse HEAD)"
echo "$COMMIT" > "$ROOT/third_party/VTM_COMMIT"
echo "VTM tag:    $TAG"
echo "VTM commit: $COMMIT (written to third_party/VTM_COMMIT)"
