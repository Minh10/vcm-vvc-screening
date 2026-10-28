"""Projection of real-valued ALF coefficients onto valid luma ALF syntax and export for the VTM hook (O1-A').

The exported file is read by the ``VCMAlfExternalFile`` hook (docs/ALF_CODEC_AUDIT.md). For every picture listed,
the hook writes a new ALF APS whose luma filters are exactly these 25 filters (one per class, no merging) and
switches luma ALF on with that APS in every CTB. Chroma ALF and CC-ALF keep the VTM decisions.

Plain-text format, parsed by the C++ hook without extra dependencies::

    # vcm-alf-luma-txt-v1
    POC 8
    c0 c1 ... c11 k0 k1 ... k11      <- 25 lines: 12 coefficients (7 fractional bits), 12 clipping indices
    ...
    POC 16
    ...
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .spec import COEFF_MAX, COEFF_MIN, COEFF_SHIFT, NUM_CLASSES, NUM_COEFF

FORMAT = "vcm-alf-luma-txt-v1"


def project(real_coeff: np.ndarray, clip_idx: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray, dict]:
    """Round to 7 fractional bits and clamp to the signalled range. Returns (coeff, clip_idx, report)."""
    g = np.asarray(real_coeff, dtype=np.float64).reshape(NUM_CLASSES, NUM_COEFF)
    scaled = g * (1 << COEFF_SHIFT)
    f = np.clip(np.rint(scaled), COEFF_MIN, COEFF_MAX).astype(np.int64)
    clip = np.zeros_like(f) if clip_idx is None else np.asarray(clip_idx, dtype=np.int64).reshape(f.shape)
    if clip.min() < 0 or clip.max() > 3:
        raise ValueError("clip indices must be in 0..3")
    report = {
        "clamped": int(np.sum((scaled < COEFF_MIN - 0.5) | (scaled > COEFF_MAX + 0.5))),
        "max_abs_rounding_error": float(np.max(np.abs(np.clip(scaled, COEFF_MIN, COEFF_MAX) - f))),
    }
    return f, clip, report


def write(path: str | Path, pictures: list[dict]) -> None:
    """``pictures``: list of {"poc", "coeff" (25x12 int), "clip_idx" (25x12 int)}."""
    lines = [f"# {FORMAT}"]
    for p in sorted(pictures, key=lambda d: int(d["poc"])):
        c, k = np.asarray(p["coeff"], dtype=np.int64), np.asarray(p["clip_idx"], dtype=np.int64)
        if c.shape != (NUM_CLASSES, NUM_COEFF) or k.shape != c.shape:
            raise ValueError("coeff and clip_idx must be 25 x 12")
        if c.min() < COEFF_MIN or c.max() > COEFF_MAX:
            raise ValueError("coefficient out of the signalled range")
        if k.min() < 0 or k.max() > 3:
            raise ValueError("clip indices must be in 0..3")
        lines.append(f"POC {int(p['poc'])}")
        lines += [" ".join(map(str, [*c[i], *k[i]])) for i in range(NUM_CLASSES)]
    Path(path).write_text("\n".join(lines) + "\n")


def read(path: str | Path) -> dict[int, tuple[np.ndarray, np.ndarray]]:
    rows = [ln.strip() for ln in Path(path).read_text().splitlines()]
    if not rows or rows[0] != f"# {FORMAT}":
        raise ValueError(f"{path}: missing '# {FORMAT}' header")
    out, i = {}, 1
    while i < len(rows):
        if not rows[i]:
            i += 1
            continue
        tag, poc = rows[i].split()
        if tag != "POC":
            raise ValueError(f"{path}: expected 'POC <n>' at line {i + 1}")
        block = np.array([list(map(int, rows[i + 1 + r].split())) for r in range(NUM_CLASSES)])
        out[int(poc)] = (block[:, :NUM_COEFF], block[:, NUM_COEFF:])
        i += 1 + NUM_CLASSES
    return out
