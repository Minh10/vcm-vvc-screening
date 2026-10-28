"""Per-class (weighted) least-squares design of luma ALF coefficients.

For class c the filter output is rec + Phi g (g = f / 128). Minimising sum_n w_n (t_n - Phi_n g)^2 with
t = orig - rec gives the normal equations A g = b with A = sum w Phi Phi^T, b = sum w Phi t. Uniform weights
reproduce the classical Wiener (MSE) design used by VTM; non-uniform weights give the task-weighted design (O1-B).

Clipping: as in the VTM encoder, statistics are accumulated once for all 4 clipping indices of every coefficient
(a 48 x 48 matrix per class), so any clipping assignment can be evaluated without revisiting the pixels.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .spec import COEFF_MAX, COEFF_MIN, COEFF_SHIFT, NUM_CLASSES, NUM_COEFF, TRANSPOSE_IDX, _Padded, clip_values, \
    pixel_map, stripes, tap_differences

NCLIP = 4


@dataclass
class ClassStats:
    G: np.ndarray      # (48, 48) sum w x x^T over all (coefficient, clip) features
    b: np.ndarray      # (48,)   sum w x t
    e: float           # sum w t^2
    n: int             # number of pixels
    wsum: float

    def system(self, clip: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        idx = np.arange(NUM_COEFF) * NCLIP + np.asarray(clip)
        return self.G[np.ix_(idx, idx)], self.b[idx]


def collect_stats(rec: np.ndarray, orig: np.ndarray, cls: np.ndarray, transpose: np.ndarray, bitdepth: int,
                  weights: np.ndarray | None = None, mask: np.ndarray | None = None, ctu_size: int = 128,
                  virtual_boundary: bool = True) -> list[ClassStats]:
    """Accumulate per-class statistics. ``weights`` per pixel (default 1), ``mask`` selects pixels used."""
    rec = np.asarray(rec, dtype=np.int64)
    h, w = rec.shape
    t_all = (np.asarray(orig, dtype=np.int64) - rec).astype(np.float64)
    wt_all = np.ones((h, w)) if weights is None else np.asarray(weights, dtype=np.float64)
    use_all = np.ones((h, w), bool) if mask is None else np.asarray(mask, bool)
    cmap_all, tmap_all = pixel_map(cls), pixel_map(transpose)
    cvals = clip_values(bitdepth)
    P = _Padded(rec, 4)
    nf = NUM_COEFF * NCLIP
    G = np.zeros((NUM_CLASSES, nf, nf))
    B = np.zeros((NUM_CLASSES, nf))
    E = np.zeros(NUM_CLASSES)
    N = np.zeros(NUM_CLASSES, dtype=np.int64)
    W = np.zeros(NUM_CLASSES)

    for r0, r1 in stripes(h):
        diffs = tap_differences(rec, ctu_size, virtual_boundary, r0, r1, P)
        tmap, cmap = tmap_all[r0:r1], cmap_all[r0:r1]
        # X[y, x, j*4 + ci] = clipped pair sum for coefficient index j with clip index ci
        X = np.zeros((r1 - r0, w, nf))
        for k in range(NUM_COEFF):
            j = TRANSPOSE_IDX[tmap, k]
            for ci in range(NCLIP):
                c = cvals[ci]
                val = (np.clip(diffs[k, 0], -c, c) + np.clip(diffs[k, 1], -c, c)).astype(np.float64)
                np.put_along_axis(X, (j * NCLIP + ci)[..., None], val[..., None], axis=2)
        t, wt, use = t_all[r0:r1], wt_all[r0:r1], use_all[r0:r1]
        for c in np.unique(cmap[use]):
            sel = (cmap == c) & use
            Xc, tc, wc = X[sel], t[sel], wt[sel]
            Xw = Xc * wc[:, None]
            G[c] += Xw.T @ Xc
            B[c] += Xw.T @ tc
            E[c] += float(np.sum(wc * tc * tc))
            N[c] += int(sel.sum())
            W[c] += float(wc.sum())
    return [ClassStats(G=G[c], b=B[c], e=float(E[c]), n=int(N[c]), wsum=float(W[c])) for c in range(NUM_CLASSES)]


def _solve(A: np.ndarray, b: np.ndarray, ridge: float) -> np.ndarray:
    reg = ridge * (np.trace(A) / len(A) + 1e-12)
    return np.linalg.solve(A + reg * np.eye(len(A)), b)


def weighted_error(s: ClassStats, clip: np.ndarray, g: np.ndarray) -> float:
    A, b = s.system(clip)
    return float(s.e - 2 * b @ g + g @ A @ g)


def design_class(s: ClassStats, ridge: float = 1e-6, search_clip: bool = True, max_rounds: int = 3
                 ) -> tuple[np.ndarray, np.ndarray, float]:
    """Return (g real coefficients /128 units removed, clip indices, weighted error) for one class."""
    clip = np.zeros(NUM_COEFF, dtype=np.int64)
    if s.n == 0 or s.wsum == 0:
        return np.zeros(NUM_COEFF), clip, 0.0
    A, b = s.system(clip)
    g = _solve(A, b, ridge)
    best = weighted_error(s, clip, g)
    if search_clip:
        for _ in range(max_rounds):
            improved = False
            for j in range(NUM_COEFF):
                for ci in range(NCLIP):
                    if ci == clip[j]:
                        continue
                    trial = clip.copy()
                    trial[j] = ci
                    A, b = s.system(trial)
                    gt = _solve(A, b, ridge)
                    err = weighted_error(s, trial, gt)
                    if err < best - 1e-9 * max(1.0, abs(best)):
                        best, clip, g, improved = err, trial, gt, True
            if not improved:
                break
    return g, clip, best


def quantize(g: np.ndarray, s: ClassStats | None = None, clip: np.ndarray | None = None, refine: bool = True
             ) -> np.ndarray:
    """Integer coefficients with 7 fractional bits in [COEFF_MIN, COEFF_MAX]; optional ±1 coordinate refinement
    of the weighted quadratic error (as the VTM encoder does after rounding)."""
    f = np.clip(np.rint(np.asarray(g) * (1 << COEFF_SHIFT)), COEFF_MIN, COEFF_MAX).astype(np.int64)
    if not refine or s is None or s.n == 0:
        return f
    scale = 1.0 / (1 << COEFF_SHIFT)
    err = weighted_error(s, clip, f * scale)
    improved = True
    while improved:
        improved = False
        for j in range(NUM_COEFF):
            for step in (-1, 1):
                cand = f.copy()
                cand[j] = np.clip(cand[j] + step, COEFF_MIN, COEFF_MAX)
                e2 = weighted_error(s, clip, cand * scale)
                if e2 < err - 1e-9:
                    f, err, improved = cand, e2, True
    return f


def design(stats: list[ClassStats], ridge: float = 1e-6, search_clip: bool = True
           ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Design all 25 classes. Returns (integer coeff (25, 12), clip_idx (25, 12), real coeff g (25, 12))."""
    coeff = np.zeros((NUM_CLASSES, NUM_COEFF), dtype=np.int64)
    clip = np.zeros((NUM_CLASSES, NUM_COEFF), dtype=np.int64)
    real = np.zeros((NUM_CLASSES, NUM_COEFF))
    for c, s in enumerate(stats):
        g, ci, _ = design_class(s, ridge, search_clip)
        real[c], clip[c] = g, ci
        coeff[c] = quantize(g, s, ci)
    return coeff, clip, real
