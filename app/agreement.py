"""app/agreement.py — method-comparison statistics for validating Plaque Toolkit measurements
against a reference (e.g. manual Fiji/ImageJ): Bland-Altman (bias + 95% limits of agreement),
ICC(A,1) absolute agreement, Pearson r, and a regression slope (proportional-bias check).

Pure Python for the maths (easy to test); matplotlib only for the optional figure."""
import math
import re


_NUM = r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?"


def parse_column(text):
    """Parse a pasted/typed column of values.

    Tolerates blank lines, headers and extra columns. Two things the old parser got
    wrong (AUDIT-2026-10.md, PT-35): a pasted Fiji *Results* table starts every row with
    its row number, and the parser took that (1, 2, 3 ...) instead of the measurement; and
    a European decimal comma ("1,24") was read as 1. Now: when every line carries two or
    more numbers and the first ones count 1..n, the second number is used; a lone comma
    between digits is a decimal point."""
    rows = []
    for line in str(text).splitlines():
        t = line.strip()
        if not t:
            continue
        if re.fullmatch(r"-?\d+,\d+", t):             # "1,24" -> 1.24
            t = t.replace(",", ".")
        nums = [float(x) for x in re.findall(_NUM, t.replace(",", " "))]
        if nums:
            rows.append(nums)
    if not rows:
        return []
    multi = all(len(r) >= 2 for r in rows)
    looks_indexed = multi and all(r[0] == i for i, r in enumerate(rows, start=1))
    return [r[1] if looks_indexed else r[0] for r in rows]


def area_to_diam(areas):
    """Area (mm^2) -> area-equivalent diameter (mm): d = 2*sqrt(A/pi)."""
    return [2.0 * math.sqrt(max(a, 0.0) / math.pi) for a in areas]


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


def _ba_slope(avg, diff):
    """(slope, p) of diff ~ avg (Bland-Altman proportional bias); p via scipy if present."""
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
    try:
        from scipy import stats as _st
        p = float(2 * _st.t.sf(abs(slope / se), n - 2))
    except Exception:                               # pragma: no cover
        p = float("nan")
    return slope, p


def _loa_ci_halfwidth(sd, n):
    if n < 3 or sd != sd:
        return float("nan")
    try:
        from scipy import stats as _st
        t = float(_st.t.ppf(0.975, n - 1))
    except Exception:                               # pragma: no cover
        t = 1.96
    return t * sd * math.sqrt(3.0 / n)


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
    tool, fiji = tool[:n], fiji[:n]
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
        "ba_slope": _ba_slope(avg, diff)[0], "ba_slope_p": _ba_slope(avg, diff)[1],
        "loa_ci_halfwidth": _loa_ci_halfwidth(sd, n),
    }


# Wording bands kept identical to plaque_stats/agreement/agreement.py (PT-4).
# This module is deliberately dependency-free, so the few lines are duplicated
# rather than imported across the two packages.

def icc_grade(icc):
    """Koo & Li (2016) reliability bands."""
    if icc != icc:
        return "n/a"
    return ("poor" if icc < 0.5 else "moderate" if icc < 0.75
            else "good" if icc < 0.90 else "excellent")


def agreement_phrase(icc):
    if icc != icc:
        return "could not be compared with"
    if icc < 0.5:
        return "did NOT agree at the individual level with"
    if icc < 0.75:
        return "agreed only moderately with"
    if icc < 0.90:
        return "agreed well with"
    return "agreed closely with"


def correlation_phrase(r):
    if r != r:
        return "not correlated (undefined)"
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


def report_sentence(s, unit="mm", what="diameters"):
    """Sentence whose adjectives are derived from the statistics, never asserted.

    See PT-4 in AUDIT-2026-09.md: the old wording claimed agreement even when
    ICC was negative."""
    icc = s["icc"]
    sentence = ("Plaque %s measured with Plaque Toolkit %s manual Fiji/ImageJ "
                "measurements (n = %d): %s, Pearson r = %.2f, ICC(A,1) = %.2f (%s agreement). "
                "Bland-Altman analysis showed a mean bias of %+.3f %s (%.1f%%) with 95%% limits "
                "of agreement of %+.3f to %+.3f %s, and a regression slope of %.2f "
                "(1.0 = no proportional bias)."
                % (what, agreement_phrase(icc), s["n"], correlation_phrase(s["r"]),
                   s["r"], icc, icc_grade(icc), s["bias"], unit, s["pct_bias"],
                   s["loa_lo"], s["loa_hi"], unit, s["slope"]))
    if icc == icc and icc < 0.5:
        sentence += (" These two methods therefore cannot be used interchangeably for "
                     "individual %s; a similar group MEAN does not imply agreement." % what)
    return sentence


