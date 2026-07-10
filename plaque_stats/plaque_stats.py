#!/usr/bin/env python3
"""plaque_stats.py — publication-ready violin plots + statistics for grouped plaque measurements.

Reads a tidy CSV of measurements grouped by SAMPLE (and, ideally, by REPLICATE / plate), then:
  1. writes data summaries (per group and per replicate),
  2. computes group-comparison statistics that treat the PLATE as the experimental unit
     (avoiding pseudoreplication — the correct default for plaque data),
  3. draws a customizable, reproducible, publication-ready violin plot,
  4. writes a plain-language report + a machine-readable run_config.json for reproducibility.

Only dependencies: pandas, numpy, matplotlib, scipy.  (statsmodels is optional — used for a
linear mixed-effects model if installed.)

------------------------------------------------------------------------------------------------
INPUT DATA FORMAT  (tidy CSV — one row per plaque)
------------------------------------------------------------------------------------------------
LONG (recommended — one file can hold several metrics):
    group,replicate,metric,value
    T4,plate1,diameter_mm,2.34
    T4,plate1,diameter_mm,2.51
    T7,plate1,diameter_mm,1.80
WIDE (matches the app's per-plaque export — just add group/replicate columns):
    group,replicate,diameter_mm,area_mm2,turbidity
    T4,plate1,2.34,4.30,0.12
Columns:
  group      (REQUIRED) the sample/condition/phage you compare — the x-axis categories.
  replicate  (recommended) the plate / experimental-unit id — used so stats are per-plate.
  value      (LONG only) the number to analyse; pair with a `metric` column to hold many metrics.
  <numeric>  (WIDE) any numeric column (diameter_mm, area_mm2, turbidity, …) selectable with --value.

Usage:
    python plaque_stats.py DATA.csv --group group --value diameter_mm --replicate replicate --out results
    python plaque_stats.py DATA.csv --config my_config.json          # everything from a JSON config
    python plaque_stats.py --make-example                            # write example + template CSVs
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import PathPatch

import scipy
from scipy import stats as st

__version__ = "1.0.0"

# Okabe–Ito colour-blind-safe qualitative palette (the publication default, for the group violins)
OKABE_ITO = ["#0072B2", "#E69F00", "#009E73", "#CC79A7", "#56B4E9",
             "#D55E00", "#F0E442", "#999999", "#000000"]

# muted qualitative palette for REPLICATES (plates): SuperPlot points + plate-mean markers are
# coloured by plate, so plate-to-plate structure is visible (Lord et al. 2020; Kenny & Schoen 2021)
REP_PALETTE = ["#4C6E9C", "#E0A458", "#6AAA64", "#B65C5C", "#8A78B0",
               "#4FA3A5", "#C77CB5", "#9A8C6B", "#6C6C6C"]


def _darken(hexc, f=0.62):
    hexc = str(hexc).lstrip("#")
    if len(hexc) != 6:
        return "#33413c"
    r, g, b = (int(hexc[i:i + 2], 16) for i in (0, 2, 4))
    return "#%02x%02x%02x" % (int(r * f), int(g * f), int(b * f))

DEFAULTS = {
    "group": "group", "value": None, "replicate": "replicate", "metric": "metric",
    "unit": "auto",                # auto | replicate | plaque  (statistical unit)
    "order": None,                 # explicit group order (list) or None = as-they-appear
    "palette": OKABE_ITO,
    "title": None, "ylabel": None, "xlabel": "",
    "parametric": "auto",          # auto | parametric | nonparametric
    "annotate": "auto",            # auto | all | adjacent | none  (which pairs get brackets)
    "show_points": True, "show_box": True, "show_mean": True,
    "log_y": False, "width": 8.0, "height": 5.2, "dpi": 300,
    "point_size": 16.0, "jitter": 0.08, "violin_alpha": 0.55, "seed": 7,
    "formats": ["png", "svg", "pdf"], "theme": "clean", "legend": True, "violin_fill": "auto",
}


# --------------------------------------------------------------------------- I/O
def read_table(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xls"):
        return pd.read_excel(path)
    sep = "\t" if ext in (".tsv", ".txt") else ","
    return pd.read_csv(path, sep=sep, comment="#", skip_blank_lines=True)


def normalize(df, group, value, replicate, metric):
    """Return a tidy frame with columns: group, replicate, value (float) — long or wide input.
    `value` may be None in wide mode only if there is exactly one numeric column."""
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    cols = set(df.columns)
    if group not in cols:
        raise SystemExit(f"[error] group column {group!r} not found. Columns: {sorted(cols)}")

    long_mode = ("value" in cols) and (value in (None, "value"))
    if long_mode:
        vcol = "value"
        if metric in cols and value not in (None, "value") and value != "value":
            df = df[df[metric] == value]
    else:
        if value is None:
            numeric = [c for c in df.columns
                       if c not in (group, replicate, metric) and pd.api.types.is_numeric_dtype(df[c])]
            if len(numeric) != 1:
                raise SystemExit("[error] specify --value (one of: %s)" % ", ".join(numeric) if numeric
                                 else "[error] no numeric value column found")
            vcol = numeric[0]
        else:
            if value not in cols:
                raise SystemExit(f"[error] value column {value!r} not found. Columns: {sorted(cols)}")
            vcol = value

    out = pd.DataFrame({"group": df[group].astype(str).str.strip()})
    out["replicate"] = df[replicate].astype(str).str.strip() if replicate in cols else np.nan
    out["value"] = pd.to_numeric(df[vcol], errors="coerce")
    out = out.dropna(subset=["value"]).reset_index(drop=True)
    if out.empty:
        raise SystemExit("[error] no numeric values after parsing — check your columns.")
    return out, (value or vcol)


# --------------------------------------------------------------------- summaries
def _ci95(x):
    x = np.asarray(x, float)
    n = len(x)
    if n < 2:
        return (np.nan, np.nan)
    sem = st.sem(x)
    h = sem * st.t.ppf(0.975, n - 1)
    return (float(np.mean(x) - h), float(np.mean(x) + h))


def describe(values):
    x = np.asarray(values, float)
    n = len(x)
    lo, hi = _ci95(x)
    m = float(np.mean(x)) if n else np.nan
    sd = float(np.std(x, ddof=1)) if n > 1 else np.nan
    q1, q3 = (np.percentile(x, [25, 75]) if n else (np.nan, np.nan))
    return {
        "n": n, "mean": m, "sd": sd,
        "sem": float(st.sem(x)) if n > 1 else np.nan,
        "ci95_lo": lo, "ci95_hi": hi,
        "median": float(np.median(x)) if n else np.nan,
        "q1": float(q1), "q3": float(q3), "iqr": float(q3 - q1) if n else np.nan,
        "min": float(np.min(x)) if n else np.nan, "max": float(np.max(x)) if n else np.nan,
        "cv_pct": float(100 * sd / m) if (n > 1 and m) else np.nan,
    }


def group_summary(df, order):
    rows = []
    for g in order:
        d = describe(df.loc[df["group"] == g, "value"].values)
        d["group"] = g
        d["n_replicates"] = df.loc[df["group"] == g, "replicate"].nunique(dropna=True)
        rows.append(d)
    cols = ["group", "n", "n_replicates", "mean", "sd", "sem", "ci95_lo", "ci95_hi",
            "median", "q1", "q3", "iqr", "min", "max", "cv_pct"]
    return pd.DataFrame(rows)[cols]


def replicate_means(df):
    """Per-(group, replicate) mean value — the plate-level table used for correct stats."""
    if df["replicate"].isna().all():
        return None
    rm = (df.dropna(subset=["replicate"])
            .groupby(["group", "replicate"], as_index=False)
            .agg(value=("value", "mean"), n_plaques=("value", "size")))
    return rm


# ------------------------------------------------------------------- statistics
def stars(p):
    if p is None or (isinstance(p, float) and math.isnan(p)):
        return "ns"
    return "***" if p < 1e-3 else "**" if p < 1e-2 else "*" if p < 5e-2 else "ns"


def cohens_d(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return np.nan
    sp = math.sqrt(((na - 1) * np.var(a, ddof=1) + (nb - 1) * np.var(b, ddof=1)) / (na + nb - 2))
    return float((np.mean(a) - np.mean(b)) / sp) if sp else np.nan


def dunn(groups):
    """Dunn's post-hoc after Kruskal–Wallis, with tie correction; returns {(i,j): p_holm}."""
    labels = list(groups)
    allv = np.concatenate([np.asarray(groups[g], float) for g in labels])
    ranks = st.rankdata(allv)
    N = len(allv)
    idx, rbar, n = {}, {}, {}
    pos = 0
    for g in labels:
        k = len(groups[g])
        rr = ranks[pos:pos + k]
        idx[g] = rr; rbar[g] = rr.mean(); n[g] = k; pos += k
    _, counts = np.unique(allv, return_counts=True)
    ties = np.sum(counts ** 3 - counts)
    sigma2 = (N * (N + 1) / 12.0) - ties / (12.0 * (N - 1))
    raw = {}
    for a, b in itertools.combinations(labels, 2):
        se = math.sqrt(sigma2 * (1.0 / n[a] + 1.0 / n[b]))
        z = (rbar[a] - rbar[b]) / se if se else 0.0
        raw[(a, b)] = 2 * st.norm.sf(abs(z))
    return _holm(raw)


