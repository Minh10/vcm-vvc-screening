#!/usr/bin/env bash
# Fetch VTM into third_party/VTM and record exactly what was fetched.
#
# The hooked encoder used by both screening branches is VTM-24.0 (commit ca331de2) + the encoder-side VCM hooks
# (VCM_HOOKS.md). It is published two ways, which must agree:
#   1. branch `vcm-hooks` of https://github.com/Minh10/VVCSoftware_VTM (may be private);
#   2. third_party/vtm_patch/vcm-hooks.patch in this repository (= git diff VTM-24.0..vcm-hooks), public and
#      auditable on its own.
# Default: try (1); if it cannot be cloned, clone official VTM-24.0 and apply (2). Either way the script checks
# that the hooked tree equals VTM-24.0 + the patch and writes third_party/VTM_COMMIT (base, tree, patch hash).
# With every VCM option empty, the hooked encoder's output is byte-identical to VTM-24.0.
#
# Force the patch route:          VTM_SOURCE=patch scripts/fetch_vtm.sh
# Unmodified reference instead:   VTM_SOURCE=vanilla scripts/fetch_vtm.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$ROOT/third_party/VTM"
PATCH="$ROOT/third_party/vtm_patch/vcm-hooks.patch"
BASE_COMMIT="ca331de230f27e0489df9d2fa6c006e2dcd2ed89"   # VTM-24.0
HOOK_REPO="${VTM_REPO:-https://github.com/Minh10/VVCSoftware_VTM.git}"
HOOK_REF="${VTM_REF:-vcm-hooks}"
OFFICIAL="${VTM_OFFICIAL:-https://vcgit.hhi.fraunhofer.de/jvet/VVCSoftware_VTM.git}"
SOURCE="${VTM_SOURCE:-auto}"

clone_official() {
  git clone --branch VTM-24.0 "$OFFICIAL" "$DEST"
  [[ "$(git -C "$DEST" rev-parse HEAD)" == "$BASE_COMMIT" ]] || { echo "VTM-24.0 tag is not $BASE_COMMIT" >&2; exit 1; }
}

if [[ -e "$DEST/.git" || -L "$DEST" ]]; then
  echo "VTM already present at $DEST"
elif [[ "$SOURCE" == "vanilla" ]]; then
  clone_official
elif [[ "$SOURCE" == "auto" ]] && git clone --branch "$HOOK_REF" "$HOOK_REPO" "$DEST" 2>/dev/null; then
  echo "cloned $HOOK_REPO@$HOOK_REF"
else
  echo "applying $PATCH to official VTM-24.0"
  clone_official
  git -C "$DEST" apply --whitespace=nowarn "$PATCH"
  git -C "$DEST" -c user.name=vcm -c user.email=vcm@localhost commit -qam "apply vcm-hooks.patch"
fi

HEAD="$(git -C "$DEST" rev-parse HEAD)"
TREE="$(git -C "$DEST" rev-parse 'HEAD^{tree}')"
PATCH_SHA="$(sha256sum "$PATCH" | cut -d' ' -f1)"
if git -C "$DEST" cat-file -e "$BASE_COMMIT" 2>/dev/null; then
  if [[ "$SOURCE" != "vanilla" ]]; then
    DIFF_SHA="$(git -C "$DEST" diff "$BASE_COMMIT" HEAD | sha256sum | cut -d' ' -f1)"
    if [[ "$DIFF_SHA" != "$PATCH_SHA" ]]; then
      echo "WARNING: VTM tree differs from VTM-24.0 + vcm-hooks.patch (diff sha $DIFF_SHA)" >&2
    fi
  fi
else
  echo "WARNING: base commit $BASE_COMMIT not in the clone; cannot check the patch" >&2
fi

cat > "$ROOT/third_party/VTM_COMMIT" <<EOF
$HEAD
EOF
cat > "$ROOT/third_party/VTM_PROVENANCE" <<EOF
source: $SOURCE
head_commit: $HEAD
tree: $TREE
base_commit: $BASE_COMMIT
patch_sha256: $PATCH_SHA
EOF
echo "VTM commit: $HEAD (tree $TREE); details in third_party/VTM_PROVENANCE"
