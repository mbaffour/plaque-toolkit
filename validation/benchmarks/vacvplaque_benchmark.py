"""Assemble VACVPlaque per-well score CSVs (from app/validate.py) into one Markdown table.

Usage:
    python validation/benchmarks/vacvplaque_benchmark.py <results folder> [--out FILE.md]

<results folder> holds files named results_<variant>.csv, each being the `per_plate_df` that
app.validate.validate() returns (one row per well and mode). The table reports, per variant
and engine: wells scored, pooled TP/FP/FN, micro precision / recall / F1, the per-well
recall range, and the number of wells where no dish (well) was found. It also records the
toolkit commit and the digest of the detector weights, so the numbers are tied to code.
"""
import argparse
import glob
import hashlib
import os
import subprocess
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _git(*args):
    try:
        return subprocess.check_output(["git", "-C", ROOT] + list(args), text=True).strip()
    except Exception:
        return "?"


def _digest(path, n=16):
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()[:n]
    except Exception:
        return "?"


def summarise(csv_path):
    df = pd.read_csv(csv_path)
    df = df[df["error"].fillna("") == ""]
    rows = []
    for mode, sub in df.groupby("mode", sort=False):
        tp, fp, fn = sub["tp"].sum(), sub["fp"].sum(), sub["fn"].sum()
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * p * r / (p + r) if p + r else 0.0
        rec = pd.to_numeric(sub["recall"], errors="coerce")
        rows.append({"engine": mode, "wells": len(sub), "plaques": int(sub["n_gt"].sum()),
                     "TP": int(tp), "FP": int(fp), "FN": int(fn),
                     "precision": round(p, 3), "recall": round(r, 3), "F1": round(f1, 3),
                     "recall per well (min-max)": "%.2f-%.2f" % (rec.min(), rec.max()) if len(rec) else "",
                     "wells without dish": int(sub["size_mae_mm"].isna().sum())})
    return pd.DataFrame(rows)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("results_dir")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    files = sorted(glob.glob(os.path.join(a.results_dir, "results_*.csv")))
    if not files:
        raise SystemExit("no results_*.csv in %s" % a.results_dir)
    L = ["# VACVPlaque benchmark", "",
         "Toolkit commit `%s` (%s); PlaqSeg weights `small.pt` sha256 `%s`; classifier `plaque_clf.pt` sha256 `%s`."
         % (_git("rev-parse", "--short", "HEAD"), _git("branch", "--show-current"),
            _digest(os.path.join(ROOT, "_plaqseg", "models", "small.pt")),
            _digest(os.path.join(ROOT, "_research", "clf", "plaque_clf.pt"))),
         "", "Scored with `app/validate.py` (match radius = max(4 px, 0.5 x gold radius)); pooled metrics are",
         "micro-averages over wells. Variants: `x1` native scale, `x3` scale-normalised (well ~1,800 px),",
         "`gray` = scale-normalised grayscale.", ""]
    for f in files:
        variant = os.path.basename(f)[len("results_"):-4]
        L.append("## %s" % variant)
        L.append("")
        L.append(summarise(f).to_markdown(index=False))
        L.append("")
    text = "\n".join(L)
    if a.out:
        open(a.out, "w").write(text)
        print("wrote", a.out)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
