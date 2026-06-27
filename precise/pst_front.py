"""Precise pipeline -- PLAQUE-ENV front end (stage 1 + stage 6 data).

Runs in the 'plaque' conda env (cv2, numpy<2, pandas, imutils; PST + plaque_gui).
For one plate it produces, from the ORIGINAL image:
  * dish geometry (center, radius, diam_px) for the artifact masks + hard rim reject,
  * calibration mm_per_px (the value plaque_gui calls "pxl_per_mm", which is actually
    mm-PER-pixel -- it is plate_mm / dish_diam_px),
  * PST NORMAL centers   (plaque_gui.run_detection(img, plate_mm, True, False)),
  * PST SENSITIVE centers (plaque_gui.run_detection(img, plate_mm, True, True)) with
    their per-plaque area_pxl (used by stage 6 recall gating + the density switch).

It writes a single JSON the plaqseg-env combiner consumes.  No PlaqSeg, no flat-field,
no CLAHE here -- this side only owns the dish + PST detections.

Usage:
  python pst_front.py IMAGE OUT_JSON [PLATE_MM]
"""
import sys
import os
import json

# plaque_gui + plaque_size_tool live at the repo root; ensure they import regardless
# of how this script is launched.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import plaque_gui


def detect(image_path, plate_mm):
    # PST NORMAL pass (used for the density switch reference count).
    res_n = plaque_gui.run_detection(image_path, plate_mm, True, False)
    (_d, orig_bgr, _g, plaques_n, ppm_n, _c, _l, plate) = res_n

    # PST SENSITIVE pass (recall candidates for the sparse/clean branch).
    res_s = plaque_gui.run_detection(image_path, plate_mm, True, True)
    (_d2, _o2, _g2, plaques_s, ppm_s, _c2, _l2, _p2) = res_s

    h, w = orig_bgr.shape[:2]

    def centers(plaques):
        out = []
        for p in plaques:
            cx, cy = p["center"]
            out.append({"x": float(cx), "y": float(cy),
                        "area_pxl": float(p.get("area_pxl", 0.0))})
        return out

    plate_out = None
    if plate is not None:
        plate_out = {
            "center": [float(plate["center"][0]), float(plate["center"][1])],
            "radius": float(plate["radius"]),
            "diam_px": float(plate.get("diam_px", plate["radius"] * 2.0)),
        }

    # plaque_gui's "pxl_per_mm" is mm-per-pixel (plate_mm / dish_diam_px). Keep the
    # NORMAL-pass value (both passes calibrate off the same dish, so they agree).
    mm_per_px = float(ppm_n) if ppm_n else None

    return {
        "image": image_path,
        "plate_mm": float(plate_mm),
        "img_w": int(w), "img_h": int(h),
        "mm_per_px": mm_per_px,
        "plate": plate_out,
        "n_pst_normal": len(plaques_n),
        "n_pst_sensitive": len(plaques_s),
        "pst_normal": centers(plaques_n),
        "pst_sensitive": centers(plaques_s),
    }


def main():
    image = sys.argv[1]
    out = sys.argv[2]
    plate_mm = sys.argv[3] if len(sys.argv) > 3 else "100"
    result = detect(image, plate_mm)
    with open(out, "w") as f:
        json.dump(result, f, indent=1)
    print("PST_FRONT_DONE n_normal=%d n_sensitive=%d mm_per_px=%s diam_px=%s" % (
        result["n_pst_normal"], result["n_pst_sensitive"],
        str(result["mm_per_px"]),
        (str(result["plate"]["diam_px"]) if result["plate"] else "None")))


if __name__ == "__main__":
    main()
