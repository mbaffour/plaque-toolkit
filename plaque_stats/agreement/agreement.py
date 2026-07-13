#!/usr/bin/env python3
"""agreement.py — tool-vs-manual method-comparison statistics (standalone).

Compares paired measurements from an automated tool against a manual reference
(e.g. **Plaque Toolkit vs manual Fiji/ImageJ tracing**) and reports the standard
method-comparison statistics + a publication figure:

  * Pearson r
  * ICC(A,1) — two-way random effects, ABSOLUTE agreement (Koo & Li 2016)
  * Bland-Altman: mean bias, 95% limits of agreement, RMSE, % bias, MAE
  * proportional-bias check (least-squares slope of tool on reference; 1.0 = none)
  * a two-panel figure: method-comparison scatter (line of identity) + Bland-Altman
  * a stats CSV, a report.md with a paste-ready sentence + interpretation, run_config.json

The maths are vendored verbatim from the desktop app's `app/agreement.py` — the same
code that produced the toolkit's own validation (ICC 0.97) — so the numbers match.

INPUT: one row per item (plaque), two numeric columns = the two methods, e.g.
    id,toolkit_mm,manual_mm
    1,0.67,0.68
Columns are auto-detected (tool/toolkit/auto/precise vs manual/fiji/imagej/hand/reference)
or given explicitly with --tool / --manual.

Usage:
    python agreement.py data.csv --tool toolkit_mm --manual manual_mm --unit mm --out results
    python agreement.py --make-example        # write example_agreement.csv and exit
"""
from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
from matplotlib.figure import Figure
# keep text EDITABLE in SVG/PDF (Illustrator / Inkscape)
matplotlib.rcParams.update({"svg.fonttype": "none", "pdf.fonttype": 42, "ps.fonttype": 42})

__version__ = "1.0.0"


# =============================================================================
#  Vendored maths — copied verbatim from app/agreement.py (keep in sync)
# =============================================================================
def _mean(a):
    return sum(a) / len(a)


def _sd(a):
    if len(a) < 2:
        return 0.0
    m = _mean(a)
    return math.sqrt(sum((x - m) ** 2 for x in a) / (len(a) - 1))


def pearson(x, y):
    mx, my = _mean(x), _mean(y)
    num = sum((x[i] - mx) * (y[i] - my) for i in range(len(x)))
    dx = sum((v - mx) ** 2 for v in x)
    dy = sum((v - my) ** 2 for v in y)
    return num / math.sqrt(dx * dy) if dx > 0 and dy > 0 else float("nan")


def icc_a1(ref, test):
    """ICC(A,1): two-way random effects, absolute agreement, single measures."""
    n = len(ref)
    if n < 2:
        return float("nan")
    allv = []
    for i in range(n):
        allv += [ref[i], test[i]]
    grand = _mean(allv)
    k = 2
    ssr = k * sum(((ref[i] + test[i]) / 2 - grand) ** 2 for i in range(n))
    ssc = n * ((_mean(ref) - grand) ** 2 + (_mean(test) - grand) ** 2)
    sse = sum((v - grand) ** 2 for v in allv) - ssr - ssc
    msr = ssr / (n - 1)
    msc = ssc / (k - 1)
    mse = sse / ((n - 1) * (k - 1))
    denom = msr + (k - 1) * mse + (k / n) * (msc - mse)
    return (msr - mse) / denom if denom else float("nan")


def regress(x, y):
    """Least-squares y = slope*x + intercept."""
    mx, my = _mean(x), _mean(y)
    sxx = sum((v - mx) ** 2 for v in x)
    slope = (sum((x[i] - mx) * (y[i] - my) for i in range(len(x))) / sxx) if sxx else float("nan")
    return slope, my - slope * mx


def compute(tool, fiji):
    """`tool` = the method under test, `fiji` = the reference. Bias is tool - fiji.
    Returns a dict of agreement statistics (raises ValueError if < 3 pairs)."""
    n = min(len(tool), len(fiji))
    if n < 3:
        raise ValueError("need at least 3 paired values")
    tool, fiji = list(tool[:n]), list(fiji[:n])
    diff = [tool[i] - fiji[i] for i in range(n)]
    avg = [(tool[i] + fiji[i]) / 2 for i in range(n)]
    bias, sd = _mean(diff), _sd(diff)
    grand = _mean(avg)
    slope, intercept = regress(fiji, tool)
    return {
        "n": n, "mean_tool": _mean(tool), "mean_fiji": _mean(fiji),
        "bias": bias, "sd": sd, "loa_lo": bias - 1.96 * sd, "loa_hi": bias + 1.96 * sd,
        "rmse": math.sqrt(_mean([d * d for d in diff])),
        "pct_bias": (bias / grand * 100.0) if grand else float("nan"),
        "mae": _mean([abs(d) for d in diff]),
        "r": pearson(tool, fiji), "icc": icc_a1(fiji, tool),
        "slope": slope, "intercept": intercept, "diff": diff, "avg": avg,
        "tool": tool, "fiji": fiji,
    }


