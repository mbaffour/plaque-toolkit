"""In-app validation / scoring of the plaque detector against hand-corrected ground truth.

PURE Python — NO Qt imports here (numpy + pandas only; no scipy). This module lets a user
score the program's automatic detections against their own ground-truth labels (the JSON the
editor's "Save labels" button writes, schema "plaque-groundtruth-v1").

What it does:
  * For one labelled plate, run the chosen engine mode and greedily match detected plaques to
    the ground-truth plaques, then report precision / recall / F1 and size agreement (MAE, bias,
    Pearson on matched diameters).
  * Across many plates, aggregate per mode (micro precision/recall/F1 from summed tp/fp/fn,
    plus mean size MAE).

Calibration note
----------------
The engine derives its pixel->mm scale from the detected dish diameter and a plate_mm value.
To keep the detector's millimetre numbers comparable with the ground-truth millimetres, we try
to recover the dish size the labeller used from meta["mm_per_px"] and meta["dish_diam_px"]
(plate_mm ~= mm_per_px * dish_diam_px). If those are missing we fall back to plate_mm=100, the
app's default. Pixel-space matching (centres/radii) is unaffected by this; only the mm-size
agreement metrics depend on calibration matching the labels.
"""

import argparse
import glob
import json
import math
import os
import sys

import numpy as np
import pandas as pd


# Lazy / path-tolerant imports of the engine + GUI helpers. When run as a script we insert the
# repo root on sys.path in __main__ first; when imported as app.validate the package is already
# importable. We import inside helpers where practical so a missing optional dep (e.g. the heavy
# engine) doesn't break a bare `import app.validate`.
def _engine():
    try:
        from app import engine_api
    except Exception:  # running from inside the app/ dir or with repo root on the path
        import engine_api  # type: ignore
    return engine_api


def _measure_fn():
    try:
        import plaque_gui as pgui
    except Exception:  # pragma: no cover - repo root must be importable to score real files
        from .. import plaque_gui as pgui  # type: ignore
    return pgui.measure


IMAGE_EXTS = (".tif", ".tiff", ".jpg", ".jpeg", ".png", ".heic", ".heif")

# mode -> kwargs for engine_api.detect_single (precise is handled separately via detect_precise)
_MODE_KWARGS = {
    "published": {"published": True},
    "current": {"small": True},
    "sensitive": {"small": True, "sensitive": True},
}


# --------------------------------------------------------------------------- #
#  Point extraction
# --------------------------------------------------------------------------- #
def _plaque_points(plaques, ppm):
    """Return [(x, y, r_px, diam_mm), ...] from engine plaque dicts.

    r_px is the area-equivalent radius sqrt(area_pxl / pi); diam_mm comes from
    plaque_gui.measure(area_pxl, ppm)[2] (note: ppm is actually mm/px). Plaques missing a
    usable centre/area are skipped."""
    measure = _measure_fn()
    pts = []
    for p in plaques or []:
        try:
            area = float(p.get("area_pxl", 0.0))
        except (TypeError, ValueError):
            continue
        if area <= 0:
            continue
        center = p.get("center")
        if center is None:
            continue
        try:
            x = float(center[0])
            y = float(center[1])
        except (TypeError, ValueError, IndexError):
            continue
        r_px = math.sqrt(area / math.pi)
        diam_mm = float(measure(area, ppm)[2])
        pts.append((x, y, r_px, diam_mm))
    return pts


