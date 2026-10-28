"""Per-pixel task weights for the weighted Wiener design (O1-B).

Two estimators, both computed on the encoder side from the *original* frame only:

- ``box_weights``: background weight ``bg`` plus detector-score coverage of pseudo-label boxes (ROI weighting),
  with the controls of O1-B (``roi_weights``): ``continuous`` (score coverage), ``binary`` (1 inside any box),
  ``shuffled`` (the same boxes moved to random positions: same weight budget, no alignment with objects) and
  ``uniform`` (all ones: must reproduce the default ALF bitstream exactly);
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


def relocate_boxes(boxes: np.ndarray, height: int, width: int, rng: np.random.Generator,
                   tries: int = 50) -> np.ndarray:
    """Move every box by a random *integer* offset to a uniformly random position inside the picture (its pixel
    footprint, hence the weight budget, is unchanged), avoiding overlap with all original boxes when possible
    (up to ``tries`` draws per box)."""
    boxes = np.asarray(boxes, float).reshape(-1, 4)
    out = boxes.copy()
    for i, (x0, y0, x1, y1) in enumerate(boxes):
        xa, ya = max(0, int(np.floor(x0))), max(0, int(np.floor(y0)))
        xb, yb = min(width, int(np.ceil(x1))), min(height, int(np.ceil(y1)))
        for _ in range(tries):
            dx = int(rng.integers(0, width - (xb - xa) + 1)) - xa
            dy = int(rng.integers(0, height - (yb - ya) + 1)) - ya
            cand = np.array([max(x0, xa) + dx, max(y0, ya) + dy, min(x1, xb) + dx, min(y1, yb) + dy])
            ox = np.minimum(cand[2], boxes[:, 2]) - np.maximum(cand[0], boxes[:, 0])
            oy = np.minimum(cand[3], boxes[:, 3]) - np.maximum(cand[1], boxes[:, 1])
            out[i] = cand
            if not np.any((ox > 0) & (oy > 0)):
                break
    return out


def roi_weights(mode: str, boxes: np.ndarray, scores: np.ndarray, height: int, width: int, bg: float = 0.1,
                score_threshold: float = 0.3, rng: np.random.Generator | None = None) -> np.ndarray:
    """Weight map of one O1-B arm (see module docstring); not normalised."""
    boxes = np.asarray(boxes, float).reshape(-1, 4)
    scores = np.asarray(scores, float).reshape(-1)
    if mode == "continuous":
        return box_weights(boxes, scores, height, width, bg, score_threshold)
    if mode == "binary":
        keep = scores >= score_threshold
        return box_weights(boxes[keep], np.ones(int(keep.sum())), height, width, bg, 0.0)
    if mode == "shuffled":
        keep = scores >= score_threshold
        moved = relocate_boxes(boxes[keep], height, width, rng or np.random.default_rng(0))
        return box_weights(moved, scores[keep], height, width, bg, 0.0)
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
