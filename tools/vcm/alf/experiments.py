"""Branch B drivers. Each sub-command produces the input of one ladder stage (docs/RESEARCH_PLAN.md).

``weights``  O1-B input: per-POC luma weight maps w_<poc>.f32 from detector boxes on the *original* frames, for
             ``--VCMAlfWeightDir`` (VTM's own ALF encoder then designs, merges and switches filters on weighted
             statistics). One folder per arm: continuous ROI, binary ROI, shuffled ROI, uniform (sanity).
             This is ROI-weighted pixel SSE — task-*guided*, not a minimisation of a task loss.
``wiener``   O1-A' / O1-B-forced input: per-POC (weighted) Wiener coefficients designed offline from an ALF dump
             (pre-ALF luma + original), written for ``--VCMAlfExternalFile`` (forced in every CTB).
``oracle``   O1-A: per-POC coefficients optimised by gradient through a task loss on the pre-ALF luma of a dump.
             Writes (a) the projected coefficients for ``--VCMAlfExternalFile`` (O1-A'), (b) optionally a
             pseudo-variant job folder whose decoded output is the oracle-filtered picture at the anchor's bitrate.

What O1-A is — and is not
-------------------------
O1-A is a **relaxed, approximate oracle**, not a guaranteed upper bound:

* relaxed: real-valued coefficients (no 7-bit quantisation), no APS signalling cost, no effect on later pictures
  through the reference buffer (the filtered picture is not fed back into the encoder);
* restricted: one luma filter set per picture applied to **every** CTB, the anchor's clipping indices kept fixed.
  The anchor's actual ALF output (per-CTB on/off, choice among several APS / fixed filters, class merging) is
  *not* in this family in general;
* approximate: local gradient descent from the anchor's most-used filter; the result is the best iterate seen.

Consequently the oracle can be worse than the anchor's real ALF output. The report gives, per POC,
``loss_anchor_actual`` (the anchor's real post-ALF picture), ``loss_start`` and ``loss_best``, and
``beats_anchor_actual``. The pseudo-variant is labelled ``o1a_relaxed_oracle`` and flagged ``pseudo_variant`` in its
manifest; ``vcm.curves`` refuses it unless asked explicitly (``--allow-pseudo``), and its rate is the anchor's.

POC handling: dump/decoded frame index = POC (output order); original frame index =
``frame_offset + POC * frame_step``, taken from the anchor job's manifest (``--anchor-job``) or ``--poc-step``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

import numpy as np

from ..evaluate import source_frame_ids
from ..yuv import read_frames, write_frames
from . import dump, project, spec, wiener, weights


PSEUDO_VARIANT = "o1a_relaxed_oracle"


def _boxes_by_frame(detections: list[dict], gt: dict) -> dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]]:
    frame_of = {img_id: f for f, img_id in source_frame_ids(gt)[0].items()}   # image id -> source frame
    out: dict[int, list] = {}
    for r in detections:
        f = frame_of.get(r["image_id"])
        if f is None:
            continue
        x, y, w, h = r["bbox"]
        out.setdefault(f, []).append((x, y, x + w, y + h, r["score"], r["category_id"]))
    return {f: (np.array([v[:4] for v in vals], float), np.array([v[4] for v in vals]), np.array([v[5] for v in vals]))
            for f, vals in out.items()}


def _sampling(a) -> tuple[int, int]:
    """(frame_offset, frame_step) from the anchor manifest; --poc-step must agree with it if both are given."""
    if getattr(a, "anchor_job", None):
        man = json.loads((Path(a.anchor_job) / "manifest.json").read_text())
        step, offset = int(man.get("frame_step", 1)), int(man.get("frame_offset", 0))
        if a.poc_step is not None and a.poc_step != step:
            raise SystemExit(f"--poc-step {a.poc_step} contradicts frame_step {step} of {a.anchor_job}")
        return offset, step
    return 0, a.poc_step or 1


def _anchor_init(dump_dir, poc: int) -> np.ndarray | None:
    """Coefficients (/128) of the luma filter the anchor used in most CTBs of this picture; None if ALF was off.
    Starting the oracle there makes its result never worse than the anchor's filter on the optimised loss."""
    _, ctbs = dump.read_ctbs(dump_dir, poc)
    used = [c for c in ctbs if c.mode >= 0]
    if not used:
        return None
    modes, counts = np.unique([c.mode for c in used], return_counts=True)
    top = next(c for c in used if c.mode == modes[np.argmax(counts)])
    meta = dump.read_meta(dump_dir)
    return top.coeff / float(1 << spec.COEFF_SHIFT), dump.clip_index(top.clip_values, meta.bitdepth)


