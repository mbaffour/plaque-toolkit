"""Convert the public VACVPlaque dataset into per-well plates with toolkit ground-truth labels.

VACVPlaque (De et al., Scientific Data 2025; RODARE record 3003, CC BY 4.0) is 211 phone
photographs of crystal-violet-stained 6-well plates with hand-drawn per-plaque and per-well
instance masks. It is a *different domain* from phage lawns on Petri dishes -- mammalian
monolayers in 35 mm wells -- which is exactly why it makes a good held-out test: none of the
toolkit's engines or weights ever saw it.

This script cuts every well out of every photo (the well mask gives the "dish"), writes the
crop as an 8-bit PNG, and writes a `labels_<image>_w<k>.json` in the toolkit's
`plaque-groundtruth-v1` schema next to it, so `app/validate.py` can score any engine on it
unchanged. The mm calibration is NOMINAL: a 6-well plate well is taken as 34.8 mm across, and
mm/px is derived from the well mask's equivalent diameter. Detection metrics do not depend on
it; size agreement is also reported in pixels by `vacvplaque_benchmark.py`.

Usage:
    python validation/benchmarks/vacvplaque_convert.py <split folder> <out folder>
        [--well-mm 34.8] [--margin 0.12] [--scale 3] [--max-images N]

<split folder> is the unzipped VACVPlaque_<split>.zip (images/, plaque_masks/, well_masks/).
Nothing is written inside the repository; point <out folder> at a scratch location.
"""
import argparse
import hashlib
import json
import math
import os
import sys

import numpy as np
from PIL import Image

SCHEMA = "plaque-groundtruth-v1"


