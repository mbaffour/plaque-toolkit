# app_py.py — Agreement (tool vs manual) as a Shiny for Python browser app.
# ---------------------------------------------------------------------------------------------
# A browser GUI over agreement.py: upload paired measurements, pick the tool + reference columns,
# see the method-comparison figure + all the statistics, and DOWNLOAD everything (figure PNG/SVG/PDF,
# stats CSV, report, or a single ZIP with the lot). Reuses agreement.py, so numbers match the CLI.
#
# Run:   shiny run --reload plaque_stats/agreement/app_py.py     (or double-click the .bat)
# ---------------------------------------------------------------------------------------------
import base64
import io
import json
import os
import re
import sys
import tempfile
import zipfile

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from shiny import App, ui, render, reactive, req
from shiny.types import SilentException

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import agreement as ag          # the shared engine (same code as the CLI)
_lk = ag._lk                    # plaque_stats/legend_key.py, loaded by the engine (figure key rule)

# The three figures of the app: (tab label, engine `which`, file base name suffix).
# CT-R2 N8: the file names are agreement_<what>[_suffix], exactly the names ag.run() gives the
# files of the ZIP, so a stand-alone download and the same file inside the ZIP are called alike.
FIGURES = {"both": ("Both (A + B)", "both", ""),
           "a": ("A · Method comparison", "scatter", "_A_method_comparison"),
           "b": ("B · Bland–Altman", "bland", "_B_bland_altman")}
FIG_DPI = 300                    # the figure's dpi: the PNG, the ZIP and the stand-alone key use it


def fig_base(k, what):
    """File name stem of figure `k` (no extension): the engine's name for it in the ZIP."""
    return "agreement_%s%s" % (ag._safe(resolved_what(what)), FIGURES[k][2])


def make_fig(s, which, unit="mm", label_tool="Plaque Toolkit", label_manual="Fiji / ImageJ",
             title=None, show_key=True, show_stats=True):
    """One of the three figures, exactly as previewed and downloaded. ``which`` = both|scatter|bland."""
    if which == "both":
        return ag.make_figure(s, unit, label_tool, label_manual, title,
                              show_key=show_key, show_stats=show_stats)
    return ag.make_panel(s, which, unit, label_tool, label_manual, title,
                         show_key=show_key, show_stats=show_stats if which == "scatter" else True)


def key_text(fig):
    """CT-R1 F9: the legend text starter of the figure as drawn now (from its own key)."""
    key = _lk.from_figure(fig) if _lk is not None else None
    return _lk.text_starter(key) if key else "(this figure has no key entries)"


def key_zip_bytes(fig, base, dpi=FIG_DPI):
    """CT-R1 F9: the stand-alone legend key of `fig` in the figure's formats (PNG, SVG, PDF) plus
    the text starter, as one ZIP. Built from the figure's own key, so it always matches it.
    CT-R2 N8: `base` is fig_base(...) so the files carry the names they have in the results ZIP,
    and the PNG is rendered at the figure's dpi."""
    key = _lk.from_figure(fig) if _lk is not None else None
    buf = io.BytesIO()
    with tempfile.TemporaryDirectory() as tmp:
        with ag.figure_rc():
            paths = _lk.write_key_files(key, os.path.join(tmp, base), ["png", "svg", "pdf"],
                                         dpi=dpi) if key else []
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for fp in paths:
                z.write(fp, os.path.basename(fp))
    return buf.getvalue()

