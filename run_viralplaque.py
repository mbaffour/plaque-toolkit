"""Run the headless ViralPlaque (LowRes) macro on every plate under a sample-folder tree,
using the dish ROI + mm calibration from PST so the comparison is on the same lawn region.
Writes vp_<photo>.csv (ImageJ Results) into each photo's output folder, plus a root-level
viralplaque_vs_pst.csv comparing ViralPlaque vs PST counts/median diameter, and a tidy
plot_data_viralplaque.csv (one row per plaque).

Usage: python run_viralplaque.py [--root "Plaques to measure"] [--one PATH]
"""
import argparse, os, glob, subprocess
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import plaque_gui as pgui
import plaque_size_tool as pst

JAVA = r"C:\Program Files (x86)\Common Files\Oracle\Java\java8path\java.exe"
JAR = r"C:\Users\mbaff\Downloads\Plaque Size Tool\_imagej\ImageJ\ij.jar"
MACRO_LOWRES = r"C:\Users\mbaff\Downloads\Plaque Size Tool\_imagej\viralplaque_headless.ijm"
MACRO_DIFF = r"C:\Users\mbaff\Downloads\Plaque Size Tool\_imagej\viralplaque_difference.ijm"
# ViralPlaque defaults: min 20 px^2, max 200000 px^2, circ 0.7, median 4, gauss 1, enhance-contrast 1
VP = dict(minPx=20, maxPx=200000, circ=0.7, medR=4, gauss=1, enhcon=1)


def dish_params(img):
    pst.use_published = False
    det = pgui.run_detection(img, "100", True)     # small mode, corrected dish
    plate = det[7]
    if not plate:
        return None
    cx, cy = plate["center"]; r = plate["radius"]
    ppm = plate["diam_px"] / 100.0                  # pixels per mm (100 mm dish)
    r2 = 0.93 * r                                   # inset to drop the rim
    return dict(ppm=ppm, ox=int(round(cx - r2)), oy=int(round(cy - r2)), owh=int(round(2 * r2)))


def run_one(img, outdir, method="lowres"):
    os.makedirs(outdir, exist_ok=True)
    name = os.path.splitext(os.path.basename(img))[0]
    d = dish_params(img)
    if d is None:
        return dict(name=name, count=None, median_mm=None, note="no dish")
    if method == "difference":
        macro, mid = MACRO_DIFF, [VP["enhcon"]]
    else:
        macro, mid = MACRO_LOWRES, [VP["medR"], VP["gauss"]]
    args = ",".join(str(x) for x in [img, outdir, round(d["ppm"], 4), VP["minPx"], VP["maxPx"],
                                     VP["circ"], *mid, d["ox"], d["oy"], d["owh"]])
    subprocess.run([JAVA, "-jar", JAR, "-batch", macro, args], capture_output=True, text=True, timeout=300)
    res = os.path.join(outdir, "vp_%s.csv" % name)
    if not os.path.exists(res):
        return dict(name=name, count=0, median_mm=None, ppm=round(d["ppm"], 3))
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
    a = ap.parse_args()
    base = os.path.dirname(os.path.abspath(__file__))
    root = a.root if os.path.isabs(a.root) else os.path.join(base, a.root)

    if a.one:
        r = run_one(a.one, os.path.join(os.path.dirname(a.one), os.path.splitext(os.path.basename(a.one))[0]), a.method)
        r.pop("diams", None)
        print("ONE:", r)
        return

    rows, tidy = [], []
    for sample in sorted(os.listdir(root)):
        sdir = os.path.join(root, sample)
        if not os.path.isdir(sdir):
            continue
        rep = 0
        for photo in sorted(f for f in os.listdir(sdir) if f.lower().endswith((".jpg", ".jpeg", ".png"))):
            rep += 1
            base_name = os.path.splitext(photo)[0]
            outdir = os.path.join(sdir, base_name)
            r = run_one(os.path.join(sdir, photo), outdir, a.method)
            for dmm in r.pop("diams", []) or []:
                tidy.append({"SAMPLE": sample, "REPLICATE": rep, "PLATE": base_name, "DIAMETER_MM": round(dmm, 3)})
            rows.append({"SAMPLE": sample, "REPLICATE": rep, "PLATE": base_name,
                         "vp_count": r["count"], "vp_median_mm": r["median_mm"], "vp_mean_mm": r.get("mean_mm")})
            print("done %-6s %-12s vp_count=%s vp_median=%s" % (sample, base_name, r["count"], r["median_mm"]))

    pd.DataFrame(tidy).to_csv(os.path.join(root, "plot_data_viralplaque.csv"), index=False)
    vp = pd.DataFrame(rows)
    vp.to_csv(os.path.join(root, "viralplaque_summary.csv"), index=False)
    print("WROTE viralplaque_summary.csv + plot_data_viralplaque.csv | plates:", len(vp),
          "| plaques:", len(tidy))


if __name__ == "__main__":
    main()
