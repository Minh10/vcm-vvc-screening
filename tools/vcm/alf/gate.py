"""Gate B-1 of branch B (docs/RESEARCH_PLAN.md), computed in one place so the decision is mechanical.

Pre-registered criteria (all required for GO), per prediction structure, on the ``report`` split:

1. ``alf_weighted`` beats ``alf_default``: per-sequence task BD-rate (rate at equal task quality, %) of
   alf_weighted vs alf_default; mean over sequences < 0, its 95 % bootstrap CI entirely < 0, Holm-adjusted
   sign-flip p < alpha.
2. ``alf_weighted`` beats the shuffled control: per sequence, BD-rate of alf_weighted vs each
   ``alf_weighted_shuffled_s<k>`` averaged over the pre-registered seeds (a sequence needs a valid BD value for
   at least ``min_seeds`` seeds); same three conditions. Holm is applied over the two comparisons.
3. Validity: at every (sequence, QP) that has an ``alf_default`` point, ``alf_weighted_uniform`` exists and its
   bitstream is byte-identical to ``alf_default``; optionally (``--weights-root``) every shuffled arm has the
   continuous arm's weight distribution and an accepted (chance-level) shift.

Decision: ``INVALID`` if 3 fails; ``GO`` if 1 and 2 hold; ``NO-GO (gain not attributable to object alignment)``
if only 1 holds; ``NO-GO`` otherwise.

CLI::

    python -m vcm.alf.gate --results results/b1 --structure ldp --metric map --split report \
        [--weights-root results/b1/weights] --out results/b1/gate_b1_ldp
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from ..curves import collect, compare
from ..stats import holm, paired_test

ANCHOR, METHOD, UNIFORM, SHUFFLED_PREFIX = "alf_default", "alf_weighted", "alf_weighted_uniform", \
    "alf_weighted_shuffled_s"


def _criteria(t, p_holm: float, alpha: float) -> dict:
    return {"mean_below_0": bool(t.estimate < 0), "ci_below_0": bool(t.ci[1] < 0),
            "p_holm_below_alpha": bool(p_holm < alpha)}


def uniform_check(rows: list[dict], structure: str, split: str | None) -> dict:
    sha = {(r["sequence"], r["qp"], r["variant"]): r.get("bitstream_sha256") for r in rows
           if r["structure"] == structure and (split is None or r["split"] == split)}
    points = sorted({(s, q) for s, q, v in sha if v == ANCHOR})
    missing = [f"{s}@{q}" for s, q in points if (s, q, UNIFORM) not in sha]
    differ = [f"{s}@{q}" for s, q in points if (s, q, UNIFORM) in sha and sha[(s, q, UNIFORM)] != sha[(s, q, ANCHOR)]]
    return {"points": len(points), "missing": missing, "differ": differ,
            "ok": bool(points) and not missing and not differ}


def weights_check(root: Path, sequences: list[str], structure: str) -> dict:
    bad, overlaps = [], []
    for s in sequences:
        f = root / f"{s}__{structure}" / "weights_summary.json"
        if not f.exists():
            bad.append(f"{s}: no weights_summary.json")
            continue
        arms = json.loads(f.read_text())["arms"]
        for name, arm in arms.items():
            if arm.get("mode") != "shuffled":
                continue
            if not arm.get("same_weight_distribution_as_continuous"):
                bad.append(f"{s}/{name}: weight distribution differs")
            if not arm.get("shift", {}).get("accepted", False):
                bad.append(f"{s}/{name}: shift above chance overlap")
            if arm.get("roi_overlap") is not None:
                overlaps.append(arm["roi_overlap"])
    return {"ok": not bad, "problems": bad,
            "roi_overlap": {"mean": float(np.mean(overlaps)), "max": float(np.max(overlaps))} if overlaps else None}


def gate_b1(rows: list[dict], structure: str, metric: str = "map", split: str | None = "report",
            alpha: float = 0.05, min_seeds: int = 3, min_points: int = 4, n_resamples: int = 10_000,
            weights_root: Path | None = None) -> dict:
    seeds = sorted({r["variant"] for r in rows if r["variant"].startswith(SHUFFLED_PREFIX)})
    vs_default = compare(rows, ANCHOR, METHOD, structure, metric, split, min_points, n_resamples)
    per_seed = {k: compare(rows, k, METHOD, structure, metric, split, min_points, n_resamples) for k in seeds}
    d1 = {s: r.value for s, r in vs_default.per_sequence_rate.items() if r.valid}
    d2 = {}
    for s in sorted({s for c in per_seed.values() for s in c.per_sequence_rate}):
        vals = [c.per_sequence_rate[s].value for c in per_seed.values()
                if s in c.per_sequence_rate and c.per_sequence_rate[s].valid]
        if len(vals) >= min_seeds:
            d2[s] = float(np.mean(vals))
    out: dict = {"structure": structure, "metric": metric, "split": split, "alpha": alpha,
                 "shuffled_seeds": seeds, "min_seeds": min_seeds}
    validity = {"uniform": uniform_check(rows, structure, split)}
    if weights_root is not None:
        validity["weights"] = weights_check(Path(weights_root), sorted(d1 | d2), structure)
    out["validity"] = validity
    if len(d1) < 2 or len(d2) < 2 or not seeds:
        out["decision"] = "INVALID"
        out["reason"] = "fewer than 2 sequences with valid BD values in a comparison, or no shuffled arm"
        return out
    t1 = paired_test(d1, {s: 0.0 for s in d1}, np.mean, n_resamples)
    t2 = paired_test(d2, {s: 0.0 for s in d2}, np.mean, n_resamples)
    p_holm = holm([t1.p_value, t2.p_value])
    c1, c2 = _criteria(t1, p_holm[0], alpha), _criteria(t2, p_holm[1], alpha)
    for name, t, c, ph, d in (("vs_default", t1, c1, p_holm[0], d1), ("vs_shuffled", t2, c2, p_holm[1], d2)):
        out[name] = {"n": len(t.sequences), "mean_bd_rate": t.estimate, "ci": list(t.ci), "p": t.p_value,
                     "p_holm": float(ph), "criteria": c, "pass": all(c.values()), "per_sequence": d}
    out["excluded"] = {"vs_default": vs_default.excluded,
                       "vs_shuffled": sorted(set(vs_default.per_sequence_rate) - set(d2))}
    valid = all(v["ok"] for v in validity.values())
    if not valid:
        out["decision"] = "INVALID"
    elif out["vs_default"]["pass"] and out["vs_shuffled"]["pass"]:
        out["decision"] = "GO"
    elif out["vs_default"]["pass"]:
        out["decision"] = "NO-GO (gain not attributable to object alignment)"
    else:
        out["decision"] = "NO-GO"
    return out


def to_markdown(g: dict) -> str:
    lines = [f"# Gate B-1 — {g['structure']}, metric `{g['metric']}`, split `{g['split']}`", "",
             f"**Decision: {g['decision']}**", ""]
    for name in ("vs_default", "vs_shuffled"):
        if name not in g:
            continue
        t = g[name]
        lines.append(f"- {name}: n={t['n']}, mean BD-rate {t['mean_bd_rate']:+.2f} %, CI [{t['ci'][0]:+.2f}, "
                     f"{t['ci'][1]:+.2f}], p={t['p']:.4g}, p_Holm={t['p_holm']:.4g} → {'pass' if t['pass'] else 'fail'}")
    u = g["validity"]["uniform"]
    lines.append(f"- uniform arm identical to alf_default: {u['ok']} ({u['points']} points; missing "
                 f"{len(u['missing'])}, differing {len(u['differ'])})")
    if "weights" in g["validity"]:
        w = g["validity"]["weights"]
        lines.append(f"- shuffled weight maps valid: {w['ok']}; ROI overlap {w['roi_overlap']}")
        lines += [f"  - {p}" for p in w["problems"][:20]]
    if "vs_default" in g:
        lines += ["", "| Sequence | BD-rate vs default (%) | BD-rate vs shuffled, seed mean (%) |", "| --- | --- | --- |"]
        seqs = sorted(set(g["vs_default"]["per_sequence"]) | set(g["vs_shuffled"]["per_sequence"]))
        for s in seqs:
            a = g["vs_default"]["per_sequence"].get(s)
            b = g["vs_shuffled"]["per_sequence"].get(s)
            lines.append(f"| {s} | {'—' if a is None else f'{a:+.2f}'} | {'—' if b is None else f'{b:+.2f}'} |")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Gate B-1 (branch B)")
    ap.add_argument("--results", required=True)
    ap.add_argument("--structure", required=True)
    ap.add_argument("--metric", default="map")
    ap.add_argument("--split", default="report", help="'all' to use every sequence (pilot only)")
    ap.add_argument("--alpha", type=float, default=0.05)
    ap.add_argument("--min-seeds", type=int, default=3)
    ap.add_argument("--weights-root")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    g = gate_b1(collect(a.results), a.structure, a.metric, None if a.split == "all" else a.split, a.alpha,
                a.min_seeds, weights_root=Path(a.weights_root) if a.weights_root else None)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".json").write_text(json.dumps(g, indent=2))
    md = to_markdown(g)
    out.with_suffix(".md").write_text(md)
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