LEARN = """
<div style="max-width:840px;line-height:1.5">
<h4>What this tool answers</h4>
<p>Not “are the two measurements correlated?” but <b>“do they <i>agree</i>?”</b> — can the Plaque
Toolkit’s automatic measurement stand in for your manual reference, or is there a systematic
difference? Two methods can correlate almost perfectly and still disagree (e.g. one reads 10&nbsp;% high
on every plaque), so we report <b>agreement</b> statistics, not just correlation.</p>

<h4>What is actually being compared</h4>
<ul>
<li><b>The same quantity on both sides.</b> Each value is an <b>area-equivalent diameter</b> in mm —
the diameter of a circle with the same area, <code>d = 2·√(area/π)</code>. The tool derives the area
from the detected plaque outline; the manual side from your traced region (Fiji <i>Area</i> → the
identical formula). So it is a true like-for-like comparison.</li>
<li><b>One row = one plaque</b>; the two columns are the two methods. Plaques are <b>paired by row
order</b> — row 5 of the tool column is compared with row 5 of the manual column — so line the rows
up by plaque before you run it.</li>
</ul>

<h4>The statistics — what each one tells you</h4>
<table class="table table-sm" style="font-size:.92em">
<thead><tr><th>Statistic</th><th>What it answers</th><th>Good value</th></tr></thead>
<tbody>
<tr><td><b>Pearson r / R²</b></td><td><i>Association</i> — do the two rise and fall together? Stays
high even when one method is biased, so <b>never report it alone</b>.</td><td>→ 1, but not sufficient</td></tr>
<tr><td><b>ICC(A,1)</b></td><td><i>Agreement, bias included</i> — the headline reliability number
(two-way, absolute agreement).</td><td>&gt;0.90 excellent · 0.75–0.90 good · 0.5–0.75 moderate ·
&lt;0.5 poor (Koo &amp; Li 2016)</td></tr>
<tr><td><b>Lin’s CCC</b></td><td>Accuracy (dots on the identity line) <i>and</i> precision (tight
scatter) in one number.</td><td>→ 1</td></tr>
<tr><td><b>Mean bias</b></td><td>The systematic offset, <b>tool − reference</b>. The paired t-test asks
whether it differs from zero.</td><td>≈ 0 (and n.s.)</td></tr>
<tr><td><b>95% limits of agreement</b></td><td>The range containing ~95&nbsp;% of the plaque-by-plaque
differences — how interchangeable the methods are <i>in practice</i>.</td><td>narrow, relative to a
biologically meaningful size</td></tr>
<tr><td><b>Regression slope</b></td><td><i>Proportional bias</i> — does the gap grow with plaque size?
1.0 = the gap is the same at every size.</td><td>≈ 1.0</td></tr>
<tr><td><b>RMSE / MAE</b></td><td>The typical size of a single-plaque error.</td><td>small</td></tr>
</tbody></table>

<h4>Reading the figure</h4>
<ul>
<li><b>Panel A — Method comparison.</b> Each dot is a plaque (manual on x, tool on y). The dashed line
is perfect agreement (identity); the solid line is the fitted regression. Dots hugging the dashed line
= good agreement; a tilt away from it = proportional bias.</li>
<li><b>Panel B — Bland–Altman.</b> x = the plaque’s mean of the two methods, y = their difference. The
centre line is the mean bias; the dashed lines are the 95&nbsp;% limits of agreement. A flat cloud
centred on ~0 means the methods agree across all sizes; a slope, funnel, or offset flags a problem.</li>
</ul>

<h4>Report it like this</h4>
<p>Lead with agreement, not r: quote <b>ICC(A,1) with its 95&nbsp;% CI</b>, <b>Lin’s CCC</b>, and the
<b>bias with its 95&nbsp;% limits of agreement</b>. The <b>Statistics</b> tab writes this as a
paste-ready sentence for you.</p>

<div style="border-left:4px solid #b45309;background:#fff7ed;padding:.7em 1em;border-radius:6px;margin-top:1em">
<b>⚠ Get it right — three things that silently break the comparison</b>
<ol style="margin-bottom:0">
<li><b>Compare like with like.</b> Use the tool’s <code>DIAMETER_MM</code> against a manual
<i>area-equivalent</i> diameter, or area against area. Don’t pair a straight-line / Feret caliper
diameter against the area-equivalent one — for non-round plaques those are genuinely different numbers.
<b>If your two columns are areas</b> (e.g. the tool’s <code>AREA_MM2</code> and Fiji’s <i>Area</i>),
tick <b>“Columns are AREA → convert to diameter”</b> in the sidebar and the tool derives the
area-equivalent diameters for you (<code>d = 2·√(A/π)</code>, the same formula it uses internally) — so
you get the diameter result straight from an area sheet.</li>
<li><b>Use the same mm-per-pixel on both sides.</b> If the manual calibration differs from the app’s,
you inject a fake <b>proportional bias</b> that shows up as a regression <b>slope ≠ 1</b> — a
calibration artefact, not a real disagreement.</li>
<li><b>Align the rows.</b> Pairing is by position, and unequal-length columns are truncated to the
shorter one — so make sure row <i>i</i> is the same plaque in both columns.</li>
</ol>
</div>

<p style="margin-top:1em">Input recap: one row per plaque, two numeric columns (tool measurement and
manual reference). Open the <b>Interactive guide</b> tab for a live Bland–Altman demo — drag the
bias/spread sliders and watch ICC fall while r barely moves.</p>
</div>
"""

# --------------------------------------------------------------------------- server logic as plain
# functions (CT-R1 web), tested without a browser in tests/test_ct_r1_web.py.
_DELIMS = {",": "comma", ";": "semicolon", "\t": "tab", "|": "pipe"}
# CT-R2 N4: the default wording is the command-line tool's (`--what diameters`), read from the
# engine's own parser, so the paste-ready sentence opens exactly as the CLI's does.
AREA_UNIT, AREA_WHAT = "mm²", "areas"
DIAM_UNIT, DIAM_WHAT = "mm", ag.build_args().get_default("what")
BLANK_WHAT = "measurements"       # what the engine's sentence falls back to for an empty box


def resolved_what(what):
    """CT-R2 N4: the ONE wording used by the screen sentence, the ZIP and the file names."""
    return (what or "").strip() or BLANK_WHAT


class Stale(Exception):
    """The column pickers still hold the previous file's names: wait for them."""


def _to_number(col):
    """(float series, decimal comma used?) or (None, False) when the column is not numeric."""
    txt = col.astype(str).str.strip()
    blank = col.isna() | (txt == "")
    num = pd.to_numeric(txt.where(~blank), errors="coerce")
    if (num.isna() & ~blank).any():
        alt = pd.to_numeric(txt.str.replace(",", ".", regex=False).where(~blank), errors="coerce")
        if (alt.isna() & ~blank).any() or not txt[~blank].str.match(r"^[+-]?\d+,\d+$|^[+-]?\d+$").all():
            return None, False
        return alt.astype(float), True
    if num.notna().sum() == 0:
        return None, False
    return num.astype(float), False


