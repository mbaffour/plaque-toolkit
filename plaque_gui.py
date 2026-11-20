"""
Interactive GUI companion for plaque_size_tool.

Runs the SAME automatic detection + calibration as plaque_size_tool.py, then lets
you correct the result by hand:

  * left-drag            -> add a missed plaque as a circle (click centre, drag to edge)
  * left-click (Trace)   -> add a missed plaque by auto-tracing its outline
  * right-click          -> remove a plaque (auto or manual) under the cursor
  * Undo button / 'u'    -> undo the last add/remove
  * Save button / 's'    -> write the combined result (overwrites the standard outputs)
  * Mode button / 't'    -> toggle between Circle and Trace add-modes

Manual measurements use the exact same pixel->mm calibration as the automatic ones,
so the numbers are directly comparable. Output files (overwritten on Save):
  out/data-green-<name>.csv   (adds a SOURCE column: auto / manual)
  out/out_<name>.<ext>        (auto plaques green, manual plaques blue)

Usage:
  python plaque_gui.py -i IMAGE [-p PLATE_MM] [-small]
  python plaque_gui.py IMAGE  [-p PLATE_MM] [-small]
  python plaque_gui.py            (opens a file picker)
"""

import argparse
import math
import os

import cv2
import numpy as np
import pandas as pd
import imutils
from PIL import Image, ImageEnhance

import plaque_size_tool as pst

try:
    from scalebar import draw_scale_bar
except Exception:          # never let a missing helper break detection/saves
    draw_scale_bar = None

# Module-level toggle: stamp a physical scale bar onto saved annotated images.
# Set to False to disable everywhere this save_results is used (GUI editor, app,
# measure_samples.py). The actual draw is also guarded by try/except below.
draw_scalebar = True


# --------------------------------------------------------------------------- #
#  Detection (mirrors plaque_size_tool.main() for a single image)
# --------------------------------------------------------------------------- #
SCALES = ("auto", "standard", "small")
# Labels for the app's "Plaque size" choice (key, label). Published offers only the last two.
SCALE_LABELS = (("auto", "Auto (both scales)"), ("standard", "Standard"),
                ("small", "Small (< ~2.5 mm)"))


def resolve_scale(scale=None, small=False, published=False):
    """The plaque-size scale a run really uses. ``scale`` wins; None falls back to the old
    ``small`` switch (True = "small", False = "standard"). Published never runs Auto: it is
    the unchanged published algorithm, one pass at the standard or the -small block size."""
    s = scale if scale in SCALES else ("small" if small else "standard")
    if published and s == "auto":
        s = "standard"
    return s


def run_detection(image_path, plate_size, small, sensitive=False, scale=None, info=None):
    """Return (display_rgb, orig_bgr, proc_gray, plaques, pxl_per_mm, candidates, lawn_gray, plate).
    sensitive=True lowers the size gates to catch very small plaques (more, noisier); it is
    forced OFF in --published mode so the validated algorithm is never altered.

    ``scale`` (CT-R1 detection D1-D3) selects the app's plaque-size handling for the
    NON-published engines: "standard" (block 231), "small" (block 49) or "auto" (both passes
    merged, see _run_scaled). Left as None the call is exactly the pre-1.3 one-pass path
    (``small`` picks the block size, the dish comes from that same pass, nothing is dropped):
    Precise's PST front relies on that so its numbers do not change. Under --published the
    one-pass path always runs (``scale`` only picks small or standard), so the app's Published
    engine keeps matching `plaque_size_tool.py --published`.

    ``info``: an optional dict this call fills with how the result was made (scale, where the
    dish came from or why there is none, n_outside_dish, dish_warnings); the 8-tuple return
    stays as it was for every existing caller."""
    if scale is not None:
        if pst.use_published:
            small = resolve_scale(scale, small, published=True) == "small"
        else:
            return _run_scaled(image_path, plate_size, resolve_scale(scale), sensitive, info)
    if info is not None:
        info.update({"scale": "small" if small else "standard", "dish_source": "same pass",
                     "dish_reason": None, "n_outside_dish": 0, "dish_warnings": []})
    pst.small_plaques = bool(small)
    pst.sensitive = bool(sensitive) and not pst.use_published
    pst.debug_mode = False

    # HEIC-safe read + in-memory dimming (no temp files)
    orig = pst.read_image_bgr(image_path)
    image = orig
    image_brightness = float(cv2.cvtColor(orig, cv2.COLOR_BGR2GRAY).mean())
    if image_brightness > 70:
        image = np.clip(orig.astype(np.float32) * 0.5, 0, 255).astype(np.uint8)

    binary_image, high_contrast, clr_high_contrast = pst.process_image(image, 2.5)
    contours = pst.get_contours(binary_image)
    image_size = binary_image.shape

    green_df, red_df, other_df, plate_df = pst.filter_contours(contours, image_size)
    if pst.watershed_enabled:
        rec = pst.recover_merged_plaques(image_size, green_df, red_df, other_df)
        green_df = green_df.copy()
        green_df["SOURCE"] = "auto"
        if not rec.empty:
            rec = rec.copy()
            rec["SOURCE"] = "watershed"
            green_df = pd.concat([green_df, rec], ignore_index=True)
    green_df_copy = pst.check_duplicate_plaques(green_df.copy())
    green_df_copy = pst.calculate_size_mm(plate_size, green_df_copy, plate_df)

    if green_df_copy.size > 0:
        green_df_copy["MEAN_COLOUR"] = green_df_copy.apply(
            lambda x: pst.get_mean_grey_colour(clr_high_contrast, x["CONTOURS"]), axis=1)
        keep = green_df_copy.apply(lambda x: abs(x["MEAN_COLOUR"]) >= 40, axis=1)
        green_df_copy = green_df_copy[keep]
    green_df_copy = pst.renumerate_df(green_df_copy)

    # choose the dish contour ONCE and reuse it for calibration, lawn mask and overlay.
    # Enhanced path: pick the ROUNDEST large contour so a bigger-but-lumpy blob (the dark
    # surround / halo around the dish) can't hijack the mm calibration. Published mode keeps
    # the original "largest contour" rule so the validated algorithm is unchanged.
    dish_idx = None
    if not plate_df.empty:
        try:
            _ad = plate_df.apply(pst.calc_AREA_PXL_diff, axis=1)
            if pst.use_published:
                dish_idx = plate_df["ENCL_DIAMETER_PXL"].idxmax()
            else:
                cand = plate_df[_ad <= float(_ad.min()) + 0.05]
                dish_idx = cand["ENCL_DIAMETER_PXL"].idxmax()
        except Exception:
            dish_idx = plate_df["ENCL_DIAMETER_PXL"].idxmax()

    # pixel -> mm calibration (scales off the chosen dish diameter)
    pxl_per_mm = None
    if plate_size and dish_idx is not None:
        try:
            max_d = float(plate_df.loc[dish_idx, "ENCL_DIAMETER_PXL"])
            if max_d > 0:
                pxl_per_mm = float(plate_size) / max_d
        except Exception:
            pxl_per_mm = None

    plaques = []
    for _, row in green_df_copy.iterrows():
        m = cv2.moments(row["CONTOURS"])
        if m["m00"] != 0:
            cx, cy = m["m10"] / m["m00"], m["m01"] / m["m00"]
        else:
            cx, cy = row["ENCL_CENTER"]
        _p = {
            "source": row.get("SOURCE", "auto"),
            "kind": "contour",
            "contour": np.asarray(row["HULL"], dtype=np.int32),
            "area_pxl": float(row["AREA_PXL"]),
            "center": (float(cx), float(cy)),
            # QC inputs only (CT-R1 detection D5); no measured value depends on them
            "encl_diam_px": float(row["ENCL_DIAMETER_PXL"]),
        }
        try:
            _ha = float(row["AREA_PXL"])
            _p["solidity"] = (round(float(cv2.contourArea(np.asarray(row["CONTOURS"], dtype=np.int32))) / _ha, 4)
                              if _ha > 0 else None)
        except Exception:
            pass
        plaques.append(_p)

    # candidate contours for auto-trace: every non-plate shape the detector found
    # (including the ones it filtered out of the green set), so a click can snap to
    # a real boundary even when the plaque was rejected by the circularity/size filter.
    candidates = []
    cand_df = pd.concat([green_df, red_df, other_df], ignore_index=True)
    for _, row in cand_df.iterrows():
        area = float(row["AREA_PXL"])
        if area <= 0 or area >= 100000:
            continue
        m = cv2.moments(row["CONTOURS"])
        if m["m00"] != 0:
            cc = (m["m10"] / m["m00"], m["m01"] / m["m00"])
        else:
            cc = tuple(row["ENCL_CENTER"])
        candidates.append({"hull": np.asarray(row["HULL"], dtype=np.int32),
                           "area": area, "center": cc})

    # lawn reference for turbidity: median grey of the dish interior minus plaques
    orig_gray = cv2.cvtColor(orig, cv2.COLOR_BGR2GRAY)
    dish_mask = None
    plate = None
    if dish_idx is not None:
        plate_hull = np.asarray(plate_df.loc[dish_idx, "HULL"], dtype=np.int32)
        dish_mask = pst._mask_from_contour(orig_gray.shape, plate_hull)
        (pcx, pcy), prad = cv2.minEnclosingCircle(plate_hull)
        # ellipticity of the CHOSEN dish via cv2.fitEllipse (same method the CLI warning uses).
        # >1.03 => tilt/foreshortening biases the mm calibration (which scales off the dish).
        axis_ratio = None
        try:
            if len(plate_hull) >= 5:
                (_c, (_a1, _a2), _ang) = cv2.fitEllipse(plate_hull)
                lo, hi = min(_a1, _a2), max(_a1, _a2)
                axis_ratio = (hi / lo) if lo > 0 else None
        except Exception:
            axis_ratio = None
        plate = {"hull": plate_hull.reshape(-1, 2),
                 "center": (float(pcx), float(pcy)),
                 "radius": float(prad),
                 "diam_px": float(plate_df.loc[dish_idx, "ENCL_DIAMETER_PXL"]),
                 "axis_ratio": axis_ratio}
    auto_masks = [pst._mask_from_contour(orig_gray.shape, p["contour"]) for p in plaques]
    lawn_gray = pst.estimate_lawn_gray(orig_gray, dish_mask, auto_masks)

    display_rgb = cv2.cvtColor(orig, cv2.COLOR_BGR2RGB)
    return display_rgb, orig, high_contrast, plaques, pxl_per_mm, candidates, lawn_gray, plate


