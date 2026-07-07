"""Precise pipeline -- SINGLE-PROCESS orchestrator (no conda subprocesses).

The original Precise pipeline (precise/run_precise.py) hands work between two conda
envs: the ``plaque`` env runs PST (cv2, numpy<2) and the ``plaqseg`` env runs PlaqSeg
+ the learned classifier (torch, ultralytics). A frozen/installed app cannot spawn
conda envs, so this module runs ALL stages in the CURRENT interpreter.

It works because numpy 1.26 satisfies both PST's ``numpy<2`` pin and torch/ultralytics,
so a single unified env (``plaqueapp``, the one we package) can import everything. The
algorithm is unchanged -- this just calls the same refactored cores:

  * dish geometry + mm/px + PST normal/sensitive centers : precise.pst_front.detect()
    (which calls plaque_gui.run_detection, exactly as the subprocess path did).
  * PlaqSeg YOLO tiling + inference + NMS               : _plaqseg.run_plaqseg.detect_plaqseg()
  * masks, density switch, PST-recall gating, optional blob, the --clf gate,
    union, sizing, overlay + CSV + summary               : precise.combine.combine_detections()

Public API:
  run_inprocess(image_path, plate_mm=100, out_dir=None, clf=True, clf_thr=None,
                blob=False, weights=None, conf=0.1, iou=0.5) -> dict (the summary)

Verify with:  python -m precise.pipeline IMAGE [OUT_DIR]
"""
import os
import sys

# repo root: under a PyInstaller bundle the data files (_plaqseg/models, _research/clf)
# are extracted under sys._MEIPASS; from source they sit at the project root (two dirs up).
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    _ROOT = sys._MEIPASS
else:
    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import cv2  # noqa: E402

# These imports pull cv2/numpy/torch/ultralytics; keep them lazy-friendly but module-level
# is fine since run_inprocess is only ever called when Precise is requested.
from precise import pst_front           # noqa: E402
from precise import combine             # noqa: E402

# default YOLO weights live next to the repo (or under sys._MEIPASS when frozen)
DEFAULT_WEIGHTS = os.path.join(_ROOT, "_plaqseg", "models", "small.pt")

# cache the (heavy) YOLO model between calls (batch / repeated single plates)
_YOLO_CACHE = {}


def torch_inprocess_available():
    """True iff torch + ultralytics import in the CURRENT interpreter (i.e. the unified
    or frozen env), meaning Precise can run in-process with no conda subprocesses."""
    try:
        import torch        # noqa: F401
        import ultralytics  # noqa: F401
        return True
    except Exception:
        return False


def _load_yolo(weights):
    if weights in _YOLO_CACHE:
        return _YOLO_CACHE[weights]
    from ultralytics import YOLO
    model = YOLO(weights)
    _YOLO_CACHE[weights] = model
    return model


