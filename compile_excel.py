"""Compile every per-photo PST result into ONE Excel workbook.

Sheets:
  - Summary (per photo)   one row per photo: normal & sensitive counts + median/mean Ø, dish info
  - Stats (per sample)    one row per sample: plate-level mean +/- SD of count & diameter (n=plates)
  - Normal - all plaques  every plaque (validated -small gate), long format
  - Sensitive - all plaques  every plaque (sensitive mode), long format

Usage: python compile_excel.py [--root "Plaques to measure"] [--out Plaque_data_compiled.xlsx]
"""
import argparse, os, glob
import numpy as np
import pandas as pd

MODES = ["normal", "sensitive"]
ORDER = ["WT", "2-4", "DTR", "G12E", "I70T", "T65I", "T71A"]


def sample_key(s):
    return (ORDER.index(s) if s in ORDER else len(ORDER), s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="Plaques to measure")
    ap.add_argument("--out", default="Plaque_data_compiled.xlsx")
    a = ap.parse_args()
    base_dir = os.path.dirname(os.path.abspath(__file__))
    root = a.root if os.path.isabs(a.root) else os.path.join(base_dir, a.root)

    # optional dish info from SUMMARY.csv
    dish = {}
    sump = os.path.join(root, "SUMMARY.csv")
    if os.path.exists(sump):
        sdf = pd.read_csv(sump)
        for _, r in sdf.iterrows():
            key = (str(r.get("sample")), os.path.splitext(str(r.get("photo")))[0])
            dish[key] = dict(dish_diam_px=r.get("dish_diam_px"),
                             dish_axis_ratio=r.get("dish_axis_ratio"),
                             dish_tilt_flag=r.get("dish_tilt_flag"),
                             mm_per_px=r.get("normal_mm_per_px"))

    long = {m: [] for m in MODES}
    per_photo = []
    samples = sorted([d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))], key=sample_key)
    for sample in samples:
        sdir = os.path.join(root, sample)
        rep = 0
        for photo_dir in sorted(os.listdir(sdir)):
            pdir = os.path.join(sdir, photo_dir)
            if not os.path.isdir(pdir):
                continue
            rep += 1
            rec = {"SAMPLE": sample, "REPLICATE": rep, "PLATE": photo_dir}
            d0 = dish.get((sample, photo_dir), {})
            rec.update({"DISH_DIAM_PX": d0.get("dish_diam_px"), "DISH_AXIS": d0.get("dish_axis_ratio"),
                        "TILT_FLAG": d0.get("dish_tilt_flag"), "MM_PER_PX": d0.get("mm_per_px")})
            found = False
            for m in MODES:
                csvp = os.path.join(pdir, "%s_%s.csv" % (photo_dir, m))
                if not os.path.exists(csvp):
                    rec["%s_count" % m] = None
                    continue
                df = pd.read_csv(csvp)
                df.insert(0, "SAMPLE", sample); df.insert(1, "REPLICATE", rep)
                df.insert(2, "PLATE", photo_dir); df.insert(3, "MODE", m)
                long[m].append(df)
                dia = pd.to_numeric(df.get("DIAMETER_MM"), errors="coerce").dropna()
                dia = dia[dia > 0]
                rec["%s_count" % m] = int(len(df))
                rec["%s_median_mm" % m] = round(float(dia.median()), 3) if len(dia) else None
                rec["%s_mean_mm" % m] = round(float(dia.mean()), 3) if len(dia) else None
                found = True
            if found:
                per_photo.append(rec)

    photo_df = pd.DataFrame(per_photo)
    front = ["SAMPLE", "REPLICATE", "PLATE"]
    photo_df = photo_df[front + [c for c in photo_df.columns if c not in front]]

    # per-sample plate-level stats (plate = experimental unit)
    stats = []
    for sample in samples:
        sub = photo_df[photo_df["SAMPLE"] == sample]
        if sub.empty:
            continue
        row = {"SAMPLE": sample, "N_PLATES": len(sub)}
        for m in MODES:
            counts = pd.to_numeric(sub["%s_count" % m], errors="coerce").dropna()
            med = pd.to_numeric(sub["%s_median_mm" % m], errors="coerce").dropna()  # per-plate medians
            row["%s_count_mean" % m] = round(counts.mean(), 1) if len(counts) else None
            row["%s_count_sd" % m] = round(counts.std(ddof=1), 1) if len(counts) > 1 else None
            row["%s_diam_mm_mean_of_plate_medians" % m] = round(med.mean(), 3) if len(med) else None
            row["%s_diam_mm_sd_of_plate_medians" % m] = round(med.std(ddof=1), 3) if len(med) > 1 else None
        stats.append(row)
    stats_df = pd.DataFrame(stats)

    def grouped(d):
        if d.empty:
            return d
        d = d.copy()
        d["_o"] = d["SAMPLE"].map(lambda s: ORDER.index(s) if s in ORDER else len(ORDER))
        sort_cols = ["_o", "REPLICATE"] + (["INDEX_COL"] if "INDEX_COL" in d.columns else [])
        d = d.sort_values(sort_cols).drop(columns="_o")
        return d

    normal_all = grouped(pd.concat(long["normal"], ignore_index=True)) if long["normal"] else pd.DataFrame()
    sens_all = grouped(pd.concat(long["sensitive"], ignore_index=True)) if long["sensitive"] else pd.DataFrame()

    outp = a.out if os.path.isabs(a.out) else os.path.join(root, a.out)
    with pd.ExcelWriter(outp, engine="openpyxl") as xl:
        photo_df.to_excel(xl, sheet_name="Summary (per replicate)", index=False)
        stats_df.to_excel(xl, sheet_name="Stats (per sample)", index=False)
        normal_all.to_excel(xl, sheet_name="Normal - all plaques", index=False)
        sens_all.to_excel(xl, sheet_name="Sensitive - all plaques", index=False)
    print("WROTE", outp)
    print("  photos:", len(photo_df), "| samples:", len(stats_df),
          "| normal plaques:", len(normal_all), "| sensitive plaques:", len(sens_all))


if __name__ == "__main__":
    main()
