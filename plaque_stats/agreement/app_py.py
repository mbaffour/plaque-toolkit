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

HELP = """
<h4>Agreement (tool vs manual) — how to read it</h4>
<ul>
<li><b>Pearson r / R²</b> measure <i>association</i>, not agreement — two methods can correlate
perfectly yet disagree systematically, so never report r alone.</li>
<li><b>ICC(A,1)</b> is the agreement statistic (penalises bias): &lt;0.5 poor · 0.5–0.75 moderate ·
0.75–0.90 good · &gt;0.90 excellent (Koo &amp; Li 2016).</li>
<li><b>Lin's CCC</b> captures accuracy <i>and</i> precision together.</li>
<li><b>Bland–Altman</b>: <b>bias</b> = the systematic offset; <b>95% limits of agreement</b> = the
range within which ~95% of differences fall; a paired t-test says whether the bias differs from zero.</li>
<li><b>Regression slope</b> near 1.0 (a flat Bland–Altman cloud) = the disagreement does not grow
with size.</li>
</ul>
<p>Input: one row per plaque, two numeric columns (the tool measurement and the manual reference).</p>
"""

app_ui = ui.page_sidebar(
    ui.sidebar(
        ui.input_file("file", "Paired data (CSV / TSV / XLSX)",
                      accept=[".csv", ".tsv", ".txt", ".xlsx", ".xls"]),
        ui.input_action_button("load_example", "Load example data", class_="btn-sm"),
        ui.hr(),
        ui.output_ui("col_pickers"),
        ui.hr(),
        ui.input_text("unit", "Unit", "mm"),
        ui.input_text("what", "What was measured", "plaque diameter"),
        ui.input_text("label_tool", "Tool label", "Plaque Toolkit"),
        ui.input_text("label_manual", "Reference label", "Fiji / ImageJ"),
        ui.input_text("title", "Figure title", ""),
        width=330,
    ),
    ui.navset_tab(
        ui.nav_panel("Figure",
                     ui.output_plot("fig", height="440px"),
                     ui.div(ui.download_button("dl_png", "PNG"),
                            ui.download_button("dl_svg", "SVG (editable)"),
                            ui.download_button("dl_pdf", "PDF (editable)"))),
        ui.nav_panel("Statistics",
                     ui.output_data_frame("stats_tbl"),
                     ui.h5("Paste-ready sentence"), ui.output_text_verbatim("sentence"),
                     ui.hr(),
                     ui.download_button("dl_all", "⬇ Download EVERYTHING (ZIP)", class_="btn-primary")),
        ui.nav_panel("How to read it", ui.HTML(HELP)),
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

    @reactive.calc
    def stats():
        df = raw.get(); req(df is not None); req(input.tool()); req(input.manual())
        d = df[[input.tool(), input.manual()]].apply(pd.to_numeric, errors="coerce").dropna()
        if len(d) < 3:
            req(False)
        t, m = d[input.tool()].tolist(), d[input.manual()].tolist()
        s = ag.compute(t, m)
        s.update(ag.extra_stats(t, m))
        return s

    @render.plot
    def fig():
        return ag.make_figure(stats(), input.unit(), input.label_tool(),
                              input.label_manual(), input.title() or None)

    @render.data_frame
    def stats_tbl():
        s = stats(); u = input.unit()
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
        return ag.report_sentence(stats(), input.unit(), input.what(),
                                  input.label_tool(), input.label_manual())

    # ---- downloads ---------------------------------------------------------
    def _fig_bytes(fmt):
        fig = ag.make_figure(stats(), input.unit(), input.label_tool(),
                             input.label_manual(), input.title() or None)
        buf = io.BytesIO()
        fig.savefig(buf, format=fmt, dpi=300, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        return buf.getvalue()

    @render.download(filename=lambda: "agreement.png")
    def dl_png():
        yield _fig_bytes("png")

    @render.download(filename=lambda: "agreement.svg")
    def dl_svg():
        yield _fig_bytes("svg")

    @render.download(filename=lambda: "agreement.pdf")
    def dl_pdf():
        yield _fig_bytes("pdf")

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
                "formats": ["png", "svg", "pdf"], "dpi": 300})
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for fn in sorted(os.listdir(outdir)):
                z.write(os.path.join(outdir, fn), fn)
        yield buf.getvalue()


app = App(app_ui, server)
