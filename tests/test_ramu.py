import numpy as np
import pandas as pd
import pytest

from vcm.ramu.analysis import build_sequence_table, gate_a1, interactions, score_models, topk_regret
from vcm.ramu.features import FEATURE_SETS, graph_features, importance_from_boxes
from vcm.ramu.graph import Picture, build_edges, load_trace, node_table, shuffle_edges
from vcm.ramu.simulate import simulate_dataset

PIC = Picture(256, 128, 64)   # 4 x 2 CTUs of 64


def _cu(poc, co, x, y, w, h, mode="inter", r0=-1, m0=(0, 0), r1=-1, m1=(0, 0), qp=37, res=10.0, tid=1):
    return dict(poc=poc, coding_order=co, temporal_id=tid, x=x, y=y, w=w, h=h, qp=qp, mode=mode,
                ref_poc0=r0, mv0x=m0[0], mv0y=m0[1], ref_poc1=r1, mv1x=m1[0], mv1y=m1[1], resid_energy=res)


def test_picture_geometry():
    p = Picture(200, 100, 64)
    assert (p.cols, p.rows) == (4, 2)
    assert p.ctu_area(3) == 8 * 64 and p.ctu_area(7) == 8 * 36
    assert p.ctu_addr(130, 70) == 6


def test_edges_from_motion_shift_and_bi_prediction():
    trace = pd.DataFrame([
        _cu(0, 0, 0, 0, 64, 64, "intra", tid=0),
        # CTU 0 of poc 1 predicted from poc 0 shifted right by 32 -> half CTU 0, half CTU 1
        _cu(1, 1, 0, 0, 64, 64, r0=0, m0=(32, 0)),
        # CTU 2 of poc 1, bi-prediction from poc 0 at zero motion (both lists the same ref)
        _cu(1, 1, 128, 0, 64, 64, r0=0, r1=0),
    ])
    e = build_edges(trace, PIC)
    assert e[((0, 0), (1, 0))] == pytest.approx(0.5)
    assert e[((0, 1), (1, 0))] == pytest.approx(0.5)
    assert e[((0, 2), (1, 2))] == pytest.approx(1.0)       # two halves from the same CTU
    assert all(dst[0] == 1 for _, dst in e)


def test_edges_clip_outside_picture():
    trace = pd.DataFrame([_cu(1, 1, 0, 0, 64, 64, r0=0, m0=(-32, 0))])
    assert build_edges(trace, PIC) == {((0, 0), (1, 0)): pytest.approx(0.5)}


def test_load_trace_validates(tmp_path):
    p = tmp_path / "t.csv"
    pd.DataFrame([_cu(0, 0, 0, 0, 8, 8)]).drop(columns=["qp"]).to_csv(p, index=False)
    with pytest.raises(ValueError, match="missing"):
        load_trace(p)


def test_node_table_aggregates_area_weighted():
    trace = pd.DataFrame([_cu(1, 1, 0, 0, 32, 64, "skip", r0=0, qp=30), _cu(1, 1, 32, 0, 32, 64, "intra", qp=40)])
    n = node_table(trace, PIC).iloc[0]
    assert n.skip_frac == pytest.approx(0.5) and n.intra_frac == pytest.approx(0.5)
    assert n.mean_qp == pytest.approx(35.0)


def test_graph_features_chain():
    # (0,0) -> (1,0) -> (2,0), weights 1.0 and 0.5
    edges = {((0, 0), (1, 0)): 1.0, ((1, 0), (2, 0)): 0.5}
    nodes = pd.DataFrame({"poc": [0, 1, 2], "ctu_addr": [0, 0, 0], "coding_order": [0, 1, 2],
                          "imp": [0.0, 2.0, 4.0]})
    g = graph_features(edges, nodes, rho=0.5).set_index("poc")
    assert g.loc[2, "depth"] == 0 and g.loc[1, "depth"] == 1 and g.loc[0, "depth"] == 2
    assert g.loc[1, "infl"] == pytest.approx(0.5)
    assert g.loc[0, "infl"] == pytest.approx(1.0 * (1 + 0.5 * 0.5))
    assert g.loc[0, "fanout_imp1"] == pytest.approx(2.0)
    assert g.loc[0, "infl_imp"] == pytest.approx(1.0 * (2.0 + 0.5 * (0.5 * 4.0)))


