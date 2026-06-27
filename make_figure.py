"""Make a publication-quality violin figure of plaque size per sample, from a tidy CSV.

Input CSV (default 'plaque_data_tidy.csv') needs columns:
    SAMPLE, PLATE, MODE, DIAMETER_MM   (AREA_MM2, TURBIDITY_REL optional)
one row per plaque.

Each sample is drawn in its own colour. The pooled distribution is shown as a violin;
the black-edged white dots are the per-PLATE medians (n = replicate plates) so the
experimental-unit-level data is visible (plate is the experimental unit, not the plaque).

Usage:
    python make_figure.py                         # normal mode, diameter, y-capped at 2 mm
    python make_figure.py --mode sensitive
    python make_figure.py --metric AREA_MM2 --ymax 3 --out fig_area

Tweak the figure by editing the CONFIG block below (colours, order, fonts, size).
"""
import argparse, os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ---------------------------- CONFIG (edit me) ----------------------------- #
ORDER   = ["WT", "2-4", "DTR", "G12E", "I70T", "T65I", "T71A"]   # x-axis order
PALETTE = ["#E69F00", "#56B4E9", "#009E73", "#CC79A7", "#0072B2", "#D55E00", "#7F7F7F"]  # colour-blind safe
YLABELS = {"DIAMETER_MM": "Plaque diameter (mm)", "AREA_MM2": "Plaque area (mm$^2$)",
           "TURBIDITY_REL": "Turbidity index (within-plate, relative)",
           "MEAN_GRAY": "Mean grey inside plaque (0-255)",
           "AREA_PXL": "Plaque area (px)", "DIAMETER_PXL": "Plaque diameter (px)"}
SHOW_POINTS = True            # jittered individual plaque points on each violin
POINT_SIZE = 5
POINT_ALPHA = 0.25
POINT_COLOR = "black"         # set to "" to colour points by sample
SHOW_PLATE_MEDIANS = True     # white dots = per-plate medians (replicate-level)
SHOW_N = True                 # annotate n plaques under each violin
FONT = 12
# --------------------------------------------------------------------------- #


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=os.path.join("Plaques to measure", "plaque_data_tidy.csv"))
    ap.add_argument("--mode", default="normal", choices=["normal", "sensitive"])
    ap.add_argument("--metric", default="DIAMETER_MM")
    ap.add_argument("--ymax", type=float, default=2.0, help="y-axis cap (mm); set 0 to show all")
    ap.add_argument("--out", default=None, help="output basename (default: <mode>_<metric>_figure)")
    a = ap.parse_args()

    plt.rcParams.update({"font.size": FONT, "axes.linewidth": 1.0, "svg.fonttype": "none"})
    df = pd.read_csv(a.csv)
    if "MODE" in df.columns:                       # combined file -> pick the mode
        df = df[df["MODE"] == a.mode].copy()
    else:                                          # already a single-mode file (plot_data_<mode>.csv)
        df = df.copy()
    df[a.metric] = pd.to_numeric(df[a.metric], errors="coerce")
    df = df[df[a.metric] > 0]

    samples = [s for s in ORDER if s in set(df["SAMPLE"])]
    samples += [s for s in sorted(df["SAMPLE"].unique()) if s not in samples]

    fig, ax = plt.subplots(figsize=(1.15 * len(samples) + 1.5, 5.6))
    rng = np.random.default_rng(0)
    hidden = 0
    for i, s in enumerate(samples):
        vals = df.loc[df["SAMPLE"] == s, a.metric].values
        color = PALETTE[i % len(PALETTE)]
        vp = ax.violinplot(vals, positions=[i + 1], widths=0.82, showextrema=False)
        for b in vp["bodies"]:
            b.set_facecolor(color); b.set_edgecolor("black"); b.set_alpha(0.80); b.set_linewidth(0.8)
        # jittered individual plaque points
        if SHOW_POINTS:
            xj = (i + 1) + (rng.random(len(vals)) - 0.5) * 0.55
            ax.scatter(xj, vals, s=POINT_SIZE, color=(POINT_COLOR or color),
                       alpha=POINT_ALPHA, linewidths=0, zorder=3)
        # median + IQR
        q1, med, q3 = np.percentile(vals, [25, 50, 75])
        ax.vlines(i + 1, q1, q3, color="black", lw=4, zorder=4)
        ax.hlines(med, i + 1 - 0.28, i + 1 + 0.28, color="black", lw=2.2, zorder=5)
        # per-plate medians (experimental-unit level)
        if SHOW_PLATE_MEDIANS:
            pm = df[df["SAMPLE"] == s].groupby("PLATE")[a.metric].median().values
            ax.scatter(np.full(len(pm), i + 1), pm, s=42, facecolor="white",
                       edgecolor="black", linewidth=1.1, zorder=6)
        if SHOW_N:
            ax.annotate("n=%d" % len(vals), (i + 1, 0), xytext=(0, -22),
                        textcoords="offset points", ha="center", va="top", fontsize=9, color="#444")
        if a.ymax:
            hidden += int(np.sum(vals > a.ymax))

    ax.set_xticks(range(1, len(samples) + 1))
    ax.set_xticklabels(samples)
    ax.set_ylabel(YLABELS.get(a.metric, a.metric))
    ax.set_xlim(0.4, len(samples) + 0.6)
    ax.set_ylim(0, a.ymax if a.ymax else None)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(direction="out", length=4)
    ax.yaxis.grid(True, alpha=0.25, linewidth=0.7)
    ax.set_axisbelow(True)
    if a.ymax and hidden:
        ax.annotate("%d plaque(s) > %.1f mm not shown" % (hidden, a.ymax),
                    (1, 1), xytext=(-4, -4), xycoords="axes fraction",
                    textcoords="offset points", ha="right", va="top", fontsize=8, color="#888")
    fig.tight_layout()

    out = a.out or ("%s_%s_figure" % (a.mode, a.metric.lower()))
    out = out if os.path.isabs(out) else os.path.join(os.path.dirname(os.path.abspath(a.csv)) or ".", out)
    for ext in ("png", "pdf", "svg"):
        fig.savefig("%s.%s" % (out, ext), dpi=300, bbox_inches="tight")
    print("SAVED %s.(png|pdf|svg)  | %s mode | %d samples | %d plaques%s" %
          (out, a.mode, len(samples), len(df), ("  (%d hidden > %.1f mm)" % (hidden, a.ymax)) if hidden else ""))


if __name__ == "__main__":
    main()
