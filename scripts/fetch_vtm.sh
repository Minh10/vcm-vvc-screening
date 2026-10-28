#!/usr/bin/env bash
# Fetch VTM into third_party/VTM and verify that it is exactly the encoder the screening uses.
#
# The hooked encoder is VTM-24.0 (commit ca331de2) + the encoder-side VCM hooks (VCM_HOOKS.md). It is published two
# ways, which must give the SAME git tree (third_party/vtm_patch/EXPECTED_TREE):
#   1. branch `vcm-hooks` of https://github.com/Minh10/VVCSoftware_VTM (private);
#   2. third_party/vtm_patch/vcm-hooks.patch in this repository (= git diff VTM-24.0..vcm-hooks), public.
# Default: try (1); if it cannot be cloned, clone official VTM-24.0 and apply (2). In every case — including an
# existing checkout — the tree must equal EXPECTED_TREE, otherwise the script fails (exit 1). With every VCM option
# empty, the hooked encoder's output is byte-identical to VTM-24.0.
#
# Force the patch route:          VTM_SOURCE=patch scripts/fetch_vtm.sh
# Unmodified reference instead:   VTM_SOURCE=vanilla scripts/fetch_vtm.sh   (checks HEAD == VTM-24.0)
# Other clone of the JVET repo:   VTM_OFFICIAL=<url or local path> ...
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${VTM_DEST:-$ROOT/third_party/VTM}"
PATCH="$ROOT/third_party/vtm_patch/vcm-hooks.patch"
EXPECTED_TREE="$(tr -d '[:space:]' < "$ROOT/third_party/vtm_patch/EXPECTED_TREE")"
BASE_COMMIT="ca331de230f27e0489df9d2fa6c006e2dcd2ed89"   # VTM-24.0
HOOK_REPO="${VTM_REPO:-https://github.com/Minh10/VVCSoftware_VTM.git}"
HOOK_REF="${VTM_REF:-vcm-hooks}"
OFFICIAL="${VTM_OFFICIAL:-https://vcgit.hhi.fraunhofer.de/jvet/VVCSoftware_VTM.git}"
SOURCE="${VTM_SOURCE:-auto}"

die() { echo "ERROR: $*" >&2; exit 1; }

clone_official() {
  git clone --branch VTM-24.0 "$OFFICIAL" "$DEST"
  [[ "$(git -C "$DEST" rev-parse HEAD)" == "$BASE_COMMIT" ]] || die "VTM-24.0 tag is not $BASE_COMMIT"
}

apply_patch() {
  # --index stages every change, including files the patch creates (VCM_HOOKS.md); commit -a would miss them
  git -C "$DEST" apply --index --whitespace=nowarn "$PATCH"
  git -C "$DEST" -c user.name=vcm -c user.email=vcm@localhost commit -q -m "apply vcm-hooks.patch"
}

if [[ -e "$DEST/.git" || -L "$DEST" ]]; then
  echo "VTM already present at $DEST (verifying it)"
  [[ -z "$(git -C "$DEST" status --porcelain --untracked-files=no)" ]] || die "$DEST has uncommitted changes"
elif [[ "$SOURCE" == "vanilla" ]]; then
  clone_official
elif [[ "$SOURCE" == "auto" ]] && git clone --branch "$HOOK_REF" "$HOOK_REPO" "$DEST" 2>/dev/null; then
  echo "cloned $HOOK_REPO@$HOOK_REF"
  SOURCE=branch
else
  echo "applying $PATCH to official VTM-24.0"
  clone_official
  apply_patch
  SOURCE=patch
fi

HEAD="$(git -C "$DEST" rev-parse HEAD)"
TREE="$(git -C "$DEST" rev-parse 'HEAD^{tree}')"
PATCH_SHA="$(sha256sum "$PATCH" | cut -d' ' -f1)"
if [[ "$SOURCE" == "vanilla" ]]; then
  [[ "$HEAD" == "$BASE_COMMIT" ]] || die "vanilla checkout is $HEAD, not VTM-24.0 ($BASE_COMMIT)"
else
  [[ "$TREE" == "$EXPECTED_TREE" ]] || die "VTM tree $TREE != expected $EXPECTED_TREE (VTM-24.0 + vcm-hooks.patch). \
Refusing to build an unverified encoder."
fi

echo "$HEAD" > "$ROOT/third_party/VTM_COMMIT"
cat > "$ROOT/third_party/VTM_PROVENANCE" <<EOF
source: $SOURCE
head_commit: $HEAD
tree: $TREE
expected_tree: $EXPECTED_TREE
base_commit: $BASE_COMMIT
patch_sha256: $PATCH_SHA
EOF
echo "VTM commit: $HEAD, tree $TREE verified; details in third_party/VTM_PROVENANCE"