# =============================================================================
#  Interpretation, report, figure (parameterised labels)
# =============================================================================
def icc_grade(icc):
    """Koo & Li (2016) reliability bands."""
    if icc != icc:
        return "n/a"
    return ("poor" if icc < 0.5 else "moderate" if icc < 0.75
            else "good" if icc < 0.90 else "excellent")


def report_sentence(s, unit, what, label_tool, label_manual):
    return ("Plaque %s measured with %s agreed with %s (n = %d): Pearson r = %.2f, "
            "ICC(A,1) = %.2f (%s agreement). Bland-Altman analysis showed a mean bias of "
            "%+.3f %s (%.1f%%) with 95%% limits of agreement of %+.3f to %+.3f %s, and a "
            "regression slope of %.2f (1.0 = no proportional bias)."
            % (what, label_tool, label_manual, s["n"], s["r"], s["icc"], icc_grade(s["icc"]),
               s["bias"], unit, s["pct_bias"], s["loa_lo"], s["loa_hi"], unit, s["slope"]))


def make_figure(s, unit, label_tool, label_manual, title=None):
    """Two-panel method-comparison + Bland-Altman Figure (vendored from app/agreement.py)."""
    tool, fiji = s["tool"], s["fiji"]
    fig = Figure(figsize=(9.6, 4.6), layout="constrained")
    if title:
        fig.suptitle(title, fontsize=12, fontweight="bold")
    ax1, ax2 = fig.subplots(1, 2)
    TEAL, AMB, BLU, OUT = "#0e7d5b", "#b45309", "#3f5b8c", "#d1495b"
    diff = s["diff"]
    out = [d < s["loa_lo"] or d > s["loa_hi"] for d in diff]
    keep = lambda seq, flag: [seq[i] for i in range(len(seq)) if out[i] == flag]
    n_out = sum(out)

    lo, hi = min(tool + fiji), max(tool + fiji)
    pad = (hi - lo) * 0.06 or 0.1
    lim = [lo - pad, hi + pad]
    ax1.plot(lim, lim, "--", color="#9fb3ab", lw=1, zorder=1)
    ax1.scatter(keep(fiji, False), keep(tool, False), s=20, color=TEAL, alpha=.72,
                edgecolor="white", linewidth=.4, zorder=3, label="within limits")
    if n_out:
        ax1.scatter(keep(fiji, True), keep(tool, True), s=34, color=OUT, alpha=.95,
                    edgecolor="white", linewidth=.5, zorder=4, label="outside 95%% limits")
        ax1.legend(loc="lower right", fontsize=7.5, framealpha=.92)
    ax1.set_xlim(lim); ax1.set_ylim(lim); ax1.set_aspect("equal", "box")
    _tk = [t for t in ax1.get_xticks() if lim[0] <= t <= lim[1]]
    if _tk:
        ax1.set_xticks(_tk); ax1.set_yticks(_tk); ax1.set_xlim(lim); ax1.set_ylim(lim)
    ax1.set_xlabel("%s (%s)" % (label_manual, unit))
    ax1.set_ylabel("%s (%s)" % (label_tool, unit))
    ax1.set_title("A  Method comparison", loc="left", fontsize=10, fontweight="bold")
    ax1.text(.04, .96, "n=%d\nr=%.3f\nICC=%.3f" % (s["n"], s["r"], s["icc"]),
             transform=ax1.transAxes, va="top", ha="left", fontsize=8, family="monospace",
             bbox=dict(boxstyle="round,pad=0.3", fc="#f0f5f2", ec="#cfe0d8"))

    ax2.axhline(0, color="#c8d2ce", lw=.8)
    ax2.axhline(s["bias"], color=TEAL, lw=1.7, label="bias  %+.3f" % s["bias"])
    ax2.axhline(s["loa_hi"], color=AMB, lw=1.3, ls="--", label="+1.96 SD  %+.3f" % s["loa_hi"])
    ax2.axhline(s["loa_lo"], color=AMB, lw=1.3, ls="--", label="-1.96 SD  %+.3f" % s["loa_lo"])
    ax2.scatter(keep(s["avg"], False), keep(diff, False), s=20, color=BLU, alpha=.72,
                edgecolor="white", linewidth=.4, zorder=3)
    if n_out:
        ax2.scatter(keep(s["avg"], True), keep(diff, True), s=34, color=OUT, alpha=.95,
                    edgecolor="white", linewidth=.5, zorder=4)
    ax2.set_xlabel("Mean of the two methods (%s)" % unit)
    ax2.set_ylabel("%s - %s (%s)" % (label_tool, label_manual, unit))
    ax2.set_title("B  Bland-Altman", loc="left", fontsize=10, fontweight="bold")
    yspan = max(abs(s["loa_hi"]), abs(s["loa_lo"]), max(abs(d) for d in s["diff"])) * 1.15 or 0.1
    ax2.set_ylim(-yspan, yspan)
    ax2.legend(loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=3, frameon=False,
               fontsize=8, handlelength=1.6, columnspacing=1.4, prop={"family": "monospace"})
    return fig


