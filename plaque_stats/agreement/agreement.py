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
import re
from datetime import datetime

import numpy as np
import pandas as pd
from scipy import stats as scstats

import matplotlib
matplotlib.use("Agg")
from matplotlib.figure import Figure
# keep text EDITABLE in SVG/PDF (Illustrator / Inkscape)
matplotlib.rcParams.update({"svg.fonttype": "none", "pdf.fonttype": 42, "ps.fonttype": 42})

__version__ = "1.0.0"


# >>> SHARED AGREEMENT CORE >>>
# Everything between the two SHARED markers is IDENTICAL in app/agreement.py (desktop tab) and
# plaque_stats/agreement/agreement.py (CLI + web app); tests/test_ct_r1_agreement_validate.py
# compares the two copies text-for-text. Edit one, paste into the other.
# (The two packages are frozen separately, so one cannot import the other.)
def _mean(a):
    return sum(a) / len(a)


def _sd(a):
    if len(a) < 2:
        return 0.0
    m = _mean(a)
    return math.sqrt(sum((x - m) ** 2 for x in a) / (len(a) - 1))


def _finite(v):
    try:
        return v is not None and math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


def pearson(x, y):
    mx, my = _mean(x), _mean(y)
    num = sum((x[i] - mx) * (y[i] - my) for i in range(len(x)))
    dx = sum((v - mx) ** 2 for v in x)
    dy = sum((v - my) ** 2 for v in y)
    return num / math.sqrt(dx * dy) if dx > 0 and dy > 0 else float("nan")


def _icc_ms(ref, test):
    """Two-way ANOVA mean squares (MSR rows/plaques, MSC columns/methods, MSE residual)."""
    n, k = len(ref), 2
    allv = []
    for i in range(n):
        allv += [ref[i], test[i]]
    grand = _mean(allv)
    ssr = k * sum(((ref[i] + test[i]) / 2 - grand) ** 2 for i in range(n))
    ssc = n * ((_mean(ref) - grand) ** 2 + (_mean(test) - grand) ** 2)
    sse = sum((v - grand) ** 2 for v in allv) - ssr - ssc
    return ssr / (n - 1), ssc / (k - 1), sse / ((n - 1) * (k - 1))


def icc_a1(ref, test):
    """ICC(A,1): two-way random effects, absolute agreement, single measures."""
    n = len(ref)
    if n < 2:
        return float("nan")
    k = 2
    msr, msc, mse = _icc_ms(ref, test)
    denom = msr + (k - 1) * mse + (k / n) * (msc - mse)
    return (msr - mse) / denom if denom else float("nan")


ICC_CI_MIN_N = 5           # below this no interval is reported ("n too small for an interval")


def icc_ci(tool, fiji, n_boot=None, seed=None):
    """95% CI of ICC(A,1) by the exact F interval of McGraw & Wong (1996), Table 7, case 2A
    (two-way, absolute agreement, single measure). CT-R1 SM-F15: replaces the percentile
    bootstrap, whose coverage was 0.83-0.90 at n = 5-10. ``n_boot``/``seed`` are accepted
    and ignored (old callers). Returns (nan, nan) below n = 5 or when undefined."""
    n, k = len(tool), 2
    if n < ICC_CI_MIN_N or n != len(fiji):
        return float("nan"), float("nan")
    ref, test = [float(v) for v in fiji], [float(v) for v in tool]
    msr, msc, mse = _icc_ms(ref, test)
    icc = icc_a1(ref, test)
    if not _finite(icc) or icc >= 1.0 or mse <= 0:
        return float("nan"), float("nan")
    from scipy import stats as _st
    a = k * icc / (n * (1 - icc))
    b = 1 + k * icc * (n - 1) / (n * (1 - icc))
    v = (a * msc + b * mse) ** 2 / ((a * msc) ** 2 / (k - 1) + (b * mse) ** 2 / ((n - 1) * (k - 1)))
    fl = float(_st.f.ppf(0.975, n - 1, v))
    fu = float(_st.f.ppf(0.975, v, n - 1))
    lo = n * (msr - fl * mse) / (fl * (k * msc + (k * n - k - n) * mse) + n * msr)
    hi = n * (fu * msr - mse) / (k * msc + (k * n - k - n) * mse + n * fu * msr)
    return float(lo), float(hi)


