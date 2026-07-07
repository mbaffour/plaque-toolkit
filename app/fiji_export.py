"""app/fiji_export.py — one bundle that makes app<->Fiji plaque correspondence exact.

From the editor's plaques + image it writes, into a folder:
  * ``<name>_plate.tif``        calibrated crop (mm baked in) to open in Fiji
  * ``<name>_RoiSet.zip``       ImageJ ROIs (oval / polygon) in the crop's pixel frame,
                                ordered top-down so ROI #k == plaque #k
  * ``<name>_map.png``          the crop with numbered plaques (an at-a-glance map)
  * ``<name>_registration.csv`` per-plaque crop-frame X/Y (px & mm) + the app measurements
  * ``<name>_fiji.txt``         how-to (calibration + the three ways to line plaques up)

Everything is expressed in the CROP's coordinate frame, which is exactly what Fiji reports
when you open ``<name>_plate.tif`` — so centroids, ROIs and numbers all line up.
"""
import os
import math

import numpy as np
import pandas as pd

from app import engine_api, imagej_roi
import plate_crop


def _contour_xy(p):
    c = np.asarray(p["contour"], dtype=float).reshape(-1, 2)
    return c[:, 0], c[:, 1]


def app_match_frame(plaques, orig_bgr, plate, ppm):
    """Return the app side for fiji_match.match(): INDEX, X, Y, DIAMETER in the CROP frame.

    Coordinates are millimetres when calibrated (ppm set), else crop pixels. This is the
    same frame Fiji sees when it opens the exported ``_plate.tif`` crop."""
    mm_per_px = (1.0 / ppm) if ppm else 1.0
    x0, y0, _x1, _y1 = plate_crop.crop_box_from_plate(orig_bgr.shape, plate)
    rows = []
    for i, p in enumerate(plaques, start=1):
        cx, cy = p["center"]
        _dp, _amm, dia_mm = _measure(p["area_pxl"], ppm)
        rows.append({"INDEX": i,
                     "X": (cx - x0) * mm_per_px, "Y": (cy - y0) * mm_per_px,
                     "DIAMETER": dia_mm})
    return pd.DataFrame(rows, columns=["INDEX", "X", "Y", "DIAMETER"])


def _measure(area_pxl, ppm):
    import plaque_gui as pgui
    return pgui.measure(area_pxl, ppm)


