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
# CT-R3 F8/F10: the reader and the column-role guess are the ENGINE's (the command line calls the
# same functions), so the three front-ends cannot drift.
_DELIMS = ag._DELIMS
# CT-R2 N4: the default wording is the command-line tool's (`--what diameters`), the engine's own.
AREA_UNIT, AREA_WHAT = "mm²", "areas"
DIAM_UNIT, DIAM_WHAT = "mm", ag.DEFAULT_WHAT
BLANK_WHAT = "measurements"       # what the engine's sentence falls back to for an empty box


def resolved_what(what):
    """CT-R2 N4: the ONE wording used by the screen sentence, the ZIP and the file names."""
    return (what or "").strip() or BLANK_WHAT


class Stale(Exception):
    """The column pickers still hold the previous file's names: wait for them."""


read_paired = ag.read_paired
_to_number = ag._to_number


def numeric_cols(df):
    return [str(c) for c in ag.numeric_cols(df)]


id_like = ag.id_like
is_area = ag.is_area
is_diam = ag.is_diam
column_kind = ag.column_kind
_roles = ag._roles
guess_columns = ag.guess_columns
mixed_quantities = ag.mixed_quantities


MIXED_WARNING = ("Warning: one column looks like an area and the other like a diameter: agreement "
                 "between different quantities is meaningless. Change a column, or tick "
                 "“Compare anyway” under the column pickers; the downloads stay off until then.")


CONVERT_WARNING = ("Warning: “Convert area” is ticked but %s. Converting a diameter as if it were "
                   "an area gives wrong values. Untick “Convert area”, or tick “Compare anyway” "
                   "under the column pickers; the downloads stay off until then.")


def convert_problem(df, tool, manual, convert):
    """CT-R3 F1/F5: '' or the reason why “Convert area” does not fit the picked columns. The rule:
    a column is NOT an area when its NAME says diameter (diameter_mm, fiji_diam, dia) or gives a
    length unit without saying area (toolkit_mm, size_px), or when it
    holds a negative number (an area cannot be negative, and the conversion would silently turn
    it into a zero diameter). The values alone cannot tell a diameter from an area."""
    if not convert:
        return ""
    bad = []
    for c in (tool, manual):
        if not c:
            continue
        if column_kind(c) == "diam" or ag.is_length(c):
            bad.append("the column “%s” looks like a diameter (a length, not an area)" % c)
        elif df is not None and c in df.columns and (pd.to_numeric(df[c], errors="coerce") < 0).any():
            bad.append("the column “%s” holds negative values, so it cannot be an area" % c)
    return CONVERT_WARNING % " and ".join(bad) if bad else ""


def downloads_blocked(tool, manual, anyway, df=None, convert=False):
    """CT-R2 N1 / CT-R3 F1: the downloads are off while the picked pair mixes an area with a
    diameter, or “Convert area” is ticked on columns that are not both areas, until “Compare
    anyway”."""
    off = mixed_quantities(tool, manual) or bool(convert_problem(df, tool, manual, convert))
    return off and not anyway


BLOCKED_MESSAGE = ("The downloads are off: the picked columns do not fit together (see the red "
                   "message above the tabs). Fix the columns, or tick “Compare anyway” under the "
                   "column pickers.")


def quantity_text(name, convert, unit):
    """One side of the 'Compared:' line."""
    kind = column_kind(name)
    if convert:
        if kind == "diam" or ag.is_length(name):      # CT-R3 F5: never claim a diameter was 'converted from area'
            return "diameter (%s), converted as if it were an area" % DIAM_UNIT
        return "diameter (%s, converted from area)" % DIAM_UNIT
    u = (unit or "").strip() or "no unit"
    if kind == "diam" and u == AREA_UNIT:          # the one Unit box follows an area column
        u = DIAM_UNIT
    elif kind == "area" and u == DIAM_UNIT:
        u = AREA_UNIT
    return "%s (%s)" % ({"diam": "diameter", "area": "area"}.get(kind, "measurement"), u)


def compared_text(tool, manual, convert, unit):
    """CT-R2 N1: 'Compared: diameter (mm) vs diameter (mm)', under the column pickers."""
    return "Compared: %s vs %s" % (quantity_text(tool, convert, unit), quantity_text(manual, convert, unit))


