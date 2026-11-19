"""Legend key: every figure that colours samples / plates / phages ships a key built from the
same mapping it was drawn with (the owner's standing rule; see README "Legend key").

The five required checks run on the shared statistics engine (the violin SuperPlot behind the
desktop Analyze tab, the Plaque Stats CLI and its web app); further tests cover the grouped
plot, make_figure.py, the turbidity histograms and the Analyze tab itself (headless Qt).
"""
import importlib.util
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("scipy")

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import colors as mcolors  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
lk = ps = None


@pytest.fixture(autouse=True)
def _engine_as_package():
    """Use the engine the way the desktop app does (``from plaque_stats import plaque_stats``).
    Other test modules put plaque_stats/ itself on sys.path and import the flat module under the
    same name, so swap that out for these tests and put everything back afterwards."""
    global lk, ps
    saved_path = list(sys.path)
    saved_mods = {k: v for k, v in sys.modules.items()
                  if k == "plaque_stats" or k.startswith("plaque_stats.") or k == "legend_key"}
    for k in saved_mods:
        del sys.modules[k]
    sys.path[:] = [p for p in sys.path if os.path.abspath(p) not in (
        os.path.join(ROOT, "plaque_stats"), os.path.join(ROOT, "plaque_stats", "agreement"))]
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    import importlib
    ps = importlib.import_module("plaque_stats.plaque_stats")
    lk = importlib.import_module("plaque_stats.legend_key")
    try:
        yield
    finally:
        for k in [k for k in sys.modules if k == "plaque_stats" or k.startswith("plaque_stats.")
                  or k == "legend_key"]:
            del sys.modules[k]
        sys.modules.update(saved_mods)
        sys.path[:] = saved_path


def _hex(c):
    return mcolors.to_hex(c, keep_alpha=False).upper()


def _frame(groups=("WT", "T7", "lambda"), plates=("plate1", "plate2")):
    rng = np.random.default_rng(3)
    rows = []
    for gi, g in enumerate(groups):
        for p in plates:
            for v in rng.normal(1.0 + 0.3 * gi, 0.08, 25):
                rows.append({"group": g, "replicate": p, "value": float(v)})
    return pd.DataFrame(rows)


def _opts(**kw):
    o = dict(ps.DEFAULTS)
    o.update({"palette": list(ps.OKABE_ITO), "violin_fill": "group"})   # sample colour + plate colour
    o.update(kw)
    return o


def _violin(df, order, opts):
    fig = ps.plot_violin(df, order, opts, "diameter_mm", {})
    return fig, lk.from_figure(fig)


def _texts(svg_path):
    ns = "{http://www.w3.org/2000/svg}"
    root = ET.parse(svg_path).getroot()
    return ["".join(t.itertext()).strip() for t in root.iter(ns + "text")]


# --------------------------------------------------------------------------- the five checks
def test_1_every_sample_and_plate_in_the_mapping_is_in_the_key_with_its_drawn_style():
    df, order, opts = _frame(), ["WT", "T7", "lambda"], _opts()
    gcol, rcol, neutral, reps = ps.violin_colours(df, order, opts)
    fig, key = _violin(df, order, opts)
    by = {e["label"]: e for e in key["entries"]}
    assert not neutral and sorted(by) == sorted(order + reps)
    # samples: violin patches in the mapping's literal colour, outlined in its darkened shade
    bodies = [c for c in fig.axes[0].collections if c.__class__.__name__ in ("PolyCollection", "FillBetweenPolyCollection")]
    for i, g in enumerate(order):
        e = by[g]
        assert e["kind"] == "patch" and e["section"] == "sample"
        assert e["colour"] == _hex(gcol[g]) and e["edge"] == _hex(ps._darken(gcol[g]))
        assert _hex(bodies[i].get_facecolor()[0]) == e["colour"]          # as drawn
        assert _hex(bodies[i].get_edgecolor()[0]) == e["edge"]
    # plates: filled circles in the plate colour with the dark outline the plate means carry
    for r in reps:
        e = by[r]
        assert (e["kind"], e["marker"], e["filled"], e["section"]) == ("marker", "o", True, "plate")
        assert e["colour"] == _hex(rcol[r]) and e["edge"] == "#12211D"
    drawn_means = [c for c in fig.axes[0].collections if c.get_sizes().size and
                   c.get_sizes()[0] == pytest.approx(opts["point_size"] * 5.5)]
    drawn = {_hex(fc) for c in drawn_means for fc in c.get_facecolors()}
    assert drawn == {by[r]["colour"] for r in reps}
    plt.close(fig)