def read_paired(path, name=None):
    """(DataFrame, note) for a CSV / TSV / TXT / XLSX of paired measurements (CT-R1 F4): the
    delimiter is detected from the header (comma, semicolon, tab, pipe), European decimal commas
    are read as numbers, lines starting with # are skipped, and a file that parses to one column
    is refused with a plain ValueError. (A small local reader: the frozen Agreement app does not
    ship the statistics engine's read_table.)"""
    name = name or os.path.basename(str(path))
    if str(name).lower().endswith((".xlsx", ".xls")):
        try:
            df = pd.read_excel(path)
        except Exception as e:                                # noqa: BLE001
            raise ValueError("could not read %s as a spreadsheet: %s" % (name, e))
        note = "read %d rows x %d columns (spreadsheet)" % df.shape
        sep = None
    else:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
            lines = [ln for ln in fh.read().splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
        if not lines:
            raise ValueError("%s is empty." % name)
        counts = {d: lines[0].count(d) for d in _DELIMS}
        sep = max(counts, key=lambda d: (counts[d], d == ","))
        if not counts[sep]:
            raise ValueError("%s was read as ONE column (%r). Expected two or more columns separated "
                             "by commas, semicolons or tabs, with a header row." % (name, lines[0][:60]))
        try:
            df = pd.read_csv(io.StringIO("\n".join(lines)), sep=sep, dtype=str, keep_default_na=False,
                             na_values=[""])
        except Exception as e:                                # noqa: BLE001
            raise ValueError("could not read %s as a %s-separated table: %s" % (name, _DELIMS[sep], e))
        note = "read %d rows x %d columns" % df.shape
        if sep != ",":
            note += "; %s-separated" % _DELIMS[sep]
    df.columns = [str(c).strip() for c in df.columns]
    comma = False
    for c in df.columns:
        if pd.api.types.is_numeric_dtype(df[c]):
            continue
        num, dc = _to_number(df[c])
        if num is not None:
            df[c] = num
            comma = comma or dc
    if comma:
        note += "; decimal commas read as decimal points"
    return df, note + "."


def numeric_cols(df):
    return [str(c) for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]


def id_like(name, series=None):
    """An identifier column (plaque_id, id, row, index, or the integers 1..n): never guessed as a
    measurement (CT-R1 F17: an id column guessed as 'tool' gave a bias of +59 mm)."""
    toks = ag._tokens(name)
    if any(t in ("id", "idx", "index", "row", "no", "number", "n") for t in toks):
        return True
    if series is not None:
        v = pd.to_numeric(series, errors="coerce").dropna()
        if len(v) > 2 and (v == v.round()).all() and (v.diff().dropna() == 1).all():
            return True
    return False


def is_area(name):
    toks = ag._tokens(name)
    return any(t.startswith("area") or t in ("mm2", "um2", "px2") for t in toks) or "mm²" in str(name)


def is_diam(name):
    """A column name that says diameter (diameter_mm, fiji_diam, dia)."""
    return any(t.startswith("diam") or t == "dia" for t in ag._tokens(name))


def column_kind(name):
    """'area' | 'diam' | None (the name does not say; a name that says both is not decided)."""
    a, d = is_area(name), is_diam(name)
    return "area" if (a and not d) else "diam" if (d and not a) else None


def _roles(cols):
    """(tool, manual) inside one group of columns: the hinted one keeps its role, the other
    column takes the other role; unhinted columns keep their file order."""
    manual = ag._find_col(cols, ag.MANUAL_HINTS)
    tool = ag._find_col(cols, ag.TOOL_HINTS, exclude=(manual,))
    if manual is None:
        manual = next((c for c in cols if c != tool), None)
    if tool is None:
        tool = next((c for c in cols if c != manual), None)
    return tool, manual


def guess_columns(df):
    """(tool, manual) default picks. CT-R2 N1: the two columns are a PAIR OF THE SAME QUANTITY
    (both diameters if a diameter pair exists, else both areas): an area never meets a diameter
    here (the CLI's per-column 'prefer diam' paired AREA_MM2 with fiji_diam). Columns whose
    names say neither are paired by their hints; only when no same-kind pair exists at all
    (e.g. one diameter + one area) the first two numeric columns are offered, and the mixed
    warning then stops the downloads. Id-like columns are skipped (CT-R1 F17)."""
    num = [c for c in numeric_cols(df) if not id_like(c, df[c])]
    for kind in ("diam", "area"):
        same = [c for c in num if column_kind(c) == kind]
        if len(same) >= 2:
            return _roles(same)
    unnamed = [c for c in num if column_kind(c) is None]
    if len(unnamed) >= 2:
        return _roles(unnamed)
    return _roles(num)


def mixed_quantities(tool, manual):
    """CT-R2 N1: True when one column looks like an area and the other like a diameter."""
    return {column_kind(tool or ""), column_kind(manual or "")} == {"area", "diam"}


MIXED_WARNING = ("Warning: one column looks like an area and the other like a diameter: agreement "
                 "between different quantities is meaningless. Change a column, or tick "
                 "“Compare anyway” under the column pickers; the downloads stay off until then.")


def downloads_blocked(tool, manual, anyway):
    """CT-R2 N1: the downloads are off while the picked pair mixes an area with a diameter."""
    return mixed_quantities(tool, manual) and not anyway


def quantity_text(name, convert, unit):
    """One side of the 'Compared:' line."""
    kind = column_kind(name)
    if convert:
        return "diameter (%s, converted from area)" % DIAM_UNIT
    return "%s (%s)" % ({"diam": "diameter", "area": "area"}.get(kind, "measurement"),
                        (unit or "").strip() or "no unit")


def compared_text(tool, manual, convert, unit):
    """CT-R2 N1: 'Compared: diameter (mm) vs diameter (mm)', under the column pickers."""
    return "Compared: %s vs %s" % (quantity_text(tool, convert, unit), quantity_text(manual, convert, unit))


def column_warnings(df, tool, manual, convert):
    """CT-R2 N9: plain warnings about the picked columns (the comparison still runs)."""
    out = []
    for role, c in (("Tool", tool), ("Reference", manual)):
        if c in df.columns and id_like(c, df[c]):
            out.append("Warning: the %s column “%s” looks like an identifier (a plaque number or "
                       "row index), not a measurement. Pick the measurement columns." % (role.lower(), c))
    if convert:
        for c in (tool, manual):
            if column_kind(c) == "diam":
                out.append("Warning: “Convert area” is ticked but the column “%s” looks like a "
                           "diameter: converting a diameter as if it were an area gives wrong "
                           "values. Untick it if the columns are already diameters." % c)
    return out


def unit_what_defaults(tool, manual, convert):
    """CT-R1 F6: area columns compared as areas are labelled as areas in mm²; with the
    conversion on they are diameters in mm."""
    if not convert and (is_area(tool) or is_area(manual)):
        return AREA_UNIT, AREA_WHAT
    return DIAM_UNIT, DIAM_WHAT


def effective_unit(convert, unit):
    return DIAM_UNIT if convert else (unit or "").strip()


def pair_values(df, tool, manual, convert=False):
    """(tool values, manual values, rows in file, rows dropped). Plain ValueError for the
    same column twice or fewer than 3 complete pairs (CT-R1 F16, F17)."""
    num = numeric_cols(df)
    if tool not in num or manual not in num:
        raise Stale()
    if tool == manual:
        raise ValueError("The tool and the reference column are the same column (%s). Pick the two "
                         "different methods." % tool)
    d = df[[tool, manual]].apply(pd.to_numeric, errors="coerce").dropna()
    if len(d) < 3:
        raise ValueError("Need at least 3 complete pairs (rows with a number in both columns); "
                         "found %d of %d rows." % (len(d), len(df)))
    t, m = d[tool].tolist(), d[manual].tolist()
    if convert:
        t, m = ag.area_to_diameter(t), ag.area_to_diameter(m)
    return t, m, len(df), len(df) - len(d)


def compute(df, tool, manual, convert=False):
    """The statistics on screen: ag.full_stats on the complete pairs + the row count."""
    t, m, n_rows, n_drop = pair_values(df, tool, manual, convert)
    s = ag.full_stats(t, m)
    s["_rows"], s["_dropped"] = n_rows, n_drop
    return s


def icc_na_reason(s):
    """CT-R2 N9: why the ICC interval is not available (never a bare 'n/a')."""
    n, icc = s["n"], s.get("icc")
    if n < ag.ICC_CI_MIN_N:
        return "needs %d pairs" % ag.ICC_CI_MIN_N
    if not ag._finite(icc):
        return "the ICC itself could not be computed"
    if icc >= 1.0:
        return "agreement is perfect, so the interval has no width"
    try:
        if ag._icc_ms(s["fiji"], s["tool"])[2] <= 0:
            return "the methods differ by a constant only, so there is no residual variance"
    except Exception:                                         # noqa: BLE001
        pass
    return "the interval cannot be computed when the methods differ by a very large offset"


def icc_cell(s):
    """CT-R1 F17 / CT-R2 N9: the interval, or 'n/a (reason)' - below the interval's minimum n
    and whenever the engine cannot compute one."""
    lo, hi = s.get("icc_lo"), s.get("icc_hi")
    if ag._finite(lo) and ag._finite(hi):
        ci = "[%.3f–%.3f]" % (lo, hi)
    else:
        ci = "[n/a (%s)]" % icc_na_reason(s)
    # the engine's rule (CT-R2 N8): the grade is the grade of the INTERVAL, none without one
    grade = ag.icc_grade_interval(lo, hi)
    return "%.3f  %s  (%s)" % (s["icc"], ci, ("%s, graded on the interval" % grade) if grade
                               else "no agreement grade without an interval")


def _num(v, fmt):
    return fmt % v if ag._finite(v) else "n/a"


def _signed(v, nd):
    """'%+.3f' that never prints '-0.000' (CT-R2 N2)."""
    if not ag._finite(v):
        return "n/a"
    t = "%+.*f" % (nd, v)
    return "+" + t[1:] if not t.strip("+-0.") else t


def pct_bias_defined(s):
    """CT-R2 N9: the engine divides the bias by the mean of the two methods; when that mean is
    near zero (|mean| < 10 % of the spread of the values) the percentage is meaningless."""
    g = (s["mean_tool"] + s["mean_fiji"]) / 2.0
    spread = ag._sd(list(s["tool"]) + list(s["fiji"]))
    return ag._finite(s.get("pct_bias")) and abs(g) >= 0.1 * spread and g != 0


def pct_bias_text(s):
    return "%s%%" % _num(s["pct_bias"], "%.1f") if pct_bias_defined(s) else "n/a: mean near zero"


def report_rows(s, u):
    """CT-R2 N2: THE statistics rows, (statistic, value) in the order of the ZIP report. The
    screen table renders them and zip_bytes writes the same rows into the report, so the two can
    never differ. One number format: 3 decimals, the slope 4, a sign only where it matters, and
    never '-0.000'."""
    drop = s.get("_dropped", 0)
    rows = [
        ("n pairs", "%d (of %d rows; %d dropped: a value missing or not a number)"
         % (s["n"], s.get("_rows", s["n"]), drop) if drop else "%d" % s["n"]),
        ("Pearson r (p)", "%s (%s)" % (_num(s["r"], "%.3f"), ag._pfmt(s["pearson_p"]))),
        ("R²", _num(s["r2"], "%.3f")),
        ("ICC(A,1) [95% CI]", icc_cell(s)),
        ("Lin's CCC", _num(s["ccc"], "%.3f")),
        ("mean bias (%s)" % u, "%s (%s)" % (_signed(s["bias"], 3), pct_bias_text(s))),
        ("bias vs 0 (paired t)", "t = %s, %s" % (_num(s["t_stat"], "%.2f"), ag._pstr(s["t_p"]))),
        ("95% limits of agreement", "%s to %s %s (bias ± 1.96 SD)"
         % (_signed(s["loa_lo"], 3), _signed(s["loa_hi"], 3), u)),
    ]
    if ag._finite(s.get("pred_lo")):
        rows.append(("95%% prediction interval, one new difference (n < %d)" % ag.PRED_N,
                     "%s to %s %s (bias ± t·SD·√(1+1/n))" % (_signed(s["pred_lo"], 3),
                                                              _signed(s["pred_hi"], 3), u)))
    rows += [
        ("%s95%% CI of each limit" % ("approximate " if s["n"] < ag.SMALL_N else ""),
         "±%s %s (Bland & Altman 1999)" % (_num(s.get("loa_ci_halfwidth"), "%.3f"), u)),
        ("proportional bias (difference ~ mean)", "slope %s, %s" % (
            _signed(s.get("ba_slope"), 4), ag._pstr(s.get("ba_slope_p", float("nan"))))),
        ("RMSE / MAE (%s)" % u, "%s / %s" % (_num(s["rmse"], "%.3f"), _num(s["mae"], "%.3f"))),
        ("regression (tool on ref)", "y = %s x %s  (slope 1.0 = no proportional bias)"
         % (_num(s["slope"], "%.3f"), _signed(s["intercept"], 3))),
    ]
    return rows


def stats_rows(s, u):
    return pd.DataFrame(report_rows(s, u), columns=["statistic", "value"])


def report_table_md(s, u):
    return "| statistic | value |\n|---|---|\n" + "".join("| %s | %s |\n" % r for r in report_rows(s, u))


def labels(opts):
    """Figure-safe text: a `$` or `\\` in a label or title never raises a mathtext error (F22)."""
    import re
    st = _lk.safe_text if _lk is not None else (lambda x: x)

    def one(x):
        x = st(x)
        # an odd `$` would pair with one in the OTHER label once the engine joins them into the
        # Bland-Altman axis label ("tool - reference"): escape it so each label prints as typed
        if (x.count("$") - x.count(r"\$")) % 2:
            x = re.sub(r"(?<!\\)\$", r"\\$", x)
        return x
    return {k: one(opts[k]) if opts.get(k) else opts.get(k) for k in ("label_tool", "label_manual", "title")}


def sentence_of(s, unit, what, label_tool, label_manual):
    """The paste-ready sentence: the engine's (word for word, the CLI's), except that a
    percentage bias over a near-zero mean is left out (CT-R2 N9; the engine's own rule that a
    statistic missing from `s` leaves its clause out)."""
    if not pct_bias_defined(s):
        s = dict(s, pct_bias=float("nan"))
    return ag.report_sentence(s, unit, resolved_what(what), label_tool, label_manual)


_NEG_ZERO = re.compile(r"(?<![\w.])-(0\.0+)(?!\d)")


def zip_bytes(df, tool, manual, opts, src_name=None, src_bytes=None):
    """CT-R1 F16/F23: the ZIP is ag.run on EXACTLY the pairs on screen (same columns, same rows,
    same conversion, unit and wording), so its numbers are the screen's; the input file is
    included and run_config names it instead of a server temp path. CT-R2 N2: the report's
    statistics table is written from report_rows(), the rows the screen shows."""
    pair_values(df, tool, manual, opts["convert_area"])             # same refusals as the screen
    safe = labels(opts)
    what = resolved_what(opts["what"])
    unit = DIAM_UNIT if opts["convert_area"] else opts["unit"]
    s_screen = compute(df, tool, manual, opts["convert_area"])
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "pairs.csv")
        df[[tool, manual]].apply(pd.to_numeric, errors="coerce").dropna().to_csv(src, index=False)
        outdir = os.path.join(tmp, "out")
        import contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            s_run = ag.run({"data": src, "tool": tool, "manual": manual, "unit": opts["unit"],
                            "what": what, "label_tool": safe["label_tool"],
                            "label_manual": safe["label_manual"], "title": safe["title"] or None,
                            "out": outdir, "show_key": opts["show_key"], "show_stats": opts["show_stats"],
                            "convert_area": opts["convert_area"], "formats": ["png", "svg", "pdf"],
                            "dpi": FIG_DPI})
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for fn in sorted(os.listdir(outdir)):
                p = os.path.join(outdir, fn)
                if fn.endswith(".md"):                             # the report shows labels as typed
                    txt = open(p, encoding="utf-8").read()
                    txt = _report_like_screen(txt, s_screen, s_run, unit, what, safe)
                    for k in ("label_tool", "label_manual"):
                        if opts.get(k) and safe[k] != opts[k]:
                            txt = txt.replace(safe[k], opts[k])
                    z.writestr(fn, txt)
                elif fn.startswith("agreement_stats") and fn.endswith(".csv") and not pct_bias_defined(s_screen):
                    st = pd.read_csv(p)
                    st["pct_bias"] = float("nan")                 # CT-R2 N9: blank, not -15304.7
                    z.writestr(fn, st.to_csv(index=False))
                elif fn.startswith("run_config") and fn.endswith(".json"):
                    cfg = json.load(open(p, encoding="utf-8"))
                    cfg["data"] = src_name or "example data"
                    if not pct_bias_defined(s_screen) and isinstance(cfg.get("stats"), dict):
                        cfg["stats"]["pct_bias"] = None
                    z.writestr(fn, json.dumps(cfg, indent=2, default=float))
                else:
                    z.write(p, fn)
            if src_bytes is not None:
                z.writestr("input_" + os.path.basename(src_name or "data.csv"), src_bytes)
        return buf.getvalue()


