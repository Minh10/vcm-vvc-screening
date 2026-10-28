"""Torch-dependent ALF tools: differentiable ALF, O1-A optimiser, Hutchinson weights."""

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from vcm.alf import oracle, spec, weights  # noqa: E402
from vcm.yuv import to_rgb  # noqa: E402


@pytest.fixture(scope="module")
def frame():
    rng = np.random.default_rng(11)
    yy, xx = np.mgrid[0:32, 0:32]
    y = np.clip(500 + 150 * np.sin(xx / 2.0) + 80 * np.cos(yy / 3.0) + rng.normal(0, 15, xx.shape), 64, 940)
    u = np.full((16, 16), 512.0)
    v = np.full((16, 16), 512.0)
    return y.astype(np.int64), u, v


def test_rgb_conversion_matches_numpy(frame):
    y, u, v = frame
    rgb_t = oracle.yuv_to_rgb(torch.tensor(y, dtype=torch.float32), torch.tensor(u), torch.tensor(v), 10)
    rgb_n = to_rgb(y.astype(np.uint16), u.astype(np.uint16), v.astype(np.uint16), 10)
    assert np.max(np.abs(rgb_t.permute(1, 2, 0).numpy() * 255 - rgb_n)) <= 0.51


def test_differentiable_alf_matches_integer_filter(frame):
    y, _, _ = frame
    cls, tr = spec.classify(y, 10, ctu_size=16)
    rng = np.random.default_rng(1)
    coeff = rng.integers(-30, 31, size=(25, 12))
    ref = spec.apply(y, cls, tr, coeff, np.zeros((25, 12), int), 10, ctu_size=16)
    alf = oracle.DifferentiableALF(y, cls, tr, 10, ctu_size=16)
    out = alf(torch.tensor(coeff / 128.0, dtype=torch.float32)).numpy()
    assert np.max(np.abs(out - ref)) <= 1.0            # only the integer rounding differs


def test_optimise_reduces_feature_loss(frame):
    y, u, v = frame
    torch.manual_seed(0)
    net = torch.nn.Sequential(torch.nn.Conv2d(3, 4, 3, padding=1), torch.nn.ReLU(), torch.nn.Conv2d(4, 4, 3))
    for p in net.parameters():
        p.requires_grad_(False)
    rng = np.random.default_rng(2)
    target = oracle.yuv_to_rgb(torch.tensor(y, dtype=torch.float32), torch.tensor(u), torch.tensor(v), 10)[None]
    degraded = np.clip(y + rng.normal(0, 25, y.shape), 0, 1023).astype(np.int64)   # stands in for "decoded"
    cls, tr = spec.classify(degraded, 10, ctu_size=16)
    alf = oracle.DifferentiableALF(degraded, cls, tr, 10, ctu_size=16)
    g, hist = oracle.optimise(alf, u, v, 10, oracle.feature_loss(net, target), steps=60, lr=0.02)
    assert hist[-1] < 0.9 * hist[0]
    assert g.max() <= 127 / 128 + 1e-6 and g.min() >= -1.0 - 1e-6


def test_hutchinson_identity_features(frame):
    y, u, v = frame
    d = weights.hutchinson_luma(lambda rgb: rgb, y, u, v, 10, samples=200, seed=0, normalise=False)
    expected = 3.0 / (4 * 219.0) ** 2           # each RGB channel moves by 1/(scale*219) per luma step
    assert np.mean(d) == pytest.approx(expected, rel=0.15)


def test_box_weights():
    w = weights.box_weights(np.array([[2, 2, 6, 6], [0, 0, 8, 8]]), np.array([0.9, 0.1]), 8, 8, bg=0.2)
    assert w[0, 0] == pytest.approx(0.2) and w[3, 3] == pytest.approx(0.2 + 0.8 * 0.9)
