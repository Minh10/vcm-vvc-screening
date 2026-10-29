"""Per-pixel task weights for the weighted Wiener design (O1-B).

Two estimators, both computed on the encoder side from the *original* frame only:

- ``box_weights``: background weight ``bg`` plus detector-score coverage of pseudo-label boxes (ROI weighting),
  with the controls of O1-B (``roi_weights``): ``continuous`` (score coverage), ``binary`` (1 inside any box),
  ``shuffled`` (the continuous map cyclically shifted by one offset per sequence and seed: a pixel permutation, so
  the weight distribution of every picture is *identical* and its temporal coherence is kept, only the alignment
  with the objects is destroyed) and ``uniform`` (all ones: must reproduce the default ALF bitstream exactly);
- ``hutchinson_luma``: diag(J^T J) of a feature extractor w.r.t. the luma plane, estimated with Rademacher
  probes (E[(J^T r)_i^2] = (J^T J)_ii). This is the FP-RDO / IDSE-style sensitivity, used here only as a weight.
"""

from __future__ import annotations

import numpy as np


def box_weights(boxes: np.ndarray, scores: np.ndarray, height: int, width: int, bg: float = 0.1,
                score_threshold: float = 0.3) -> np.ndarray:
    """``boxes`` (N, 4) xyxy in luma pixels. Returns weights in [bg, 1]."""
    cov = np.zeros((height, width))
    for (x0, y0, x1, y1), s in zip(np.asarray(boxes).reshape(-1, 4), np.asarray(scores).reshape(-1)):
        if s < score_threshold:
            continue
        xa, ya = max(0, int(np.floor(x0))), max(0, int(np.floor(y0)))
        xb, yb = min(width, int(np.ceil(x1))), min(height, int(np.ceil(y1)))
        if xb > xa and yb > ya:
            cov[ya:yb, xa:xb] += s
    return bg + (1.0 - bg) * np.minimum(cov, 1.0)


ROI_MODES = ("continuous", "binary", "shuffled", "uniform")


def roi_mask(boxes: np.ndarray, scores: np.ndarray, height: int, width: int, score_threshold: float = 0.3
             ) -> np.ndarray:
    """Pixels covered by at least one box with score >= threshold."""
    return box_weights(boxes, scores, height, width, 0.0, score_threshold) > 0


def choose_shift(masks: list[np.ndarray], height: int, width: int, rng: np.random.Generator, factor: int = 4,
                 max_tries: int = 1000) -> dict:
    """One cyclic offset (dy, dx), multiple of ``factor``, for a whole sequence.

    ``masks`` are ROI masks sub-sampled by ``factor`` (``mask[::factor, ::factor]``). Offsets are drawn uniformly;
    the first whose ROI self-overlap (share of shifted-ROI pixels that land on the true ROI, pooled over pictures)
    is at most the chance level (mean ROI area fraction) is accepted — the shifted map is then no better aligned
    with the objects than a random placement. If none is found in ``max_tries`` draws, the least-overlapping one."""
    total = sum(int(m.sum()) for m in masks)
    if total == 0:
        return {"dy": 0, "dx": 0, "overlap": None, "chance": 0.0, "tries": 0, "accepted": True}
    chance = total / sum(m.size for m in masks)
    best = None
    for t in range(1, max_tries + 1):
        dy = int(rng.integers(0, max(1, height // factor))) * factor
        dx = int(rng.integers(0, max(1, width // factor))) * factor
        hit = sum(int(np.logical_and(np.roll(m, (dy // factor, dx // factor), axis=(0, 1)), m).sum()) for m in masks)
        ov = hit / total
        if best is None or ov < best["overlap"]:
            best = {"dy": dy, "dx": dx, "overlap": ov, "chance": chance, "tries": t, "accepted": ov <= chance}
        if ov <= chance:
            return best
    return best


def roi_weights(mode: str, boxes: np.ndarray, scores: np.ndarray, height: int, width: int, bg: float = 0.1,
                score_threshold: float = 0.3, shift: tuple[int, int] = (0, 0)) -> np.ndarray:
    """Weight map of one O1-B arm (see module docstring); not normalised. ``shift`` = (dy, dx) of the shuffled arm."""
    boxes = np.asarray(boxes, float).reshape(-1, 4)
    scores = np.asarray(scores, float).reshape(-1)
    if mode == "continuous":
        return box_weights(boxes, scores, height, width, bg, score_threshold)
    if mode == "binary":
        keep = scores >= score_threshold
        return box_weights(boxes[keep], np.ones(int(keep.sum())), height, width, bg, 0.0)
    if mode == "shuffled":
        return np.roll(box_weights(boxes, scores, height, width, bg, score_threshold), shift, axis=(0, 1))
    if mode == "uniform":
        return np.ones((height, width))
    raise ValueError(f"unknown ROI weight mode {mode!r}")


def hutchinson_luma(feature_fn, y: np.ndarray, u: np.ndarray, v: np.ndarray, bitdepth: int, samples: int = 4,
                    seed: int = 0, normalise: bool = True) -> np.ndarray:
    """Estimate diag(J^T J) w.r.t. luma samples. ``feature_fn`` maps a (1, 3, H, W) float RGB tensor in [0, 1]
    to a tensor or a list/tuple of tensors (several feature levels are concatenated)."""
    import torch

    from .oracle import yuv_to_rgb

    gen = torch.Generator().manual_seed(seed)
    yt = torch.tensor(np.asarray(y, dtype=np.float32), requires_grad=True)
    ut = torch.tensor(np.asarray(u, dtype=np.float32))
    vt = torch.tensor(np.asarray(v, dtype=np.float32))
    acc = torch.zeros_like(yt)
    for _ in range(samples):
        feats = feature_fn(yuv_to_rgb(yt, ut, vt, bitdepth)[None])
        feats = feats if isinstance(feats, (list, tuple)) else [feats]
        probe = sum((torch.randint(0, 2, f.shape, generator=gen).float() * 2 - 1).mul(f).sum() for f in feats)
        (g,) = torch.autograd.grad(probe, yt)
        acc += g.detach() ** 2
    d = (acc / samples).numpy().astype(np.float64)
    if normalise and d.mean() > 0:
        d = d / d.mean()
    return d