# =============================================================================
#  I/O + CLI
# =============================================================================
TOOL_HINTS = ("tool", "toolkit", "auto", "precise", "software", "app", "detected")
MANUAL_HINTS = ("manual", "fiji", "imagej", "hand", "reference", "ref", "gt", "ground")


def _find_col(cols, hints):
    for c in cols:
        cl = str(c).lower()
        if any(h in cl for h in hints):
            return c
    return None


def _numeric_cols(df):
    return [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]


def _safe(s):
    return "".join(ch if ch.isalnum() else "_" for ch in str(s))


def run(args):
    df = pd.read_csv(args["data"], comment="#", skip_blank_lines=True) \
        if str(args["data"]).lower().endswith((".csv", ".tsv", ".txt")) \
        else pd.read_excel(args["data"])
    num = _numeric_cols(df)
    tcol = args.get("tool") or _find_col(df.columns, TOOL_HINTS)
    mcol = args.get("manual") or _find_col(df.columns, MANUAL_HINTS)
    if (tcol is None or mcol is None) and len(num) == 2:
        tcol, mcol = tcol or num[0], mcol or num[1]
        print("note: columns not named — using '%s' (tool) vs '%s' (manual). "
              "Override with --tool/--manual." % (tcol, mcol))
    if tcol is None or mcol is None:
        raise SystemExit("Could not identify the two columns. Pass --tool COL --manual COL. "
                         "Numeric columns found: %s" % num)

    d = df[[tcol, mcol]].apply(pd.to_numeric, errors="coerce").dropna()
    tool_vals, manual_vals = d[tcol].tolist(), d[mcol].tolist()
    s = compute(tool_vals, manual_vals)

    unit = args["unit"]; what = args["what"]
    lt, lm = args["label_tool"], args["label_manual"]
    out = args["out"]; os.makedirs(out, exist_ok=True)
    suf = _safe(what)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    # figure (multi-format, editable vectors)
    fig = make_figure(s, unit, lt, lm, title=args.get("title"))
    for fmt in args["formats"]:
        kw = {"pil_kwargs": {"compression": "tiff_lzw"}} if fmt == "tiff" else {}
        fig.savefig(os.path.join(out, "agreement_%s.%s" % (suf, fmt)), dpi=args["dpi"],
                    bbox_inches="tight", facecolor="white", **kw)

    # stats CSV (one row)
    row = {k: s[k] for k in ("n", "mean_tool", "mean_fiji", "bias", "sd", "loa_lo", "loa_hi",
                             "rmse", "pct_bias", "mae", "r", "icc", "slope", "intercept")}
    row["icc_grade"] = icc_grade(s["icc"])
    pd.DataFrame([row]).to_csv(os.path.join(out, "agreement_stats_%s.csv" % suf), index=False)

    # report + paste-ready sentence
    sent = report_sentence(s, unit, what, lt, lm)
    with open(os.path.join(out, "agreement_report_%s.md" % suf), "w", encoding="utf-8") as f:
        f.write("# Method-comparison report - %s\n\n_Generated %s | agreement.py v%s_\n\n"
                % (what, stamp, __version__))
        f.write("**%s vs %s**  (bias = %s - %s)\n\n" % (lt, lm, lt, lm))
        f.write("| statistic | value |\n|---|---|\n")
        f.write("| n pairs | %d |\n" % s["n"])
        f.write("| Pearson r | %.3f |\n" % s["r"])
        f.write("| ICC(A,1) | %.3f (%s) |\n" % (s["icc"], icc_grade(s["icc"])))
        f.write("| mean bias (%s) | %+.3f (%.1f%%) |\n" % (unit, s["bias"], s["pct_bias"]))
        f.write("| 95%% limits of agreement | %+.3f to %+.3f %s |\n" % (s["loa_lo"], s["loa_hi"], unit))
        f.write("| RMSE / MAE (%s) | %.3f / %.3f |\n" % (unit, s["rmse"], s["mae"]))
        f.write("| proportional-bias slope | %.3f (1.0 = none) |\n\n" % s["slope"])
        f.write("## Paste-ready sentence\n\n> %s\n\n" % sent)
        f.write("## How to read it\n\n"
                "- **ICC(A,1)** (Koo & Li 2016): <0.5 poor, 0.5-0.75 moderate, 0.75-0.90 good, "
                ">0.90 excellent.\n"
                "- **Bias** = the systematic offset (tool minus reference); state it, don't hide it.\n"
                "- **95%% limits of agreement** = the range within which ~95%% of differences fall - "
                "the practical measure of how interchangeable the methods are.\n"
                "- **Proportional-bias slope** near 1.0 means the disagreement does not grow with size.\n")
    print("[done] %s: n=%d  r=%.3f  ICC=%.3f  bias=%+.3f %s (%.1f%%)  LoA %+.3f..%+.3f  -> %s"
          % (what, s["n"], s["r"], s["icc"], s["bias"], unit, s["pct_bias"],
             s["loa_lo"], s["loa_hi"], out))

    json.dump({"data": args["data"], "tool_col": tcol, "manual_col": mcol, "unit": unit,
               "what": what, "stamp": stamp, "version": __version__,
               "numpy": np.__version__, "pandas": pd.__version__, "stats": row},
              open(os.path.join(out, "run_config_%s.json" % suf), "w"), indent=2, default=float)
    return s


