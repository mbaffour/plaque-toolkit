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
    "current":   {"small": True},
    "sensitive": {"small": True, "sensitive": True},
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
            out.append(path)
    return sorted(out)


def _safe_float(v):
    """Best-effort float() that returns None instead of raising (for stat fields)."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    # guard against NaN sneaking into CSVs as a number
    return f if f == f else None


def batch_measure(folder, plate_mm=100, mode="current", small=True, watershed=False,
                  out_dir=None, progress=None, crops=False):
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
    out_dir : str or None
        Output directory. Defaults to ``<folder>/out_batch`` and is created.
    progress : callable(str) or None
        Optional status callback, invoked once per image.
    crops : bool
        When True, also write a Fiji/ImageJ-calibrated cropped-plate TIFF per image
        (``<name>_plate.tif`` + a ``.fiji.txt`` sidecar) into the per-image folder,
        so the same scale-bar-in-Fiji workflow applies to every photo in one run.

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
    if watershed:
        mode_kwargs["watershed"] = True
    if small and mode == "published":
        mode_kwargs["small"] = True

    images = find_images(folder)
    N = len(images)

    plate_rows = []     # one dict per image -> per_plate.csv
    all_frames = []     # list of per-image plaque DataFrames -> all_plaques.csv
    errors = []         # list of {"image", "error"} for failures

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

            plaques = det["plaques"]
            orig_bgr = det["orig_bgr"]
            ppm = det["pxl_per_mm"]
            lawn_gray = det["lawn_gray"]
            plate = det.get("plate")

            # ---- save annotated image + per-image CSV -------------------- #
            # save_results creates ``perimg`` itself; it writes the overlay and
            # the data-green-<name>.csv mirroring the single-image GUI output.
            plaque_gui.save_results(plaques, orig_bgr, path, perimg, ppm,
                                    lawn_gray, plate=plate)

            # ---- optional Fiji-calibrated cropped-plate TIFF ------------- #
            if crops:
                import plate_crop
                plate_crop.save_plate_crop(
                    orig_bgr, plate, ppm, os.path.join(perimg, name + "_plate.tif"))

            # ---- measurement table (no file writes) ---------------------- #
            df = engine_api.measure_table(plaques, orig_bgr, ppm, lawn_gray)

            # diameter summary stats over this plate's plaques
            if len(df):
                diam = df["DIAMETER_MM"].astype(float)
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

            n_plaques = int(det.get("n_plaques", len(df)))
            plate_rows.append({
                "image": os.path.basename(path),
                "n_plaques": n_plaques,
                "mm_per_px": _safe_float(ppm),
                "median_diam_mm": median_diam,
                "mean_diam_mm": mean_diam,
                "axis_ratio": axis_ratio,
                "tilt_flag": tilt_flag,
            })

            # add the IMAGE column and stash for the combined all_plaques.csv
            df = df.copy()
            df.insert(0, "IMAGE", os.path.basename(path))
            all_frames.append(df)

            if progress:
                progress("%d/%d %s: %d plaques" % (i, N, name, n_plaques))

        except Exception as exc:  # one bad image must not abort the whole batch
            errors.append({"image": os.path.basename(path), "error": str(exc)})
            # record an error row in the per-plate table so it's visible in the CSV
            plate_rows.append({
                "image": os.path.basename(path),
                "n_plaques": None,
                "mm_per_px": None,
                "median_diam_mm": None,
                "mean_diam_mm": None,
                "axis_ratio": None,
                "tilt_flag": False,
                "error": str(exc),
            })
            if progress:
                progress("%d/%d %s: ERROR %s" % (i, N, name, exc))

    # ---- assemble + write the combined CSVs ------------------------------ #
    plate_cols = ["image", "n_plaques", "mm_per_px", "median_diam_mm",
                  "mean_diam_mm", "axis_ratio", "tilt_flag"]
    if any("error" in r for r in plate_rows):
        plate_cols = plate_cols + ["error"]
    summary_df = pd.DataFrame(plate_rows, columns=plate_cols)

    if all_frames:
        all_df = pd.concat(all_frames, ignore_index=True)
    else:
        # empty frame with the expected columns so downstream code never KeyErrors
        all_df = pd.DataFrame(columns=[
            "IMAGE", "INDEX", "AREA_PXL", "DIAMETER_PXL", "AREA_MM2",
            "DIAMETER_MM", "MEAN_GRAY", "TURBIDITY_REL", "SOURCE"])

    summary_df.to_csv(os.path.join(out_dir, "per_plate.csv"), index=False)
    all_df.to_csv(os.path.join(out_dir, "all_plaques.csv"), index=False)

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
