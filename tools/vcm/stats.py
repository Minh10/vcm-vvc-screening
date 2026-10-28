"""Sequence-level paired statistics.

The statistical unit is the video sequence. Callers pass one value per sequence for the method and for the
control (e.g. per-sequence BD-rate, Spearman rho, or regret); CTU- or frame-level samples must be aggregated
per sequence before they reach this module.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from itertools import product

import numpy as np


@dataclass
class PairedResult:
    sequences: list[str]
    diffs: np.ndarray            # method − control, one per sequence
    estimate: float              # statistic of diffs (median by default)
    ci: tuple[float, float]
    p_value: float               # two-sided sign-flip permutation test on the mean difference

    def summary(self) -> str:
        lo, hi = self.ci
        return (f"n={len(self.sequences)}  estimate={self.estimate:+.4f}  "
                f"CI=[{lo:+.4f}, {hi:+.4f}]  p={self.p_value:.4g}")


def align(method: Mapping[str, float], control: Mapping[str, float]) -> tuple[list[str], np.ndarray]:
    """Return sorted sequence names and method − control differences. Sequence sets must match exactly."""
    if set(method) != set(control):
        missing = sorted(set(method) ^ set(control))
        raise ValueError(f"method and control must cover the same sequences; mismatched: {missing}")
    names = sorted(method)
    diffs = np.array([method[s] - control[s] for s in names], dtype=float)
    if not np.all(np.isfinite(diffs)):
        bad = [s for s, d in zip(names, diffs) if not np.isfinite(d)]
        raise ValueError(f"non-finite per-sequence values (e.g. invalid BD-rate) for: {bad}")
    return names, diffs


def sign_flip_pvalue(diffs, n_resamples: int = 10_000, seed: int = 0, exact_max_n: int = 16) -> float:
    """Two-sided paired permutation (sign-flip) test of mean(diffs) == 0.

    Enumerates all 2^n sign patterns when n <= exact_max_n, otherwise uses Monte Carlo with the
    (count + 1) / (resamples + 1) correction.
    """
    d = np.asarray(diffs, dtype=float)
    n = len(d)
    if n == 0:
        raise ValueError("need at least one sequence")
    observed = abs(d.mean())
    tol = 1e-12 * max(1.0, observed)
    if n <= exact_max_n:
        signs = np.array(list(product((1.0, -1.0), repeat=n)))
        stats = np.abs((signs * d).mean(axis=1))
        return float(np.mean(stats >= observed - tol))
    rng = np.random.default_rng(seed)
    signs = rng.choice((1.0, -1.0), size=(n_resamples, n))
    stats = np.abs((signs * d).mean(axis=1))
    return float((np.sum(stats >= observed - tol) + 1) / (n_resamples + 1))


def bootstrap_ci(diffs, statistic: Callable[[np.ndarray], float] = np.median, n_resamples: int = 10_000,
                 level: float = 0.95, seed: int = 0) -> tuple[float, float]:
    """Percentile bootstrap CI, resampling sequences with replacement."""
    d = np.asarray(diffs, dtype=float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(d), size=(n_resamples, len(d)))
    boot = np.array([statistic(d[row]) for row in idx])
    alpha = (1.0 - level) / 2.0
    return float(np.quantile(boot, alpha)), float(np.quantile(boot, 1.0 - alpha))


def paired_test(method: Mapping[str, float], control: Mapping[str, float],
                statistic: Callable[[np.ndarray], float] = np.median, n_resamples: int = 10_000,
                level: float = 0.95, seed: int = 0) -> PairedResult:
    names, diffs = align(method, control)
    return PairedResult(
        sequences=names,
        diffs=diffs,
        estimate=float(statistic(diffs)),
        ci=bootstrap_ci(diffs, statistic, n_resamples, level, seed),
        p_value=sign_flip_pvalue(diffs, n_resamples, seed),
    )


def holm(p_values) -> np.ndarray:
    """Holm–Bonferroni adjusted p-values, returned in the input order."""
    p = np.asarray(p_values, dtype=float)
    m = len(p)
    order = np.argsort(p)
    adjusted = np.empty(m)
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * p[i]))
        adjusted[i] = running
    return adjusted
