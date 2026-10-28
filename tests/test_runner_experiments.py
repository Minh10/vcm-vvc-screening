"""RAMU-Lite runner (sampling, job construction, collection), branch-B drivers and pseudo-label scoring."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from vcm.alf import dump, experiments, project, spec
from vcm.evaluate import coco_detection_metrics, pseudo_ground_truth
from vcm.jobs import Sequence
from vcm.ramu import runner
from vcm.ramu.graph import Picture

PIC = Picture(256, 128, 64)


def _trace(rng):
    rows = []
    for poc in range(6):
        for addr in range(8):
            x, y = (addr % 4) * 64, (addr // 4) * 64
            intra = poc == 0
            resid = float(rng.integers(0, 3) * 10) if addr % 2 == 0 else 0.0     # odd CTUs: no residual
            rows.append(dict(poc=poc, coding_order=poc, temporal_id=0 if poc % 4 == 0 else 1, x=x, y=y, w=64,
                             h=64, qp=32, mode="intra" if intra else ("inter" if resid else "skip"),
                             ref_poc0=-1 if intra else poc - 1, mv0x=float(rng.integers(-8, 9)), mv0y=0.0,
                             ref_poc1=-1, mv1x=0.0, mv1y=0.0, resid_energy=resid))
    return pd.DataFrame(rows)


def test_sampling_only_uses_valid_ctus_and_stratifies():
    rng = np.random.default_rng(0)
    trace = _trace(rng)
    boxes = pd.DataFrame({"poc": range(6), "x0": 0, "y0": 0, "x1": 100, "y1": 64, "score": 0.9})
    nodes = runner.candidate_table(trace, boxes, PIC)
    assert not nodes.loc[nodes.ctu_addr % 2 == 1, "valid"].any()          # no residual -> not eligible
    s = runner.sample(nodes, 10, seed=1)
    assert len(s) == min(10, int(nodes.valid.sum()))
    assert set(map(tuple, s[["poc", "ctu_addr"]].values)) <= set(map(tuple, nodes.loc[nodes.valid, ["poc", "ctu_addr"]].values))
    assert (s.delta_qp == -2).all() and s.stratum.between(0, 7).all()
    pairs = runner.sample_pairs(trace, PIC, s, 6, seed=1)
    assert set(pairs.columns) == {"poc_a", "ctu_a", "poc_b", "ctu_b", "same_branch"}


def test_sampling_fails_without_valid_ctus():
    trace = _trace(np.random.default_rng(0)).assign(resid_energy=0.0)
    nodes = runner.candidate_table(trace, pd.DataFrame(columns=["poc", "x0", "y0", "x1", "y1", "score"]), PIC)
    with pytest.raises(ValueError, match="no valid"):
        runner.sample(nodes, 5)


def test_build_jobs_and_collect(tmp_path):
    seq = Sequence("s", "s.yuv", 256, 128, 30, 6)
    cand = tmp_path / "cand"
    cand.mkdir()
    jobs = runner.build_jobs(cand, seq, "ldp", 32, tmp_path / "runs")
    assert [j.variant for j in jobs] == ["dqp_anchor"]                     # anchor first, before sampling
    pd.DataFrame({"poc": [1, 2], "ctu_addr": [3, 4], "delta_qp": [-2, -2], "stratum": [0, 1]}) \
        .to_csv(cand / "candidates.csv", index=False)
    pd.DataFrame({"poc_a": [1], "ctu_a": [3], "poc_b": [2], "ctu_b": [4], "same_branch": [True]}) \
        .to_csv(cand / "pairs.csv", index=False)
    jobs = runner.build_jobs(cand, seq, "ldp", 32, tmp_path / "runs")
    assert len(jobs) == 1 + 2 + 1
    iv = Path(jobs[1].extra_args[0].split("=", 1)[1]).read_text().splitlines()
    assert iv == ["poc,ctu_addr,delta_qp", "1,3,-2"]
    assert "--VCMTraceFile=" in jobs[0].extra_args[1]
    # fake finished runs
    for j, (bits, pm, m) in zip(jobs, [(1000, 60.0, 50.0), (1100, 61.0, 50.5), (1050, 59.0, 49.0), (1200, 61.5, 50.0)]):
        d = tmp_path / "runs" / j.job_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "manifest.json").write_text(json.dumps({"bits": bits}))
        (d / "task_metrics.json").write_text(json.dumps({"map": m, "pseudo_map": pm}))
    singles, pairs = runner.collect(tmp_path / "runs", cand, "ldp", 32, "s")
    assert singles.delta_bits.tolist() == [100, 50]
    assert singles.delta_loss.tolist() == pytest.approx([-0.01, 0.01])
    assert (singles.loss_source == "pseudo_map").all()
    assert pairs.delta_bits.tolist() == [200]


def test_pseudo_ground_truth_scores_identity_as_perfect():
    gt = {"images": [{"id": 1, "file_name": "a", "frame_index": 0}], "annotations": [],
          "categories": [{"id": 3, "name": "car"}]}
    orig = [{"image_id": 1, "category_id": 3, "bbox": [10, 10, 20, 20], "score": 0.9},
            {"image_id": 1, "category_id": 3, "bbox": [50, 50, 10, 10], "score": 0.2}]
    pgt = pseudo_ground_truth(gt, orig, 0.5)
    assert len(pgt["annotations"]) == 1
    assert coco_detection_metrics(pgt, orig[:1])["map"] == pytest.approx(100.0)


@pytest.fixture
def fake_dump(tmp_path):
    rng = np.random.default_rng(9)
    h, w, bd = 32, 48, 10
    d = tmp_path / "dump"
    d.mkdir()
    (d / "meta.txt").write_text(f"width {w}\nheight {h}\nbitdepth {bd}\nctu_size 16\nvb_pos 12\n")
    coeff = rng.integers(-20, 21, (25, 12))
    clipv = spec.clip_values(bd)[rng.integers(0, 4, (25, 12))]
    for poc in range(2):
        org = np.clip(512 + rng.normal(0, 60, (h, w)), 0, 1023).astype(np.int64)
        pre = np.clip(org + rng.normal(0, 15, (h, w)), 0, 1023).astype(np.int64)
        cls, tr = spec.classify(pre, bd, 16)
        post = spec.apply(pre, cls, tr, coeff, dump.clip_index(clipv, bd), bd, ctu_size=16)
        for name, a in (("pre", pre), ("org", org), ("post", post)):
            a.astype("<i2").tofile(d / f"{name}_{poc}.y16")
        lines = [f"# vcm-alf-ctb-v1 poc {poc} luma_enabled 1"]
        for ctb in range(6):
            lines.append(f"CTB {ctb} 16")
            lines += [" ".join(map(str, [*coeff[c], *clipv[c]])) for c in range(25)]
        (d / f"ctb_{poc}.txt").write_text("\n".join(lines) + "\n")
    return d, coeff, clipv


def test_dump_reproduce_and_anchor_init(fake_dump):
    d, coeff, clipv = fake_dump
    ours, post = dump.reproduce(d, 1)
    assert np.array_equal(ours, post)
    g, clip = experiments._anchor_init(d, 0)
    assert np.allclose(g * 128, coeff) and np.array_equal(spec.clip_values(10)[clip], clipv)


def test_wiener_and_weights_commands(fake_dump, tmp_path):
    d, _, _ = fake_dump
    out = tmp_path / "w.txt"
    experiments.main(["wiener", "--dump", str(d), "--out", str(out)])
    assert sorted(project.read(out)) == [0, 1]
    gt = {"images": [{"id": 7, "file_name": "a", "frame_index": 0}, {"id": 8, "file_name": "b", "frame_index": 1}]}
    det = [{"image_id": 8, "category_id": 1, "bbox": [0, 0, 24, 16], "score": 0.9}]
    (tmp_path / "gt.json").write_text(json.dumps(gt))
    (tmp_path / "det.json").write_text(json.dumps(det))
    wd = tmp_path / "wmaps"
    experiments.main(["weights", "--detections", str(tmp_path / "det.json"), "--gt", str(tmp_path / "gt.json"),
                      "--width", "48", "--height", "32", "--pocs", "2", "--out", str(wd)])
    w0 = np.fromfile(wd / "w_0.f32", "<f4").reshape(32, 48)
    w1 = np.fromfile(wd / "w_1.f32", "<f4").reshape(32, 48)
    assert np.allclose(w0, 1.0)                                   # no boxes -> uniform (mean-normalised)
    assert w1.mean() == pytest.approx(1.0, rel=1e-5) and w1[0, 0] > w1[-1, -1]
    experiments.main(["wiener", "--dump", str(d), "--weights", str(wd), "--out", str(tmp_path / "ww.txt")])
    assert sorted(project.read(tmp_path / "ww.txt")) == [0, 1]