# --------------------------------------------------------------------------- #
#  Plaque-size scales for the app's Current / Sensitive engines (CT-R1 detection D1-D3)
# --------------------------------------------------------------------------- ## The scale merge and halo resolution live in plaque_scales (shared with the CLI's
# --multiscale, CT-R1 detection D10b); these names are re-exported for existing callers.
from plaque_scales import (  # noqa: E402,F401
    CONCENTRIC_PX, SPLIT_SOURCE, RELAXED_SOURCE, HALO_MIN_RATIO, _contour_center,
    _plaque_dicts, _inside, dedupe_by_containment, merge_scales, standard_mask, halo_ratio,
    source_counts, resolve_halos, _split_mask, roundest_dish_idx as _roundest_dish_idx,
    plate_from_row as _plate_from_row, drop_outside_dish, auto_plaques)


def _detect_pass(image, small, sensitive):
    """One pass of the validated detector at one block size (231, or 49 when ``small``), with
    the same de-duplication and mean-colour gate run_detection applies. Returns
    (green_df, red_df, other_df, plate_df, raw_green_df, high_contrast)."""
    pst.small_plaques = bool(small)
    pst.sensitive = bool(sensitive) and not pst.use_published
    pst.debug_mode = False
    binary_image, high_contrast, clr_high_contrast = pst.process_image(image, 2.5)
    contours = pst.get_contours(binary_image)
    image_size = binary_image.shape
    green_df, red_df, other_df, plate_df = pst.filter_contours(contours, image_size)
    raw_green = green_df
    if pst.watershed_enabled:
        rec = pst.recover_merged_plaques(image_size, green_df, red_df, other_df)
        green_df = green_df.copy()
        green_df["SOURCE"] = "auto"
        if not rec.empty:
            rec = rec.copy()
            rec["SOURCE"] = "watershed"
            green_df = pd.concat([green_df, rec], ignore_index=True)
    g = pst.check_duplicate_plaques(green_df.copy())
    if g.size > 0:
        mc = g.apply(lambda x: pst.get_mean_grey_colour(clr_high_contrast, x["CONTOURS"]), axis=1)
        g = g[mc.abs() >= 40]
    return g, red_df, other_df, plate_df, raw_green, high_contrast


def _run_scaled(image_path, plate_size, scale, sensitive, info):
    """run_detection for the app's Current / Sensitive engines with a plaque-size scale.

    * standard: one block-231 pass.
    * small:    one block-49 pass, concentric core/halo duplicates removed by containment.
    * auto:     both passes merged (merge_scales): large plaques keep their full standard
                outline (the block-49 pass outlines only the core of plaques wider than
                ~50 px, CT-R1 F1) and small plaques the standard gates miss are still found.
    The dish always comes from the STANDARD pass when it finds one (the block-49 threshold
    puts the rim on the outer halo, +4-5 % on 4 of 17 bundled plates, and misses it on
    Plate_2; CT-R1 F2), else from the small pass, else there is none and ``dish_reason``
    says why. Plaques whose centre lies outside the dish are dropped and counted
    (``n_outside_dish``, CT-R1 F18) unless the dish itself looks implausible."""
    prev = (pst.small_plaques, pst.sensitive)
    try:
        orig = pst.read_image_bgr(image_path)
        image = orig
        if float(cv2.cvtColor(orig, cv2.COLOR_BGR2GRAY).mean()) > 70:
            image = np.clip(orig.astype(np.float32) * 0.5, 0, 255).astype(np.uint8)
        # the standard pass runs in every scale: it gives the dish (and, outside Small, plaques)
        std = _detect_pass(image, False, sensitive)
        sml = _detect_pass(image, True, sensitive) if scale in ("auto", "small") else None
    finally:
        pst.small_plaques, pst.sensitive = prev

    std_g, std_r, std_o, std_plate, std_raw, std_hc = std
    std_pl = _plaque_dicts(std_g)
    if scale == "standard":
        plaques, proc, cand_dfs = std_pl, std_hc, [std_raw, std_r, std_o]
        n_added = 0
    else:
        sml_g, sml_r, sml_o, _sml_plate, sml_raw, sml_hc = sml
        sml_pl = _plaque_dicts(sml_g)
        if scale == "small":
            plaques, _nd = dedupe_by_containment(sml_pl)
            proc, cand_dfs, n_added = sml_hc, [sml_raw, sml_r, sml_o], 0
        else:
            proc, cand_dfs = std_hc, [std_raw, std_r, std_o, sml_raw, sml_r, sml_o]

    # dish: standard pass first, small pass as the fallback (CT-R1 F2)
    plate, dish_source, dish_reason = None, None, None
    idx = _roundest_dish_idx(std_plate)
    if idx is not None:
        plate, dish_source = _plate_from_row(std_plate, idx), "standard pass"
    elif sml is not None and _roundest_dish_idx(sml[3]) is not None:
        plate, dish_source = _plate_from_row(sml[3], _roundest_dish_idx(sml[3])), "small pass"
    else:
        dish_reason = ("no round contour larger than 100,000 px (the dish rim) was found; "
                       "sizes are in pixels unless you set the plate by hand")

    halo_counts = None
    if scale == "auto":
        # CT-R1 detection D8: one definition of the plaque edge per plate -- the standard
        # (block-231) threshold's halo edge wherever that mask holds the plaque
        # (plaque_scales.auto_plaques: the same code the CLI's --multiscale runs)
        plaques, halo_counts = auto_plaques(std_pl, sml_pl, std_hc, plate, orig)
        n_added = sum(p["source"] != "auto" for p in plaques)

    # CT-R1 F18 (D3): a detection whose centre lies outside the dish is not a plaque on this
    # lawn (glare on the wall, the label, the bench); see plaque_scales.drop_outside_dish
    plaques, n_outside = drop_outside_dish(plaques, plate, orig.shape)

    pxl_per_mm = None
    if plate_size and plate is not None and plate["diam_px"] > 0:
        try:
            pxl_per_mm = float(plate_size) / float(plate["diam_px"])
        except (TypeError, ValueError):
            pxl_per_mm = None

    candidates = []
    for row_df in cand_dfs:
        for _, row in row_df.iterrows():
            area = float(row["AREA_PXL"])
            if area <= 0 or area >= 100000:
                continue
            candidates.append({"hull": np.asarray(row["HULL"], dtype=np.int32), "area": area,
                               "center": _contour_center(row["CONTOURS"], row["ENCL_CENTER"])})

    orig_gray = cv2.cvtColor(orig, cv2.COLOR_BGR2GRAY)
    dish_mask = pst._mask_from_contour(orig_gray.shape, plate["hull"]) if plate is not None else None
    auto_masks = [pst._mask_from_contour(orig_gray.shape, p["contour"]) for p in plaques]
    lawn_gray = pst.estimate_lawn_gray(orig_gray, dish_mask, auto_masks)

    if info is not None:
        info.update({"scale": scale, "dish_source": dish_source, "dish_reason": dish_reason,
                     "n_outside_dish": n_outside, "n_small_added": n_added, "dish_warnings": [],
                     "sources": source_counts(plaques) if scale == "auto" else None,
                     "halo_resolution": halo_counts})
    return (cv2.cvtColor(orig, cv2.COLOR_BGR2RGB), orig, proc, plaques, pxl_per_mm,
            candidates, lawn_gray, plate)


def detect_region(orig_bgr, roi, sensitive=True, small=True):
    """Re-run the validated plaque detector inside a rectangular ROI of an already-loaded
    image. Returns plaque dicts (kind='contour', source='region') in FULL-image pixel
    coordinates. Calibration/dish are NOT recomputed — the caller keeps the plate-level
    mm/px. Used by the editor's 'Detect area' tool to recover plaques the global pass
    missed (it runs sensitive on the crop, so faint blobs inside the box surface).

    roi = (x, y, w, h) in image pixels. Sets the same process-global flags run_detection
    uses and restores them; the engine_api wrapper holds the lock + restores use_published."""
    x0, y0, w, h = (int(round(v)) for v in roi)
    H, W = orig_bgr.shape[:2]
    x0 = max(0, x0); y0 = max(0, y0)
    x1 = min(W, x0 + max(w, 0)); y1 = min(H, y0 + max(h, 0))
    if x1 - x0 < 4 or y1 - y0 < 4:
        return []
    crop = orig_bgr[y0:y1, x0:x1]

    # mirror run_detection's in-memory dimming so the thresholds behave the same
    image = crop
    if float(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).mean()) > 70:
        image = np.clip(crop.astype(np.float32) * 0.5, 0, 255).astype(np.uint8)

    prev = (pst.small_plaques, pst.sensitive, pst.watershed_enabled)
    pst.small_plaques = bool(small)
    pst.sensitive = bool(sensitive) and not pst.use_published
    pst.watershed_enabled = False
    pst.debug_mode = False
    try:
        binary_image, _high, clr_high_contrast = pst.process_image(image, 2.5)
        contours = pst.get_contours(binary_image)
        green_df, _red, _other, _plate = pst.filter_contours(contours, binary_image.shape)
    finally:
        pst.small_plaques, pst.sensitive, pst.watershed_enabled = prev

    if green_df is None or green_df.empty:
        return []
    # mean-colour gate like run_detection (drop near-lawn-grey blobs)
    try:
        mc = green_df.apply(
            lambda r: pst.get_mean_grey_colour(clr_high_contrast, r["CONTOURS"]), axis=1)
        green_df = green_df[mc.abs() >= 40]
    except Exception:
        pass

    region_area = float((x1 - x0) * (y1 - y0))
    off = np.array([x0, y0], dtype=np.int32)
    out = []
    for _, row in green_df.iterrows():
        area = float(row["AREA_PXL"])
        if area <= 0 or area >= 0.5 * region_area:     # skip junk / the whole-box blob
            continue
        hull = np.asarray(row["HULL"], dtype=np.int32).reshape(-1, 2) + off
        m = cv2.moments(hull)
        if m["m00"] != 0:
            cx, cy = m["m10"] / m["m00"], m["m01"] / m["m00"]
        else:
            ec = row.get("ENCL_CENTER", (0, 0))
            cx, cy = float(ec[0]) + x0, float(ec[1]) + y0
        out.append({"source": "region", "kind": "contour",
                    "contour": hull.astype(np.int32), "area_pxl": area,
                    "center": (float(cx), float(cy))})
    return out


