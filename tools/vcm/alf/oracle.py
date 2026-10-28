"""O1-A: gradient-based relaxed oracle for luma ALF coefficients (outside the codec).

The ALF is differentiable in its coefficients: out = rec + sum_j Phi_j * g[class, j] with Phi from
``spec.design_matrix`` (clipping indices fixed). We optimise g (25 x 12, real-valued, no rounding) for a task
loss on the decoded picture, with the decoded chroma held fixed.

The result is a **relaxed, approximate oracle**, not a guaranteed upper bound: it relaxes the codec (real-valued
coefficients, no APS cost, no effect on reference pictures) but also restricts it (one filter set per picture on
every CTB, fixed clipping indices; no per-CTB on/off or APS choice) and the optimisation is local. It can be worse
than the anchor's real ALF output and must never be reported as a codec result (docs/RESEARCH_PLAN.md, O1-A).
Losses use the detector's outputs on the *original* frame as targets (pseudo-labels), never test ground truth.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from . import spec

_MATRICES = {"bt709": (0.2126, 0.0722), "bt601": (0.299, 0.114)}


def yuv_to_rgb(y, u, v, bitdepth: int, matrix: str = "bt709", full_range: bool = False):
    """Differentiable 4:2:0 -> RGB in [0, 1] (torch), same convention as ``vcm.yuv.to_rgb`` without rounding."""
    import torch

    kr, kb = _MATRICES[matrix]
    kg = 1.0 - kr - kb
    scale = float(1 << (bitdepth - 8))
    u, v = u.to(y.dtype), v.to(y.dtype)
    uu = u.repeat_interleave(2, 0).repeat_interleave(2, 1)
    vv = v.repeat_interleave(2, 0).repeat_interleave(2, 1)
    yf, uf, vf = y / scale, uu / scale, vv / scale
    if full_range:
        yn, un, vn = yf / 255.0, (uf - 128.0) / 255.0, (vf - 128.0) / 255.0
    else:
        yn, un, vn = (yf - 16.0) / 219.0, (uf - 128.0) / 224.0, (vf - 128.0) / 224.0
    r = yn + 2.0 * (1.0 - kr) * vn
    b = yn + 2.0 * (1.0 - kb) * un
    g = (yn - kr * r - kb * b) / kg
    return torch.stack([r, g, b]).clamp(0.0, 1.0)


class DifferentiableALF:
    def __init__(self, rec: np.ndarray, cls: np.ndarray, transpose: np.ndarray, bitdepth: int,
                 clip_idx: np.ndarray | None = None, ctu_size: int = 128, virtual_boundary: bool = True):
        import torch

        clip = np.zeros((spec.NUM_CLASSES, spec.NUM_COEFF), int) if clip_idx is None else clip_idx
        h = rec.shape[0]
        phi = np.concatenate([spec.design_matrix(rec, cls, transpose, clip, bitdepth, ctu_size, virtual_boundary,
                                                 r0, r1) for r0, r1 in spec.stripes(h)], axis=1)
        shift = spec.rounding_shift(h, ctu_size, virtual_boundary)
        # on VB-adjacent rows the sum is divided by 2^10 instead of 2^7: scale Phi so g keeps one meaning
        self.phi = torch.tensor(phi * (2.0 ** (spec.COEFF_SHIFT - shift))[None, :, None], dtype=torch.float32)
        self.rec = torch.tensor(rec, dtype=torch.float32)
        self.cmap = torch.tensor(spec.pixel_map(cls), dtype=torch.long)
        self.maxval = float((1 << bitdepth) - 1)

    def __call__(self, g):
        """g: (25, 12) tensor of real coefficients in units of 1 (i.e. integer coefficient / 128)."""
        gp = g[self.cmap]                                   # (H, W, 12)
        out = self.rec + (self.phi.permute(1, 2, 0) * gp).sum(-1)
        return out.clamp(0.0, self.maxval)


def optimise(alf: DifferentiableALF, u: np.ndarray, v: np.ndarray, bitdepth: int,
             loss_fn: Callable, steps: int = 200, lr: float = 0.002, init: np.ndarray | None = None,
             limit: float = 127 / 128) -> tuple[np.ndarray, list[float]]:
    """Minimise ``loss_fn(rgb (1, 3, H, W) in [0, 1])`` over g, starting from ``init`` (e.g. the anchor's own ALF
    coefficients / 128) or zero. Coefficients stay within the signalled range (|g| <= 127/128).

    Returns the **best** iterate seen (never worse than the start) and the loss history (history[0] = start)."""
    import torch

    g = torch.zeros(spec.NUM_CLASSES, spec.NUM_COEFF) if init is None else torch.tensor(init, dtype=torch.float32)
    g = g.clamp(-1.0, limit).requires_grad_(True)
    ut, vt = torch.tensor(u, dtype=torch.float32), torch.tensor(v, dtype=torch.float32)
    opt = torch.optim.Adam([g], lr=lr)
    hist, best_loss, best_g = [], float("inf"), g.detach().clone()
    for _ in range(steps + 1):
        opt.zero_grad()
        loss = loss_fn(yuv_to_rgb(alf(g), ut, vt, bitdepth)[None])
        val = float(loss.detach())
        hist.append(val)
        if val < best_loss:
            best_loss, best_g = val, g.detach().clone()
        if len(hist) > steps:
            break
        loss.backward()
        opt.step()
        with torch.no_grad():
            g.clamp_(-1.0, limit)
    return best_g.numpy().astype(np.float64), hist


def feature_loss(feature_fn: Callable, target_rgb):
    """||f(x_hat) - f(x)||^2 summed over feature levels, targets computed once from the original frame."""
    import torch

    with torch.no_grad():
        ref = feature_fn(target_rgb)
        ref = [r.detach() for r in (ref if isinstance(ref, (list, tuple)) else [ref])]

    def loss(rgb):
        out = feature_fn(rgb)
        out = out if isinstance(out, (list, tuple)) else [out]
        return sum(torch.mean((o - r) ** 2) for o, r in zip(out, ref))

    return loss


def torchvision_detection_loss(model, boxes: np.ndarray, labels: np.ndarray):
    """Sum of torchvision detection training losses against pseudo-label boxes (xyxy) / labels.

    The model is put in train mode only to obtain losses; its weights are not updated (only g is optimised)."""
    import torch

    model.train()
    for p in model.parameters():
        p.requires_grad_(False)
    target = [{"boxes": torch.tensor(np.asarray(boxes, np.float32).reshape(-1, 4)),
               "labels": torch.tensor(np.asarray(labels, np.int64).reshape(-1))}]

    def loss(rgb):
        losses = model([rgb[0]], target)
        return sum(losses.values())

    return loss
