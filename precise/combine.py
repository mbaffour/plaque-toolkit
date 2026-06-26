"""Precise pipeline -- PLAQSEG-ENV combiner (stages 2 through 10).

Runs in the 'plaqseg' conda env (ultralytics, torch CPU, cv2, scikit-image, numpy2).
Consumes the JSON written by pst_front.py (dish, calibration, PST normal+sensitive
centers) plus the PlaqSeg CSV produced by _plaqseg/run_plaqseg.py, and emits the final
per-plaque CSV, a colored overlay, and a one-line summary.

Decided pipeline (PlaqSeg-primary, PST-recall-boost, dish-calibrated):
  2. Artifact masks from dish geometry: lawn ROI (0.80*radius), blue-label mask,
     hard dish-boundary reject.
  3. PRIMARY = PlaqSeg detections (X,Y,AREA_PXL,DIAMETER_MM,CONF); drop any outside
     lawn ROI / on label / outside dish.
  4. Internal float flat-field for the recall pass ONLY (GaussianBlur bg sigma=W/8,
     interior-only divide, float32, no JPEG write, no CLAHE).
  5. Density switch: if n_plaqseg >= DENSE_FACTOR * n_pst_sensitive -> dense -> final
     = PlaqSeg set (skip PST recall + blob_log).
  6. PST recall gating (sparse/clean): accept a PST-sensitive center only if inside
     lawn ROI, not within match-radius of any PlaqSeg det, AND center-vs-ring contrast
     on the float-flattened lawn >= CONTRAST_FLOOR.
  7. Optional blob_log recovery (sparse only): blob_log on float-flattened inverted
     lawn, same masks + contrast gate, add only unmatched blobs.
  8. Combine: UNION(PlaqSeg, gated PST-only, gated blob-only); dedup by match-radius.
  9. Sizing: PlaqSeg detections keep their mask-area diameter; recovered PST use
     equiv-diameter from area_pxl; recovered blobs use 2*r_px*mm_per_px.
 10. Output: per-plaque CSV (X,Y,DIAMETER_MM,SOURCE,CONFIRMED) + colored overlay
     (green=PlaqSeg, blue=recovered, cyan lawn ring, dish circle) + summary row.

Usage:
  python combine.py PST_JSON PLAQSEG_CSV OUT_DIR TAG
"""
import sys
import os
import csv
import math
import json

import numpy as np
import cv2
from skimage.feature import blob_log

# repo root: under a PyInstaller bundle the data files (_research/clf) are extracted
# under sys._MEIPASS; from source they sit at the project root (two dirs up).
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    _ROOT = sys._MEIPASS
else:
    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
try:
    from scalebar import draw_scale_bar       # physical mm scale bar on the overlay
except Exception:
    draw_scale_bar = None

# --------------------------------------------------------------------------- #
#  OPTIONAL learned precision gate (plaque-vs-texture classifier).
#  Default OFF -> the validated hand-tuned-contrast path is unchanged. When
#  enabled (PRECISE_CLF=1 or run_precise.py --clf), every candidate detection
#  (PlaqSeg primary + gated-PST + blob) is re-cropped to the SAME 48x48 patch
#  convention used to mine the training data, scored by _research/clf/infer.py,
#  and kept only if P(plaque) >= PRECISE_CLF_THR.
# --------------------------------------------------------------------------- #
CLF_DIR = os.path.join(_ROOT, "_research", "clf")
# patch geometry -- MUST mirror stage2_mine.crop_norm so the classifier sees the
# same distribution it was trained on.
CLF_PATCH = 48
CLF_FILL = 0.55
CLF_MIN_HALF = 14
CLF_MAX_HALF = 200

# ---- tunables (match the prototypes) -------------------------------------- #
# Each tunable can be overridden via an environment variable (PRECISE_<NAME>)
# for cheap parameter sweeps without editing the source. Defaults below are the
# locked-in engine defaults.
def _envf(name, default):
    v = os.environ.get("PRECISE_" + name)
    return float(v) if v is not None else default

