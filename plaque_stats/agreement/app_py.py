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
import sys
import tempfile
import zipfile

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from shiny import App, ui, render, reactive, req

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import agreement as ag          # the shared engine (same code as the CLI)
_lk = ag._lk                    # plaque_stats/legend_key.py, loaded by the engine (figure key rule)

# The three figures of the app: (tab label, engine `which`, file base name).
FIGURES = {"both": ("Both (A + B)", "both", "agreement_both"),
           "a": ("A · Method comparison", "scatter", "agreement_A_method_comparison"),
           "b": ("B · Bland–Altman", "bland", "agreement_B_bland_altman")}


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


def key_zip_bytes(fig, base):
    """CT-R1 F9: the stand-alone legend key of `fig` in the figure's formats (PNG, SVG, PDF) plus
    the text starter, as one ZIP. Built from the figure's own key, so it always matches it."""
    key = _lk.from_figure(fig) if _lk is not None else None
    buf = io.BytesIO()
    with tempfile.TemporaryDirectory() as tmp:
        with ag.figure_rc():
            paths = _lk.write_key_files(key, os.path.join(tmp, base), ["png", "svg", "pdf"]) if key else []
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
AREA_UNIT, AREA_WHAT = "mm²", "plaque area"
DIAM_UNIT, DIAM_WHAT = "mm", "plaque diameter"


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


def guess_columns(df):
    """(tool, manual) default picks: named hints first, diameter columns preferred over areas
    (CT-R1 F6, the CLI does the same), id-like columns skipped (F17)."""
    num = [c for c in numeric_cols(df) if not id_like(c, df[c])]
    tool = ag._find_col(num, ag.TOOL_HINTS, prefer="diam") or (num[0] if num else None)
    manual = (ag._find_col(num, ag.MANUAL_HINTS, exclude=(tool,), prefer="diam")
              or next((c for c in num if c != tool), None))
    return tool, manual


def is_area(name):
    toks = ag._tokens(name)
    return any(t.startswith("area") or t in ("mm2", "um2", "px2") for t in toks) or "mm²" in str(name)


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


def icc_cell(s):
    """CT-R1 F17: 'n/a (needs 5 pairs)' rather than 'nan–nan' below the interval's minimum n."""
    lo, hi = s.get("icc_lo"), s.get("icc_hi")
    if ag._finite(lo) and ag._finite(hi):
        ci = "[%.3f–%.3f]" % (lo, hi)
    else:
        ci = "[n/a (needs %d pairs)]" % ag.ICC_CI_MIN_N if s["n"] < ag.ICC_CI_MIN_N else "[n/a]"
    return "%.3f  %s  (%s)" % (s["icc"], ci, ag.icc_grade(s["icc"]))


def _num(v, fmt):
    return fmt % v if ag._finite(v) else "n/a"


def stats_rows(s, u):
    return pd.DataFrame([
        ("n pairs", "%d (of %d rows; %d dropped: a value missing or not a number)"
         % (s["n"], s.get("_rows", s["n"]), s.get("_dropped", 0)) if s.get("_dropped") else "%d" % s["n"]),
        ("Pearson r (p)", "%s (%s)" % (_num(s["r"], "%.3f"), ag._pfmt(s["pearson_p"]))),
        ("R²", _num(s["r2"], "%.3f")),
        ("ICC(A,1) [95% CI]", icc_cell(s)),
        ("Lin's CCC", _num(s["ccc"], "%.3f")),
        ("mean bias (%s)" % u, "%+.3f  (%s%%)" % (s["bias"], _num(s["pct_bias"], "%.1f"))),
        ("bias vs 0 (paired t)", "t = %s, %s" % (_num(s["t_stat"], "%.2f"), ag._pstr(s["t_p"]))),
        ("95% limits of agreement", "%+.3f to %+.3f %s  (each ±%s, 95%% CI)"
         % (s["loa_lo"], s["loa_hi"], u, _num(s.get("loa_ci_halfwidth"), "%.3f"))),
        ("proportional bias (diff ~ mean)", "slope %s, %s" % (_num(s.get("ba_slope"), "%+.3f"),
                                                              ag._pstr(s.get("ba_slope_p", float("nan"))))),
        ("RMSE / MAE (%s)" % u, "%.3f / %.3f" % (s["rmse"], s["mae"])),
        ("regression (tool on ref)", "y = %s x %+.3f" % (_num(s["slope"], "%.3f"), s["intercept"])),
    ], columns=["statistic", "value"])


def labels(opts):
    """Figure-safe text: a `$` or `\\` in a label or title never raises a mathtext error (F22)."""
    st = _lk.safe_text if _lk is not None else (lambda x: x)
    return {k: st(opts[k]) if opts.get(k) else opts.get(k) for k in ("label_tool", "label_manual", "title")}