def test_2_rename_and_recolour_show_up_on_the_next_key():
    df, order = _frame(), ["WT", "T7", "lambda"]
    fig, key = _violin(df, order, _opts())
    before = {e["label"]: e["colour"] for e in key["entries"]}
    plt.close(fig)
    df2 = df.copy()
    df2.loc[df2["group"] == "T7", "group"] = "T7 ΔgeneX"                 # rename one sample
    pal = list(ps.OKABE_ITO); pal[2] = "#D62728"                          # recolour another (lambda)
    order2 = ["WT", "T7 ΔgeneX", "lambda"]
    fig2, key2 = _violin(df2, order2, _opts(palette=pal))
    after = {e["label"]: e["colour"] for e in key2["entries"]}
    assert "T7" not in after and "T7 ΔgeneX" in after
    assert after["lambda"] == "#D62728" != before["lambda"]
    assert after["WT"] == before["WT"]
    assert "T7 ΔgeneX" in lk.text_starter(key2) and "T7 (" not in lk.text_starter(key2)
    plt.close(fig2)


def test_3_text_starter_names_every_entry_once_with_a_colour_word():
    df, order = _frame(), ["WT", "T7", "lambda"]
    fig, key = _violin(df, order, _opts())
    text = lk.text_starter(key)
    clauses = text.rstrip(".").split("; ")
    names = [c.split(" (", 1)[0] for c in clauses]
    assert names == [e["label"] for e in key["entries"]]
    assert len(set(names)) == len(names)
    colour_words = {n for n, _ in lk.COLOUR_NAMES}
    for c in clauses:
        inside = c.split(" (", 1)[1].rstrip(")")
        word = inside.split(",")[0].strip()
        assert word in colour_words or word.split(" ", 1)[-1] in colour_words, c
    assert lk.colour_name("#000000") == "black" and lk.colour_name("#FF7F00") == "orange"
    plt.close(fig)


def test_4_embedded_and_standalone_keys_list_the_same_entries():
    df, order = _frame(), ["WT", "T7", "lambda"]
    fig, key = _violin(df, order, _opts(legend=True))
    emb = fig.axes[0].get_legend()
    assert emb is not None
    alone = lk.key_figure(key).legends[0]
    lab = lambda leg: [t.get_text() for t in leg.get_texts()]  # noqa: E731
    assert lab(emb) == lab(alone)
    assert [h for h in lab(emb) if h not in ("sample", "plate")] == [e["label"] for e in key["entries"]]
    # same font, same handle colours
    assert {t.get_fontfamily()[0] for t in emb.get_texts()} == {key["font_family"]}
    def colours(leg):
        out = []
        for h in leg.legend_handles if hasattr(leg, "legend_handles") else leg.legendHandles:
            if hasattr(h, "get_markerfacecolor") and h.get_marker() not in (None, "None", ""):
                out.append(_hex(h.get_markerfacecolor()))
            elif hasattr(h, "get_facecolor"):
                out.append(_hex(h.get_facecolor()))
        return out
    assert colours(emb) == colours(alone)
    # switching the key off the figure removes it (the stand-alone key is still there)
    fig2, key2 = _violin(df, order, _opts(legend=False))
    assert fig2.axes[0].get_legend() is None and lk.entries_signature(key2) == lk.entries_signature(key)
    plt.close(fig); plt.close(fig2)


def test_5_vector_keys_keep_names_as_text(tmp_path):
    df, order = _frame(), ["WT", "T7", "lambda"]
    fig, key = _violin(df, order, _opts())
    paths = lk.write_key_files(key, str(tmp_path / "violin"), ["png", "svg", "pdf"])
    assert [os.path.basename(p) for p in paths] == [
        "violin_legend_key.png", "violin_legend_key.svg", "violin_legend_key.pdf",
        "violin_legend_text.txt"]
    texts = _texts(str(tmp_path / "violin_legend_key.svg"))
    for e in key["entries"]:
        assert e["label"] in texts
    pdf = (tmp_path / "violin_legend_key.pdf").read_bytes()
    assert b"/Type3" not in pdf and (b"/TrueType" in pdf or b"/CIDFontType2" in pdf)
    assert open(paths[-1], encoding="utf-8").read().strip() == lk.text_starter(key)
    plt.close(fig)


# --------------------------------------------------------------------------- other figures
def test_default_superplot_key_is_the_plate_legend_it_always_had():
    """Neutral violins (the default with plates): the key lists the plates only, titled
    'plate' -- the in-plot legend the figure already drew, now built from the key."""
    df, order = _frame(), ["WT", "T7", "lambda"]
    fig, key = _violin(df, order, _opts(violin_fill="auto"))
    assert [e["label"] for e in key["entries"]] == ["plate1", "plate2"]
    leg = fig.axes[0].get_legend()
    assert leg.get_title().get_text() == "plate"
    assert [t.get_text() for t in leg.get_texts()] == ["plate1", "plate2"]
    plt.close(fig)