def _report_like_screen(txt, s, s_run, unit, what, safe):
    """The engine's report with the statistics table of the screen (CT-R2 N2), the sentence the
    screen shows, and no '-0.000'."""
    head, sep, rest = txt.partition("| statistic | value |")
    if sep:
        tail = rest.split("\n\n", 1)
        txt = head + report_table_md(s, unit).rstrip("\n") + ("\n\n" + tail[1] if len(tail) > 1 else "\n")
    eng = ag.report_sentence(s_run, unit, what, safe["label_tool"], safe["label_manual"])
    mine = sentence_of(s, unit, what, safe["label_tool"], safe["label_manual"])
    if eng != mine:
        txt = txt.replace(eng, mine)
    return _NEG_ZERO.sub(r"+\1", txt)


def png_bytes(fig):
    buf = io.BytesIO()
    with ag.figure_rc():
        fig.savefig(buf, format="png", dpi=FIG_DPI, bbox_inches="tight", facecolor="white")
    return buf.getvalue()


CSS = """
pre.shiny-text-output, .shiny-text-output { white-space: pre-wrap; word-break: break-word; }
.ct-fig img { width: 100%; height: auto; display: block; }
.ct-msg { white-space: pre-wrap; }
a.shiny-download-link.ct-off { pointer-events: none; opacity: .45; }
@media (max-width: 575.98px) {
  h1.bslib-page-title { white-space: normal; font-size: 1.15rem; }
  html body div.bslib-sidebar-layout.bslib-sidebar-layout { display: flex !important; flex-direction: column;
                                                        height: auto !important; min-height: 0; }
  html body div.bslib-sidebar-layout.bslib-sidebar-layout > * { flex: 0 0 auto; }
  html body div.bslib-sidebar-layout.bslib-sidebar-layout > .sidebar { order: -1; }
}
"""
JS = """
Shiny.addCustomMessageHandler('ct_downloads', function(ok) {
  document.querySelectorAll('a.shiny-download-link').forEach(function(a) {
    a.classList.toggle('ct-off', !ok); a.setAttribute('aria-disabled', ok ? 'false' : 'true');
  });
});
/* CT-R2 N14: "Load example data" empties the file box (it kept the old file's name) */
Shiny.addCustomMessageHandler('ct_clear_file', function(m) {
  var f = document.getElementById(m.id); if (!f) return;
  f.value = '';
  var g = f.closest('.input-group'); var t = g && g.querySelector('input[type=text]'); if (t) t.value = '';
  var pr = document.getElementById(m.id + '_progress');
  if (pr) { pr.style.visibility = 'hidden'; var b = pr.querySelector('.progress-bar');
            if (b) { b.style.width = '0%'; b.textContent = ''; } }
  Shiny.setInputValue(m.id, null);
});
Shiny.addCustomMessageHandler('ct_disable', function(m) {
  var e = document.getElementById(m.id); if (e) { e.disabled = !!m.off; }
});
"""


