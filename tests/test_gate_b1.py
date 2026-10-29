"""Gate B-1 decisions on synthetic rate–task curves."""

import numpy as np
import pytest

from vcm.alf.gate import gate_b1, to_markdown

QPS = [22, 27, 32, 37]
RATE = np.array([1600.0, 800.0, 400.0, 200.0])
MAP = np.array([60.0, 57.0, 51.0, 42.0])


def _rows(n_seq=8, weighted=0.9, shuffled=1.0, uniform_same=True, seeds=5, seed=0):
    rng = np.random.default_rng(seed)
    arms = {"alf_default": 1.0, "alf_weighted": weighted, "alf_weighted_uniform": 1.0}
    arms.update({f"alf_weighted_shuffled_s{k}": shuffled for k in range(seeds)})
    rows = []
    for i in range(n_seq):
        jitter = 1 + 0.01 * rng.standard_normal()
        for v, f in arms.items():
            for qp, r, m in zip(QPS, RATE, MAP):
                fac = f * (jitter if v == "alf_weighted" else 1.0) * (1 + 0.002 * rng.standard_normal()
                                                                       if "shuffled" in v else 1.0)
                same = v == "alf_default" or (v == "alf_weighted_uniform" and uniform_same)
                rows.append({"sequence": f"s{i}", "split": "report", "structure": "ldp", "variant": v, "qp": qp,
                             "kbps": float(r * fac), "bits": int(r * fac * 1000), "pseudo_variant": False,
                             "bitstream_sha256": f"s{i}q{qp}" if same else f"s{i}q{qp}{v}", "detector": "d",
                             "map": float(m)})
    return rows


def test_go_when_beating_default_and_shuffled():
    g = gate_b1(_rows(), "ldp", n_resamples=2000)
    assert g["decision"] == "GO"
    assert g["vs_default"]["mean_bd_rate"] == pytest.approx(-10, abs=1.0)
    assert g["vs_shuffled"]["n"] == 8 and g["vs_shuffled"]["mean_bd_rate"] < -8
    assert "Decision: GO" in to_markdown(g)


def test_gain_shared_by_shuffled_control_is_not_attributed():
    g = gate_b1(_rows(shuffled=0.9), "ldp", n_resamples=2000)
    assert g["vs_default"]["pass"] and not g["vs_shuffled"]["pass"]
    assert g["decision"] == "NO-GO (gain not attributable to object alignment)"


def test_no_gain_and_invalid_cases():
    assert gate_b1(_rows(weighted=1.05), "ldp", n_resamples=2000)["decision"] == "NO-GO"
    g = gate_b1(_rows(uniform_same=False), "ldp", n_resamples=2000)
    assert g["decision"] == "INVALID" and len(g["validity"]["uniform"]["differ"]) == 8 * 4
    rows = [r for r in _rows() if r["variant"] != "alf_weighted_uniform"]
    assert gate_b1(rows, "ldp", n_resamples=2000)["decision"] == "INVALID"
    assert gate_b1(_rows(seeds=0), "ldp", n_resamples=2000)["decision"] == "INVALID"


def test_holm_needs_enough_sequences():
    g = gate_b1(_rows(n_seq=6), "ldp", n_resamples=2000)       # exact sign-flip p = 1/32, Holm 1/16 > 0.05
    assert not g["vs_default"]["criteria"]["p_holm_below_alpha"] and g["decision"] != "GO"