# --------------------------------------------------------------------------- #
#  Measurement + manual segmentation helpers
# --------------------------------------------------------------------------- #
def measure(area_pxl, pxl_per_mm, published=None):
    """Area-equivalent diameter (px), area (mm^2), diameter (mm) -- as the tool does.

    `published` (None = follow pst.use_published) selects the Published engine's sizing,
    which derives DIAMETER_MM from AREA_MM2 *rounded to 2 dp* (upstream stored it as a
    2-dp string). The app and this editor used the un-rounded area for every engine, so
    their "Published" DIAMETER_MM differed from the CLI's by 0.01 mm on ~3 % of plaques
    (AUDIT-2026-10.md, PT-30). Current/Sensitive sizing is unchanged.
    """
    if published is None:
        published = bool(pst.use_published)
    dia_pxl = 2.0 * np.sqrt(area_pxl / np.pi)
    if pxl_per_mm:
        area_mm2 = area_pxl * pxl_per_mm * pxl_per_mm
        if published:
            dia_mm = 2.0 * np.sqrt(round(area_mm2, 2) / np.pi)
        else:
            dia_mm = 2.0 * np.sqrt(area_mm2 / np.pi)
    else:
        area_mm2, dia_mm = 0.0, 0.0
    return dia_pxl, area_mm2, dia_mm


def trace_by_contour(candidates, x, y):
    """Snap to the smallest detector contour that contains (x, y). None if no hit."""
    best, best_area = None, None
    for c in candidates:
        if cv2.pointPolygonTest(c["hull"], (float(x), float(y)), False) >= 0:
            if best_area is None or c["area"] < best_area:
                best, best_area = c, c["area"]
    if best is None:
        return None
    return best["hull"], best["area"], best["center"]


def trace_at(candidates, gray, x, y, tol=20):
    """Auto-trace at (x, y): prefer a detector contour, fall back to a flood-fill whose
    sensitivity is `tol` (higher grabs fainter/larger boundaries)."""
    res = trace_by_contour(candidates, x, y)
    return res if res is not None else autotrace(gray, x, y, tol=tol)


