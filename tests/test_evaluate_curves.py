import json

import numpy as np
import pytest

from vcm.curves import collect, compare, to_markdown, write_csv
from vcm.detect import FrameDetections, run_on_yuv, to_coco_results
from vcm.evaluate import evaluate_detections, frame_image_ids
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


def test_run_on_yuv_with_fake_detector(tmp_path):
    p = tmp_path / "v.yuv"
    write_frames(p, [(np.full((8, 8), 16), np.full((4, 4), 128), np.full((4, 4), 128))] * 3)
    seen = []

    def fake(rgb):
        seen.append(rgb.shape)
        return np.array([[0, 0, 4, 4]]), np.array([1.0]), np.array([1])

    dets = run_on_yuv(fake, p, 8, 8, 8, frames=2)
    assert len(dets) == 2 and seen == [(8, 8, 3), (8, 8, 3)]


def _fake_results(root, seqs, rate_factor):
    qps = [22, 27, 32, 37]
    base_rate = np.array([1600.0, 800.0, 400.0, 200.0])
    base_map = np.array([60.0, 57.0, 51.0, 42.0])
    for s in seqs:
        for variant, f in (("anchor", 1.0), ("test", rate_factor)):
            for qp, r, m in zip(qps, base_rate * f, base_map):
                d = root / f"{s}__ldp__qp{qp}__{variant}"
                d.mkdir(parents=True)
                (d / "manifest.json").write_text(json.dumps({
                    "status": "ok", "kbps": float(r), "bits": int(r * 1000),
                    "job": {"sequence": {"name": s, "split": "report"}, "structure": "ldp",
                            "variant": variant, "qp": qp}}))
                (d / "task_metrics.json").write_text(json.dumps({"map": float(m), "detector_spec_sha": "x"}))


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
