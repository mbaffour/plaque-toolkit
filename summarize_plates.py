"""Combine the per-plate `data-green-*.csv` files into one `summary.csv`
(one row per plate: plaque count + size stats). Aggregation only -- it does NOT
re-run detection, so it never changes any measurement.

Usage:
  python summarize_plates.py [-o OUT_FOLDER]      # default folder: out
"""
import argparse
import glob
import os

import pandas as pd

PREFIX, SUFFIX = "data-green-", ".csv"


def summarize(out_dir):
    rows = []
    for csv in sorted(glob.glob(os.path.join(out_dir, PREFIX + "*" + SUFFIX))):
        plate = os.path.basename(csv)[len(PREFIX):-len(SUFFIX)]
        d = pd.read_csv(csv)
        dm = pd.to_numeric(d.get("DIAMETER_MM"), errors="coerce").dropna()
        am = pd.to_numeric(d.get("AREA_MM2"), errors="coerce").dropna()
        rows.append({
            "PLATE": plate,
            "N_PLAQUES": len(d),
            "DIAM_MM_MEAN": round(dm.mean(), 3) if len(dm) else "",
            "DIAM_MM_MEDIAN": round(dm.median(), 3) if len(dm) else "",
            "DIAM_MM_MIN": round(dm.min(), 3) if len(dm) else "",
            "DIAM_MM_MAX": round(dm.max(), 3) if len(dm) else "",
            "AREA_MM2_MEAN": round(am.mean(), 4) if len(am) else "",
        })
    if not rows:
        print("No data-green-*.csv files found in", out_dir)
        return None
    df = pd.DataFrame(rows)
    out = os.path.join(out_dir, "summary.csv")
    df.to_csv(out, index=False)
    print(df.to_string(index=False))
    print(f"\nWrote {out}  ({len(df)} plates)")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Summarise per-plate plaque CSVs into one table")
    ap.add_argument("-o", "--out", default="out", help="folder holding data-green-*.csv (default: out)")
    summarize(ap.parse_args().out)