def autotrace(gray, x, y, tol=20, max_area=100000):
    """Bounded flood-fill fallback around (x, y); return (hull, area, center) or None."""
    h, w = gray.shape[:2]
    xi, yi = int(round(x)), int(round(y))
    if not (0 <= xi < w and 0 <= yi < h):
        return None

    mask = np.zeros((h + 2, w + 2), np.uint8)
    flags = 4 | (255 << 8) | cv2.FLOODFILL_MASK_ONLY | cv2.FLOODFILL_FIXED_RANGE
    cv2.floodFill(gray.copy(), mask, (xi, yi), 0, tol, tol, flags)
    region = mask[1:-1, 1:-1]
    region = cv2.morphologyEx(region, cv2.MORPH_CLOSE,
                              cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))

    filled = int(region.sum() // 255)
    if filled < 10 or filled > 0.2 * h * w:   # too tiny or bled into the whole plate
        return None

    cnts = imutils.grab_contours(
        cv2.findContours(region, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE))
    chosen = None
    for c in cnts:
        if cv2.pointPolygonTest(c, (xi, yi), False) >= 0:
            chosen = c
            break
    if chosen is None and cnts:
        chosen = max(cnts, key=cv2.contourArea)
    if chosen is None:
        return None

    hull = cv2.convexHull(chosen)
    area = cv2.contourArea(hull)
    if area <= 0 or area > min(max_area, 0.2 * h * w):   # not a plausible single plaque
        return None
    m = cv2.moments(hull)
    if m["m00"] != 0:
        center = (m["m10"] / m["m00"], m["m01"] / m["m00"])
    else:
        center = (float(x), float(y))
    return hull.astype(np.int32), float(area), center


# --------------------------------------------------------------------------- #
#  Save (overwrites the standard plaque_size_tool outputs)
# --------------------------------------------------------------------------- #
def _plaque_mask(shape, p):
    mask = np.zeros(shape[:2], dtype="uint8")
    if p["kind"] == "circle":
        cv2.circle(mask, (int(round(p["center"][0])), int(round(p["center"][1]))),
                   max(int(round(p["radius"])), 1), 255, -1)
    else:
        cv2.drawContours(mask, [np.asarray(p["contour"], dtype=np.int32)], -1, 255, -1)
    return mask


# --------------------------------------------------------------------------- #
#  The plate figure: ONE style for the on-screen canvas and every exported image
# --------------------------------------------------------------------------- #
# CT-R1 F9/F12: the canvas drew five colours, the export two (and a different blue), so the
# file did not look like the screen and nothing explained the colours. This map is the only
# place a plaque class gets its name, colour and line style: app/plaque_canvas.py draws the
# canvas from it, annotate_plaques() draws every exported image from it (Save results,
# Export all, side-by-side, Batch overlays) and plate_key() builds the legend key from it.
#   class key -> (plain name, RGB exactly as drawn, "solid" | "dashed")
PLAQUE_CLASSES = {
    "auto":      ("auto-detected",   (40, 220, 70),   "solid"),
    # (30, 144, 255), not the canvas's old (30, 170, 255): the legend text names that "cyan"
    "manual":    ("added by hand",   (30, 144, 255),  "solid"),
    "region":    ("detect-area",     (255, 170, 0),   "solid"),
    "watershed": ("watershed split", (180, 120, 255), "solid"),
    "overlap":   ("overlapping",     (255, 40, 150),  "dashed"),
}
CLASS_ORDER = ("auto", "manual", "region", "watershed", "overlap")
# a plaque's SOURCE -> its class (a freehand outline is "added by hand" like a circle or trace)
# "small" = found only by the small-scale pass of the Auto plaque size (CT-R1 detection D1):
# a detector result like "auto", drawn and keyed as such; only the SOURCE column tells them apart
_SOURCE_CLASS = {"auto": "auto", "small": "auto", "split": "auto", "standard-relaxed": "auto",
                 "manual": "manual", "freehand": "manual",
                 "region": "region", "watershed": "watershed"}
# CT-R1 detection D8: "split" / "standard-relaxed" are Auto's halo outlines -- detector results
DETECTOR_SOURCES = ("auto", "small", "split", "standard-relaxed")
LABEL_MODES = ("numbers", "numbers + mm", "none")
# where a label is tried, in this order: right, left, above, below, then the four diagonals
LABEL_SIDES = ("E", "W", "N", "S", "NE", "SE", "NW", "SW")
_SIDE_DIR = {"E": (1, 0), "W": (-1, 0), "N": (0, -1), "S": (0, 1),
             "NE": (1, -1), "SE": (1, 1), "NW": (-1, -1), "SW": (-1, 1)}


def class_name(key, precise=False):
    """Plain name of a plaque class. Under Precise the orange class is not the Detect-area
    tool: it marks plaques only the classic detector found (PlaqSeg did not confirm them)."""
    if precise and key == "region":
        return "classic detector only"
    return PLAQUE_CLASSES[key][0]


def overlap_flags(plaques, margin=1.0):
    """True where a plaque's area-equivalent disk overlaps/touches another's (centre distance
    < (r_i + r_j) * margin). Uniform for circles and contours, O(n^2) over the (few) plaques."""
    import math
    g = []
    for p in plaques:
        if p.get("kind") == "circle" and p.get("radius"):
            r = float(p["radius"])
        else:
            r = math.sqrt(max(float(p.get("area_pxl", 0.0)), 1.0) / math.pi)
        g.append((float(p["center"][0]), float(p["center"][1]), r))
    n = len(g)
    flags = [False] * n
    for i in range(n):
        xi, yi, ri = g[i]
        for j in range(i + 1, n):
            xj, yj, rj = g[j]
            if math.hypot(xi - xj, yi - yj) < (ri + rj) * margin:
                flags[i] = True
                flags[j] = True
    return flags


def plaque_class(p, overlap=False):
    """Class key of one plaque: 'overlap' wins over its source, as on the canvas."""
    if overlap:
        return "overlap"
    return _SOURCE_CLASS.get(p.get("source") or "auto", "auto")


def plaque_classes(plaques):
    """Class key per plaque. The overlap test is recomputed here rather than read from a tag,
    so Batch and CLI callers (whose plaques carry no tag) get the same picture as the app."""
    return [plaque_class(p, ov) for p, ov in zip(plaques, overlap_flags(plaques))]


def figure_metrics(image_shape):
    """Label and line sizes that scale with the image width, so a figure reads the same on a
    1,200 px and a 4,000 px photo (the old labels were a fixed 0.5-scale, 1 px Hershey font:
    specks on a 2,811 px plate)."""
    w = float(max(int(image_shape[1]), 1))
    font_px = max(12, int(round(w / 80.0)))
    return {"font_px": font_px,
            "stroke": max(2, int(round(font_px / 8.0))),      # dark outline round each glyph
            "line": max(2, int(round(w / 650.0))),            # plaque outline width
            "gap": max(2, int(round(font_px / 5.0)))}         # label <-> outline distance


def label_text(index, area_pxl, pxl_per_mm, mode="numbers", published=None):
    """The text beside plaque #index for a label mode ('numbers', 'numbers + mm', 'none').
    `published` must be the flag of the engine that made the result, so the diameter printed
    on the figure is the diameter in the table."""
    if mode == "none":
        return ""
    if mode != "numbers + mm":
        return str(index)
    dia_pxl, _area_mm2, dia_mm = measure(area_pxl, pxl_per_mm, published)
    if pxl_per_mm:
        return "%d: %.2f mm" % (index, dia_mm)
    return "%d: %.0f px" % (index, dia_pxl)


def plaque_bbox(p):
    """(x0, y0, x1, y1) of a plaque's outline in image pixels."""
    if p["kind"] == "circle":
        r = float(p.get("radius") or np.sqrt(max(p["area_pxl"], 1) / np.pi))
        cx, cy = float(p["center"][0]), float(p["center"][1])
        return (cx - r, cy - r, cx + r, cy + r)
    pts = np.asarray(p["contour"], dtype=float).reshape(-1, 2)
    return (float(pts[:, 0].min()), float(pts[:, 1].min()),
            float(pts[:, 0].max()), float(pts[:, 1].max()))


def label_anchor(bbox, side):
    """(x, y, dx, dy): the point on a plaque's outline a label hangs from, and the direction
    the label extends from it (dx: -1 left, 0 centred, 1 right; dy: -1 above, 0, 1 below)."""
    dx, dy = _SIDE_DIR[side]
    x0, y0, x1, y1 = bbox
    k = 0.7071 if (dx and dy) else 1.0          # a diagonal hangs off the outline at 45 degrees
    return ((x0 + x1) / 2.0 + dx * k * (x1 - x0) / 2.0,
            (y0 + y1) / 2.0 + dy * k * (y1 - y0) / 2.0, dx, dy)


def label_rect(bbox, size, side, gap):
    """Rectangle (x0, y0, x1, y1) of a label of `size` (w, h) placed just outside `bbox` on
    `side` (see LABEL_SIDES), `gap` pixels off the outline."""
    ax, ay, dx, dy = label_anchor(bbox, side)
    w, h = size
    x = ax + dx * gap - (w if dx < 0 else (w / 2.0 if dx == 0 else 0.0))
    y = ay + dy * gap - (h if dy < 0 else (h / 2.0 if dy == 0 else 0.0))
    return (x, y, x + w, y + h)


def layout_labels(plaques, sizes, image_shape, gap, avoid=()):
    """Choose a side for every label: the first of right / left / above / below (then the four
    diagonals) that covers no other plaque, no label already placed, nothing in `avoid` (the
    scale bar, the legend key) and stays inside the image; when none is clean, the one that
    covers least -- a label on top of another label counts far worse than one grazing a
    plaque. Returns [(side, rect)] in plaque order. Shared by the canvas (which uses the
    side) and the export, so a label sits on the same side of its plaque in both."""
    n = len(plaques)
    if n == 0:
        return []
    H, W = float(image_shape[0]), float(image_shape[1])
    boxes = np.array([plaque_bbox(p) for p in plaques], dtype=float).reshape(n, 4)
    fixed = np.array([tuple(r) for r in avoid if r is not None], dtype=float).reshape(-1, 4)
    # obstacles: the plaques themselves, shrunk a little (a bounding box overstates a round
    # outline at its corners, and a label may graze those)
    bw = (boxes[:, 2] - boxes[:, 0]) * 0.12
    bh = (boxes[:, 3] - boxes[:, 1]) * 0.12
    obst = np.column_stack([boxes[:, 0] + bw, boxes[:, 1] + bh, boxes[:, 2] - bw, boxes[:, 3] - bh])

    def covered(rect, others):
        if len(others) == 0:
            return 0.0
        ix = np.minimum(rect[2], others[:, 2]) - np.maximum(rect[0], others[:, 0])
        iy = np.minimum(rect[3], others[:, 3]) - np.maximum(rect[1], others[:, 1])
        return float((np.clip(ix, 0, None) * np.clip(iy, 0, None)).sum())

    placed = np.zeros((0, 4), dtype=float)
    out = []
    keep = np.ones(n, dtype=bool)
    for i in range(n):
        keep[:] = True
        keep[i] = False
        best = None
        for side in LABEL_SIDES:
            r = label_rect(tuple(boxes[i]), sizes[i], side, gap)
            area = max((r[2] - r[0]) * (r[3] - r[1]), 1e-9)
            inside = (max(0.0, min(r[2], W) - max(r[0], 0.0))
                      * max(0.0, min(r[3], H) - max(r[1], 0.0)))
            cost = (covered(r, obst[keep]) + 8.0 * covered(r, placed) + 8.0 * covered(r, fixed)
                    + 8.0 * (area - inside))
            if cost <= 1e-6:
                best = (0.0, side, r)
                break
            if best is None or cost < best[0]:
                best = (cost, side, r)
        out.append((best[1], best[2]))
        # a placed label keeps a small margin, so the next one does not butt against it
        b = best[2]
        placed = np.vstack([placed, np.array([b[0] - gap, b[1] - gap / 2.0, b[2] + gap, b[3] + gap / 2.0])])
    return out


# ---- text: DejaVu Sans (the font matplotlib draws the legend key in), white with a dark outline
_FONTS = {}


def figure_font_path(bold=True):
    """Path of DejaVu Sans as bundled with matplotlib, or None. The plaque numbers, the
    scale-bar label and the legend key are then all in one font. Found without importing
    matplotlib, so drawing an overlay never loads it (Batch draws on a worker thread)."""
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    cands = []
    try:
        import importlib.util
        spec = importlib.util.find_spec("matplotlib")
        if spec is not None and spec.origin:
            cands.append(os.path.join(os.path.dirname(spec.origin), "mpl-data", "fonts", "ttf", name))
    except Exception:                               # noqa: BLE001
        pass
    import sys
    base = getattr(sys, "_MEIPASS", None)           # frozen app
    if base:
        cands.append(os.path.join(base, "matplotlib", "mpl-data", "fonts", "ttf", name))
    for c in cands:
        if os.path.exists(c):
            return c
    return None


def _font(px, bold=True):
    k = (int(px), bool(bold))
    if k not in _FONTS:
        f = None
        try:
            from PIL import ImageFont
            path = figure_font_path(bold)
            if path:
                f = ImageFont.truetype(path, int(px))
        except Exception:                           # noqa: BLE001 -- fall back to OpenCV text
            f = None
        _FONTS[k] = f
    return _FONTS[k]


def text_size(text, font_px, stroke=0):
    """(w, h) in pixels of `text` as _draw_texts will draw it (ink box, outline included)."""
    f = _font(font_px)
    if f is not None:
        l, t, r, b = f.getbbox(text, stroke_width=int(stroke))
        return (r - l, b - t)
    scale = font_px / 30.0
    (tw, th), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, max(1, int(round(scale * 2))))
    return (tw + 2 * int(stroke), th + base + 2 * int(stroke))


def _draw_texts(img_bgr, items):
    """Draw outlined text items in place. item = (text, x, y, font_px, fill_rgb, stroke) with
    (x, y) the top-left of the ink box. One PIL round-trip for all of them."""
    items = [it for it in items if it[0]]
    if not items:
        return img_bgr
    if all(_font(it[3]) is not None for it in items):
        from PIL import ImageDraw
        im = Image.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))
        d = ImageDraw.Draw(im)
        for text, x, y, font_px, fill, stroke in items:
            f = _font(font_px)
            l, t, _r, _b = f.getbbox(text, stroke_width=int(stroke))
            d.text((int(round(x - l)), int(round(y - t))), text, font=f,
                   fill=tuple(int(v) for v in fill), stroke_width=int(stroke), stroke_fill=(0, 0, 0))
        img_bgr[:] = cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)
        return img_bgr
    for text, x, y, font_px, fill, stroke in items:            # no TrueType font: OpenCV text
        scale = font_px / 30.0
        thick = max(1, int(round(scale * 2)))
        (_tw, th), _base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thick)
        org = (int(round(x + stroke)), int(round(y + stroke + th)))
        cv2.putText(img_bgr, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0),
                    thick + 2 * int(stroke), cv2.LINE_AA)
        cv2.putText(img_bgr, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale,
                    tuple(int(v) for v in fill[::-1]), thick, cv2.LINE_AA)
    return img_bgr


def _outline_points(p):
    """Closed outline of a plaque as an (N, 2) float array."""
    if p["kind"] == "circle":
        r = max(float(p.get("radius") or np.sqrt(max(p["area_pxl"], 1) / np.pi)), 1.0)
        n = int(max(48, min(720, 2 * np.pi * r / 3.0)))
        a = np.linspace(0.0, 2 * np.pi, n, endpoint=False)
        return np.column_stack([p["center"][0] + r * np.cos(a), p["center"][1] + r * np.sin(a)])
    return np.asarray(p["contour"], dtype=float).reshape(-1, 2)


def _draw_dashed(img, pts, bgr, thick, dotted=False):
    """Closed dashed polyline: evenly spaced dashes (an integer number round the outline).
    ``dotted`` draws short dots instead of dashes (the "size not used" class, CT-R2 N3)."""
    closed = np.vstack([pts, pts[:1]])
    seg = np.hypot(np.diff(closed[:, 0]), np.diff(closed[:, 1]))
    per = float(seg.sum())
    if per <= 0:
        return
    s = np.concatenate([[0.0], np.cumsum(seg)])
    period = (3.0 if dotted else 8.0) * thick
    n_dash = max(6 if dotted else 4, int(round(per / period)))
    period = per / n_dash
    dash = (0.2 if dotted else 0.58) * period
    lines = []
    for k in range(n_dash):
        t = np.linspace(k * period, k * period + dash, max(2, int(dash) + 1))
        x = np.interp(t, s, closed[:, 0])
        y = np.interp(t, s, closed[:, 1])
        lines.append(np.round(np.column_stack([x, y])).astype(np.int32).reshape(-1, 1, 2))
    cv2.polylines(img, lines, False, bgr, int(thick), cv2.LINE_AA)