def pairwise_mwu(groups):
    raw = {}
    for a, b in itertools.combinations(groups, 2):
        try:
            raw[(a, b)] = float(st.mannwhitneyu(groups[a], groups[b], alternative="two-sided").pvalue)
        except ValueError:
            raw[(a, b)] = np.nan
    return _holm(raw)


def tukey(groups):
    labels = list(groups)
    res = st.tukey_hsd(*[np.asarray(groups[g], float) for g in labels])
    out = {}
    for i, j in itertools.combinations(range(len(labels)), 2):
        out[(labels[i], labels[j])] = float(res.pvalue[i, j])
    return out


def _holm(raw):
    items = [(k, v) for k, v in raw.items() if v == v]  # drop nan
    items.sort(key=lambda kv: kv[1])
    m = len(items)
    adj, prev = {}, 0.0
    for rank, (k, p) in enumerate(items):
        a = min(1.0, (m - rank) * p)
        a = max(a, prev); prev = a
        adj[k] = a
    for k, v in raw.items():
        adj.setdefault(k, v)
    return adj


def run_stats(df, order, unit, parametric):
    """Compute normality, an omnibus test, and pairwise post-hoc p-values on the chosen unit."""
    rm = replicate_means(df)
    have_rep = rm is not None and rm.groupby("group")["replicate"].nunique().min() >= 2
    if unit == "auto":
        unit = "replicate" if have_rep else "plaque"
    src = rm if (unit == "replicate" and rm is not None) else df
    groups = {g: src.loc[src["group"] == g, "value"].values for g in order}
    ns = {g: len(v) for g, v in groups.items()}

    # normality (Shapiro per group) + equal variance (Levene) to guide parametric vs not
    normal = {}
    for g, v in groups.items():
        normal[g] = float(st.shapiro(v).pvalue) if 3 <= len(v) <= 5000 else np.nan
    vals = [v for v in groups.values() if len(v) >= 2]
    levene_p = float(st.levene(*vals).pvalue) if len(vals) >= 2 else np.nan
    all_normal = all((p != p) or p > 0.05 for p in normal.values())
    if parametric == "auto":
        use_param = bool(all_normal and (levene_p != levene_p or levene_p > 0.05))
    else:
        use_param = (parametric == "parametric")

    k = len(order)
    omni = {"unit": unit, "n_per_group": ns, "levene_p": levene_p,
            "normality_p": normal, "parametric_used": use_param}
    if k == 2:
        a, b = groups[order[0]], groups[order[1]]
        omni["test"] = "Welch t-test" if use_param else "Mann–Whitney U"
        try:
            omni["p"] = float(st.ttest_ind(a, b, equal_var=False).pvalue) if use_param \
                else float(st.mannwhitneyu(a, b, alternative="two-sided").pvalue)
        except ValueError:
            omni["p"] = np.nan
        omni["effect"] = {"cohens_d": cohens_d(a, b)}
        posthoc = {(order[0], order[1]): omni["p"]}
    elif k > 2:
        gv = [groups[g] for g in order]
        if use_param:
            omni["test"] = "one-way ANOVA"
            omni["p"] = float(st.f_oneway(*gv).pvalue)
            posthoc = tukey(groups)
        else:
            omni["test"] = "Kruskal–Wallis"
            omni["p"] = float(st.kruskal(*gv).pvalue)
            posthoc = dunn(groups)
    else:
        omni["test"] = "n/a (need ≥2 groups)"; omni["p"] = np.nan; posthoc = {}
    return omni, posthoc, unit, have_rep


