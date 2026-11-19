"""The detector side of a Precise run, recorded the same way by both Precise paths.

summary_<tag>.json gets a ``yolo`` block (weights identity, thresholds, inference size, tiling
edge rule, max_det) whether Precise ran in-process (precise/pipeline.py) or through the two-env
runner (precise/run_precise.py); the runner used to write none (CT-R1 F22). Kept free of
torch / ultralytics imports so the plaque-env runner can use it.
"""
import hashlib
import os

MAX_DET_DEFAULT = 1000      # _plaqseg/run_plaqseg.py: PLAQSEG_MAX_DET default


def max_det():
    return int(os.environ.get("PLAQSEG_MAX_DET", str(MAX_DET_DEFAULT)))


def yolo_block(weights, conf, iou, imgsz):
    wpath = str(weights)
    wsha = ""
    if os.path.exists(wpath):
        with open(wpath, "rb") as fh:
            wsha = hashlib.sha256(fh.read()).hexdigest()[:16]
    keep_edge = os.environ.get("PLAQSEG_KEEP_EDGE", "0") not in ("0", "", "false", "False")
    return {"weights": os.path.basename(wpath), "weights_sha256_16": wsha,
            "conf": float(conf), "iou": float(iou), "imgsz": int(imgsz),
            "tile_edge_fragments_dropped": not keep_edge, "max_det": max_det()}
