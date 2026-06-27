"""
Batch cross-plate plaque TURBIDITY by transmitted-light optical density.

Designed for comparing plaque turbidity *between phages* on plates imaged in one
session under identical transmitted-light (back-lit) conditions. It anchors every
plaque to the SAME physical references so the values are comparable across plates:

  * I0  (fully clear)  = light through cell-free agar  -> a blank agar plate (--blank)
  * lawn (fully opaque) = each plate's own bacterial lawn (measured per plate)

For each plaque it reports:
  MEAN_GRAY     raw mean grey (0-255) on the ORIGINAL 8-bit image, uncalibrated
  TRANSMITTANCE I / I0   (1.0 = as clear as agar, ~0 = opaque)  [on linearised intensity]
  OD            -log10(I / I0)            (apparent) optical density
  OD_LAWN       the plate's lawn OD       (per-plate opaque reference)
  TURBIDITY     OD / OD_LAWN  clipped     0 = as clear as agar, 1 = as opaque as lawn

Why references are needed: a bare grey value is on an arbitrary 0-255 scale and is
gamma-encoded, so it is not a turbidity. Linearising + dividing by I0 makes it a
relative optical density, and the shared anchors make phage-A-vs-phage-B fair.

IMPORTANT (for publication): OD is a true *absorbance* only when the input is radiometrically
LINEAR (camera RAW / linear TIFF, ideally with --dark + --flat). iPhone HEIC/JPEG apply
spatially-varying tone mapping that inverse-sRGB cannot undo, so OD from such images is an
APPARENT optical density (a within-session relative measure), not a calibrated absorbance.
Use RAW/linear input for any absolute-OD claim.

Usage:
  python plaque_turbidity.py -d PLATES_DIR -p 100 --blank BLANK.tif [--flat FLAT.tif] [-small]
  (file name stem is used as the phage/sample label)

Outputs (in --out, default 'out_turbidity'):
  plaques_all.csv     one row per plaque, all plates, with the columns above
  per_phage.csv       per-phage summary (n, mean/median/SD of OD and TURBIDITY)
  qc.csv              per-plate QC: lawn OD, I0 level, illumination evenness, #plaques

If --blank is omitted, it falls back to anchoring on the lawn only (relative
transmittance vs lawn); still comparable across phages, but without an absolute
clear reference (flagged in the output).
"""

import argparse
import datetime
import hashlib
import json
import math
import os
import sys

import cv2
import numpy as np
import pandas as pd

import plaque_size_tool as pst

__version__ = "2.0"

# enable reading iPhone HEIC/HEIF (computational-photography caveats apply -- see docstring)
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except Exception:
    pass

EPS = 1e-6

# --------------------------------------------------------------------------- #
#  Pixel linearisation (undo sRGB gamma so values are proportional to light)
# --------------------------------------------------------------------------- #
_SRGB_LUT = None


def _srgb_lut():
    global _SRGB_LUT
    if _SRGB_LUT is None:
        v = np.arange(256, dtype=np.float64) / 255.0
        _SRGB_LUT = np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)
    return _SRGB_LUT


