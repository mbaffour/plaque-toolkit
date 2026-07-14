#!/usr/bin/env python3
"""fiji_import.py — file Fiji/ImageJ hand-labelled plaques into the training store.

Reads the `plaque_labels_<image>.csv` written by the Plaque Toolkit Fiji macro (measurements in
PIXELS: Area, X, Y, Width, Height) and files them as ground-truth labels, converting to mm with the
mm-per-pixel you pass (the same calibration the app uses; d = 2·sqrt(area·mm_per_px²/π)).

Usage:
    python fiji_import.py --results plaque_labels_WT-1.jpeg.csv --image WT-1.jpeg --mm-per-px 0.0393
    python fiji_import.py --results labels.csv                 # pixels only (no mm)
"""
import argparse
import csv
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # repo root
import label_store as ls


def _num(row, *keys):
    for k in keys:
        v = row.get(k)
        if v not in (None, ""):
            try:
                return float(v)
            except ValueError:
                pass
    return None


def read_results(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def main(argv=None):
    p = argparse.ArgumentParser(description="File Fiji plaque labels into the training store.")
    p.add_argument("--results", required=True, help="the plaque_labels_*.csv from the Fiji macro")
    p.add_argument("--image", default=None, help="the plate image that was labelled (for a stored copy)")
    p.add_argument("--mm-per-px", type=float, default=None, dest="mmpp",
                   help="mm per pixel (the app's calibration); omit for pixel-only labels")
    p.add_argument("--sample", default=None, help="override the sample name (else parsed from the image)")
    p.add_argument("--notes", default="", help="free-text note recorded with the entry")
    p.add_argument("--no-image", action="store_true", help="don't copy the image into the store")
    ns = p.parse_args(argv)

    rows = read_results(ns.results)
    plaques = []
    for i, r in enumerate(rows, start=1):
        area = _num(r, "Area")
        w, h = _num(r, "Width"), _num(r, "Height")
        if area is None and w and h:
            area = math.pi * (w / 2.0) * (h / 2.0)          # ellipse area from the bounding box
        if area is None:
            continue
        x, y = _num(r, "X"), _num(r, "Y")
        r_px = math.sqrt(area / math.pi)
        diam_mm = round(2.0 * math.sqrt(area * (ns.mmpp ** 2) / math.pi), 3) if ns.mmpp else None
        plaques.append({"index": i,
                        "x_px": round(x, 1) if x is not None else None,
                        "y_px": round(y, 1) if y is not None else None,
                        "r_px": round(r_px, 1), "area_px": round(area, 1),
                        "diam_mm": diam_mm, "source": "manual", "kind": "oval"})
    if not plaques:
        raise SystemExit("No plaque rows found in %s (expected ImageJ Results with an Area column)." % ns.results)

    stem = os.path.splitext(os.path.basename(ns.image or ns.results))[0]
    stem = re.sub(r"^plaque_labels_", "", stem)
    stem = re.sub(r"\.(jpe?g|png|tif|tiff|heic|bmp)$", "", stem, flags=re.I)
    meta = {"image": (os.path.basename(ns.image) if ns.image else stem),
            "image_path": (os.path.abspath(ns.image) if ns.image else None),
            "mm_per_px": ns.mmpp, "n_plaques": len(plaques),
            "schema": "plaque-groundtruth-v1", "labeller": "fiji"}
    if ns.sample:
        meta["sample_override"] = ns.sample
    out = ls.file_into_store(meta, plaques,
                             ns.image if (ns.image and os.path.exists(ns.image)) else None,
                             source="fiji-manual", engine="manual(fiji)", notes=ns.notes,
                             copy_image=not ns.no_image)
    n, tot, by = ls.catalog_summary()
    print("filed %d plaques%s -> %s" % (len(plaques), (" (mm calibrated)" if ns.mmpp else " (pixels only)"),
                                        os.path.basename(out)))
    print("store now: %d labelled plates, %d plaques -> %s" % (n, tot, ls.store_root()))


if __name__ == "__main__":
    main()