def run_inprocess(image_path, plate_mm=100, out_dir=None, clf=True, clf_thr=None,
                  blob=False, weights=None, conf=0.1, iou=0.5, tag=None, base=None):
    """Run the entire Precise pipeline on ONE image in this process and return the
    summary dict (same shape as the subprocess path's summary_<tag>.json).

    Side effects (in out_dir): precise_<tag>.csv, precise_overlay_<tag>.jpg,
    summary_<tag>.json -- byte-for-byte the same artifacts the two-env path writes,
    so app.engine_api.detect_precise can consume them identically.

    clf=True enables the learned precision gate by default (the recommended Precise
    config); pass clf=False for the raw PlaqSeg+PST union. blob=False matches the
    subprocess default (blob_log over-detects on textured lawns)."""
    image_path = os.path.abspath(image_path)
    weights = weights or DEFAULT_WEIGHTS
    tag = tag or os.path.splitext(os.path.basename(image_path))[0]
    if out_dir is None:
        out_dir = os.path.join(os.path.dirname(image_path), "out_precise")
    os.makedirs(out_dir, exist_ok=True)

    def _embedded_mm(fallback):
        # No dish to calibrate from (e.g. an already-cropped plate): prefer an embedded
        # ImageJ/Fiji mm scale (our "…_plate.tif" crop carries one), else run uncalibrated.
        if fallback:
            return fallback
        try:
            import plate_crop
            return plate_crop.read_mm_per_px(image_path)
        except Exception:
            return None

    # Read the image + load the YOLO model up front (both stages need them).
    bgr = base["orig_bgr"] if base is not None else cv2.imread(image_path)
    if bgr is None:
        from PIL import Image
        import numpy as np
        bgr = cv2.cvtColor(np.array(Image.open(image_path).convert("RGB")),
                           cv2.COLOR_RGB2BGR)
    model = _load_yolo(weights)                 # pre-load in main thread (no cache race)
    from _plaqseg.run_plaqseg import detect_plaqseg

    # The PST SENSITIVE pass (OpenCV, one run_detection) and the YOLO inference (torch,
    # releases the GIL) are independent — both need only the image + calibration. Run them
    # CONCURRENTLY when we already have `base` (the GUI path, so calibration is known and
    # only one PST call happens → no engine-global race). Set PRECISE_PARALLEL=0 to disable.
    parallel = base is not None and os.environ.get("PRECISE_PARALLEL", "1") != "0"
    if parallel:
        import threading
        mmpp0 = _embedded_mm(base.get("pxl_per_mm"))     # calibration for YOLO, known up front
        out, errs = {}, {}

        def _guard(key, fn):
            try:
                out[key] = fn()
            except Exception as e:  # capture; re-raised on the main thread below
                errs[key] = e

        ta = threading.Thread(target=_guard, args=("pst",
                              lambda: pst_front.detect(image_path, str(plate_mm), base=base)))
        tb = threading.Thread(target=_guard, args=("ps",
                              lambda: detect_plaqseg(model, bgr, conf=conf, iou=iou, ppm=(mmpp0 or 0.0))))
        ta.start(); tb.start(); ta.join(); tb.join()
        if errs:
            raise next(iter(errs.values()))
        pst = out["pst"]
        ps_rows, _raw = out["ps"]
        mm_per_px = pst["mm_per_px"] or mmpp0
        pst["mm_per_px"] = mm_per_px
    else:
        pst = pst_front.detect(image_path, str(plate_mm), base=base)
        mm_per_px = pst["mm_per_px"] or _embedded_mm(None)
        pst["mm_per_px"] = mm_per_px
        ps_rows, _raw = detect_plaqseg(model, bgr, conf=conf, iou=iou, ppm=(mm_per_px or 0.0))

    # detect_plaqseg returns the CSV schema (X,Y,AREA_PXL,...); combine expects the
    # lowercase load_plaqseg schema. Convert in-memory (no CSV round-trip).
    ps_all = [{
        "x": float(r["X"]), "y": float(r["Y"]),
        "area_pxl": float(r.get("AREA_PXL", 0.0)),
        "diam_px": float(r.get("DIAMETER_PXL", 0.0)),
        "diam_mm": float(r.get("DIAMETER_MM", 0.0)),
        "conf": float(r.get("CONF", 0.0)),
    } for r in ps_rows]

    # --- Stages 2,4-10: combine (masks, density switch, recall gating, optional blob,
    # optional clf gate, union, sizing, overlay + CSV + summary). Pass the already-read
    # BGR so combine doesn't re-read the file.
    summary = combine.combine_detections(
        pst, ps_all, out_dir, tag,
        blob_enabled=bool(blob), bgr=bgr,
        clf_enabled=bool(clf),
        clf_thr=(float(clf_thr) if clf_thr is not None else None))
    return summary


def main():
    if len(sys.argv) < 2:
        print("usage: python -m precise.pipeline IMAGE [OUT_DIR] [PLATE_MM]")
        return 2
    image = sys.argv[1]
    out_dir = sys.argv[2] if len(sys.argv) > 2 else None
    plate_mm = float(sys.argv[3]) if len(sys.argv) > 3 else 100
    s = run_inprocess(image, plate_mm=plate_mm, out_dir=out_dir)
    print("PRECISE_INPROCESS_DONE n_final=%d overlay=%s csv=%s" % (
        s["n_final"], s.get("overlay"), s.get("csv")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