def _ba_slope(avg, diff):
    """(slope, p) of diff ~ avg (Bland-Altman proportional bias); p from the t-test on the
    slope (n - 2 df)."""
    n = len(avg)
    if n < 3:
        return float("nan"), float("nan")
    mx, my = _mean(avg), _mean(diff)
    sxx = sum((a - mx) ** 2 for a in avg)
    if sxx == 0:
        return float("nan"), float("nan")
    slope = sum((a - mx) * (d - my) for a, d in zip(avg, diff)) / sxx
    intercept = my - slope * mx
    resid = [d - (intercept + slope * a) for a, d in zip(avg, diff)]
    se = math.sqrt(sum(r * r for r in resid) / (n - 2) / sxx)
    if not se or se != se:
        return slope, float("nan")
    from scipy import stats as _st
    return slope, float(2 * _st.t.sf(abs(slope / se), n - 2))


LOA_LARGE_N = 20           # from here on the limits are bias +/- 1.96 SD


def loa_multiplier(n):
    """Multiplier k of the limits of agreement bias +/- k*SD. CT-R1 SM-F16: below 20 pairs
    +/-1.96 SD holds only 77-85 % of new differences, so the limits become the 95 % prediction
    interval t(0.975, n-1) * sqrt(1 + 1/n); from 20 pairs on they stay bias +/- 1.96 SD."""
    if n >= LOA_LARGE_N:
        return 1.96
    from scipy import stats as _st
    return float(_st.t.ppf(0.975, n - 1)) * math.sqrt(1.0 + 1.0 / n)


def _loa_ci_halfwidth(sd, n, k=1.96):
    """Half-width of the 95% CI of each limit of agreement, Bland & Altman (1999) exact form:
    SE(limit) = SD * sqrt(1/n + k^2 / (2(n-1))), times t(0.975, n-1). (k = the limit multiplier.)"""
    if n < 3 or not _finite(sd):
        return float("nan")
    from scipy import stats as _st
    return float(_st.t.ppf(0.975, n - 1)) * sd * math.sqrt(1.0 / n + k * k / (2.0 * (n - 1)))


def regress(x, y):
    """Least-squares y = slope*x + intercept."""
    mx, my = _mean(x), _mean(y)
    sxx = sum((v - mx) ** 2 for v in x)
    slope = (sum((x[i] - mx) * (y[i] - my) for i in range(len(x))) / sxx) if sxx else float("nan")
    return slope, my - slope * mx


def check_pairs(tool, fiji):
    """Plain-language refusal BEFORE any statistic is computed (CT-R1 SM-F17): too few pairs,
    unequal lengths, non-numbers, identical columns, or a column with no spread."""
    if len(tool) != len(fiji):
        raise ValueError("The two methods have different numbers of values (%d vs %d); each "
                         "plaque needs one value from each method." % (len(tool), len(fiji)))
    if len(tool) < 3:
        raise ValueError("Need at least 3 paired values (got %d)." % len(tool))
    for name, seq in (("tool", tool), ("reference", fiji)):
        for i, v in enumerate(seq, start=1):
            if not _finite(v):
                raise ValueError("Value %d of the %s column is not a number (%r)." % (i, name, v))
    if all(float(a) == float(b) for a, b in zip(tool, fiji)):
        raise ValueError("The two columns are identical (every difference is 0), so there is "
                         "nothing to compare. Check that the two columns hold the two methods.")
    for name, seq in (("tool", tool), ("reference", fiji)):
        if max(seq) == min(seq):
            raise ValueError("Every %s value is the same (%g), so r and the ICC cannot be "
                             "computed. Agreement needs plaques of different sizes." % (name, seq[0]))