# ----------------------------------------------------------------------- plotting
def _style_axes(ax, opts):
    """Minimal, journal-style axes: only left + bottom spines, thin, tidy ticks."""
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_linewidth(0.9); ax.spines[s].set_color("#33413c")
    ax.tick_params(width=0.9, color="#33413c", length=4, labelsize=11)
    if opts.get("theme") == "grid":
        ax.yaxis.grid(True, color="#ececec", lw=0.8); ax.set_axisbelow(True)


def plot_violin(df, order, opts, metric_name, posthoc):
    """Violin SuperPlot (Lord et al. 2020; Kenny & Schoen 2021): soft group-coloured violins,
    plaque points and plate means coloured by plate, summary = mean ± SEM of the plate means.
    No boxes — the plate means ARE the summary. Falls back to violin + median/IQR with no replicates."""
    plt.rcParams.update({"svg.fonttype": "none", "pdf.fonttype": 42, "ps.fonttype": 42,
                         "font.size": 12, "font.family": "sans-serif", "axes.linewidth": 0.9})
    rng = np.random.default_rng(opts["seed"])
    fig, ax = plt.subplots(figsize=(opts["width"], opts["height"]))
    gpal = opts["palette"]
    rm = replicate_means(df)
    reps = sorted(df["replicate"].dropna().unique().tolist()) if rm is not None else []
    rcol = {r: REP_PALETTE[i % len(REP_PALETTE)] for i, r in enumerate(reps)}

    data = [df.loc[df["group"] == g, "value"].values for g in order]
    pos = np.arange(1, len(order) + 1)

    vfill = opts.get("violin_fill", "auto")
    neutral = (vfill == "neutral") or (vfill == "auto" and rm is not None)  # grey when points carry plate colour
    parts = ax.violinplot(data, positions=pos, showextrema=False, widths=0.80)
    for i, b in enumerate(parts["bodies"]):
        if neutral:
            b.set_facecolor("#b9c2bd"); b.set_edgecolor("#6f7b74"); b.set_alpha(0.38)
        else:
            c = gpal[i % len(gpal)]
            b.set_facecolor(c); b.set_edgecolor(_darken(c)); b.set_alpha(0.22)
        b.set_linewidth(0.9)
        verts = b.get_paths()[0].vertices                 # trim the violin to the data range
        verts[:, 1] = np.clip(verts[:, 1], float(np.min(data[i])), float(np.max(data[i])))

    for i, g in enumerate(order):
        v = data[i]; x0 = pos[i]; c = gpal[i % len(gpal)]
        sub = df[df["group"] == g]
        if rm is not None:                                # ---------- Violin SuperPlot ----------
            if opts["show_points"]:
                for r in reps:
                    vv = sub.loc[sub["replicate"] == r, "value"].values
                    if not len(vv):
                        continue
                    jx = x0 + rng.uniform(-opts["jitter"], opts["jitter"], size=len(vv))
                    ax.scatter(jx, vv, s=opts["point_size"], color=rcol[r], alpha=0.45,
                               edgecolor="none", zorder=3)
            gm = rm[rm["group"] == g]
            jx = (x0 + np.linspace(-0.05, 0.05, len(gm))) if len(gm) > 1 else np.array([float(x0)])
            ax.scatter(jx, gm["value"].values, s=opts["point_size"] * 5.5,
                       c=[rcol[r] for r in gm["replicate"]], edgecolor="#12211d",
                       linewidth=0.9, zorder=6)
            m = float(gm["value"].mean())
            sem = float(gm["value"].sem()) if len(gm) > 1 else 0.0
            ax.plot([x0 - 0.19, x0 + 0.19], [m, m], color="#12211d", lw=2.0,
                    solid_capstyle="round", zorder=7)
            if sem:
                ax.plot([x0, x0], [m - sem, m + sem], color="#12211d", lw=1.1, zorder=7)
        else:                                             # -------- no replicates: median/IQR --------
            if opts["show_points"]:
                jx = x0 + rng.uniform(-opts["jitter"], opts["jitter"], size=len(v))
                ax.scatter(jx, v, s=opts["point_size"], color=c, alpha=0.42, edgecolor="none", zorder=3)
            q1, med, q3 = np.percentile(v, [25, 50, 75])
            ax.plot([x0, x0], [q1, q3], color="#33413c", lw=1.4, zorder=5)
            ax.plot([x0 - 0.10, x0 + 0.10], [med, med], color="#12211d", lw=2.2, zorder=6)

    ax.set_xticks(pos); ax.set_xticklabels(order)
    ax.set_ylabel(opts["ylabel"] or metric_name, fontsize=13)
    if opts["xlabel"]:
        ax.set_xlabel(opts["xlabel"], fontsize=13)
    if opts["title"]:
        ax.set_title(opts["title"], fontsize=14, fontweight="bold", loc="left")
    if opts["log_y"]:
        ax.set_yscale("log")
    _style_axes(ax, opts)

    if rm is not None and opts.get("legend", True) and reps:
        from matplotlib.lines import Line2D
        handles = [Line2D([0], [0], marker="o", linestyle="none", markerfacecolor=rcol[r],
                          markeredgecolor="#12211d", markersize=7, label=str(r)) for r in reps]
        ax.legend(handles=handles, title="plate", frameon=False, fontsize=9, title_fontsize=9,
                  loc="upper left", bbox_to_anchor=(1.005, 1.0), handletextpad=0.3, borderaxespad=0.2)

    pairs = _pairs_to_annotate(order, posthoc, opts["annotate"])
    if pairs:
        ymax = max(np.max(v) for v in data); ymin = min(np.min(v) for v in data)
        span = (ymax - ymin) or 1.0; step = span * 0.085
        lvl = ymax + step * 0.7
        for (a, b) in pairs:
            i, j = order.index(a), order.index(b)
            x1, x2 = pos[i], pos[j]
            ax.plot([x1, x1, x2, x2], [lvl, lvl + step * 0.22, lvl + step * 0.22, lvl],
                    lw=1.0, color="#33413c")
            ax.text((x1 + x2) / 2, lvl + step * 0.24,
                    stars(posthoc.get((a, b), posthoc.get((b, a)))),
                    ha="center", va="bottom", fontsize=11)
            lvl += step
        ax.set_ylim(top=lvl + step)

    fig.tight_layout()
    return fig