def _fig_tab(k):
    pre = "" if k == "both" else k + "_"
    return ui.nav_panel(
        FIGURES[k][0],
        # CT-R1 F7: the preview IS the PNG download, shown at the figure's own aspect
        ui.div(ui.output_ui("fig" if k == "both" else "fig_" + k), class_="ct-fig"),
        ui.div(ui.download_button("dl_%spng" % pre, "PNG"),
               ui.download_button("dl_%ssvg" % pre, "SVG (editable)"),
               ui.download_button("dl_%spdf" % pre, "PDF (editable)"),
               # CT-R1 F9: the figure rule's one-click legend key
               ui.download_button("dl_key_" + k, "Legend key (PNG + SVG + PDF)")),
        ui.h6("Legend text starter", style="margin-top:.6em"),
        ui.output_text_verbatim("key_text_" + k),
        ui.tags.button("Copy", class_="btn btn-sm btn-outline-secondary",
                       onclick="navigator.clipboard.writeText("
                               "document.getElementById('key_text_%s').innerText)" % k))


app_ui = ui.page_sidebar(
    ui.sidebar(
        ui.input_file("file", "Paired data (CSV / TSV / XLSX)",
                      accept=[".csv", ".tsv", ".txt", ".xlsx", ".xls"]),
        ui.input_action_button("load_example", "Load example data", class_="btn-sm"),
        ui.hr(),
        ui.output_ui("col_pickers"),
        ui.output_ui("compared_line"),                  # CT-R2 N1: what is being compared
        ui.input_checkbox("convert_area", "Columns are AREA → convert to diameter (d = 2·√(A/π))", False),
        ui.hr(),
        ui.input_text("unit", "Unit (mm while converting areas)", DIAM_UNIT),
        ui.input_text("what", "What was measured", DIAM_WHAT),
        ui.input_text("label_tool", "Tool label", "Plaque Toolkit"),
        ui.input_text("label_manual", "Reference label", "Fiji / ImageJ"),
        ui.input_text("title", "Figure title", ""),
        ui.hr(),
        ui.input_checkbox("show_key", "Place key on figure", True),   # CT-R1 F9: the ONE key switch
        ui.input_checkbox("show_stats", "Stats box on Panel A", True),
        width=330, open="always",
    ),
    ui.tags.style(CSS),
    ui.tags.script(JS),
    ui.output_ui("messages"),
    ui.navset_tab(
        ui.nav_panel("Figures", ui.navset_pill(*[_fig_tab(k) for k in FIGURES])),
        ui.nav_panel("Statistics",
                     ui.output_data_frame("stats_tbl"),
                     ui.h5("Paste-ready sentence"), ui.output_text_verbatim("sentence"),
                     ui.hr(),
                     ui.download_button("dl_all", "⬇ Download EVERYTHING (ZIP)", class_="btn-primary")),
        ui.nav_panel("Learn", ui.HTML(LEARN)),
        ui.nav_panel("Interactive guide",
                     ui.tags.iframe(src="guide/GUIDE.html",
                                    style="width:100%;height:80vh;border:1px solid #dde3e0;border-radius:8px;")),
    ),
    title="Agreement — tool vs manual  ·  Python / Shiny",
)


