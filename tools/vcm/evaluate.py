"""Task metrics on decoder output.

Detection: COCO-style AP via pycocotools against a per-sequence COCO ground-truth file. Values are reported in
percent: ``map`` (AP@[.5:.95]), ``ap50``, ``ap75``, ``ap_small``. Which one is the primary metric is fixed in
``configs/experiment.yaml`` (``evaluation.primary_metric``) from the CTC document during P0.

Frame-to-image mapping: GT images carry ``frame_index`` (0-based decoded frame order); if absent, images sorted
by ``file_name`` are taken to be in frame order. The mapping actually used is stored with the metrics.

CLI::

    python -m vcm.evaluate --results results/b0 --sequences configs/sequences.csv --config configs/experiment.yaml
    python -m vcm.evaluate --original --out results/original --sequences ... --config ...
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
from pathlib import Path

import yaml

from .detect import FrameDetections, build, run_on_yuv, to_coco_results
from .jobs import load_sequences

METRIC_KEYS = ("map", "ap50", "ap75", "ap_small")


def frame_image_ids(gt: dict) -> list[int]:
    images = gt["images"]
    if images and all("frame_index" in im for im in images):
        ordered = sorted(images, key=lambda im: im["frame_index"])
        idx = [im["frame_index"] for im in ordered]
        if idx != list(range(len(idx))):
            raise ValueError("frame_index values must be 0..N-1 without gaps")
    else:
        ordered = sorted(images, key=lambda im: im["file_name"])
    return [im["id"] for im in ordered]


def coco_detection_metrics(gt: dict, results: list[dict]) -> dict[str, float]:
    from pycocotools.coco import COCO
    from pycocotools.cocoeval import COCOeval

    if not results:
        return {k: 0.0 for k in METRIC_KEYS}
    with contextlib.redirect_stdout(io.StringIO()):
        coco_gt = COCO()
        coco_gt.dataset = json.loads(json.dumps(gt))
        coco_gt.createIndex()
        coco_dt = coco_gt.loadRes(results)
        ev = COCOeval(coco_gt, coco_dt, "bbox")
        ev.evaluate()
        ev.accumulate()
        ev.summarize()
    s = ev.stats
    return {"map": 100 * s[0], "ap50": 100 * s[1], "ap75": 100 * s[2], "ap_small": 100 * max(s[3], 0.0)}


def evaluate_detections(dets: list[FrameDetections], gt: dict) -> dict:
    ids = frame_image_ids(gt)
    metrics = coco_detection_metrics(gt, to_coco_results(dets, ids))
    metrics["frames_scored"] = min(len(dets), len(ids))
    return metrics


def pseudo_ground_truth(gt: dict, original_results: list[dict], score_threshold: float = 0.5) -> dict:
    """Ground truth built from the detector's own outputs on the *original* frames (same images/categories as
    ``gt``). Used as a fine-grained surrogate (e.g. RAMU-Lite ΔL) that never touches test labels."""
    anns = []
    for k, r in enumerate(r for r in original_results if r["score"] >= score_threshold):
        x, y, w, h = r["bbox"]
        anns.append({"id": k + 1, "image_id": r["image_id"], "category_id": r["category_id"],
                     "bbox": [x, y, w, h], "area": w * h, "iscrowd": 0})
    cats = gt.get("categories") or [{"id": c} for c in sorted({a["category_id"] for a in anns})]
    return {"images": gt["images"], "annotations": anns, "categories": cats}


def _spec_hash(spec: dict) -> str:
    return hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:16]


def _score(detector, spec, yuv: Path, seq, out_dir: Path, original_dir: Path | None = None) -> dict:
    gt = json.loads(Path(seq.annotations).read_text())
    dets = run_on_yuv(detector, yuv, seq.width, seq.height, seq.bitdepth, seq.frames,
                      spec.get("matrix", "bt709"), spec.get("full_range", False))
    results = to_coco_results(dets, frame_image_ids(gt))
    (out_dir / "detections.json").write_text(json.dumps(results))
    m = evaluate_detections(dets, gt)
    if original_dir is not None:
        orig = json.loads((original_dir / seq.name / "detections.json").read_text())
        pgt = pseudo_ground_truth(gt, orig, spec.get("pseudo_label_threshold", 0.5))
        m.update({f"pseudo_{k}": v for k, v in coco_detection_metrics(pgt, results).items()})
    m["detector_spec_sha"] = _spec_hash(spec)
    (out_dir / "task_metrics.json").write_text(json.dumps(m, indent=2))
    return m


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Compute task metrics on decoded (or original) sequences")
    ap.add_argument("--sequences", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--results", help="directory of job folders produced by vcm.jobs")
    ap.add_argument("--original", action="store_true", help="score the uncompressed sources instead")
    ap.add_argument("--out", help="output folder for --original")
    ap.add_argument("--pseudo", help="folder written by --original; adds pseudo-label metrics (pseudo_map, ...)")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)

    spec = yaml.safe_load(Path(a.config).read_text())["detector"]
    detector = build(spec)
    seqs = {s.name: s for s in load_sequences(a.sequences)}

    if a.original:
        root = Path(a.out or "results/original")
        for s in seqs.values():
            d = root / s.name
            d.mkdir(parents=True, exist_ok=True)
            if (d / "task_metrics.json").exists() and not a.force:
                continue
            m = _score(detector, spec, Path(s.path), s, d)
            print(f"{s.name:40s} original  map={m['map']:.2f}")
        return 0

    for mpath in sorted(Path(a.results).glob("*/manifest.json")):
        man = json.loads(mpath.read_text())
        d = mpath.parent
        if man.get("status") != "ok" or ((d / "task_metrics.json").exists() and not a.force):
            continue
        s = seqs[man["job"]["sequence"]["name"]]
        m = _score(detector, spec, d / "rec_dec.yuv", s, d, Path(a.pseudo) if a.pseudo else None)
        print(f"{man['job_id']:60s} map={m['map']:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
