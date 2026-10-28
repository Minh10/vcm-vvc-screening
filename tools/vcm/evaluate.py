"""Task metrics on decoder output.

Detection: COCO-style AP via pycocotools against a per-sequence COCO ground-truth file. Values are reported in
percent: ``map`` (AP@[.5:.95]), ``ap50``, ``ap75``, ``ap_small``. Which one is the primary metric is fixed in
``configs/experiment.yaml`` (``evaluation.primary_metric``) from the CTC document during P0.

Frame alignment (decoded frame -> source frame -> GT image)
-----------------------------------------------------------
* GT images carry ``frame_index`` = 0-based index of the frame **in the source sequence** (gaps allowed, e.g.
  annotations only every 8th frame). Without ``frame_index``, images sorted by ``file_name`` are taken to be
  source frames 0, 1, 2, … (recorded as ``frame_mapping = "file_name_order"``).
* Decoded frame k is source frame ``frame_offset + k * frame_step`` (from the job manifest: the encoder's
  FrameSkip and TemporalSubsampleRatio; step 1 for LDP/RA, 8 for the VTM AI cfg).
* Scoring uses only GT images of coded source frames. GT images of frames that were not coded are excluded (not
  counted as misses); decoded frames without a GT image are not scored. Counts of both are recorded.
* The decoded file must contain exactly ``coded_frames`` frames, otherwise the job is rejected.

Caching: ``task_metrics.json`` stores a fingerprint (detector spec + weights hash, decoded-file MD5 from the
manifest, GT hash, frame step, pseudo-label source hash). It is recomputed whenever the fingerprint changes.

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
import os
import time
from pathlib import Path

import yaml

from .detect import FrameDetections, build, run_on_yuv, to_coco_results
from .jobs import _sha_file, load_sequences

METRIC_KEYS = ("map", "ap50", "ap75", "ap_small")
EVAL_VERSION = 2


def source_frame_ids(gt: dict) -> tuple[dict[int, int], str]:
    """Map source frame index -> GT image id, and the rule used (``frame_index`` or ``file_name_order``)."""
    images = gt["images"]
    if images and all("frame_index" in im for im in images):
        out: dict[int, int] = {}
        for im in images:
            f = int(im["frame_index"])
            if f < 0 or f in out:
                raise ValueError(f"frame_index {f} is negative or duplicated")
            out[f] = im["id"]
        return out, "frame_index"
    if any("frame_index" in im for im in images):
        raise ValueError("frame_index present on some GT images only")
    ordered = sorted(images, key=lambda im: im["file_name"])
    return {f: im["id"] for f, im in enumerate(ordered)}, "file_name_order"


def frame_image_ids(gt: dict) -> list[int]:
    """GT image ids in source-frame order (kept for callers that only need the order)."""
    ids, _ = source_frame_ids(gt)
    return [ids[f] for f in sorted(ids)]


def gt_subset(gt: dict, image_ids: set[int]) -> dict:
    return {**gt, "images": [im for im in gt["images"] if im["id"] in image_ids],
            "annotations": [a for a in gt.get("annotations", []) if a["image_id"] in image_ids]}


def align(dets: list[FrameDetections], gt: dict, frame_step: int = 1,
          frame_offset: int = 0) -> tuple[list[FrameDetections], dict, dict]:
    """Renumber decoded detections to source frames and restrict GT to the coded frames.

    Returns (detections indexed by source frame, GT subset, alignment report)."""
    if frame_step < 1:
        raise ValueError("frame_step must be >= 1")
    ids, rule = source_frame_ids(gt)
    src = [FrameDetections(frame_offset + d.frame * frame_step, d.boxes, d.scores, d.labels) for d in dets]
    coded = {d.frame for d in src}
    kept = {img for f, img in ids.items() if f in coded}
    sub = gt_subset(gt, kept)
    report = {"frame_mapping": rule, "frame_step": frame_step, "frame_offset": frame_offset, "decoded_frames": len(dets),
              "gt_images_total": len(ids), "gt_images_scored": len(kept),
              "gt_images_not_coded": len(ids) - len(kept),
              "decoded_frames_without_gt": sum(1 for f in coded if f not in ids),
              "gt_annotations_scored": len(sub["annotations"])}
    return src, sub, report


def coco_detection_metrics(gt: dict, results: list[dict]) -> dict[str, float]:
    from pycocotools.coco import COCO
    from pycocotools.cocoeval import COCOeval

    if not gt["images"]:
        raise ValueError("no GT image overlaps the coded frames; check frame_index / frame_step")
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


def evaluate_detections(dets: list[FrameDetections], gt: dict, frame_step: int = 1, frame_offset: int = 0) -> dict:
    src, sub, report = align(dets, gt, frame_step, frame_offset)
    ids, _ = source_frame_ids(sub)
    metrics = coco_detection_metrics(sub, to_coco_results(src, ids))
    metrics["frames_scored"] = report["gt_images_scored"]
    metrics["alignment"] = report
    return metrics


def pseudo_ground_truth(gt: dict, original_results: list[dict], score_threshold: float = 0.5) -> dict:
    """Ground truth built from the detector's own outputs on the *original* frames (same images/categories as
    ``gt``). Used as a fine-grained surrogate (e.g. RAMU-Lite ΔL) that never touches test labels."""
    image_ids = {im["id"] for im in gt["images"]}
    anns = []
    for r in original_results:
        if r["score"] < score_threshold or r["image_id"] not in image_ids:
            continue
        x, y, w, h = r["bbox"]
        anns.append({"id": len(anns) + 1, "image_id": r["image_id"], "category_id": r["category_id"],
                     "bbox": [x, y, w, h], "area": w * h, "iscrowd": 0})
    cats = gt.get("categories") or [{"id": c} for c in sorted({a["category_id"] for a in anns})]
    return {"images": gt["images"], "annotations": anns, "categories": cats}


def detector_fingerprint(spec: dict) -> str:
    """Hash of the detector spec plus the content of every file it references (config, weights)."""
    files = {k: _sha_file(Path(v)) for k, v in sorted(spec.items())
             if isinstance(v, str) and v and os.path.isfile(v)}
    return hashlib.sha256(json.dumps({"spec": spec, "files": files}, sort_keys=True).encode()).hexdigest()


def _fingerprint(det_fp: str, recon_md5: str, seq, frame_step: int, original_dir: Path | None,
                 frame_offset: int = 0) -> dict:
    fp = {"version": EVAL_VERSION, "detector": det_fp, "recon_md5": recon_md5,
          "gt_sha256": _sha_file(Path(seq.annotations)), "frame_step": frame_step, "frame_offset": frame_offset,
          "pseudo_source": None}
    if original_dir is not None:
        fp["pseudo_source"] = _sha_file(original_dir / seq.name / "detections.json")
    fp["hash"] = hashlib.sha256(json.dumps(fp, sort_keys=True).encode()).hexdigest()
    return fp


def _md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _cached(out_dir: Path, fp: dict) -> bool:
    p = out_dir / "task_metrics.json"
    return p.exists() and json.loads(p.read_text()).get("fingerprint", {}).get("hash") == fp["hash"]


def _score(detector, spec, yuv: Path, seq, out_dir: Path, original_dir: Path | None = None,
           frame_step: int = 1, expected_frames: int | None = None, fingerprint: dict | None = None,
           frame_offset: int = 0) -> dict:
    gt = json.loads(Path(seq.annotations).read_text())
    n = expected_frames if expected_frames is not None else -(-(seq.frames) // frame_step)
    t0 = time.time()
    dets = run_on_yuv(detector, yuv, seq.width, seq.height, seq.bitdepth, None,
                      spec.get("matrix", "bt709"), spec.get("full_range", False))
    detector_seconds = round(time.time() - t0, 3)
    if len(dets) != n:
        raise ValueError(f"{yuv}: {len(dets)} frames decoded, expected {n} (frame_step={frame_step})")
    src, sub, report = align(dets, gt, frame_step, frame_offset)
    ids, _ = source_frame_ids(sub)
    results = to_coco_results(src, ids)
    (out_dir / "detections.json").write_text(json.dumps(results))
    m = coco_detection_metrics(sub, results)
    m["frames_scored"] = report["gt_images_scored"]
    m["alignment"] = report
    m["detector_seconds"] = detector_seconds
    if original_dir is not None:
        orig = json.loads((original_dir / seq.name / "detections.json").read_text())
        pgt = pseudo_ground_truth(sub, orig, spec.get("pseudo_label_threshold", 0.5))
        m.update({f"pseudo_{k}": v for k, v in coco_detection_metrics(pgt, results).items()})
    m["detector_spec_sha"] = (fingerprint or {}).get("detector", detector_fingerprint(spec))[:16]
    m["fingerprint"] = fingerprint or {}
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
    ap.add_argument("--force", action="store_true", help="recompute even if the fingerprint matches")
    a = ap.parse_args(argv)

    spec = yaml.safe_load(Path(a.config).read_text())["detector"]
    detector = build(spec)
    det_fp = detector_fingerprint(spec)
    seqs = {s.name: s for s in load_sequences(a.sequences)}

    if a.original:
        root = Path(a.out or "results/original")
        for s in seqs.values():
            d = root / s.name
            d.mkdir(parents=True, exist_ok=True)
            fp = _fingerprint(det_fp, f"source:{_sha_file(Path(s.path))}", s, 1, None)
            if _cached(d, fp) and not a.force:
                continue
            m = _score(detector, spec, Path(s.path), s, d, None, 1, s.frames, fp)
            print(f"{s.name:40s} original  map={m['map']:.2f}")
        return 0

    failures = 0
    for mpath in sorted(Path(a.results).glob("*/manifest.json")):
        man = json.loads(mpath.read_text())
        d = mpath.parent
        if man.get("status") != "ok":
            continue          # pseudo-variants (O1-A) are scored like any decoded output; vcm.curves guards them
        s = seqs[man["job"]["sequence"]["name"]]
        step, offset = int(man.get("frame_step", 1)), int(man.get("frame_offset", 0))
        fp = _fingerprint(det_fp, man["recon_md5_decoder"], s, step, Path(a.pseudo) if a.pseudo else None, offset)
        if _cached(d, fp) and not a.force:
            continue
        try:
            if _md5(d / "rec_dec.yuv") != man["recon_md5_decoder"]:
                raise ValueError("rec_dec.yuv does not match the MD5 recorded in its manifest")
            m = _score(detector, spec, d / "rec_dec.yuv", s, d, Path(a.pseudo) if a.pseudo else None,
                       step, man.get("coded_frames"), fp, offset)
            print(f"{man['job_id']:60s} map={m['map']:.2f}")
        except ValueError as exc:
            failures += 1
            print(f"FAIL {man['job_id']}: {exc}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
