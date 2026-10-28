import numpy as np
import pytest

from vcm.stats import align, bootstrap_ci, holm, paired_test, sign_flip_pvalue


def test_align_requires_same_sequences():
    with pytest.raises(ValueError, match="same sequences"):
        align({"a": 1.0, "b": 2.0}, {"a": 1.0})


def test_align_rejects_nan():
    with pytest.raises(ValueError, match="non-finite"):
        align({"a": float("nan")}, {"a": 0.0})


def test_exact_sign_flip_all_positive():
    # 5 identical positive diffs: only the all-+ and all-− patterns reach |mean| -> p = 2 / 32.
    assert sign_flip_pvalue([1.0] * 5) == pytest.approx(2 / 32)


def test_sign_flip_null_is_not_significant():
    assert sign_flip_pvalue([1.0, -1.0, 2.0, -2.0]) == pytest.approx(1.0)


def test_monte_carlo_branch_runs_and_is_bounded():
    rng = np.random.default_rng(1)
    p = sign_flip_pvalue(rng.normal(0.5, 1.0, size=30), n_resamples=2000)
    assert 0.0 < p <= 1.0


def test_bootstrap_ci_contains_true_center():
    d = np.linspace(-1.0, 3.0, 21)       # median 1.0
    lo, hi = bootstrap_ci(d, n_resamples=2000)
    assert lo <= 1.0 <= hi


def test_paired_test_summary():
    method = {"s1": -0.05, "s2": -0.04, "s3": -0.06, "s4": -0.03}
    control = {"s1": 0.0, "s2": 0.0, "s3": 0.0, "s4": 0.0}
    res = paired_test(method, control, n_resamples=2000)
    assert res.sequences == ["s1", "s2", "s3", "s4"]
    assert res.estimate == pytest.approx(-0.045)
    assert res.ci[1] < 0
    assert "n=4" in res.summary()


def test_holm_matches_hand_computation():
    adj = holm([0.01, 0.04, 0.03])
    # sorted: 0.01*3=0.03, 0.03*2=0.06, 0.04*1 -> max(0.06, 0.04)=0.06
    assert list(adj) == pytest.approx([0.03, 0.06, 0.06])