def cmd_weights(a) -> None:
    """One sub-folder per O1-B arm: <out>/<mode>/w_<poc>.f32, normalised to mean 1 per picture (keeps the
    distortion scale of VTM's RD decisions; the uniform arm is then exactly 1)."""
    out = Path(a.out)
    boxes = _boxes_by_frame(json.loads(Path(a.detections).read_text()), json.loads(Path(a.gt).read_text()))
    offset, step = _sampling(a)
    summary = {}
    for mode in a.modes:
        (out / mode).mkdir(parents=True, exist_ok=True)
        rng = np.random.default_rng(a.seed)
        inside, outside, alignment = [], [], []
        for poc in range(a.pocs):
            b, s, _ = boxes.get(offset + poc * step, (np.zeros((0, 4)), np.zeros(0), np.zeros(0)))
            w = weights.roi_weights(mode, b, s, a.height, a.width, a.bg, a.threshold, rng)
            w = w / w.mean()
            w.astype("<f4").tofile(out / mode / f"w_{poc}.f32")
            roi = weights.box_weights(b, s, a.height, a.width, 0.0, a.threshold) > 0     # true ROI mask
            if roi.any() and (~roi).any():
                inside.append(float(w[roi].mean()))
                outside.append(float(w[~roi].mean()))
                alignment.append(float(w[roi].sum() / w.sum()))
        summary[mode] = {"pocs": a.pocs, "mean_weight_in_roi": float(np.mean(inside)) if inside else None,
                         "mean_weight_outside_roi": float(np.mean(outside)) if outside else None,
                         "weight_share_in_roi": float(np.mean(alignment)) if alignment else None}
    (out / "weights_summary.json").write_text(json.dumps({"bg": a.bg, "threshold": a.threshold, "seed": a.seed,
                                                          "frame_step": step, "frame_offset": offset,
                                                          "modes": summary}, indent=2))
    print(f"wrote {a.pocs} weight maps x {len(a.modes)} arms to {out}")


def cmd_wiener(a) -> None:
    meta = dump.read_meta(a.dump)
    pics = []
    for poc in dump.pocs(a.dump):
        pre, org = dump.read_plane(a.dump, "pre", poc, meta), dump.read_plane(a.dump, "org", poc, meta)
        w = None
        if a.weights:
            w = np.fromfile(Path(a.weights, f"w_{poc}.f32"), dtype="<f4").reshape(meta.height, meta.width)
        cls, tr = spec.classify(pre, meta.bitdepth, meta.ctu_size)
        coeff, clip, _ = wiener.design(wiener.collect_stats(pre, org, cls, tr, meta.bitdepth, w,
                                                            ctu_size=meta.ctu_size))
        pics.append({"poc": poc, "coeff": coeff, "clip_idx": clip})
    project.write(a.out, pics)
    print(f"wrote {'weighted ' if a.weights else ''}Wiener coefficients for {len(pics)} pictures to {a.out}")


