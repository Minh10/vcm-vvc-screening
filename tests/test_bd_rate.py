import numpy as np
import pytest

from vcm.bd_rate import bd_quality, bd_rate, pareto_front

RATES = np.array([100.0, 200.0, 400.0, 800.0, 1600.0])
MAP = np.array([0.30, 0.42, 0.51, 0.57, 0.60])


def test_identical_curves_give_zero():
    assert bd_rate(RATES, MAP, RATES, MAP).value == pytest.approx(0.0, abs=1e-9)
    assert bd_quality(RATES, MAP, RATES, MAP).value == pytest.approx(0.0, abs=1e-9)


def test_uniform_rate_scaling_is_recovered_exactly():
    # Same quality at 80 % of the bits everywhere -> exactly -20 % BD-rate.
    res = bd_rate(RATES, MAP, RATES * 0.8, MAP)
    assert res.valid
    assert res.value == pytest.approx(-20.0, abs=1e-6)


def test_uniform_quality_shift_is_recovered_exactly():
    res = bd_quality(RATES, MAP, RATES, MAP + 0.01)
    assert res.value == pytest.approx(0.01, abs=1e-9)


def test_pareto_front_drops_non_monotone_point():
    r, q, dropped = pareto_front([100, 200, 400, 800], [0.30, 0.45, 0.44, 0.50])
    assert list(r) == [100, 200, 800]
    assert list(q) == [0.30, 0.45, 0.50]
    assert dropped == [2]


def test_too_few_monotone_points_is_nan_with_reason():
    res = bd_rate([100, 200, 400, 800], [0.3, 0.5, 0.4, 0.45], RATES, MAP)
    assert not res.valid
    assert "monotone" in res.reason
    assert res.dropped[0] == [2, 3]


def test_no_overlap_is_nan():
    res = bd_rate(RATES, MAP, RATES, MAP + 1.0)
    assert not res.valid
    assert "overlap" in res.reason


def test_rejects_non_positive_rates():
    with pytest.raises(ValueError):
        bd_rate([0, 1, 2, 3], [0.1, 0.2, 0.3, 0.4], RATES, MAP)