LAWN_FRAC = _envf("LAWN_FRAC", 0.80)          # lawn ROI = inner 80% of dish radius
LABEL_DILATE = 15         # blue-label dilation (px)
MIN_TOL_MM = _envf("MIN_TOL_MM", 0.35)        # match-radius floor (mm)
CONTRAST_FLOOR = _envf("CONTRAST_FLOOR", 0.030)  # center-vs-ring contrast gate on the float-flattened lawn
RING_K = 2.2              # outer ring radius = RING_K * detection radius
DENSE_FACTOR = _envf("DENSE_FACTOR", 1.5)     # density switch: n_plaqseg >= 1.5*n_pst_sensitive -> dense
MATCH_TOL_SCALE = _envf("MATCH_TOL_SCALE", 1.0)  # multiplies the PlaqSeg/PST de-dup match radius
# learned precision gate (default OFF -> validated path unchanged)
CLF_ENABLED = os.environ.get("PRECISE_CLF", "0") not in ("0", "", "false", "False")
CLF_THR = _envf("CLF_THR", 0.5)               # keep detection only if P(plaque) >= CLF_THR
# blob_log (sparse recovery)
BLOB_MIN_SIGMA = 1.6
BLOB_MAX_SIGMA = 16.0
BLOB_NUM_SIGMA = 12
BLOB_THRESHOLD = 0.035
BLOB_OVERLAP = 0.6


# --------------------------------------------------------------------------- #
#  Stage 4: internal float flat-field (recall pass only -- NO write, NO CLAHE)
# --------------------------------------------------------------------------- #
def float_flatten(gray, img_w):
    """Smooth-background divide -> float32 in [0,1]. sigma = img_width/8."""
    g = gray.astype(np.float32)
    sigma = img_w / 8.0
    bg = cv2.GaussianBlur(g, (0, 0), sigmaX=sigma)
    flat = g / (bg + 1e-3)
    flat = np.clip(flat, 0, 2.0)
    flat = (flat - flat.min()) / (flat.max() - flat.min() + 1e-9)
    return flat


def center_ring_contrast(flat, x, y, r_px):
    """Positive => center darker than surrounding ring (real-plaque signature)."""
    H, W = flat.shape
    cr = max(int(r_px), 2)
    x0, x1 = max(0, int(x) - cr), min(W, int(x) + cr + 1)
    y0, y1 = max(0, int(y) - cr), min(H, int(y) + cr + 1)
    if x1 <= x0 or y1 <= y0:
        return None
    center_val = float(flat[y0:y1, x0:x1].mean())
    rr = int(r_px * RING_K) + 1
    rx0, rx1 = max(0, int(x) - rr), min(W, int(x) + rr + 1)
    ry0, ry1 = max(0, int(y) - rr), min(H, int(y) + rr + 1)
    ring_patch = flat[ry0:ry1, rx0:rx1]
    cyl, cxl = int(y) - ry0, int(x) - rx0
    yy, xx = np.ogrid[:ring_patch.shape[0], :ring_patch.shape[1]]
    ring_mask = ((xx - cxl) ** 2 + (yy - cyl) ** 2) > cr ** 2
    if ring_mask.sum() < 4:
        return None
    ring_val = float(ring_patch[ring_mask].mean())
    return ring_val - center_val


# --------------------------------------------------------------------------- #
#  Learned-gate helpers
# --------------------------------------------------------------------------- #
def clf_crop(bgr, cx, cy, dia_px):
    """Scale-normalized 48x48 BGR patch -- mirrors stage2_mine.crop_norm exactly
    (window half-size so the detection fills ~FILL of the frame). Returns None if
    the window falls off the image (same reject behaviour as training)."""
    H, W = bgr.shape[:2]
    half = int(round((dia_px / CLF_FILL) / 2.0))
    half = max(CLF_MIN_HALF, min(CLF_MAX_HALF, half))
    x0, y0 = int(round(cx - half)), int(round(cy - half))
    x1, y1 = x0 + 2 * half, y0 + 2 * half
    if x0 < 0 or y0 < 0 or x1 > W or y1 > H:
        return None
    win = bgr[y0:y1, x0:x1]
    if win.shape[0] < 2 or win.shape[1] < 2:
        return None
    return cv2.resize(win, (CLF_PATCH, CLF_PATCH), interpolation=cv2.INTER_AREA)


def load_clf():
    """Import _research/clf/infer.py and load the model. Returns (model, meta) or
    raises with a clear message if torch/torchvision or the checkpoint is absent."""
    import importlib.util
    infer_path = os.path.join(CLF_DIR, "infer.py")
    spec = importlib.util.spec_from_file_location("clf_infer", infer_path)
    infer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(infer)
    model, meta = infer.load_model()
    return infer, model, meta


# --------------------------------------------------------------------------- #
def load_plaqseg(csv_path):
    """PlaqSeg rows: X,Y,AREA_PXL,DIAMETER_PXL,DIAMETER_MM,CONF."""
    rows = []
    if not os.path.exists(csv_path):
        return rows
    with open(csv_path) as f:
        for r in csv.DictReader(f):
            rows.append({
                "x": float(r["X"]), "y": float(r["Y"]),
                "area_pxl": float(r.get("AREA_PXL", 0.0)),
                "diam_px": float(r.get("DIAMETER_PXL", 0.0)),
                "diam_mm": float(r.get("DIAMETER_MM", 0.0)),
                "conf": float(r.get("CONF", 0.0)),
            })
    return rows


