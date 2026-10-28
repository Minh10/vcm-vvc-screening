import json

import numpy as np
import pytest

from vcm.curves import collect, compare, to_markdown, write_csv
from vcm.detect import FrameDetections, run_on_yuv, to_coco_results
from vcm.evaluate import _score, align, evaluate_detections, frame_image_ids, source_frame_ids
from vcm.yuv import write_frames

GT = {
    "images": [{"id": 11, "file_name": "f0.png", "frame_index": 0, "width": 64, "height": 64},
               {"id": 12, "file_name": "f1.png", "frame_index": 1, "width": 64, "height": 64}],
    "annotations": [
        {"id": 1, "image_id": 11, "category_id": 1, "bbox": [10, 10, 20, 20], "area": 400, "iscrowd": 0},
        {"id": 2, "image_id": 12, "category_id": 1, "bbox": [30, 30, 16, 16], "area": 256, "iscrowd": 0},
    ],
    "categories": [{"id": 1, "name": "obj"}],
}


def test_frame_image_ids_uses_frame_index_or_file_name():
    assert frame_image_ids(GT) == [11, 12]
    gt = {"images": [{"id": 5, "file_name": "b.png"}, {"id": 4, "file_name": "a.png"}]}
    assert frame_image_ids(gt) == [4, 5]


def test_perfect_and_empty_detections():
    perfect = [FrameDetections(0, np.array([[10, 10, 30, 30]]), np.array([0.9]), np.array([1])),
               FrameDetections(1, np.array([[30, 30, 46, 46]]), np.array([0.8]), np.array([1]))]
    m = evaluate_detections(perfect, GT)
    assert m["map"] == pytest.approx(100.0)
    assert m["frames_scored"] == 2
    empty = [FrameDetections(i, np.zeros((0, 4)), np.zeros(0), np.zeros(0, int)) for i in range(2)]
    assert evaluate_detections(empty, GT)["map"] == 0.0


def test_coco_results_skip_unannotated_frames():
    d = [FrameDetections(5, np.array([[0, 0, 1, 1]]), np.array([0.5]), np.array([1]))]
    assert to_coco_results(d, [11, 12]) == []



def _gt_every_frame(n, box_of):
    """GT annotating every source frame 0..n-1; object position depends on the source frame."""
    images = [{"id": 100 + f, "file_name": f"f{f:03d}.png", "frame_index": f, "width": 64, "height": 64}
              for f in range(n)]
    anns = [{"id": f + 1, "image_id": 100 + f, "category_id": 1, "bbox": list(box_of(f)), "area": 100, "iscrowd": 0}
            for f in range(n)]
    return {"images": images, "annotations": anns, "categories": [{"id": 1, "name": "obj"}]}


def _box(f):
    return (2 * f, 0, 10, 10)          # object moves 2 px per source frame


def _det_for_source(k, f):
    x, y, w, h = _box(f)
    return FrameDetections(k, np.array([[x, y, x + w, y + h]]), np.array([0.9]), np.array([1]))


def test_ai_subsampled_decoded_frames_map_to_source_frames():
    gt = _gt_every_frame(17, _box)
    # AI with TemporalSubsampleRatio 8: decoded frames 0,1,2 are source frames 0,8,16
    dets = [_det_for_source(k, 8 * k) for k in range(3)]
    m = evaluate_detections(dets, gt, frame_step=8)
    assert m["map"] == pytest.approx(100.0)
    assert m["alignment"]["gt_images_scored"] == 3
    assert m["alignment"]["gt_images_not_coded"] == 14          # excluded, not counted as misses
    # the old consecutive mapping would compare decoded frame 1 (source 8) with GT of source frame 1
    naive = evaluate_detections(dets, gt, frame_step=1)
    assert naive["map"] < 50


def test_ldp_every_frame_and_sparse_gt():
    gt = _gt_every_frame(6, _box)
    dets = [_det_for_source(k, k) for k in range(6)]
    assert evaluate_detections(dets, gt)["map"] == pytest.approx(100.0)
    sparse = {**gt, "images": gt["images"][::3], "annotations": gt["annotations"][::3]}   # GT on frames 0, 3
    m = evaluate_detections(dets, sparse)
    assert m["map"] == pytest.approx(100.0)
    assert m["alignment"]["decoded_frames_without_gt"] == 4
    off = evaluate_detections([_det_for_source(k, k + 3) for k in range(3)], gt, frame_offset=3)
    assert off["map"] == pytest.approx(100.0)


