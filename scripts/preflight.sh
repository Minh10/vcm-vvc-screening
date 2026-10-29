#!/usr/bin/env bash
# Preflight before P0: everything from a CLEAN checkout, nothing reused from the working copy.
#
#   1. fresh clone of this repository at REF;
#   2. pytest -q in the clone;
#   3. VTM from the public patch route (VTM_SOURCE=patch): official VTM-24.0 + vcm-hooks.patch, tree checked
#      against third_party/vtm_patch/EXPECTED_TREE (fetch_vtm.sh exits on mismatch);
#   4. Release build;
#   5. smoke tests AI, LDP, RA (decoder MD5 match, deterministic bitstream);
#   6. hooks-off identity: the hooked encoder with no VCM option vs an unmodified VTM-24.0 build (VTM_SOURCE=vanilla),
#      AI/LDP/RA, byte-identical bitstreams;
#   7. summary JSON at $OUT.
#
# Usage: scripts/preflight.sh [REF]          (default REF: current branch)
# Env:   REPO_URL (default: this checkout's origin), WORK (scratch dir), OUT (summary path),
#        VTM_OFFICIAL (JVET repo URL or a local clone), JOBS (build parallelism)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REF="${1:-$(git -C "$HERE" rev-parse --abbrev-ref HEAD)}"
REPO_URL="${REPO_URL:-$(git -C "$HERE" remote get-url origin)}"
WORK="${WORK:-$(mktemp -d)}"
OUT="${OUT:-$HERE/results/p0/preflight_$(date -u +%Y%m%dT%H%M%SZ).json}"
LOG="$WORK/preflight.log"
mkdir -p "$WORK" "$(dirname "$OUT")"
declare -A R

step() { echo "== $*" | tee -a "$LOG"; }

step "clone $REPO_URL@$REF into $WORK/repo"
git clone -q --branch "$REF" "$REPO_URL" "$WORK/repo"
cd "$WORK/repo"
R[commit]="$(git rev-parse HEAD)"

step "pytest"
if python -m pytest -q >>"$LOG" 2>&1; then R[pytest]="$(tail -1 "$LOG")"; else R[pytest]="FAIL"; fi

step "VTM via patch route"
VTM_SOURCE=patch scripts/fetch_vtm.sh >>"$LOG" 2>&1 && R[vtm_patch_route]="ok" || { R[vtm_patch_route]="FAIL"; }
[[ "${R[vtm_patch_route]}" == ok ]] || { tail -5 "$LOG"; echo "patch route failed" >&2; exit 1; }
R[vtm_tree]="$(git -C third_party/VTM rev-parse 'HEAD^{tree}')"
R[expected_tree]="$(tr -d '[:space:]' < third_party/vtm_patch/EXPECTED_TREE)"

step "build hooked VTM"
scripts/build_vtm.sh >>"$LOG" 2>&1

step "VTM-24.0 unmodified (reference for identity)"
VTM_DEST="$WORK/vtm_vanilla" VTM_SOURCE=vanilla scripts/fetch_vtm.sh >>"$LOG" 2>&1
VTM_SRC="$WORK/vtm_vanilla" scripts/build_vtm.sh >>"$LOG" 2>&1
# fetch_vtm.sh wrote the vanilla provenance last: restore the hooked one
VTM_SOURCE=patch scripts/fetch_vtm.sh >>"$LOG" 2>&1

for cfg in ai ldp ra; do
  step "smoke $cfg"
  if SMOKE_OUT="$WORK/smoke_$cfg" scripts/smoke_test.sh "$cfg" >>"$LOG" 2>&1; then R[smoke_$cfg]=PASS; else R[smoke_$cfg]=FAIL; fi
done

find_bin() { find "$1/bin" -type f -name "$2*" -perm -u+x | head -1; }
HOOKED="$(find_bin third_party/VTM EncoderApp)"; VANILLA="$(find_bin "$WORK/vtm_vanilla" EncoderApp)"
CLIP="$WORK/smoke_ldp/synthetic_416x240.yuv"
for cfg in ai ldp ra; do
  case $cfg in ai) c=encoder_intra_vtm.cfg ;; ldp) c=encoder_lowdelay_P_vtm.cfg ;; ra) c=encoder_randomaccess_vtm.cfg ;; esac
  step "identity $cfg"
  args=(-c "third_party/VTM/cfg/$c" -i "$CLIP" -wdt 416 -hgt 240 -fr 30 -f 8 -q 32 --InputBitDepth=8
        --OutputBitDepth=8 --TemporalSubsampleRatio=1 -o /dev/null)
  "$HOOKED" "${args[@]}" -b "$WORK/id_hooked_$cfg.bin" >>"$LOG" 2>&1
  "$VANILLA" "${args[@]}" -b "$WORK/id_vanilla_$cfg.bin" >>"$LOG" 2>&1
  a="$(sha256sum "$WORK/id_hooked_$cfg.bin" | cut -d' ' -f1)"; b="$(sha256sum "$WORK/id_vanilla_$cfg.bin" | cut -d' ' -f1)"
  [[ "$a" == "$b" ]] && R[identity_$cfg]="PASS $a" || R[identity_$cfg]="FAIL $a != $b"
done

python - "$OUT" <<EOF
import json, sys
r = {$(for k in "${!R[@]}"; do printf '"%s": "%s", ' "$k" "${R[$k]}"; done)}
r["ref"] = "$REF"
r["repo"] = "$REPO_URL"
r["vtm_provenance"] = open("third_party/VTM_PROVENANCE").read()
r["pass"] = (r["pytest"] != "FAIL" and r["vtm_tree"] == r["expected_tree"]
             and all(r[f"smoke_{c}"] == "PASS" for c in ("ai", "ldp", "ra"))
             and all(r[f"identity_{c}"].startswith("PASS") for c in ("ai", "ldp", "ra")))
json.dump(r, open(sys.argv[1], "w"), indent=2, sort_keys=True)
print(json.dumps(r, indent=2, sort_keys=True))
sys.exit(0 if r["pass"] else 1)
EOF