def _pairs_to_annotate(order, posthoc, mode):
    if mode == "none" or not posthoc:
        return []
    allpairs = list(itertools.combinations(order, 2))
    if mode == "adjacent":
        cand = [(order[i], order[i + 1]) for i in range(len(order) - 1)]
    elif mode == "all":
        cand = allpairs
    else:  # auto: annotate significant pairs (fall back to adjacent if none significant)
        sig = [p for p in allpairs
               if (posthoc.get(p, posthoc.get((p[1], p[0]))) or 1) < 0.05]
        cand = sig or [(order[i], order[i + 1]) for i in range(len(order) - 1)]
    return cand


# --------------------------------------------------------------------- reporting
def write_report(path, metric, summ, rep_summ, omni, posthoc, unit, have_rep, args):
    L = []
    L.append(f"# Plaque statistics report — {metric}\n")
    L.append(f"_Generated {args['_stamp']} · plaque_stats v{__version__}_\n")
    L.append("## Group summary (per plaque)\n")
    L.append(_md(summ.round(4)))
    if rep_summ is not None:
        L.append("\n## Per-replicate (plate) means\n")
        L.append(_md(rep_summ.round(4)))
    L.append("\n## Group comparison\n")
    L.append(f"- **Statistical unit:** {unit}"
             + ("  _(per-plate means — avoids pseudoreplication)_" if unit == "replicate"
                else "  _(per-plaque — no replicate column, so plates are pooled;"
                     " treat with caution)_") + "\n")
    L.append(f"- **Omnibus test:** {omni['test']}, p = {_fmt_p(omni['p'])}"
             f" (parametric={omni['parametric_used']}, Levene p={_fmt_p(omni['levene_p'])})\n")
    if posthoc:
        L.append("\n**Pairwise (adjusted p):**\n")
        rows = [{"pair": f"{a} vs {b}", "p_adj": _fmt_p(p), "signif": stars(p)}
                for (a, b), p in posthoc.items()]
        L.append(_md(pd.DataFrame(rows)))
    # paste-ready sentence
    L.append("\n## Paste-ready sentence\n")

    def _n(row):
        s = "n=%d" % int(row["n"])
        return s + (", %d plates" % int(row["n_replicates"]) if have_rep else " plaques")

    if len(summ) == 2:
        g1, g2 = summ.iloc[0], summ.iloc[1]
        d_txt = ""
        d_val = omni.get("effect", {}).get("cohens_d")
        if d_val is not None and d_val == d_val:
            d_txt = ", Cohen's d = %.2f" % d_val
        L.append("> %s in %s was %.2f ± %.2f (%s) vs %s %.2f ± %.2f (%s); %s p = %s%s."
                 % (metric, g1["group"], g1["mean"], g1["sd"], _n(g1),
                    g2["group"], g2["mean"], g2["sd"], _n(g2),
                    omni["test"], _fmt_p(omni["p"]), d_txt))
    else:
        L.append("> %s across %d groups: p = %s (statistical unit: %s; pairwise adjusted with "
                 "Holm/Tukey). Values are mean ± SD; the plate is the experimental unit."
                 % (omni["test"], len(summ), _fmt_p(omni["p"]), unit))
    open(path, "w", encoding="utf-8").write("\n".join(L) + "\n")


