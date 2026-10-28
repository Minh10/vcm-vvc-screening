"""Sequence-disjoint evaluation of the RAMU-Lite predictors and the A1 gate.

Every model is trained leave-one-sequence-out: predictions for a sequence come from a model that never saw it.
B1–B6 use the same model family and the same fixed hyper-parameters (no tuning on report sequences); B0 is random.

Per held-out sequence:
- Spearman rho between predicted and measured ΔL of the interventions,
- top-k regret: share of the oracle's achievable benefit (−ΔL) lost when the k units with the best *predicted*
  benefit are chosen instead of the k truly best (k = ``topk_frac`` of the sequence's interventions).

Gate A1 (docs/RESEARCH_PLAN.md), all conditions required:
1. median over sequences of (rho_B4 − rho_B3) >= 0.05,
2. lower bound of its bootstrap CI > 0,
3. mean regret of B4 at least 10 % lower than B3,
4. B4 beats the shuffled-graph control B5: median(rho_B4 − rho_B5) > 0 and Holm-adjusted p < alpha.

CLI::

    python -m vcm.ramu.analysis --inputs configs/ramu_inputs.yaml --out results/ramu/a1
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from scipy.stats import spearmanr
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from ..stats import holm, paired_test
from .features import FEATURE_SETS, assemble, importance_from_boxes
from .graph import Picture, build_edges, load_trace, node_table, shuffle_edges

MODELS = ["B0", *FEATURE_SETS]


def make_model(kind: str, seed: int):
    if kind == "gbr":
        return GradientBoostingRegressor(n_estimators=200, max_depth=3, learning_rate=0.05, subsample=0.8,
                                         random_state=seed)
    if kind == "ridge":
        return make_pipeline(StandardScaler(), Ridge(alpha=1.0))
    raise ValueError(kind)


def build_sequence_table(name: str, pic: Picture, trace: pd.DataFrame, boxes: pd.DataFrame,
                         interventions: pd.DataFrame, rho: float = 0.5, shuffle_seed: int = 0) -> pd.DataFrame:
    """One row per intervention, with all features computed from the baseline encode only (no leakage)."""
    edges = build_edges(trace, pic)
    nodes = assemble(node_table(trace, pic), importance_from_boxes(boxes, pic), edges,
                     shuffle_edges(edges, shuffle_seed), rho)
    df = interventions.merge(nodes, on=["poc", "ctu_addr"], how="left", validate="many_to_one")
    if df["coding_order"].isna().any():
        bad = df.loc[df["coding_order"].isna(), ["poc", "ctu_addr"]].head().values.tolist()
        raise ValueError(f"{name}: interventions on CTUs absent from the trace, e.g. {bad}")
    df.insert(0, "sequence", name)
    return df


def loso_predict(df: pd.DataFrame, model_name: str, target: str = "delta_loss", kind: str = "gbr",
                 seed: int = 0) -> pd.Series:
    pred = pd.Series(np.nan, index=df.index)
    if model_name == "B0":
        rng = np.random.default_rng(seed)
        return pd.Series(rng.standard_normal(len(df)), index=df.index)
    cols = FEATURE_SETS[model_name]
    for seq in df["sequence"].unique():
        test = df["sequence"] == seq
        m = make_model(kind, seed)
        m.fit(df.loc[~test, cols].to_numpy(float), df.loc[~test, target].to_numpy(float))
        pred[test] = m.predict(df.loc[test, cols].to_numpy(float))
    return pred


def topk_regret(pred_loss: np.ndarray, true_loss: np.ndarray, frac: float) -> float:
    benefit, pred_benefit = -np.asarray(true_loss), -np.asarray(pred_loss)
    k = max(1, int(round(frac * len(benefit))))
    oracle = np.sort(benefit)[::-1][:k].sum()
    chosen = benefit[np.argsort(pred_benefit, kind="stable")[::-1][:k]].sum()
    if oracle <= 0:
        return float("nan")
    return float((oracle - chosen) / oracle)


def score_models(df: pd.DataFrame, kind: str = "gbr", topk_frac: float = 0.1, seed: int = 0) -> pd.DataFrame:
    rows = []
    for model in MODELS:
        p_loss = loso_predict(df, model, "delta_loss", kind, seed)
        p_bits = loso_predict(df, model, "delta_bits", kind, seed) if model != "B0" else None
        for seq, g in df.groupby("sequence"):
            yl = g["delta_loss"].to_numpy(float)
            pl = p_loss[g.index].to_numpy(float)
            rho = spearmanr(pl, yl).statistic if np.ptp(pl) > 0 and np.ptp(yl) > 0 else 0.0
            rows.append({
                "sequence": seq, "model": model, "spearman": float(rho),
                "regret": topk_regret(pl, yl, topk_frac),
                "mae_loss": float(np.mean(np.abs(pl - yl))) if model != "B0" else float("nan"),
                "mae_bits": float(np.mean(np.abs(p_bits[g.index] - g["delta_bits"]))) if p_bits is not None
                else float("nan"),
                "n": len(g),
            })
    return pd.DataFrame(rows)


def gate_a1(scores: pd.DataFrame, min_median_gain: float = 0.05, min_regret_reduction: float = 0.10,
            alpha: float = 0.05, n_resamples: int = 10_000, seed: int = 0) -> dict:
    rho = {m: dict(zip(g["sequence"], g["spearman"])) for m, g in scores.groupby("model")}
    t43 = paired_test(rho["B4"], rho["B3"], np.median, n_resamples, seed=seed)
    t45 = paired_test(rho["B4"], rho["B5"], np.median, n_resamples, seed=seed)
    p_adj = holm([t43.p_value, t45.p_value])
    reg = scores.groupby("model")["regret"].mean()
    reduction = (reg["B3"] - reg["B4"]) / reg["B3"] if reg["B3"] > 0 else float("nan")
    checks = {
        "median_gain_B4_vs_B3": bool(t43.estimate >= min_median_gain),
        "ci_lower_B4_vs_B3_above_0": bool(t43.ci[0] > 0),
        "regret_reduction_B4_vs_B3": bool(np.isfinite(reduction) and reduction >= min_regret_reduction),
        "B4_beats_shuffled_B5": bool(t45.estimate > 0 and p_adj[1] < alpha),
    }
    return {
        "decision": "GO" if all(checks.values()) else "NO-GO",
        "checks": checks,
        "B4_minus_B3": {"median": t43.estimate, "ci": t43.ci, "p": t43.p_value, "p_holm": float(p_adj[0])},
        "B4_minus_B5": {"median": t45.estimate, "ci": t45.ci, "p": t45.p_value, "p_holm": float(p_adj[1])},
        "mean_regret": {k: float(v) for k, v in reg.items()},
        "regret_reduction_B4_vs_B3": float(reduction),
        "n_sequences": len(t43.sequences),
    }


def interactions(singles: pd.DataFrame, pairs: pd.DataFrame) -> pd.DataFrame:
    """I^L = ΔL_ab − ΔL_a − ΔL_b and I^R likewise, summarised by ``same_branch``.

    ``singles``: sequence, poc, ctu_addr, delta_loss, delta_bits.
    ``pairs``: sequence, poc_a, ctu_a, poc_b, ctu_b, same_branch, delta_loss, delta_bits.
    """
    s = singles.set_index(["sequence", "poc", "ctu_addr"])[["delta_loss", "delta_bits"]]
    a = s.loc[list(zip(pairs["sequence"], pairs["poc_a"], pairs["ctu_a"]))].to_numpy()
    b = s.loc[list(zip(pairs["sequence"], pairs["poc_b"], pairs["ctu_b"]))].to_numpy()
    out = pairs.copy()
    out["I_L"] = pairs["delta_loss"].to_numpy() - a[:, 0] - b[:, 0]
    out["I_R"] = pairs["delta_bits"].to_numpy() - a[:, 1] - b[:, 1]
    out["rel_I_L"] = np.abs(out["I_L"]) / (np.abs(a[:, 0]) + np.abs(b[:, 0]) + 1e-12)
    return out.groupby("same_branch").agg(n=("I_L", "size"), mean_I_L=("I_L", "mean"),
                                          median_rel_I_L=("rel_I_L", "median"), mean_I_R=("I_R", "mean")
                                          ).reset_index()


def report(scores: pd.DataFrame, gate: dict) -> str:
    summ = scores.groupby("model").agg(spearman_median=("spearman", "median"), regret_mean=("regret", "mean"),
                                       mae_loss=("mae_loss", "mean")).reindex(MODELS)
    lines = [f"# RAMU-Lite gate A1: **{gate['decision']}**", "",
             f"Sequences: {gate['n_sequences']} (leave-one-sequence-out).", "",
             "| Model | median Spearman | mean top-k regret | mean MAE ΔL |", "| --- | --- | --- | --- |"]
    for m, r in summ.iterrows():
        lines.append(f"| {m} | {r.spearman_median:.3f} | {r.regret_mean:.3f} | {r.mae_loss:.4g} |")
    lines += ["", "| Check | Passed |", "| --- | --- |"]
    lines += [f"| {k} | {'yes' if v else 'no'} |" for k, v in gate["checks"].items()]
    for key in ("B4_minus_B3", "B4_minus_B5"):
        g = gate[key]
        lines.append(f"\n- {key}: median {g['median']:+.3f}, CI [{g['ci'][0]:+.3f}, {g['ci'][1]:+.3f}], "
                     f"p {g['p']:.4g}, Holm p {g['p_holm']:.4g}")
    lines.append(f"- Regret reduction B4 vs B3: {gate['regret_reduction_B4_vs_B3']:.1%}")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="RAMU-Lite A1 analysis")
    ap.add_argument("--inputs", required=True, help="YAML listing per-sequence trace/boxes/interventions files")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    spec = yaml.safe_load(Path(a.inputs).read_text())
    rho, kind, frac, seed = spec.get("rho", 0.5), spec.get("model", "gbr"), spec.get("topk_frac", 0.1), \
        spec.get("seed", 0)
    tables, singles, pairs = [], [], []
    for s in spec["sequences"]:
        pic = Picture(s["width"], s["height"], s.get("ctu", 128))
        iv = pd.read_csv(s["interventions"])
        tables.append(build_sequence_table(s["name"], pic, load_trace(s["trace"]), pd.read_csv(s["boxes"]), iv,
                                           rho, seed))
        singles.append(iv.assign(sequence=s["name"]))
        if s.get("pairs"):
            pairs.append(pd.read_csv(s["pairs"]).assign(sequence=s["name"]))
    df = pd.concat(tables, ignore_index=True)
    scores = score_models(df, kind, frac, seed)
    gate = gate_a1(scores, seed=seed)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "design.csv", index=False)
    scores.to_csv(out / "scores.csv", index=False)
    (out / "gate_a1.json").write_text(json.dumps(gate, indent=2))
    text = report(scores, gate)
    if pairs:
        inter = interactions(pd.concat(singles), pd.concat(pairs))
        inter.to_csv(out / "interactions.csv", index=False)
        text += "\n## Interactions\n\n" + inter.to_markdown(index=False) + "\n"
    (out / "report.md").write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