def to_linear_gray(bgr, assume_srgb=True):
    """BGR -> linear-light grey in [0, 1]. Forces 8-bit before the sRGB LUT lookup."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    if gray.dtype != np.uint8:                       # e.g. a 16-bit TIFF
        g = gray.astype(np.float64)
        gray = np.clip(g / (g.max() or 1.0) * 255.0, 0, 255).astype(np.uint8)
    if assume_srgb:
        return _srgb_lut()[gray]
    return gray.astype(np.float64) / 255.0


def read_bgr(path):
    """Read any supported image (incl. iPhone HEIC) to a BGR uint8 array.

    Applies EXIF orientation so iPhone photos aren't analysed sideways. Raises a
    normal exception on failure (so batch runs can skip a bad file, not abort).
    """
    from PIL import Image, ImageOps
    ext = os.path.splitext(path)[1].lower()
    # PIL for HEIC and for EXIF-orientation-carrying formats (HEIF/JPEG)
    if ext in (".heic", ".heif", ".jpg", ".jpeg"):
        im = ImageOps.exif_transpose(Image.open(path).convert("RGB"))
        return cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)
    img = cv2.imread(path)
    if img is not None:
        return img
    im = ImageOps.exif_transpose(Image.open(path).convert("RGB"))
    return cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)


# --------------------------------------------------------------------------- #
#  Detection (reuse the validated plaque_size_tool pipeline)
# --------------------------------------------------------------------------- #
def detect_plate(path, plate_size, small):
    """Return dict with plaque hulls, dish geometry, dish & lawn masks."""
    pst.small_plaques = bool(small)
    pst.debug_mode = False

    orig = read_bgr(path)
    # brightness + optional dimming, in-memory (matches pst.main, but HEIC-safe / no temp file)
    brightness = float(cv2.cvtColor(orig, cv2.COLOR_BGR2GRAY).mean())
    image = orig
    if brightness > 70:
        image = np.clip(orig.astype(np.float32) * 0.5, 0, 255).astype(np.uint8)

    binary, high_contrast, clr = pst.process_image(image, 2.5)
    contours = pst.get_contours(binary)
    shape = binary.shape

    green_df, red_df, other_df, plate_df = pst.filter_contours(contours, shape)
    if pst.watershed_enabled:
        rec = pst.recover_merged_plaques(shape, green_df, red_df, other_df)
        if not rec.empty:
            green_df = pd.concat([green_df, rec], ignore_index=True)
    green = pst.check_duplicate_plaques(green_df.copy())
    green = pst.calculate_size_mm(plate_size, green, plate_df)
    if green.size > 0:
        green["MEAN_COLOUR"] = green.apply(
            lambda x: pst.get_mean_grey_colour(clr, x["CONTOURS"]), axis=1)
        green = green[green.apply(lambda x: abs(x["MEAN_COLOUR"]) >= 40, axis=1)]
    green = pst.renumerate_df(green)

    # dish geometry from the largest plate contour
    dish_center, dish_r, dish_mask = None, None, None
    if not plate_df.empty:
        big = plate_df["ENCL_DIAMETER_PXL"].idxmax()
        dish_center = tuple(float(c) for c in plate_df.loc[big, "ENCL_CENTER"])
        dish_r = float(plate_df.loc[big, "ENCL_DIAMETER_PXL"]) / 2.0
        dish_mask = pst._mask_from_contour(shape, plate_df.loc[big, "HULL"])

    # plaque hulls + measurements
    plaques = []
    plaque_masks = []
    for _, row in green.iterrows():
        hull = np.asarray(row["HULL"], dtype=np.int32)
        m = pst._mask_from_contour(shape, hull)
        plaque_masks.append(m)
        plaques.append({"hull": hull, "area_pxl": float(row["AREA_PXL"]),
                        "diameter_mm": row.get("DIAMETER_MM", 0)})

    # lawn = dish interior, eroded off the meniscus, minus (dilated) plaques
    lawn_mask = None
    if dish_mask is not None:
        er = max(int(round(dish_r * 0.06)), 3)
        lawn_mask = cv2.erode(dish_mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (er, er)))
        if plaque_masks:
            union = np.zeros(shape, dtype="uint8")
            for m in plaque_masks:
                union = cv2.bitwise_or(union, m)
            union = cv2.dilate(union, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))
            lawn_mask[union > 0] = 0

    return {"orig": orig, "shape": shape, "plaques": plaques, "plaque_masks": plaque_masks,
            "dish_center": dish_center, "dish_r": dish_r, "dish_mask": dish_mask,
            "lawn_mask": lawn_mask}


# --------------------------------------------------------------------------- #
#  Reference handling: flat-field + blank-agar I0
# --------------------------------------------------------------------------- #
def load_linear(path, shape):
    """Load an image, linearise, resize to `shape`. Used for flat / dark frames."""
    if not path:
        return None
    img = to_linear_gray(read_bgr(path))
    if img.shape != shape:
        img = cv2.resize(img, (shape[1], shape[0]), interpolation=cv2.INTER_LINEAR)
    return img


def make_flat(flat_path, shape, dark=None):
    """Normalised illumination field F (mean 1.0) at the target shape, or None.

    With a dark frame, F is built from (flat - dark) so the correction is the proper
    quantitative form (I-dark)/(flat-dark)."""
    flat = load_linear(flat_path, shape)
    if flat is None:
        return None
    if dark is not None:
        flat = np.clip(flat - dark, 0, None)
    flat = cv2.GaussianBlur(flat, (0, 0), 9)          # smooth: illumination is low-frequency
    mean = float(np.mean(flat[flat > 0])) if np.any(flat > 0) else 1.0
    flat = np.clip(flat / (mean + EPS), 0.2, 5.0)     # guard against tiny/zero values
    return flat


def core_mask(mask, area_pxl, core_frac):
    """Erode a plaque mask to its central `core_frac` of radius (reduces halo / edge
    / lawn contamination of the turbidity reading). Falls back to the full mask if
    erosion would empty it."""
    if core_frac >= 1.0:
        return mask
    equiv_r = (area_pxl / np.pi) ** 0.5
    k = int(round((1.0 - core_frac) * equiv_r))
    if k < 1:
        return mask
    eroded = cv2.erode(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * k + 1, 2 * k + 1)))
    return eroded if eroded.any() else mask


def align_blank(blank_lin, blank_geo, dst_center, dst_r, dst_shape):
    """Similarity-warp the blank's clear field onto the sample's dish position."""
    (bx, by), br = blank_geo
    scale = dst_r / br if br else 1.0
    M = np.array([[scale, 0, dst_center[0] - scale * bx],
                  [0, scale, dst_center[1] - scale * by]], dtype=np.float64)
    return cv2.warpAffine(blank_lin, M, (dst_shape[1], dst_shape[0]),
                          flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


# --------------------------------------------------------------------------- #
#  Per-plate OD measurement
# --------------------------------------------------------------------------- #
def mean_in_mask(arr, mask):
    vals = arr[mask > 0]
    return float(np.mean(vals)) if vals.size else float("nan")


def measure_plate(det, phage, plate, flat, blank_lin, blank_geo, dark=None, core_frac=1.0):
    """Return (rows, qc) for one plate."""
    shape = det["shape"]

    # saturation/clipping QC on the raw 8-bit dish pixels (Beer-Lambert needs unclipped data)
    gray8 = cv2.cvtColor(det["orig"], cv2.COLOR_BGR2GRAY)
    dm = det["dish_mask"]
    if dm is not None and dm.any():
        dpx = gray8[dm > 0]
        frac_sat = float(np.mean((dpx >= 254) | (dpx <= 1)))
    else:
        frac_sat = float("nan")

    gray = to_linear_gray(det["orig"])
    if dark is not None:
        gray = np.clip(gray - dark, 0, None)
    if flat is not None:
        gray = gray / flat

    # I0 field (clear reference)
    i0_map, i0_level, absolute = None, float("nan"), False
    if blank_lin is not None and det["dish_center"] is not None:
        i0_map = align_blank(blank_lin, blank_geo, det["dish_center"], det["dish_r"], shape)
        if dark is not None:
            i0_map = np.clip(i0_map - dark, 0, None)
        if flat is not None:
            i0_map = i0_map / flat
        i0_level = mean_in_mask(i0_map, det["dish_mask"]) if det["dish_mask"] is not None else float(np.median(i0_map))
        absolute = True

    # lawn reference
    lawn_I = mean_in_mask(gray, det["lawn_mask"]) if det["lawn_mask"] is not None else float("nan")
    if absolute:
        lawn_I0 = mean_in_mask(i0_map, det["lawn_mask"]) if det["lawn_mask"] is not None else i0_level
        od_lawn = -math.log10(max(lawn_I, EPS) / max(lawn_I0, EPS))
    else:
        od_lawn = float("nan")

    rows = []
    plaque_I_vals = []
    n_overclear = 0
    for i, (p, m) in enumerate(zip(det["plaques"], det["plaque_masks"]), start=1):
        mm = core_mask(m, p["area_pxl"], core_frac)   # central region only if core_frac < 1
        I = mean_in_mask(gray, mm)                    # linearised intensity (for OD)
        plaque_I_vals.append(I)
        raw_gray = round(mean_in_mask(gray8, mm), 2)  # true raw 8-bit mean (matches MEAN_GRAY name)
        if absolute:
            I0 = mean_in_mask(i0_map, mm)
            T = max(I, EPS) / max(I0, EPS)
            if T > 1.0:
                n_overclear += 1
            # SIGNED optical density (a real absorbance). Negative OD means the plaque
            # transmits MORE than the clear reference -> usually an I0/flat-field problem,
            # surfaced via the over-clear QC rather than silently clamped to 0.
            od = -math.log10(max(T, EPS))
            turb_raw = od / od_lawn if (od_lawn and od_lawn > EPS) else float("nan")
            # normalized turbidity kept in [0,1] for interpretation; raw OD is unclamped above
            turb = None if turb_raw != turb_raw else round(min(max(turb_raw, 0.0), 1.0), 3)
        else:
            # lawn-only fallback: transmittance relative to lawn (>1 => clearer than lawn)
            T = max(I, EPS) / max(lawn_I, EPS)
            od = float("nan")
            turb = float("nan")
        # categorical clarity from the normalized turbidity (thresholds are conventional)
        clarity = ""
        if isinstance(turb, (int, float)) and turb == turb:
            clarity = "clear" if turb < 0.33 else ("turbid" if turb > 0.66 else "intermediate")
        rows.append({
            "PHAGE": phage,
            "PLATE": plate,
            "PLATE_INDEX": i,
            "AREA_PXL": round(p["area_pxl"], 2),
            "DIAMETER_MM": p["diameter_mm"],
            "MEAN_GRAY": raw_gray,
            "TRANSMITTANCE": round(T, 4),
            "OD": (round(od, 4) if od == od else ""),
            "OD_LAWN": (round(od_lawn, 4) if od_lawn == od_lawn else ""),
            "TURBIDITY": ("" if turb is None or (isinstance(turb, float) and turb != turb) else turb),
            "CLARITY": clarity,
        })

    illum_cv = ""
    if i0_map is not None and det["dish_mask"] is not None:
        v = i0_map[det["dish_mask"] > 0]
        if v.size and np.mean(v) > 0:
            illum_cv = round(float(np.std(v) / np.mean(v)), 3)

    # polarity check: in transmitted light, clear plaques should read BRIGHTER than
    # the lawn. If most plaques are darker than the lawn, the imaging/assumption is off.
    frac_darker = ""
    polarity_ok = True
    if plaque_I_vals and lawn_I == lawn_I:
        frac_darker = round(float(np.mean([1.0 if v < lawn_I else 0.0 for v in plaque_I_vals])), 3)
        polarity_ok = frac_darker <= 0.5

    qc = {
        "PHAGE": phage,
        "PLATE": plate,
        "N_PLAQUES": len(rows),
        "DISH_FOUND": det["dish_center"] is not None,
        "I0_LEVEL": (round(i0_level, 4) if i0_level == i0_level else ""),
        "LAWN_I": (round(lawn_I, 4) if lawn_I == lawn_I else ""),
        "MEAN_PLAQUE_I": (round(float(np.mean(plaque_I_vals)), 4) if plaque_I_vals else ""),
        "OD_LAWN": (round(od_lawn, 4) if od_lawn == od_lawn else ""),
        "ILLUM_CV": illum_cv,
        "FRAC_DARKER_THAN_LAWN": frac_darker,
        "FRAC_OVERCLEAR": (round(n_overclear / len(rows), 3) if (absolute and rows) else ""),
        "FRAC_SATURATED": (round(frac_sat, 4) if frac_sat == frac_sat else ""),
        "POLARITY_OK": polarity_ok,
        "ABSOLUTE_OD": absolute,
    }
    return rows, qc


# --------------------------------------------------------------------------- #
#  Batch driver
# --------------------------------------------------------------------------- #
def list_images(directory):
    exts = (".tif", ".tiff", ".jpg", ".jpeg", ".png", ".heic", ".heif")
    out = []
    for r, _, files in os.walk(directory):
        for f in sorted(files):
            if os.path.splitext(f)[1].lower() in exts:
                out.append(os.path.join(r, f))
    return out


def summarise(df):
    """Per-phage summary. Reports BOTH plaque-level pooled stats and plate-level
    stats (mean of per-plate means). For cross-phage stats use the plate-level
    columns: the plate is the biological replicate, the plaque is not (pooling
    plaques across one plate is pseudoreplication)."""
    if df.empty:
        return pd.DataFrame()
    metrics = [c for c in ("TRANSMITTANCE", "OD", "TURBIDITY") if c in df.columns]
    rows = []
    for phage, g in df.groupby("PHAGE"):
        rec = {"PHAGE": phage,
               "N_PLATES": g["PLATE"].nunique() if "PLATE" in g else 1,
               "N_PLAQUES": len(g)}
        for col in metrics:
            vals = pd.to_numeric(g[col], errors="coerce").dropna()
            if "PLATE" in g:
                per_plate = (g.assign(_v=pd.to_numeric(g[col], errors="coerce"))
                             .groupby("PLATE")["_v"].mean().dropna())
            else:
                per_plate = vals
            rec[f"{col}_PLAQUE_MEAN"] = round(vals.mean(), 4) if len(vals) else ""
            rec[f"{col}_PLATE_MEAN"] = round(per_plate.mean(), 4) if len(per_plate) else ""
            rec[f"{col}_PLATE_SD"] = round(per_plate.std(ddof=1), 4) if len(per_plate) > 1 else ""
        rows.append(rec)
    return pd.DataFrame(rows)


def phage_label(stem, group_by_prefix):
    """Derive the phage label from a file stem. With --group-by-prefix, everything
    before the last '_' or '-' is the phage (so T4_1, T4_2 -> phage 'T4')."""
    if group_by_prefix:
        for sep in ("_", "-"):
            if sep in stem:
                return stem.rsplit(sep, 1)[0]
    return stem


def annotate_plate(det, rows, out_dir, plate):
    """Save a QC overlay: dish outline + plaque hulls coloured green(clear)->red(turbid)."""
    img = det["orig"].copy()
    if det["dish_center"] is not None:
        cv2.circle(img, (int(round(det["dish_center"][0])), int(round(det["dish_center"][1]))),
                   int(round(det["dish_r"])), (0, 200, 255), 3)
    for p, r in zip(det["plaques"], rows):
        hull = np.asarray(p["hull"], dtype=np.int32)
        val = r.get("TURBIDITY")
        if isinstance(val, (int, float)):
            v = min(max(float(val), 0.0), 1.0)
            col = (0, int(255 * (1 - v)), int(255 * v))    # BGR: green=clear, red=turbid
        else:
            col = (0, 200, 0)
        cv2.drawContours(img, [hull], -1, col, 2)
        (cx, cy), _ = cv2.minEnclosingCircle(hull)
        cv2.putText(img, str(r["PLATE_INDEX"]), (int(cx), int(cy)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    cv2.imwrite(os.path.join(out_dir, f"overlay_{plate}.png"), img)


def write_metadata(out_dir, args_dict, images, qc_rows, errors):
    """Write run_metadata.json for provenance/reproducibility."""
    meta = {
        "tool": "plaque_turbidity.py",
        "version": __version__,
        "timestamp_utc": datetime.datetime.utcnow().isoformat() + "Z",
        "args": args_dict,
        "python": sys.version.split()[0],
        "engine_size_tool": getattr(pst, "__version__", "?"),
        "library_versions": {"opencv": cv2.__version__, "numpy": np.__version__,
                             "pandas": pd.__version__},
        "n_images": len(images),
        "n_failed": len(errors),
        "images": [],
    }
    for path in images:
        try:
            with open(path, "rb") as fh:
                h = hashlib.sha256(fh.read()).hexdigest()[:16]
        except Exception:
            h = ""
        meta["images"].append({"file": os.path.basename(path), "sha256_16": h})
    with open(os.path.join(out_dir, "run_metadata.json"), "w") as f:
        json.dump(meta, f, indent=2)


def write_plots(df, out_dir):
    """Per-phage comparison box plots + overlaid histograms for size & turbidity."""
    if df.empty:
        return
    try:
        # Use bare Figure objects (NOT pyplot / matplotlib.use) so this is thread-safe and
        # never switches the global backend -- important when called from inside a Qt app.
        from matplotlib.figure import Figure
    except Exception:
        return
    for metric in ("DIAMETER_MM", "TURBIDITY", "TRANSMITTANCE"):
        if metric not in df.columns:
            continue
        groups = {}
        for phage, g in df.groupby("PHAGE"):
            v = pd.to_numeric(g[metric], errors="coerce").dropna()
            if len(v):
                groups[phage] = v.values
        if not groups:
            continue
        try:
            fig = Figure(figsize=(max(5, 1.3 * len(groups)), 4))
            ax = fig.add_subplot(111)
            ax.boxplot(list(groups.values()), tick_labels=list(groups.keys()), showmeans=True)
            ax.set_ylabel(metric)
            ax.set_title(f"{metric} by phage")
            fig.tight_layout()
            fig.savefig(os.path.join(out_dir, f"compare_{metric}.png"), dpi=120)

            fig = Figure(figsize=(6, 4))
            ax = fig.add_subplot(111)
            for phage, v in groups.items():
                ax.hist(v, bins=20, alpha=0.5, label=str(phage))
            ax.set_xlabel(metric)
            ax.set_ylabel("plaque count")
            ax.set_title(f"{metric} distribution")
            ax.legend(fontsize=8)
            fig.tight_layout()
            fig.savefig(os.path.join(out_dir, f"hist_{metric}.png"), dpi=120)
        except Exception as e:
            print(f"  (plot failed for {metric}: {e})")


def run_batch(directory, plate_size, small, blank_path, flat_path, out_dir,
              group_by_prefix=False, dark_path=None, core_frac=1.0, make_overlays=True,
              dilution=None, volume_ul=None, make_plots=True):
    images = list_images(directory)
    if not images:
        raise SystemExit(f"No images found in {directory}")
    os.makedirs(out_dir, exist_ok=True)

    # prepare references once (a bad blank/flat should not abort the whole run)
    shape0 = None
    flat = None
    dark = None
    blank_lin, blank_geo = None, None
    try:
        sample0 = detect_plate(images[0], plate_size, small)
        shape0 = sample0["shape"]
        dark = load_linear(dark_path, shape0)
        flat = make_flat(flat_path, shape0, dark)
    except Exception as e:
        print(f"WARNING: could not pre-read {images[0]} ({e}); continuing.")
        sample0 = None
    if blank_path:
        try:
            bdet = detect_plate(blank_path, plate_size, small)
            blank_lin = to_linear_gray(bdet["orig"])
            if bdet["dish_center"] is None:
                print("WARNING: no dish detected in blank; using whole-image median as I0 "
                      "(absolute OD will be approximate).")
                blank_geo = ((bdet["shape"][1] / 2, bdet["shape"][0] / 2), max(bdet["shape"]) / 2)
            else:
                blank_geo = (bdet["dish_center"], bdet["dish_r"])
        except Exception as e:
            print(f"WARNING: could not read blank {blank_path} ({e}); falling back to lawn-relative mode.")

    all_rows, qc_rows, errors = [], [], []
    for path in images:
        plate = os.path.splitext(os.path.basename(path))[0]
        phage = phage_label(plate, group_by_prefix)
        try:
            det = sample0 if (sample0 is not None and path == images[0]) else detect_plate(path, plate_size, small)
            rows, qc = measure_plate(det, phage, plate, flat, blank_lin, blank_geo,
                                     dark=dark, core_frac=core_frac)
        except Exception as e:
            print(f"  ERROR [{plate}]: {e} -- skipped.")
            errors.append({"PLATE": plate, "FILE": path, "ERROR": str(e)})
            continue
        qc["COUNT"] = qc["N_PLAQUES"]
        if dilution and volume_ul:
            qc["PFU_PER_ML"] = round(qc["N_PLAQUES"] / (volume_ul / 1000.0) * dilution, 1)
        all_rows.extend(rows)
        qc_rows.append(qc)
        if make_overlays:
            try:
                annotate_plate(det, rows, out_dir, plate)
            except Exception as e:
                print(f"  (overlay failed for {plate}: {e})")
        mode = "OD" if qc["ABSOLUTE_OD"] else "lawn-relative"
        print(f"{plate} (phage {phage}): {qc['N_PLAQUES']} plaques  ({mode}, lawn_OD={qc['OD_LAWN']})")
        if qc["ABSOLUTE_OD"] and not qc["POLARITY_OK"]:
            print(f"  WARNING [{plate}]: {qc['FRAC_DARKER_THAN_LAWN']:.0%} of plaques are DARKER "
                  f"than the lawn. For transmitted light, clear plaques should be brighter -- "
                  f"check the imaging (is it really back-lit?) before trusting these values.")

    df = pd.DataFrame(all_rows)
    df.to_csv(os.path.join(out_dir, "plaques_all.csv"), index=False)
    summarise(df).to_csv(os.path.join(out_dir, "per_phage.csv"), index=False)
    pd.DataFrame(qc_rows).to_csv(os.path.join(out_dir, "qc.csv"), index=False)
    if errors:
        pd.DataFrame(errors).to_csv(os.path.join(out_dir, "errors.csv"), index=False)

    if make_plots:
        write_plots(df, out_dir)

    write_metadata(out_dir, {"plate_size": plate_size, "small": small, "blank": blank_path,
                             "flat": flat_path, "dark": dark_path, "core_frac": core_frac,
                             "group_by_prefix": group_by_prefix, "dilution": dilution,
                             "volume_ul": volume_ul, "published": pst.use_published,
                             "watershed": pst.watershed_enabled}, images, qc_rows, errors)

    # consolidated QC summary so problems can't be missed
    _print_qc_summary(qc_rows, errors)
    if dilution and volume_ul:
        titers = [q.get("PFU_PER_ML") for q in qc_rows if isinstance(q.get("PFU_PER_ML"), (int, float))]
        if titers:
            print(f"  titer: {len(titers)} plates, PFU/mL range {min(titers):.2e}-{max(titers):.2e}")

    if not blank_path:
        print("\nNOTE: no --blank given -> TURBIDITY/OD are blank; only lawn-relative "
              "TRANSMITTANCE is reported. Provide a blank agar plate for absolute OD.")
    print(f"\nWrote: {os.path.join(out_dir, 'plaques_all.csv')}, per_phage.csv, qc.csv"
          + (", errors.csv" if errors else ""))
    return df


def _print_qc_summary(qc_rows, errors):
    bad_polarity = [q["PLATE"] for q in qc_rows if q.get("ABSOLUTE_OD") and not q.get("POLARITY_OK")]
    no_dish = [q["PLATE"] for q in qc_rows if not q.get("DISH_FOUND")]
    high_cv = [q["PLATE"] for q in qc_rows
               if isinstance(q.get("ILLUM_CV"), (int, float)) and q["ILLUM_CV"] > 0.15]
    print("\n--- QC summary ---")
    print(f"  plates analysed: {len(qc_rows)}" + (f"; failed: {len(errors)}" if errors else ""))
    if no_dish:
        print(f"  NO DISH DETECTED (calibration/turbidity unreliable): {', '.join(no_dish)}")
    if bad_polarity:
        print(f"  POLARITY FAIL (plaques darker than lawn): {', '.join(bad_polarity)}")
    if high_cv:
        print(f"  UNEVEN ILLUMINATION (ILLUM_CV>0.15, use a flat field): {', '.join(high_cv)}")
    if not (no_dish or bad_polarity or high_cv):
        print("  all plates passed dish/polarity/illumination checks.")


def parse_args():
    ap = argparse.ArgumentParser(description="Batch cross-plate plaque turbidity (OD)")
    ap.add_argument("-d", "--directory", required=True, help="folder of phage plate images")
    ap.add_argument("-p", "--plate_size", help="dish diameter (mm)")
    ap.add_argument("-small", "--small_plaque", action="store_true")
    ap.add_argument("--blank", help="blank agar plate image (clear reference, I0)")
    ap.add_argument("--flat", help="flat-field image (bare light box)")
    ap.add_argument("--dark", help="dark-frame image (lens covered / lightbox off)")
    ap.add_argument("--core", type=float, default=1.0,
                    help="measure turbidity over the central fraction of each plaque radius "
                         "(e.g. 0.6) to avoid halo/edge contamination; default 1.0 = whole plaque")
    ap.add_argument("-o", "--out", default="out_turbidity", help="output directory")
    ap.add_argument("--group-by-prefix", action="store_true",
                    help="treat the filename part before the last _ or - as the phage "
                         "(so T4_1, T4_2 are replicates of phage T4)")
    ap.add_argument("--no-overlay", action="store_true", help="skip the QC overlay PNGs")
    ap.add_argument("--dilution", type=float,
                    help="dilution factor of the plated lysate (for PFU/mL titer)")
    ap.add_argument("--volume-ul", type=float,
                    help="plated volume in microlitres (for PFU/mL titer)")
    ap.add_argument("--no-plots", action="store_true", help="skip distribution plots")
    ap.add_argument("--published", action="store_true",
                    help="use exact published Plaque Size Tool detection/sizing behaviour")
    ap.add_argument("--watershed", action="store_true",
                    help="split touching/merged plaques via watershed before measuring OD")
    return ap.parse_args()


def main():
    a = parse_args()
    pst.use_published = a.published
    pst.watershed_enabled = bool(a.watershed) and not a.published
    run_batch(a.directory, a.plate_size, a.small_plaque, a.blank, a.flat, a.out,
              group_by_prefix=a.group_by_prefix, dark_path=a.dark,
              core_frac=a.core, make_overlays=not a.no_overlay,
              dilution=a.dilution, volume_ul=a.volume_ul, make_plots=not a.no_plots)


if __name__ == "__main__":
    main()
