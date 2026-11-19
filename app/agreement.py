"""app/agreement.py — method-comparison statistics for validating Plaque Toolkit measurements
against a reference (e.g. manual Fiji/ImageJ): Bland-Altman (bias + 95% limits of agreement),
ICC(A,1) absolute agreement, Pearson r, and a regression slope (proportional-bias check).

Pure Python for the maths (easy to test); matplotlib only for the optional figure."""
import math
import re


# --------------------------------------------------------------------------- paste parser
# CT-R1 DA-F7: the old parser pulled every digit out of every line with a regex, so a header
# "AREA_MM2" became the value 2 (shifting every pair: ICC 0.998 -> -0.751), a Fiji table whose
# row numbers start at 7 was read as the row numbers, ".62" was read as 62, "1,234.5" as 1, a
# word in the middle of the column was silently dropped (shifting the rest), and values typed
# on one line were rejected. It now reads the paste LINE BY LINE, cell by cell, says what it
# did in plain notes, and refuses (naming the line) rather than guess.
_NUM_RE = re.compile(r"^[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?$")
_THOUSANDS_RE = re.compile(r"^[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?$")       # 1,234.5 / 1,234,567
_EU_THOUSANDS_RE = re.compile(r"^[-+]?\d{1,3}(?:\.\d{3})+,\d+$")         # 1.234,5
_DEC_COMMA_RE = re.compile(r"^[-+]?\d*,\d+$")                           # 1,27 / ,5


def _num(cell):
    """One cell -> float, or None when it is not a number."""
    c = str(cell).strip().strip("\"'").strip().replace("−", "-")
    if not c:
        return None
    if _NUM_RE.match(c):
        return float(c)
    if _DEC_COMMA_RE.match(c):                      # a lone comma is a decimal comma (1,27)
        return float(c.replace(",", "."))
    if "." in c and _THOUSANDS_RE.match(c) or (c.count(",") > 1 and _THOUSANDS_RE.match(c)):
        return float(c.replace(",", ""))            # 1,234.5 (unambiguous thousands)
    if _EU_THOUSANDS_RE.match(c):
        return float(c.replace(".", "").replace(",", "."))
    return None


def _cells(line):
    """Split one line into cells: tab, then semicolon, then comma-separated when the commas
    cannot be decimal commas (a '.' elsewhere, or ', '), else whitespace."""
    s = line.strip()
    for sep in ("\t", ";"):
        if sep in s:
            cells = [c.strip() for c in s.split(sep)]
            while cells and not cells[-1]:          # a trailing tab is not a cell
                cells.pop()
            return cells
    if "," in s and (", " in s or ("." in s and _num(s) is None)):
        return [c.strip() for c in s.split(",")]
    toks = s.split()
    if len(toks) == 1 and "," in s and _num(s) is None:
        return [c.strip() for c in s.split(",")]      # 1,2,3 -> three values
    return toks


def _count(k):
    return "%d value%s" % (k, "" if k == 1 else "s")


def _clip(s, n=40):
    s = str(s).strip()
    return s if len(s) <= n else s[:n - 1] + "…"


def parse_values(text):
    """Parse a pasted column (or a pasted table) of measurements.

    Returns ``(values, notes)``; ``notes`` are plain sentences saying what was skipped or
    chosen. Raises ``ValueError`` naming the line when a line in the middle is not a number
    or the rows have different numbers of cells (never a silent drop).

    * A first line that is not purely numbers is a header (digits inside a header such as
      ``AREA_MM2`` are not data) and is skipped.
    * In a table, a first column of consecutive increasing integers (1, 2, 3 ... or 7, 8, 9 ...)
      is a row number; the measurement column next to it is used. With several measurement
      columns left, the one whose header names area/diameter wins, else the first one.
    * Decimal commas (``1,27``), ``.62`` = 0.62, ``1,234.5`` = 1234.5, and values typed on
      ONE line (tab / space / semicolon / comma separated) all read as a column.
    """
    notes = []
    lines = [(i + 1, l) for i, l in enumerate(str(text).splitlines())]
    lines = [(no, l) for no, l in lines if any(c for c in _cells(l))]
    if not lines:
        return [], notes
    header = None
    first_no, first = lines[0]
    if any(_num(c) is None for c in _cells(first) if c):
        header = _cells(first)
        notes.append('Skipped the header line "%s".' % _clip(first))
        lines = lines[1:]
    rows = []
    for no, l in lines:
        cells = _cells(l)
        if any(not c for c in cells):
            raise ValueError('Line %d ("%s") has an empty cell. Remove it or fill it in; '
                             'nothing was computed.' % (no, _clip(l)))
        vals = [_num(c) for c in cells]
        if any(v is None for v in vals):
            bad = next(c for c, v in zip(cells, vals) if v is None)
            what = "" if bad.strip() == l.strip() else ' ("%s" is not a number)' % _clip(bad, 20)
            raise ValueError('Line %d ("%s") is not a number%s. Remove or fix that line; '
                             'nothing was computed.' % (no, _clip(l), what))
        rows.append((no, vals))
    if not rows:
        return [], notes
    if len(rows) == 1 and len(rows[0][1]) > 1:      # values typed on one line = a column
        notes.append("Read the %d values on line %d as one column." % (len(rows[0][1]), rows[0][0]))
        return list(rows[0][1]), notes
    ncols = len(rows[0][1])
    for no, vals in rows[1:]:
        if len(vals) != ncols:
            raise ValueError("Line %d has %s but line %d has %s. Every line must have the same "
                             "columns; nothing was computed."
                             % (no, _count(len(vals)), rows[0][0], _count(ncols)))
    if ncols == 1:
        return [v[0] for _no, v in rows], notes
    cols = [[v[j] for _no, v in rows] for j in range(ncols)]
    c0 = cols[0]
    is_index = (len(c0) >= 2 and all(float(x).is_integer() for x in c0)
                and all(b - a == 1 for a, b in zip(c0, c0[1:])))
    cand = list(range(1, ncols)) if is_index else list(range(ncols))
    names = None
    if header is not None:
        h = list(header)
        if len(h) == ncols - 1:                      # Fiji's row-number column has no name
            h = [""] + h
        if len(h) == ncols:
            names = h
    pick = cand[0]
    if names and len(cand) > 1:
        for j in cand:
            if re.search(r"area|diam", names[j], re.I):
                pick = j
                break
    if is_index:
        notes.append("The first column (%g, %g, %g …) is a row number, not a measurement."
                     % tuple(c0[:3]) if len(c0) >= 3 else
                     "The first column (%s) is a row number, not a measurement."
                     % ", ".join("%g" % x for x in c0))
    if len(cand) > 1 or is_index:
        nm = (' "%s"' % names[pick]) if names and names[pick] else ""
        notes.append("Used column %d%s of %d. To use another column, paste only that column."
                     % (pick + 1, nm, ncols))
    return cols[pick], notes


def parse_column(text):
    """Parse a pasted/typed column of values (see :func:`parse_values`); the values only."""
    return parse_values(text)[0]


def area_to_diam(areas):
    """Area (mm^2) -> area-equivalent diameter (mm): d = 2*sqrt(A/pi)."""
    return [2.0 * math.sqrt(max(a, 0.0) / math.pi) for a in areas]


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
