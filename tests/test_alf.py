"""ALF tools: vectorised implementation vs a literal port of the VTM-24.0 C++ loops, and coefficient design."""


import numpy as np
import pytest

from vcm.alf import project, spec, wiener

CTU = 16          # small power-of-two CTU so the virtual boundary (row 12 of every 16) is exercised often


# ---------- literal ports of VTM-24.0 AdaptiveLoopFilter.cpp (deriveClassificationBlk / filterBlk) ----------

def _px(rec, y, x):
    h, w = rec.shape
    return int(rec[min(max(y, 0), h - 1), min(max(x, 0), w - 1)])


def vtm_classify(rec, bd, ctu):
    vb_pos, H, W = ctu - 4, *rec.shape
    height, width = H + 4, W + 4
    lap = {k: [[0] * width for _ in range(height)] for k in ("ver", "hor", "d0", "d1")}
    for i in range(0, height, 2):
        r1 = i - 2
        r0, r2, r3 = r1 - 1, r1 + 1, r1 + 2
        y = -2 + i
        if y > 0 and (y & (ctu - 1)) == vb_pos - 2:
            r3 = r1 + 1
        elif y > 0 and (y & (ctu - 1)) == vb_pos:
            r0 = r1
        for j in range(0, width, 2):
            c = j - 2
            p = lambda r, cc: _px(rec, r, cc)
            y0, yup1 = p(r1, c) << 1, p(r2, c + 1) << 1
            lap["ver"][i][j] = abs(y0 - p(r0, c) - p(r2, c)) + abs(yup1 - p(r1, c + 1) - p(r3, c + 1))
            lap["hor"][i][j] = abs(y0 - p(r1, c + 1) - p(r1, c - 1)) + abs(yup1 - p(r2, c + 2) - p(r2, c))
            lap["d0"][i][j] = abs(y0 - p(r0, c - 1) - p(r2, c + 1)) + abs(yup1 - p(r1, c) - p(r3, c + 2))
            lap["d1"][i][j] = abs(y0 - p(r2, c - 1) - p(r0, c + 1)) + abs(yup1 - p(r3, c) - p(r1, c + 2))
            if j > 4 and (j - 6) % 4 == 0:
                for k in lap:
                    lap[k][i][j - 6] += lap[k][i][j - 4] + lap[k][i][j - 2] + lap[k][i][j]
    th = [0, 1, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 3, 3, 3, 4]
    cls = np.zeros((H // 4, W // 4), int)
    tr = np.zeros((H // 4, W // 4), int)
    for i in range(0, H, 4):
        for j in range(0, W, 4):
            rows = [i, i + 2, i + 4, i + 6]
            if i % ctu == vb_pos - 4:
                rows = [i, i + 2, i + 4]
            elif i % ctu == vb_pos:
                rows = [i + 2, i + 4, i + 6]
            s = {k: sum(lap[k][r][j] for r in rows) for k in lap}
            yv = i & (ctu - 1)
            ac = 96 if yv in (vb_pos - 4, vb_pos) else 64
            act = min(max((s["ver"] + s["hor"]) * ac >> (bd + 4), 0), 15)
            ci = th[act]
            if s["ver"] > s["hor"]:
                hv1, hv0, dhv = s["ver"], s["hor"], 1
            else:
                hv1, hv0, dhv = s["hor"], s["ver"], 3
            if s["d0"] > s["d1"]:
                d1, d0, dd = s["d0"], s["d1"], 0
            else:
                d1, d0, dd = s["d1"], s["d0"], 2
            if d1 * hv0 > hv1 * d0:
                hvd1, hvd0, main, sec = d1, d0, dd, dhv
            else:
                hvd1, hvd0, main, sec = hv1, hv0, dhv, dd
            strength = 0
            if hvd1 > 2 * hvd0:
                strength = 1
            if hvd1 * 2 > 9 * hvd0:
                strength = 2
            if strength:
                ci += (((main & 1) << 1) + strength) * 5
            cls[i // 4, j // 4] = ci
            tr[i // 4, j // 4] = [0, 1, 0, 2, 2, 3, 1, 3][main * 2 + (sec >> 1)]
    return cls, tr


def vtm_filter(rec, cls, tr, coef, clipidx, bd, ctu):
    vb_pos, (H, W) = ctu - 4, rec.shape
    clipv = spec.clip_values(bd)
    out = np.zeros_like(rec)
    for y in range(H):
        for x in range(W):
            t = tr[y // 4, x // 4]
            c = cls[y // 4, x // 4]
            fc = [coef[c][spec.TRANSPOSE_IDX[t][k]] for k in range(12)]
            fl = [clipv[clipidx[c][spec.TRANSPOSE_IDX[t][k]]] for k in range(12)]
            row = {0: y, 1: y + 1, 2: y - 1, 3: y + 2, 4: y - 2, 5: y + 3, 6: y - 3}
            yvb = y & (ctu - 1)
            if vb_pos - 4 <= yvb < vb_pos:
                if yvb == vb_pos - 1:
                    row[1] = row[0]
                if yvb >= vb_pos - 2:
                    row[3] = row[1]
                if yvb >= vb_pos - 3:
                    row[5] = row[3]
                if yvb == vb_pos - 1:
                    row[2] = row[0]
                if yvb >= vb_pos - 2:
                    row[4] = row[2]
                if yvb >= vb_pos - 3:
                    row[6] = row[4]
            elif vb_pos <= yvb <= vb_pos + 3:
                if yvb == vb_pos:
                    row[2] = row[0]
                if yvb <= vb_pos + 1:
                    row[4] = row[2]
                if yvb <= vb_pos + 2:
                    row[6] = row[4]
                if yvb == vb_pos:
                    row[1] = row[0]
                if yvb <= vb_pos + 1:
                    row[3] = row[1]
                if yvb <= vb_pos + 2:
                    row[5] = row[3]
            cur = _px(rec, y, x)
            g = lambda k, dx: _px(rec, row[k], x + dx)
            cl = lambda cv, a, b: max(-cv, min(cv, a - cur)) + max(-cv, min(cv, b - cur))
            pairs = [(5, 0, 6, 0), (3, 1, 4, -1), (3, 0, 4, 0), (3, -1, 4, 1), (1, 2, 2, -2), (1, 1, 2, -1),
                     (1, 0, 2, 0), (1, -1, 2, 1), (1, -2, 2, 2), (0, 3, 0, -3), (0, 2, 0, -2), (0, 1, 0, -1)]
            s = sum(fc[k] * cl(fl[k], g(a, da), g(b, db)) for k, (a, da, b, db) in enumerate(pairs))
            near = yvb == vb_pos - 1 or yvb == vb_pos
            s = (s + (1 << 9)) >> 10 if near else (s + 64) >> 7
            out[y, x] = min(max(s + cur, 0), (1 << bd) - 1)
    return out


@pytest.fixture(scope="module")
def picture():
    """Regions with different activity and orientation: flat, vertical/horizontal/diagonal stripes, noise."""
    rng = np.random.default_rng(3)
    yy, xx = np.mgrid[0:48, 0:40]
    base = np.full(xx.shape, 512.0)
    base[:, 8:16] += 120 * np.sin(xx[:, 8:16] * 1.3)                 # vertical stripes
    base[:, 16:24] += 120 * np.sin(yy[:, 16:24] * 1.3)               # horizontal stripes
    base[:, 24:32] += 120 * np.sin((xx + yy)[:, 24:32] * 0.9)        # diagonal
    base[:, 32:40] += 120 * np.sin((xx - yy)[:, 32:40] * 0.9)        # anti-diagonal
    base[24:, :] += 40 * np.sin(xx[24:, :] / 2.0)                    # milder texture in the bottom half
    noise_sd = np.where(xx < 8, 1.0, np.where(yy < 24, 4.0, 25.0))
    return np.clip(base + rng.normal(0, 1, base.shape) * noise_sd, 0, 1023).astype(np.int64)


def test_classification_matches_vtm_port(picture):
    cls, tr = spec.classify(picture, 10, ctu_size=CTU)
    ref_cls, ref_tr = vtm_classify(picture, 10, CTU)
    assert np.array_equal(cls, ref_cls)
    assert np.array_equal(tr, ref_tr)
    assert len(np.unique(cls)) > 5 and len(np.unique(tr)) > 1    # the test picture exercises many classes


def test_filter_matches_vtm_port(picture):
    rng = np.random.default_rng(4)
    cls, tr = spec.classify(picture, 10, ctu_size=CTU)
    coef = rng.integers(-40, 41, size=(25, 12))
    clip = rng.integers(0, 4, size=(25, 12))
    ours = spec.apply(picture, cls, tr, coef, clip, 10, ctu_size=CTU)
    ref = vtm_filter(picture, cls, tr, coef, clip, 10, CTU)
    assert np.array_equal(ours, ref)


def test_stripes_do_not_change_result(picture, monkeypatch):
    cls, tr = spec.classify(picture, 10, ctu_size=CTU)
    coef = np.full((25, 12), 5)
    clip = np.zeros((25, 12), int)
    full = spec.apply(picture, cls, tr, coef, clip, 10, ctu_size=CTU)
    monkeypatch.setattr(spec, "STRIPE", 7)
    assert np.array_equal(spec.apply(picture, cls, tr, coef, clip, 10, ctu_size=CTU), full)


def test_zero_coefficients_are_identity(picture):
    cls, tr = spec.classify(picture, 10, ctu_size=CTU)
    out = spec.apply(picture, cls, tr, np.zeros((25, 12), int), np.zeros((25, 12), int), 10, ctu_size=CTU)
    assert np.array_equal(out, picture)


def test_clip_values_match_vtm_formula():
    assert spec.clip_values(10).tolist() == [1024, 128, 32, 8]
    assert spec.clip_values(8).tolist() == [256, 32, 8, 2]


def test_wiener_recovers_known_filter(picture):
    rng = np.random.default_rng(5)
    cls, tr = spec.classify(picture, 10, ctu_size=CTU)
    true = rng.integers(-20, 21, size=(25, 12))
    clip0 = np.zeros((25, 12), int)
    orig = spec.apply(picture, cls, tr, true, clip0, 10, ctu_size=CTU)
    stats = wiener.collect_stats(picture, orig, cls, tr, 10, ctu_size=CTU)
    coeff, clip, _ = wiener.design(stats, search_clip=False)
    out = spec.apply(picture, cls, tr, coeff, clip, 10, ctu_size=CTU)
    mse_before = np.mean((picture - orig) ** 2.0)
    mse_after = np.mean((out - orig) ** 2.0)
    # the true filter reaches 0; the designed one must remove essentially all of the error (rounding level)
    assert mse_before > 50
    assert mse_after < 0.02 * mse_before


def test_weights_select_pixels(picture):
    """With zero weight on the bottom half, the design must fit the top half's filter only."""
    cls, tr = spec.classify(picture, 10, ctu_size=CTU)
    a, b = np.full((25, 12), 10), np.full((25, 12), -10)
    zero = np.zeros((25, 12), int)
    top = spec.apply(picture, cls, tr, a, zero, 10, ctu_size=CTU)
    bot = spec.apply(picture, cls, tr, b, zero, 10, ctu_size=CTU)
    orig = np.vstack([top[:24], bot[24:]])
    w = np.zeros(picture.shape)
    w[:24] = 1.0
    coeff, _, _ = wiener.design(wiener.collect_stats(picture, orig, cls, tr, 10, weights=w, ctu_size=CTU),
                                search_clip=False)
    used = np.unique(cls[:6])
    assert np.mean(coeff[used]) > 5            # follows the weighted (top) half, not the average


def test_clip_search_never_increases_error(picture):
    rng = np.random.default_rng(6)
    cls, tr = spec.classify(picture, 10, ctu_size=CTU)
    orig = np.clip(picture + rng.normal(0, 20, picture.shape), 0, 1023).astype(np.int64)
    stats = wiener.collect_stats(picture, orig, cls, tr, 10, ctu_size=CTU)
    for s in stats:
        if s.n < 50:
            continue
        g0, _, e0 = wiener.design_class(s, search_clip=False)
        _, _, e1 = wiener.design_class(s, search_clip=True)
        assert e1 <= e0 + 1e-6


def test_project_and_export(tmp_path):
    real = np.full((25, 12), 0.1)
    real[0, 0] = 5.0                       # 640 -> clamped to 127
    f, clip, rep = project.project(real)
    assert f[0, 0] == 127 and f[1, 1] == 13 and rep["clamped"] == 1
    p = tmp_path / "c.txt"
    clip2 = clip.copy()
    clip2[3, 5] = 2
    project.write(p, [{"poc": 8, "coeff": f, "clip_idx": clip2}, {"poc": 4, "coeff": -f, "clip_idx": clip}])
    back = project.read(p)
    assert sorted(back) == [4, 8]
    assert np.array_equal(back[8][0], f) and np.array_equal(back[8][1], clip2)
    assert np.array_equal(back[4][0], -f)
    assert p.read_text().splitlines()[0] == f"# {project.FORMAT}"
    with pytest.raises(ValueError):
        project.write(p, [{"poc": 0, "coeff": f + 200, "clip_idx": clip}])


def test_choose_shift_reaches_chance_level_and_is_a_permutation():
    from vcm.alf import weights
    rng = np.random.default_rng(0)
    boxes = [np.array([[10, 10, 60, 40], [40, 20, 90, 70]]) + 2 * t for t in range(6)]   # overlapping, moving
    masks = [weights.roi_mask(b, np.ones(2), 96, 128)[::4, ::4] for b in boxes]
    sh = weights.choose_shift(masks, 96, 128, rng)
    assert sh["accepted"] and sh["overlap"] <= sh["chance"] and sh["dy"] % 4 == 0 and sh["dx"] % 4 == 0
    w = weights.roi_weights("continuous", boxes[0], np.array([0.9, 0.6]), 96, 128)
    ws = weights.roi_weights("shuffled", boxes[0], np.array([0.9, 0.6]), 96, 128, shift=(sh["dy"], sh["dx"]))
    assert np.array_equal(np.sort(w.ravel()), np.sort(ws.ravel()))       # overlaps and clipping preserved exactly
    assert weights.choose_shift([np.zeros((4, 4), bool)], 16, 16, rng)["dy"] == 0      # no ROI: no shift
