"""Branch B drivers. Each sub-command produces the input of one ladder stage (docs/RESEARCH_PLAN.md).

``weights``  O1-B input: per-POC luma weight maps w_<poc>.f32 from detector boxes on the *original* frames, for
             ``--VCMAlfWeightDir`` (VTM's own ALF encoder then designs, merges and switches filters on weighted
             statistics).
``wiener``   O1-A' / O1-B-forced input: per-POC (weighted) Wiener coefficients designed offline from an ALF dump
             (pre-ALF luma + original), written for ``--VCMAlfExternalFile`` (forced in every CTB).
``oracle``   O1-A: per-POC coefficients optimised by gradient through a task loss on the pre-ALF luma of a dump.
             Writes (a) the projected coefficients for ``--VCMAlfExternalFile`` (O1-A'), (b) optionally a
             pseudo-variant job folder whose decoded output is the oracle-filtered picture at the anchor's bitrate
             — an UPPER BOUND that ignores APS cost and reference effects, labelled as such in its manifest.

POC handling: dump/decoded frame index = POC; original frame index = POC * --poc-step (the encoder's temporal
subsampling ratio, 1 for LDP/RA).
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import numpy as np

from ..evaluate import frame_image_ids
from ..yuv import read_frames, write_frames
from . import dump, project, spec, wiener, weights


def _boxes_by_frame(detections: list[dict], gt: dict) -> dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]]:
    frame_of = {img_id: f for f, img_id in enumerate(frame_image_ids(gt))}
    out: dict[int, list] = {}
    for r in detections:
        f = frame_of.get(r["image_id"])
        if f is None:
            continue
        x, y, w, h = r["bbox"]
        out.setdefault(f, []).append((x, y, x + w, y + h, r["score"], r["category_id"]))
    return {f: (np.array([v[:4] for v in vals], float), np.array([v[4] for v in vals]), np.array([v[5] for v in vals]))
            for f, vals in out.items()}


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
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    boxes = _boxes_by_frame(json.loads(Path(a.detections).read_text()), json.loads(Path(a.gt).read_text()))
    for poc in range(a.pocs):
        b, s, _ = boxes.get(poc * a.poc_step, (np.zeros((0, 4)), np.zeros(0), np.zeros(0)))
        w = weights.box_weights(b, s, a.height, a.width, a.bg, a.threshold)
        w = w / w.mean()                     # mean 1: keeps the distortion scale of VTM's RD decisions
        w.astype("<f4").tofile(out / f"w_{poc}.f32")
    print(f"wrote {a.pocs} weight maps to {out}")


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
    pics, report, oracle_frames = [], {}, []
    for poc in dump.pocs(a.dump):
        pre = dump.read_plane(a.dump, "pre", poc, meta)
        y0, u0, v0 = src[poc * a.poc_step]
        target = yuv_to_rgb(*(torch.tensor(p.astype(np.float32)) for p in (y0, u0, v0)), a.source_bitdepth)[None]
        u, v = dec[poc][1].astype(np.float64) * up, dec[poc][2].astype(np.float64) * up
        if a.loss == "feature":
            loss = feature_loss(feats, target)
        else:
            b, s, c = boxes.get(poc * a.poc_step, (np.zeros((0, 4)), np.zeros(0), np.zeros(0)))
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
        report[poc] = {"loss_anchor_actual": loss_anchor, "loss_start": hist[0], "loss_best": min(hist), **rep}
        if a.variant_dir:
            yf = alf(torch.tensor(g, dtype=torch.float32)).detach().numpy()
            oracle_frames.append((np.clip(np.rint(yf / up), 0, (1 << a.decoded_bitdepth) - 1), dec[poc][1], dec[poc][2]))
        print(f"poc {poc}: task loss anchor {loss_anchor:.5g} | start {hist[0]:.5g} -> best {min(hist):.5g}")
    project.write(a.out, pics)
    Path(a.out).with_suffix(".report.json").write_text(json.dumps(report, indent=2))

    if a.variant_dir:
        # pseudo-variant: same bitstream size as the anchor, decoded output replaced by the oracle output
        anchor = Path(a.anchor_job)
        man = json.loads((anchor / "manifest.json").read_text())
        out = Path(a.variant_dir)
        out.mkdir(parents=True, exist_ok=True)
        write_frames(out / "rec_dec.yuv", oracle_frames, a.decoded_bitdepth)
        man["job"]["variant"] = "o1a_oracle_upper_bound"
        man["job_id"] = man["job_id"].rsplit("__", 1)[0] + "__o1a_oracle_upper_bound"
        man["note"] = ("UPPER BOUND (O1-A): real-valued per-picture ALF coefficients optimised on the task loss; "
                       "APS cost and reference effects ignored; rate copied from the anchor job")
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
    w.add_argument("--poc-step", type=int, default=1)
    w.add_argument("--bg", type=float, default=0.1)
    w.add_argument("--threshold", type=float, default=0.3)
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
    o.add_argument("--poc-step", type=int, default=1)
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
    o.add_argument("--anchor-job")
    a = ap.parse_args(argv)
    {"weights": cmd_weights, "wiener": cmd_wiener, "oracle": cmd_oracle}[a.cmd](a)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
