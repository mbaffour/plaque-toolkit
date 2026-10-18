"""
Convert a folder of iPhone HEIC/HEIF photos to lossless TIFF.

Every toolkit engine reads HEIC directly (via pillow-heif), so this converter is only
needed for the one path that cannot: `plaque_size_tool.py --upstream-exact`, which
reproduces the original upstream read path, and for third-party tools (Fiji, ViralPlaque).

Note: converting does NOT undo the iPhone's in-camera processing - it just changes the
container. For quantitative turbidity, prefer re-shooting in ProRAW (see notes from setup).

Usage:
  python heic_to_tiff.py -d PATH\\to\\heic_folder [-o OUTPUT_FOLDER]
  (default output: a 'tiff' subfolder inside the input folder)
"""

import argparse
import os

from PIL import Image, ImageOps

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except Exception as e:  # pragma: no cover
    raise SystemExit("pillow-heif is required: pip install pillow-heif  (" + str(e) + ")")


def convert_dir(src_dir, out_dir):
    if not os.path.isdir(src_dir):
        raise SystemExit(f"Not a folder: {src_dir}")
    os.makedirs(out_dir, exist_ok=True)
    n = 0
    for f in sorted(os.listdir(src_dir)):
        if os.path.splitext(f)[1].lower() not in (".heic", ".heif"):
            continue
        src = os.path.join(src_dir, f)
        dst = os.path.join(out_dir, os.path.splitext(f)[0] + ".tif")
        try:
            # exif_transpose: honour the phone's orientation tag, exactly as the engines do
            # when they read the HEIC directly, so the TIFF is not rotated relative to them.
            ImageOps.exif_transpose(Image.open(src)).convert("RGB").save(dst, format="TIFF")
            n += 1
            print(f"  {f} -> {os.path.basename(dst)}")
        except Exception as e:
            print(f"  SKIP {f}: {e}")
    print(f"\nConverted {n} HEIC file(s) -> {out_dir}")
    return n


def main():
    ap = argparse.ArgumentParser(description="Convert HEIC/HEIF photos to TIFF")
    ap.add_argument("-d", "--directory", required=True, help="folder of HEIC images")
    ap.add_argument("-o", "--out", help="output folder (default: <input>/tiff)")
    a = ap.parse_args()
    out = a.out or os.path.join(a.directory, "tiff")
    convert_dir(a.directory, out)


if __name__ == "__main__":
    main()
