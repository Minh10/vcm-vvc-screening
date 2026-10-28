"""Reference VVC luma ALF classification and filtering (numpy, integer arithmetic).

Written against VTM-24.0 (commit ca331de230f27e0489df9d2fa6c006e2dcd2ed89):
``source/Lib/CommonLib/AdaptiveLoopFilter.cpp`` — ``deriveClassificationBlk`` (classification) and
``filterBlk<ALF_FILTER_7>`` (filtering), including the ALF virtual boundary (VB) 4 luma rows above each CTU row
boundary. Picture borders use replicate padding (VTM extends the picture border before ALF).

Not modelled: slice / tile / subpicture / PPS virtual boundaries (none in the VCM CTC configurations).
Bit-exactness against VTM is checked with the ALF dump hook (docs/ALF_CODEC_AUDIT.md).
"""

from __future__ import annotations

import numpy as np

NUM_CLASSES = 25
NUM_COEFF = 12
COEFF_SHIFT = 7                      # COEFF_SCALE_BITS
COEFF_MIN, COEFF_MAX = -128, 127     # AlfCoeff range for signalled luma coefficients (checked in the audit)
VB_ROWS_ABOVE = 4                    # ALF_VB_POS_ABOVE_CTUROW_LUMA

# Tap pairs of the 7x7 diamond, k = 0..11, as (dx, dy); the mirror tap is (-dx, -dy).
TAPS = [(0, 3), (1, 2), (0, 2), (-1, 2), (2, 1), (1, 1), (0, 1), (-1, 1), (-2, 1), (3, 0), (2, 0), (1, 0)]

# filterCoeff[k] = coef[TRANSPOSE_IDX[transposeIdx][k]]
TRANSPOSE_IDX = np.array([
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
    [9, 4, 10, 8, 1, 5, 11, 7, 3, 0, 2, 6],
    [0, 3, 2, 1, 8, 7, 6, 5, 4, 9, 10, 11],
    [9, 8, 10, 4, 3, 7, 11, 5, 1, 0, 2, 6],
])
TRANSPOSE_TABLE = np.array([0, 1, 0, 2, 2, 3, 1, 3])
VAR_TAB = np.array([0, 1, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 3, 3, 3, 4])


def clip_values(bitdepth: int) -> np.ndarray:
    """m_alfClippingValues[LUMA]: [1 << bd, 1 << (bd - 3), 1 << (bd - 5), 1 << (bd - 7)]."""
    shift = bitdepth - 8
    return np.array([1 << bitdepth] + [1 << (7 - 2 * i + shift) for i in (1, 2, 3)], dtype=np.int64)


class _Padded:
    """Picture with replicate padding; ``at(rows, cols)`` takes absolute (possibly negative) coordinates."""

    def __init__(self, rec: np.ndarray, pad: int):
        self.pad = pad
        self.p = np.pad(np.asarray(rec, dtype=np.int64), pad, mode="edge")

    def at(self, rows, cols):
        return self.p[np.asarray(rows)[:, None] + self.pad, np.asarray(cols)[None, :] + self.pad]