def _md(df):
    try:
        return df.to_markdown(index=False)
    except Exception:
        return "```\n" + df.to_string(index=False) + "\n```"


def _fmt_p(p):
    if p is None or (isinstance(p, float) and math.isnan(p)):
        return "n/a"
    return "< 0.001" if p < 1e-3 else f"{p:.3f}"


# ----------------------------------------------------------------------- example
def make_example(folder):
    """Write example_data_long.csv, example_data_wide.csv and TEMPLATE.csv (reproducible)."""
    rng = np.random.default_rng(42)
    os.makedirs(folder, exist_ok=True)
    rows = []
    truth = {"T4": 2.6, "T7": 1.9, "lambda": 3.1}     # mean diameter per phage (mm)
    for phage, mu in truth.items():
        for pl in range(1, 4):                        # 3 plates each
            plate_shift = rng.normal(0, 0.12)         # plate-to-plate variation (real biology)
            for _ in range(rng.integers(18, 32)):     # plaques per plate
                d = max(0.2, rng.normal(mu + plate_shift, 0.35))
                area = math.pi * (d / 2) ** 2
                turb = float(np.clip(rng.normal(0.35 if phage != "T7" else 0.6, 0.12), 0, 1))
                rows.append((phage, f"plate{pl}", round(d, 3), round(area, 3), round(turb, 3)))
    wide = pd.DataFrame(rows, columns=["group", "replicate", "diameter_mm", "area_mm2", "turbidity"])
    wide.to_csv(os.path.join(folder, "example_data_wide.csv"), index=False)
    long = wide.melt(id_vars=["group", "replicate"], var_name="metric", value_name="value")
    long.to_csv(os.path.join(folder, "example_data_long.csv"), index=False)
    tmpl = pd.DataFrame({"group": ["SampleA", "SampleA", "SampleB"],
                         "replicate": ["plate1", "plate1", "plate1"],
                         "diameter_mm": [2.30, 2.55, 1.80],
                         "area_mm2": [4.15, 5.11, 2.54],
                         "turbidity": [0.20, 0.15, 0.62]})
    tmpl.to_csv(os.path.join(folder, "TEMPLATE.csv"), index=False)
    print("wrote example_data_long.csv, example_data_wide.csv, TEMPLATE.csv ->", os.path.abspath(folder))