def column_warnings(df, tool, manual, convert):
    """CT-R2 N9: plain warnings about the picked columns (the comparison still runs). (The
    “Convert area” mismatch is a blocking message of its own, convert_problem.)"""
    out = []
    for role, c in (("Tool", tool), ("Reference", manual)):
        if c in df.columns and id_like(c, df[c]):
            out.append("Warning: the %s column “%s” looks like an identifier (a plaque number or "
                       "row index), not a measurement. Pick the measurement columns." % (role.lower(), c))
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
    """(tool values, manual values, rows in file, rows dropped): the engine's pairing; a
    picker that still holds the previous file's column names waits (Stale)."""
    num = numeric_cols(df)
    if tool not in num or manual not in num:
        raise Stale()
    return ag.pair_values(df, tool, manual, convert)


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
        ci = "[%s to %s]" % (ag._plain(lo), ag._plain(hi))
    else:
        ci = "[n/a (%s)]" % icc_na_reason(s)
    # the engine's rule (CT-R2 N8): the grade is the grade of the INTERVAL, none without one
    grade = ag.icc_grade_interval(lo, hi)
    return "%.3f  %s  (%s)" % (s["icc"], ci, ("%s, graded on the interval" % grade) if grade
                               else "no agreement grade without an interval")


def _num(v, fmt):
    return fmt % v if ag._finite(v) else "n/a"


def _signed(v, nd):
    """'%+.3f' that never prints '-0.000' (CT-R2 N2): the engine's."""
    return ag._signed(v, nd)


def pct_bias_defined(s):
    """CT-R3 F2: the rule lives in the engine (compute() leaves the percentage NaN over a
    near-zero mean, so the sentence, the tables and the CSV all leave it out)."""
    return ag._finite(s.get("pct_bias"))


pct_bias_text = ag.pct_bias_text


