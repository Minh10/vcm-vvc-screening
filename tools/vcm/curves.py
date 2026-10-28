"""Collect rate–task points and compare two variants sequence by sequence.

For each sequence: BD-rate (and BD-quality) of ``test`` vs ``anchor`` on the common monotone interval
(``vcm.bd_rate``). Across sequences: sequence-level paired statistics (``vcm.stats``) of the per-sequence values
against zero. Sequences whose BD value is undefined are listed explicitly and excluded; the report states how many.

CLI::

    python -m vcm.curves --results results/b0 --anchor alf_default --test alf_off --structure ldp \
        --metric map [--split report] [--csv results/b0/points.csv] [--md results/b0/report_alf_off.md]
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .bd_rate import BDResult, bd_quality, bd_rate
from .stats import PairedResult, paired_test

FIELDS = ("sequence", "split", "structure", "variant", "qp", "kbps", "bits")


def collect(results_dir: str | Path) -> list[dict]:
    rows = []
    for mpath in sorted(Path(results_dir).glob("*/manifest.json")):
        man = json.loads(mpath.read_text())
        tm = mpath.parent / "task_metrics.json"
        if man.get("status") != "ok" or not tm.exists():
            continue
        job = man["job"]
        row = {"sequence": job["sequence"]["name"], "split": job["sequence"]["split"],
               "structure": job["structure"], "variant": job["variant"], "qp": job["qp"],
               "kbps": man["kbps"], "bits": man["bits"]}
        row.update({k: v for k, v in json.loads(tm.read_text()).items() if isinstance(v, (int, float))})
        rows.append(row)
    return rows


def write_csv(rows: list[dict], path: str | Path) -> None:
    keys = list(FIELDS) + sorted({k for r in rows for k in r} - set(FIELDS))
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def _curve(rows, seq, structure, variant, metric):
    pts = sorted((r["qp"], r["kbps"], r[metric]) for r in rows
                 if r["sequence"] == seq and r["structure"] == structure and r["variant"] == variant)
    return np.array([p[1] for p in pts]), np.array([p[2] for p in pts])


@dataclass
class Comparison:
    anchor: str
    test: str
    structure: str
    metric: str
    per_sequence_rate: dict[str, BDResult]
    per_sequence_quality: dict[str, BDResult]
    rate_test: PairedResult | None
    quality_test: PairedResult | None

    @property
    def excluded(self) -> list[str]:
        return sorted(s for s, r in self.per_sequence_rate.items() if not r.valid)


def compare(rows, anchor: str, test: str, structure: str, metric: str, split: str | None = None,
            min_points: int = 4, n_resamples: int = 10_000) -> Comparison:
    seqs = sorted({r["sequence"] for r in rows
                   if r["structure"] == structure and (split is None or r["split"] == split)})
    rate, qual = {}, {}
    for s in seqs:
        ra, qa = _curve(rows, s, structure, anchor, metric)
        rt, qt = _curve(rows, s, structure, test, metric)
        if len(ra) == 0 or len(rt) == 0:
            continue
        rate[s] = bd_rate(ra, qa, rt, qt, min_points)
        qual[s] = bd_quality(ra, qa, rt, qt, min_points)

    def _test(d):
        valid = {s: r.value for s, r in d.items() if r.valid}
        if len(valid) < 2:
            return None
        return paired_test(valid, {s: 0.0 for s in valid}, statistic=np.mean, n_resamples=n_resamples)

    return Comparison(anchor, test, structure, metric, rate, qual, _test(rate), _test(qual))


def to_markdown(c: Comparison) -> str:
    lines = [f"# {c.test} vs {c.anchor} — {c.structure}, metric `{c.metric}`", "",
             "| Sequence | BD-rate (%) | BD-quality | Points used (anchor/test) | Note |",
             "| --- | --- | --- | --- | --- |"]
    for s in sorted(c.per_sequence_rate):
        r, q = c.per_sequence_rate[s], c.per_sequence_quality[s]
        rv = f"{r.value:+.2f}" if r.valid else "—"
        qv = f"{q.value:+.3f}" if q.valid else "—"
        lines.append(f"| {s} | {rv} | {qv} | {r.points_used[0]}/{r.points_used[1]} | {r.reason} |")
    lines.append("")
    for name, t in (("BD-rate", c.rate_test), ("BD-quality", c.quality_test)):
        lines.append(f"- **{name}** (mean over sequences, sign-flip test vs 0): "
                     + (t.summary() if t else "fewer than 2 valid sequences"))
    lines.append(f"- Excluded (undefined BD): {', '.join(c.excluded) or 'none'}")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Rate–task comparison of two variants")
    ap.add_argument("--results", required=True)
    ap.add_argument("--anchor", required=True)
    ap.add_argument("--test", required=True)
    ap.add_argument("--structure", required=True)
    ap.add_argument("--metric", default="map")
    ap.add_argument("--split", choices=["tune", "report"])
    ap.add_argument("--min-points", type=int, default=4)
    ap.add_argument("--csv")
    ap.add_argument("--md")
    a = ap.parse_args(argv)

    rows = collect(a.results)
    if a.csv:
        write_csv(rows, a.csv)
    c = compare(rows, a.anchor, a.test, a.structure, a.metric, a.split, a.min_points)
    md = to_markdown(c)
    if a.md:
        Path(a.md).write_text(md)
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