def _sha1(path):
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def convert_image(img_path, plaque_mask_path, well_mask_path, out_dir, well_mm=34.8, margin=0.12,
                  source_tag="VACVPlaque", scale=1.0):
    """Write one PNG + one labels JSON per well. Returns a list of manifest rows."""
    img = np.asarray(Image.open(img_path).convert("RGB"))
    pm = np.asarray(Image.open(plaque_mask_path))
    wm = np.asarray(Image.open(well_mask_path))
    if pm.shape != img.shape[:2] or wm.shape != img.shape[:2]:
        raise ValueError("mask/image shape mismatch for %s" % os.path.basename(img_path))
    H, W = pm.shape
    stem = os.path.splitext(os.path.basename(img_path))[0]
    rows = []
    for wid in sorted(int(v) for v in np.unique(wm) if v != 0):
        wmask = wm == wid
        ys, xs = np.nonzero(wmask)
        if xs.size < 1000:
            continue
        x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
        mw, mh = x1 - x0, y1 - y0
        pad_x, pad_y = int(round(margin * mw)), int(round(margin * mh))
        cx0, cx1 = max(0, x0 - pad_x), min(W, x1 + pad_x + 1)
        cy0, cy1 = max(0, y0 - pad_y), min(H, y1 + pad_y + 1)
        crop = img[cy0:cy1, cx0:cx1]
        if scale != 1.0:
            # Scale normalisation: the toolkit's size gates are in pixels and were tuned on
            # Petri-dish photos ~1500-2800 px across; a 35 mm well photographed on a 6-well
            # plate is ~600 px across, so its plaques fall under the gates. Upsample so the
            # well spans a dish-like pixel diameter; every coordinate below is scaled too.
            crop = np.asarray(Image.fromarray(crop).resize(
                (int(round(crop.shape[1] * scale)), int(round(crop.shape[0] * scale))), Image.BICUBIC))
        well_area_px = float(wmask.sum()) * scale * scale
        well_diam_px = 2.0 * math.sqrt(well_area_px / math.pi)
        mm_per_px = well_mm / well_diam_px

        # plaques whose instance pixels fall (mostly) inside this well
        sub_pm = pm[cy0:cy1, cx0:cx1]
        sub_wm = wmask[cy0:cy1, cx0:cx1]
        ids, counts = np.unique(sub_pm[sub_wm], return_counts=True)
        plaques = []
        for pid, n_in in zip(ids, counts):
            if pid == 0:
                continue
            inst = sub_pm == pid
            n_tot = int(inst.sum())
            if n_in < 0.5 * n_tot:              # mostly in another well (touching the rim)
                continue
            py, px = np.nonzero(inst)
            area_px = float(n_tot) * scale * scale
            r_px = math.sqrt(area_px / math.pi)
            plaques.append({
                "index": len(plaques) + 1,
                "x_px": round(float(px.mean()) * scale, 1), "y_px": round(float(py.mean()) * scale, 1),
                "r_px": round(r_px, 2), "area_px": round(area_px, 1),
                "diam_mm": round(2.0 * r_px * mm_per_px, 4),
                "source": "manual", "kind": "mask", "instance_id": int(pid),
            })
        name = "%s_w%d" % (stem, wid)
        png = os.path.join(out_dir, name + ".png")
        Image.fromarray(crop).save(png)
        meta = {
            "image": name + ".png", "image_path": os.path.abspath(png),
            "mm_per_px": mm_per_px, "n_plaques": len(plaques), "n_manual": len(plaques),
            "dish_diam_px": well_diam_px,
            "dish_center_px": [float(xs.mean() - cx0) * scale, float(ys.mean() - cy0) * scale],
            "scale": scale,
            "schema": SCHEMA,
            "dataset": source_tag, "source_image": os.path.basename(img_path),
            "well_id": wid, "well_mm_nominal": well_mm,
            "crop_box_xyxy": [int(cx0), int(cy0), int(cx1), int(cy1)],
            "note": "mm/px is nominal (well taken as %g mm); detection metrics are scale-free" % well_mm,
        }
        with open(os.path.join(out_dir, "labels_%s.json" % name), "w") as fh:
            json.dump({"meta": meta, "plaques": plaques}, fh, indent=1)
        rows.append({"name": name, "source_image": os.path.basename(img_path), "well_id": wid,
                     "n_plaques": len(plaques), "crop_w": int(cx1 - cx0), "crop_h": int(cy1 - cy0),
                     "well_diam_px": round(well_diam_px, 1), "mm_per_px": round(mm_per_px, 6),
                     "png_sha1": _sha1(png)})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("split_dir")
    ap.add_argument("out_dir")
    ap.add_argument("--well-mm", type=float, default=34.8, help="nominal well diameter (mm)")
    ap.add_argument("--margin", type=float, default=0.12, help="crop margin as a fraction of the well")
    ap.add_argument("--scale", type=float, default=1.0,
                    help="upsample factor so a well spans a Petri-dish-like pixel diameter (e.g. 3)")
    ap.add_argument("--max-images", type=int, default=None)
    a = ap.parse_args(argv)
    images = sorted(os.listdir(os.path.join(a.split_dir, "images")))
    if a.max_images:
        images = images[: a.max_images]
    os.makedirs(a.out_dir, exist_ok=True)
    manifest = []
    for i, fn in enumerate(images, 1):
        base = os.path.splitext(fn)[0]
        pm = os.path.join(a.split_dir, "plaque_masks", fn)
        wm = os.path.join(a.split_dir, "well_masks", fn)
        if not (os.path.exists(pm) and os.path.exists(wm)):
            print("skip (no masks):", fn)
            continue
        rows = convert_image(os.path.join(a.split_dir, "images", fn), pm, wm, a.out_dir,
                             well_mm=a.well_mm, margin=a.margin, scale=a.scale)
        manifest += rows
        print("%d/%d %s: %d wells, %d plaques" % (i, len(images), base, len(rows), sum(r["n_plaques"] for r in rows)))
    import csv
    with open(os.path.join(a.out_dir, "manifest.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(manifest[0].keys()))
        w.writeheader()
        w.writerows(manifest)
    print("wrote %d wells, %d plaques -> %s" % (len(manifest), sum(r["n_plaques"] for r in manifest), a.out_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
