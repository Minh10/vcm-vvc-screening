"""RAMU-Lite intervention pipeline: sample -> run -> collect.

1. ``sample``  From the baseline (DQP-enabled anchor) trace, pick CTUs for a single ΔQP intervention, stratified by
   local importance, reference fan-out and motion. Only *valid* CTUs are eligible: CTUs with a coded luma residual
   in the baseline. A CTU coded entirely without residual sends no cu_qp_delta, so a QP change cannot act on it
   (verified on VTM-24.0 + vcm-hooks; docs/ALF_CODEC_AUDIT.md). Optionally also samples intervention pairs on the
   same / different reference branches for the interaction diagnostic.
2. ``run``     One full encode + unmodified decode per intervention (``--VCMQpOffsetFile``), plus the anchor
   (header-only offset file, ``--VCMTraceFile`` for the trace). Uses ``vcm.jobs.run_job``.
3. ``collect`` After ``python -m vcm.evaluate --results <runs> --pseudo <original>``: ΔR = actual bits − anchor bits;
   ΔL = (pseudo_map_anchor − pseudo_map) / 100 (loss = 1 − AP against the detector's own outputs on the original
   frames; ground-truth mAP difference kept as ``delta_map_gt`` for reporting only).

CLI::

    python -m vcm.ramu.runner sample  --trace T.csv --boxes B.csv --width W --height H --n 200 --pairs 100 --out C/
    python -m vcm.ramu.runner run     --candidates C/ --sequences S.csv --sequence NAME --structure ldp --qp 32 \
                                      --vtm third_party/VTM --out R/ [--workers 8]
    python -m vcm.ramu.runner collect --runs R/ --candidates C/ --out C/
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from ..jobs import Job, find_binary, load_sequences, run_job
from .features import assemble, importance_from_boxes
from .graph import Picture, build_edges, load_trace, node_table, shuffle_edges

ANCHOR = "dqp_anchor"


def candidate_table(trace: pd.DataFrame, boxes: pd.DataFrame, pic: Picture) -> pd.DataFrame:
    edges = build_edges(trace, pic)
    nodes = assemble(node_table(trace, pic), importance_from_boxes(boxes, pic), edges, shuffle_edges(edges))
    coded = trace.assign(ctu_addr=[pic.ctu_addr(x, y) for x, y in zip(trace.x, trace.y)]) \
        .groupby(["poc", "ctu_addr"])["resid_energy"].sum().rename("resid_sum").reset_index()
    nodes = nodes.merge(coded, on=["poc", "ctu_addr"], how="left").fillna({"resid_sum": 0.0})
    nodes["valid"] = nodes["resid_sum"] > 0
    return nodes


def _split(x: pd.Series) -> pd.Series:
    return (x > x.median()).astype(int)


def sample(nodes: pd.DataFrame, n: int, seed: int = 0, delta_qp: int = -2) -> pd.DataFrame:
    """Stratified sample of valid CTUs: 2 (importance) x 2 (fan-out) x 2 (motion) strata, equal allocation,
    remaining quota filled at random from the valid pool."""
    rng = np.random.default_rng(seed)
    v = nodes[nodes["valid"]].copy()
    if len(v) == 0:
        raise ValueError("no valid CTU (no coded residual anywhere in the baseline)")
    v["stratum"] = _split(v["imp"]) * 4 + _split(v["fanout1"]) * 2 + _split(v["mean_mv"])
    per = max(1, n // 8)
    picks = []
    for _, g in v.groupby("stratum"):
        picks.extend(rng.choice(g.index, size=min(per, len(g)), replace=False))
    rest = v.index.difference(picks)
    if len(picks) < n and len(rest):
        picks.extend(rng.choice(rest, size=min(n - len(picks), len(rest)), replace=False))
    out = v.loc[picks[:n], ["poc", "ctu_addr", "stratum"]].copy()
    out.insert(2, "delta_qp", delta_qp)
    return out.sort_values(["poc", "ctu_addr"]).reset_index(drop=True)


def _descendants(edges, start, hops: int = 3) -> set:
    adj = defaultdict(set)
    for (u, w), _ in edges.items():
        adj[u].add(w)
    seen, frontier = set(), {start}
    for _ in range(hops):
        frontier = {w for u in frontier for w in adj[u]} - seen
        seen |= frontier
    return seen


def sample_pairs(trace: pd.DataFrame, pic: Picture, singles: pd.DataFrame, n_pairs: int, seed: int = 0
                 ) -> pd.DataFrame:
    """Half the pairs on the same reference branch (b is a descendant of a within 3 hops), half unrelated."""
    rng = np.random.default_rng(seed)
    edges = build_edges(trace, pic)
    nodes = [tuple(r) for r in singles[["poc", "ctu_addr"]].itertuples(index=False)]
    node_set = set(nodes)
    desc = {a: _descendants(edges, a) & node_set for a in nodes}
    same = [(a, b) for a in nodes for b in desc[a]]
    other = [(a, b) for a in nodes for b in nodes
             if a[0] < b[0] and b not in desc[a] and a not in desc.get(b, set())]
    rows = []
    for pool, flag in ((same, True), (other, False)):
        k = min(n_pairs // 2, len(pool))
        for i in rng.choice(len(pool), size=k, replace=False) if k else []:
            (pa, ca), (pb, cb) = pool[i]
            rows.append({"poc_a": pa, "ctu_a": ca, "poc_b": pb, "ctu_b": cb, "same_branch": flag})
    return pd.DataFrame(rows, columns=["poc_a", "ctu_a", "poc_b", "ctu_b", "same_branch"])


def _variant(row) -> str:
    return f"iv_p{int(row.poc)}_c{int(row.ctu_addr)}_d{int(row.delta_qp)}"


def _pair_variant(row, dqp: int) -> str:
    return f"pair_p{int(row.poc_a)}_c{int(row.ctu_a)}_p{int(row.poc_b)}_c{int(row.ctu_b)}_d{dqp}"


def build_jobs(cand_dir: Path, seq, structure: str, qp: int, run_dir: Path) -> list[Job]:
    offsets = run_dir / "offsets"
    offsets.mkdir(parents=True, exist_ok=True)
    empty = offsets / "anchor.csv"
    empty.write_text("poc,ctu_addr,delta_qp\n")
    jobs = [Job(seq, structure, qp, ANCHOR, (f"--VCMQpOffsetFile={empty}",
                                            f"--VCMTraceFile={run_dir / 'anchor_trace.csv'}"))]
    if not (cand_dir / "candidates.csv").exists():
        return jobs          # anchor first: the candidates are sampled from its trace
    singles = pd.read_csv(cand_dir / "candidates.csv")
    for r in singles.itertuples(index=False):
        f = offsets / f"{_variant(r)}.csv"
        f.write_text(f"poc,ctu_addr,delta_qp\n{r.poc},{r.ctu_addr},{r.delta_qp}\n")
        jobs.append(Job(seq, structure, qp, _variant(r), (f"--VCMQpOffsetFile={f}",)))
    pairs_path = cand_dir / "pairs.csv"
    if pairs_path.exists():
        dqp = int(singles["delta_qp"].iloc[0])
        for r in pd.read_csv(pairs_path).itertuples(index=False):
            f = offsets / f"{_pair_variant(r, dqp)}.csv"
            f.write_text(f"poc,ctu_addr,delta_qp\n{r.poc_a},{r.ctu_a},{dqp}\n{r.poc_b},{r.ctu_b},{dqp}\n")
            jobs.append(Job(seq, structure, qp, _pair_variant(r, dqp), (f"--VCMQpOffsetFile={f}",)))
    return jobs


def collect(run_dir: Path, cand_dir: Path, structure: str, qp: int, seq_name: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    def load(variant):
        d = run_dir / f"{seq_name}__{structure}__qp{qp}__{variant}"
        man = json.loads((d / "manifest.json").read_text())
        tm = json.loads((d / "task_metrics.json").read_text())
        return man["bits"], tm

    a_bits, a_tm = load(ANCHOR)
    key = "pseudo_map" if "pseudo_map" in a_tm else "map"

    def deltas(variant):
        bits, tm = load(variant)
        return bits - a_bits, (a_tm[key] - tm[key]) / 100.0, tm["map"] - a_tm["map"]

    singles = pd.read_csv(cand_dir / "candidates.csv")
    d = [deltas(_variant(r)) for r in singles.itertuples(index=False)]
    singles["delta_bits"], singles["delta_loss"], singles["delta_map_gt"] = zip(*d) if d else ([], [], [])
    singles["loss_source"] = key
    pairs = pd.DataFrame()
    if (cand_dir / "pairs.csv").exists():
        pairs = pd.read_csv(cand_dir / "pairs.csv")
        dqp = int(singles["delta_qp"].iloc[0])
        d = [deltas(_pair_variant(r, dqp)) for r in pairs.itertuples(index=False)]
        pairs["delta_bits"], pairs["delta_loss"], pairs["delta_map_gt"] = zip(*d) if d else ([], [], [])
    return singles, pairs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="RAMU-Lite intervention pipeline")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample")
    s.add_argument("--trace", required=True)
    s.add_argument("--boxes", required=True, help="CSV poc,x0,y0,x1,y1,score (detector on original frames)")
    s.add_argument("--width", type=int, required=True)
    s.add_argument("--height", type=int, required=True)
    s.add_argument("--ctu", type=int, default=128)
    s.add_argument("--n", type=int, default=200)
    s.add_argument("--pairs", type=int, default=0)
    s.add_argument("--delta-qp", type=int, default=-2)
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--out", required=True)
    r = sub.add_parser("run")
    r.add_argument("--candidates", required=True)
    r.add_argument("--sequences", required=True)
    r.add_argument("--sequence", required=True)
    r.add_argument("--structure", default="ldp")
    r.add_argument("--qp", type=int, required=True)
    r.add_argument("--vtm", default="third_party/VTM")
    r.add_argument("--out", required=True)
    r.add_argument("--workers", type=int, default=1)
    r.add_argument("--anchor-only", action="store_true", help="only the anchor encode (to get the trace)")
    c = sub.add_parser("collect")
    c.add_argument("--runs", required=True)
    c.add_argument("--candidates", required=True)
    c.add_argument("--sequence", required=True)
    c.add_argument("--structure", default="ldp")
    c.add_argument("--qp", type=int, required=True)
    c.add_argument("--out", required=True)
    a = ap.parse_args(argv)

    if a.cmd == "sample":
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        pic = Picture(a.width, a.height, a.ctu)
        trace = load_trace(a.trace)
        nodes = candidate_table(trace, pd.read_csv(a.boxes), pic)
        singles = sample(nodes, a.n, a.seed, a.delta_qp)
        singles.to_csv(out / "candidates.csv", index=False)
        print(f"{len(singles)} interventions from {int(nodes.valid.sum())} valid of {len(nodes)} CTUs")
        if a.pairs:
            p = sample_pairs(trace, pic, singles, a.pairs, a.seed)
            p.to_csv(out / "pairs.csv", index=False)
            print(f"{len(p)} pairs ({int(p.same_branch.sum())} same-branch)")
        return 0

    if a.cmd == "run":
        seq = {x.name: x for x in load_sequences(a.sequences)}[a.sequence]
        vtm, out = Path(a.vtm), Path(a.out)
        jobs = build_jobs(Path(a.candidates), seq, a.structure, a.qp, out)
        if a.anchor_only:
            jobs = jobs[:1]
        enc, dec = find_binary(vtm, "EncoderApp"), find_binary(vtm, "DecoderApp")
        commit = Path("third_party/VTM_COMMIT")
        prov = {"vtm_commit": commit.read_text().strip() if commit.exists() else "unknown"}
        with ThreadPoolExecutor(max_workers=a.workers) as pool:
            for f in [pool.submit(run_job, j, enc, dec, vtm, out, prov) for j in jobs]:
                f.result()
        print(f"{len(jobs)} encodes done in {out}")
        return 0

    singles, pairs = collect(Path(a.runs), Path(a.candidates), a.structure, a.qp, a.sequence)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    singles.to_csv(out / "interventions.csv", index=False)
    if len(pairs):
        pairs.to_csv(out / "pairs_measured.csv", index=False)
    print(f"collected {len(singles)} interventions, {len(pairs)} pairs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