def server(input, output, session):
    raw = reactive.value(None)
    note = reactive.value("")
    load_error = reactive.value("")          # CT-R1 F19: a failed upload stays visible
    source = reactive.value((None, None))
    anyway = reactive.value(False)           # CT-R2 N1: "Compare anyway" (never kept across files)

    def _set(df, nt, name, data):
        raw.set(df); note.set(nt); source.set((name, data)); load_error.set("")
        anyway.set(False)
        ui.update_checkbox("compare_anyway", value=False)

    @reactive.effect
    @reactive.event(input.compare_anyway)
    def _anyway_changed():
        anyway.set(bool(input.compare_anyway()))

    @reactive.effect
    @reactive.event(input.file)
    def _load_file():
        f = input.file()
        if not f:
            return
        name, path = f[0]["name"], f[0]["datapath"]
        try:
            df, nt = read_paired(path, name)
            data = open(path, "rb").read()
        except Exception as e:                                    # noqa: BLE001
            raw.set(None); note.set(""); source.set((None, None))   # clear the old results
            load_error.set("Could not use %s: %s" % (name, e))
            return
        _set(df, nt, name, data)

    @reactive.effect
    @reactive.event(input.load_example)
    async def _load_example():
        await session.send_custom_message("ct_clear_file", {"id": "file"})
        p = os.path.join(HERE, "example_agreement.csv")
        if not os.path.exists(p):
            ag.make_example(p)
        df, nt = read_paired(p)
        _set(df, nt, "example_agreement.csv", open(p, "rb").read())

    def _in(name, default=None):
        try:
            return input[name]()
        except Exception:                                         # noqa: BLE001
            return default

    @render.ui
    def col_pickers():
        df = raw.get()
        if df is None:
            return ui.p("Upload a paired CSV (tool + manual columns), or click “Load example data”.")
        num = numeric_cols(df)
        if len(num) < 2:
            return ui.p("This file has %s numeric column%s (%s); agreement needs two: the tool's "
                        "measurement and the reference." % (len(num), "" if len(num) == 1 else "s",
                                                             ", ".join(num) or "none"),
                        class_="text-danger")
        tguess, mguess = guess_columns(df)
        return ui.TagList(
            ui.input_select("tool", "Tool column (method under test)", {c: c for c in num}, selected=tguess),
            ui.input_select("manual", "Manual / reference column", {c: c for c in num}, selected=mguess),
        )

    @reactive.effect
    def _labels_follow_columns():
        """CT-R1 F6: area columns are labelled mm² / plaque area unless converted; the defaults
        follow the columns, a unit or wording the user typed is kept."""
        t, m, conv = _in("tool"), _in("manual"), input.convert_area()
        if not t or not m:
            return
        u, w = unit_what_defaults(t, m, conv)
        with reactive.isolate():
            if input.unit() in (DIAM_UNIT, AREA_UNIT) and input.unit() != u:
                ui.update_text("unit", value=u)
            if input.what() in (DIAM_WHAT, AREA_WHAT) and input.what() != w:
                ui.update_text("what", value=w)

    @reactive.effect
    async def _unit_box():
        await session.send_custom_message("ct_disable", {"id": "unit", "off": bool(input.convert_area())})

    def _unit():
        return effective_unit(input.convert_area(), input.unit())

    def _blocked():
        """CT-R2 N1: an area compared with a diameter: no downloads unless 'Compare anyway'."""
        return downloads_blocked(_in("tool"), _in("manual"), anyway.get())

    def _open():
        """Raised inside a download handler while the downloads are off."""
        req(not _blocked())

    @render.ui
    def compared_line():
        t, m = _in("tool"), _in("manual")
        with reactive.isolate():
            on = anyway.get()
        if not t or not m or t == m:
            return ui.HTML("")
        out = [ui.p(compared_text(t, m, input.convert_area(), _unit()), class_="small text-muted mb-1")]
        if mixed_quantities(t, m):
            out.append(ui.input_checkbox("compare_anyway", "Compare anyway (area vs diameter)", on))
        return ui.TagList(*out)

    @reactive.calc
    def result():
        df = raw.get()
        if df is None:
            return {"wait": True}
        try:
            return {"ok": compute(df, _in("tool"), _in("manual"), input.convert_area())}
        except Stale:
            if len(numeric_cols(df)) < 2:
                return {"error": "the file needs two numeric columns (found: %s)."
                                 % (", ".join(numeric_cols(df)) or "none")}
            return {"wait": True}
        except SilentException:
            raise
        except (Exception, SystemExit) as e:                      # noqa: BLE001 -- never a dead session
            return {"error": str(e) or e.__class__.__name__}

    def stats():
        r = result()
        req("ok" in r)
        return r["ok"]

    @reactive.effect
    async def _downloads_enabled():
        await session.send_custom_message("ct_downloads", "ok" in result() and not _blocked())

    def _opts():
        return {"label_tool": input.label_tool(), "label_manual": input.label_manual(),
                "title": input.title(), "unit": input.unit(), "what": input.what(),
                "show_key": input.show_key(), "show_stats": input.show_stats(),
                "convert_area": input.convert_area()}

    def _mk(which):
        sf = labels(_opts())
        return make_fig(stats(), which, _unit(), sf["label_tool"], sf["label_manual"],
                        sf["title"] or None, show_key=input.show_key(), show_stats=input.show_stats())

    @render.ui
    def messages():
        r = result()
        out = []
        if load_error.get():
            out.append(ui.div(load_error.get(), class_="alert alert-danger ct-msg"))
        if "error" in r:
            out.append(ui.div("Cannot compare these columns: " + r["error"], class_="alert alert-warning ct-msg"))
        elif "ok" in r:
            s = r["ok"]
            if _blocked():
                out.append(ui.div(MIXED_WARNING, class_="alert alert-danger ct-msg"))
            elif mixed_quantities(_in("tool"), _in("manual")):
                out.append(ui.div("Warning: an area is being compared with a diameter (you ticked "
                                  "“Compare anyway”).", class_="alert alert-warning ct-msg small"))
            for w in column_warnings(raw.get(), _in("tool"), _in("manual"), input.convert_area()):
                out.append(ui.div(w, class_="alert alert-warning ct-msg small"))
            line = "File: %s %d pairs used" % (note.get(), s["n"])
            if s.get("_dropped"):
                line += "; %d of %d rows dropped (a value missing or not a number)" % (s["_dropped"], s["_rows"])
            out.append(ui.div(line + ".", class_="alert alert-light ct-msg small"))
            if not input.convert_area() and (is_area(_in("tool", "")) or is_area(_in("manual", ""))):
                out.append(ui.div("These are AREA columns, compared as areas (%s). Tick “Columns are AREA "
                                  "→ convert to diameter” to compare area-equivalent diameters in mm."
                                  % input.unit(), class_="alert alert-info ct-msg small"))
        return ui.TagList(*out)

    # one cached PNG per figure: the preview and the PNG download are the same bytes (F7)
    def _png_calc(which):
        @reactive.calc
        def _c():
            fig = _mk(which)
            try:
                return {"png": png_bytes(fig), "text": key_text(fig)}
            finally:
                plt.close(fig)
        return _c

    PNG = {k: _png_calc(FIGURES[k][1]) for k in FIGURES}

    def _wire(k):
        which = FIGURES[k][1]
        pre = "" if k == "both" else k + "_"

        def _img():
            src = "data:image/png;base64," + base64.b64encode(PNG[k]()["png"]).decode("ascii")
            return ui.img(src=src, alt=FIGURES[k][0] + " (the same image as the PNG download)")

        def _txt():
            return PNG[k]()["text"]

        def _png():
            _open()
            yield PNG[k]()["png"]

        def _vec(fmt):
            def _f():
                _open()
                fig = _mk(which)
                try:
                    buf = io.BytesIO()
                    with ag.figure_rc():
                        fig.savefig(buf, format=fmt, dpi=FIG_DPI, bbox_inches="tight", facecolor="white")
                    yield buf.getvalue()
                finally:
                    plt.close(fig)
            return _f

        def _key():
            _open()
            fig = _mk(which)
            try:
                yield key_zip_bytes(fig, fig_base(k, input.what()))
            finally:
                plt.close(fig)

        _img.__name__ = "fig" if k == "both" else "fig_" + k
        _txt.__name__ = "key_text_" + k
        _png.__name__ = "dl_%spng" % pre
        _key.__name__ = "dl_key_" + k
        render.ui(_img)
        render.text(_txt)
        render.download(filename=lambda: fig_base(k, input.what()) + ".png")(_png)
        for fmt in ("svg", "pdf"):
            f = _vec(fmt)
            f.__name__ = "dl_%s%s" % (pre, fmt)
            render.download(filename=(lambda fm=fmt: "%s.%s" % (fig_base(k, input.what()), fm)))(f)
        render.download(filename=lambda: fig_base(k, input.what()) + "_legend_key.zip")(_key)

    for _k in FIGURES:
        _wire(_k)

    @render.data_frame
    def stats_tbl():
        return stats_rows(stats(), _unit())

    @render.text
    def sentence():
        return sentence_of(stats(), _unit(), input.what(), input.label_tool(), input.label_manual())

    @render.download(filename=lambda: "agreement_results.zip")
    def dl_all():
        stats()
        _open()
        name, data = source.get()
        yield zip_bytes(raw.get(), _in("tool"), _in("manual"), _opts(), name, data)


app = App(app_ui, server, static_assets={"/guide": HERE})   # serves GUIDE.html + its assets at /guide/
