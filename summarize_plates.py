"""Combine the per-plate `data-green-*.csv` files into one `summary.csv`
(one row per plate: plaque count + size stats). Aggregation only -- it does NOT
re-run detection, so it never changes any measurement.

Usage:
  python summarize_plates.py [-o OUT_FOLDER]          # default folder: out
  python summarize_plates.py -o OUT -i IMAGE_FOLDER   # also list plates that
                                                      # produced no CSV at all

A plate with **zero** plaques is a real observation (a negative control, a
dilution that came up empty) and gets a row with `N_PLAQUES = 0` -- dropping it
would bias every mean count and titer upward. See AUDIT-2026-09.md (PT-3).
"""
import argparse
import glob
import os
import re

import pandas as pd

PREFIX, SUFFIX = "data-green-", ".csv"
IMAGE_EXTS = (".tif", ".tiff", ".jpg", ".jpeg", ".png", ".heic", ".heif")


def _natural_key(s):
    """Sort Plate_2 before Plate_10 (plain string order puts Plate_10 first)."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", str(s))]


def _stats_row(plate, d, csv_found=True):
    dm = pd.to_numeric(d.get("DIAMETER_MM"), errors="coerce").dropna() if d is not None else []
    am = pd.to_numeric(d.get("AREA_MM2"), errors="coerce").dropna() if d is not None else []
    # A plate with no detected dish has mm columns of 0 (Current) or nan (Published). Zero
    # is a placeholder, not a diameter: averaging it in gave DIAM_MM_MEAN = 0.0 for a plate
    # with real plaques (AUDIT-2026-10.md). Leave the mm cells blank instead, as for nan.
    if len(dm):
        dm = dm[dm > 0]
    if len(am):
        am = am[am > 0]
    return {
        "PLATE": plate,
        "N_PLAQUES": len(d) if d is not None else 0,
        "DIAM_MM_MEAN": round(dm.mean(), 3) if len(dm) else "",
        "DIAM_MM_MEDIAN": round(dm.median(), 3) if len(dm) else "",
        "DIAM_MM_MIN": round(dm.min(), 3) if len(dm) else "",
        "DIAM_MM_MAX": round(dm.max(), 3) if len(dm) else "",
        "AREA_MM2_MEAN": round(am.mean(), 4) if len(am) else "",
        "MM_CALIBRATED": bool(len(dm)) if d is not None and len(d) else "",
        "CSV_FOUND": bool(csv_found),
    }


def _image_stems(images_dir):
    stems = []
    for root, _dirs, files in os.walk(images_dir):
        for f in sorted(files):
            if os.path.splitext(f)[1].lower() in IMAGE_EXTS:
                stems.append(os.path.splitext(f)[0])
    return stems


def summarize(out_dir, images_dir=None):
    rows = []
    seen = set()
    for csv in sorted(glob.glob(os.path.join(out_dir, PREFIX + "*" + SUFFIX))):
        plate = os.path.basename(csv)[len(PREFIX):-len(SUFFIX)]
        seen.add(plate)
        rows.append(_stats_row(plate, pd.read_csv(csv)))

    # Optionally enumerate the INPUT images too, so a plate that produced no CSV at
    # all (a crash, a skipped file) is visible as a gap rather than silently absent.
    missing = []
    if images_dir:
        for stem in _image_stems(images_dir):
            if stem not in seen:
                seen.add(stem)
                missing.append(stem)
                rows.append(_stats_row(stem, None, csv_found=False))

    if not rows:
        print("No %s*%s files found in %s" % (PREFIX, SUFFIX, out_dir))
        return None
    df = pd.DataFrame(rows)
    df = df.iloc[sorted(range(len(df)), key=lambda i: _natural_key(df["PLATE"].iloc[i]))]
    df = df.reset_index(drop=True)
    out = os.path.join(out_dir, "summary.csv")
    df.to_csv(out, index=False)
    print(df.to_string(index=False))
    n_zero = int((df["N_PLAQUES"] == 0).sum())
    if n_zero:
        print(f"\nNote: {n_zero} plate(s) have N_PLAQUES = 0. That is a real observation "
              f"and is included in this table on purpose.")
    n_uncal = int((df["MM_CALIBRATED"] == False).sum())
    if n_uncal:
        print(f"WARNING: {n_uncal} plate(s) have plaques but no mm calibration (no dish was "
              f"detected); their mm columns are blank, not zero.")
    if missing:
        print(f"WARNING: no CSV was found for {len(missing)} input image(s) "
              f"({', '.join(missing[:5])}{'...' if len(missing) > 5 else ''}). They are listed "
              f"with CSV_FOUND = False and N_PLAQUES = 0 -- check whether they failed to process, "
              f"because that is NOT the same as a genuine zero count.")
    print(f"\nWrote {out}  ({len(df)} plates)")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Summarise per-plate plaque CSVs into one table")
    ap.add_argument("-o", "--out", default="out",
                    help="folder holding data-green-*.csv (default: out)")
    ap.add_argument("-i", "--images", default=None,
                    help="optional: the folder of INPUT images, so plates that produced no "
                         "CSV at all are listed too (CSV_FOUND = False)")
    a = ap.parse_args()
    summarize(a.out, a.images)