def draw_outline(img, p, rgb, style, thick):
    """Draw one outline (plaque dict) in ``rgb`` with ``style`` 'solid' | 'dashed' | 'dotted'.
    The ONE outline drawing of every exported figure: plate figures and the turbidity QC
    overlays (CT-R2 N8)."""
    bgr = (int(rgb[2]), int(rgb[1]), int(rgb[0]))
    if style in ("dashed", "dotted"):
        _draw_dashed(img, _outline_points(p), bgr, thick, dotted=(style == "dotted"))
    elif p["kind"] == "circle":
        cv2.circle(img, (int(round(p["center"][0])), int(round(p["center"][1]))),
                   max(int(round(p["radius"])), 1), bgr, int(thick), cv2.LINE_AA)
    else:
        cv2.drawContours(img, [np.asarray(p["contour"], dtype=np.int32)], -1, bgr, int(thick), cv2.LINE_AA)


def _draw_outline(img, p, cls, thick):
    _name, rgb, style = PLAQUE_CLASSES[cls]
    draw_outline(img, p, rgb, style, thick)


# ---- legend key (the standing figure rule): built by plaque_stats/legend_key.py ------------
_KEY_LINESTYLE = {"solid": "-", "dashed": "--", "dotted": ":"}


def outline_key(spec, title="Plaque outlines"):
    """A legend key of outline classes: ``spec`` = [(plain name, RGB as drawn, line style)].
    The ONE builder behind the plate figure's key (plate_key) and the turbidity QC overlay's
    key (CT-R2 N8), so every outline figure is keyed the same way. None for an empty spec."""
    if not spec:
        return None
    from plaque_stats import legend_key
    entries = [legend_key.entry(name, "#%02X%02X%02X" % tuple(rgb), kind="line",
                                linestyle=_KEY_LINESTYLE.get(style, "-"), linewidth=2.0)
               for name, rgb, style in spec]
    return legend_key.make_key(entries, title=title, fontsize=9.0, frameon=True)


def plate_key(plaques, precise=False):
    """The legend key of a plate figure: one entry per plaque class PRESENT on this plate,
    with the colour and line style it is drawn in and a plain name. Returns a legend_key key
    dict (None when there are no plaques). Read from the current plaques every time."""
    if not plaques:
        return None
    present = set(plaque_classes(plaques))
    spec = []
    for k in CLASS_ORDER:
        if k in present:
            _n, rgb, style = PLAQUE_CLASSES[k]
            spec.append((class_name(k, precise), rgb, style))
    return outline_key(spec)


def write_key_files_for(key, figure_path):
    """The stand-alone key + legend text beside a figure, in the figure's own format (plus
    PNG, which every viewer opens). Returns the paths written ([] for no key)."""
    if not key or not key.get("entries"):
        return []
    from plaque_stats import legend_key
    ext = os.path.splitext(figure_path)[1].lower().lstrip(".") or "png"
    if ext in ("heic", "heif"):
        ext = "png"
    formats = [ext] + ([] if ext == "png" else ["png"])
    return legend_key.write_key_files(key, os.path.splitext(figure_path)[0], formats=formats)


def key_text(plaques, precise=False):
    """Legend text starter for a plate figure, e.g. 'auto-detected (green, solid line); ...'."""
    key = plate_key(plaques, precise)
    if not key:
        return ""
    from plaque_stats import legend_key
    return legend_key.text_starter(key)


def key_image(key, font_px):
    """The stand-alone key (legend_key.key_figure -- the same drawing `save_key` writes)
    rendered to a BGR array, at a resolution where its text is `font_px` pixels high. The
    key placed on a figure is this picture, so it cannot differ from the stand-alone file."""
    import io
    import matplotlib
    from plaque_stats import legend_key
    with matplotlib.rc_context(legend_key.VECTOR_RC):
        fig = legend_key.key_figure(key)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=72.0 * float(font_px) / float(key["fontsize"]),
                    bbox_inches="tight", pad_inches=0.05, facecolor="white")
    return cv2.imdecode(np.frombuffer(buf.getvalue(), np.uint8), cv2.IMREAD_COLOR)


def key_origin(image_shape, key_shape):
    """Top-left pixel of the embedded key: the image's top-right corner (outside a round dish)."""
    H, W = int(image_shape[0]), int(image_shape[1])
    pad = max(6, int(round(0.015 * W)))
    return (max(0, W - pad - int(key_shape[1])), min(pad, max(0, H - int(key_shape[0]))))


def key_image_for(image_shape, key):
    """The key picture at the size it has ON a figure of `image_shape` (text as high as the
    plaque labels), or None when there is nothing to key. The canvas shows this same array."""
    if not key or not key.get("entries"):
        return None
    patch = key_image(key, figure_metrics(image_shape)["font_px"])
    if patch is None:
        return None
    H, W = int(image_shape[0]), int(image_shape[1])
    if patch.shape[1] > 0.6 * W or patch.shape[0] > 0.6 * H:      # tiny image: shrink to fit
        f = min(0.6 * W / patch.shape[1], 0.6 * H / patch.shape[0])
        patch = cv2.resize(patch, (max(1, int(patch.shape[1] * f)), max(1, int(patch.shape[0] * f))),
                           interpolation=cv2.INTER_AREA)
    cv2.rectangle(patch, (0, 0), (patch.shape[1] - 1, patch.shape[0] - 1), (60, 60, 60), 1)
    return patch


def _paste_key(img_bgr, patch):
    x, y = key_origin(img_bgr.shape, patch.shape)
    img_bgr[y:y + patch.shape[0], x:x + patch.shape[1]] = patch
    return (x, y, patch.shape[1], patch.shape[0])


def place_key(img_bgr, key):
    """Paste the key onto the figure (in place). Returns the rectangle used, or None."""
    patch = key_image_for(img_bgr.shape, key)
    if patch is None:
        return None
    return _paste_key(img_bgr, patch)


def scalebar_rect(g):
    """The rectangle a scale bar and its label occupy (from scalebar.bar_geometry), so plaque
    labels can keep clear of it."""
    top = (g["y0"] - g["gap"] - 1.5 * g["label_h"]) if g["label_above"] else g["y0"]
    bot = (g["y0"] + g["thickness"]) if g["label_above"] else (g["y0"] + g["thickness"] + g["gap"] + 1.5 * g["label_h"])
    half = max(g["length_px"], 1.3 * g["label_w"]) / 2.0
    return (g["label_cx"] - half - g["outline"], top, g["label_cx"] + half + g["outline"], bot + g["outline"])


def scalebar_label_font(g, metrics):
    """(font px, outline px) of the scale-bar label when drawn in the figure's own font."""
    px = max(metrics["font_px"], int(round(g["label_h"] / 0.73)))
    return px, max(2, int(round(px / 8.0)))


def annotate_plaques(orig_bgr, plaques, pxl_per_mm, draw_numbers=True, scalebar=True, plate=None,
                     scalebar_mm=None, scalebar_anchor=None, scalebar_color=(255, 255, 255),
                     labels="numbers", key=False, published=None, precise=False):
    """Draw the plate figure onto a copy of the image and return it (BGR): plaque outlines in
    their class colours (PLAQUE_CLASSES: the canvas's own), a label beside each plaque (white
    with a dark outline, sized to the image, just outside the outline, on the first free of
    four sides) and a physical scale bar. The ONE drawing function behind Save results,
    Export all, the side-by-side figure and the Batch overlays (CT-R1 F9).

    ``labels``  'numbers' (default), 'numbers + mm' or 'none'; ``draw_numbers=False`` = 'none'.
    ``key``     True also places the legend key (plate_key) in the top-right corner.
    ``scalebar_mm`` forces the bar length (mm); ``scalebar_anchor`` (x, y in image px) its
    left end. With neither, and ``plate`` known, the bar is auto-sized and placed INSIDE the
    dish (an image corner would fall in the dark surround)."""
    annotated = orig_bgr.copy()
    if annotated.ndim == 2:
        annotated = cv2.cvtColor(annotated, cv2.COLOR_GRAY2BGR)
    m = figure_metrics(annotated.shape)
    for p, cls in zip(plaques, plaque_classes(plaques)):
        _draw_outline(annotated, p, cls, m["line"])

    texts = []
    avoid = []                    # what a plaque label must not cover: the scale bar, the key
    # Physical scale bar (e.g. "5 mm"). pxl_per_mm is actually mm/px, so pass it straight.
    if scalebar and draw_scalebar and draw_scale_bar is not None:
        try:
            import scalebar as _sb
            g = _sb.bar_geometry(annotated.shape, pxl_per_mm, anchor=scalebar_anchor,
                                 length_mm=scalebar_mm, plate=plate)
            own_font = g is not None and _font(m["font_px"]) is not None
            draw_scale_bar(annotated, pxl_per_mm, anchor=scalebar_anchor, length_mm=scalebar_mm,
                           color=scalebar_color, plate=plate, draw_label=not own_font)
            if g is not None:
                avoid.append(scalebar_rect(g))
            if own_font:                                # the label in the figure's own font
                px, stroke = scalebar_label_font(g, m)
                tw, th = text_size(g["label"], px, stroke)
                tx = max(2.0, min(g["label_cx"] - tw / 2.0, annotated.shape[1] - tw - 2.0))
                ty = (g["y0"] - g["gap"] - th) if g["label_above"] else (g["y0"] + g["thickness"] + g["gap"])
                texts.append((g["label"], tx, max(1.0, ty), px,
                              tuple(int(v) for v in scalebar_color[::-1]), stroke))
        except Exception:
            pass          # never let the overlay break a save
    key_patch = None
    if key:
        try:
            key_patch = key_image_for(annotated.shape, plate_key(plaques, precise))
            if key_patch is not None:
                kx, ky = key_origin(annotated.shape, key_patch.shape)
                avoid.append((kx, ky, kx + key_patch.shape[1], ky + key_patch.shape[0]))
        except Exception:
            key_patch = None

    mode = labels if (draw_numbers and labels in LABEL_MODES) else ("numbers" if draw_numbers else "none")
    if mode != "none" and plaques:
        strs = [label_text(i, p["area_pxl"], pxl_per_mm, mode, published)
                for i, p in enumerate(plaques, start=1)]
        sizes = [text_size(s, m["font_px"], m["stroke"]) for s in strs]
        placed = layout_labels(plaques, sizes, annotated.shape, m["gap"], avoid=avoid)
        for s, (_side, rect) in zip(strs, placed):
            texts.append((s, rect[0], rect[1], m["font_px"], (255, 255, 255), m["stroke"]))
    try:
        _draw_texts(annotated, texts)
    except Exception:
        pass
    if key_patch is not None:
        _paste_key(annotated, key_patch)
    return annotated


