# app_py.py — Plaque Stats & Violins as a Shiny for Python web app.
# ---------------------------------------------------------------------------------------------
# A browser-based (HTML) app that reuses plaque_stats.py DIRECTLY — the same normalize(),
# group_summary(), run_stats() and plot_violin() the CLI and R app use — so the figures and
# statistics are byte-for-byte identical. No re-implementation.
#
# Run:   shiny run --reload plaque_stats/app_py.py     (opens http://127.0.0.1:8000)
#   first time only:  pip install shiny openpyxl        (plus plaque_stats' deps)
#
# Same tidy data format as the CLI / R app (see README.md):
#   WIDE: group,replicate,diameter_mm,area_mm2,turbidity   |   LONG: group,replicate,metric,value
# ---------------------------------------------------------------------------------------------
import io
import os
import sys
import tempfile

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from shiny import App, ui, render, reactive, req

import plaque_stats as ps          # the shared engine (same code as the CLI)

HERE = os.path.dirname(os.path.abspath(__file__))


def _example_wide_path():
    """Locate example_data_wide.csv, regenerating it if necessary.

    Search order (robust across source / editable / wheel / frozen installs):
      1. next to this module (source & editable installs),
      2. a dir advertised by the launcher via PLAQUE_STATS_EXAMPLE_DIR,
      3. the install prefix's share/plaque_stats (data-files from the wheel),
      4. as a last resort, generate it fresh with ps.make_example() into a
         temp dir and read from there.
    """
    candidates = [HERE]
    env_dir = os.environ.get("PLAQUE_STATS_EXAMPLE_DIR")
    if env_dir:
        candidates.append(env_dir)
    candidates.append(os.path.join(sys.prefix, "share", "plaque_stats"))
    if getattr(sys, "_MEIPASS", None):
        candidates.append(sys._MEIPASS)
    for d in candidates:
        p = os.path.join(d, "example_data_wide.csv")
        if os.path.exists(p):
            return p
    # Fallback: generate on the fly into a stable temp dir.
    tmp = os.path.join(tempfile.gettempdir(), "plaque_stats_example")
    os.makedirs(tmp, exist_ok=True)
    p = os.path.join(tmp, "example_data_wide.csv")
    if not os.path.exists(p):
        ps.make_example(tmp)
    return p


FORMAT_HELP = """
<h4>Input data format (one row per plaque)</h4>
<p><b>WIDE</b> (matches the app export — add <code>group</code> + <code>replicate</code>):</p>
<pre>group,replicate,diameter_mm,area_mm2,turbidity
T4,plate1,2.34,4.30,0.12
T7,plate1,1.80,2.54,0.62</pre>
<p><b>LONG</b> (one file, many metrics):</p>
<pre>group,replicate,metric,value
T4,plate1,diameter_mm,2.34</pre>
<ul><li><b>group</b> (required): the sample/condition/phage compared.</li>
<li><b>replicate</b> (recommended): the plate / experimental unit — makes stats per-plate.</li>
<li><b>value</b> / numeric columns: the measurement(s).</li></ul>
<p>This app calls the same <code>plaque_stats.py</code> engine as the command-line tool and the
R-Shiny app, so the violin figure and every statistic are identical.</p>
"""

