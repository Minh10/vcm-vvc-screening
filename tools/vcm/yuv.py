"""Raw planar YUV 4:2:0 I/O and conversion to RGB for detectors.

The colour conversion used to feed the detector is part of the evaluation protocol: it must match the one the
VCM CTC prescribes and must be pinned in P0. Defaults here are BT.709, limited range, nearest-neighbour chroma
upsampling; change them only through the function arguments so the choice is recorded in the run manifest.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import numpy as np

_MATRICES = {"bt709": (0.2126, 0.0722), "bt601": (0.299, 0.114)}


def bytes_per_sample(bitdepth: int) -> int:
    if not 8 <= bitdepth <= 16:
        raise ValueError("bitdepth must be in [8, 16]")
    return 1 if bitdepth == 8 else 2


def frame_bytes(width: int, height: int, bitdepth: int) -> int:
    if width % 2 or height % 2:
        raise ValueError("4:2:0 requires even width and height")
    return (width * height * 3 // 2) * bytes_per_sample(bitdepth)


def num_frames(path: str | Path, width: int, height: int, bitdepth: int) -> int:
    size = Path(path).stat().st_size
    fb = frame_bytes(width, height, bitdepth)
    if size % fb:
        raise ValueError(f"{path}: size {size} is not a multiple of the frame size {fb}")
    return size // fb


def read_frames(path: str | Path, width: int, height: int, bitdepth: int = 8, start: int = 0,
                count: int | None = None) -> Iterator[tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Yield (Y, U, V) planes as uint16 arrays (sample values, not rescaled)."""
    dtype = np.uint8 if bytes_per_sample(bitdepth) == 1 else np.dtype("<u2")
    fb = frame_bytes(width, height, bitdepth)
    total = num_frames(path, width, height, bitdepth)
    end = total if count is None else min(total, start + count)
    ys, cs = width * height, (width // 2) * (height // 2)
    with open(path, "rb") as fh:
        fh.seek(start * fb)
        for _ in range(start, end):
            buf = np.frombuffer(fh.read(fb), dtype=dtype).astype(np.uint16)
            y = buf[:ys].reshape(height, width)
            u = buf[ys:ys + cs].reshape(height // 2, width // 2)
            v = buf[ys + cs:].reshape(height // 2, width // 2)
            yield y, u, v


def write_frames(path: str | Path, frames, bitdepth: int = 8) -> None:
    """Write an iterable of (Y, U, V) planes."""
    dtype = np.uint8 if bytes_per_sample(bitdepth) == 1 else np.dtype("<u2")
    with open(path, "wb") as fh:
        for y, u, v in frames:
            for plane in (y, u, v):
                fh.write(np.asarray(plane).astype(dtype).tobytes())


def to_rgb(y: np.ndarray, u: np.ndarray, v: np.ndarray, bitdepth: int = 8, matrix: str = "bt709",
           full_range: bool = False) -> np.ndarray:
    """Convert one 4:2:0 frame to 8-bit RGB (H, W, 3), nearest-neighbour chroma upsampling."""
    kr, kb = _MATRICES[matrix]
    kg = 1.0 - kr - kb
    scale = float(1 << (bitdepth - 8))
    yf = y.astype(np.float64) / scale
    uf = np.repeat(np.repeat(u, 2, axis=0), 2, axis=1).astype(np.float64) / scale
    vf = np.repeat(np.repeat(v, 2, axis=0), 2, axis=1).astype(np.float64) / scale
    if full_range:
        yn, un, vn = yf / 255.0, (uf - 128.0) / 255.0, (vf - 128.0) / 255.0
    else:
        yn, un, vn = (yf - 16.0) / 219.0, (uf - 128.0) / 224.0, (vf - 128.0) / 224.0
    r = yn + 2.0 * (1.0 - kr) * vn
    b = yn + 2.0 * (1.0 - kb) * un
    g = (yn - kr * r - kb * b) / kg
    rgb = np.stack([r, g, b], axis=-1)
    return np.clip(np.rint(rgb * 255.0), 0, 255).astype(np.uint8)