def save_bundle(plaques, orig_bgr, plate, ppm, lawn_gray, out_dir, base_name):
    """Write the full Fiji registration bundle. Returns a dict of output paths + metadata."""
    import cv2
    os.makedirs(out_dir, exist_ok=True)
    mm_per_px = (1.0 / ppm) if ppm else None
    x0, y0, x1, y1 = plate_crop.crop_box_from_plate(orig_bgr.shape, plate)

    # 1) calibrated crop TIFF
    tiff_path = os.path.join(out_dir, f"{base_name}_plate.tif")
    info = plate_crop.save_plate_crop(orig_bgr, plate, mm_per_px, tiff_path, write_readme=False)

    # 2) measurements in the app's order/INDEX
    df = engine_api.measure_table(plaques, orig_bgr, ppm, lawn_gray)

    # 3) ROIs (crop frame) + registration rows + a numbered map
    crop = np.ascontiguousarray(orig_bgr[y0:y1, x0:x1]).copy()
    rois, reg = [], []
    for i, p in enumerate(plaques, start=1):
        cx, cy = p["center"]
        xc, yc = cx - x0, cy - y0
        if p.get("kind") == "circle":
            r = float(p.get("radius", math.sqrt(max(p["area_pxl"], 1) / math.pi)))
            rois.append((f"{i:04d}", imagej_roi.oval_roi(xc - r, yc - r, 2 * r, 2 * r)))
        else:
            xs, ys = _contour_xy(p)
            rois.append((f"{i:04d}", imagej_roi.polygon_roi(xs - x0, ys - y0)))
        row = df.iloc[i - 1]
        reg.append({"INDEX": i,
                    "X_CROP_PX": round(float(xc), 1), "Y_CROP_PX": round(float(yc), 1),
                    "X_MM": (round(float(xc) * mm_per_px, 3) if mm_per_px else ""),
                    "Y_MM": (round(float(yc) * mm_per_px, 3) if mm_per_px else ""),
                    "DIAMETER_MM": row["DIAMETER_MM"], "AREA_MM2": row["AREA_MM2"],
                    "MEAN_GRAY": row["MEAN_GRAY"], "TURBIDITY_REL": row["TURBIDITY_REL"],
                    "SOURCE": row["SOURCE"]})
        p0 = (int(round(xc)), int(round(yc)))
        cv2.circle(crop, p0, 3, (0, 0, 255), -1)
        cv2.putText(crop, str(i), (p0[0] + 5, p0[1] - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(crop, str(i), (p0[0] + 5, p0[1] - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)

    roiset = os.path.join(out_dir, f"{base_name}_RoiSet.zip")
    imagej_roi.write_roiset(rois, roiset)
    map_path = os.path.join(out_dir, f"{base_name}_map.png")
    cv2.imwrite(map_path, crop)

    reg_cols = ["INDEX", "X_CROP_PX", "Y_CROP_PX", "X_MM", "Y_MM", "DIAMETER_MM",
                "AREA_MM2", "MEAN_GRAY", "TURBIDITY_REL", "SOURCE"]
    reg_path = os.path.join(out_dir, f"{base_name}_registration.csv")
    pd.DataFrame(reg, columns=reg_cols).to_csv(reg_path, index=False)

    readme = _write_readme(out_dir, base_name, info, len(plaques))
    return {"tiff": info["tiff"], "roiset": roiset, "map": map_path,
            "registration": reg_path, "readme": readme,
            "n": len(plaques), "calibrated": bool(mm_per_px), "out_dir": out_dir}


def _write_readme(out_dir, base_name, info, n):
    path = os.path.join(out_dir, f"{base_name}_fiji.txt")
    mm = info.get("mm_per_px")
    L = []
    L.append("FIJI REGISTRATION BUNDLE — line up the SAME plaques in Fiji and the app")
    L.append("=" * 68)
    L.append(f"Plaques: {n}   (numbered 1..N top-to-bottom, same as the app)")
    if mm:
        L.append(f"Scale  : 1 px = {mm:.5f} mm  ({1.0/mm:.2f} px/mm) — baked into the TIFF")
    else:
        L.append("Scale  : NONE (no dish detected) — set it in Fiji, or match by pixels")
    L.append("")
    L.append("FILES")
    L.append(f"  {base_name}_plate.tif        the plate crop — OPEN THIS in Fiji")
    L.append(f"  {base_name}_RoiSet.zip       the app's plaques as ImageJ ROIs (same order)")
    L.append(f"  {base_name}_map.png          the crop with plaque numbers drawn on")
    L.append(f"  {base_name}_registration.csv per-plaque X/Y (px & mm) + app measurements")
    L.append("")
    L.append("THREE WAYS TO COMPARE THE SAME PLAQUE (use any / all):")
    L.append("")
    L.append("  A. LOAD THE APP'S OUTLINES (fastest, guarantees #k == #k)")
    L.append(f"     1. Open {base_name}_plate.tif in Fiji.")
    L.append("     2. Analyze > Tools > ROI Manager > More >> > Open… >  the RoiSet.zip.")
    L.append("     3. Set Measurements: tick Area, Centroid, Feret's, Display label.")
    L.append("     4. ROI Manager > Measure. Row k is plaque #k in the app.")
    L.append("        (These are the app's regions — great for measurement agreement.)")
    L.append("")
    L.append("  B. MATCH YOUR OWN INDEPENDENT TRACES BY POSITION (best for validation)")
    L.append(f"     1. Open {base_name}_plate.tif (or your own image) and trace plaques")
    L.append("        yourself. Set Measurements MUST include 'Centroid' (X, Y) + Area.")
    L.append("     2. Measure all, File > Save As > Results.csv.")
    L.append("     3. Back in the app: 'Compare vs Fiji…' next to the table, pick that CSV.")
    L.append("        The app pairs each of your rows to the nearest plaque by location and")
    L.append("        prints the per-plaque differences — no matching numbers needed.")
    L.append("")
    L.append("  C. EYEBALL WITH THE MAP")
    L.append(f"     Keep {base_name}_map.png open beside Fiji to see which plaque is #k.")
    L.append("")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    return path