def make_example(path):
    """Write a synthetic paired example (tool vs manual) with a small, realistic offset."""
    rng = np.random.default_rng(7)
    manual = np.clip(rng.lognormal(mean=0.05, sigma=0.42, size=120), 0.2, 3.2)   # ~1.1 mm plaques
    tool = manual * 0.982 + rng.normal(0, 0.055, manual.size)                    # ~ -1.8% bias
    tool = np.clip(tool, 0.05, None)
    pd.DataFrame({"plaque_id": np.arange(1, manual.size + 1),
                  "toolkit_mm": tool.round(3), "manual_mm": manual.round(3)}).to_csv(path, index=False)
    print("wrote", path)


def build_args():
    p = argparse.ArgumentParser(description="Tool-vs-manual method-comparison statistics.")
    p.add_argument("data", nargs="?", help="paired CSV/TSV/XLSX (one row per item, two method columns)")
    p.add_argument("--make-example", action="store_true", help="write example_agreement.csv and exit")
    p.add_argument("--tool", help="the automated/tool measurement column")
    p.add_argument("--manual", help="the manual/reference measurement column")
    p.add_argument("--unit", default="mm")
    p.add_argument("--what", default="diameters", help="what was measured (for labels/filenames)")
    p.add_argument("--label-tool", dest="label_tool", default="Plaque Toolkit")
    p.add_argument("--label-manual", dest="label_manual", default="Fiji / ImageJ")
    p.add_argument("--title", default=None)
    p.add_argument("--out", default="agreement_out")
    p.add_argument("--formats", default="png,svg,pdf")
    p.add_argument("--dpi", type=int, default=300)
    return p


def main(argv=None):
    ns = build_args().parse_args(argv)
    if ns.make_example:
        make_example(os.path.join(os.path.dirname(os.path.abspath(__file__)), "example_agreement.csv"))
        return
    if not ns.data:
        build_args().error("provide a DATA file (or --make-example).")
    args = vars(ns)
    args["formats"] = [x.strip() for x in ns.formats.split(",") if x.strip()]
    run(args)


if __name__ == "__main__":
    main()