def compute(tool, fiji):
    """`tool` = the method under test, `fiji` = the reference. Bias is tool - fiji.
    Returns a dict of agreement statistics; raises ValueError (plain message) on input that
    cannot be compared (see check_pairs)."""
    tool, fiji = [float(v) for v in tool], [float(v) for v in fiji]
    check_pairs(tool, fiji)
    n = len(tool)
    diff = [tool[i] - fiji[i] for i in range(n)]
    avg = [(tool[i] + fiji[i]) / 2 for i in range(n)]
    bias, sd = _mean(diff), _sd(diff)
    grand = _mean(avg)
    slope, intercept = regress(fiji, tool)
    k = loa_multiplier(n)
    ba_slope, ba_p = _ba_slope(avg, diff)
    return {
        "n": n, "mean_tool": _mean(tool), "mean_fiji": _mean(fiji),
        "bias": bias, "sd": sd, "loa_lo": bias - k * sd, "loa_hi": bias + k * sd,
        "loa_mult": k, "loa_method": "1.96 SD" if n >= LOA_LARGE_N else "t prediction",
        "rmse": math.sqrt(_mean([d * d for d in diff])),
        "pct_bias": (bias / grand * 100.0) if grand else float("nan"),
        "mae": _mean([abs(d) for d in diff]),
        "r": pearson(tool, fiji), "icc": icc_a1(fiji, tool),
        "slope": slope, "intercept": intercept, "diff": diff, "avg": avg,
        "tool": tool, "fiji": fiji,
        # Bland-Altman proportional bias: regress the difference on the mean of the two
        # methods; a non-zero slope means the bias changes with plaque size (PT-46).
        "ba_slope": ba_slope, "ba_slope_p": ba_p,
        # 95% CI of each limit of agreement (Bland & Altman 1999, exact form).
        "loa_ci_halfwidth": _loa_ci_halfwidth(sd, n, k),
    }


def ccc(x, y):
    """Lin's concordance correlation coefficient (accuracy AND precision)."""
    import numpy as _np
    x = _np.asarray(x, float); y = _np.asarray(y, float)
    mx, my = x.mean(), y.mean()
    vx, vy = x.var(), y.var()            # population variances (Lin 1989)
    cov = ((x - mx) * (y - my)).mean()
    denom = vx + vy + (mx - my) ** 2
    return float(2 * cov / denom) if denom else float("nan")


def extra_stats(tool, fiji, seed=None):
    """scipy-backed additions to compute(): R^2, Pearson p, paired t-test, CCC, ICC CI."""
    import warnings
    from scipy import stats as _st
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        r, rp = _st.pearsonr(tool, fiji)
        t, tp = _st.ttest_rel(tool, fiji)
    lo, hi = icc_ci(tool, fiji)
    return {"r2": float(r * r), "pearson_p": float(rp),
            "t_stat": float(t), "t_p": float(tp),
            "ccc": ccc(tool, fiji), "icc_lo": lo, "icc_hi": hi}


def full_stats(tool, fiji):
    """compute() + extra_stats(): everything the report sentence and the figure use."""
    s = compute(tool, fiji)
    s.update(extra_stats(s["tool"], s["fiji"]))
    return s


def _pfmt(p):
    if not _finite(p):
        return "not testable"
    return "< 0.001" if p < 0.001 else ("%.3f" % p)


def _pstr(p):
    """p-value WITH its operator, for inline use: 'p < 0.001' / 'p = 0.034' / 'p not testable'."""
    if not _finite(p):
        return "p not testable"
    return "p < 0.001" if p < 0.001 else "p = %.3f" % p


def icc_grade(icc):
    """Koo & Li (2016) reliability bands."""
    if icc != icc:
        return "n/a"
    return ("poor" if icc < 0.5 else "moderate" if icc < 0.75
            else "good" if icc < 0.90 else "excellent")


# --- Honest wording bands (PT-4) ------------------------------------------- #
# The adjectives in the "paste-ready" sentence are derived from the statistics they describe
# (a committed artefact once read "closely agreed ... ICC(A,1) = -0.012 (poor agreement)").
def agreement_phrase(icc):
    """Verb phrase for the ICC(A,1) band (Koo & Li 2016). Matches icc_grade()."""
    if icc != icc:
        return "could not be compared with"
    if icc < 0.5:
        return "did NOT agree at the individual level with"
    if icc < 0.75:
        return "agreed only moderately with"
    if icc < 0.90:
        return "agreed well with"
    return "agreed closely with"


def correlation_phrase(r, p=float("nan")):
    """Describe the correlation by strength, direction and significance."""
    if r != r:
        return "not correlated (undefined)"
    if p == p and p >= 0.05:
        return "not significantly correlated"
    a = abs(r)
    if a < 0.30:
        strength = "essentially uncorrelated"
    elif a < 0.50:
        strength = "weakly correlated"
    elif a < 0.70:
        strength = "moderately correlated"
    elif a < 0.90:
        strength = "strongly correlated"
    else:
        strength = "very strongly correlated"
    if r < 0 and a >= 0.30:
        strength = "INVERSELY " + strength
    return strength


