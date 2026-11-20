"""Headless batch folder processor for the plaque-measurement app.

PURE Python — NO PySide6/Qt imports — so it imports and runs in a headless
interpreter (CLI, CI, a worker thread). It reuses the SAME validated detection /
calibration / measurement pipeline the GUI uses, via the thin ``app.engine_api``
adapter and ``plaque_gui`` helpers, and writes two CSVs:

  * ``out_batch/per_plate.csv``   — one row per image (counts + summary stats)
  * ``out_batch/all_plaques.csv`` — every plaque from every image (with IMAGE col)

plus, per image, a sub-folder ``out_batch/<name>/`` containing the annotated
overlay image and the per-plate ``data-green-<name>.csv`` written by
``plaque_gui.save_results``.

Each image is processed inside its own try/except so a single unreadable /
pathological image records an error row and the batch keeps going.

Run as a script:
    python -m app.batch_measure FOLDER [--plate-mm 100] [--mode current] [--out DIR]
or
    python app/batch_measure.py FOLDER ...
"""

import os
import sys

# Image extensions we attempt to load (lower-case, with leading dot).
IMAGE_EXTS = (".tif", ".tiff", ".jpg", ".jpeg", ".png", ".heic", ".heif")

# Mode name -> kwargs passed to engine_api.detect_single. "precise" is handled
# separately (it calls engine_api.detect_precise, not detect_single).
MODE_KWARGS = {
    "published": {"published": True},
    # Current / Sensitive run engine_api.DEFAULT_PLAQUE_SIZE (filled in at run time, so the
    # default lives in one place; CT-R2 coordinator A); the Batch tab's "Plaque size" choice
    # overrides it through ``scale``
    "current":   {},
    "sensitive": {"sensitive": True},
}


def find_images(folder):
    """Return a sorted list of absolute-ish image paths directly inside ``folder``
    (NON-recursive) whose extension is one of IMAGE_EXTS. Hidden/za matching is
    case-insensitive on the extension."""
    if not folder or not os.path.isdir(folder):
        return []
    out = []
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        if os.path.splitext(name)[1].lower() in IMAGE_EXTS:
            try:
                import plaque_size_tool as _pst
                if _pst.is_toolkit_output_file(name, folder):
                    continue
            except Exception:                        # pragma: no cover
                pass
            out.append(path)
    # Natural order (Plate_2 before Plate_10), so the progress line, per_plate.csv and the
    # Batch table all list the plates the way a person numbers them (CT-R1 F18).
    return sorted(out, key=lambda p: natural_key(os.path.basename(p)))


def natural_key(text):
    """Sort key that orders embedded numbers by value: Plate_2 < Plate_10 < plate_11."""
    import re
    parts = re.split(r"(\d+)", str(text).lower())
    return [(0, int(t), "") if t.isdigit() else (1, 0, t) for t in parts if t != ""]


def error_reason(exc, path):
    """Why a plate could not be measured, in plain words and WITHOUT the path."""
    name = os.path.basename(path)
    raw = " ".join(str(exc).split()) or type(exc).__name__
    low = raw.lower()
    if "cannot identify image file" in low or "could not be read" in low:
        return ("not a readable image (empty or damaged file?). Re-export it as TIFF, PNG or "
                "JPEG and run the batch again")
    # drop the path (quoted or not) from the engine's sentence; it is given once, at the end
    reason = raw
    for token in (repr(path), '"%s"' % path, path, repr(name)):
        reason = reason.replace(token, "").strip()
    return " ".join(reason.split()).strip(" :-") or type(exc).__name__


def friendly_error(exc, path):
    """One line for a plate that could not be measured: FILE NAME first, then the reason in
    plain words, the full path last. The raw exception text started with a 150-character
    path, so the reason was cut off in the table and the status line (CT-R1 F18)."""
    return "%s: %s  [%s]" % (os.path.basename(path), error_reason(exc, path), path)


def qc_flag_counts(df):
    """How many of a plate's plaques carry each 'look at me' QC flag: EDGE (touches the dish
    rim / image border), OVERLAP (touches another plaque) and MERGED? (probably two plaques
    counted as one). Tells the user WHICH plates to open in Measure (CT-R1, idea 8)."""
    out = {"n_edge": 0, "n_overlap": 0, "n_merged": 0, "n_split": 0, "n_core": 0}
    if df is None or "QC_FLAG" not in getattr(df, "columns", ()):
        return out
    for flags in df["QC_FLAG"].fillna("").astype(str):
        parts = set(flags.split("|"))
        out["n_edge"] += "EDGE" in parts
        out["n_overlap"] += "OVERLAP" in parts
        out["n_merged"] += "MERGED?" in parts
        out["n_split"] += "SPLIT" in parts           # CT-R1 detection D8 (Auto)
        out["n_core"] += "CORE?" in parts
    return {k: int(v) for k, v in out.items()}


