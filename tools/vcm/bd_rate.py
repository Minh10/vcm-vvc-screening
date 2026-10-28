"""Bjøntegaard-delta metrics for rate–task curves.

Machine-task curves (mAP, MOTA vs. bitrate) are often non-monotone. This module applies one fixed,
pre-registered rule instead of ad-hoc curve fixing:

1. Each curve is reduced to its Pareto front: points sorted by rate, keeping a point only if its quality
   is strictly higher than every lower-rate point.
2. If a reduced curve has fewer than ``min_points`` points, the result is NaN with a reason.
3. Integration runs over the common interval of both reduced curves only.

Interpolation is piecewise cubic Hermite (PCHIP) of log10(rate) against quality (BD-rate) or of quality
against log10(rate) (BD-quality).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.interpolate import PchipInterpolator


@dataclass
class BDResult:
    value: float                      # BD-rate in percent, or BD-quality in quality units
    interval: tuple[float, float] | None
    points_used: tuple[int, int]      # (anchor, test) after Pareto reduction
    dropped: tuple[list[int], list[int]] = field(default_factory=lambda: ([], []))
    reason: str = ""

    @property
    def valid(self) -> bool:
        return bool(np.isfinite(self.value))


def pareto_front(rates, quality) -> tuple[np.ndarray, np.ndarray, list[int]]:
    """Return (rates, quality, dropped_indices) keeping only points that improve quality as rate grows."""
    r = np.asarray(rates, dtype=float)
    q = np.asarray(quality, dtype=float)
    if r.shape != q.shape or r.ndim != 1:
        raise ValueError("rates and quality must be 1-D arrays of equal length")
    if np.any(r <= 0):
        raise ValueError("rates must be positive")
    order = np.argsort(r, kind="stable")
    keep, dropped, best = [], [], -np.inf
    for i in order:
        if q[i] > best:
            keep.append(i)
            best = q[i]
        else:
            dropped.append(int(i))
    keep = np.array(keep, dtype=int)
    return r[keep], q[keep], sorted(dropped)


def _reduce(anchor_rates, anchor_quality, test_rates, test_quality, min_points):
    ra, qa, da = pareto_front(anchor_rates, anchor_quality)
    rt, qt, dt = pareto_front(test_rates, test_quality)
    used = (len(ra), len(rt))
    if min(used) < min_points:
        return None, used, (da, dt), f"fewer than {min_points} monotone points after Pareto reduction"
    return (ra, qa, rt, qt), used, (da, dt), ""


def bd_rate(anchor_rates, anchor_quality, test_rates, test_quality, min_points: int = 4) -> BDResult:
    """Average bitrate difference (%) of test vs. anchor at equal task quality. Negative = test saves bits."""
    reduced, used, dropped, reason = _reduce(anchor_rates, anchor_quality, test_rates, test_quality, min_points)
    if reduced is None:
        return BDResult(float("nan"), None, used, dropped, reason)
    ra, qa, rt, qt = reduced
    lo, hi = max(qa.min(), qt.min()), min(qa.max(), qt.max())
    if not hi > lo:
        return BDResult(float("nan"), None, used, dropped, "no overlapping quality interval")
    fa = PchipInterpolator(qa, np.log10(ra))
    ft = PchipInterpolator(qt, np.log10(rt))
    avg = (ft.integrate(lo, hi) - fa.integrate(lo, hi)) / (hi - lo)
    return BDResult(float((10.0 ** avg - 1.0) * 100.0), (float(lo), float(hi)), used, dropped)


def bd_quality(anchor_rates, anchor_quality, test_rates, test_quality, min_points: int = 4) -> BDResult:
    """Average task-quality difference (test − anchor) at equal bitrate, e.g. BD-mAP."""
    reduced, used, dropped, reason = _reduce(anchor_rates, anchor_quality, test_rates, test_quality, min_points)
    if reduced is None:
        return BDResult(float("nan"), None, used, dropped, reason)
    ra, qa, rt, qt = reduced
    la, lt = np.log10(ra), np.log10(rt)
    lo, hi = max(la.min(), lt.min()), min(la.max(), lt.max())
    if not hi > lo:
        return BDResult(float("nan"), None, used, dropped, "no overlapping rate interval")
    fa = PchipInterpolator(la, qa)
    ft = PchipInterpolator(lt, qt)
    avg = (ft.integrate(lo, hi) - fa.integrate(lo, hi)) / (hi - lo)
    return BDResult(float(avg), (float(10 ** lo), float(10 ** hi)), used, dropped)