def test_gt_without_overlap_or_bad_index_fails():
    gt = _gt_every_frame(4, _box)
    gt_late = {**gt, "images": [dict(im, frame_index=im["frame_index"] + 100) for im in gt["images"]]}
    with pytest.raises(ValueError, match="no GT image"):
        evaluate_detections([_det_for_source(0, 0)], gt_late)
    dup = {**gt, "images": [dict(im, frame_index=0) for im in gt["images"]]}
    with pytest.raises(ValueError, match="duplicated"):
        source_frame_ids(dup)


def test_score_rejects_wrong_decoded_frame_count(tmp_path):
    from vcm.jobs import Sequence
    gt = _gt_every_frame(17, _box)
    (tmp_path / "gt.json").write_text(json.dumps(gt))
    yuv = tmp_path / "rec.yuv"
    write_frames(yuv, [(np.full((64, 64), 16), np.full((32, 32), 128), np.full((32, 32), 128))] * 2)
    seq = Sequence("s", str(yuv), 64, 64, 30, 17, annotations=str(tmp_path / "gt.json"))
    det = lambda rgb: (np.zeros((0, 4)), np.zeros(0), np.zeros(0, int))   # noqa: E731
    with pytest.raises(ValueError, match="expected 3"):
        _score(det, {}, yuv, seq, tmp_path, frame_step=8, expected_frames=3)


def test_run_on_yuv_with_fake_detector(tmp_path):
    p = tmp_path / "v.yuv"
    write_frames(p, [(np.full((8, 8), 16), np.full((4, 4), 128), np.full((4, 4), 128))] * 3)
    seen = []

    def fake(rgb):
        seen.append(rgb.shape)
        return np.array([[0, 0, 4, 4]]), np.array([1.0]), np.array([1])

    dets = run_on_yuv(fake, p, 8, 8, 8, frames=2)
    assert len(dets) == 2 and seen == [(8, 8, 3), (8, 8, 3)]


def _fake_results(root, seqs, rate_factor, test_variant="test", pseudo=False, same_bits=False, detector="x"):
    qps = [22, 27, 32, 37]
    base_rate = np.array([1600.0, 800.0, 400.0, 200.0])
    base_map = np.array([60.0, 57.0, 51.0, 42.0])
    for s in seqs:
        for variant, f in (("anchor", 1.0), (test_variant, rate_factor)):
            for qp, r, m in zip(qps, base_rate * f, base_map):
                d = root / f"{s}__ldp__qp{qp}__{variant}"
                d.mkdir(parents=True, exist_ok=True)
                sha = f"{s}{qp}" if same_bits or variant == "anchor" else f"{s}{qp}{variant}"
                (d / "manifest.json").write_text(json.dumps({
                    "status": "ok", "kbps": float(r), "bits": int(r * 1000), "recon_md5_decoder": f"md5{variant}",
                    "bitstream_sha256": sha, "pseudo_variant": pseudo and variant != "anchor",
                    "job": {"sequence": {"name": s, "split": "report"}, "structure": "ldp",
                            "variant": variant, "qp": qp}}))
                (d / "task_metrics.json").write_text(json.dumps({
                    "map": float(m), "detector_spec_sha": detector[:16],
                    "fingerprint": {"detector": detector, "recon_md5": f"md5{variant}"}}))


def test_compare_recovers_uniform_saving(tmp_path):
    _fake_results(tmp_path, [f"s{i}" for i in range(5)], 0.9)
    rows = collect(tmp_path)
    assert len(rows) == 5 * 2 * 4
    write_csv(rows, tmp_path / "points.csv")
    c = compare(rows, "anchor", "test", "ldp", "map", n_resamples=2000)
    assert all(r.value == pytest.approx(-10.0, abs=1e-6) for r in c.per_sequence_rate.values())
    assert c.rate_test.estimate == pytest.approx(-10.0, abs=1e-6)
    assert c.rate_test.p_value == pytest.approx(2 / 32)      # exact test, n = 5, all same sign
    assert c.excluded == []
    assert "s0" in to_markdown(c)


