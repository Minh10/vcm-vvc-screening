"""Collect rate–task points and compare two variants sequence by sequence.

For each sequence: BD-rate (and BD-quality) of ``test`` vs ``anchor`` on the common monotone interval
(``vcm.bd_rate``). Across sequences: sequence-level paired statistics (``vcm.stats``) of the per-sequence values
against zero. Sequences whose BD value is undefined are listed explicitly and excluded; the report states how many.

Guards:
* task metrics whose fingerprint does not match the job's decoded file are ignored (stale);
* rows scored by different detectors are never compared;
* pseudo-variants (e.g. the O1-A relaxed oracle, whose rate is copied from its anchor) are refused unless
  ``--allow-pseudo``; the report then carries a warning that the result is not a coding result;
* sequences where the test bitstreams are byte-identical to the anchor's at every QP are listed (an intervention
  that was requested but never changed the encoding).

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

FIELDS = ("sequence", "split", "structure", "variant", "qp", "kbps", "bits", "pseudo_variant", "bitstream_sha256",
          "detector")


def collect(results_dir: str | Path, verbose: bool = True) -> list[dict]:
    rows = []
    for mpath in sorted(Path(results_dir).glob("*/manifest.json")):
        man = json.loads(mpath.read_text())
        tm = mpath.parent / "task_metrics.json"
        if man.get("status") != "ok" or not tm.exists():
            continue
        metrics = json.loads(tm.read_text())
        fp = metrics.get("fingerprint") or {}
        if fp and fp.get("recon_md5") != man.get("recon_md5_decoder"):
            if verbose:
                print(f"skip {man.get('job_id')}: task metrics belong to a different decoded file")
            continue
        job = man["job"]
        row = {"sequence": job["sequence"]["name"], "split": job["sequence"]["split"],
               "structure": job["structure"], "variant": job["variant"], "qp": job["qp"],
               "kbps": man["kbps"], "bits": man["bits"], "pseudo_variant": bool(man.get("pseudo_variant")),
               "bitstream_sha256": man.get("bitstream_sha256"),
               "detector": fp.get("detector") or metrics.get("detector_spec_sha")}
        row.update({k: v for k, v in metrics.items() if isinstance(v, (int, float)) and not isinstance(v, bool)})
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
    pseudo: bool = False
    identical_bitstreams: tuple[str, ...] = ()

    @property
    def excluded(self) -> list[str]:
        return sorted(s for s, r in self.per_sequence_rate.items() if not r.valid)


def compare(rows, anchor: str, test: str, structure: str, metric: str, split: str | None = None,
            min_points: int = 4, n_resamples: int = 10_000, allow_pseudo: bool = False) -> Comparison:
    used = [r for r in rows if r["structure"] == structure and r["variant"] in (anchor, test)
            and (split is None or r["split"] == split)]
    pseudo = sorted({r["variant"] for r in used if r.get("pseudo_variant")})
    if pseudo and not allow_pseudo:
        raise ValueError(f"{pseudo} are pseudo-variants (not coding results; rate copied from an anchor). "
                         "Use allow_pseudo / --allow-pseudo to compare them, and label the result as such.")
    detectors = {r.get("detector") for r in used if r.get("detector")}
    if len(detectors) > 1:
        raise ValueError(f"rows were scored by {len(detectors)} different detectors; re-run vcm.evaluate")
    seqs = sorted({r["sequence"] for r in used})
    rate, qual, identical = {}, {}, []
    for s in seqs:
        sha = {(r["variant"], r["qp"]): r.get("bitstream_sha256") for r in used if r["sequence"] == s}
        qps = {q for v, q in sha if v == test}
        if qps and all(sha.get((test, q)) and sha.get((test, q)) == sha.get((anchor, q)) for q in qps):
            identical.append(s)
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

    return Comparison(anchor, test, structure, metric, rate, qual, _test(rate), _test(qual),
                      bool(pseudo), tuple(identical))


def to_markdown(c: Comparison) -> str:
    lines = [f"# {c.test} vs {c.anchor} — {c.structure}, metric `{c.metric}`", ""]
    if c.pseudo:
        lines += ["> **PSEUDO-VARIANT — not a coding result.** At least one side is a relaxed oracle whose rate is",
                  "> copied from its anchor (no APS cost, no reference effects). Use only as a diagnostic of headroom.",
                  ""]
    lines += ["| Sequence | BD-rate (%) | BD-quality | Points used (anchor/test) | Note |",
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
    lines.append(f"- Test bitstream identical to anchor at every QP (intervention not realised): "
                 f"{', '.join(c.identical_bitstreams) or 'none'}")
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
    ap.add_argument("--allow-pseudo", action="store_true", help="allow pseudo-variants (O1-A relaxed oracle)")
    a = ap.parse_args(argv)

    rows = collect(a.results)
    if a.csv:
        write_csv(rows, a.csv)
    try:
        c = compare(rows, a.anchor, a.test, a.structure, a.metric, a.split, a.min_points,
                    allow_pseudo=a.allow_pseudo)
    except ValueError as exc:
        raise SystemExit(str(exc))
    md = to_markdown(c)
    if a.md:
        Path(a.md).write_text(md)
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
