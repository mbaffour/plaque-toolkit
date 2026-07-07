"""plate_crop.py — export a cropped, Fiji/ImageJ-calibrated plate image.

The dish region of a plate photo is written as a TIFF that carries spatial
calibration in **millimetres**, in the exact tag layout ImageJ/Fiji reads
automatically (an ``ImageJ=...\\nunit=mm`` ImageDescription plus an XResolution
of pixels-per-mm). When such a TIFF is opened in Fiji:

  * ``Image > Properties…`` already shows the pixel size in mm — no manual
    *Set Scale* step.
  * Cropping or Duplicating a plaque **preserves** that calibration, so a
    zoomed-in plaque keeps the correct mm scale.
  * ``Analyze > Tools > Scale Bar…`` then draws a correct mm bar.

This lets the user crop the whole plate here, then crop individual plaques in
Fiji and add consistent scale bars — using one shared, image-specific scale.

Pillow is used as the writer (always present in the app / frozen build, and it
emits byte-for-byte the same tags ImageJ itself writes); no extra dependency.
"""
import os

import numpy as np
from PIL import Image
from PIL.TiffImagePlugin import ImageFileDirectory_v2

# TIFF tag numbers
_TAG_IMAGEDESCRIPTION = 270
_TAG_XRESOLUTION = 282
_TAG_YRESOLUTION = 283
_TAG_RESOLUTIONUNIT = 296


def read_mm_per_px(path):
    """mm-per-pixel embedded in an ImageJ/Fiji-calibrated TIFF (ImageDescription
    ``unit=mm|cm|um`` + XResolution = pixels-per-unit) — e.g. the app's own
    ``…_plate.tif`` crop. Returns ``None`` when absent or ambiguous.

    Deliberately ignores a plain DPI resolution tag: a camera JPEG/TIFF often carries a
    meaningless XResolution (72, 300 …) that must NOT be mistaken for a plate scale, so a
    metric ``unit=`` in the ImageDescription is required."""
    try:
        import re
        from PIL import Image
        with Image.open(path) as im:
            tags = getattr(im, "tag_v2", None)
            desc = tags.get(270) if tags else None   # ImageDescription
            xres = tags.get(282) if tags else None   # XResolution (pixels per unit)
        if not desc or xres is None:
            return None
        m = re.search(r"unit=([a-zµ]+)", str(desc).lower())
        if not m:
            return None
        mm_per_unit = {"mm": 1.0, "cm": 10.0, "um": 1e-3, "µm": 1e-3,
                       "micron": 1e-3, "microns": 1e-3}.get(m.group(1))
        xr = float(xres)                              # IFDRational -> pixels per unit
        if not mm_per_unit or xr <= 0:
            return None
        return mm_per_unit / xr                       # mm per pixel
    except Exception:
        return None


def crop_box_from_plate(shape, plate, margin_frac=0.03):
    """Bounding box (x0, y0, x1, y1) around the detected dish, clipped to the image.

    ``plate`` is the detection's dish dict ({'center': (cx, cy), 'radius': r, …}).
    ``margin_frac`` adds a thin rim of surrounding context (fraction of radius).
    Falls back to the whole image when no usable dish geometry is present.
    """
    H, W = shape[:2]
    if plate and plate.get("center") and plate.get("radius"):
        cx, cy = plate["center"]
        r = float(plate["radius"]) * (1.0 + float(margin_frac))
        x0 = int(max(0, round(cx - r)))
        y0 = int(max(0, round(cy - r)))
        x1 = int(min(W, round(cx + r)))
        y1 = int(min(H, round(cy + r)))
        if x1 - x0 >= 8 and y1 - y0 >= 8:
            return x0, y0, x1, y1
    return 0, 0, W, H