def test_no_replicates_key_lists_samples_by_point_colour():
    df = _frame().drop(columns="replicate")
    df["replicate"] = np.nan
    order = ["WT", "T7", "lambda"]
    fig, key = _violin(df, order, _opts(violin_fill="neutral"))
    gcol = ps.violin_colours(df, order, _opts(violin_fill="neutral"))[0]
    assert [(e["label"], e["kind"], e["colour"]) for e in key["entries"]] == [
        (g, "marker", _hex(gcol[g])) for g in order]
    plt.close(fig)


def test_grouped_plot_key_follows_the_subgroup_colours_and_control():
    df = _frame().rename(columns={})
    df["subgroup"] = np.where(df.index % 2 == 0, "LE392", "MG1655")
    pal = list(ps.OKABE_ITO)
    opts = _opts(palette=pal); opts["_sublabel"] = "host"
    comp = pd.DataFrame(columns=["group", "subgroup", "p"])
    fig = ps.plot_grouped(df, ["WT", "T7", "lambda"], ["LE392", "MG1655"], "LE392", opts,
                          "diameter_mm", comp)
    key = lk.from_figure(fig)
    assert [(e["label"], e["colour"]) for e in key["entries"]] == [
        ("LE392 (control)", _hex(pal[0])), ("MG1655", _hex(pal[1]))]
    leg = fig.axes[0].get_legend()
    assert leg.get_title().get_text() == "host"
    assert [t.get_text() for t in leg.get_texts()] == ["LE392 (control)", "MG1655"]
    plt.close(fig)


def test_cli_bundle_writes_key_beside_each_figure(tmp_path):
    data = tmp_path / "d.csv"
    _frame().rename(columns={"value": "diameter_mm"}).to_csv(data, index=False)
    args = dict(ps.DEFAULTS)
    args.update({"data": str(data), "value": "diameter_mm", "out": str(tmp_path / "out"),
                 "formats": ["png", "svg"], "order": None, "_stamp": ""})
    ps.run(args)
    out = tmp_path / "out"
    assert (out / "violin_diameter_mm_legend_key.png").exists()
    assert (out / "violin_diameter_mm_legend_key.svg").exists()
    assert "plate1" in (out / "violin_diameter_mm_legend_text.txt").read_text(encoding="utf-8")


def test_make_figure_cli_writes_key_and_text(tmp_path):
    rows = []
    rng = np.random.default_rng(1)
    for s, mu in (("WT", 1.0), ("2-4", 1.3), ("NEW", 0.8)):
        for p in range(2):
            for v in rng.normal(mu, 0.1, 20):
                rows.append({"SAMPLE": s, "PLATE": "p%d" % p, "MODE": "normal", "DIAMETER_MM": v})
    csv = tmp_path / "tidy.csv"
    pd.DataFrame(rows).to_csv(csv, index=False)
    out = tmp_path / "fig"
    r = subprocess.run([sys.executable, os.path.join(ROOT, "make_figure.py"), "--csv", str(csv),
                        "--legend-key", "--key-on-figure", "--out", str(out)],
                       capture_output=True, text=True, cwd=str(tmp_path))
    assert r.returncode == 0, r.stderr
    for ext in ("png", "pdf", "svg"):
        assert (tmp_path / ("fig_legend_key.%s" % ext)).exists()
    text = (tmp_path / "fig_legend_text.txt").read_text(encoding="utf-8")
    assert text.startswith("WT (") and "2-4 (" in text and "NEW (" in text
    # the embedded key on the figure SVG names the same samples, as text
    assert {"WT", "2-4", "NEW"} <= set(_texts(str(tmp_path / "fig_legend_key.svg")))


def test_turbidity_histograms_write_their_key(tmp_path):
    import plaque_turbidity as pt
    rng = np.random.default_rng(0)
    df = pd.DataFrame({"PHAGE": np.repeat(["T4", "T7", "lambda"], 30),
                       "DIAMETER_MM": rng.normal(1.0, 0.2, 90)})
    pt.write_plots(df, str(tmp_path))
    assert (tmp_path / "hist_DIAMETER_MM.png").exists()
    assert (tmp_path / "hist_DIAMETER_MM_legend_key.png").exists()
    # CT-R1 F13: the box plots now draw each phage in its histogram colour and explain their
    # marks (mean / median), so they carry a key too (was: "box plot: no colours", no key).
    assert (tmp_path / "compare_DIAMETER_MM_legend_key.png").exists()
    text = (tmp_path / "hist_DIAMETER_MM_legend_text.txt").read_text(encoding="utf-8")
    cols = pt.phage_colours(["T4", "T7", "lambda"])
    assert text.startswith("T4 (%s, filled bars)" % lk.colour_name(cols["T4"]))
    assert "T7 (" in text and "lambda (" in text


