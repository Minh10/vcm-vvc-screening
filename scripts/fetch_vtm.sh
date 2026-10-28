#!/usr/bin/env bash
# Fetch VTM into third_party/VTM and record the exact commit.
#
# Default: the hooked encoder used by both screening branches = branch `vcm-hooks` of the GitHub import of the
# JVET repository (VTM-24.0 + encoder-side VCM hooks, see VCM_HOOKS.md there). With every VCM option empty its
# output is byte-identical to VTM-24.0.
#
# Unmodified reference instead:  VTM_REF=VTM-24.0 scripts/fetch_vtm.sh
# Official JVET server instead:  VTM_REPO=https://vcgit.hhi.fraunhofer.de/jvet/VVCSoftware_VTM.git VTM_REF=VTM-24.0 ...
set -euo pipefail

REF="${VTM_REF:-vcm-hooks}"
REPO="${VTM_REPO:-https://github.com/Minh10/vvcsoftware_vtm.git}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$ROOT/third_party/VTM"

if [[ -e "$DEST/.git" ]]; then
  echo "VTM already present at $DEST"
else
  git clone --depth 1 --branch "$REF" "$REPO" "$DEST"
fi

COMMIT="$(git -C "$DEST" rev-parse HEAD)"
echo "$COMMIT" > "$ROOT/third_party/VTM_COMMIT"
echo "VTM ref:    $REF"
echo "VTM commit: $COMMIT (written to third_party/VTM_COMMIT)"
