"""
add_scale.py - stamp a physical scale bar onto ANY plate photo.

This reuses the dish calibration the toolkit already computes (via
plaque_gui.run_detection) to work out millimetres-per-pixel, then draws a nice
round scale bar (e.g. "5 mm") with scalebar.draw_scale_bar. It does NOT re-draw
plaque outlines - it scale-bars the original photo, so you can add a bar to any
existing image without re-measuring.

Usage:
  python add_scale.py --image IMG [--plate-mm 100] [--out OUT]
  python add_scale.py IMG                 (positional image, default plate 100 mm)

Output: <name>_scaled.jpg next to the input (or --out path). If the dish can't be
found / calibrated, a pixel-length bar is drawn instead so it never fails.
"""

import argparse
import os
import sys

import cv2

import plaque_gui
import plaque_size_tool as pst
from scalebar import draw_scale_bar


def add_scale(image_path, plate_mm="100", out_path=None):
    """Read image_path, get dish calibration, stamp the scale bar, save and return out path."""
    # Read via the toolkit's HEIC-safe reader so iPhone photos work too.
    img = pst.read_image_bgr(image_path)
    if img is None:
        raise SystemExit(f"Could not read image: {image_path}")

    mm_per_px = None
    try:
        # run_detection returns pxl_per_mm which is actually mm/px (the calibration).
        # We only want the calibration here, so plaque detection results are ignored.
        result = plaque_gui.run_detection(image_path, str(plate_mm), True)
        mm_per_px = result[4]          # pxl_per_mm position in the returned tuple
    except Exception as e:
        print(f"  (calibration/detection failed: {e}; drawing a pixel-length bar)")
        mm_per_px = None

    if mm_per_px:
        print(f"  calibration: {mm_per_px:.5f} mm/px  (plate {plate_mm} mm)")
    else:
        print("  no calibration (dish not found); drawing a pixel-length bar")

    draw_scale_bar(img, mm_per_px)

    if out_path is None:
        base = os.path.splitext(image_path)[0]
        out_path = base + "_scaled.jpg"
    # OpenCV cannot write some extensions for HEIC inputs; force a jpg if needed.
    ext = os.path.splitext(out_path)[1].lower()
    if ext in (".heic", ".heif", ""):
        out_path = os.path.splitext(out_path)[0] + ".jpg"

    ok = cv2.imwrite(out_path, img)
    if not ok:
        raise SystemExit(f"Failed to write output: {out_path}")
    return out_path


def parse_args():
    ap = argparse.ArgumentParser(description="Add a physical scale bar to a plate photo")
    ap.add_argument("image", nargs="?", help="path to the input image")
    ap.add_argument("-i", "--image", dest="image_opt", help="path to the input image")
    ap.add_argument("--plate-mm", "--plate_mm", dest="plate_mm", default="100",
                    help="petri dish diameter in mm for calibration (default 100)")
    ap.add_argument("--out", dest="out", default=None,
                    help="output path (default: <name>_scaled.jpg)")
    a = ap.parse_args()
    return (a.image_opt or a.image), a.plate_mm, a.out


def main():
    image, plate_mm, out = parse_args()
    if not image:
        print("No image given. Usage: python add_scale.py --image IMG [--plate-mm 100]")
        sys.exit(1)
    out_path = add_scale(image, plate_mm, out)
    print(f"Saved scaled image -> {out_path}")


if __name__ == "__main__":
    main()
