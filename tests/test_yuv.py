import numpy as np
import pytest

from vcm.yuv import frame_bytes, num_frames, read_frames, to_rgb, write_frames


def test_frame_bytes():
    assert frame_bytes(416, 240, 8) == 416 * 240 * 3 // 2
    assert frame_bytes(416, 240, 10) == 416 * 240 * 3
    with pytest.raises(ValueError):
        frame_bytes(415, 240, 8)


@pytest.mark.parametrize("bitdepth", [8, 10])
def test_roundtrip(tmp_path, bitdepth):
    rng = np.random.default_rng(0)
    hi = (1 << bitdepth) - 1
    frames = [(rng.integers(0, hi, (8, 16)), rng.integers(0, hi, (4, 8)), rng.integers(0, hi, (4, 8)))
              for _ in range(3)]
    p = tmp_path / "x.yuv"
    write_frames(p, frames, bitdepth)
    assert num_frames(p, 16, 8, bitdepth) == 3
    back = list(read_frames(p, 16, 8, bitdepth, start=1, count=5))
    assert len(back) == 2
    for (y, u, v), (y0, u0, v0) in zip(back, frames[1:]):
        assert np.array_equal(y, y0) and np.array_equal(u, u0) and np.array_equal(v, v0)


def test_to_rgb_black_white_limited_range():
    y = np.array([[16, 235], [16, 235]], dtype=np.uint16)
    u = v = np.array([[128]], dtype=np.uint16)
    rgb = to_rgb(y, u, v, 8)
    assert rgb[0, 0].tolist() == [0, 0, 0]
    assert rgb[0, 1].tolist() == [255, 255, 255]


def test_to_rgb_10bit_matches_8bit():
    y8 = np.full((2, 2), 120, dtype=np.uint16)
    u8 = np.array([[90]], dtype=np.uint16)
    v8 = np.array([[170]], dtype=np.uint16)
    assert np.array_equal(to_rgb(y8, u8, v8, 8), to_rgb(y8 * 4, u8 * 4, v8 * 4, 10))