def zip_bytes(df, tool, manual, opts, src_name=None, src_bytes=None):
    """CT-R1 F16/F23: the ZIP is ag.run on EXACTLY the pairs on screen (same columns, same rows,
    same conversion, unit and wording), so its numbers are the screen's; the input file is
    included and run_config names it instead of a server temp path."""
    pair_values(df, tool, manual, opts["convert_area"])             # same refusals as the screen
    safe = labels(opts)
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "pairs.csv")
        df[[tool, manual]].apply(pd.to_numeric, errors="coerce").dropna().to_csv(src, index=False)
        outdir = os.path.join(tmp, "out")
        import contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            ag.run({"data": src, "tool": tool, "manual": manual, "unit": opts["unit"],
                    "what": opts["what"] or "measurement", "label_tool": safe["label_tool"],
                    "label_manual": safe["label_manual"], "title": safe["title"] or None,
                    "out": outdir, "show_key": opts["show_key"], "show_stats": opts["show_stats"],
                    "convert_area": opts["convert_area"], "formats": ["png", "svg", "pdf"], "dpi": 300})
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for fn in sorted(os.listdir(outdir)):
                p = os.path.join(outdir, fn)
                if fn.endswith(".md"):                             # the report shows labels as typed
                    txt = open(p, encoding="utf-8").read()
                    for k in ("label_tool", "label_manual"):
                        if opts.get(k) and safe[k] != opts[k]:
                            txt = txt.replace(safe[k], opts[k])
                    z.writestr(fn, txt)
                elif fn.startswith("run_config") and fn.endswith(".json"):
                    cfg = json.load(open(p, encoding="utf-8"))
                    cfg["data"] = src_name or "example data"
                    z.writestr(fn, json.dumps(cfg, indent=2, default=float))
                else:
                    z.write(p, fn)
            if src_bytes is not None:
                z.writestr("input_" + os.path.basename(src_name or "data.csv"), src_bytes)
        return buf.getvalue()


def png_bytes(fig):
    buf = io.BytesIO()
    with ag.figure_rc():
        fig.savefig(buf, format="png", dpi=300, bbox_inches="tight", facecolor="white")
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

    def _set(df, nt, name, data):
        raw.set(df); note.set(nt); source.set((name, data)); load_error.set("")

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
    def _load_example():
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
        except (ValueError, ZeroDivisionError, SystemExit) as e:
            return {"error": str(e)}

    def stats():
        r = result()
        req("ok" in r)
        return r["ok"]

    @reactive.effect
    async def _downloads_enabled():
        await session.send_custom_message("ct_downloads", "ok" in result())

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
        which, base = FIGURES[k][1], FIGURES[k][2]
        pre = "" if k == "both" else k + "_"

        def _img():
            src = "data:image/png;base64," + base64.b64encode(PNG[k]()["png"]).decode("ascii")
            return ui.img(src=src, alt=FIGURES[k][0] + " (the same image as the PNG download)")

        def _txt():
            return PNG[k]()["text"]

        def _png():
            yield PNG[k]()["png"]

        def _vec(fmt):
            def _f():
                fig = _mk(which)
                try:
                    buf = io.BytesIO()
                    with ag.figure_rc():
                        fig.savefig(buf, format=fmt, dpi=300, bbox_inches="tight", facecolor="white")
                    yield buf.getvalue()
                finally:
                    plt.close(fig)
            return _f

        def _key():
            fig = _mk(which)
            try:
                yield key_zip_bytes(fig, base)
            finally:
                plt.close(fig)

        _img.__name__ = "fig" if k == "both" else "fig_" + k
        _txt.__name__ = "key_text_" + k
        _png.__name__ = "dl_%spng" % pre
        _key.__name__ = "dl_key_" + k
        render.ui(_img)
        render.text(_txt)
        render.download(filename=lambda: base + ".png")(_png)
        for fmt in ("svg", "pdf"):
            f = _vec(fmt)
            f.__name__ = "dl_%s%s" % (pre, fmt)
            render.download(filename=(lambda fm=fmt: "%s.%s" % (base, fm)))(f)
        render.download(filename=lambda: base + "_legend_key.zip")(_key)

    for _k in FIGURES:
        _wire(_k)

    @render.data_frame
    def stats_tbl():
        return stats_rows(stats(), _unit())

    @render.text
    def sentence():
        return ag.report_sentence(stats(), _unit(), input.what(), input.label_tool(), input.label_manual())

    @render.download(filename=lambda: "agreement_results.zip")
    def dl_all():
        stats()
        name, data = source.get()
        yield zip_bytes(raw.get(), _in("tool"), _in("manual"), _opts(), name, data)


app = App(app_ui, server, static_assets={"/guide": HERE})   # serves GUIDE.html + its assets at /guide/
