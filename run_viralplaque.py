"""Run the headless ViralPlaque (LowRes) macro on every plate under a sample-folder tree,
using the dish ROI + mm calibration from PST so the comparison is on the same lawn region.
Writes vp_<photo>.csv (ImageJ Results) into each photo's output folder, plus a root-level
viralplaque_vs_pst.csv comparing ViralPlaque vs PST counts/median diameter, and a tidy
plot_data_viralplaque.csv (one row per plaque).

Usage: python run_viralplaque.py [--root "Plaques to measure"] [--one PATH] [--plate 100]
"""
import argparse, os, glob, shutil, subprocess
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import plaque_gui as pgui
import plaque_size_tool as pst
from measure_samples import IMG_EXT

# --- Java / ImageJ locations -------------------------------------------------
# These used to be hard-coded to one Windows machine (PT-5). They are now resolved
# relative to this repository, with environment-variable overrides, so the script
# runs wherever the repo is checked out:
#
#   PLAQUE_JAVA        path to java(.exe)                   (default: "java" on PATH)
#   PLAQUE_IMAGEJ_DIR  folder holding ij.jar + the .ijm macros
#                      (default: <repo>/_imagej)
_HERE = os.path.dirname(os.path.abspath(__file__))
_IMAGEJ_DIR = os.environ.get("PLAQUE_IMAGEJ_DIR") or os.path.join(_HERE, "_imagej")

JAVA = os.environ.get("PLAQUE_JAVA") or shutil.which("java") or "java"
JAR = os.path.join(_IMAGEJ_DIR, "ImageJ", "ij.jar")
if not os.path.exists(JAR):                       # some layouts keep ij.jar at the top
    JAR = os.path.join(_IMAGEJ_DIR, "ij.jar")
MACRO_LOWRES = os.path.join(_IMAGEJ_DIR, "viralplaque_headless.ijm")
MACRO_DIFF = os.path.join(_IMAGEJ_DIR, "viralplaque_difference.ijm")


def check_imagej():
    """Fail with an actionable message rather than a cryptic subprocess error."""
    missing = [p for p in (JAR, MACRO_LOWRES) if not os.path.exists(p)]
    if missing:
        raise SystemExit(
            "ImageJ / ViralPlaque files not found:\n  " + "\n  ".join(missing) +
            "\n\nThis script drives the external ViralPlaque ImageJ macro, which is NOT "
            "bundled with the toolkit. Put ij.jar and the .ijm macros under "
            "%s, or set PLAQUE_IMAGEJ_DIR to wherever they live." % _IMAGEJ_DIR)
# ViralPlaque defaults: min 20 px^2, max 200000 px^2, circ 0.7, median 4, gauss 1, enhance-contrast 1
VP = dict(minPx=20, maxPx=200000, circ=0.7, medR=4, gauss=1, enhcon=1)


def dish_params(img, plate_mm=100.0, small=True):
    pst.use_published = False
    det = pgui.run_detection(img, str(plate_mm), small)   # corrected dish
    plate = det[7]
    if not plate:
        return None
    cx, cy = plate["center"]; r = plate["radius"]
    ppm = plate["diam_px"] / float(plate_mm)        # pixels per mm; was hard-coded to 100 mm
    r2 = 0.93 * r                                   # inset to drop the rim
    return dict(ppm=ppm, ox=int(round(cx - r2)), oy=int(round(cy - r2)), owh=int(round(2 * r2)))