# --------------------------------------------------------------------------- main
def run(args):
    df, metric = normalize(read_table(args["data"]), args["group"], args["value"],
                           args["replicate"], args["metric"])
    order = args["order"] or list(dict.fromkeys(df["group"]))
    order = [g for g in order if g in set(df["group"])]
    out = args["out"]; os.makedirs(out, exist_ok=True)

    summ = group_summary(df, order)
    rep = replicate_means(df)
    summ.to_csv(os.path.join(out, "summary_by_group.csv"), index=False)
    if rep is not None:
        rep.to_csv(os.path.join(out, "summary_by_replicate.csv"), index=False)

    omni, posthoc, unit, have_rep = run_stats(df, order, args["unit"], args["parametric"])
    tests = pd.DataFrame([{"test": omni["test"], "unit": unit, "p": omni["p"],
                           "parametric": omni["parametric_used"], "levene_p": omni["levene_p"]}])
    tests.to_csv(os.path.join(out, "omnibus_test.csv"), index=False)
    if posthoc:
        pd.DataFrame([{"group_a": a, "group_b": b, "p_adj": p, "signif": stars(p)}
                      for (a, b), p in posthoc.items()]).to_csv(
            os.path.join(out, "pairwise_tests.csv"), index=False)

    fig = plot_violin(df, order, args, metric, posthoc)
    base = os.path.join(out, f"violin_{_safe(metric)}")
    for fmt in args["formats"]:
        kw = {"dpi": args["dpi"], "bbox_inches": "tight", "facecolor": "white"}
        if fmt in ("tif", "tiff"):
            kw["pil_kwargs"] = {"compression": "tiff_lzw"}
        fig.savefig(f"{base}.{fmt}", **kw)
    plt.close(fig)

    write_report(os.path.join(out, "report.md"), metric, summ, rep, omni, posthoc, unit, have_rep, args)
    prov = {k: v for k, v in args.items() if not k.startswith("_")}
    prov.update({"metric": metric, "groups": order, "unit": unit,
                 "versions": {"plaque_stats": __version__, "numpy": np.__version__,
                              "pandas": pd.__version__, "scipy": scipy.__version__}})
    with open(os.path.join(out, "run_config.json"), "w") as fh:
        json.dump(prov, fh, indent=2)
    print(f"[done] {metric}: {omni['test']} p={_fmt_p(omni['p'])} (unit={unit}) -> {os.path.abspath(out)}")


