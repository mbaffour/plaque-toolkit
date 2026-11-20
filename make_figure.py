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
    python make_figure.py --legend-key            # also write <out>_legend_key.(png|pdf|svg) +
                                                  # <out>_legend_text.txt (colour key + text starter)
    python make_figure.py --key-on-figure         # draw the same key on the figure (outside right)

Tweak the figure by editing the CONFIG block below (colours, order, fonts, size).
"""
import argparse, os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt



def _legend_key_module():
    """The shared legend-key helper, imported the way plaque_turbidity does it (CT-R1 SM-F19):
    the package (repo checkout), else a flat legend_key.py on sys.path (pip-installed stats
    package, which also shadows the folder with a flat plaque_stats.py), else None -- then the
    figure is still drawn, only the key files are skipped."""
    try:
        from plaque_stats import legend_key as m
        m.entry                                          # a flat plaque_stats.py has no such module
        return m
    except Exception:                                    # noqa: BLE001
        try:
            import legend_key as m
            return m
        except Exception:                                # noqa: BLE001
            return None


legend_key = _legend_key_module()

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


SIZE_METRICS = ("DIAMETER_MM", "AREA_MM2", "DIAMETER_PXL", "AREA_PXL")


def _size_rows(df, metric):
    """Which rows may be plotted as a SIZE (CT-R2 detection N1), or None for all rows: tables
    without QC_FLAG and non-size metrics (turbidity) keep every row."""
    if metric not in SIZE_METRICS:
        return None
    try:
        import plaque_qc
    except Exception:                       # pragma: no cover - a standalone copy of this script
        return None
    return plaque_qc.sized_rows(df)


def sample_colours(samples):
    """The one sample -> colour mapping: the violins are drawn from it and the key built from it."""
    return {s: PALETTE[i % len(PALETTE)] for i, s in enumerate(samples)}


def figure_key(samples, colours):
    """Legend key: one entry per sample, styled exactly as its violin (and points, when the points
    are coloured by sample). Plate medians and black points carry no sample colour."""
    entries = []
    for s in samples:
        c = colours[s]
        em = (dict(marker="o", colour=c, edge="none", alpha=POINT_ALPHA, size=4.0)
              if (SHOW_POINTS and not POINT_COLOR) else None)
        entries.append(legend_key.entry(s, c, kind="patch", edge="black", alpha=0.80,
                                        linewidth=0.8, shape="violin", extra_marker=em))
    return legend_key.make_key(entries, fontsize=FONT - 2, frameon=False,
                               note="Violins: all plaques. Bar: median, whisker: IQR (25th to 75th "
                                    "percentile) of all plaques. White dots: plate medians.")


def main():
    global ORDER
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=os.path.join("Plaques to measure", "plaque_data_tidy.csv"))
    ap.add_argument("--mode", default="normal", choices=["normal", "sensitive"])
    ap.add_argument("--metric", default="DIAMETER_MM")
    ap.add_argument("--ymax", type=float, default=2.0, help="y-axis cap (mm); set 0 to show all")
    ap.add_argument("--out", default=None, help="output basename (default: <mode>_<metric>_figure)")
    ap.add_argument("--legend-key", action="store_true",
                    help="also write <out>_legend_key.(png|pdf|svg) and <out>_legend_text.txt")
    ap.add_argument("--key-on-figure", action="store_true",
                    help="draw the legend key on the figure, outside the top-right corner")
    ap.add_argument("--order", default=None, help="comma-separated sample order for the x-axis / sheet order, e.g. 'WT,2-4,DTR' (default: %s; samples not listed follow, sorted)" % ",".join(ORDER))
    a = ap.parse_args()
    if a.order:
        ORDER = [s.strip() for s in a.order.split(",") if s.strip()]

    plt.rcParams.update({"font.size": FONT, "axes.linewidth": 1.0, "svg.fonttype": "none"})
    df = pd.read_csv(a.csv)
    if "MODE" in df.columns:                       # combined file -> pick the mode
        df = df[df["MODE"] == a.mode].copy()
    else:                                          # already a single-mode file (plot_data_<mode>.csv)
        df = df.copy()
    df[a.metric] = pd.to_numeric(df[a.metric], errors="coerce")
    # CT-R2 detection N1: with a QC_FLAG column, plotted SIZES come only from plaque_qc.size_ok
    # rows (CORE? / NO_SIZE plaques count but their size is not this plate's edge definition)
    keep = _size_rows(df, a.metric)
    if keep is not None:
        n_all = len(df)
        df = df[keep]
        print("Sizes from %d of %d plaques (the rest are flagged CORE? / NO_SIZE in QC_FLAG)"
              % (len(df), n_all))
    df = df[df[a.metric] > 0]

    samples = [s for s in ORDER if s in set(df["SAMPLE"])]
    samples += [s for s in sorted(df["SAMPLE"].unique()) if s not in samples]

    fig, ax = plt.subplots(figsize=(1.15 * len(samples) + 1.5, 5.6))
    colours = sample_colours(samples)
    rng = np.random.default_rng(0)
    hidden = 0
    for i, s in enumerate(samples):
        vals = df.loc[df["SAMPLE"] == s, a.metric].values
        color = colours[s]
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
    key = legend_key.attach(fig, figure_key(samples, colours)) if legend_key else None
    if legend_key is None and (a.legend_key or a.key_on_figure):
        print("NOTE: the legend key helper (plaque_stats/legend_key.py) was not found, so the "
              "legend key was skipped; the figure is drawn as usual.")
    if a.key_on_figure and key:
        legend_key.embed(ax, key)
    fig.tight_layout()

    out = a.out or ("%s_%s_figure" % (a.mode, a.metric.lower()))
    out = out if os.path.isabs(out) else os.path.join(os.path.dirname(os.path.abspath(a.csv)) or ".", out)
    for ext in ("png", "pdf", "svg"):
        fig.savefig("%s.%s" % (out, ext), dpi=300, bbox_inches="tight")
    if a.legend_key and key:
        legend_key.write_key_files(key, out, ("png", "pdf", "svg"), dpi=300)
        print("SAVED %s_legend_key.(png|pdf|svg) + %s_legend_text.txt" % (out, out))
    print("SAVED %s.(png|pdf|svg)  | %s mode | %d samples | %d plaques%s" %
          (out, a.mode, len(samples), len(df), ("  (%d hidden > %.1f mm)" % (hidden, a.ymax)) if hidden else ""))


if __name__ == "__main__":
    main()