# --------------------------------------------------------------------------- #
#  Matching + scoring
# --------------------------------------------------------------------------- #
def match_and_score(gt_pts, det_pts, match_frac=0.5, min_radius_px=4.0):
    """Greedily match detections to ground truth and compute detection + size metrics.

    gt_pts / det_pts: lists of (x, y, r_px, diam_mm).

    For each ground-truth plaque (processed small-first so tight, small plaques claim their
    nearest detection before large ones sweep it up), find the nearest UNUSED detection whose
    centre lies within match_radius = max(min_radius_px, match_frac * gt_r). A match consumes
    that detection. TP = matched gt; FN = unmatched gt; FP = unmatched det.

    Size agreement is computed over matched (gt_diam_mm, det_diam_mm) pairs:
      size_mae_mm  = mean |gt - det|
      size_bias_mm = mean (det - gt)
      size_pearson = numpy.corrcoef(gt, det)[0,1] when >= 3 pairs (and both vary), else None

    Returns a dict: n_gt, n_det, tp, fp, fn, precision, recall, f1,
    size_mae_mm, size_bias_mm, size_pearson.
    """
    n_gt = len(gt_pts)
    n_det = len(det_pts)

    # process gt small-first so small plaques get first claim on a nearby detection
    gt_order = sorted(range(n_gt), key=lambda i: gt_pts[i][2])
    used_det = [False] * n_det

    tp = 0
    gt_diams = []
    det_diams = []
    for gi in gt_order:
        gx, gy, gr, gdiam = gt_pts[gi]
        match_radius = max(float(min_radius_px), float(match_frac) * float(gr))
        best_j = None
        best_d = None
        for j in range(n_det):
            if used_det[j]:
                continue
            dx = det_pts[j][0] - gx
            dy = det_pts[j][1] - gy
            d = math.hypot(dx, dy)
            if d <= match_radius and (best_d is None or d < best_d):
                best_d = d
                best_j = j
        if best_j is not None:
            used_det[best_j] = True
            tp += 1
            gt_diams.append(gdiam)
            det_diams.append(det_pts[best_j][3])

    fn = n_gt - tp
    fp = n_det - tp

    precision = (tp / (tp + fp)) if (tp + fp) > 0 else 0.0
    recall = (tp / (tp + fn)) if (tp + fn) > 0 else 0.0
    f1 = (2.0 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    if gt_diams:
        gt_arr = np.asarray(gt_diams, dtype=float)
        det_arr = np.asarray(det_diams, dtype=float)
        size_mae_mm = float(np.mean(np.abs(gt_arr - det_arr)))
        size_bias_mm = float(np.mean(det_arr - gt_arr))
    else:
        size_mae_mm = None
        size_bias_mm = None

    size_pearson = None
    if len(gt_diams) >= 3:
        gt_arr = np.asarray(gt_diams, dtype=float)
        det_arr = np.asarray(det_diams, dtype=float)
        # corrcoef is undefined (nan) if either series is constant; guard that to None
        if np.std(gt_arr) > 0 and np.std(det_arr) > 0:
            r = float(np.corrcoef(gt_arr, det_arr)[0, 1])
            size_pearson = r if math.isfinite(r) else None

    return {
        "n_gt": n_gt,
        "n_det": n_det,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "size_mae_mm": size_mae_mm,
        "size_bias_mm": size_bias_mm,
        "size_pearson": size_pearson,
    }


# --------------------------------------------------------------------------- #
#  Per-plate scoring against a label file
# --------------------------------------------------------------------------- #
def _resolve_image_path(label_json_path, meta):
    """Find the plate image: prefer meta['image_path'] (abs); fall back to a sibling file named
    meta['image'] next to the JSON; finally any sibling with a matching stem + known extension."""
    img = meta.get("image_path")
    if img and os.path.exists(img):
        return img
    base_dir = os.path.dirname(os.path.abspath(label_json_path))
    name = meta.get("image")
    if name:
        cand = os.path.join(base_dir, name)
        if os.path.exists(cand):
            return cand
        stem = os.path.splitext(name)[0]
        for ext in IMAGE_EXTS:
            cand = os.path.join(base_dir, stem + ext)
            if os.path.exists(cand):
                return cand
    # last resort: original image_path basename next to the json
    if img:
        cand = os.path.join(base_dir, os.path.basename(img))
        if os.path.exists(cand):
            return cand
    return img  # may be None / nonexistent; caller will error informatively


def _plate_mm_from_meta(meta):
    """Recover the dish diameter in mm the labeller used so the engine calibrates the same way.
    plate_mm ~= mm_per_px * dish_diam_px. Returns a float (mm) or None if not derivable."""
    try:
        mmpp = meta.get("mm_per_px")
        dpx = meta.get("dish_diam_px")
        if mmpp and dpx:
            val = float(mmpp) * float(dpx)
            if 1.0 < val < 1000.0:  # sanity window (a Petri dish is tens of mm)
                return val
    except (TypeError, ValueError):
        pass
    return None


def _gt_points_from_labels(plaques):
    """Build (x, y, r_px, diam_mm) tuples directly from the label JSON plaque records."""
    pts = []
    for p in plaques or []:
        try:
            x = float(p["x_px"])
            y = float(p["y_px"])
        except (KeyError, TypeError, ValueError):
            continue
        # radius: prefer r_px, else derive from area_px
        r_px = p.get("r_px")
        if r_px is None:
            area = p.get("area_px")
            r_px = math.sqrt(float(area) / math.pi) if area else 0.0
        try:
            r_px = float(r_px)
        except (TypeError, ValueError):
            r_px = 0.0
        try:
            diam_mm = float(p.get("diam_mm", 0.0))
        except (TypeError, ValueError):
            diam_mm = 0.0
        pts.append((x, y, r_px, diam_mm))
    return pts


def score_label_file(label_json_path, mode="precise", match_frac=0.5, progress=None):
    """Score one ground-truth label file against the engine running in `mode`.

    Loads the JSON (schema plaque-groundtruth-v1), builds gt points from its plaques, runs the
    engine on the plate image (recovering the labeller's dish mm for matching calibration, else
    plate_mm=100), extracts detection points, and scores via match_and_score.

    Returns {image, mode, n_gt, **metrics}. Raises on I/O / engine errors (caller wraps).
    """
    with open(label_json_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    meta = data.get("meta", {}) or {}
    gt_plaques = data.get("plaques", []) or []
    gt_pts = _gt_points_from_labels(gt_plaques)

    image_path = _resolve_image_path(label_json_path, meta)
    if not image_path or not os.path.exists(image_path):
        raise FileNotFoundError(
            "could not locate the plate image for %s (meta.image_path=%r, meta.image=%r)"
            % (os.path.basename(label_json_path), meta.get("image_path"), meta.get("image")))

    plate_mm = _plate_mm_from_meta(meta)
    if plate_mm is None:
        plate_mm = 100.0  # documented default when the labels don't carry dish size

    engine_api = _engine()

    if progress:
        progress("Scoring %s [%s]" % (os.path.basename(image_path), mode))

    if mode == "precise":
        det = engine_api.detect_precise(image_path, plate_mm=plate_mm, progress=progress)
    else:
        kwargs = _MODE_KWARGS.get(mode)
        if kwargs is None:
            raise ValueError("unknown mode %r (expected one of precise/published/current/sensitive)" % mode)
        det = engine_api.detect_single(image_path, plate_mm=plate_mm, **kwargs)

    ppm = det.get("pxl_per_mm")
    det_pts = _plaque_points(det.get("plaques", []), ppm)

    metrics = match_and_score(gt_pts, det_pts, match_frac=match_frac)
    out = {"image": os.path.basename(image_path), "mode": mode, "n_gt": len(gt_pts)}
    out.update(metrics)
    return out


# --------------------------------------------------------------------------- #
#  Batch validation
# --------------------------------------------------------------------------- #
def _collect_label_paths(label_paths):
    """Normalise the `label_paths` argument into a flat list of .json files.

    Accepts a single directory (glob labels_*.json within it; fall back to *.json), a single
    file path, or a list of files/dirs."""
    if isinstance(label_paths, (str, os.PathLike)):
        label_paths = [label_paths]
    files = []
    for entry in label_paths:
        entry = os.fspath(entry)
        if os.path.isdir(entry):
            found = sorted(glob.glob(os.path.join(entry, "labels_*.json")))
            if not found:
                found = sorted(glob.glob(os.path.join(entry, "*.json")))
            files.extend(found)
        else:
            files.append(entry)
    return files


def validate(label_paths, modes=("precise", "current"), match_frac=0.5, progress=None):
    """Validate the detector across one or more labelled plates and several modes.

    label_paths: a list of .json files OR a single directory (globs labels_*.json within it).
    modes: detection modes to evaluate (precise/published/current/sensitive).

    For each (file, mode) pair, score_label_file is run; failures become an error row (and an
    entry in `errors`) rather than aborting the run. Returns:
      {
        "per_plate_df": DataFrame  # one row per (file, mode), incl. error rows (NaN metrics),
        "per_mode_df":  DataFrame  # one row per mode: micro precision/recall/f1 + mean MAE,
        "errors":       [ {label_file, mode, error}, ... ],
      }
    """
    files = _collect_label_paths(label_paths)
    if isinstance(modes, str):
        modes = [m.strip() for m in modes.split(",") if m.strip()]

    rows = []
    errors = []
    for f in files:
        for mode in modes:
            try:
                res = score_label_file(f, mode=mode, match_frac=match_frac, progress=progress)
                res["label_file"] = os.path.basename(f)
                res["error"] = ""
                rows.append(res)
            except Exception as e:  # one bad plate/mode shouldn't sink the batch
                msg = "%s: %s" % (type(e).__name__, e)
                errors.append({"label_file": os.path.basename(f), "mode": mode, "error": msg})
                rows.append({
                    "label_file": os.path.basename(f), "image": "", "mode": mode,
                    "n_gt": None, "n_det": None, "tp": None, "fp": None, "fn": None,
                    "precision": None, "recall": None, "f1": None,
                    "size_mae_mm": None, "size_bias_mm": None, "size_pearson": None,
                    "error": msg,
                })

    per_plate_cols = ["label_file", "image", "mode", "n_gt", "n_det", "tp", "fp", "fn",
                      "precision", "recall", "f1", "size_mae_mm", "size_bias_mm",
                      "size_pearson", "error"]
    per_plate_df = pd.DataFrame(rows, columns=per_plate_cols)

    # Aggregate per mode: micro precision/recall/f1 from SUMMED tp/fp/fn; mean size_mae_mm.
    mode_rows = []
    for mode in modes:
        sub = per_plate_df[(per_plate_df["mode"] == mode) & (per_plate_df["error"] == "")]
        tp = float(pd.to_numeric(sub["tp"], errors="coerce").sum())
        fp = float(pd.to_numeric(sub["fp"], errors="coerce").sum())
        fn = float(pd.to_numeric(sub["fn"], errors="coerce").sum())
        precision = (tp / (tp + fp)) if (tp + fp) > 0 else 0.0
        recall = (tp / (tp + fn)) if (tp + fn) > 0 else 0.0
        f1 = (2.0 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
        mae_series = pd.to_numeric(sub["size_mae_mm"], errors="coerce").dropna()
        mean_mae = float(mae_series.mean()) if len(mae_series) else None
        mode_rows.append({
            "mode": mode,
            "n_plates": int(len(sub)),
            "tp": int(tp), "fp": int(fp), "fn": int(fn),
            "precision": precision, "recall": recall, "f1": f1,
            "mean_size_mae_mm": mean_mae,
        })
    per_mode_df = pd.DataFrame(
        mode_rows,
        columns=["mode", "n_plates", "tp", "fp", "fn", "precision", "recall", "f1",
                 "mean_size_mae_mm"])

    return {"per_plate_df": per_plate_df, "per_mode_df": per_mode_df, "errors": errors}


# --------------------------------------------------------------------------- #
#  CLI
# --------------------------------------------------------------------------- #
def _main(argv=None):
    ap = argparse.ArgumentParser(
        description="Validate the plaque detector against hand-corrected ground-truth labels.")
    ap.add_argument("labels", help="a ground-truth labels .json file OR a directory of them")
    ap.add_argument("--modes", default="precise,current",
                    help="comma-separated detection modes (precise,current,published,sensitive)")
    ap.add_argument("--match-frac", type=float, default=0.5,
                    help="match radius = max(4px, match_frac * gt_radius_px); default 0.5")
    args = ap.parse_args(argv)

    modes = [m.strip() for m in args.modes.split(",") if m.strip()]

    def _progress(msg):
        print("  ..", msg)

    result = validate(args.labels, modes=modes, match_frac=args.match_frac, progress=_progress)

    pd.set_option("display.width", 160)
    pd.set_option("display.max_columns", 20)
    print("\nPer-mode summary")
    print("================")
    print(result["per_mode_df"].to_string(index=False))
    if result["errors"]:
        print("\n%d error(s):" % len(result["errors"]))
        for e in result["errors"]:
            print("  %s [%s]: %s" % (e["label_file"], e["mode"], e["error"]))
    return 0


if __name__ == "__main__":
    # Insert repo root on sys.path so `app.validate` / `plaque_gui` / `engine_api` resolve when
    # this file is run directly (python app/validate.py ...).
    _repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)
    raise SystemExit(_main())