def _safe(s):
    return "".join(c if c.isalnum() else "_" for c in str(s))


def build_args():
    p = argparse.ArgumentParser(description="Publication-ready violin plots + stats for plaque data.")
    p.add_argument("data", nargs="?", help="input CSV/TSV/XLSX (tidy — see the header of this file)")
    p.add_argument("--config", help="JSON config file (overrides defaults; CLI flags override it)")
    p.add_argument("--make-example", action="store_true", help="write example + template CSVs and exit")
    p.add_argument("--group"); p.add_argument("--value"); p.add_argument("--replicate")
    p.add_argument("--metric"); p.add_argument("--out", default="plaque_stats_out")
    p.add_argument("--unit", choices=["auto", "replicate", "plaque"])
    p.add_argument("--parametric", choices=["auto", "parametric", "nonparametric"])
    p.add_argument("--annotate", choices=["auto", "all", "adjacent", "none"])
    p.add_argument("--violin-fill", dest="violin_fill", choices=["auto", "group", "neutral"])
    p.add_argument("--order", help="comma-separated group order")
    p.add_argument("--palette", help="comma-separated hex colours")
    p.add_argument("--title"); p.add_argument("--ylabel"); p.add_argument("--xlabel")
    p.add_argument("--formats", help="comma-separated: png,svg,pdf,tiff")
    p.add_argument("--width", type=float); p.add_argument("--height", type=float)
    p.add_argument("--dpi", type=int); p.add_argument("--seed", type=int)
    p.add_argument("--log-y", dest="log_y", action="store_true")
    p.add_argument("--no-points", dest="show_points", action="store_false")
    p.add_argument("--no-box", dest="show_box", action="store_false")
    p.add_argument("--theme", choices=["clean", "grid"])
    return p


def main(argv=None):
    ns = build_args().parse_args(argv)
    if ns.make_example:
        make_example(os.path.dirname(os.path.abspath(__file__)))
        return
    if not ns.data:
        build_args().error("provide a DATA file (or --make-example). See the file header for the format.")

    args = dict(DEFAULTS)
    if ns.config:
        args.update(json.load(open(ns.config)))
    for k, v in vars(ns).items():
        if v is not None and k not in ("config", "make_example"):
            args[k] = v
    for listy in ("order", "palette", "formats"):
        if isinstance(args.get(listy), str):
            args[listy] = [x.strip() for x in args[listy].split(",") if x.strip()]
    args["data"] = ns.data
    args["_stamp"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    run(args)


if __name__ == "__main__":
    main()