# --------------------------------------------------------------------------- desktop Analyze tab
@pytest.mark.skipif(importlib.util.find_spec("PySide6") is None
                    or importlib.util.find_spec("pytestqt") is None,
                    reason="needs PySide6 + pytest-qt")
def test_analyze_tab_key_follows_renames(qtbot, tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from app import ui as appui
    win = appui.MainWindow(); qtbot.addWidget(win)
    st = win.study_tab
    rng = np.random.default_rng(0)

    def add(group, mus):
        st._samples.append({"group": group, "subgroup": ""})
        si = len(st._samples) - 1
        for mu in mus:
            d = (mu + rng.normal(0, 0.05, 30)).round(3).tolist()
            st._add_plate(si, d, [x * x for x in d])

    add("WT", [0.9, 0.92]); add("mut", [1.2, 1.22]); add("T7", [1.5, 1.52])
    st._refresh_tree(); st.fill_sel.setCurrentIndex(2)        # coloured violins
    st._analyse()
    assert st.key_btn.isEnabled() and st.legend_cb.text() == "Place key on figure"
    text = st.key_text.text()
    assert all(n in text for n in ("WT (", "mut (", "T7 ("))
    assert st._last_fig.axes[0].get_legend() is not None
    st.legend_cb.setChecked(False)                             # key off the figure, text stays
    assert st._last_fig.axes[0].get_legend() is None and st.key_text.text() == text
    path = st._save_key(str(tmp_path / "k.svg"))
    assert path and "mut" in _texts(path)

    st._samples[1]["group"] = "mut ΔX"                           # rename -> stale analysis cleared
    for p in st._plates:
        if p["group"] == "mut":
            p["group"] = "mut ΔX"
    st._refresh_tree()
    assert st.key_text.text() == "" and not st.key_btn.isEnabled()
    st._analyse()
    assert "mut ΔX (" in st.key_text.text() and "mut (" not in st.key_text.text()
    path = st._save_key(str(tmp_path / "k2.svg"))
    assert "mut ΔX" in _texts(path)


# --------------------------------------------------------------------------- R Shiny app
def test_r_shiny_app_key(tmp_path):
    """plaque_stats/app.R: the key comes from the same style map the violins and plate means are
    drawn from, follows a rename + recolour, and the vector key keeps the names as text."""
    import shutil
    rscript = shutil.which("Rscript")
    if not rscript:
        pytest.skip("R not installed")
    pkgs = 'c("shiny","ggplot2","dplyr","tidyr","readr","DT","rstatix","ggpubr","svglite")'
    ok = subprocess.run([rscript, "-e", "q(status = !all(sapply(%s, requireNamespace, "
                         "quietly = TRUE)))" % pkgs], capture_output=True)
    if ok.returncode != 0:
        pytest.skip("the R app's packages are not installed")
    r = subprocess.run([rscript, os.path.join(ROOT, "tests", "r_legend_key_check.R")],
                       cwd=os.path.join(ROOT, "plaque_stats"), capture_output=True, text=True,
                       env=dict(os.environ, OUT_DIR=str(tmp_path)), timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]
    got = dict(line.split("=", 1) for line in r.stdout.splitlines() if "=" in line)
    key1 = dict(x.split(":") for x in got["KEY1"].split("|"))
    key2 = dict(x.split(":") for x in got["KEY2"].split("|"))
    assert list(key1) == ["WT", "T7", "lambda", "plate1", "plate2"]
    # 1. every keyed colour is a colour the figure actually draws, and vice versa
    assert set(key1.values()) == set(got["DRAWN1"].split("|"))
    # 2. rename + recolour reach the key (and the drawing)
    assert "T7" not in key2 and "T7 mut" in key2 and key2["T7 mut"] == key1["T7"]
    assert key2["lambda"] == "#D62728" != key1["lambda"]
    assert set(key2.values()) == set(got["DRAWN2"].split("|"))
    # 3. text starter: every name once, each with a colour word
    for name in ("T7 mut (", "WT (", "lambda (", "plate1 (", "plate2 ("):
        assert got["TEXT2"].count(name) == 1
    assert "T7 (" not in got["TEXT2"]
    # 4. "Place key on figure" composes the same key_plot beside the figure; off removes it
    assert got["PLACED1"] == "TRUE" and got["PLACED2"] == "FALSE"
    # 5. SVG key keeps the names as text; the text file is the starter
    svg = "\n".join(_texts(str(tmp_path / "violin_legend_key.svg")))
    for name in ("WT", "T7", "lambda", "plate1", "plate2"):
        assert name in svg
    assert (tmp_path / "violin_legend_text.txt").read_text().strip() == got["TEXT1"].strip()