def report_rows(s, u):
    """CT-R2 N2: THE statistics rows, (statistic, value) in the order of the ZIP report. The
    screen table renders them and zip_bytes writes the same rows into the report, so the two can
    never differ. One number format: 3 decimals, the slope 4, a sign only where it matters, and
    never '-0.000'."""
    drop = s.get("_dropped", 0)
    few, na = ag._report_few(s), ag.NA_FEW        # CT-R3 F7: below 5 pairs r, ICC, slope are not given
    rows = [
        ("n pairs", "%d (of %d rows; %d dropped: %s)" % (s["n"], s.get("_rows", s["n"]), drop, ag.DROP_REASON)
         if drop else "%d" % s["n"]),
        ("Pearson r (p)", na if few else "%s (%s)" % (_num(s["r"], "%.3f"), ag._pfmt(s["pearson_p"]))),
        ("R²", na if few else _num(s["r2"], "%.3f")),
        ("ICC(A,1) [95% CI]", na if few else icc_cell(s)),
        ("Lin's CCC", na if few else _num(s["ccc"], "%.3f")),
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
        ("proportional bias (difference ~ mean)", na if few else "slope %s, %s" % (
            _signed(s.get("ba_slope"), 4), ag._pstr(s.get("ba_slope_p", float("nan"))))),
        ("RMSE / MAE (%s)" % u, "%s / %s" % (_num(s["rmse"], "%.3f"), _num(s["mae"], "%.3f"))),
        ("regression (tool on ref)", na if few else "y = %s x %s  (slope 1.0 = no proportional bias)"
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
    """The paste-ready sentence: the engine's, word for word (the CLI's). CT-R3 F2: the
    near-zero-mean rule for the percentage bias is the engine's own now."""
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
                elif fn.startswith("run_config") and fn.endswith(".json"):
                    cfg = json.load(open(p, encoding="utf-8"))
                    cfg["data"] = src_name or "example data"
                    cfg["rows_in_file"], cfg["rows_dropped"] = s_screen["_rows"], s_screen["_dropped"]
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
    dropped = ag.drop_text(s.get("_dropped", 0), s.get("_rows", 0))
    if dropped and "_%s._" % dropped not in txt:                 # CT-R3 F8: the report says it too
        txt = txt.replace("| statistic | value |", "_%s._\n\n| statistic | value |" % dropped, 1)
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
a.shiny-download-link.ct-off { opacity: .45; cursor: not-allowed; }
#ct_dl_msg { position: fixed; left: 50%; bottom: 1rem; transform: translateX(-50%); z-index: 2000;
             max-width: min(34rem, 92vw); padding: .6rem .9rem; border-radius: 8px; display: none;
             background: #7f1d1d; color: #fff; box-shadow: 0 4px 16px rgba(0,0,0,.3); }
a.ct-full { font-size: .85rem; }
@media (max-width: 575.98px) {
  h1.bslib-page-title { white-space: normal; font-size: 1.15rem; }
  html body div.bslib-sidebar-layout.bslib-sidebar-layout { display: flex !important; flex-direction: column;
                                                        height: auto !important; min-height: 0; }
  html body div.bslib-sidebar-layout.bslib-sidebar-layout > * { flex: 0 0 auto; }
  html body div.bslib-sidebar-layout.bslib-sidebar-layout > .sidebar { order: -1; }
}
"""
JS = """
/* CT-R3 F5: a blocked download says why instead of starting and cancelling */
var ctDlMsg = '';
Shiny.addCustomMessageHandler('ct_downloads', function(m) {
  ctDlMsg = m.ok ? '' : m.msg;
  document.querySelectorAll('a.shiny-download-link').forEach(function(a) {
    a.classList.toggle('ct-off', !m.ok); a.setAttribute('aria-disabled', m.ok ? 'false' : 'true');
  });
});
document.addEventListener('click', function(e) {
  var a = e.target.closest && e.target.closest('a.shiny-download-link.ct-off');
  if (!a) return;
  e.preventDefault(); e.stopPropagation(); e.stopImmediatePropagation();
  var box = document.getElementById('ct_dl_msg');
  if (!box) { box = document.createElement('div'); box.id = 'ct_dl_msg'; box.setAttribute('role', 'alert');
              document.body.appendChild(box); }
  box.textContent = ctDlMsg || 'The downloads are off.'; box.style.display = 'block';
  clearTimeout(box._t); box._t = setTimeout(function() { box.style.display = 'none'; }, 7000);
}, true);
/* CT-R3 F11: "open full size" shows the preview at its own size in a new tab (at phone width the
   figure text is too small to read in the page) */
function ctOpenFull(a) {
  var img = a.closest('.tab-pane').querySelector('.ct-fig img'); if (!img) return false;
  fetch(img.src).then(function(r) { return r.blob(); }).then(function(b) {
    window.open(URL.createObjectURL(b), '_blank');
  });
  return false;
}
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
        ui.tags.a("open full size", href="#", class_="ct-full", onclick="return ctOpenFull(this)",
                  title="Open the figure at its own size in a new tab"),
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

    def _reset_gates():
        """CT-R3 F1/F4: “Compare anyway” and “Convert area” are decisions about ONE pair of
        columns: a new file, “Load example data” and a change of the chosen pair all reset them."""
        anyway.set(False)
        ui.update_checkbox("compare_anyway", value=False)
        ui.update_checkbox("convert_area", value=False)

    def _set(df, nt, name, data):
        raw.set(df); note.set(nt); source.set((name, data)); load_error.set("")
        _reset_gates()

    @reactive.effect
    @reactive.event(input.tool, input.manual, ignore_init=True)
    def _pair_changed():
        _reset_gates()

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
        """CT-R2 N1 / CT-R3 F1: an area compared with a diameter, or “Convert area” on columns that
        are not both areas: no downloads unless 'Compare anyway'."""
        return downloads_blocked(_in("tool"), _in("manual"), anyway.get(), raw.get(), input.convert_area())

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
        elif convert_problem(raw.get(), t, m, input.convert_area()):
            out.append(ui.input_checkbox("compare_anyway", "Compare anyway (Convert area on non-area columns)", on))
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
        await session.send_custom_message("ct_downloads", {"ok": "ok" in result() and not _blocked(),
                                                             "msg": BLOCKED_MESSAGE if "ok" in result()
                                                             else "There is no result to download yet."})

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
            cp = convert_problem(raw.get(), _in("tool"), _in("manual"), input.convert_area())
            if _blocked():
                out.append(ui.div(MIXED_WARNING if mixed_quantities(_in("tool"), _in("manual")) else cp,
                                  class_="alert alert-danger ct-msg"))
            elif mixed_quantities(_in("tool"), _in("manual")) or cp:
                out.append(ui.div("Warning: %s (you ticked “Compare anyway”)." % (
                    "an area is being compared with a diameter" if mixed_quantities(_in("tool"), _in("manual"))
                    else "“Convert area” is applied to columns that are not both areas"),
                    class_="alert alert-warning ct-msg small"))
            for w in column_warnings(raw.get(), _in("tool"), _in("manual"), input.convert_area()):
                out.append(ui.div(w, class_="alert alert-warning ct-msg small"))
            line = "File: %s %d pairs used" % (note.get(), s["n"])
            if s.get("_dropped"):
                line += "; " + ag.drop_text(s["_dropped"], s["_rows"])
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
