"""Export a YOLO-seg training set (images + polygon labels) from VACVPlaque-style instance masks.

One training image per well: the well is cropped from the photo (well mask bounding box plus a
margin), optionally rescaled, and every plaque instance whose pixels fall mostly inside that
well becomes one polygon (class 0 = plaque) in normalised xy pairs, the format ultralytics
expects (`<class> x1 y1 x2 y2 ...`).

Usage:
    python validation/benchmarks/yolo_dataset_from_masks.py <split folder> <out folder> \
        --name train [--scale 1.0] [--margin 0.12] [--min-area 4]

Writes <out>/images/<name>/*.png and <out>/labels/<name>/*.txt, plus a data.yaml at <out>.
Run once per split (`--name train`, `--name val`). The converter in vacvplaque_convert.py
produces the *scoring* labels; this one produces *training* labels. Keep the test split out
of this script entirely: it is scored, never trained on.
"""
import argparse
import math
import os
import sys

import cv2
import numpy as np
from PIL import Image


def _polygons(inst_mask, min_area):
    """Largest external contour of a binary instance mask, as an (N, 2) float array."""
    cnts, _ = cv2.findContours(inst_mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None
    c = max(cnts, key=cv2.contourArea)
    if cv2.contourArea(c) < min_area or len(c) < 3:
        # a tiny instance: emit a small square so the label is still a valid polygon
        ys, xs = np.nonzero(inst_mask)
        if xs.size == 0:
            return None
        cx, cy = float(xs.mean()), float(ys.mean())
        r = max(1.5, math.sqrt(xs.size / math.pi))
        return np.array([[cx - r, cy - r], [cx + r, cy - r], [cx + r, cy + r], [cx - r, cy + r]])
    return c.reshape(-1, 2).astype(float)


def export_image(img_path, plaque_mask_path, well_mask_path, out_images, out_labels,
                 scale=1.0, margin=0.12, min_area=4):
    img = np.asarray(Image.open(img_path).convert("RGB"))
    pm = np.asarray(Image.open(plaque_mask_path))
    wm = np.asarray(Image.open(well_mask_path))
    H, W = pm.shape
    stem = os.path.splitext(os.path.basename(img_path))[0]
    n_imgs = n_polys = 0
    for wid in sorted(int(v) for v in np.unique(wm) if v != 0):
        wmask = wm == wid
        ys, xs = np.nonzero(wmask)
        if xs.size < 1000:
            continue
        x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
        px_, py_ = int(round(margin * (x1 - x0))), int(round(margin * (y1 - y0)))
        cx0, cx1 = max(0, x0 - px_), min(W, x1 + px_ + 1)
        cy0, cy1 = max(0, y0 - py_), min(H, y1 + py_ + 1)
        crop = img[cy0:cy1, cx0:cx1]
        ch, cw = crop.shape[:2]
        if scale != 1.0:
            crop = np.asarray(Image.fromarray(crop).resize((int(round(cw * scale)), int(round(ch * scale))), Image.BICUBIC))
        sub_pm = pm[cy0:cy1, cx0:cx1]
        sub_wm = wmask[cy0:cy1, cx0:cx1]
        ids, counts = np.unique(sub_pm[sub_wm], return_counts=True)
        lines = []
        for pid, n_in in zip(ids, counts):
            if pid == 0:
                continue
            inst = sub_pm == pid
            if n_in < 0.5 * inst.sum():
                continue
            poly = _polygons(inst, min_area)
            if poly is None:
                continue
            xy = np.clip(poly / np.array([cw, ch]), 0.0, 1.0)       # normalised to the crop
            lines.append("0 " + " ".join("%.5f %.5f" % (x, y) for x, y in xy))
        name = "%s_w%d" % (stem, wid)
        Image.fromarray(crop).save(os.path.join(out_images, name + ".png"))
        with open(os.path.join(out_labels, name + ".txt"), "w") as fh:
            fh.write("\n".join(lines) + ("\n" if lines else ""))
        n_imgs += 1
        n_polys += len(lines)
    return n_imgs, n_polys


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("split_dir")
    ap.add_argument("out_dir")
    ap.add_argument("--name", required=True, help="subset name: train or val")
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--margin", type=float, default=0.12)
    ap.add_argument("--min-area", type=float, default=4.0)
    ap.add_argument("--max-images", type=int, default=None)
    a = ap.parse_args(argv)
    out_images = os.path.join(a.out_dir, "images", a.name)
    out_labels = os.path.join(a.out_dir, "labels", a.name)
    os.makedirs(out_images, exist_ok=True)
    os.makedirs(out_labels, exist_ok=True)
    images = sorted(os.listdir(os.path.join(a.split_dir, "images")))[: a.max_images]
    ti = tp = 0
    for i, fn in enumerate(images, 1):
        ni, npl = export_image(os.path.join(a.split_dir, "images", fn),
                               os.path.join(a.split_dir, "plaque_masks", fn),
                               os.path.join(a.split_dir, "well_masks", fn),
                               out_images, out_labels, a.scale, a.margin, a.min_area)
        ti += ni
        tp += npl
        print("%d/%d %s: %d wells, %d polygons" % (i, len(images), fn, ni, npl), flush=True)
    yaml = os.path.join(a.out_dir, "data.yaml")
    with open(yaml, "w") as fh:
        fh.write("path: %s\ntrain: images/train\nval: images/val\nnames:\n  0: plaque\n" % os.path.abspath(a.out_dir))
    print("wrote %d images, %d polygons for '%s'; data.yaml at %s" % (ti, tp, a.name, yaml))
    return 0


if __name__ == "__main__":
    sys.exit(main())