RASTER_EXTS = (".png", ".jpg", ".jpeg", ".tif", ".tiff")
VECTOR_EXTS = (".pdf", ".svg")


def write_figure(img_bgr, out_path):
    """Write a figure image and return the path ACTUALLY written. .png/.jpg/.tif go through
    OpenCV; .pdf/.svg through matplotlib (the picture embedded at full resolution); any other
    extension (HEIC, none, a typo) is saved as .png -- compare the result with what you asked
    for to tell the user. A failed write raises (CT-R1 F22: a .pdf name used to raise an
    uncaught cv2.error after the dialog closed, with nothing saved and nothing said)."""
    root, ext = os.path.splitext(out_path)
    ext = ext.lower()
    if ext not in RASTER_EXTS + VECTOR_EXTS:
        out_path = (root if ext in (".heic", ".heif", "") else out_path) + ".png"
        ext = ".png"
    d = os.path.dirname(os.path.abspath(out_path))
    if d:
        os.makedirs(d, exist_ok=True)
    if ext in VECTOR_EXTS:
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        h, w = img_bgr.shape[:2]
        dpi = 300.0
        fig = Figure(figsize=(w / dpi, h / dpi), dpi=dpi)
        FigureCanvasAgg(fig)
        ax = fig.add_axes([0, 0, 1, 1])
        ax.axis("off")
        ax.imshow(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB), interpolation="none")
        fig.savefig(out_path, dpi=dpi)
    else:
        pst.imwrite_checked(out_path, img_bgr)
    if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        raise IOError("could not write %s" % out_path)
    return out_path


def save_figure(plaques, orig_bgr, out_path, pxl_per_mm, draw_numbers=True, scalebar=True,
                plate=None, scalebar_mm=None, scalebar_anchor=None, scalebar_color=(255, 255, 255),
                labels="numbers", key=False, published=None, precise=False):
    """Render the annotated overlay (outlines + labels + scale bar, optionally the legend key)
    and write it to out_path as a stand-alone figure. Returns the path actually written
    (see write_figure: unknown extension / HEIC -> PNG)."""
    annotated = annotate_plaques(orig_bgr, plaques, pxl_per_mm,
                                 draw_numbers=draw_numbers, scalebar=scalebar, plate=plate,
                                 scalebar_mm=scalebar_mm, scalebar_anchor=scalebar_anchor,
                                 scalebar_color=scalebar_color, labels=labels, key=key,
                                 published=published, precise=precise)
    return write_figure(annotated, out_path)