def classify(rec: np.ndarray, bitdepth: int, ctu_size: int = 128, virtual_boundary: bool = True
             ) -> tuple[np.ndarray, np.ndarray]:
    """Return (class_idx, transpose_idx) per 4x4 block, shapes (H/4, W/4). H and W must be multiples of 4."""
    rec = np.asarray(rec, dtype=np.int64)
    h, w = rec.shape
    if h % 4 or w % 4:
        raise ValueError("luma size must be a multiple of 4 (VTM pads to the minimum CU size)")
    P = _Padded(rec, 8)
    vb = ctu_size - VB_ROWS_ABOVE if virtual_boundary else None
    mask_ctu = ctu_size - 1

    # Row pairs start at every even row y in [-2, h + 4]; pair = Laplacians at (y, even x) and (y+1, odd x).
    ys = np.arange(-2, h + 6, 2)
    xe = np.arange(-2, w + 6, 2)          # even columns for the first row of the pair
    lap = {k: np.zeros((len(ys), len(xe)), dtype=np.int64) for k in ("v", "h", "d0", "d1")}
    for r, y in enumerate(ys):
        up0, dn1 = y - 1, y + 2          # neighbours used by row y (above) and row y+1 (below)
        if vb is not None and y > 0 and (y & mask_ctu) == vb - 2:
            dn1 = y + 1                  # src3 = src2: row y+2 is beyond the VB for row y+1
        elif vb is not None and y > 0 and (y & mask_ctu) == vb:
            up0 = y                      # src0 = src1: row y-1 is above the VB for row y
        a = P.at([y], xe)[0]
        a_up, a_dn = P.at([up0], xe)[0], P.at([y + 1], xe)[0]
        a_ul, a_ur = P.at([up0], xe - 1)[0], P.at([up0], xe + 1)[0]
        a_dl, a_dr = P.at([y + 1], xe - 1)[0], P.at([y + 1], xe + 1)[0]
        a_l, a_r = P.at([y], xe - 1)[0], P.at([y], xe + 1)[0]
        xo = xe + 1
        b = P.at([y + 1], xo)[0]
        b_up, b_dn = P.at([y], xo)[0], P.at([dn1], xo)[0]
        b_ul, b_ur = P.at([y], xo - 1)[0], P.at([y], xo + 1)[0]
        b_dl, b_dr = P.at([dn1], xo - 1)[0], P.at([dn1], xo + 1)[0]
        b_l, b_r = P.at([y + 1], xo - 1)[0], P.at([y + 1], xo + 1)[0]
        lap["v"][r] = np.abs(2 * a - a_up - a_dn) + np.abs(2 * b - b_up - b_dn)
        lap["h"][r] = np.abs(2 * a - a_l - a_r) + np.abs(2 * b - b_l - b_r)
        lap["d0"][r] = np.abs(2 * a - a_ul - a_dr) + np.abs(2 * b - b_ul - b_dr)
        lap["d1"][r] = np.abs(2 * a - a_dl - a_ur) + np.abs(2 * b - b_dl - b_ur)

    hb, wb = h // 4, w // 4
    by = np.arange(hb) * 4
    # column window [-2, 5] = 4 consecutive even-column entries starting at x0 - 2  -> indices x0/2 .. x0/2 + 3
    col = {k: v[:, 0:2 * wb:2] + v[:, 1:2 * wb + 1:2] + v[:, 2:2 * wb + 2:2] + v[:, 3:2 * wb + 3:2]
           for k, v in lap.items()}
    # row pairs for block origin y0: indices of ys == y0-2, y0, y0+2, y0+4  ->  y0/2 + 0..3
    sums = {}
    yv = by & mask_ctu
    use0 = np.ones(hb, bool) if vb is None else (yv != vb)          # drop pair y0-2 when y0 is at the VB
    use3 = np.ones(hb, bool) if vb is None else (yv != vb - 4)      # drop pair y0+4 when y0 = VB - 4
    for k, v in col.items():
        i0 = by // 2
        sums[k] = (v[i0] * use0[:, None] + v[i0 + 1] + v[i0 + 2] + v[i0 + 3] * use3[:, None])
    s_v, s_h, s_d0, s_d1 = sums["v"], sums["h"], sums["d0"], sums["d1"]

    ac = np.where(((yv == vb - 4) | (yv == vb))[:, None], 96, 64) if vb is not None else 64
    act = np.clip(((s_v + s_h) * ac) >> (bitdepth + 4), 0, 15)
    cls = VAR_TAB[act]

    v_first = s_v > s_h
    hv1, hv0 = np.where(v_first, s_v, s_h), np.where(v_first, s_h, s_v)
    dir_hv = np.where(v_first, 1, 3)
    d_first = s_d0 > s_d1
    d1, d0 = np.where(d_first, s_d0, s_d1), np.where(d_first, s_d1, s_d0)
    dir_d = np.where(d_first, 0, 2)
    diag = d1 * hv0 > hv1 * d0
    hvd1, hvd0 = np.where(diag, d1, hv1), np.where(diag, d0, hv0)
    main, second = np.where(diag, dir_d, dir_hv), np.where(diag, dir_hv, dir_d)
    strength = np.where(hvd1 * 2 > 9 * hvd0, 2, np.where(hvd1 > 2 * hvd0, 1, 0))
    cls = cls + np.where(strength != 0, (((main & 1) << 1) + strength) * 5, 0)
    transpose = TRANSPOSE_TABLE[main * 2 + (second >> 1)]
    return cls.astype(np.int64), transpose.astype(np.int64)


def pixel_map(block_map: np.ndarray) -> np.ndarray:
    return np.repeat(np.repeat(block_map, 4, axis=0), 4, axis=1)


def _row_limit(h: int, ctu_size: int, virtual_boundary: bool) -> np.ndarray:
    """Max |dy| allowed per picture row by the VB (3 = unrestricted)."""
    lim = np.full(h, 3, dtype=np.int64)
    if virtual_boundary:
        vb = ctu_size - VB_ROWS_ABOVE
        yv = np.arange(h) & (ctu_size - 1)
        above = (yv < vb) & (yv >= vb - 4)
        below = (yv >= vb) & (yv <= vb + 3)
        lim[above] = np.minimum(3, vb - 1 - yv[above])
        lim[below] = np.minimum(3, yv[below] - vb)
    return lim