def cmd_oracle(a) -> None:
    import torch

    from ..detect import torchvision_backbone_features, torchvision_model
    from .oracle import DifferentiableALF, feature_loss, optimise, torchvision_detection_loss, yuv_to_rgb

    meta = dump.read_meta(a.dump)
    model = torchvision_model(a.arch, a.weights_file)
    feats = torchvision_backbone_features(model)
    w, h = meta.width, meta.height
    src = list(read_frames(a.source, w, h, a.source_bitdepth))
    dec = list(read_frames(a.decoded, w, h, a.decoded_bitdepth))
    boxes = {}
    if a.loss == "detection":
        boxes = _boxes_by_frame(json.loads(Path(a.detections).read_text()), json.loads(Path(a.gt).read_text()))

    up = 1 << (meta.bitdepth - a.decoded_bitdepth)
    offset, step = _sampling(a)
    pics, report, oracle_frames = [], {}, []
    for poc in dump.pocs(a.dump):
        pre = dump.read_plane(a.dump, "pre", poc, meta)
        y0, u0, v0 = src[offset + poc * step]
        target = yuv_to_rgb(*(torch.tensor(p.astype(np.float32)) for p in (y0, u0, v0)), a.source_bitdepth)[None]
        u, v = dec[poc][1].astype(np.float64) * up, dec[poc][2].astype(np.float64) * up
        if a.loss == "feature":
            loss = feature_loss(feats, target)
        else:
            b, s, c = boxes.get(offset + poc * step, (np.zeros((0, 4)), np.zeros(0), np.zeros(0)))
            keep = s >= a.threshold
            loss = torchvision_detection_loss(model, b[keep], c[keep])
        cls, tr = spec.classify(pre, meta.bitdepth, meta.ctu_size)
        init = _anchor_init(a.dump, poc)
        g0, clip0 = init if init is not None else (None, None)
        alf = DifferentiableALF(pre, cls, tr, meta.bitdepth, clip_idx=clip0, ctu_size=meta.ctu_size)
        g, hist = optimise(alf, u, v, meta.bitdepth, loss, steps=a.steps, lr=a.lr, init=g0)
        coeff, clip, rep = project.project(g, clip0)
        pics.append({"poc": poc, "coeff": coeff, "clip_idx": clip})
        with torch.no_grad():
            post = torch.tensor(dump.read_plane(a.dump, "post", poc, meta).astype(np.float32))
            ut, vt = torch.tensor(u, dtype=torch.float32), torch.tensor(v, dtype=torch.float32)
            loss_anchor = float(loss(yuv_to_rgb(post, ut, vt, meta.bitdepth)[None]))
        # loss_anchor_actual: the anchor's real ALF output (per-CTB on/off and APS choices);
        # loss_start: its most-used filter forced on every CTB (the oracle's starting point)
        report[poc] = {"loss_anchor_actual": loss_anchor, "loss_start": hist[0], "loss_best": min(hist),
                       "beats_anchor_actual": bool(min(hist) < loss_anchor), **rep}
        if a.variant_dir:
            yf = alf(torch.tensor(g, dtype=torch.float32)).detach().numpy()
            oracle_frames.append((np.clip(np.rint(yf / up), 0, (1 << a.decoded_bitdepth) - 1), dec[poc][1], dec[poc][2]))
        print(f"poc {poc}: task loss anchor {loss_anchor:.5g} | start {hist[0]:.5g} -> best {min(hist):.5g}")
    project.write(a.out, pics)
    n_beat = sum(r["beats_anchor_actual"] for r in report.values())
    summary = {"kind": "relaxed_oracle", "pocs": len(report), "pocs_beating_anchor_actual": n_beat,
               "family": "one real-valued luma filter set per picture, all CTBs, anchor clip indices",
               "per_poc": report}
    Path(a.out).with_suffix(".report.json").write_text(json.dumps(summary, indent=2))
    print(f"oracle beats the anchor's actual ALF output on {n_beat}/{len(report)} pictures")

    if a.variant_dir:
        # pseudo-variant: same bitstream size as the anchor, decoded output replaced by the oracle output
        anchor = Path(a.anchor_job)
        man = json.loads((anchor / "manifest.json").read_text())
        out = Path(a.variant_dir)
        out.mkdir(parents=True, exist_ok=True)
        if len(oracle_frames) != man.get("coded_frames", len(oracle_frames)):
            raise SystemExit("dump does not cover every coded picture of the anchor job")
        write_frames(out / "rec_dec.yuv", oracle_frames, a.decoded_bitdepth)
        man["job"]["variant"] = PSEUDO_VARIANT
        man["job_id"] = man["job_id"].rsplit("__", 1)[0] + "__" + PSEUDO_VARIANT
        man["pseudo_variant"] = True
        man["pseudo_kind"] = "relaxed_oracle"
        man["rate_source"] = anchor.name
        man["recon_md5_decoder"] = hashlib.md5((out / "rec_dec.yuv").read_bytes()).hexdigest()
        man.pop("recon_md5_encoder", None)
        man["bitstream_sha256"] = None
        man["oracle_report"] = str(Path(a.out).with_suffix(".report.json"))
        man["note"] = ("RELAXED ORACLE (O1-A), not a codec output and not a guaranteed upper bound: real-valued "
                       "per-picture luma ALF coefficients optimised on the task loss, applied to every CTB; APS "
                       "cost and reference effects ignored; rate copied from the anchor job")
        (out / "manifest.json").write_text(json.dumps(man, indent=2))
        shutil.copy(anchor / "enc.log", out / "anchor_enc.log")
        print(f"wrote pseudo-variant {out}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Branch B (MAPS-ALF) drivers")
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("weights")
    w.add_argument("--detections", required=True, help="COCO results of the detector on the ORIGINAL frames")
    w.add_argument("--gt", required=True, help="annotation file (only used for the image-id -> frame mapping)")
    w.add_argument("--width", type=int, required=True)
    w.add_argument("--height", type=int, required=True)
    w.add_argument("--pocs", type=int, required=True)
    w.add_argument("--poc-step", type=int, help="source frames per POC (default: from --anchor-job, else 1)")
    w.add_argument("--anchor-job", help="any job folder of this sequence/structure (frame_step/frame_offset)")
    w.add_argument("--bg", type=float, default=0.1)
    w.add_argument("--threshold", type=float, default=0.3)
    w.add_argument("--modes", nargs="+", choices=weights.ROI_MODES, default=list(weights.ROI_MODES))
    w.add_argument("--seed", type=int, default=0, help="seed of the shuffled arm")
    w.add_argument("--out", required=True)
    n = sub.add_parser("wiener")
    n.add_argument("--dump", required=True)
    n.add_argument("--weights")
    n.add_argument("--out", required=True)
    o = sub.add_parser("oracle")
    o.add_argument("--dump", required=True, help="VCMAlfDumpDir of the ALF-default anchor encode")
    o.add_argument("--decoded", required=True, help="decoded YUV of the same encode (chroma source)")
    o.add_argument("--decoded-bitdepth", type=int, default=8)
    o.add_argument("--source", required=True)
    o.add_argument("--source-bitdepth", type=int, default=8)
    o.add_argument("--poc-step", type=int, help="source frames per POC (default: from --anchor-job, else 1)")
    o.add_argument("--arch", default="fasterrcnn_resnet50_fpn")
    o.add_argument("--weights-file", required=True)
    o.add_argument("--loss", choices=["feature", "detection"], default="feature")
    o.add_argument("--detections")
    o.add_argument("--gt")
    o.add_argument("--threshold", type=float, default=0.5)
    o.add_argument("--steps", type=int, default=150)
    o.add_argument("--lr", type=float, default=0.002)
    o.add_argument("--out", required=True)
    o.add_argument("--variant-dir")
    o.add_argument("--anchor-job", help="the anchor job folder of the dump (rate, frame_step); required with "
                                        "--variant-dir")
    a = ap.parse_args(argv)
    {"weights": cmd_weights, "wiener": cmd_wiener, "oracle": cmd_oracle}[a.cmd](a)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