def save_comparison(plaques, orig_bgr, out_path, pxl_per_mm, plate=None, scalebar_mm=None,
                    scalebar_anchor=None, labels=("Input", "Detected"), scalebar_color=(255, 255, 255),
                    plaque_labels="numbers", key=False, published=None, precise=False):
    """Write a side-by-side 'input vs annotated output' figure: the original plate on the left,
    the annotated detection (the same drawing as save_figure) on the right, under a labelled
    banner. Returns the path actually written."""
    left = orig_bgr.copy()
    right = annotate_plaques(orig_bgr, plaques, pxl_per_mm, plate=plate,
                             scalebar_mm=scalebar_mm, scalebar_anchor=scalebar_anchor,
                             scalebar_color=scalebar_color, labels=plaque_labels, key=key,
                             published=published, precise=precise)
    h, w = left.shape[:2]
    gap = max(8, int(round(0.01 * w)))
    sep = np.full((h, gap, 3), 255, np.uint8)               # white divider
    combo = np.hstack([left, sep, right])
    cw = combo.shape[1]
    px = max(16, int(round(w / 45.0)))                      # banner titles, in the figure's font
    banner_h = max(34, int(round(px * 1.9)))
    banner = np.full((banner_h, cw, 3), 28, np.uint8)       # dark title strip
    items = []
    for text, cx in ((labels[0], w // 2), (labels[1], w + gap + w // 2)):
        tw, th = text_size(text, px, 0)
        items.append((text, cx - tw / 2.0, (banner_h - th) / 2.0, px, (255, 255, 255), 0))
    _draw_texts(banner, items)
    final = np.vstack([banner, combo])
    return write_figure(final, out_path)


def save_image(img_bgr, out_path):
    """Write a BGR image to out_path (see write_figure for the formats)."""
    return write_figure(img_bgr, out_path)


def write_run_metadata(out_dir, tool, image_path, csv_path, n_rows, plaques, pxl_per_mm, *,
                       published, sensitive=False, small=False, watershed=False, precise=False,
                       plate_mm=None, edited=None, edits=None, source_image=None, orientation=None,
                       engine_label=None, extra_settings=None, detection=None):
    """run_metadata.json for one plate, from EXPLICIT engine flags. Shared by save_results
    and the app's Export all, so both describe a result the same way (CT-R1 F6).

    ``detection`` (optional dict, CT-R1 detection D1-D4): how the plaques and the dish were
    found -- ``scale`` (plaque size: auto / standard / small) goes into the settings as
    ``plaque_size``; ``dish_source``, ``dish_reason``, ``n_outside_dish`` and
    ``dish_warnings`` into the plate's record."""
    import provenance
    label = engine_label or provenance.engine_name(
        published=bool(published), sensitive=bool(sensitive) and not published, precise=bool(precise))
    n_manual = sum(1 for p in plaques if p.get("source") not in (None,) + DETECTOR_SOURCES)
    if edited is None:
        edited = n_manual > 0
    settings = {"plate_size_mm": plate_mm, "small_plaque": bool(small),
                "published": bool(published), "sensitive": bool(sensitive) and not published,
                "watershed": bool(watershed) and not published, "edited": bool(edited)}
    if source_image:
        settings["source_image"] = source_image
    if orientation is not None:
        settings["orientation"] = list(orientation)
    det_info = dict(detection or {})
    if det_info.get("scale"):
        settings["plaque_size"] = det_info["scale"]
    settings.update(extra_settings or {})
    rec = {"file": os.path.basename(image_path), "path": image_path,
           "sha256_16": provenance.file_digest(image_path), "n_plaques": int(n_rows),
           "n_manual_or_edited": n_manual, "mm_per_px": pxl_per_mm,
           "csv": os.path.basename(csv_path)}
    if edits:
        rec["edits"] = dict(edits)
    for k in ("dish_source", "dish_reason", "n_outside_dish", "dish_warnings", "sources"):
        if det_info.get(k) is not None:
            rec[k] = det_info[k]
    return provenance.write_metadata(out_dir, tool, label, settings, [rec])


def save_results(plaques, orig_bgr, image_path, out_dir, pxl_per_mm, lawn_gray=None, plate=None,
                 scalebar_mm=None, scalebar_anchor=None, scalebar_color=(255, 255, 255),
                 published=None, write_provenance=True, engine_label=None, *,
                 sensitive=None, small=None, watershed=None, precise=False, plate_mm=None,
                 edited=None, edits=None, source_image=None, orientation=None,
                 labels="numbers", key=False, write_key=False, detection=None):
    """Write data-green-<stem>.csv + out_<stem>.<ext>, and (by default) a run_metadata.json
    sibling saying which engine and edits produced them (PT-9 never covered the editor or
    the app's Save; AUDIT-2026-10.md, PT-31).

    Keyword-only, all optional (CT-R1 F6): ``sensitive`` / ``small`` / ``watershed`` /
    ``precise`` are the flags of the engine that PRODUCED the plaques, ``plate_mm`` the dish
    diameter the calibration stands for, ``edited`` / ``edits`` whether and how the plaque set
    or calibration was changed by hand, ``source_image`` / ``orientation`` the original file
    and the rotate/flip steps when ``image_path`` is an oriented copy. Left as None they fall
    back to what this function always did (the module-level engine settings; "edited" = any
    non-auto plaque) so the CLI editor, measure_samples.py and the batch runner are unchanged.
    The desktop app passes all of them: its Save used to record whatever engine another tab
    had last run. ``labels`` / ``key`` style the overlay (see annotate_plaques);
    ``write_key=True`` also writes out_<stem>_legend_key.<overlay format> (+ .png) and
    out_<stem>_legend_text.txt."""
    os.makedirs(out_dir, exist_ok=True)
    gray = cv2.cvtColor(orig_bgr, cv2.COLOR_BGR2GRAY)

    # turbidity: mean grey inside each plaque (original image) + normalised index
    means = [pst.mean_gray_in_mask(gray, _plaque_mask(gray.shape, p)) for p in plaques]
    if lawn_gray is None:
        lawn_gray = pst.estimate_lawn_gray(gray)
    turb = pst.turbidity_indices(means, lawn_gray)

    rows = []
    for i, (p, mg, tb) in enumerate(zip(plaques, means, turb), start=1):
        dia_pxl, area_mm2, dia_mm = measure(p["area_pxl"], pxl_per_mm, published)
        rows.append({
            "INDEX_COL": i,
            "AREA_PXL": round(p["area_pxl"], 2),
            "DIAMETER_PXL": round(dia_pxl, 2),
            "AREA_MM2": round(area_mm2, 2),
            "DIAMETER_MM": round(dia_mm, 2),
            "MEAN_GRAY": round(mg, 2),
            "TURBIDITY_REL": round(tb, 3),
            "SOURCE": p["source"],
        })
    annotated = annotate_plaques(orig_bgr, plaques, pxl_per_mm, plate=plate,    # outlines + numbers + scale bar
                                 scalebar_mm=scalebar_mm, scalebar_anchor=scalebar_anchor,
                                 scalebar_color=scalebar_color, labels=labels, key=key,
                                 published=published, precise=precise)

    name = os.path.splitext(os.path.split(image_path)[1])[0]
    ext = os.path.splitext(os.path.split(image_path)[1])[1]
    if ext.lower() in (".heic", ".heif"):   # OpenCV cannot write HEIC
        ext = ".png"
    csv_path = os.path.join(out_dir, f"data-green-{name}.csv")
    img_path = os.path.join(out_dir, f"out_{name}{ext}")
    pd.DataFrame(rows, columns=["INDEX_COL", "AREA_PXL", "DIAMETER_PXL", "AREA_MM2",
                                "DIAMETER_MM", "MEAN_GRAY", "TURBIDITY_REL", "SOURCE"]).to_csv(csv_path, index=False)
    pst.imwrite_checked(img_path, annotated)          # PT-20: never a silent False
    if write_key and plaques:
        try:                                          # in the overlay's own format (CT-R2 N8)
            write_key_files_for(plate_key(plaques, precise), img_path)
        except Exception:                             # a key must never break a save
            pass
    if write_provenance:
        try:
            if published is None:
                published = bool(pst.use_published)
            if sensitive is None:
                sensitive = bool(getattr(pst, "sensitive", False))
            if small is None:
                small = bool(pst.small_plaques)
            if watershed is None:
                watershed = bool(pst.watershed_enabled)
            if plate_mm is None:
                plate_mm = (plate or {}).get("plate_mm")
            write_run_metadata(out_dir, "plaque_gui.save_results", image_path, csv_path, len(rows),
                               plaques, pxl_per_mm, published=published, sensitive=sensitive,
                               small=small, watershed=watershed, precise=precise,
                               plate_mm=plate_mm, edited=edited, edits=edits,
                               source_image=source_image, orientation=orientation,
                               engine_label=engine_label, detection=detection)
        except Exception:                             # provenance must never break a save
            pass
    return csv_path, img_path, len(rows)


# --------------------------------------------------------------------------- #
#  Interactive editor
# --------------------------------------------------------------------------- #
class PlaqueEditor:
    def __init__(self, display_rgb, orig_bgr, proc_gray, plaques, pxl_per_mm,
                 image_path, out_dir, candidates=None, lawn_gray=None, plate=None,
                 small=False, plate_size=None, sensitive=False, fig=None):
        self._ext_fig = fig          # if given, embed into this figure (e.g. inside a Qt app)
        self.display_rgb = display_rgb
        self.orig_bgr = orig_bgr
        self.proc_gray = proc_gray
        self.plaques = plaques
        self.pxl_per_mm = pxl_per_mm
        self.image_path = image_path
        self.out_dir = out_dir
        self.candidates = candidates or []
        self.lawn_gray = lawn_gray
        self.plate = plate           # detected dish (drawn for calibration QC); may be None
        self.small = bool(small)     # remembered so the in-editor Sensitive button can re-detect
        self.plate_size = plate_size
        self.sensitive = bool(sensitive)

        self.mode = "circle"          # or "trace"
        self.undo_stack = []
        self.artists = []
        self.drag_center = None
        self.preview = None
        self._build()

    # ---- figure / widgets ----
    def _build(self):
        import matplotlib.pyplot as plt
        from matplotlib.widgets import Button
        self.plt = plt

        if self._ext_fig is not None:                 # embedded (Qt) mode
            self.fig = self._ext_fig
            self.ax = self.fig.add_subplot(111)
        else:
            self.fig, self.ax = plt.subplots(figsize=(11, 8.5))
            try:
                self.fig.canvas.manager.set_window_title(
                    "Plaque editor - " + os.path.basename(self.image_path))
            except Exception:
                pass
        self.fig.subplots_adjust(left=0.03, right=0.99, top=0.94, bottom=0.11)
        self.ax.imshow(self.display_rgb)
        self.ax.set_xticks([]); self.ax.set_yticks([])
        self._draw_plate()

        self.b_mode = Button(self.fig.add_axes([0.04, 0.02, 0.17, 0.055]), "Mode: Circle")
        self.b_undo = Button(self.fig.add_axes([0.22, 0.02, 0.11, 0.055]), "Undo")
        self.b_save = Button(self.fig.add_axes([0.34, 0.02, 0.11, 0.055]), "Save")
        self.b_help = Button(self.fig.add_axes([0.46, 0.02, 0.11, 0.055]), "Help")
        self.b_mode.on_clicked(lambda e: self._toggle_mode())
        self.b_undo.on_clicked(lambda e: self._undo())
        self.b_save.on_clicked(lambda e: self._save())
        self.b_help.on_clicked(lambda e: self._help())
        self.b_sens = None
        if self._ext_fig is None:        # standalone window: offer a live Sensitive toggle
            self.b_sens = Button(self.fig.add_axes([0.59, 0.02, 0.22, 0.055]),
                                 "Sensitive: " + ("ON" if self.sensitive else "OFF"))
            self.b_sens.on_clicked(lambda e: self._toggle_sensitive())

        self.fig.canvas.mpl_connect("button_press_event", self._on_press)
        self.fig.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self.fig.canvas.mpl_connect("button_release_event", self._on_release)
        self.fig.canvas.mpl_connect("key_press_event", self._on_key)

        self._redraw()
        self._title()

    def show(self):
        self.plt.show()

    # ---- plate / dish overlay (calibration QC) ----
    def _draw_plate(self):
        """Draw the detected dish so you can confirm the mm calibration is trustworthy.
        Orange dashed circle = the enclosing circle the calibration scales off; thin solid
        outline = the actual detected dish boundary; label shows diameter + tilt ratio."""
        if not self.plate:
            self.ax.set_title("", fontsize=9)
            return
        from matplotlib.patches import Circle, Polygon
        cx, cy = self.plate["center"]
        r = self.plate["radius"]
        self.ax.add_patch(Circle((cx, cy), r, fill=False, color="orange",
                                 lw=1.6, ls="--", alpha=0.9))
        hull = self.plate.get("hull")
        if hull is not None and len(hull) >= 3:
            self.ax.add_patch(Polygon(np.asarray(hull, dtype=float), closed=True,
                                     fill=False, color="orange", lw=1.0, alpha=0.55))
        ar = self.plate.get("axis_ratio")
        tag = "detected plate  Ø=%.0f px" % self.plate["diam_px"]
        if ar:
            tag += ",  axis ratio %.2f%s" % (ar, "  - tilted, mm may be biased" if ar > 1.03 else "")
        self.ax.text(cx, cy - r, tag, color="orange", fontsize=7, ha="center", va="bottom",
                     bbox=dict(boxstyle="round,pad=0.2", fc="black", ec="orange", alpha=0.5))

    # ---- helpers ----
    def _toolbar_active(self):
        try:
            return getattr(self.fig.canvas.manager.toolbar, "mode", "") not in ("", None)
        except Exception:
            return False

    def _title(self, msg=None):
        cal = ("%.4f mm/px" % self.pxl_per_mm) if self.pxl_per_mm else "pixels only"
        base = (f"{len(self.plaques)} plaques  |  add-mode: {self.mode}  |  {cal}   "
                f"(left-drag = circle, right-click = remove, t = mode, u = undo, s = save)")
        self.ax.set_title((msg + "   --   " + base) if msg else base, fontsize=9)
        self.fig.canvas.draw_idle()

    def _push_undo(self):
        # Snapshot the detection state too: a Sensitive toggle replaces the plaque set, the
        # lawn reference and the candidates, and Undo used to put back only the plaques,
        # leaving the button and the TURBIDITY_REL reference out of step (AUDIT-2026-10.md).
        self.undo_stack.append({"plaques": [dict(p) for p in self.plaques],
                                "sensitive": getattr(self, "sensitive", None),
                                "lawn_gray": getattr(self, "lawn_gray", None),
                                "candidates": getattr(self, "candidates", None),
                                "proc_gray": getattr(self, "proc_gray", None)})

    def _find_plaque(self, x, y):
        """Index of the smallest plaque containing (x, y), else nearest centre within 15 px."""
        best, best_area = None, None
        for i, p in enumerate(self.plaques):
            inside = False
            if p["kind"] == "circle":
                inside = np.hypot(x - p["center"][0], y - p["center"][1]) <= p["radius"]
            else:
                inside = cv2.pointPolygonTest(np.asarray(p["contour"], dtype=np.int32),
                                              (float(x), float(y)), False) >= 0
            if inside and (best_area is None or p["area_pxl"] < best_area):
                best, best_area = i, p["area_pxl"]
        if best is not None:
            return best
        nearest, nd = None, 15.0
        for i, p in enumerate(self.plaques):
            d = np.hypot(x - p["center"][0], y - p["center"][1])
            if d < nd:
                nearest, nd = i, d
        return nearest

    # ---- drawing ----
    def _redraw(self):
        from matplotlib.patches import Circle
        for a in self.artists:
            try:
                a.remove()
            except Exception:
                pass
        self.artists = []
        for i, p in enumerate(self.plaques, start=1):
            color = "lime" if p["source"] == "auto" else "deepskyblue"
            if p["kind"] == "circle":
                c = Circle(p["center"], p["radius"], fill=False, color=color, lw=1.4)
                self.ax.add_patch(c)
                self.artists.append(c)
            else:
                cnt = np.asarray(p["contour"], dtype=np.int32).reshape(-1, 2)
                xs = np.append(cnt[:, 0], cnt[0, 0])
                ys = np.append(cnt[:, 1], cnt[0, 1])
                line, = self.ax.plot(xs, ys, color=color, lw=1.2)
                self.artists.append(line)
            t = self.ax.text(p["center"][0], p["center"][1], str(i),
                             color="yellow", fontsize=7, ha="center", va="center")
            self.artists.append(t)
        self.fig.canvas.draw_idle()

    # ---- events ----
    def _on_press(self, event):
        if event.inaxes != self.ax or self._toolbar_active() or event.xdata is None:
            return
        x, y = event.xdata, event.ydata
        if event.button == 3:                       # right click -> remove
            idx = self._find_plaque(x, y)
            if idx is None:
                self._title("nothing to remove there")
                return
            self._push_undo()
            removed = self.plaques.pop(idx)
            self._redraw()
            self._title(f"removed a {removed['source']} plaque")
            return
        if event.button == 1:
            if self.mode == "circle":
                from matplotlib.patches import Circle
                self.drag_center = (x, y)
                self.preview = Circle((x, y), 0.1, fill=False, color="yellow", lw=1.5, ls="--")
                self.ax.add_patch(self.preview)
                self.fig.canvas.draw_idle()
            else:
                self._add_trace(x, y)

    def _on_motion(self, event):
        if self.drag_center is None or event.inaxes != self.ax or event.xdata is None:
            return
        r = np.hypot(event.xdata - self.drag_center[0], event.ydata - self.drag_center[1])
        self.preview.set_radius(max(r, 0.1))
        self.fig.canvas.draw_idle()

    def _on_release(self, event):
        if self.drag_center is None:
            return
        cx, cy = self.drag_center
        self.drag_center = None
        if self.preview is not None:
            self.preview.remove()
            self.preview = None
        if event.xdata is None or event.inaxes is not self.ax:
            # Released over a button: xdata is then the BUTTON's 0-1 coordinate, and the
            # old check added a dish-sized bogus "manual" plaque (AUDIT-2026-10.md).
            self.fig.canvas.draw_idle()
            return
        r = float(np.hypot(event.xdata - cx, event.ydata - cy))
        if r < 3:
            self.fig.canvas.draw_idle()
            return
        self._push_undo()
        self.plaques.append({"source": "manual", "kind": "circle",
                             "center": (cx, cy), "radius": r, "area_pxl": float(np.pi * r * r)})
        self._redraw()
        self._title("added circle")

    def _add_trace(self, x, y):
        res = trace_at(self.candidates, self.proc_gray, x, y)
        if res is None:
            self._title("auto-trace failed here - use circle mode instead")
            return
        hull, area, center = res
        self._push_undo()
        self.plaques.append({"source": "manual", "kind": "contour",
                             "contour": hull, "area_pxl": area, "center": center})
        self._redraw()
        self._title("added traced plaque")

    def _on_key(self, event):
        if event.key in ("t", "T"):
            self._toggle_mode()
        elif event.key in ("u", "U", "ctrl+z"):
            self._undo()
        elif event.key in ("s", "S"):
            self._save()
        elif event.key in ("h", "H"):
            self._help()

    def _toggle_mode(self):
        self.mode = "trace" if self.mode == "circle" else "circle"
        self.b_mode.label.set_text("Mode: " + ("Trace" if self.mode == "trace" else "Circle"))
        self._title()

    def _toggle_sensitive(self):
        """Re-run auto-detection with sensitive mode flipped, KEEPING any manual edits.
        Standalone only — the app drives detection through the locked engine_api adapter."""
        if self._ext_fig is not None or self.b_sens is None:
            return
        manual = [p for p in self.plaques if p.get("source") == "manual"]
        self._push_undo()
        self.sensitive = not self.sensitive
        try:
            (_disp, _orig, proc, plaques, _ppm, candidates, lawn_gray, _plate) = run_detection(
                self.image_path, self.plate_size, self.small, self.sensitive)
        except Exception as e:
            self.sensitive = not self.sensitive          # revert flag on failure
            self.undo_stack.pop()                         # discard the unused checkpoint
            self._title(f"sensitive toggle failed: {e}")
            return
        self.plaques = plaques + manual                   # calibration/dish are unchanged
        self.proc_gray = proc
        self.candidates = candidates or []
        self.lawn_gray = lawn_gray
        self.b_sens.label.set_text("Sensitive: " + ("ON" if self.sensitive else "OFF"))
        self._redraw()
        self._title(f"sensitive {'ON' if self.sensitive else 'OFF'}: "
                    f"{len(plaques)} auto + {len(manual)} manual")

    def _undo(self):
        if not self.undo_stack:
            self._title("nothing to undo")
            return
        state = self.undo_stack.pop()
        if isinstance(state, dict):
            self.plaques = state["plaques"]
            if state.get("sensitive") is not None and state["sensitive"] != getattr(self, "sensitive", None):
                self.sensitive = state["sensitive"]
                self.lawn_gray = state.get("lawn_gray")
                self.candidates = state.get("candidates") or []
                self.proc_gray = state.get("proc_gray")
                if getattr(self, "b_sens", None) is not None:
                    self.b_sens.label.set_text("Sensitive: " + ("ON" if self.sensitive else "OFF"))
        else:                                   # pre-1.1.1 snapshots were a bare list
            self.plaques = state
        self._redraw()
        self._title("undid last change")

    def _save(self):
        csv_path, img_path, n = save_results(
            self.plaques, self.orig_bgr, self.image_path, self.out_dir,
            self.pxl_per_mm, self.lawn_gray)
        print(f"Saved {n} plaques -> {csv_path}")
        print(f"Annotated image  -> {img_path}")
        self._title(f"SAVED {n} plaques to {os.path.relpath(csv_path)}")

    def _help(self):
        print(__doc__)
        self._title("help printed to the console window")


# --------------------------------------------------------------------------- #
#  Entry point
# --------------------------------------------------------------------------- #
def parse_args():
    ap = argparse.ArgumentParser(description="Interactive plaque measurement editor")
    ap.add_argument("image", nargs="?", help="path to the input image")
    ap.add_argument("-i", "--image", dest="image_opt", help="path to the input image")
    ap.add_argument("-p", "--plate_size", help="plate diameter (mm) for mm measurements")
    ap.add_argument("-small", "--small_plaque", action="store_true",
                    help="for plaques < 2.5 mm or low-resolution images")
    ap.add_argument("-o", "--out", default="out", help="output directory (default: out)")
    ap.add_argument("--selftest", action="store_true",
                    help="run detection + a synthetic edit + save without opening a window")
    ap.add_argument("--published", action="store_true",
                    help="use exact published Plaque Size Tool detection/sizing behaviour")
    ap.add_argument("--watershed", action="store_true",
                    help="split touching/merged plaques via watershed before editing")
    ap.add_argument("-sensitive", "--sensitive", action="store_true",
                    help="also catch very small plaques (lowers size gates; more, noisier; off under --published)")
    a = ap.parse_args()
    return ((a.image_opt or a.image), a.plate_size, a.small_plaque, a.out, a.selftest,
            a.published, a.watershed, a.sensitive)


def pick_file():
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        path = filedialog.askopenfilename(
            title="Select a plaque image",
            filetypes=[("Images", "*.tif *.tiff *.jpg *.jpeg *.png"), ("All files", "*.*")])
        root.destroy()
        return path
    except Exception:
        return None


def main():
    image, plate_size, small, out_dir, selftest, published, watershed, sensitive = parse_args()
    pst.use_published = published
    pst.watershed_enabled = bool(watershed) and not published
    if not image:
        image = pick_file()
        if not image:
            print("No image selected.")
            return

    display_rgb, orig, proc, plaques, ppm, candidates, lawn_gray, plate = run_detection(
        image, plate_size, small, sensitive)
    cal = ("%.5f mm/px" % ppm) if ppm else "pixels only (no -p given or plate not found)"
    if sensitive and not published:
        print("(sensitive mode ON: catching very small plaques - more, and some false positives)")
    print(f"Auto-detected {len(plaques)} plaques.  Calibration: {cal}")
    if plate and plate.get("axis_ratio") and plate["axis_ratio"] > 1.03:
        print(f"  NOTE: detected dish axis ratio {plate['axis_ratio']:.2f} (>1.03) - "
              f"photo may be tilted; mm calibration could be biased.")

    if selftest:
        h, w = orig.shape[:2]
        r = 40.0
        plaques.append({"source": "manual", "kind": "circle",
                        "center": (w / 2.0, h / 2.0), "radius": r, "area_pxl": float(np.pi * r * r)})
        # seed the auto-trace test on a real detected plaque if we have one
        if plaques and plaques[0]["source"] == "auto":
            tx, ty = plaques[0]["center"]
        else:
            tx, ty = w / 2.0, h / 3.0
        res = trace_at(candidates, proc, tx, ty)
        if res:
            hull, area, center = res
            plaques.append({"source": "manual", "kind": "contour",
                            "contour": hull, "area_pxl": area, "center": center})
            print(f"auto-trace OK (area={area:.0f}px)")
        else:
            print("auto-trace returned None at the test point (acceptable)")
        csv_path, img_path, n = save_results(plaques, orig, image, out_dir, ppm, lawn_gray)
        print(f"SELFTEST saved {n} rows -> {csv_path}")
        print(f"SELFTEST image     -> {img_path}")
        return

    PlaqueEditor(display_rgb, orig, proc, plaques, ppm, image, out_dir, candidates, lawn_gray,
                 plate=plate, small=small, plate_size=plate_size, sensitive=sensitive).show()


if __name__ == "__main__":
    main()
