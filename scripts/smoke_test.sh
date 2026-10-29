#!/usr/bin/env bash
# P0 smoke test:
#   1. encode a few frames with the pinned VTM (ALF on by default in the VTM cfgs),
#   2. decode with the unmodified DecoderApp,
#   3. check encoder recon == decoder output (MD5),
#   4. encode again and check the bitstream is byte-identical (determinism).
# Usage: scripts/smoke_test.sh [cfg-name] [input.yuv width height frames]
#   cfg-name: ai | ldp | ra (default ldp). Without an input, a synthetic 416x240 clip is generated with ffmpeg.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${VTM_SRC:-$ROOT/third_party/VTM}"
CFG_NAME="${1:-ldp}"
case "$CFG_NAME" in
  ai)  CFG="$SRC/cfg/encoder_intra_vtm.cfg" ;;
  ldp) CFG="$SRC/cfg/encoder_lowdelay_P_vtm.cfg" ;;
  ra)  CFG="$SRC/cfg/encoder_randomaccess_vtm.cfg" ;;
  *) echo "unknown cfg: $CFG_NAME" >&2; exit 1 ;;
esac

find_bin() { find "$SRC/bin" -type f -name "$1*" -perm -u+x 2>/dev/null | head -1; }
ENC="$(find_bin EncoderApp)"; DEC="$(find_bin DecoderApp)"
[[ -x "$ENC" && -x "$DEC" ]] || { echo "Build VTM first (scripts/build_vtm.sh)" >&2; exit 1; }

OUT="${SMOKE_OUT:-$ROOT/results/p0/smoke_${CFG_NAME}}"
mkdir -p "$OUT"

if [[ $# -ge 5 ]]; then
  IN="$2"; W="$3"; H="$4"; N="$5"
else
  W=416; H=240; N=8
  IN="$OUT/synthetic_${W}x${H}.yuv"
  ffmpeg -loglevel error -y -f lavfi -i "testsrc2=size=${W}x${H}:rate=30" \
         -frames:v "$N" -pix_fmt yuv420p -f rawvideo "$IN"
fi

encode() {  # $1 = suffix
  "$ENC" -c "$CFG" -i "$IN" -wdt "$W" -hgt "$H" -fr 30 -f "$N" -q 37 \
         --InputBitDepth=8 --OutputBitDepth=8 \
         -b "$OUT/str_$1.bin" -o "$OUT/rec_$1.yuv" > "$OUT/enc_$1.log"
}

encode a
encode b
"$DEC" -b "$OUT/str_a.bin" -o "$OUT/dec_a.yuv" -d 8 > "$OUT/dec_a.log"

REC_MD5="$(md5sum "$OUT/rec_a.yuv" | cut -d' ' -f1)"
DEC_MD5="$(md5sum "$OUT/dec_a.yuv" | cut -d' ' -f1)"
SHA_A="$(sha256sum "$OUT/str_a.bin" | cut -d' ' -f1)"
SHA_B="$(sha256sum "$OUT/str_b.bin" | cut -d' ' -f1)"

echo "cfg:              $CFG_NAME"
echo "bitstream bytes:  $(stat -c %s "$OUT/str_a.bin")"
echo "recon md5 (enc):  $REC_MD5"
echo "recon md5 (dec):  $DEC_MD5"
echo "bitstream sha256: $SHA_A"

status=0
[[ "$REC_MD5" == "$DEC_MD5" ]] && echo "PASS decoder match" || { echo "FAIL decoder mismatch"; status=1; }
[[ "$SHA_A" == "$SHA_B" ]] && echo "PASS deterministic" || { echo "FAIL non-deterministic bitstream"; status=1; }
exit "$status"