SMALL_N = 10               # below this the sentence says the estimates rest on few pairs


def report_sentence(s, unit="mm", what="diameters", label_tool="Plaque Toolkit",
                    label_manual="Fiji / ImageJ"):
    """THE paste-ready sentence (desktop tab, CLI report and web app all call this one).

    Adjectives follow the statistics; a statistic missing from ``s`` leaves its clause out,
    and a p-value that is NaN reads "not testable" (never "significantly different ... p = nan").
    r and ICC are given to three decimals; below 10 pairs the wording is softened."""
    nan = float("nan")
    n = int(s["n"])
    icc, r = s.get("icc", nan), s.get("r", nan)
    phrase = agreement_phrase(icc)
    what = str(what).strip() or "measurements"
    lead = what[:1].upper() + what[1:]
    if n < SMALL_N:
        phrase = phrase.replace("did NOT agree", "did NOT appear to agree") \
                       .replace("agreed", "appeared to agree")
        lead = "With only %d pairs (too few for precise estimates), %s" % (n, what)
    out = "%s measured with %s %s %s (n = %d)" % (lead, label_tool, phrase, label_manual, n)
    # correlation
    if _finite(r):
        p = s.get("pearson_p")
        corr = "Pearson r = %.3f, R² = %.3f" % (r, s.get("r2", r * r))
        if "pearson_p" in s:
            corr += ", " + _pstr(p)
        out += ": %s (%s)" % (correlation_phrase(r, p if p is not None else nan), corr)
    else:
        out += ": Pearson r could not be computed"
    # ICC (+ CI) and CCC
    if _finite(icc):
        if _finite(s.get("icc_lo")) and _finite(s.get("icc_hi")):
            ci = " (95%% CI %.3f-%.3f)" % (s["icc_lo"], s["icc_hi"])
        elif "icc_lo" in s and n < ICC_CI_MIN_N:
            ci = " (n too small for an interval)"
        else:
            ci = ""
        out += ", with an intraclass correlation coefficient ICC(A,1) = %.3f%s (%s agreement)" \
               % (icc, ci, icc_grade(icc))
        if _finite(s.get("ccc")):
            out += " and Lin's concordance correlation CCC = %.3f" % s["ccc"]
    out += "."
    # Bland-Altman bias
    bits = []
    if _finite(s.get("pct_bias")):
        bits.append("%.1f%%" % s["pct_bias"])
    if "t_p" in s:
        tp = s["t_p"]
        if _finite(tp):
            bits.append("%s, paired t-test %s" % ("significantly different from zero" if tp < 0.05
                                                  else "not significantly different from zero",
                                                  _pstr(tp)))
        else:
            bits.append("difference from zero not testable")
    out += " Bland-Altman analysis showed a mean bias of %+.3f %s%s" \
           % (s["bias"], unit, (" (%s)" % "; ".join(bits)) if bits else "")
    loa = "with 95%% limits of agreement of %+.3f to %+.3f %s" % (s["loa_lo"], s["loa_hi"], unit)
    extra = []
    if _finite(s.get("loa_ci_halfwidth")):
        extra.append("each limit ±%.3f %s, 95%% CI" % (s["loa_ci_halfwidth"], unit))
    if s.get("loa_method") == "t prediction":
        extra.append("t-based prediction limits, as n < %d" % LOA_LARGE_N)
    if extra:
        loa += " (%s)" % "; ".join(extra)
    out += " " + loa
    if _finite(s.get("slope")):
        out += ", and a regression slope of %.2f (1.0 = no proportional bias)" % s["slope"]
    out += "."
    bs, bp = s.get("ba_slope", nan), s.get("ba_slope_p", nan)
    if _finite(bs) and _finite(bp):
        if bp < 0.05:
            out += (" The difference depended on plaque size (Bland-Altman slope %+.3f %s per %s, %s): "
                    "a proportional bias, so a single bias value does not describe the whole range."
                    % (bs, unit, unit, _pstr(bp)))
        else:
            out += (" The difference did not depend on plaque size (Bland-Altman slope %+.3f, %s)."
                    % (bs, _pstr(bp)))
    if _finite(icc) and icc < 0.5:
        out += (" These two methods therefore cannot be used interchangeably for "
                "individual %s; a similar group MEAN does not imply agreement, and any "
                "per-plaque claim needs a method that does agree." % what)
    return out