def run_one(img, outdir, method="lowres", plate_mm=100.0, small=True):
    os.makedirs(outdir, exist_ok=True)
    name = os.path.splitext(os.path.basename(img))[0]
    d = dish_params(img, plate_mm, small)
    if d is None:
        return dict(name=name, count=None, median_mm=None, note="no dish")
    if method == "difference":
        macro, mid = MACRO_DIFF, [VP["enhcon"]]
    else:
        macro, mid = MACRO_LOWRES, [VP["medR"], VP["gauss"]]
    args = ",".join(str(x) for x in [img, outdir, round(d["ppm"], 4), VP["minPx"], VP["maxPx"],
                                     VP["circ"], *mid, d["ox"], d["oy"], d["owh"]])
    res = os.path.join(outdir, "vp_%s.csv" % name)
    if os.path.exists(res):                      # never let a stale result pass as this run's
        os.remove(res)
    try:
        r = subprocess.run([JAVA, "-jar", JAR, "-batch", macro, args],
                           capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return dict(name=name, count=None, median_mm=None, ppm=round(d["ppm"], 3),
                    note="imagej timed out after 300 s")
    if r.returncode != 0 or not os.path.exists(res):
        # A failed macro used to be recorded as count=0, indistinguishable from a real
        # zero-plaque plate (AUDIT-2026-10.md). count=None + a note means "did not run".
        tail = (r.stderr or r.stdout or "").strip().splitlines()
        return dict(name=name, count=None, median_mm=None, ppm=round(d["ppm"], 3),
                    note="imagej failed (rc=%s): %s" % (r.returncode, " | ".join(tail[-3:])[:200]))
    df = pd.read_csv(res)
    area = pd.to_numeric(df.get("Area"), errors="coerce").dropna()
    area = area[area > 0]
    dia = 2 * np.sqrt(area / np.pi)
    return dict(name=name, count=int(len(df)), median_mm=round(float(dia.median()), 3) if len(dia) else None,
                mean_mm=round(float(dia.mean()), 3) if len(dia) else None, ppm=round(d["ppm"], 3),
                diams=dia.tolist())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="Plaques to measure")
    ap.add_argument("--one", default=None, help="run a single image path and print result")
    ap.add_argument("--method", default="lowres", choices=["lowres", "difference"])
    ap.add_argument("--plate", type=float, default=100.0,
                    help="dish diameter in mm used for the mm calibration (default 100; use the "
                         "same value you gave measure_samples.py --plate)")
    ap.add_argument("--no-small", dest="small", action="store_false",
                    help="detect with the standard (not -small) size gates")
    a = ap.parse_args()
    check_imagej()
    base = os.path.dirname(os.path.abspath(__file__))
    root = a.root if os.path.isabs(a.root) else os.path.join(base, a.root)

    if a.one:
        r = run_one(a.one, os.path.join(os.path.dirname(a.one), os.path.splitext(os.path.basename(a.one))[0]),
                    a.method, a.plate, a.small)
        r.pop("diams", None)
        print("ONE:", r)
        return

    rows, tidy = [], []
    for sample in sorted(os.listdir(root)):
        sdir = os.path.join(root, sample)
        if not os.path.isdir(sdir):
            continue
        rep = 0
        for photo in sorted(f for f in os.listdir(sdir) if f.lower().endswith(IMG_EXT)):
            rep += 1
            base_name = os.path.splitext(photo)[0]
            outdir = os.path.join(sdir, base_name)
            r = run_one(os.path.join(sdir, photo), outdir, a.method, a.plate, a.small)
            for dmm in r.pop("diams", []) or []:
                tidy.append({"SAMPLE": sample, "REPLICATE": rep, "PLATE": base_name, "DIAMETER_MM": round(dmm, 3)})
            rows.append({"SAMPLE": sample, "REPLICATE": rep, "PLATE": base_name,
                         "vp_count": r["count"], "vp_median_mm": r["median_mm"], "vp_mean_mm": r.get("mean_mm"),
                         "note": r.get("note", "")})
            print("done %-6s %-12s vp_count=%s vp_median=%s" % (sample, base_name, r["count"], r["median_mm"]))

    pd.DataFrame(tidy).to_csv(os.path.join(root, "plot_data_viralplaque.csv"), index=False)
    vp = pd.DataFrame(rows)
    vp.to_csv(os.path.join(root, "viralplaque_summary.csv"), index=False)
    print("WROTE viralplaque_summary.csv + plot_data_viralplaque.csv | plates:", len(vp),
          "| plaques:", len(tidy))


if __name__ == "__main__":
    main()