def make_figure(s, unit="mm", title="Plaque Toolkit vs Fiji/ImageJ"):
    """Two-panel method-comparison + Bland-Altman matplotlib Figure."""
    from matplotlib.figure import Figure
    tool, fiji = s["tool"], s["fiji"]
    fig = Figure(figsize=(9.6, 4.5), layout="constrained")
    ax1, ax2 = fig.subplots(1, 2)
    TEAL, AMB, BLU, OUT = "#0e7d5b", "#b45309", "#3f5b8c", "#d1495b"
    diff = s["diff"]
    # a plaque is an "outlier" when its Toolkit−Fiji difference falls OUTSIDE the 95% limits
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
                    edgecolor="white", linewidth=.5, zorder=4, label="outside 95% limits")
        ax1.legend(loc="lower right", fontsize=7.5, framealpha=.92)
    ax1.set_xlim(lim); ax1.set_ylim(lim); ax1.set_aspect("equal", "box")
    # identity plot: force the SAME tick values on both axes so both sides read alike
    _tk = [t for t in ax1.get_xticks() if lim[0] <= t <= lim[1]]
    if _tk:
        ax1.set_xticks(_tk); ax1.set_yticks(_tk)
        ax1.set_xlim(lim); ax1.set_ylim(lim)   # re-apply (setting ticks can nudge the view)
    ax1.set_xlabel("Fiji / ImageJ (%s)" % unit); ax1.set_ylabel("Plaque Toolkit (%s)" % unit)
    ax1.set_title("A  Method comparison", loc="left", fontsize=10, fontweight="bold")
    ax1.text(.04, .96, "n=%d\nr=%.3f\nICC=%.3f" % (s["n"], s["r"], s["icc"]),
             transform=ax1.transAxes, va="top", ha="left", fontsize=8, family="monospace",
             bbox=dict(boxstyle="round,pad=0.3", fc="#f0f5f2", ec="#cfe0d8"))
    ax2.axhline(0, color="#c8d2ce", lw=.8)
    ax2.axhline(s["bias"], color=TEAL, lw=1.7, label="bias  %+.3f" % s["bias"])
    ax2.axhline(s["loa_hi"], color=AMB, lw=1.3, ls="--", label="+1.96 SD  %+.3f" % s["loa_hi"])
    ax2.axhline(s["loa_lo"], color=AMB, lw=1.3, ls="--", label="−1.96 SD  %+.3f" % s["loa_lo"])
    ax2.scatter(keep(s["avg"], False), keep(diff, False), s=20, color=BLU, alpha=.72,
                edgecolor="white", linewidth=.4, zorder=3)
    if n_out:
        ax2.scatter(keep(s["avg"], True), keep(diff, True), s=34, color=OUT, alpha=.95,
                    edgecolor="white", linewidth=.5, zorder=4)
    ax2.set_xlabel("Mean of the two methods (%s)" % unit)
    ax2.set_ylabel("Toolkit − Fiji (%s)" % unit)
    ax2.set_title("B  Bland–Altman", loc="left", fontsize=10, fontweight="bold")
    # give the differences vertical headroom, and label the lines in a legend BELOW the panel
    # (so the numbers never overlap the points or the axis)
    yspan = max(abs(s["loa_hi"]), abs(s["loa_lo"]), max(abs(d) for d in s["diff"])) * 1.15 or 0.1
    ax2.set_ylim(-yspan, yspan)
    ax2.legend(loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=3, frameon=False,
               fontsize=8, handlelength=1.6, columnspacing=1.4, prop={"family": "monospace"})
    return fig