# <<< SHARED AGREEMENT CORE <<<


def _icc_ci_text(s):
    if _finite(s.get("icc_lo")) and _finite(s.get("icc_hi")):
        return "95%% CI %.3f-%.3f, McGraw & Wong F interval" % (s["icc_lo"], s["icc_hi"])
    return "n too small for an interval" if s["n"] < ICC_CI_MIN_N else "CI undefined"


def _loa_method_text(s):
    if s.get("loa_method") == "t prediction":
        return "bias ± t(0.975, n-1)·SD·√(1+1/n) = ±%.2f SD: prediction limits, as n < %d" % (
            s["loa_mult"], LOA_LARGE_N)
    return "bias ± 1.96 SD"


def area_to_diameter(vals):
    """Area-equivalent diameter d = 2·√(A/π) for each area value — the SAME formula the measurement
    tool uses for its DIAMETER_MM column. Lets you feed AREA (mm²) columns and get the diameter (mm)
    comparison without converting the spreadsheet yourself."""
    return [2.0 * math.sqrt(max(float(v), 0.0) / math.pi) for v in vals]


_TEAL, _AMB, _BLU, _OUT = "#0e7d5b", "#b45309", "#3f5b8c", "#d1495b"


def _out_split(s):
    """Flag which paired differences fall outside the 95% limits of agreement."""
    diff = s["diff"]
    out = [d < s["loa_lo"] or d > s["loa_hi"] for d in diff]
    keep = lambda seq, flag: [seq[i] for i in range(len(seq)) if out[i] == flag]
    return diff, keep, sum(out)


def _draw_scatter(ax1, s, unit, label_tool, label_manual, show_key=True, show_stats=True):
    """Panel A — method-comparison scatter with identity + regression lines.

    show_key   = draw the line/point key (identity, fit, within/outside dots).
    show_stats = draw the n/r/R²/ICC/CCC + equation box.
    """
    tool, fiji = s["tool"], s["fiji"]
    _diff, keep, n_out = _out_split(s)
    lo, hi = min(tool + fiji), max(tool + fiji)
    pad = (hi - lo) * 0.06 or 0.1
    lim = [lo - pad, hi + pad]
    _xl = np.array(lim)
    (h_id,) = ax1.plot(lim, lim, "--", color="#9fb3ab", lw=1.1, zorder=1)            # identity y=x
    (h_fit,) = ax1.plot(_xl, s["slope"] * _xl + s["intercept"], "-", color=_AMB,     # regression fit
                        lw=1.6, zorder=2)
    h_in = ax1.scatter(keep(fiji, False), keep(tool, False), s=20, color=_TEAL, alpha=.72,
                       edgecolor="white", linewidth=.4, zorder=3)
    h_out = None
    if n_out:
        h_out = ax1.scatter(keep(fiji, True), keep(tool, True), s=34, color=_OUT, alpha=.95,
                            edgecolor="white", linewidth=.5, zorder=4)
    ax1.set_xlim(lim); ax1.set_ylim(lim); ax1.set_aspect("equal", "box")
    _tk = [t for t in ax1.get_xticks() if lim[0] <= t <= lim[1]]
    if _tk:
        ax1.set_xticks(_tk); ax1.set_yticks(_tk); ax1.set_xlim(lim); ax1.set_ylim(lim)
    ax1.set_xlabel("%s (%s)" % (label_manual, unit))
    ax1.set_ylabel("%s (%s)" % (label_tool, unit))
    ax1.set_title("A  Method comparison", loc="left", fontsize=10, fontweight="bold")
    if show_key:                                           # key: what each line / dot colour means
        handles = [h_id, h_fit, h_in] + ([h_out] if h_out is not None else [])
        labels = ["identity (y = x)", "linear fit", "within limits"] \
            + (["outside 95% limits"] if h_out is not None else [])
        ax1.legend(handles, labels, loc="lower right", fontsize=7.5, framealpha=.93,
                   handlelength=1.9, borderpad=0.6, labelspacing=0.4)
    if show_stats:
        # ALL the required numbers in ONE bold, high-contrast box (the regression equation used to be
        # faint amber text overlapping the legend — now it is dark, larger, clearly part of the figure)
        ax1.text(.035, .965,
                 "n = %d\nr = %.3f    R² = %.3f\nICC = %.3f    CCC = %.3f\ny = %.3f x %+.3f"
                 % (s["n"], s["r"], s.get("r2", s["r"] ** 2), s["icc"],
                    s.get("ccc", float("nan")), s["slope"], s["intercept"]),
                 transform=ax1.transAxes, va="top", ha="left", fontsize=9.5, family="monospace",
                 color="#103027", fontweight="bold",
                 bbox=dict(boxstyle="round,pad=0.5", fc="#ffffff", ec="#5f9484", lw=1.2, alpha=0.96))