def combine_detections(pst, ps_all, out_dir, tag, blob_enabled=True, bgr=None,
                       clf_enabled=None, clf_thr=None):
    """Stages 2-10 of the Precise pipeline as an importable function.

    ``pst`` is the dish/calibration/PST-centers dict (same shape as pst_front's JSON),
    ``ps_all`` is the list of PlaqSeg detection dicts (load_plaqseg's schema). Writes
    precise_<tag>.csv, precise_overlay_<tag>.jpg and summary_<tag>.json into out_dir and
    returns the summary dict. The CLI ``main()`` is a thin shim around this so the
    algorithm lives in one place (also called in-process by precise/pipeline.py).

    ``clf_enabled`` / ``clf_thr`` default to the module-level CLF_ENABLED / CLF_THR
    (driven by PRECISE_CLF / PRECISE_CLF_THR), but callers can pass them explicitly so
    the in-process path doesn't have to mutate os.environ."""
    if clf_enabled is None:
        clf_enabled = CLF_ENABLED
    if clf_thr is None:
        clf_thr = CLF_THR
    os.makedirs(out_dir, exist_ok=True)

    image = pst["image"]
    mm_per_px = pst["mm_per_px"]                 # mm per pixel
    px_per_mm = (1.0 / mm_per_px) if mm_per_px else None
    plate = pst["plate"]
    if plate is None:
        raise SystemExit("no dish detected for %s -- cannot calibrate" % tag)
    cx, cy = plate["center"]
    radius = plate["radius"]
    lawn_r = radius * LAWN_FRAC

    pst_sensitive = pst["pst_sensitive"]
    n_pst_sensitive = pst["n_pst_sensitive"]

    if bgr is None:
        bgr = cv2.imread(image)
        if bgr is None:
            from PIL import Image
            bgr = cv2.cvtColor(np.array(Image.open(image).convert("RGB")),
                               cv2.COLOR_RGB2BGR)
    H, W = bgr.shape[:2]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    # ---- Stage 2: artifact masks ----------------------------------------- #
    Y, X = np.ogrid[:H, :W]
    dist2 = (X - cx) ** 2 + (Y - cy) ** 2
    lawn_mask = dist2 <= lawn_r ** 2          # inside lawn ROI
    dish_mask = dist2 <= radius ** 2          # inside dish (hard boundary)

    b, g, r = cv2.split(bgr.astype(np.int16))
    blue_label = (b - r > 25) & (b > 90)
    blue_label = cv2.dilate(blue_label.astype(np.uint8),
                            np.ones((LABEL_DILATE, LABEL_DILATE), np.uint8)).astype(bool)
    keep_mask = lawn_mask & (~blue_label)     # accept region for any detection

    def accepted(px, py):
        ix, iy = int(round(px)), int(round(py))
        if ix < 0 or iy < 0 or ix >= W or iy >= H:
            return False
        if not dish_mask[iy, ix]:
            return False                       # hard dish-boundary reject
        return bool(keep_mask[iy, ix])

    # ---- Stage 3: PlaqSeg primary (masked) ------------------------------- #
    ps = [d for d in ps_all if accepted(d["x"], d["y"])]
    n_plaqseg = len(ps)
    ps_xy = np.array([[d["x"], d["y"]] for d in ps]) if ps else np.zeros((0, 2))

    # match radius: median PlaqSeg equivalent radius, floored at 0.35 mm.
    ps_radii = [math.sqrt(d["area_pxl"] / math.pi) for d in ps if d["area_pxl"] > 0]
    med_r = float(np.median(ps_radii)) if ps_radii else (
        0.4 * px_per_mm if px_per_mm else 12.0)
    min_tol = (MIN_TOL_MM * px_per_mm) if px_per_mm else 10.0
    match_r = max(med_r, min_tol) * MATCH_TOL_SCALE

    # ---- Stage 5: density switch ----------------------------------------- #
    dense = (n_pst_sensitive > 0 and n_plaqseg >= DENSE_FACTOR * n_pst_sensitive)
    regime = "dense" if dense else "sparse"

    # ---- Stage 4: float flat-field (recall only) ------------------------- #
    flat = None
    if not dense:
        flat = float_flatten(gray, W)

    def nearest_ps_dist(px, py):
        if len(ps_xy) == 0:
            return float("inf")
        return float(np.min(np.hypot(ps_xy[:, 0] - px, ps_xy[:, 1] - py)))

    # ---- Stage 6: PST recall gating (sparse only) ------------------------ #
    pst_recovered = []          # dicts: x,y,diam_mm
    if not dense:
        for d in pst_sensitive:
            px, py = d["x"], d["y"]
            if not accepted(px, py):
                continue
            if nearest_ps_dist(px, py) <= match_r:
                continue                       # already covered by PlaqSeg
            # equivalent radius from PST area for the contrast window
            a = d.get("area_pxl", 0.0)
            r_px = math.sqrt(a / math.pi) if a > 0 else min_tol
            c = center_ring_contrast(flat, px, py, r_px)
            if c is None or c < CONTRAST_FLOOR:
                continue
            diam_mm = (2.0 * r_px) * mm_per_px if mm_per_px else 0.0
            pst_recovered.append({"x": px, "y": py, "diam_mm": diam_mm})

    # ---- Stage 7: optional blob_log recovery (sparse only) --------------- #
    blob_recovered = []
    if not dense and blob_enabled:
        inv = 1.0 - flat
        inv[~keep_mask] = 0.0
        blobs = blob_log(inv, min_sigma=BLOB_MIN_SIGMA, max_sigma=BLOB_MAX_SIGMA,
                         num_sigma=BLOB_NUM_SIGMA, threshold=BLOB_THRESHOLD,
                         overlap=BLOB_OVERLAP)
        # combined set so far for dedup
        taken = list(ps_xy) + [[d["x"], d["y"]] for d in pst_recovered]
        taken = np.array(taken) if taken else np.zeros((0, 2))
        for by, bx, sigma in blobs:
            if not accepted(bx, by):
                continue
            r_px = sigma * math.sqrt(2)
            c = center_ring_contrast(flat, bx, by, r_px)
            if c is None or c < CONTRAST_FLOOR:
                continue
            if len(taken):
                if float(np.min(np.hypot(taken[:, 0] - bx, taken[:, 1] - by))) <= match_r:
                    continue
            diam_mm = (2.0 * r_px) * mm_per_px if mm_per_px else 0.0
            blob_recovered.append({"x": float(bx), "y": float(by), "diam_mm": diam_mm})
            taken = np.vstack([taken, [bx, by]]) if len(taken) else np.array([[bx, by]])

    # ---- Stage 7.5: OPTIONAL learned precision gate ---------------------- #
    # Crop the SAME 48x48 patch for every candidate (PlaqSeg + gated-PST + blob),
    # score P(plaque), and drop anything below CLF_THR. Default OFF.
    n_clf_dropped = {"plaqseg": 0, "pst": 0, "blob": 0}
    clf_used = False
    if clf_enabled:
        # candidate diameter in px for the crop window
        def dia_px_of(d, is_plaqseg):
            if is_plaqseg and d.get("diam_px", 0) > 0:
                return d["diam_px"]
            if px_per_mm and d.get("diam_mm", 0) > 0:
                return d["diam_mm"] * px_per_mm
            return 2.0 * min_tol  # fallback window

        cand_specs = (
            [(d, "plaqseg", dia_px_of(d, True)) for d in ps]
            + [(d, "pst", dia_px_of(d, False)) for d in pst_recovered]
            + [(d, "blob", dia_px_of(d, False)) for d in blob_recovered]
        )
        infer, model, meta = load_clf()
        clf_used = True
        kept_ps, kept_pst, kept_blob = [], [], []
        bucket = {"plaqseg": kept_ps, "pst": kept_pst, "blob": kept_blob}
        # batch the patches that actually crop; off-image crops are kept (cannot
        # be scored -- same as the detector that produced them, fail-open).
        patches, owners = [], []
        for d, src, dpx in cand_specs:
            patch = clf_crop(bgr, d["x"], d["y"], dpx)
            if patch is None:
                bucket[src].append(d)  # cannot score -> keep (fail-open)
                continue
            patches.append(patch)
            owners.append((d, src))
        if patches:
            probs = infer.prob_plaque_batch(model, meta, patches)
        else:
            probs = np.zeros(0, np.float32)
        for (d, src), p in zip(owners, probs):
            d["p_plaque"] = float(p)
            if p >= clf_thr:
                bucket[src].append(d)
            else:
                n_clf_dropped[src] += 1
        ps, pst_recovered, blob_recovered = kept_ps, kept_pst, kept_blob
        n_plaqseg = len(ps)

    # ---- Stage 8/9: combine + sizing ------------------------------------- #
    final = []
    for d in ps:
        final.append({"x": d["x"], "y": d["y"], "diam_mm": d["diam_mm"],
                      "source": "plaqseg", "confirmed": True,
                      "p_plaque": d.get("p_plaque")})
    for d in pst_recovered:
        final.append({"x": d["x"], "y": d["y"], "diam_mm": d["diam_mm"],
                      "source": "pst", "confirmed": False,
                      "p_plaque": d.get("p_plaque")})
    for d in blob_recovered:
        final.append({"x": d["x"], "y": d["y"], "diam_mm": d["diam_mm"],
                      "source": "blob", "confirmed": False,
                      "p_plaque": d.get("p_plaque")})

    n_final = len(final)
    diams = np.array([d["diam_mm"] for d in final if d["diam_mm"] > 0])

    # uncertainty flag: large disagreement between the two primary detectors.
    big_disagree = abs(n_plaqseg - n_pst_sensitive) > 0.5 * max(n_plaqseg, n_pst_sensitive, 1)

    # ---- Stage 10: outputs ----------------------------------------------- #
    csv_path = os.path.join(out_dir, "precise_%s.csv" % tag)
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["X", "Y", "DIAMETER_MM", "SOURCE", "CONFIRMED", "P_PLAQUE"])
        for d in final:
            pp = d.get("p_plaque")
            w.writerow(["%.1f" % d["x"], "%.1f" % d["y"], "%.3f" % d["diam_mm"],
                        d["source"], "TRUE" if d["confirmed"] else "FALSE",
                        ("%.4f" % pp) if pp is not None else ""])

    ov = bgr.copy()
    cv2.circle(ov, (int(cx), int(cy)), int(radius), (0, 165, 255), 3)     # dish (orange)
    cv2.circle(ov, (int(cx), int(cy)), int(lawn_r), (255, 255, 0), 3)     # lawn (cyan)
    rdraw = max(int(round(match_r)), 6)
    for d in final:
        if d["source"] == "plaqseg":
            col = (0, 220, 0)       # green = PlaqSeg / confirmed
        else:
            col = (255, 0, 0)       # blue = recovered (PST / blob)
        cv2.circle(ov, (int(d["x"]), int(d["y"])), rdraw, col, 3)
    txt = "PlaqSeg=%d  +PST=%d  +blob=%d  final=%d  [%s]" % (
        n_plaqseg, len(pst_recovered), len(blob_recovered), n_final, regime)
    cv2.putText(ov, txt, (30, 70), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (0, 0, 0), 8)
    cv2.putText(ov, txt, (30, 70), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (255, 255, 255), 3)
    if draw_scale_bar is not None and mm_per_px:
        try:
            draw_scale_bar(ov, mm_per_px)
        except Exception:
            pass
    ov_path = os.path.join(out_dir, "precise_overlay_%s.jpg" % tag)
    cv2.imwrite(ov_path, ov, [cv2.IMWRITE_JPEG_QUALITY, 88])

    summary = {
        "tag": tag,
        "image": os.path.basename(image),
        "n_plaqseg": n_plaqseg,
        "n_pst_sensitive": n_pst_sensitive,
        "n_pst_normal": pst.get("n_pst_normal"),
        "n_pst_recovered": len(pst_recovered),
        "n_blob_recovered": len(blob_recovered),
        "n_final": n_final,
        "match_radius_px": round(match_r, 1),
        "match_radius_mm": (round(match_r * mm_per_px, 3) if mm_per_px else None),
        "median_diam_mm": (round(float(np.median(diams)), 3) if len(diams) else None),
        "mean_diam_mm": (round(float(np.mean(diams)), 3) if len(diams) else None),
        "density_regime": regime,
        "clf_gate": clf_used,
        "clf_thr": (clf_thr if clf_used else None),
        "n_clf_dropped": (n_clf_dropped if clf_used else None),
        "uncertainty_flag": bool(big_disagree),
        "mm_per_px": mm_per_px,
        "px_per_mm": px_per_mm,
        "csv": csv_path,
        "overlay": ov_path,
    }
    sum_path = os.path.join(out_dir, "summary_%s.json" % tag)
    with open(sum_path, "w") as f:
        json.dump(summary, f, indent=2)
    return summary


def main():
    pst_json, ps_csv, out_dir, tag = sys.argv[1:5]
    # optional 6th arg: "1" (default) enables blob_log recovery, "0" disables it.
    blob_enabled = (len(sys.argv) < 6) or (sys.argv[5] != "0")
    pst = json.load(open(pst_json))
    ps_all = load_plaqseg(ps_csv)
    summary = combine_detections(pst, ps_all, out_dir, tag, blob_enabled=blob_enabled)
    print("PRECISE_RESULT " + json.dumps(summary))


if __name__ == "__main__":
    main()
