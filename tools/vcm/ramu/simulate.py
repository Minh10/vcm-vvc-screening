"""Synthetic check of the A1 analysis pipeline (NOT evidence about real codecs).

Generates CTU-level sequences with moving objects, a low-delay reference graph and intervention effects under two
ground truths:

- ``signal``: ΔL depends on the importance of the regions *actually* predicted from the CTU (topology matters),
- ``null``:   ΔL depends on local importance and on *how much* the CTU is referenced (fan-out count), but not on
  which regions are predicted from it — the strong non-graph baseline B3 can explain it.

A well-behaved analysis must say GO under ``signal`` with high probability and NO-GO under ``null`` most of the time.

CLI::

    python -m vcm.ramu.simulate --runs 20 --sequences 12 --out results/ramu/simulation
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from .analysis import gate_a1, score_models
from .features import assemble, graph_features
from .graph import shuffle_edges


def _sequence(rng, name, scenario, frames=24, cols=8, rows=5, n_interventions=80, noise=0.35):
    n_ctu = cols * rows
    # moving objects: centre (cx, cy) in CTU units, velocity, radius
    objs = [(rng.uniform(0, cols), rng.uniform(0, rows), rng.uniform(-0.4, 0.4), rng.uniform(-0.25, 0.25),
             rng.uniform(0.6, 1.3)) for _ in range(rng.integers(2, 4))]
    gx, gy = np.meshgrid(np.arange(cols) + 0.5, np.arange(rows) + 0.5)

    def importance(t):
        m = np.zeros((rows, cols))
        for cx, cy, vx, vy, r in objs:
            d2 = (gx - (cx + vx * t) % cols) ** 2 + (gy - (cy + vy * t) % rows) ** 2
            m += np.exp(-d2 / (2 * r * r))
        return np.clip(m + rng.normal(0, 0.05, m.shape), 0, None)

    imp = {t: importance(t) for t in range(frames)}
    edges: dict = defaultdict(float)
    for t in range(1, frames):
        for r in range(rows):
            for c in range(cols):
                if rng.random() < 0.08:                       # intra CTU: no reference
                    continue
                # dominant motion near objects, plus random spill to neighbours
                vx = vy = 0.0
                for cx, cy, ovx, ovy, rad in objs:
                    if (c + 0.5 - (cx + ovx * t) % cols) ** 2 + (r + 0.5 - (cy + ovy * t) % rows) ** 2 < 2 * rad:
                        vx, vy = ovx, ovy
                sr = int(np.clip(round(r - vy * 2 + rng.normal(0, 0.6)), 0, rows - 1))
                sc = int(np.clip(round(c - vx * 2 + rng.normal(0, 0.6)), 0, cols - 1))
                main = rng.uniform(0.55, 0.9)
                edges[((t - 1, sr * cols + sc), (t, r * cols + c))] += main
                nr, nc = int(np.clip(sr + rng.integers(-1, 2), 0, rows - 1)), \
                    int(np.clip(sc + rng.integers(-1, 2), 0, cols - 1))
                edges[((t - 1, nr * cols + nc), (t, r * cols + c))] += (1 - main) * rng.uniform(0.3, 1.0)
    edges = dict(edges)

    node_rows = []
    for t in range(frames):
        for a in range(n_ctu):
            i = imp[t].flat[a]
            node_rows.append({
                "poc": t, "ctu_addr": a, "coding_order": t, "temporal_id": 0 if t % 4 == 0 else 1 + (t % 2),
                "skip_frac": float(np.clip(0.7 - 0.4 * i + rng.normal(0, 0.1), 0, 1)),
                "intra_frac": float(np.clip(0.05 + rng.normal(0, 0.03), 0, 1)),
                "mean_mv": float(abs(rng.normal(0.5 + i, 0.3))),
                "mean_qp": 37.0 - (t % 4 == 0) * 2,
                "log_resid": float(5 + 2 * i + rng.normal(0, 0.5)),
            })
    nodes = pd.DataFrame(node_rows)
    imp_df = pd.DataFrame([(t, a, float(imp[t].flat[a])) for t in range(frames) for a in range(n_ctu)],
                          columns=["poc", "ctu_addr", "imp"])
    table = assemble(nodes, imp_df, edges, shuffle_edges(edges, int(rng.integers(1 << 30))), rho=0.5)

    # ground truth uses its own attenuation (0.6), different from the analysis constant (0.5)
    truth = graph_features(edges, table[["poc", "ctu_addr", "coding_order", "imp"]], rho=0.6)
    table = table.merge(truth.rename(columns={c: f"true_{c}" for c in truth.columns if c not in ("poc", "ctu_addr")}),
                        on=["poc", "ctu_addr"])
    if scenario == "signal":
        effect = 1.0 * table["imp"] + 0.8 * table["true_infl_imp"]
    elif scenario == "null":
        mean_imp = table.groupby("poc")["imp"].transform("mean")
        effect = 1.0 * table["imp"] + 0.8 * table["true_infl"] * mean_imp
    else:
        raise ValueError(scenario)
    scale = effect.std()
    table["delta_loss"] = -(effect + rng.normal(0, noise * scale, len(table)))
    table["delta_bits"] = 400 + 300 * table["log_resid"] + rng.normal(0, 150, len(table))

    pick = rng.choice(table.index[table["poc"] < frames - 1], size=n_interventions, replace=False)
    df = table.loc[pick].reset_index(drop=True)
    df.insert(0, "sequence", name)
    df["delta_qp"] = -2
    return df


def simulate_dataset(scenario: str, n_sequences: int = 12, seed: int = 0, **kw) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.concat([_sequence(rng, f"sim{i:02d}", scenario, **kw) for i in range(n_sequences)],
                     ignore_index=True)


def run(scenario: str, runs: int, n_sequences: int, kind: str, seed: int, n_resamples: int = 2000) -> dict:
    decisions, gains = [], []
    for r in range(runs):
        df = simulate_dataset(scenario, n_sequences, seed=seed + r)
        g = gate_a1(score_models(df, kind, 0.1, seed + r), n_resamples=n_resamples, seed=seed + r)
        decisions.append(g["decision"])
        gains.append(g["B4_minus_B3"]["median"])
    return {"scenario": scenario, "runs": runs, "go_rate": decisions.count("GO") / runs,
            "median_rho_gain_B4_B3": float(np.median(gains))}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--runs", type=int, default=20)
    ap.add_argument("--sequences", type=int, default=12)
    ap.add_argument("--model", default="gbr", choices=["gbr", "ridge"])
    ap.add_argument("--seed", type=int, default=1000)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    res = [run(s, a.runs, a.sequences, a.model, a.seed) for s in ("signal", "null")]
    for r in res:
        print(f"{r['scenario']:6s}  GO rate {r['go_rate']:.0%} over {r['runs']} runs  "
              f"(median rho gain B4-B3 {r['median_rho_gain_B4_B3']:+.3f})")
    if a.out:
        Path(a.out).mkdir(parents=True, exist_ok=True)
        (Path(a.out) / "simulation.json").write_text(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