def test_shuffle_preserves_source_fanout():
    rng = np.random.default_rng(0)
    edges = {((0, a), (1, b)): float(rng.uniform()) for a in range(4) for b in range(4) if rng.uniform() < 0.6}
    s = shuffle_edges(edges, seed=3)
    out = lambda e: {u: sum(w for (uu, _), w in e.items() if uu == u) for (u, _) in e}
    assert out(s) == pytest.approx(out(edges))
    assert sum(s.values()) == pytest.approx(sum(edges.values()))


def test_importance_from_boxes():
    boxes = pd.DataFrame({"poc": [0, 0], "x0": [0, 0], "y0": [0, 0], "x1": [64, 32], "y1": [64, 32],
                          "score": [1.0, 0.1]})
    imp = importance_from_boxes(boxes, PIC, score_threshold=0.3)
    assert imp.to_dict("records") == [{"poc": 0, "ctu_addr": 0, "imp": 1.0}]


def test_feature_sets_are_nested_as_designed():
    b3, b4, b5 = (set(FEATURE_SETS[k]) for k in ("B3", "B4", "B5"))
    assert b3 < b4 and b3 < b5
    assert {"infl", "depth"} <= b3                    # task-agnostic propagation lives in the baseline
    assert b4 - b3 == {"fanout_imp1", "infl_imp"}
    assert b5 - b3 == {"fanout_imp1_shuf", "infl_imp_shuf"}


def test_build_sequence_table_rejects_unknown_ctu():
    trace = pd.DataFrame([_cu(0, 0, 0, 0, 64, 64, "intra"), _cu(1, 1, 0, 0, 64, 64, r0=0)])
    boxes = pd.DataFrame(columns=["poc", "x0", "y0", "x1", "y1", "score"])
    iv = pd.DataFrame({"poc": [0], "ctu_addr": [0], "delta_qp": [-2], "delta_loss": [-0.1], "delta_bits": [100]})
    assert len(build_sequence_table("s", PIC, trace, boxes, iv)) == 1
    with pytest.raises(ValueError, match="absent"):
        build_sequence_table("s", PIC, trace, boxes, iv.assign(ctu_addr=5))


def test_topk_regret():
    true = np.array([-3.0, -2.0, -1.0, 0.0])          # benefit 3, 2, 1, 0
    assert topk_regret(true, true, 0.5) == 0.0          # perfect ranking
    assert topk_regret(-true, true, 0.5) == pytest.approx(1 - 1 / 5)   # picks benefits 0 and 1


def test_interactions():
    singles = pd.DataFrame({"sequence": "s", "poc": [1, 2], "ctu_addr": [0, 0],
                            "delta_loss": [-1.0, -2.0], "delta_bits": [10.0, 20.0]})
    pairs = pd.DataFrame({"sequence": ["s"], "poc_a": [1], "ctu_a": [0], "poc_b": [2], "ctu_b": [0],
                          "same_branch": [True], "delta_loss": [-2.5], "delta_bits": [33.0]})
    r = interactions(singles, pairs).iloc[0]
    assert r.mean_I_L == pytest.approx(0.5) and r.mean_I_R == pytest.approx(3.0)


@pytest.mark.parametrize("scenario, expected", [("signal", "GO"), ("null", "NO-GO")])
def test_gate_separates_simulated_scenarios(scenario, expected):
    df = simulate_dataset(scenario, n_sequences=8, seed=7, frames=12, cols=6, rows=4, n_interventions=50)
    gate = gate_a1(score_models(df, "ridge", 0.1, 7), n_resamples=1000, seed=7)
    assert gate["decision"] == expected