def _draw_bland(ax2, s, unit, label_tool, label_manual, show_key=True):
    """Panel B — Bland-Altman difference plot with bias + 95% limits of agreement.

    show_key = draw the bias / +1.96 SD / -1.96 SD line key below the axes.
    """
    diff, keep, n_out = _out_split(s)
    ax2.axhline(0, color="#c8d2ce", lw=.8)
    ax2.axhline(s["bias"], color=_TEAL, lw=1.7, label="bias  %+.3f" % s["bias"])
    ax2.axhline(s["loa_hi"], color=_AMB, lw=1.3, ls="--", label="+1.96 SD  %+.3f" % s["loa_hi"])
    ax2.axhline(s["loa_lo"], color=_AMB, lw=1.3, ls="--", label="-1.96 SD  %+.3f" % s["loa_lo"])
    ax2.scatter(keep(s["avg"], False), keep(diff, False), s=20, color=_BLU, alpha=.72,
                edgecolor="white", linewidth=.4, zorder=3)
    if n_out:
        ax2.scatter(keep(s["avg"], True), keep(diff, True), s=34, color=_OUT, alpha=.95,
                    edgecolor="white", linewidth=.5, zorder=4)
    ax2.set_xlabel("Mean of the two methods (%s)" % unit)
    ax2.set_ylabel("%s - %s (%s)" % (label_tool, label_manual, unit))
    ax2.set_title("B  Bland-Altman", loc="left", fontsize=10, fontweight="bold")
    yspan = max(abs(s["loa_hi"]), abs(s["loa_lo"]), max(abs(d) for d in s["diff"])) * 1.15 or 0.1
    ax2.set_ylim(-yspan, yspan)
    if show_key:
        ax2.legend(loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=3, frameon=False,
                   fontsize=8, handlelength=1.6, columnspacing=1.4, prop={"family": "monospace"})


def make_figure(s, unit, label_tool, label_manual, title=None, show_key=True, show_stats=True):
    """Two-panel method-comparison + Bland-Altman figure (both panels together)."""
    fig = Figure(figsize=(9.6, 4.6), layout="constrained")
    if title:
        fig.suptitle(title, fontsize=12, fontweight="bold")
    ax1, ax2 = fig.subplots(1, 2)
    _draw_scatter(ax1, s, unit, label_tool, label_manual, show_key=show_key, show_stats=show_stats)
    _draw_bland(ax2, s, unit, label_tool, label_manual, show_key=show_key)
    return fig


def make_panel(s, which, unit, label_tool, label_manual, title=None, show_key=True, show_stats=True):
    """Single-panel figure — which = 'scatter' (Panel A) or 'bland' (Panel B)."""
    fig = Figure(figsize=(5.0, 4.7), layout="constrained")
    if title:
        fig.suptitle(title, fontsize=12, fontweight="bold")
    ax = fig.subplots(1, 1)
    if which == "scatter":
        _draw_scatter(ax, s, unit, label_tool, label_manual, show_key=show_key, show_stats=show_stats)
    else:
        _draw_bland(ax, s, unit, label_tool, label_manual, show_key=show_key)
    return fig


# =============================================================================
#  I/O + CLI
# =============================================================================
TOOL_HINTS = ("tool", "toolkit", "auto", "precise", "software", "app", "detected")
MANUAL_HINTS = ("manual", "fiji", "imagej", "hand", "reference", "ref", "gt", "ground")


def _tokens(name):
    return [t for t in re.split(r"[^a-z0-9]+", str(name).lower()) if t]


