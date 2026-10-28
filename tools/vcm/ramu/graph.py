"""Build the CTU-level motion/reference-overlap graph from a baseline (first-pass) VTM trace.

Trace format (one row per final CU of the baseline encode, written by the VTM trace hook):

    poc, coding_order, temporal_id, x, y, w, h, qp, mode, ref_poc0, mv0x, mv0y, ref_poc1, mv1x, mv1y, resid_energy,
    flags, mv_spread, ref_mixed

- ``mode`` is one of ``intra``, ``inter``, ``skip`` (skip = inter with no residual).
- ``ref_pocN = -1`` when list N is unused. MVs are in **luma samples** (the hook divides VTM's internal 1/16 units)
  and are read from the picture's stored motion field at the CU **centre** (for affine/GEO/sub-block CUs this is
  the translational approximation; for translational CUs it is exact).
- ``flags``: ``|``-separated tools of the CU (``affine4``, ``affine6``, ``geo``, ``ciip``, ``mmvd``, ``ibc``,
  ``plt``); ``mv_spread``: max |4x4 sub-block MV − centre MV| in luma samples (L-inf); ``ref_mixed``: 4x4
  sub-blocks whose reference/list usage differs from the centre (GEO with two references).
- ``coding_order`` is the frame's position in decoding order.

Coverage. The overlap model is exact (up to interpolation taps) only for translational CUs. A CU is
**approximate** when it is GEO, has ``mv_spread`` > ``spread_tol`` (affine with non-uniform motion, sub-block
TMVP) or mixed references; an affine CU whose sub-block MVs are all equal is translational; CIIP is translational for its inter part but blends an intra prediction (its edges carry the full
weight here, flagged ``ciip``). ``coverage`` reports the area shares; ``build_edges(..., exclude_approx=True)`` and
``node_table`` (``approx_frac``) support the sensitivity analysis that drops approximate CUs/CTUs. Traces written
before these columns existed load with ``mv_spread = NaN`` (coverage unknown).

Node = (poc, ctu_addr). Edge u -> v carries the fraction of CTU v's area predicted from samples inside CTU u:
for every inter CU in v and every used list, the motion-shifted CU rectangle (clipped to the picture) is
intersected with the CTUs of the reference picture; bi-prediction gives each list half weight. Interpolation
taps, in-loop filtering and residual compensation are deliberately ignored: this is a structural approximation.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import numpy as np
import pandas as pd

TRACE_COLUMNS = ("poc", "coding_order", "temporal_id", "x", "y", "w", "h", "qp", "mode",
                 "ref_poc0", "mv0x", "mv0y", "ref_poc1", "mv1x", "mv1y", "resid_energy")
COVERAGE_COLUMNS = ("flags", "mv_spread", "ref_mixed")
APPROX_FLAGS = ("geo",)   # affine / sub-block CUs are approximate only when their sub-block MVs differ
SPREAD_TOL = 0.25          # luma samples

Node = tuple[int, int]


@dataclass(frozen=True)
class Picture:
    width: int
    height: int
    ctu: int = 128

    @property
    def cols(self) -> int:
        return -(-self.width // self.ctu)

    @property
    def rows(self) -> int:
        return -(-self.height // self.ctu)

    def ctu_addr(self, x: float, y: float) -> int:
        return int(y // self.ctu) * self.cols + int(x // self.ctu)

    def ctu_area(self, addr: int) -> int:
        cx, cy = addr % self.cols, addr // self.cols
        return (min(self.ctu, self.width - cx * self.ctu)) * (min(self.ctu, self.height - cy * self.ctu))


def load_trace(path) -> pd.DataFrame:
    df = pd.read_csv(path)
    missing = [c for c in TRACE_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"trace is missing columns: {missing}")
    bad = set(df["mode"]) - {"intra", "inter", "skip"}
    if bad:
        raise ValueError(f"unknown CU modes in trace: {bad}")
    if "flags" not in df.columns:
        df["flags"], df["mv_spread"], df["ref_mixed"] = "", np.nan, 0
    df["flags"] = df["flags"].fillna("").astype(str)
    return df


def approximate_mask(trace: pd.DataFrame, spread_tol: float = SPREAD_TOL) -> pd.Series:
    """True for inter CUs whose motion is not a single translation (see module docstring)."""
    inter = trace["mode"] != "intra"
    flagged = trace["flags"].str.split("|").apply(lambda f: any(x in APPROX_FLAGS for x in f))
    spread = trace["mv_spread"].fillna(0.0) > spread_tol
    return inter & (flagged | spread | (trace["ref_mixed"] > 0))


def coverage(trace: pd.DataFrame, spread_tol: float = SPREAD_TOL) -> dict:
    """Area shares of the inter CUs: translational vs approximate, and per tool flag."""
    area = trace["w"] * trace["h"]
    inter = trace["mode"] != "intra"
    inter_area = float(area[inter].sum())
    out = {"inter_area_frac": float(area[inter].sum() / area.sum()) if len(trace) else 0.0,
           "known": bool(trace["mv_spread"].notna().all())}
    if inter_area == 0:
        return {**out, "approx_frac_of_inter": 0.0, "by_flag": {}}
    approx = approximate_mask(trace, spread_tol)
    flags = trace.loc[inter, "flags"].str.split("|").explode()
    by_flag = {f: float(area[inter][flags[flags == f].index.unique()].sum() / inter_area)
               for f in sorted(set(flags) - {""})}
    return {**out, "approx_frac_of_inter": float(area[approx].sum() / inter_area), "by_flag": by_flag}


def _overlaps(pic: Picture, x0: float, y0: float, w: float, h: float):
    """Yield (ctu_addr, area) for the part of rectangle [x0, x0+w) x [y0, y0+h) inside the picture."""
    xa, ya = max(0.0, x0), max(0.0, y0)
    xb, yb = min(float(pic.width), x0 + w), min(float(pic.height), y0 + h)
    if xb <= xa or yb <= ya:
        return
    c0, c1 = int(xa // pic.ctu), int((xb - 1e-9) // pic.ctu)
    r0, r1 = int(ya // pic.ctu), int((yb - 1e-9) // pic.ctu)
    for r in range(r0, r1 + 1):
        for c in range(c0, c1 + 1):
            ox = min(xb, (c + 1) * pic.ctu) - max(xa, c * pic.ctu)
            oy = min(yb, (r + 1) * pic.ctu) - max(ya, r * pic.ctu)
            if ox > 0 and oy > 0:
                yield r * pic.cols + c, ox * oy


def build_edges(trace: pd.DataFrame, pic: Picture, exclude_approx: bool = False,
                spread_tol: float = SPREAD_TOL) -> dict[tuple[Node, Node], float]:
    edges: dict[tuple[Node, Node], float] = defaultdict(float)
    keep = trace["mode"] != "intra"
    if exclude_approx and "flags" in trace.columns:
        keep &= ~approximate_mask(trace, spread_tol)
    inter = trace[keep]
    for row in inter.itertuples(index=False):
        lists = [(row.ref_poc0, row.mv0x, row.mv0y), (row.ref_poc1, row.mv1x, row.mv1y)]
        used = [(int(rp), mx, my) for rp, mx, my in lists if rp >= 0]
        if not used:
            continue
        share = 1.0 / len(used)
        child_ctu = pic.ctu_addr(row.x, row.y)
        child_area = pic.ctu_area(child_ctu)
        for ref_poc, mx, my in used:
            for ref_ctu, area in _overlaps(pic, row.x + mx, row.y + my, row.w, row.h):
                edges[((ref_poc, ref_ctu), (int(row.poc), child_ctu))] += share * area / child_area
    return dict(edges)


def node_table(trace: pd.DataFrame, pic: Picture) -> pd.DataFrame:
    """Per-CTU codec statistics of the baseline encode (local, graph-free features)."""
    t = trace.copy()
    t["ctu_addr"] = [pic.ctu_addr(x, y) for x, y in zip(t["x"], t["y"])]
    t["area"] = t["w"] * t["h"]
    t["is_skip"] = (t["mode"] == "skip") * t["area"]
    t["is_intra"] = (t["mode"] == "intra") * t["area"]
    t["mv_mag"] = np.hypot(t["mv0x"].where(t["ref_poc0"] >= 0, 0.0), t["mv0y"].where(t["ref_poc0"] >= 0, 0.0))
    t["mv_area"] = t["mv_mag"] * t["area"]
    t["qp_area"] = t["qp"] * t["area"]
    t["approx_area"] = (approximate_mask(t) if "flags" in t.columns else False) * t["area"]
    g = t.groupby(["poc", "ctu_addr"], as_index=False).agg(
        coding_order=("coding_order", "first"), temporal_id=("temporal_id", "first"),
        area=("area", "sum"), skip=("is_skip", "sum"), intra=("is_intra", "sum"),
        mv_area=("mv_area", "sum"), qp_area=("qp_area", "sum"), resid_energy=("resid_energy", "sum"),
        approx_area=("approx_area", "sum"), n_cu=("x", "size"))
    g["skip_frac"] = g["skip"] / g["area"]
    g["intra_frac"] = g["intra"] / g["area"]
    g["mean_mv"] = g["mv_area"] / g["area"]
    g["mean_qp"] = g["qp_area"] / g["area"]
    g["log_resid"] = np.log1p(g["resid_energy"])
    g["approx_frac"] = g["approx_area"] / g["area"]       # bookkeeping for sensitivity analyses, not a feature
    return g[["poc", "ctu_addr", "coding_order", "temporal_id", "n_cu", "skip_frac", "intra_frac",
              "mean_mv", "mean_qp", "log_resid", "approx_frac"]]


def shuffle_edges(edges: dict[tuple[Node, Node], float], seed: int = 0) -> dict[tuple[Node, Node], float]:
    """Negative control: within each (reference picture, child picture) pair, permute which child CTU each edge
    points to. Source out-weights (fan-out) and the per-picture-pair weight distribution are preserved; only
    *which* regions are predicted from which is destroyed."""
    rng = np.random.default_rng(seed)
    groups: dict[tuple[int, int], list] = defaultdict(list)
    for (u, v), w in edges.items():
        groups[(u[0], v[0])].append((u, v, w))
    out: dict[tuple[Node, Node], float] = defaultdict(float)
    for items in groups.values():
        targets = [v for _, v, _ in items]
        perm = rng.permutation(len(targets))
        for (u, _, w), j in zip(items, perm):
            out[(u, targets[j])] += w
    return dict(out)
