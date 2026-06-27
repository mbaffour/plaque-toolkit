"""Violin plot of plaque DIAMETER_MM per sample, pooled across each sample's replicate
plates, from the SENSITIVE-mode CSVs written by measure_samples.py.

Usage: python plot_sensitive_violin.py [--root "Plaques to measure"] [--mode sensitive] [--metric DIAMETER_MM]
"""
import argparse, os, glob
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# WT first (reference), then the variants
ORDER = ["WT", "2-4", "DTR", "G12E", "I70T", "T65I", "T71A"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="Plaques to measure")
    ap.add_argument("--mode", default="sensitive")
    ap.add_argument("--metric", default="DIAMETER_MM")
    a = ap.parse_args()
    root = a.root if os.path.isabs(a.root) else os.path.join(os.path.dirname(os.path.abspath(__file__)), a.root)

    data, labels, ns, n_plates, medians = [], [], [], [], []
    samples = [s for s in ORDER if os.path.isdir(os.path.join(root, s))]
    samples += [s for s in sorted(os.listdir(root))
                if os.path.isdir(os.path.join(root, s)) and s not in samples]

    pooled_rows = []
    for s in samples:
        vals, plates = [], 0
        for csvp in glob.glob(os.path.join(root, s, "*", "*_%s.csv" % a.mode)):
            try:
                df = pd.read_csv(csvp)
            except Exception:
                continue
            if a.metric not in df.columns:
                continue
            v = pd.to_numeric(df[a.metric], errors="coerce").dropna()
            v = v[v > 0]
            if len(v):
                vals.extend(v.tolist()); plates += 1
                for x in v.tolist():
                    pooled_rows.append({"sample": s, "plate": os.path.basename(os.path.dirname(csvp)), a.metric: x})
        if vals:
            data.append(np.array(vals)); labels.append(s); ns.append(len(vals))
            n_plates.append(plates); medians.append(float(np.median(vals)))

    # save the pooled long-format data too
    pd.DataFrame(pooled_rows).to_csv(os.path.join(root, "%s_%s_pooled.csv" % (a.mode, a.metric)), index=False)

    fig, ax = plt.subplots(figsize=(11, 6.2))
    pos = np.arange(1, len(data) + 1)
    vp = ax.violinplot(data, positions=pos, showmedians=True, showextrema=False, widths=0.85)
    for b in vp["bodies"]:
        b.set_facecolor("#4da3ff"); b.set_edgecolor("#1f4e79"); b.set_alpha(0.75)
    if "cmedians" in vp:
        vp["cmedians"].set_color("#10243a"); vp["cmedians"].set_linewidth(2)
    # light jittered points for transparency about the underlying data
    rng = np.random.default_rng(0)
    for i, d in enumerate(data):
        x = pos[i] + (rng.random(len(d)) - 0.5) * 0.12
        ax.scatter(x, d, s=3, color="#11335a", alpha=0.18, linewidths=0)
        ax.text(pos[i], -0.06, "n=%d\n(%d plates)\nmed %.2f" % (ns[i], n_plates[i], medians[i]),
                ha="center", va="top", fontsize=8, color="#445", transform=ax.get_xaxis_transform())

    ax.set_xticks(pos); ax.set_xticklabels(labels)
    ax.set_ylabel("Plaque diameter (mm)")
    ax.set_title("Plaque size by sample — %s mode (replicate plates pooled)" % a.mode.upper())
    ax.set_ylim(bottom=0)
    ax.margins(x=0.02)
    ax.grid(axis="y", alpha=0.25)
    note = ("Sensitive mode is the unvalidated high-recall setting (includes some false positives); "
            "plate is the experimental unit." if a.mode == "sensitive" else
            "Normal -small is the validated gate (drops sub-0.4 mm plaques); plate is the experimental unit.")
    ax.text(0.5, 1.06, note, transform=ax.transAxes, ha="center", va="bottom", fontsize=8, color="#a06010")
    fig.subplots_adjust(bottom=0.20, top=0.86)
    outp = os.path.join(root, "%s_diameter_violin.png" % a.mode)
    fig.savefig(outp, dpi=160)
    print("SAVED", outp)
    for lab, n, npl, med in zip(labels, ns, n_plates, medians):
        print("  %-6s n=%-5d plates=%d  median=%.3f mm" % (lab, n, npl, med))


if __name__ == "__main__":
    main()