def _safe_float(v):
    """Best-effort float() that returns None instead of raising (for stat fields)."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    # guard against NaN sneaking into CSVs as a number
    return f if f == f else None


def batch_measure(folder, plate_mm=100, mode="current", small=None, watershed=False,
                  out_dir=None, progress=None, crops=False, scale=None, key_on_figure=False):
    """Measure every image in ``folder`` and write combined CSVs.

    Parameters
    ----------
    folder : str
        Directory containing plate images (searched non-recursively).
    plate_mm : float
        Physical plate diameter in mm used for the px->mm calibration.
    mode : {"published", "current", "sensitive", "precise"}
        Detection mode. Maps to engine_api kwargs (see MODE_KWARGS); "precise"
        runs the slower PST+PlaqSeg pipeline via engine_api.detect_precise.
    small, watershed : bool
        Passed through to detect_single. ``small`` only takes effect for the
        "published" mode override below (the other modes already set it); it is
        accepted for API symmetry with the GUI.
    scale : {"auto", "standard", "small"} or None
        Plaque size (CT-R1 detection D1). None = the mode's default:
        engine_api.DEFAULT_PLAQUE_SIZE for Current and Sensitive, Standard for Published (Small when ``small`` is True). Published never
        runs Auto (it falls back to Standard); Precise ignores it.
    out_dir : str or None
        Output directory. Defaults to ``<folder>/out_batch`` and is created.
    progress : callable(str) or None
        Optional status callback, invoked once per image.
    crops : bool
        When True, also write a Fiji/ImageJ-calibrated cropped-plate TIFF per image
        (``<name>_plate.tif`` + a ``.fiji.txt`` sidecar) into the per-image folder,
        so the same scale-bar-in-Fiji workflow applies to every photo in one run.
    key_on_figure : bool
        Draw the legend key on every annotated image (the Batch tab's "Place key on figure").
        The stand-alone key (in the overlay's format, + PNG) and the legend text are written
        beside every annotated image either way (CT-R2 N8).

    Returns
    -------
    dict with keys: summary_df, all_df, out_dir, n_images, errors.
    """
    # Imported here (not at module top) so importing this module stays cheap and
    # never drags in cv2 / the engine just to call find_images.
    import pandas as pd

    import app.engine_api as engine_api
    import plaque_gui

    mode = (mode or "current").lower()
    if mode not in ("published", "current", "sensitive", "precise"):
        raise ValueError(
            "mode must be one of published/current/sensitive/precise, got %r" % mode)

    if out_dir is None:
        out_dir = os.path.join(folder, "out_batch")
    os.makedirs(out_dir, exist_ok=True)

    # detect_single kwargs for the non-precise modes. Honour the caller's
    # ``watershed`` flag, and let an explicit small=True still apply in published
    # mode (published forces sensitive off inside the engine regardless).
    mode_kwargs = dict(MODE_KWARGS.get(mode, {"small": True}))
    if mode in ("current", "sensitive"):
        mode_kwargs.setdefault("scale", engine_api.DEFAULT_PLAQUE_SIZE)
    # Watershed splitting exists only in the Current / Sensitive engines: Published forces it
    # off inside the engine and Precise never reads it. Record (and pass) what is APPLIED,
    # not what was ticked -- run_metadata.json said watershed:true for Published runs that
    # never split anything (CT-R1 F18).
    watershed_used = bool(watershed) and mode in ("current", "sensitive")
    if watershed_used:
        mode_kwargs["watershed"] = True
    # Published gets -small ONLY when the caller asks for it. The old default (small=True)
    # made the Batch tab's "Published" run the engine with -small, so it disagreed with the
    # Measure tab and with `plaque_size_tool.py --published` on every plate
    # (AUDIT-2026-10.md, PT-33).
    if small and mode == "published":
        mode_kwargs["small"] = True
    if scale is not None and mode != "precise":
        mode_kwargs.pop("small", None)
        mode_kwargs["scale"] = plaque_gui.resolve_scale(scale, published=(mode == "published"))
    if mode == "precise":
        scale_used = None
    else:
        scale_used = plaque_gui.resolve_scale(mode_kwargs.get("scale"), mode_kwargs.get("small", False),
                                              published=(mode == "published"))
    small_used = scale_used == "small"

    images = find_images(folder)
    N = len(images)

    plate_rows = []     # one dict per image -> per_plate.csv
    all_frames = []     # list of per-image plaque DataFrames -> all_plaques.csv
    errors = []         # list of {"image", "error"} for failures
    det_info = {}       # image -> dish provenance (CT-R1 detection D2-D4)

    for i, path in enumerate(images, start=1):
        name = os.path.splitext(os.path.basename(path))[0]
        perimg = os.path.join(out_dir, name)
        try:
            # ---- detect -------------------------------------------------- #
            if mode == "precise":
                det = engine_api.detect_precise(
                    path, plate_mm=plate_mm, out_dir=perimg)
            else:
                det = engine_api.detect_single(
                    path, plate_mm=plate_mm, **mode_kwargs)

            # Number the plaques exactly as the Measure tab does (#1 = topmost), so a row of
            # data-green-<name>.csv / all_plaques.csv and a number on the annotated image
            # mean the same plaque as in Measure. The engine's own order ran bottom-up
            # (CT-R1 F17). Only the ORDER changes; every measured value is the same.
            plaques = engine_api.reading_order(det["plaques"])
            orig_bgr = det["orig_bgr"]
            ppm = det["pxl_per_mm"]
            lawn_gray = det["lawn_gray"]
            plate = det.get("plate")
            # how the dish was found and what was dropped, for run_metadata.json (D2-D4)
            det_info[os.path.basename(path)] = {
                k: det[k] for k in ("dish_source", "dish_reason", "n_outside_dish",
                                    "dish_warnings", "sources") if det.get(k) is not None}

            # ---- save annotated image + per-image CSV -------------------- #
            # save_results creates ``perimg`` itself; it writes the overlay and
            # the data-green-<name>.csv mirroring the single-image GUI output.
            # CT-R2 N8 (the standing figure rule): every overlay ships its legend key + text,
            # one per overlay because the outline classes present differ from plate to plate
            plaque_gui.save_results(plaques, orig_bgr, path, perimg, ppm,
                                    lawn_gray, plate=plate, published=(mode == "published"),
                                    write_provenance=False,   # the batch writes its own below
                                    key=bool(key_on_figure), write_key=True)

            # ---- optional Fiji-calibrated cropped-plate TIFF ------------- #
            if crops:
                import plate_crop
                plate_crop.save_plate_crop(
                    orig_bgr, plate, ppm, os.path.join(perimg, name + "_plate.tif"))

            # ---- measurement table (no file writes) ---------------------- #
            df = engine_api.measure_table(plaques, orig_bgr, ppm, lawn_gray,
                                          published=(mode == "published"), plate=plate)
            if det.get("sources") is not None:
                # CT-R2 N9: the same SOURCE words as the Measure tab's flag line
                det_info[os.path.basename(path)]["sources"] = plaque_gui.source_counts_now(
                    [dict(p, qc_flag=f) for p, f in zip(plaques, df["QC_FLAG"])])

            # diameter summary stats over this plate's plaques
            # sizes from size_ok rows only: CORE? / NO_SIZE plaques count but their diameter is
            # another edge definition / not reliable (CT-R1 detection D10a)
            import plaque_qc
            sized = (df[[plaque_qc.size_ok(f) for f in df["QC_FLAG"]]]
                     if len(df) and "QC_FLAG" in df.columns else df)
            n_sized = int(len(sized))
            if len(sized):
                diam = sized["DIAMETER_MM"].astype(float)
                median_diam = _safe_float(diam.median())
                mean_diam = _safe_float(diam.mean())
            else:
                median_diam = mean_diam = None

            # dish ellipticity -> tilt flag (calibration scales off the dish, so
            # an axis ratio > 1.03 means mm values may be biased).
            axis_ratio = None
            if plate:
                axis_ratio = _safe_float(plate.get("axis_ratio"))
            tilt_flag = bool(axis_ratio is not None and axis_ratio > 1.03)

            n_plaques = len(plaques)                 # what the CSV actually holds
            row = {
                "image": os.path.basename(path),
                "n_plaques": n_plaques,
                "n_sized": n_sized,
                "mm_per_px": _safe_float(ppm),
                "median_diam_mm": median_diam,
                "mean_diam_mm": mean_diam,
                "axis_ratio": axis_ratio,
                "tilt_flag": tilt_flag,
            }
            row.update(qc_flag_counts(df))           # n_edge / n_overlap / n_merged
            plate_rows.append(row)

            # add the IMAGE column and stash for the combined all_plaques.csv
            df = df.copy()
            df.insert(0, "IMAGE", os.path.basename(path))
            all_frames.append(df)

            if progress:
                progress("%d/%d %s: %d plaques" % (i, N, name, n_plaques))

        except Exception as exc:  # one bad image must not abort the whole batch
            message = friendly_error(exc, path)
            errors.append({"image": os.path.basename(path), "error": message,
                           "reason": error_reason(exc, path)})
            # record an error row in the per-plate table so it's visible in the CSV
            plate_rows.append({
                "image": os.path.basename(path),
                "n_plaques": None,
                "n_sized": None,
                "mm_per_px": None,
                "median_diam_mm": None,
                "mean_diam_mm": None,
                "axis_ratio": None,
                "tilt_flag": None,           # unknown for a plate that was not measured
                "n_edge": None,
                "n_overlap": None,
                "n_merged": None,
                "n_split": None,
                "n_core": None,
                "error": message,
            })
            if progress:
                progress("%d/%d %s" % (i, N, message))

    # ---- assemble + write the combined CSVs ------------------------------ #
    plate_cols = ["image", "n_plaques", "n_sized", "mm_per_px", "median_diam_mm",
                  "mean_diam_mm", "axis_ratio", "tilt_flag",
                  "n_edge", "n_overlap", "n_merged", "n_split", "n_core"]   # + CT-R1 D8
    if any("error" in r for r in plate_rows):
        plate_cols = plate_cols + ["error"]
    summary_df = pd.DataFrame(plate_rows, columns=plate_cols)
    # Counts are whole numbers. One failed plate (None) used to turn the whole column into
    # floats, so the CSV and the table read "44.0" and "nan" (CT-R1 F18). The nullable
    # integer type writes 44 and an empty cell.
    for col in ("n_plaques", "n_sized", "n_edge", "n_overlap", "n_merged", "n_split", "n_core"):
        summary_df[col] = pd.array(summary_df[col].tolist(), dtype="Int64")

    if all_frames:
        all_df = pd.concat(all_frames, ignore_index=True)
    else:
        # empty frame with the expected columns so downstream code never KeyErrors
        all_df = pd.DataFrame(columns=[
            "IMAGE", "INDEX", "AREA_PXL", "DIAMETER_PXL", "AREA_MM2",
            "DIAMETER_MM", "MEAN_GRAY", "TURBIDITY_REL", "CIRCULARITY", "OVERLAP", "SOURCE", "QC_FLAG"])

    summary_df.to_csv(os.path.join(out_dir, "per_plate.csv"), index=False)
    all_df.to_csv(os.path.join(out_dir, "all_plaques.csv"), index=False)

    # Provenance sibling: which engine, settings and toolkit version made these
    # CSVs (PT-9). Purely additive -- no measurement column changes.
    try:
        import provenance
        provenance.write_metadata(
            out_dir, "app/batch_measure.py",
            provenance.engine_name(published=(mode == "published"),
                                   sensitive=(mode == "sensitive"),
                                   precise=(mode == "precise")),
            {"mode": mode, "plate_size_mm": plate_mm, "small": small_used,
             "plaque_size": scale_used,
             "watershed": watershed_used, "crops": bool(crops), "folder": folder,
             "key_on_figure": bool(key_on_figure)},
            [dict({"file": r.get("image"), "n_plaques": r.get("n_plaques"),
                   "mm_per_px": r.get("mm_per_px"), "axis_ratio": r.get("axis_ratio"),
                   "tilt_flag": r.get("tilt_flag"), "error": r.get("error")},
                  **det_info.get(r.get("image"), {}))
             for r in plate_rows],
            {"n_failed": len(errors)})
    except Exception as exc:
        print("  (could not write run_metadata.json: %s)" % exc)

    return {
        "summary_df": summary_df,
        "all_df": all_df,
        "out_dir": out_dir,
        "n_images": N,
        "errors": errors,
    }


def _ensure_repo_on_path():
    """Insert the repo root (parent of this 'app' package) on sys.path so that
    'import app.engine_api' and 'import plaque_gui' resolve when this file is run
    directly as a script (python app/batch_measure.py ...)."""
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    if root not in sys.path:
        sys.path.insert(0, root)


def main(argv=None):
    import argparse

    _ensure_repo_on_path()

    ap = argparse.ArgumentParser(
        description="Batch-measure every plate image in a folder (headless).")
    ap.add_argument("folder", help="folder of plate images (non-recursive)")
    ap.add_argument("--plate-mm", type=float, default=100,
                    help="plate diameter in mm for the px->mm calibration (default 100)")
    ap.add_argument("--mode", default="current",
                    choices=["published", "current", "sensitive", "precise"],
                    help="detection mode (default current)")
    ap.add_argument("--out", default=None,
                    help="output directory (default <folder>/out_batch)")
    ap.add_argument("--crops", action="store_true",
                    help="also write a Fiji-calibrated cropped-plate TIFF per image")
    args = ap.parse_args(argv)

    if not find_images(args.folder):
        # an empty folder used to "succeed" with 0 images and two header-only CSVs
        print("No images found in %s (looked for %s). Nothing was written."
              % (args.folder, ", ".join(IMAGE_EXTS)))
        return 1

    res = batch_measure(args.folder, plate_mm=args.plate_mm, mode=args.mode,
                        out_dir=args.out, crops=args.crops, progress=lambda s: print(s))

    # Print the per-plate summary as plain text.
    summary = res["summary_df"]
    print()
    print(summary.to_string(index=False))
    print()
    print("images: %d   errors: %d   out_dir: %s"
          % (res["n_images"], len(res["errors"]), res["out_dir"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
