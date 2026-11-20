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

__version__ = "1.1.0"


def _load_legend_key():
    """plaque_stats/legend_key.py: already loaded, a flat import (web app / exe folder), or the
    file one folder up (running from the repo) -- loaded by file so the ``plaque_stats`` name
    stays free for the flat plaque_stats.py module. None = no key (the figure is unaffected)."""
    import sys
    for name in ("plaque_stats.legend_key", "legend_key"):
        if name in sys.modules:
            return sys.modules[name]
    try:
        import legend_key
        return legend_key
    except ImportError:
        pass
    import importlib.util
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "legend_key.py")
    if os.path.exists(p):
        spec = importlib.util.spec_from_file_location("legend_key", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        sys.modules.setdefault("legend_key", mod)
        return mod
    return None


_lk = _load_legend_key()


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


PRED_N = 20                # below this many pairs the report adds a prediction interval


def prediction_interval(bias, sd, n):
    """95% prediction interval for ONE new difference: bias +/- t(0.975, n-1) * SD * sqrt(1 + 1/n).
    CT-R1 SM-F16: below ~20 pairs the 95% limits of agreement (bias +/- 1.96 SD, Bland & Altman's
    definition, kept at every n) hold only 77-85 % of new differences, so the report ADDS this
    interval for n < 20. Returns (nan, nan) from 20 pairs on or when undefined."""
    if n >= PRED_N or n < 3 or not _finite(sd):
        return float("nan"), float("nan")
    from scipy import stats as _st
    h = float(_st.t.ppf(0.975, n - 1)) * sd * math.sqrt(1.0 + 1.0 / n)
    return bias - h, bias + h


def _loa_ci_halfwidth(sd, n, k=1.96):
    """Half-width of the 95% CI of each limit of agreement, Bland & Altman (1999) exact form:
    SE(limit) = SD * sqrt(1/n + 1.96^2 / (2(n-1))), times t(0.975, n-1)."""
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


def _constant_difference(diff, tool, fiji):
    """True when every tool - reference difference is the same up to float rounding (e.g. a
    fixed +0.1 offset): its spread is then 0, not 1e-17 noise that a t-test would call
    'significant' (CT-R1 SM-F17)."""
    scale = max(1.0, max(abs(v) for v in list(tool) + list(fiji)))
    return (max(diff) - min(diff)) <= 1e-9 * scale


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
    constant = _constant_difference(diff, tool, fiji)
    if constant:
        sd = 0.0
    grand = _mean(avg)
    slope, intercept = regress(fiji, tool)
    pred_lo, pred_hi = prediction_interval(bias, sd, n)
    ba_slope, ba_p = (0.0, float("nan")) if constant else _ba_slope(avg, diff)
    return {
        "n": n, "mean_tool": _mean(tool), "mean_fiji": _mean(fiji),
        "bias": bias, "sd": sd, "loa_lo": bias - 1.96 * sd, "loa_hi": bias + 1.96 * sd,
        "pred_lo": pred_lo, "pred_hi": pred_hi,
        "rmse": math.sqrt(_mean([d * d for d in diff])),
        "pct_bias": (bias / grand * 100.0) if grand else float("nan"),
        "mae": _mean([abs(d) for d in diff]),
        "r": pearson(tool, fiji), "icc": icc_a1(fiji, tool),
        "slope": slope, "intercept": intercept, "diff": diff, "avg": avg,
        "tool": tool, "fiji": fiji, "constant_difference": constant,
        # Bland-Altman proportional bias: regress the difference on the mean of the two
        # methods; a non-zero slope means the bias changes with plaque size (PT-46).
        "ba_slope": ba_slope, "ba_slope_p": ba_p,
        # 95% CI of each limit of agreement (Bland & Altman 1999, exact form).
        "loa_ci_halfwidth": _loa_ci_halfwidth(sd, n),
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
    diff = [float(a) - float(b) for a, b in zip(tool, fiji)]
    if _constant_difference(diff, tool, fiji):
        t, tp = float("nan"), float("nan")     # no spread: the paired t-test is not testable
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


def icc_grade_interval(lo, hi):
    """Koo & Li (2016) grade of the 95% CI of ICC(A,1), as Koo & Li advise (CT-R2 N8: the point
    estimate was graded, "0.949 (95% CI 0.709-0.986) (excellent agreement)" at n = 15): one word
    when both limits fall in one band, "moderate to excellent" when they span bands, "" when
    there is no interval."""
    if not (_finite(lo) and _finite(hi)):
        return ""
    a, b = icc_grade(lo), icc_grade(hi)
    return a if a == b else "%s to %s" % (a, b)


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


def icc_interval_note(s, unit="mm"):
    """A plain note when the exact ICC interval is wide because of a systematic offset
    (paired t-test p < 0.05 AND ICC - lower limit > 0.10); '' otherwise."""
    icc, lo, tp = s.get("icc"), s.get("icc_lo"), s.get("t_p")
    if not (_finite(icc) and _finite(lo) and _finite(tp)) or tp >= 0.05 or icc - lo <= 0.10:
        return ""
    return ("The ICC interval is wide because the two methods differ by a systematic offset "
            "(bias %+.3f %s): with two methods that offset is estimated from a single contrast. "
            "Judge agreement from the bias and the limits of agreement." % (s["bias"], unit))


SMALL_N = 10               # below this the sentence says the estimates rest on few pairs
VERDICT_MIN_N = 5          # below this no verdict at all: numbers only (CT-R2 N8)


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
    verdict = n >= VERDICT_MIN_N
    if not verdict:
        # CT-R2 N8: "cannot be used interchangeably" was printed from 3 pairs
        out = ("With only %d pairs (too few pairs for a verdict), %s measured with %s were compared "
               "with %s (n = %d)" % (n, what, label_tool, label_manual, n))
    else:
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
        if verdict:
            out += ": %s (%s)" % (correlation_phrase(r, p if p is not None else nan), corr)
        else:
            out += ": %s" % corr
    else:
        out += ": Pearson r could not be computed"
    # ICC (+ CI, graded on the CI) and CCC
    if _finite(icc):
        grade = icc_grade_interval(s.get("icc_lo"), s.get("icc_hi"))
        if grade:
            out += (", with an intraclass correlation coefficient ICC(A,1) = %.3f (95%% CI %.3f-%.3f): "
                    "%s agreement, graded on the interval (Koo & Li 2016)"
                    % (icc, s["icc_lo"], s["icc_hi"], grade))
        elif "icc_lo" in s and n < ICC_CI_MIN_N:
            out += (", with an intraclass correlation coefficient ICC(A,1) = %.3f (n too small for an "
                    "interval, so no agreement grade)" % icc)
        else:
            out += ", with an intraclass correlation coefficient ICC(A,1) = %.3f" % icc
        if _finite(s.get("ccc")):
            out += ", and Lin's concordance correlation CCC = %.3f" % s["ccc"]
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
    if s.get("constant_difference"):
        bits.append("every difference was the same, so their spread is zero")
    out += " Bland-Altman analysis showed a mean bias of %+.3f %s%s" \
           % (s["bias"], unit, (" (%s)" % "; ".join(bits)) if bits else "")
    loa = "with 95%% limits of agreement of %+.3f to %+.3f %s" % (s["loa_lo"], s["loa_hi"], unit)
    extra = []
    if _finite(s.get("loa_ci_halfwidth")):
        # CT-R2 N11: the interval of each limit covers ~0.92 at n <= 5: approximate below 10 pairs
        extra.append("each limit ±%.3f %s, %s95%% CI" % (s["loa_ci_halfwidth"], unit,
                                                         "approximate " if n < SMALL_N else ""))
    if extra:
        loa += " (%s)" % "; ".join(extra)
    out += " " + loa
    if _finite(s.get("slope")):
        out += ", and a regression slope of %.2f (1.0 = no proportional bias)" % s["slope"]
    out += "."
    if _finite(s.get("pred_lo")) and _finite(s.get("pred_hi")):
        out += (" With only %d pairs, a new difference is expected within %+.3f to %+.3f %s "
                "(95%% prediction interval)." % (n, s["pred_lo"], s["pred_hi"], unit))
    bs, bp = s.get("ba_slope", nan), s.get("ba_slope_p", nan)
    if _finite(bs) and _finite(bp):
        if bp < 0.05:
            out += (" The difference depended on plaque size (Bland-Altman slope %+.3f %s per %s, %s): "
                    "a proportional bias, so a single bias value does not describe the whole range."
                    % (bs, unit, unit, _pstr(bp)))
        else:
            # CT-R2 N8: a non-significant slope is no evidence of no bias, least of all at small n
            out += (" No proportional bias was detected (Bland-Altman slope %+.3f, %s%s)."
                    % (bs, _pstr(bp), "; with %d pairs there is little power to detect one" % n
                       if n < SMALL_N else ""))
    if verdict and _finite(icc) and icc < 0.5:
        out += (" These two methods therefore cannot be used interchangeably for "
                "individual %s; a similar group MEAN does not imply agreement, and any "
                "per-plaque claim needs a method that does agree." % what)
    return out

# --------------------------------------------------------------------------- figure + legend key
# CT-R1 DA-F4/F18: ONE style table. The two panels, the legend key embedded on the figure and the
# stand-alone key are all drawn from it, so "within limits" has one colour in both panels and the
# key always shows exactly what is drawn. The figure is built (and saved) inside figure_rc(), a
# clean rc context with explicit sizes, so another plot changing plt.rcParams cannot alter it.
_TEAL, _AMB, _BLU, _OUT = "#0e7d5b", "#b45309", "#3f5b8c", "#d1495b"
FIG_STYLE = {
    "within": {"label": "within the limits of agreement", "kind": "marker", "colour": _TEAL,
               "edge": "#ffffff", "s": 20, "alpha": 0.72, "lw": 0.4},
    "outside": {"label": "outside the 95% limits of agreement", "kind": "marker", "colour": _OUT,
                "edge": "#ffffff", "s": 34, "alpha": 0.95, "lw": 0.5},
    "identity": {"label": "line of identity (y = x)", "kind": "line", "colour": "#7f8c8d",
                 "ls": "--", "lw": 1.1},
    "fit": {"label": "least-squares fit", "kind": "line", "colour": _BLU, "ls": "-", "lw": 1.6},
    "zero": {"label": "zero difference", "kind": "line", "colour": "#c8d2ce", "ls": "-", "lw": 0.8},
    "bias": {"label": "mean bias", "kind": "line", "colour": _TEAL, "ls": "-", "lw": 1.7},
    "loa": {"label": "95% limits of agreement", "kind": "line", "colour": _AMB, "ls": "--", "lw": 1.3},
}
FIG_FONT = "DejaVu Sans"         # ships with matplotlib: the same font on every machine
FIG_RC = {"font.family": "sans-serif", "font.sans-serif": [FIG_FONT], "font.size": 9.0,
          "axes.titlesize": 10.0, "axes.labelsize": 9.0, "xtick.labelsize": 8.0,
          "ytick.labelsize": 8.0, "legend.fontsize": 8.0, "axes.linewidth": 0.8,
          "svg.fonttype": "none", "pdf.fonttype": 42, "ps.fonttype": 42}
KEY_FONTSIZE = 8.0


class figure_rc:
    """Context: matplotlib defaults + FIG_RC, whatever the caller's rcParams are."""

    def __enter__(self):
        import matplotlib
        self._ctx = matplotlib.rc_context()
        self._ctx.__enter__()
        matplotlib.rcdefaults()
        matplotlib.rcParams.update(FIG_RC)
        return self

    def __exit__(self, *exc):
        return self._ctx.__exit__(*exc)


def _fix_ticks(ax):
    """Tick labels are created lazily at draw time; pin their look so a later draw outside
    figure_rc() (e.g. the Qt canvas) cannot pick up someone else's rcParams."""
    kw = dict(labelsize=FIG_RC["xtick.labelsize"], length=3.5, width=0.8, pad=3.5,
              direction="out", color="black", labelcolor="black")
    try:
        ax.tick_params(labelfontfamily=FIG_FONT, **kw)
    except (TypeError, ValueError, AttributeError):    # matplotlib < 3.8
        ax.tick_params(**kw)


def _key_entry(name):
    st_ = FIG_STYLE[name]
    if st_["kind"] == "marker":
        return _lk.entry(st_["label"], st_["colour"], kind="marker", marker="o", filled=True,
                         edge=st_["edge"], alpha=st_["alpha"], size=math.sqrt(st_["s"]) + 1.0)
    return _lk.entry(st_["label"], st_["colour"], kind="line", linestyle=st_["ls"],
                     linewidth=st_["lw"])


def key_entries(s, which="both"):
    """Names (FIG_STYLE keys) of every encoding drawn, in key order: points, then lines.
    ``which`` = 'both', 'scatter' (panel A) or 'bland' (panel B)."""
    _diff, _keep, n_out = _out_split(s)
    names = ["within"] + (["outside"] if n_out else [])
    if which in ("both", "scatter"):
        names += ["identity"] + (["fit"] if _finite(s.get("slope")) else [])
    if which in ("both", "bland"):
        names += ["zero", "bias", "loa"]
    return names


def figure_key(s, which="both"):
    """The legend key of the agreement figure (legend_key format), or None when the
    legend_key helper is not available."""
    if _lk is None:
        return None
    return _lk.make_key([_key_entry(n) for n in key_entries(s, which)], fontsize=KEY_FONTSIZE,
                        frameon=False, font_family=FIG_FONT)


def _out_split(s):
    """Flag which paired differences fall outside the 95% limits of agreement."""
    diff = s["diff"]
    out = [d < s["loa_lo"] or d > s["loa_hi"] for d in diff]
    keep = lambda seq, flag: [seq[i] for i in range(len(seq)) if out[i] == flag]
    return diff, keep, sum(out)


def _scatter(ax, xs, ys, name):
    st_ = FIG_STYLE[name]
    return ax.scatter(xs, ys, s=st_["s"], color=st_["colour"], alpha=st_["alpha"],
                      edgecolor=st_["edge"], linewidth=st_["lw"], zorder=4 if name == "outside" else 3)


def _line_kw(name):
    st_ = FIG_STYLE[name]
    return dict(color=st_["colour"], ls=st_["ls"], lw=st_["lw"])


def _fmt3(v):
    return "%.3f" % v if _finite(v) else "n/a"


def _draw_scatter(ax1, s, unit, label_tool, label_manual, show_stats=True):
    """Panel A - method-comparison scatter with identity + least-squares lines."""
    import numpy as _np
    tool, fiji = s["tool"], s["fiji"]
    _diff, keep, n_out = _out_split(s)
    lo, hi = min(tool + fiji), max(tool + fiji)
    pad = (hi - lo) * 0.06 or 0.1
    lim = [lo - pad, hi + pad]
    ax1.plot(lim, lim, zorder=1, **_line_kw("identity"))
    if _finite(s.get("slope")):
        xl = _np.array(lim)
        ax1.plot(xl, s["slope"] * xl + s["intercept"], zorder=2, **_line_kw("fit"))
    _scatter(ax1, keep(fiji, False), keep(tool, False), "within")
    if n_out:
        _scatter(ax1, keep(fiji, True), keep(tool, True), "outside")
    ax1.set_xlim(lim); ax1.set_ylim(lim); ax1.set_aspect("equal", "box")
    _tk = [t for t in ax1.get_xticks() if lim[0] <= t <= lim[1]]
    if _tk:                                  # same tick values on both axes of an identity plot
        ax1.set_xticks(_tk); ax1.set_yticks(_tk); ax1.set_xlim(lim); ax1.set_ylim(lim)
    ax1.set_xlabel("%s (%s)" % (label_manual, unit))
    ax1.set_ylabel("%s (%s)" % (label_tool, unit))
    ax1.set_title("A  Method comparison", loc="left", fontsize=10, fontweight="bold")
    if show_stats:
        ax1.text(.035, .965,
                 "n = %d\nr = %s    R² = %s\nICC = %s    CCC = %s\ny = %s x %+.3f"
                 % (s["n"], _fmt3(s["r"]), _fmt3(s.get("r2", s["r"] ** 2)), _fmt3(s["icc"]),
                    _fmt3(s.get("ccc", float("nan"))), _fmt3(s["slope"]), s["intercept"]),
                 transform=ax1.transAxes, va="top", ha="left", fontsize=8.5, family="monospace",
                 color="#103027", fontweight="bold",
                 bbox=dict(boxstyle="round,pad=0.45", fc="#ffffff", ec="#5f9484", lw=1.0, alpha=0.96))
    _fix_ticks(ax1)


def _draw_bland(ax2, s, unit, label_tool, label_manual):
    """Panel B - Bland-Altman difference plot; the bias and limits carry their values."""
    diff, keep, n_out = _out_split(s)
    ax2.axhline(0, **_line_kw("zero"))
    ax2.axhline(s["bias"], **_line_kw("bias"))
    ax2.axhline(s["loa_hi"], **_line_kw("loa"))
    ax2.axhline(s["loa_lo"], **_line_kw("loa"))
    _scatter(ax2, keep(s["avg"], False), keep(diff, False), "within")
    if n_out:
        _scatter(ax2, keep(s["avg"], True), keep(diff, True), "outside")
    ax2.set_xlabel("Mean of the two methods (%s)" % unit)
    ax2.set_ylabel("%s - %s (%s)" % (label_tool, label_manual, unit))
    ax2.set_title("B  Bland-Altman", loc="left", fontsize=10, fontweight="bold")
    yspan = max(abs(s["loa_hi"]), abs(s["loa_lo"]), max(abs(d) for d in diff)) * 1.25 or 0.1
    ax2.set_ylim(-yspan, yspan)
    up, dn = "+1.96 SD", "-1.96 SD"
    tr = ax2.get_yaxis_transform()
    for y, txt, va in ((s["loa_hi"], "%s  %+.3f" % (up, s["loa_hi"]), "bottom"),
                       (s["bias"], "bias  %+.3f" % s["bias"], "bottom"),
                       (s["loa_lo"], "%s  %+.3f" % (dn, s["loa_lo"]), "top")):
        ax2.text(0.985, y, txt, transform=tr, ha="right", va=va, fontsize=7.5, family="monospace",
                 color="#1f2430", zorder=5,
                 bbox=dict(boxstyle="square,pad=0.15", fc="#ffffff", ec="none", alpha=0.75))
    _fix_ticks(ax2)


def _finish(fig, s, which, show_key):
    key = figure_key(s, which)
    if key is not None:
        _lk.attach(fig, key)
        if show_key:
            ncol = 4 if which == "both" else 2
            try:                           # 'outside' placement needs matplotlib >= 3.7
                _lk.embed(fig, key, loc="outside lower center", ncol=ncol, columnspacing=1.4,
                          handlelength=2.2)
            except (ValueError, TypeError):
                _lk.embed(fig, key, loc="lower center", ncol=ncol, columnspacing=1.4,
                          handlelength=2.2)
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    if fig.canvas is None or type(fig.canvas).__name__ == "FigureCanvasBase":
        FigureCanvasAgg(fig)
    fig.canvas.draw()                      # resolve every lazy text/tick inside figure_rc()
    return fig


def make_figure(s, unit="mm", label_tool="Plaque Toolkit", label_manual="Fiji / ImageJ",
                title=None, show_key=True, show_stats=True):
    """Two-panel method-comparison + Bland-Altman figure. ``show_key`` places the legend key
    (the same entries as the stand-alone key, ``legend_key.from_figure(fig)``) below the panels."""
    from matplotlib.figure import Figure
    with figure_rc():
        fig = Figure(figsize=(9.6, 5.0), layout="constrained")
        if title:
            fig.suptitle(title, fontsize=12, fontweight="bold")
        ax1, ax2 = fig.subplots(1, 2)
        _draw_scatter(ax1, s, unit, label_tool, label_manual, show_stats=show_stats)
        _draw_bland(ax2, s, unit, label_tool, label_manual)
        return _finish(fig, s, "both", show_key)


def make_panel(s, which, unit="mm", label_tool="Plaque Toolkit", label_manual="Fiji / ImageJ",
               title=None, show_key=True, show_stats=True):
    """Single-panel figure - which = 'scatter' (Panel A) or 'bland' (Panel B); its own key."""
    from matplotlib.figure import Figure
    which = "scatter" if which == "scatter" else "bland"
    with figure_rc():
        fig = Figure(figsize=(5.0, 5.2), layout="constrained")
        if title:
            fig.suptitle(title, fontsize=12, fontweight="bold")
        ax = fig.subplots(1, 1)
        if which == "scatter":
            _draw_scatter(ax, s, unit, label_tool, label_manual, show_stats=show_stats)
        else:
            _draw_bland(ax, s, unit, label_tool, label_manual)
        return _finish(fig, s, which, show_key)


def save_figure(fig, path, dpi=300):
    """Save a figure made here (format from the extension) inside figure_rc(); text stays text
    in SVG/PDF/EPS."""
    import os as _os
    ext = _os.path.splitext(path)[1].lower()
    kw = {"dpi": dpi, "bbox_inches": "tight", "facecolor": "white"}
    if ext in (".tif", ".tiff"):
        kw["pil_kwargs"] = {"compression": "tiff_lzw"}
    with figure_rc():
        fig.savefig(path, **kw)
    return path


def save_key_files(fig, base, formats=("png",), dpi=300):
    """Write <base>_legend_key.<fmt> for each format + <base>_legend_text.txt for a figure
    made here. Returns the paths ([] when the legend_key helper is unavailable)."""
    key = _lk.from_figure(fig) if _lk is not None else None
    if not key:
        return []
    with figure_rc():
        return _lk.write_key_files(key, base, formats, dpi=dpi)
# <<< SHARED AGREEMENT CORE <<<


def _icc_ci_text(s):
    if _finite(s.get("icc_lo")) and _finite(s.get("icc_hi")):
        return "95%% CI %.3f-%.3f, McGraw & Wong F interval" % (s["icc_lo"], s["icc_hi"])
    return "n too small for an interval" if s["n"] < ICC_CI_MIN_N else "CI undefined"


def area_to_diameter(vals):
    """Area-equivalent diameter d = 2·√(A/π) for each area value — the SAME formula the measurement
    tool uses for its DIAMETER_MM column. Lets you feed AREA (mm²) columns and get the diameter (mm)
    comparison without converting the spreadsheet yourself."""
    return [2.0 * math.sqrt(max(float(v), 0.0) / math.pi) for v in vals]


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


class ColumnError(ValueError):
    """A --tool / --manual name that is not a numeric column (the CLI exits with code 2)."""


def _numeric_cols(df):
    return [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]


def _safe(s):
    return "".join(ch if ch.isalnum() else "_" for ch in str(s))


def run(args):
    df = pd.read_csv(args["data"], comment="#", skip_blank_lines=True) \
        if str(args["data"]).lower().endswith((".csv", ".tsv", ".txt")) \
        else pd.read_excel(args["data"])
    num = _numeric_cols(df)
    for flag, key in (("--tool", "tool"), ("--manual", "manual")):
        name = args.get(key)
        if name and name not in num:       # CT-R1: a one-line message, not a pandas KeyError
            raise ColumnError("%s %r is not a numeric column of %s. Numeric columns: %s."
                              % (flag, name, os.path.basename(str(args["data"])),
                                 ", ".join(map(str, num)) or "none"))
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
        raise ValueError("Cannot compare these columns: %s" % e) from None

    unit = "mm" if convert else args["unit"]; what = args["what"]
    lt, lm = args["label_tool"], args["label_manual"]
    out = args["out"]; os.makedirs(out, exist_ok=True)
    suf = _safe(what)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    # figures (multi-format, editable vectors): the combined panel AND each panel on its own,
    # each with its legend key files beside it (CT-R1 DA-F4: the figure rule's key + text starter)
    key_files = args.get("legend_key", True) is not False
    def _save(figure, name):
        for fmt in args["formats"]:
            save_figure(figure, os.path.join(out, "%s.%s" % (name, fmt)), dpi=args["dpi"])
        if key_files:
            save_key_files(figure, os.path.join(out, name), args["formats"], dpi=args["dpi"])
    sk = args.get("show_key", True) if args.get("key_on_figure") is None else bool(args["key_on_figure"])
    ss = args.get("show_stats", True)
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
                             "ba_slope", "ba_slope_p", "loa_ci_halfwidth", "pred_lo", "pred_hi")}
    row["icc_grade"] = icc_grade(s["icc"])
    row["icc_grade_ci"] = icc_grade_interval(s.get("icc_lo"), s.get("icc_hi"))   # CT-R2 N8
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
        gci = icc_grade_interval(s.get("icc_lo"), s.get("icc_hi"))
        f.write("| ICC(A,1) | %.3f (%s%s) |\n"
                % (s["icc"], _icc_ci_text(s), ("; %s, graded on the interval" % gci) if gci else ""))
        f.write("| Lin's CCC | %.3f |\n" % s["ccc"])
        f.write("| mean bias (%s) | %+.3f (%.1f%%) |\n" % (unit, s["bias"], s["pct_bias"]))
        f.write("| bias vs 0 (paired t) | t = %.2f, %s |\n" % (s["t_stat"], _pstr(s["t_p"])))
        f.write("| 95%% limits of agreement | %+.3f to %+.3f %s (bias ± 1.96 SD) |\n"
                % (s["loa_lo"], s["loa_hi"], unit))
        if _finite(s.get("pred_lo")):
            f.write("| 95%% prediction interval, one new difference (n < %d) | %+.3f to %+.3f %s "
                    "(bias ± t·SD·√(1+1/n)) |\n" % (PRED_N, s["pred_lo"], s["pred_hi"], unit))
        f.write("| %s95%% CI of each limit | ±%.3f %s (Bland & Altman 1999) |\n"
                % ("approximate " if s["n"] < SMALL_N else "", s["loa_ci_halfwidth"], unit))
        f.write("| proportional bias (difference ~ mean) | slope %+.4f, %s |\n"
                % (s["ba_slope"], _pstr(s["ba_slope_p"])))
        f.write("| RMSE / MAE (%s) | %.3f / %.3f |\n" % (unit, s["rmse"], s["mae"]))
        f.write("| regression (tool on ref) | y = %.3f x %+.3f  (slope 1.0 = no proportional bias) |\n\n"
                % (s["slope"], s["intercept"]))
        f.write("## Paste-ready sentence\n\n> %s\n\n" % sent)
        note = icc_interval_note(s, unit)
        if note:
            f.write("**Note.** %s\n\n" % note)
        f.write("## How to read it\n\n"
                "- **Pearson r / R^2** measure *association*, not agreement - two methods can correlate "
                "perfectly yet disagree systematically, so never report r alone.\n"
                "- **ICC(A,1)** (Koo & Li 2016) is the agreement statistic (it penalises bias): "
                "<0.5 poor, 0.5-0.75 moderate, 0.75-0.90 good, >0.90 excellent, graded on its 95% CI "
                "(one word when both limits fall in one band).\n"
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
                   help="do not place the legend key on the figure")
    p.add_argument("--key-on-figure", dest="show_key", action="store_true",
                   help="place the legend key (every point and line style) below the panels "
                        "(the default)")
    p.add_argument("--legend-key", dest="legend_key", action="store_true", default=None,
                   help="write <figure>_legend_key.<fmt> + <figure>_legend_text.txt beside every "
                        "figure (the default)")
    p.add_argument("--no-legend-key", dest="legend_key", action="store_false",
                   help="do not write the legend key files")
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
    try:
        run(args)
    except ColumnError as e:             # a usage error: one line, exit code 2 (like argparse)
        import sys
        print("agreement.py: error: %s" % e, file=sys.stderr)
        raise SystemExit(2)
    except ValueError as e:              # a plain message, not a traceback
        raise SystemExit(str(e))


if __name__ == "__main__":
    main()