def _find_col(cols, hints, exclude=(), prefer=None):
    """Pick the column whose name TOKENS match one of `hints`. Substring matching used to
    pick `length_tool` for the MANUAL column ("gt" inside "length") and, on the repo's own
    validation file, the area columns for a diameter report (AUDIT-2026-10.md, PT-45).
    `prefer` (e.g. 'diam' or 'area') breaks ties when several columns qualify."""
    cands = []
    for c in cols:
        if c in exclude:
            continue
        toks = _tokens(c)
        if any(h in toks for h in hints):
            cands.append(c)
    if not cands:
        return None
    if prefer:
        pref = [c for c in cands if any(t.startswith(prefer) for t in _tokens(c))]
        if pref:
            return pref[0]
    return cands[0]


def _numeric_cols(df):
    return [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]


def _safe(s):
    return "".join(ch if ch.isalnum() else "_" for ch in str(s))


def run(args):
    df = pd.read_csv(args["data"], comment="#", skip_blank_lines=True) \
        if str(args["data"]).lower().endswith((".csv", ".tsv", ".txt")) \
        else pd.read_excel(args["data"])
    num = _numeric_cols(df)
    what_pref = None
    w = str(args.get("what") or "").lower()
    if w.startswith("diam"):
        what_pref = "diam"
    elif w.startswith("area"):
        what_pref = "area"
    tcol = args.get("tool") or _find_col(num, TOOL_HINTS, prefer=what_pref)
    mcol = args.get("manual") or _find_col(num, MANUAL_HINTS, exclude=(tcol,), prefer=what_pref)
    if tcol is not None and mcol is not None and tcol == mcol:
        mcol = _find_col(num, MANUAL_HINTS, exclude=(tcol,), prefer=what_pref)
    if (tcol is None or mcol is None) and len(num) == 2:
        tcol, mcol = tcol or num[0], mcol or num[1]
        print("note: columns not named — using '%s' (tool) vs '%s' (manual). "
              "Override with --tool/--manual." % (tcol, mcol))
    if tcol is None or mcol is None or tcol == mcol:
        raise SystemExit("Could not identify the two columns. Pass --tool COL --manual COL. "
                         "Numeric columns found: %s" % num)
    # Always say which columns were compared: a wrong silent pick is the worst outcome.
    print("columns: tool = %r, manual/reference = %r  (override with --tool/--manual)" % (tcol, mcol))

    d = df[[tcol, mcol]].apply(pd.to_numeric, errors="coerce").dropna()
    tool_vals, manual_vals = d[tcol].tolist(), d[mcol].tolist()
    convert = args.get("convert_area", False)
    if convert:                                            # columns are AREA → compare diameters
        tool_vals, manual_vals = area_to_diameter(tool_vals), area_to_diameter(manual_vals)
    try:
        s = full_stats(tool_vals, manual_vals)              # + R², CCC, ICC CI, p-values
    except ValueError as e:                                  # CT-R1 SM-F17: plain refusal
        raise SystemExit("Cannot compare these columns: %s" % e)

    unit = "mm" if convert else args["unit"]; what = args["what"]
    lt, lm = args["label_tool"], args["label_manual"]
    out = args["out"]; os.makedirs(out, exist_ok=True)
    suf = _safe(what)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    # figures (multi-format, editable vectors): the combined panel AND each panel on its own
    def _save(figure, name):
        for fmt in args["formats"]:
            kw = {"pil_kwargs": {"compression": "tiff_lzw"}} if fmt == "tiff" else {}
            figure.savefig(os.path.join(out, "%s.%s" % (name, fmt)), dpi=args["dpi"],
                           bbox_inches="tight", facecolor="white", **kw)
    sk, ss = args.get("show_key", True), args.get("show_stats", True)
    _save(make_figure(s, unit, lt, lm, title=args.get("title"), show_key=sk, show_stats=ss),
          "agreement_%s" % suf)
    _save(make_panel(s, "scatter", unit, lt, lm, title=args.get("title"), show_key=sk, show_stats=ss),
          "agreement_%s_A_method_comparison" % suf)
    _save(make_panel(s, "bland", unit, lt, lm, title=args.get("title"), show_key=sk),
          "agreement_%s_B_bland_altman" % suf)

    # stats CSV (one row)
    row = {k: s[k] for k in ("n", "mean_tool", "mean_fiji", "bias", "sd", "loa_lo", "loa_hi",
                             "rmse", "pct_bias", "mae", "r", "r2", "pearson_p", "t_stat", "t_p",
                             "icc", "icc_lo", "icc_hi", "ccc", "slope", "intercept",
                             "ba_slope", "ba_slope_p", "loa_ci_halfwidth", "loa_mult", "loa_method")}
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
        f.write("| Pearson r (p) | %.3f (%s) |\n" % (s["r"], _pfmt(s["pearson_p"])))
        f.write("| R^2 | %.3f |\n" % s["r2"])
        f.write("| ICC(A,1) | %.3f (%s; %s) |\n"
                % (s["icc"], _icc_ci_text(s), icc_grade(s["icc"])))
        f.write("| Lin's CCC | %.3f |\n" % s["ccc"])
        f.write("| mean bias (%s) | %+.3f (%.1f%%) |\n" % (unit, s["bias"], s["pct_bias"]))
        f.write("| bias vs 0 (paired t) | t = %.2f, %s |\n" % (s["t_stat"], _pstr(s["t_p"])))
        f.write("| 95%% limits of agreement | %+.3f to %+.3f %s (%s) |\n"
                % (s["loa_lo"], s["loa_hi"], unit, _loa_method_text(s)))
        f.write("| 95%% CI of each limit | ±%.3f %s (Bland & Altman 1999) |\n"
                % (s["loa_ci_halfwidth"], unit))
        f.write("| proportional bias (difference ~ mean) | slope %+.4f, %s |\n"
                % (s["ba_slope"], _pstr(s["ba_slope_p"])))
        f.write("| RMSE / MAE (%s) | %.3f / %.3f |\n" % (unit, s["rmse"], s["mae"]))
        f.write("| regression (tool on ref) | y = %.3f x %+.3f  (slope 1.0 = no proportional bias) |\n\n"
                % (s["slope"], s["intercept"]))
        f.write("## Paste-ready sentence\n\n> %s\n\n" % sent)
        f.write("## How to read it\n\n"
                "- **Pearson r / R^2** measure *association*, not agreement - two methods can correlate "
                "perfectly yet disagree systematically, so never report r alone.\n"
                "- **ICC(A,1)** (Koo & Li 2016) is the agreement statistic (it penalises bias): "
                "<0.5 poor, 0.5-0.75 moderate, 0.75-0.90 good, >0.90 excellent.\n"
                "- **Lin's CCC** captures accuracy *and* precision together (a common method-validation metric).\n"
                "- **Bias** = the systematic offset (tool minus reference); state it, don't hide it. The "
                "paired t-test says whether it differs from zero.\n"
                "- **95% limits of agreement** = the range within which ~95% of differences fall - "
                "the practical measure of how interchangeable the methods are.\n"
                "- **Regression slope** near 1.0 (a flat Bland-Altman cloud) means the disagreement does "
                "not grow with size.\n")
    print("[done] %s: n=%d  r=%.3f  R2=%.3f  ICC=%.3f (%s)  CCC=%.3f  bias=%+.3f %s (%.1f%%)  "
          "LoA %+.3f..%+.3f  -> %s"
          % (what, s["n"], s["r"], s["r2"], s["icc"], _icc_ci_text(s), s["ccc"],
             s["bias"], unit, s["pct_bias"], s["loa_lo"], s["loa_hi"], out))

    json.dump({"data": args["data"], "tool_col": tcol, "manual_col": mcol, "unit": unit,
               "what": what, "converted_area_to_diameter": convert, "stamp": stamp, "version": __version__,
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
    p.add_argument("--no-key", dest="show_key", action="store_false",
                   help="hide the line/point key (identity, fit, within/outside) if it crowds the figure")
    p.add_argument("--no-stats", dest="show_stats", action="store_false",
                   help="hide the n/r/R²/ICC/CCC + equation box on Panel A")
    p.add_argument("--convert-area-to-diameter", dest="convert_area", action="store_true",
                   help="treat the two columns as AREA and convert them to area-equivalent diameter "
                        "d=2*sqrt(A/pi) before comparing (result is diameter, in mm)")
    p.set_defaults(show_key=True, show_stats=True, convert_area=False)
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
