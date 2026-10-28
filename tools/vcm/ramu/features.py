"""Node features for the RAMU-Lite predictors.

Feature sets (docs/RAMU_LITE_SPEC.md):

- B1  local task importance only
- B2  temporal layer + direct reference fan-out
- B3  B1 + B2 + local codec statistics + task-agnostic multi-hop propagation (infl, depth)
      = the strong baseline: everything except *which* regions are predicted from the CTU
- B4  B3 + task-conditioned graph features (importance-weighted fan-out and multi-hop influence)
- B5  B3 + the same task-conditioned features computed on a shuffled graph (negative control)
- B6  task-agnostic propagation score only (multi-hop influence; the distortion-propagation literature)

B3 includes task-agnostic multi-hop propagation because the synthetic check (vcm.ramu.simulate) showed that
without it, B4 beats B3 and B5 significantly even when only reference *counts* matter — a GO that the
distortion-propagation literature already explains (docs/DECISIONS.md, 2026-10-28).

Graph features use an attenuation ``rho`` per hop, a fixed modelling constant (not tuned on report sequences)
standing in for residual compensation of reference errors.
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np
import pandas as pd

from .graph import Node, Picture

LOCAL_CODEC = ["skip_frac", "intra_frac", "mean_mv", "mean_qp", "log_resid"]
GRAPH_AGNOSTIC = ["infl", "depth"]
GRAPH_TASK = ["fanout_imp1", "infl_imp"]
GRAPH = [*GRAPH_TASK, *GRAPH_AGNOSTIC]

_B3 = ["imp", "temporal_id", "fanout1", *LOCAL_CODEC, *GRAPH_AGNOSTIC]
FEATURE_SETS: dict[str, list[str]] = {
    "B1": ["imp"],
    "B2": ["temporal_id", "fanout1"],
    "B3": _B3,
    "B4": [*_B3, *GRAPH_TASK],
    "B5": [*_B3, *[f"{g}_shuf" for g in GRAPH_TASK]],
    "B6": ["infl"],
}


def importance_from_boxes(boxes: pd.DataFrame, pic: Picture, score_threshold: float = 0.3) -> pd.DataFrame:
    """Local task importance per CTU from detector boxes on the *original* frames (pseudo-labels).

    ``boxes`` columns: poc, x0, y0, x1, y1, score. imp(u) = sum over boxes of score x covered fraction of CTU u.
    """
    imp: dict[Node, float] = defaultdict(float)
    for b in boxes[boxes["score"] >= score_threshold].itertuples(index=False):
        x0, y0 = max(0.0, b.x0), max(0.0, b.y0)
        x1, y1 = min(float(pic.width), b.x1), min(float(pic.height), b.y1)
        if x1 <= x0 or y1 <= y0:
            continue
        for r in range(int(y0 // pic.ctu), int((y1 - 1e-9) // pic.ctu) + 1):
            for c in range(int(x0 // pic.ctu), int((x1 - 1e-9) // pic.ctu) + 1):
                ox = min(x1, (c + 1) * pic.ctu) - max(x0, c * pic.ctu)
                oy = min(y1, (r + 1) * pic.ctu) - max(y0, r * pic.ctu)
                if ox > 0 and oy > 0:
                    addr = r * pic.cols + c
                    imp[(int(b.poc), addr)] += b.score * ox * oy / pic.ctu_area(addr)
    return pd.DataFrame([(p, a, v) for (p, a), v in imp.items()], columns=["poc", "ctu_addr", "imp"])


def graph_features(edges: dict[tuple[Node, Node], float], nodes: pd.DataFrame, rho: float = 0.5) -> pd.DataFrame:
    """Graph features for every node in ``nodes`` (columns poc, ctu_addr, coding_order, imp).

    fanout1     sum_v w_uv
    fanout_imp1 sum_v w_uv * imp(v)
    infl        sum_v w_uv * (1 + rho * infl(v))          (descendant mass, attenuated per hop)
    infl_imp    sum_v w_uv * (imp(v) + rho * infl_imp(v)) (importance-weighted descendant mass)
    depth       longest chain of descendants (hops)
    """
    out_adj: dict[Node, list[tuple[Node, float]]] = defaultdict(list)
    for (u, v), w in edges.items():
        out_adj[u].append((v, w))
    imp = {(int(p), int(a)): float(i) for p, a, i in zip(nodes["poc"], nodes["ctu_addr"], nodes["imp"])}
    order = nodes.sort_values("coding_order", ascending=False)
    feats: dict[Node, tuple[float, float, float, float, int]] = {}
    for p, a in zip(order["poc"], order["ctu_addr"]):
        u = (int(p), int(a))
        f1 = fi1 = inf = inf_imp = 0.0
        depth = 0
        for v, w in out_adj.get(u, ()):
            _, _, iv, iiv, dv = feats.get(v, (0.0, 0.0, 0.0, 0.0, 0))
            f1 += w
            fi1 += w * imp.get(v, 0.0)
            inf += w * (1.0 + rho * iv)
            inf_imp += w * (imp.get(v, 0.0) + rho * iiv)
            depth = max(depth, dv + 1)
        feats[u] = (f1, fi1, inf, inf_imp, depth)
    rows = [(u[0], u[1], *f) for u, f in feats.items()]
    return pd.DataFrame(rows, columns=["poc", "ctu_addr", "fanout1", "fanout_imp1", "infl", "infl_imp", "depth"])


def assemble(nodes: pd.DataFrame, imp: pd.DataFrame, edges, edges_shuffled, rho: float = 0.5) -> pd.DataFrame:
    """Join codec statistics, importance, real-graph and shuffled-graph features into one node table."""
    n = nodes.merge(imp, on=["poc", "ctu_addr"], how="left").fillna({"imp": 0.0})
    g = graph_features(edges, n, rho)
    gs = graph_features(edges_shuffled, n, rho).rename(columns={c: f"{c}_shuf" for c in ["fanout1", *GRAPH]})
    out = n.merge(g, on=["poc", "ctu_addr"], how="left").merge(gs, on=["poc", "ctu_addr"], how="left")
    return out.fillna(0.0)