def test_compare_reports_excluded_sequences(tmp_path):
    _fake_results(tmp_path, ["s0", "s1"], 0.9)
    # break s1: make the anchor curve non-monotone so fewer than 4 Pareto points remain
    d = tmp_path / "s1__ldp__qp37__anchor"
    (d / "task_metrics.json").write_text(json.dumps({"map": 70.0}))
    c = compare(collect(tmp_path), "anchor", "test", "ldp", "map")
    assert c.excluded == ["s1"]
    assert c.rate_test is None        # only one valid sequence left


def test_evaluate_cache_follows_fingerprint(tmp_path, monkeypatch):
    import vcm.evaluate as ev
    from vcm.jobs import Sequence
    gt = _gt_every_frame(2, _box)
    gt_path = tmp_path / "gt.json"
    gt_path.write_text(json.dumps(gt))
    yuv = tmp_path / "rec_dec.yuv"
    write_frames(yuv, [(np.full((64, 64), 16), np.full((32, 32), 128), np.full((32, 32), 128))] * 2)
    job = tmp_path / "res" / "s__ldp__qp22__a"
    job.mkdir(parents=True)
    (job / "rec_dec.yuv").write_bytes(yuv.read_bytes())
    seqs = tmp_path / "s.csv"
    seqs.write_text(f"name,path,width,height,fps,frames,annotations\ns,{yuv},64,64,30,2,{gt_path}\n")
    man = {"job_id": job.name, "status": "ok", "frame_step": 1, "coded_frames": 2,
           "recon_md5_decoder": ev._md5(yuv), "job": {"sequence": {"name": "s"}}}
    (job / "manifest.json").write_text(json.dumps(man))
    cfg = tmp_path / "e.yaml"
    cfg.write_text("detector: {kind: fake, score_threshold: 0.1}\n")
    calls = []

    def fake(rgb):
        calls.append(1)
        return np.zeros((0, 4)), np.zeros(0), np.zeros(0, int)

    monkeypatch.setattr(ev, "build", lambda spec: fake)
    args = ["--results", str(tmp_path / "res"), "--sequences", str(seqs), "--config", str(cfg)]
    assert ev.main(args) == 0 and len(calls) == 2
    assert ev.main(args) == 0 and len(calls) == 2            # cached
    cfg.write_text("detector: {kind: fake, score_threshold: 0.2}\n")
    assert ev.main(args) == 0 and len(calls) == 4            # detector spec changed
    gt["annotations"][0]["bbox"] = [1, 1, 5, 5]
    gt_path.write_text(json.dumps(gt))
    assert ev.main(args) == 0 and len(calls) == 6            # GT changed
    (job / "rec_dec.yuv").write_bytes(b"\0" * len(yuv.read_bytes()))
    assert ev.main(args + ["--force"]) == 1                  # decoded file no longer matches its manifest


def test_curves_refuse_pseudo_variants_unless_allowed(tmp_path):
    _fake_results(tmp_path, [f"s{i}" for i in range(3)], 1.0, test_variant="o1a_relaxed_oracle", pseudo=True)
    rows = collect(tmp_path)
    with pytest.raises(ValueError, match="pseudo-variant"):
        compare(rows, "anchor", "o1a_relaxed_oracle", "ldp", "map")
    c = compare(rows, "anchor", "o1a_relaxed_oracle", "ldp", "map", allow_pseudo=True, n_resamples=100)
    assert c.pseudo and "not a coding result" in to_markdown(c)


def test_curves_flag_identical_bitstreams_and_stale_metrics(tmp_path):
    _fake_results(tmp_path, ["a", "b"], 1.0, same_bits=True)
    c = compare(collect(tmp_path), "anchor", "test", "ldp", "map", n_resamples=100)
    assert c.identical_bitstreams == ("a", "b")
    d = tmp_path / "a__ldp__qp22__test"
    man = json.loads((d / "manifest.json").read_text())
    man["recon_md5_decoder"] = "re-encoded"
    (d / "manifest.json").write_text(json.dumps(man))
    assert len(collect(tmp_path, verbose=False)) == 2 * 2 * 4 - 1      # stale metrics ignored


def test_curves_refuse_mixed_detectors(tmp_path):
    _fake_results(tmp_path, ["a"], 0.9)
    _fake_results(tmp_path / "x", ["b"], 0.9, detector="other")
    rows = collect(tmp_path) + collect(tmp_path / "x")
    with pytest.raises(ValueError, match="different detectors"):
        compare(rows, "anchor", "test", "ldp", "map")