def write_calibrated_tiff(rgb, out_path, mm_per_px=None):
    """Write an RGB/gray ndarray as a TIFF, embedding ImageJ mm calibration when known.

    When ``mm_per_px`` is a positive number, ImageJ/Fiji will open the file already
    scaled in millimetres (pixel width = mm_per_px). Returns ``out_path``.
    """
    img = Image.fromarray(np.asarray(rgb))
    ifd = ImageFileDirectory_v2()
    if mm_per_px and mm_per_px > 0:
        px_per_mm = 1.0 / float(mm_per_px)
        # ImageDescription with unit=mm is what makes Fiji report the scale in mm;
        # XResolution = pixels-per-mm, so Fiji's pixelWidth = 1/XRes = mm_per_px.
        ifd[_TAG_IMAGEDESCRIPTION] = "ImageJ=1.54f\nunit=mm\n"
        ifd[_TAG_XRESOLUTION] = px_per_mm
        ifd[_TAG_YRESOLUTION] = px_per_mm
        ifd[_TAG_RESOLUTIONUNIT] = 1  # 'none' — the unit comes from the description
    img.save(out_path, format="TIFF", tiffinfo=ifd)
    return out_path


def _write_readme(tiff_path, info, source_name):
    """Write a sidecar <name>.fiji.txt explaining the calibration + Fiji workflow."""
    readme = os.path.splitext(tiff_path)[0] + ".fiji.txt"
    mm_per_px = info["mm_per_px"]
    px_per_mm = info["px_per_mm"]
    x0, y0, x1, y1 = info["box"]
    w, h = info["crop_px"]
    lines = []
    lines.append("PLATE CROP — Fiji / ImageJ scale")
    lines.append("================================")
    lines.append("File          : %s" % os.path.basename(tiff_path))
    lines.append("Cropped from  : %s" % source_name)
    lines.append("Crop box (px) : x %d–%d , y %d–%d   (%d × %d px)" % (x0, x1, y0, y1, w, h))
    lines.append("")
    if mm_per_px:
        lines.append("Calibration   : 1 px = %.5f mm   (%.4f px per mm)" % (mm_per_px, px_per_mm))
        lines.append("")
        lines.append("This TIFF is ALREADY calibrated in millimetres.")
        lines.append("In Fiji / ImageJ:")
        lines.append("  • Image > Properties…  shows Pixel width = %.5f mm." % mm_per_px)
        lines.append("  • Crop or Duplicate a plaque — the mm scale is kept.")
        lines.append("  • Analyze > Tools > Scale Bar…  draws a correct mm bar.")
        lines.append("")
        lines.append("If a Fiji build does not auto-read the scale, set it once:")
        lines.append("  Analyze > Set Scale…")
        lines.append("     Distance in pixels : %.4f" % px_per_mm)
        lines.append("     Known distance     : 1")
        lines.append("     Unit of length     : mm")
        lines.append("")
        lines.append("IMPORTANT — one scale PER photo: each plate's mm/px depends on how")
        lines.append("big the dish was in that photo, so this value is specific to THIS")
        lines.append("image. Only tick 'Global' in Set Scale for crops of this SAME plate;")
        lines.append("do not reuse one scale across different photos.")
    else:
        lines.append("Calibration   : NONE — no Petri dish was detected in the source,")
        lines.append("                so the mm scale is unknown for this crop.")
        lines.append("")
        lines.append("Set the scale yourself in Fiji from a known reference (e.g. the dish")
        lines.append("rim of known diameter):  Analyze > Set Scale…")
    lines.append("")
    with open(readme, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return readme


def save_plate_crop(orig_bgr, plate, mm_per_px, out_path, margin_frac=0.03, write_readme=True):
    """Crop the dish region from a BGR image and save a Fiji-calibrated TIFF.

    Returns a dict: {tiff, readme, box, mm_per_px, px_per_mm, crop_px}. A sidecar
    ``<name>.fiji.txt`` (the calibration + how-to) is written unless disabled.
    """
    import cv2  # local import (heavy / optional at import time)

    box = crop_box_from_plate(orig_bgr.shape, plate, margin_frac)
    x0, y0, x1, y1 = box
    crop_bgr = orig_bgr[y0:y1, x0:x1]
    rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)

    if not out_path.lower().endswith((".tif", ".tiff")):
        out_path += ".tif"
    write_calibrated_tiff(rgb, out_path, mm_per_px)

    info = {
        "tiff": out_path,
        "readme": None,
        "box": box,
        "mm_per_px": (float(mm_per_px) if mm_per_px else None),
        "px_per_mm": (1.0 / float(mm_per_px) if mm_per_px else None),
        "crop_px": (x1 - x0, y1 - y0),
    }
    if write_readme:
        info["readme"] = _write_readme(out_path, info, "source image")
    return info
