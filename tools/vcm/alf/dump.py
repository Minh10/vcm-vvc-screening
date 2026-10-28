"""Read the ``VCMAlfDumpDir`` output of the hooked VTM encoder and check the offline ALF against it.

Per picture the hook writes ``pre_<poc>.y16`` (luma entering ALF, i.e. after deblocking and SAO), ``post_<poc>.y16``
(luma after ALF), ``org_<poc>.y16`` (original luma used by the ALF encoder) — all int16, internal bit depth — and
``ctb_<poc>.txt`` with, for every CTB, the AlfMode and the 25 x (12 coefficients, 12 clipping values) it used.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import spec


@dataclass
class Meta:
    width: int
    height: int
    bitdepth: int
    ctu_size: int
    vb_pos: int


@dataclass
class CtbFilter:
    mode: int                       # AlfMode (-1 = off)
    coeff: np.ndarray | None        # (25, 12)
    clip_values: np.ndarray | None  # (25, 12) clipping *values* (not indices)


def read_meta(d: str | Path) -> Meta:
    kv = dict(line.split() for line in Path(d, "meta.txt").read_text().splitlines() if line.strip())
    return Meta(int(kv["width"]), int(kv["height"]), int(kv["bitdepth"]), int(kv["ctu_size"]), int(kv["vb_pos"]))


def read_plane(d: str | Path, kind: str, poc: int, meta: Meta) -> np.ndarray:
    a = np.fromfile(Path(d, f"{kind}_{poc}.y16"), dtype="<i2")
    return a.reshape(meta.height, meta.width).astype(np.int64)


def read_ctbs(d: str | Path, poc: int) -> tuple[bool, list[CtbFilter]]:
    lines = Path(d, f"ctb_{poc}.txt").read_text().splitlines()
    luma_on = lines[0].split()[-1] == "1"
    out, i = [], 1
    while i < len(lines):
        _, _, mode = lines[i].split()
        mode = int(mode)
        i += 1
        if mode < 0:
            out.append(CtbFilter(mode, None, None))
            continue
        block = np.array([list(map(int, lines[i + c].split())) for c in range(spec.NUM_CLASSES)])
        out.append(CtbFilter(mode, block[:, :spec.NUM_COEFF], block[:, spec.NUM_COEFF:]))
        i += spec.NUM_CLASSES
    return luma_on, out


def pocs(d: str | Path) -> list[int]:
    return sorted(int(p.stem.split("_")[1]) for p in Path(d).glob("ctb_*.txt"))


def clip_index(values: np.ndarray, bitdepth: int) -> np.ndarray:
    table = spec.clip_values(bitdepth)
    idx = np.searchsorted(-table, -values)            # table is decreasing
    if not np.array_equal(table[idx], values):
        raise ValueError("clipping value not in the AlfClip table")
    return idx


def reproduce(d: str | Path, poc: int) -> tuple[np.ndarray, np.ndarray]:
    """Apply the dumped per-CTB filters to the dumped pre-ALF luma with ``vcm.alf.spec``.
    Returns (ours, vtm_post)."""
    meta = read_meta(d)
    pre, post = read_plane(d, "pre", poc, meta), read_plane(d, "post", poc, meta)
    _, ctbs = read_ctbs(d, poc)
    cls, tr = spec.classify(pre, meta.bitdepth, meta.ctu_size)
    out = pre.copy()
    cols = -(-meta.width // meta.ctu_size)
    cache: dict[tuple, np.ndarray] = {}
    for addr, f in enumerate(ctbs):
        if f.mode < 0:
            continue
        key = (f.coeff.tobytes(), f.clip_values.tobytes())
        if key not in cache:
            cache[key] = spec.apply(pre, cls, tr, f.coeff, clip_index(f.clip_values, meta.bitdepth), meta.bitdepth,
                                    ctu_size=meta.ctu_size)
        y0, x0 = (addr // cols) * meta.ctu_size, (addr % cols) * meta.ctu_size
        sl = (slice(y0, y0 + meta.ctu_size), slice(x0, x0 + meta.ctu_size))
        out[sl] = cache[key][sl]
    return out, post