app_ui = ui.page_sidebar(
    ui.sidebar(
        ui.input_file("file", "Data file (CSV / TSV / XLSX)",
                      accept=[".csv", ".tsv", ".txt", ".xlsx", ".xls"]),
        ui.input_action_button("load_example", "Load example data", class_="btn-sm"),
        ui.hr(),
        ui.output_ui("col_pickers"),
        ui.hr(),
        ui.input_select("unit", "Statistical unit",
                        {"auto": "auto (plate if replicates)", "replicate": "per plate",
                         "plaque": "per plaque"}),
        ui.input_select("parametric", "Test type",
                        {"auto": "auto", "parametric": "parametric", "nonparametric": "non-parametric"}),
        ui.input_select("center", "Centre marker", {"mean": "mean", "median": "median"}),
        ui.input_select("error", "Error bar",
                        {"auto": "auto", "sd": "SD", "sem": "SEM", "ci95": "95% CI",
                         "iqr": "IQR", "none": "none"}),
        ui.input_select("violin_fill", "Violin fill",
                        {"auto": "auto (grey when plates)", "neutral": "neutral grey",
                         "group": "coloured by sample"}),
        ui.input_select("palette_name", "Colour theme",
                        {"": "(custom below)", "okabe": "Okabe-Ito", "set2": "Set2",
                         "tab10": "Tab10", "warm": "Warm", "cool": "Cool", "grays": "Grays"}),
        ui.input_text("palette_custom", "Custom palette (comma hex)", ""),
        ui.input_checkbox("show_points", "Show plaque points", True),
        ui.input_checkbox("show_n", "Show n on top", True),
        ui.input_checkbox("frame", "Box the plot (frame)", False),
        ui.input_checkbox("show_sig", "Significance brackets", True),
        ui.input_checkbox("log_y", "Log y-axis", False),
        ui.input_text("title", "Title", ""),
        ui.input_text("ylabel", "Y-axis label", ""),
        ui.input_text("order", "Group order (comma-sep)", ""),
        ui.input_slider("width", "Width (in)", 4, 16, 9, step=0.5),
        ui.input_slider("height", "Height (in)", 3, 12, 5.4, step=0.2),
        width=330,
    ),
    ui.navset_tab(
        ui.nav_panel("Plot",
                     ui.output_plot("violin", height="560px"),
                     ui.div(ui.download_button("dl_png", "PNG"),
                            ui.download_button("dl_svg", "SVG (editable)"),
                            ui.download_button("dl_pdf", "PDF (editable)"))),
        ui.nav_panel("Statistics",
                     ui.h5("Omnibus test"), ui.output_text_verbatim("omni"),
                     ui.h5("Pairwise (Sample A vs B — mean of all plates)"),
                     ui.output_data_frame("pairwise"),
                     ui.h5("Paste-ready sentence"), ui.output_text_verbatim("sentence")),
        ui.nav_panel("Summaries",
                     ui.h5("Per group"), ui.output_data_frame("summary_group"),
                     ui.download_button("dl_sumg", "Download group summary CSV"),
                     ui.h5("Per plate (replicate means)"), ui.output_data_frame("summary_rep")),
        ui.nav_panel("Data format", ui.HTML(FORMAT_HELP)),
    ),
    title="Plaque Stats & Violins  ·  Python / Shiny",
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
        except Exception as e:                                  # noqa: BLE001
            ui.notification_show(f"Could not read file: {e}", type="error")

    @reactive.effect
    @reactive.event(input.load_example)
    def _load_example():
        try:
            raw.set(pd.read_csv(_example_wide_path()))
        except Exception as e:                                  # noqa: BLE001
            ui.notification_show(f"Could not load example data: {e}", type="warning")

    @render.ui
    def col_pickers():
        df = raw.get()
        if df is None:
            return ui.p("Upload a file or click “Load example data”.")
        cols = [str(c) for c in df.columns]
        numeric = [c for c in cols if pd.api.types.is_numeric_dtype(df[c])]
        is_long = "value" in cols

        def pick(cands, pool):
            hit = [c for c in cands if c in pool]
            return hit[0] if hit else (pool[0] if pool else None)

        items = [ui.input_select("group", "Group column", {c: c for c in cols},
                                 selected=pick(["group", "sample", "Sample", "phage"], cols))]
        items.append(ui.input_select("replicate", "Replicate (plate) column",
                                     {"(none)": "(none)", **{c: c for c in cols}},
                                     selected=pick(["replicate", "Replicate", "plate"], cols) or "(none)"))
        if is_long:
            mets = [str(m) for m in df["metric"].dropna().unique()]
            items.append(ui.input_select("metric", "Metric to plot", {m: m for m in mets},
                                         selected=mets[0] if mets else None))
        else:
            items.append(ui.input_select("value", "Value column", {c: c for c in numeric},
                                         selected=pick(["diameter_mm", "DIAMETER_MM", "value"], numeric)))
        return ui.TagList(*items)

    @reactive.calc
    def analysis():
        df = raw.get(); req(df is not None)
        req(input.group())
        is_long = "value" in [str(c) for c in df.columns]
        value = input.metric() if is_long else input.value()
        rep_in = input.replicate()
        rep = rep_in if (rep_in and rep_in != "(none)") else "replicate"
        d, metric = ps.normalize(df, input.group(), value, rep, "metric")
        order_in = [x.strip() for x in (input.order() or "").split(",") if x.strip()]
        order = order_in or list(dict.fromkeys(d["group"]))
        order = [g for g in order if g in set(d["group"])]
        d = d[d["group"].isin(order)].reset_index(drop=True)

        opts = dict(ps.DEFAULTS)
        opts.update(unit=input.unit(), parametric=input.parametric(), center=input.center(),
                    error=input.error(), violin_fill=input.violin_fill(), frame=bool(input.frame()),
                    show_n=bool(input.show_n()), show_points=bool(input.show_points()),
                    annotate=("auto" if input.show_sig() else "none"),
                    log_y=bool(input.log_y()), width=float(input.width()), height=float(input.height()),
                    title=input.title() or None, ylabel=input.ylabel() or None, order=order)
        pname = input.palette_name()
        if pname and pname in ps.PALETTES:
            opts["palette"] = list(ps.PALETTES[pname])
        elif input.palette_custom().strip():
            opts["palette"] = [x.strip() for x in input.palette_custom().split(",") if x.strip()]

        omni, posthoc, unit, have_rep = ps.run_stats(d, order, opts["unit"], opts["parametric"])
        rep_means = ps.replicate_means(d)
        src = rep_means if (unit == "replicate" and rep_means is not None) else d
        unit_means = src.groupby("group")["value"].mean().to_dict()
        return dict(d=d, order=order, opts=opts, metric=metric, omni=omni,
                    posthoc=posthoc, unit=unit, have_rep=have_rep, unit_means=unit_means)

    @render.plot
    def violin():
        a = analysis()
        return ps.plot_violin(a["d"], a["order"], a["opts"], a["metric"], a["posthoc"])

    @render.data_frame
    def summary_group():
        a = analysis()
        return ps.group_summary(a["d"], a["order"]).round(4)

    @render.data_frame
    def summary_rep():
        a = analysis()
        rm = ps.replicate_means(a["d"])
        return (rm.round(4) if rm is not None else pd.DataFrame({"note": ["no replicate column"]}))

    @render.data_frame
    def pairwise():
        a = analysis()
        if not a["posthoc"]:
            return pd.DataFrame({"note": ["need ≥2 groups"]})
        um = a["unit_means"]
        rows = [{"Sample A": x, "Sample B": y,
                 "mean A": round(um.get(x, float("nan")), 4), "mean B": round(um.get(y, float("nan")), 4),
                 "Δ (A−B)": round(um.get(x, float("nan")) - um.get(y, float("nan")), 4),
                 "p_adj": ps._fmt_p(p), "signif": ps.stars(p)}
                for (x, y), p in a["posthoc"].items()]
        return pd.DataFrame(rows)

    @render.text
    def omni():
        a = analysis(); o = a["omni"]
        msg = "%s: p = %s  (unit: %s, parametric = %s, min n = %d/group)" % (
            o["test"], ps._fmt_p(o["p"]), a["unit"], o["parametric_used"], o.get("min_n", 0))
        for w in o.get("warnings", []):
            msg += "\n\n⚠ " + w
        return msg

    @render.text
    def sentence():
        a = analysis()
        summ = ps.group_summary(a["d"], a["order"])
        import tempfile
        p = os.path.join(tempfile.gettempdir(), "_plaque_report.md")
        ps.write_report(p, a["metric"], summ, ps.replicate_means(a["d"]), a["omni"],
                        a["posthoc"], a["unit"], a["have_rep"],
                        {**a["opts"], "_stamp": ""})
        txt = open(p, encoding="utf-8").read()
        return txt.split("## Paste-ready sentence")[-1].strip().lstrip(">").strip()

    def _fig_bytes(fmt):
        a = analysis()
        fig = ps.plot_violin(a["d"], a["order"], a["opts"], a["metric"], a["posthoc"])
        buf = io.BytesIO()
        fig.savefig(buf, format=fmt, dpi=300, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        return buf.getvalue()

    @render.download(filename=lambda: "violin.png")
    def dl_png():
        yield _fig_bytes("png")

    @render.download(filename=lambda: "violin.svg")
    def dl_svg():
        yield _fig_bytes("svg")

    @render.download(filename=lambda: "violin.pdf")
    def dl_pdf():
        yield _fig_bytes("pdf")

    @render.download(filename=lambda: "summary_by_group.csv")
    def dl_sumg():
        a = analysis()
        yield ps.group_summary(a["d"], a["order"]).to_csv(index=False)


app = App(app_ui, server)
