"""Batch-measure plaque photos organised in sample subfolders, writing one output folder
per photo (inside its sample folder) with BOTH a normal (-small) and a sensitive result,
plus a dish-calibration check image.

Uses PST in CURRENT (corrected) mode: the dish is chosen as the roundest large contour so
the dark surround around the dish can't hijack the mm calibration. Same PST detection
algorithm (Trofimova & Jaschke 2021) — cite as PST.

Folder layout produced:
  <root>/<SAMPLE>/<photo>/<photo>_normal.csv      (+ _normal.<img>)
                          <photo>_sensitive.csv    (+ _sensitive.<img>)
                          <photo>_dish_check.jpg
  <root>/SUMMARY.csv

Usage:  python measure_samples.py [--root "Plaques to measure"] [--plate 100]
"""
import argparse, os, csv
import cv2
import plaque_gui as pgui
import plaque_size_tool as pst

IMG_EXT = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".heic", ".heif")


def measure_one(ppath, outdir, base, plate_mm):
    """Run normal + sensitive on one photo; return a summary row dict."""
    row = {"photo": os.path.basename(ppath)}
    os.makedirs(outdir, exist_ok=True)
    plate_info = None
    for mode, sens in (("normal", False), ("sensitive", True)):
        det = pgui.run_detection(ppath, str(plate_mm), True, sens)   # small=True
        disp, orig, proc, plaques, ppm, cand, lawn, plate = det
        csv_path, img_path, n = pgui.save_results(plaques, orig, ppath, outdir, ppm, lawn)
        # rename the fixed-name outputs to <base>_<mode>.*
        new_csv = os.path.join(outdir, "%s_%s.csv" % (base, mode))
        new_img = os.path.join(outdir, "%s_%s%s" % (base, mode, os.path.splitext(img_path)[1]))
        os.replace(csv_path, new_csv)
        os.replace(img_path, new_img)
        row["%s_count" % mode] = n
        row["%s_mm_per_px" % mode] = round(ppm, 5) if ppm else None
        if mode == "normal":
            plate_info = (plate, orig)
            row["dish_diam_px"] = round(plate["diam_px"]) if plate else None
            row["dish_axis_ratio"] = round(plate["axis_ratio"], 3) if (plate and plate.get("axis_ratio")) else None
            row["dish_tilt_flag"] = "TILTED?" if (plate and plate.get("axis_ratio") and plate["axis_ratio"] > 1.03) else ""
    # dish-calibration check image (orange circle = dish used for mm scaling)
    if plate_info and plate_info[0]:
        plate, orig = plate_info
        ov = orig.copy()
        c = (int(plate["center"][0]), int(plate["center"][1]))
        cv2.circle(ov, c, max(int(plate["radius"]), 1), (0, 165, 255), 6)
        cv2.imwrite(os.path.join(outdir, "%s_dish_check.jpg" % base), ov)
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="Plaques to measure")
    ap.add_argument("--plate", default="100")
    a = ap.parse_args()
    pst.use_published = False          # CURRENT (corrected) mode -> roundest-dish calibration
    pst.watershed_enabled = False

    root = a.root if os.path.isabs(a.root) else os.path.join(os.path.dirname(os.path.abspath(__file__)), a.root)
    rows = []
    for sample in sorted(os.listdir(root)):
        sdir = os.path.join(root, sample)
        if not os.path.isdir(sdir):
            continue
        photos = sorted(f for f in os.listdir(sdir) if f.lower().endswith(IMG_EXT))
        for photo in photos:
            base = os.path.splitext(photo)[0]
            ppath = os.path.join(sdir, photo)
            outdir = os.path.join(sdir, base)
            try:
                r = measure_one(ppath, outdir, base, a.plate)
                r = {"sample": sample, **r}
            except Exception as e:
                r = {"sample": sample, "photo": photo, "normal_count": "ERROR", "sensitive_count": str(e)[:120]}
            rows.append(r)
            print("done  %-6s %-16s  normal=%s  sensitive=%s  dish_axis=%s%s" % (
                sample, r.get("photo"), r.get("normal_count"), r.get("sensitive_count"),
                r.get("dish_axis_ratio"), ("  " + r["dish_tilt_flag"]) if r.get("dish_tilt_flag") else ""))

    keys = ["sample", "photo", "normal_count", "sensitive_count", "dish_diam_px",
            "dish_axis_ratio", "dish_tilt_flag", "normal_mm_per_px", "sensitive_mm_per_px"]
    with open(os.path.join(root, "SUMMARY.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print("SUMMARY_WRITTEN ->", os.path.join(root, "SUMMARY.csv"), "| photos:", len(rows))


if __name__ == "__main__":
    main()
