"""Copy the small, shareable part of a results tree into a folder that can be committed.

Kept: manifests, task metrics, CSV/JSON/Markdown summaries (reports, gates, realisation, coverage, weight summaries,
points). Skipped: media and codec outputs (YUV, bitstreams, dumps, weight maps), traces, detections, logs, and any
file above ``--max-mb``. Large raw data stays on the server; only what the statistics are computed from is shared
(CLAUDE.md: "chỉ commit CSV/JSON tổng hợp").

CLI::

    python -m vcm.export --results results/b0 --out results/summary/2026-11-02_b0_pilot [--max-mb 5]
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

KEEP_SUFFIXES = {".json", ".csv", ".md", ".txt", ".yaml"}
SKIP_NAMES = {"detections.json"}
SKIP_DIRS = {"traces", "offsets", "dump", "weights", "external"}
SKIP_PATTERNS = ("ctb_", "enc.log", "dec.log")


def shareable(path: Path, root: Path, max_bytes: int) -> bool:
    rel = path.relative_to(root)
    if any(part in SKIP_DIRS for part in rel.parts[:-1]):
        return False
    if path.suffix not in KEEP_SUFFIXES or path.name in SKIP_NAMES or path.name.startswith(SKIP_PATTERNS):
        return False
    return path.stat().st_size <= max_bytes


def export(results: Path, out: Path, max_mb: float = 5.0) -> tuple[list[Path], list[Path]]:
    max_bytes = int(max_mb * (1 << 20))
    kept, skipped = [], []
    for p in sorted(x for x in results.rglob("*") if x.is_file()):
        if shareable(p, results, max_bytes):
            dst = out / p.relative_to(results)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst)
            kept.append(p)
        else:
            skipped.append(p)
    return kept, skipped


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--results", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-mb", type=float, default=5.0)
    a = ap.parse_args(argv)
    kept, skipped = export(Path(a.results), Path(a.out), a.max_mb)
    size = sum(p.stat().st_size for p in kept) / (1 << 20)
    print(f"exported {len(kept)} files ({size:.1f} MB) to {a.out}; skipped {len(skipped)}")
    big = [p for p in skipped if p.suffix in KEEP_SUFFIXES and p.stat().st_size > a.max_mb * (1 << 20)]
    for p in big:
        print(f"  too large, not exported: {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
