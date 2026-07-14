# app_py.py — Agreement (tool vs manual) as a Shiny for Python browser app.
# ---------------------------------------------------------------------------------------------
# A browser GUI over agreement.py: upload paired measurements, pick the tool + reference columns,
# see the method-comparison figure + all the statistics, and DOWNLOAD everything (figure PNG/SVG/PDF,
# stats CSV, report, or a single ZIP with the lot). Reuses agreement.py, so numbers match the CLI.
#
# Run:   shiny run --reload plaque_stats/agreement/app_py.py     (or double-click the .bat)
# ---------------------------------------------------------------------------------------------
import io
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

app_ui = ui.page_sidebar(
    ui.sidebar(
        ui.input_file("file", "Paired data (CSV / TSV / XLSX)",
                      accept=[".csv", ".tsv", ".txt", ".xlsx", ".xls"]),
        ui.input_action_button("load_example", "Load example data", class_="btn-sm"),
        ui.hr(),
        ui.output_ui("col_pickers"),
        ui.input_checkbox("convert_area", "Columns are AREA → convert to diameter (d = 2·√(A/π))", False),
        ui.hr(),
        ui.input_text("unit", "Unit", "mm"),
        ui.input_text("what", "What was measured", "plaque diameter"),
        ui.input_text("label_tool", "Tool label", "Plaque Toolkit"),
        ui.input_text("label_manual", "Reference label", "Fiji / ImageJ"),
        ui.input_text("title", "Figure title", ""),
        ui.hr(),
        ui.input_checkbox("show_key", "Line / point key (legend)", True),
        ui.input_checkbox("show_stats", "Stats box on Panel A", True),
        width=330,
    ),
    ui.navset_tab(
        ui.nav_panel("Figures",
                     ui.navset_pill(
                         ui.nav_panel("Both (A + B)",
                                      ui.output_plot("fig", height="440px"),
                                      ui.div(ui.download_button("dl_png", "PNG"),
                                             ui.download_button("dl_svg", "SVG (editable)"),
                                             ui.download_button("dl_pdf", "PDF (editable)"))),
                         ui.nav_panel("A · Method comparison",
                                      ui.output_plot("fig_a", height="470px"),
                                      ui.div(ui.download_button("dl_a_png", "PNG"),
                                             ui.download_button("dl_a_svg", "SVG (editable)"),
                                             ui.download_button("dl_a_pdf", "PDF (editable)"))),
                         ui.nav_panel("B · Bland–Altman",
                                      ui.output_plot("fig_b", height="470px"),
                                      ui.div(ui.download_button("dl_b_png", "PNG"),
                                             ui.download_button("dl_b_svg", "SVG (editable)"),
                                             ui.download_button("dl_b_pdf", "PDF (editable)"))),
                     )),
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

    @reactive.effect
    @reactive.event(input.file)
    def _load_file():
        f = input.file()
        if not f:
            return
        name = f[0]["name"].lower(); path = f[0]["datapath"]
        try:
            if name.endswith((".xlsx", ".xls")):
                raw.set(pd.read_excel(path))
            else:
                sep = "\t" if name.endswith((".tsv", ".txt")) else ","
                raw.set(pd.read_csv(path, sep=sep, comment="#"))
        except Exception as e:                                    # noqa: BLE001
            ui.notification_show("Could not read file: %s" % e, type="error")

    @reactive.effect
    @reactive.event(input.load_example)
    def _load_example():
        p = os.path.join(HERE, "example_agreement.csv")
        if not os.path.exists(p):
            ag.make_example(p)
        raw.set(pd.read_csv(p))

    @render.ui
    def col_pickers():
        df = raw.get()
        if df is None:
            return ui.p("Upload a paired CSV (tool + manual columns), or click “Load example data”.")
        num = [str(c) for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
        tguess = ag._find_col(df.columns, ag.TOOL_HINTS) or (num[0] if num else None)
        mguess = ag._find_col(df.columns, ag.MANUAL_HINTS) or (num[1] if len(num) > 1 else None)
        return ui.TagList(
            ui.input_select("tool", "Tool column (method under test)", {c: c for c in num}, selected=tguess),
            ui.input_select("manual", "Manual / reference column", {c: c for c in num}, selected=mguess),
        )

    def _unit():
        # diameter is always mm when we convert areas, regardless of the Unit textbox
        return "mm" if input.convert_area() else input.unit()

    @reactive.calc
    def stats():
        df = raw.get(); req(df is not None); req(input.tool()); req(input.manual())
        d = df[[input.tool(), input.manual()]].apply(pd.to_numeric, errors="coerce").dropna()
        if len(d) < 3:
            req(False)
        t, m = d[input.tool()].tolist(), d[input.manual()].tolist()
        if input.convert_area():                 # AREA columns → area-equivalent diameter
            t, m = ag.area_to_diameter(t), ag.area_to_diameter(m)
        s = ag.compute(t, m)
        s.update(ag.extra_stats(t, m))
        return s

    def _mk_both():
        return ag.make_figure(stats(), _unit(), input.label_tool(),
                              input.label_manual(), input.title() or None,
                              show_key=input.show_key(), show_stats=input.show_stats())

    def _mk_panel(which):
        return ag.make_panel(stats(), which, _unit(), input.label_tool(),
                             input.label_manual(), input.title() or None,
                             show_key=input.show_key(), show_stats=input.show_stats())

    @render.plot
    def fig():
        return _mk_both()

    @render.plot
    def fig_a():
        return _mk_panel("scatter")

    @render.plot
    def fig_b():
        return _mk_panel("bland")

    @render.data_frame
    def stats_tbl():
        s = stats(); u = _unit()
        rows = [
            ("n pairs", "%d" % s["n"]),
            ("Pearson r (p)", "%.3f (%s)" % (s["r"], ag._pfmt(s["pearson_p"]))),
            ("R²", "%.3f" % s["r2"]),
            ("ICC(A,1) [95% CI]", "%.3f  [%.3f–%.3f]  (%s)" % (s["icc"], s["icc_lo"], s["icc_hi"], ag.icc_grade(s["icc"]))),
            ("Lin's CCC", "%.3f" % s["ccc"]),
            ("mean bias (%s)" % u, "%+.3f  (%.1f%%)" % (s["bias"], s["pct_bias"])),
            ("bias vs 0 (paired t)", "t = %.2f, p = %s" % (s["t_stat"], ag._pfmt(s["t_p"]))),
            ("95%% limits of agreement", "%+.3f to %+.3f %s" % (s["loa_lo"], s["loa_hi"], u)),
            ("RMSE / MAE (%s)" % u, "%.3f / %.3f" % (s["rmse"], s["mae"])),
            ("regression (tool on ref)", "y = %.3f x %+.3f" % (s["slope"], s["intercept"])),
        ]
        return pd.DataFrame(rows, columns=["statistic", "value"])

    @render.text
    def sentence():
        return ag.report_sentence(stats(), _unit(), input.what(),
                                  input.label_tool(), input.label_manual())

    # ---- downloads ---------------------------------------------------------
    def _bytes(make, fmt):
        fig = make()
        buf = io.BytesIO()
        fig.savefig(buf, format=fmt, dpi=300, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        return buf.getvalue()

    @render.download(filename=lambda: "agreement_both.png")
    def dl_png():
        yield _bytes(_mk_both, "png")

    @render.download(filename=lambda: "agreement_both.svg")
    def dl_svg():
        yield _bytes(_mk_both, "svg")

    @render.download(filename=lambda: "agreement_both.pdf")
    def dl_pdf():
        yield _bytes(_mk_both, "pdf")

    @render.download(filename=lambda: "agreement_A_method_comparison.png")
    def dl_a_png():
        yield _bytes(lambda: _mk_panel("scatter"), "png")

    @render.download(filename=lambda: "agreement_A_method_comparison.svg")
    def dl_a_svg():
        yield _bytes(lambda: _mk_panel("scatter"), "svg")

    @render.download(filename=lambda: "agreement_A_method_comparison.pdf")
    def dl_a_pdf():
        yield _bytes(lambda: _mk_panel("scatter"), "pdf")

    @render.download(filename=lambda: "agreement_B_bland_altman.png")
    def dl_b_png():
        yield _bytes(lambda: _mk_panel("bland"), "png")

    @render.download(filename=lambda: "agreement_B_bland_altman.svg")
    def dl_b_svg():
        yield _bytes(lambda: _mk_panel("bland"), "svg")

    @render.download(filename=lambda: "agreement_B_bland_altman.pdf")
    def dl_b_pdf():
        yield _bytes(lambda: _mk_panel("bland"), "pdf")

    @render.download(filename=lambda: "agreement_results.zip")
    def dl_all():
        df = raw.get(); req(df is not None)
        tmp = tempfile.mkdtemp()
        src = os.path.join(tmp, "_paired.csv")
        df[[input.tool(), input.manual()]].to_csv(src, index=False)
        outdir = os.path.join(tmp, "out")
        ag.run({"data": src, "tool": input.tool(), "manual": input.manual(),
                "unit": input.unit(), "what": input.what() or "measurement",
                "label_tool": input.label_tool(), "label_manual": input.label_manual(),
                "title": input.title() or None, "out": outdir,
                "show_key": input.show_key(), "show_stats": input.show_stats(),
                "convert_area": input.convert_area(),
                "formats": ["png", "svg", "pdf"], "dpi": 300})
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for fn in sorted(os.listdir(outdir)):
                z.write(os.path.join(outdir, fn), fn)
        yield buf.getvalue()


app = App(app_ui, server, static_assets={"/guide": HERE})   # serves GUIDE.html + its assets at /guide/
