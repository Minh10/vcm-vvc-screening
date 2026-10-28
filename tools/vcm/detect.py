"""Detector interface and adapters.

A detector is any callable ``rgb (H, W, 3) uint8 -> (boxes_xyxy (N, 4), scores (N,), category_ids (N,))`` where
category ids are in the ground-truth annotation space. Adapters below wrap Detectron2 (the VCM CTC detector) and
torchvision; both load weights from a **local file** so runs never depend on a download at evaluation time.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np

from .yuv import read_frames, to_rgb

Detector = Callable[[np.ndarray], tuple[np.ndarray, np.ndarray, np.ndarray]]


@dataclass
class FrameDetections:
    frame: int
    boxes: np.ndarray     # (N, 4) xyxy, pixels
    scores: np.ndarray    # (N,)
    labels: np.ndarray    # (N,) category ids in GT space


def run_on_yuv(detector: Detector, path, width: int, height: int, bitdepth: int = 8, frames: int | None = None,
               matrix: str = "bt709", full_range: bool = False) -> list[FrameDetections]:
    out = []
    for i, (y, u, v) in enumerate(read_frames(path, width, height, bitdepth, count=frames)):
        boxes, scores, labels = detector(to_rgb(y, u, v, bitdepth, matrix, full_range))
        out.append(FrameDetections(i, np.asarray(boxes, float).reshape(-1, 4), np.asarray(scores, float),
                                   np.asarray(labels, int)))
    return out


def to_coco_results(dets: Sequence[FrameDetections], image_ids) -> list[dict]:
    """COCO results format. ``image_ids`` maps ``d.frame`` -> GT image id: a dict (source frame -> id, gaps
    allowed) or a sequence indexed by frame. Frames without a GT image are not scored."""
    lookup = image_ids if isinstance(image_ids, dict) else dict(enumerate(image_ids))
    res = []
    for d in dets:
        img = lookup.get(d.frame)
        if img is None:
            continue
        for (x0, y0, x1, y1), s, c in zip(d.boxes, d.scores, d.labels):
            res.append({"image_id": int(img), "category_id": int(c),
                        "bbox": [float(x0), float(y0), float(x1 - x0), float(y1 - y0)], "score": float(s)})
    return res


def detectron2_detector(config_file: str, weights: str, score_threshold: float = 0.05,
                        class_map: dict[int, int] | None = None, device: str = "cpu") -> Detector:
    """Detectron2 model (e.g. Faster R-CNN X101-FPN of the VCM CTC). ``class_map`` maps model class -> GT id."""
    from detectron2.config import get_cfg          # optional dependency
    from detectron2.engine import DefaultPredictor

    cfg = get_cfg()
    cfg.merge_from_file(config_file)
    cfg.MODEL.WEIGHTS = weights
    cfg.MODEL.ROI_HEADS.SCORE_THRESH_TEST = score_threshold
    cfg.MODEL.DEVICE = device
    predictor = DefaultPredictor(cfg)

    def run(rgb: np.ndarray):
        inst = predictor(rgb[:, :, ::-1])["instances"].to("cpu")   # Detectron2 expects BGR by default
        labels = inst.pred_classes.numpy()
        if class_map is not None:
            keep = np.array([int(c) in class_map for c in labels], bool)
            inst, labels = inst[keep], np.array([class_map[int(c)] for c in labels[keep]], int)
        return inst.pred_boxes.tensor.numpy(), inst.scores.numpy(), labels

    return run


def torchvision_detector(arch: str, weights_file: str, score_threshold: float = 0.05,
                         class_map: dict[int, int] | None = None, device: str = "cpu") -> Detector:
    """torchvision detection model with a local state_dict (no download)."""
    import torch
    import torchvision

    model = getattr(torchvision.models.detection, arch)(weights=None, weights_backbone=None)
    model.load_state_dict(torch.load(weights_file, map_location="cpu"))
    model.eval().to(device)

    @torch.no_grad()
    def run(rgb: np.ndarray):
        x = torch.from_numpy(rgb).permute(2, 0, 1).float().div(255.0).to(device)
        o = model([x])[0]
        keep = o["scores"] >= score_threshold
        boxes, scores, labels = (o[k][keep].cpu().numpy() for k in ("boxes", "scores", "labels"))
        if class_map is not None:
            m = np.array([int(c) in class_map for c in labels], bool)
            boxes, scores = boxes[m], scores[m]
            labels = np.array([class_map[int(c)] for c in labels[m]], int)
        return boxes, scores, labels

    return run


def torchvision_model(arch: str, weights_file: str, device: str = "cpu"):
    """The torch module itself (for gradient-based oracles), loaded from a local state_dict."""
    import torch
    import torchvision

    model = getattr(torchvision.models.detection, arch)(weights=None, weights_backbone=None)
    model.load_state_dict(torch.load(weights_file, map_location="cpu"))
    return model.eval().to(device)


def torchvision_backbone_features(model):
    """Feature function rgb (1, 3, H, W) in [0, 1] -> list of FPN maps, using the model's own normalisation."""
    import torch

    mean = torch.tensor(model.transform.image_mean).view(1, 3, 1, 1)
    std = torch.tensor(model.transform.image_std).view(1, 3, 1, 1)
    for p in model.parameters():
        p.requires_grad_(False)

    def features(rgb):
        return list(model.backbone((rgb - mean) / std).values())

    return features


def build(spec: dict) -> Detector:
    """Build a detector from the ``detector`` section of the experiment config."""
    kind = spec["kind"]
    cmap = {int(k): int(v) for k, v in (spec.get("class_map") or {}).items()} or None
    if kind == "detectron2":
        return detectron2_detector(spec["config_file"], spec["weights"], spec.get("score_threshold", 0.05), cmap,
                                   spec.get("device", "cpu"))
    if kind == "torchvision":
        return torchvision_detector(spec["arch"], spec["weights"], spec.get("score_threshold", 0.05), cmap,
                                    spec.get("device", "cpu"))
    raise ValueError(f"unknown detector kind: {kind}")