STRIPE = 64   # rows processed at a time, to bound memory on large pictures


def tap_differences(rec: np.ndarray, ctu_size: int = 128, virtual_boundary: bool = True, row0: int = 0,
                    row1: int | None = None, padded: _Padded | None = None) -> np.ndarray:
    """(12, 2, R, W) for picture rows [row0, row1): neighbour − centre for both samples of each tap pair,
    with the VB-aware vertical clamping of VTM."""
    rec = np.asarray(rec, dtype=np.int64)
    h, w = rec.shape
    row1 = h if row1 is None else row1
    P = padded if padded is not None else _Padded(rec, 4)
    lim = _row_limit(h, ctu_size, virtual_boundary)[row0:row1]
    rows, cols = np.arange(row0, row1), np.arange(w)
    centre = rec[row0:row1]
    out = np.empty((NUM_COEFF, 2, row1 - row0, w), dtype=np.int64)
    for k, (dx, dy) in enumerate(TAPS):
        dyc = np.minimum(abs(dy), lim) * np.sign(dy)                    # per-row clamped vertical offset
        out[k, 0] = P.p[(rows + dyc)[:, None] + P.pad, (cols + dx)[None, :] + P.pad] - centre
        out[k, 1] = P.p[(rows - dyc)[:, None] + P.pad, (cols - dx)[None, :] + P.pad] - centre
    return out


def stripes(h: int, size: int = STRIPE):
    for r0 in range(0, h, size):
        yield r0, min(h, r0 + size)


def design_matrix(rec: np.ndarray, cls: np.ndarray, transpose: np.ndarray, clip_idx: np.ndarray, bitdepth: int,
                  ctu_size: int = 128, virtual_boundary: bool = True, row0: int = 0, row1: int | None = None,
                  padded: _Padded | None = None) -> np.ndarray:
    """Phi (12, R, W) for rows [row0, row1): Phi[j] = clipped pair sum of the tap whose coefficient index is j.

    ``clip_idx`` (25, 12): clipping index per class and coefficient index."""
    h, w = rec.shape
    row1 = h if row1 is None else row1
    cmap, tmap = pixel_map(cls)[row0:row1], pixel_map(transpose)[row0:row1]
    cvals = clip_values(bitdepth)[np.asarray(clip_idx)]
    diffs = tap_differences(rec, ctu_size, virtual_boundary, row0, row1, padded)
    phi = np.zeros((NUM_COEFF, row1 - row0, w), dtype=np.int64)
    for k in range(NUM_COEFF):
        j = TRANSPOSE_IDX[tmap, k]
        c = cvals[cmap, j]
        val = np.clip(diffs[k, 0], -c, c) + np.clip(diffs[k, 1], -c, c)
        np.put_along_axis(phi, j[None], np.take_along_axis(phi, j[None], 0) + val[None], 0)
    return phi


def rounding_shift(h: int, ctu_size: int = 128, virtual_boundary: bool = True) -> np.ndarray:
    """Per-row output shift: 7, or 10 on the two rows adjacent to the VB."""
    s = np.full(h, COEFF_SHIFT, dtype=np.int64)
    if virtual_boundary:
        vb = ctu_size - VB_ROWS_ABOVE
        yv = np.arange(h) & (ctu_size - 1)
        s[(yv == vb - 1) | (yv == vb)] = COEFF_SHIFT + 3
    return s


def apply(rec: np.ndarray, cls: np.ndarray, transpose: np.ndarray, coeff: np.ndarray, clip_idx: np.ndarray,
          bitdepth: int, enabled: np.ndarray | None = None, ctu_size: int = 128,
          virtual_boundary: bool = True) -> np.ndarray:
    """Filter a luma picture. ``coeff`` (25, 12) integers, ``clip_idx`` (25, 12) in 0..3,
    ``enabled`` optional per-pixel mask (CTB on/off)."""
    rec = np.asarray(rec, dtype=np.int64)
    P = _Padded(rec, 4)
    coeff = np.asarray(coeff, dtype=np.int64)
    cmap = pixel_map(cls)
    sh_all = rounding_shift(rec.shape[0], ctu_size, virtual_boundary)
    out = np.empty_like(rec)
    for r0, r1 in stripes(rec.shape[0]):
        phi = design_matrix(rec, cls, transpose, clip_idx, bitdepth, ctu_size, virtual_boundary, r0, r1, P)
        s = np.einsum("jhw,hwj->hw", phi, coeff[cmap[r0:r1]])
        sh = sh_all[r0:r1, None]
        out[r0:r1] = np.clip(rec[r0:r1] + ((s + (1 << (sh - 1))) >> sh), 0, (1 << bitdepth) - 1)
    return out if enabled is None else np.where(enabled, out, rec)
