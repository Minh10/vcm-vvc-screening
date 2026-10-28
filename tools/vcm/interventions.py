"""Read and validate RAMU-Lite QP intervention files (poc,ctu_addr,delta_qp)."""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path

REQUIRED_COLUMNS = ("poc", "ctu_addr", "delta_qp")


@dataclass(frozen=True)
class Intervention:
    poc: int
    ctu_addr: int
    delta_qp: int


def num_ctus(width: int, height: int, ctu_size: int = 128) -> int:
    """Number of CTUs in a picture (raster order, partial CTUs at the right/bottom edge count)."""
    return math.ceil(width / ctu_size) * math.ceil(height / ctu_size)


def load(path: str | Path, *, width: int | None = None, height: int | None = None, ctu_size: int = 128,
         frames: int | None = None, max_abs_delta: int = 12) -> list[Intervention]:
    """Load an intervention CSV and reject anything that cannot be applied exactly.

    Checks: required columns, integer values, non-zero |delta_qp| <= max_abs_delta, no duplicate
    (poc, ctu_addr), and, when picture size / frame count are given, CTU address and POC ranges.
    """
    path = Path(path)
    with path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None or any(c not in reader.fieldnames for c in REQUIRED_COLUMNS):
            raise ValueError(f"{path}: header must contain {', '.join(REQUIRED_COLUMNS)}")
        rows = list(reader)

    limit = num_ctus(width, height, ctu_size) if width and height else None
    seen: set[tuple[int, int]] = set()
    out: list[Intervention] = []
    for line, row in enumerate(rows, start=2):
        try:
            item = Intervention(*(int(row[c]) for c in REQUIRED_COLUMNS))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{path}:{line}: non-integer value") from exc
        if item.delta_qp == 0 or abs(item.delta_qp) > max_abs_delta:
            raise ValueError(f"{path}:{line}: delta_qp must be non-zero and |delta_qp| <= {max_abs_delta}")
        if item.poc < 0 or (frames is not None and item.poc >= frames):
            raise ValueError(f"{path}:{line}: poc {item.poc} out of range")
        if item.ctu_addr < 0 or (limit is not None and item.ctu_addr >= limit):
            raise ValueError(f"{path}:{line}: ctu_addr {item.ctu_addr} out of range")
        key = (item.poc, item.ctu_addr)
        if key in seen:
            raise ValueError(f"{path}:{line}: duplicate intervention for poc={item.poc}, ctu={item.ctu_addr}")
        seen.add(key)
        out.append(item)
    return out
