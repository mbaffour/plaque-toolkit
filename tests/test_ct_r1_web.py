"""CT-R1 web apps (Shiny for Python): plaque_stats/app_py.py ("A", statistics) and
plaque_stats/agreement/app_py.py ("B", agreement).

Each test pins one finding of the round-1 click-through of the web apps (F1..F25). The server
logic lives in small module-level helpers so most of it is tested without a browser; the few
browser tests start the real app on a free port, drive it with Playwright + the installed Chrome,
and skip cleanly when either is missing.
"""
import importlib.util
import io
import os
import socket
import subprocess
import sys
import time
import urllib.request
import zipfile

import numpy as np
import pandas as pd
import pytest

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PS_DIR = os.path.join(ROOT, "plaque_stats")
AG_DIR = os.path.join(PS_DIR, "agreement")
for _d in (PS_DIR, AG_DIR):
    if _d not in sys.path:
        sys.path.insert(0, _d)

pytest.importorskip("shiny")


def _load(name, path):
    """Both apps are files called app_py.py: load each under its own module name."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


A = _load("ct_web_stats_app", os.path.join(PS_DIR, "app_py.py"))
B = _load("ct_web_agree_app", os.path.join(AG_DIR, "app_py.py"))
import agreement as ag  # noqa: E402
import legend_key as lk  # noqa: E402
import plaque_stats as ps  # noqa: E402


def _pairs(n=40, seed=3):
    rng = np.random.default_rng(seed)
    m = rng.uniform(0.5, 3.0, n)
    t = m * 0.98 + rng.normal(0, 0.05, n)
    return list(np.round(t, 3)), list(np.round(m, 3))


def _agree_stats(n=40):
    t, m = _pairs(n)
    return ag.full_stats(t, m)


def _html(app_module):
    from htmltools import TagList
    return str(TagList(app_module.app_ui))


# =========================================================================== B: F9 legend key
@pytest.mark.parametrize("k", ["both", "a", "b"])
def test_b_f9_every_figure_has_key_download_text_and_switch(k):
    """F9: each of the three agreement figures offers a legend key download and a text starter."""
    html = _html(B)
    assert 'id="dl_key_%s"' % k in html
    assert 'id="key_text_%s"' % k in html
    assert html.count('id="show_key"') == 1 and "Place key on figure" in html


@pytest.mark.parametrize("k,expect,absent", [
    ("both", ["line of identity", "mean bias", "95% limits of agreement"], []),
    ("a", ["line of identity", "least-squares fit"], ["mean bias"]),
    ("b", ["mean bias", "95% limits of agreement", "zero difference"], ["line of identity"]),
])
def test_b_f9_key_text_lists_what_the_figure_draws(k, expect, absent):
    s = _agree_stats()
    fig = B.make_fig(s, B.FIGURES[k][1], show_key=False)
    txt = B.key_text(fig)
    for e in expect:
        assert e in txt
    for a_ in absent:
        assert a_ not in txt
    assert "within the limits of agreement (bluish green, filled circles" in txt


@pytest.mark.parametrize("k", ["both", "a", "b"])
def test_b_f9_key_zip_has_figure_formats_and_text(k):
    s = _agree_stats()
    base = B.FIGURES[k][2]
    fig = B.make_fig(s, B.FIGURES[k][1])
    names = zipfile.ZipFile(io.BytesIO(B.key_zip_bytes(fig, base))).namelist()
    assert sorted(names) == sorted(["%s_legend_key.%s" % (base, f) for f in ("png", "svg", "pdf")]
                                   + ["%s_legend_text.txt" % base])


@pytest.mark.parametrize("k", ["both", "a", "b"])
def test_b_f9_embedded_key_equals_standalone(k):
    s = _agree_stats()
    fig = B.make_fig(s, B.FIGURES[k][1], show_key=True)
    key = lk.from_figure(fig)
    legs = list(fig.legends) + [ax.get_legend() for ax in fig.axes if ax.get_legend()]
    assert len(legs) == 1
    shown = [t.get_text() for t in legs[0].get_texts()]
    assert shown == lk.legend_handles(key)[1]
    # switch off: no key drawn, but the stand-alone key is unchanged
    fig2 = B.make_fig(s, B.FIGURES[k][1], show_key=False)
    assert not fig2.legends and lk.entries_signature(lk.from_figure(fig2)) == lk.entries_signature(key)


# =========================================================================== browser helpers
def _free_port():
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        return so.getsockname()[1]


def _have_chrome():
    try:
        from playwright.sync_api import sync_playwright
    except Exception:                                       # noqa: BLE001
        return False
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(channel="chrome", headless=True)
            b.close()
        return True
    except Exception:                                       # noqa: BLE001
        return False


_CHROME = None


def _need_browser():
    global _CHROME
    if _CHROME is None:
        _CHROME = _have_chrome()
    if not _CHROME:
        pytest.skip("playwright or Chrome not available")


class _Server:
    def __init__(self, app_path, tmp_path):
        self.port = _free_port()
        env = dict(os.environ, MPLBACKEND="Agg", TMPDIR=str(tmp_path))
        self.log = open(str(tmp_path / "server.log"), "w")
        self.proc = subprocess.Popen([sys.executable, "-m", "shiny", "run", "--port", str(self.port),
                                      app_path], stdout=self.log, stderr=subprocess.STDOUT, env=env,
                                     cwd=str(tmp_path))
        for _ in range(120):
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/" % self.port, timeout=2).read(10)
                return
            except Exception:                               # noqa: BLE001
                time.sleep(0.25)
        self.stop()
        pytest.skip("the Shiny app did not start")

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(10)
        except Exception:                                   # noqa: BLE001
            self.proc.kill()
        self.log.close()


def _idle(page, t=0.6):
    time.sleep(t)
    page.wait_for_function(
        "() => !document.documentElement.classList.contains('shiny-busy') && "
        "![...document.querySelectorAll('.recalculating')].some(e => e.offsetParent !== null)",
        timeout=60000)
    time.sleep(0.3)


def _tab(page, text):
    page.locator("a.nav-link", has_text=text).first.click(timeout=10000)
    _idle(page)


def _download(page, port, id_):
    """GET a download link's URL with the page's session (the link must be visible: Shiny only
    binds outputs that are shown)."""
    page.wait_for_function("(i) => (document.getElementById(i).getAttribute('href') || '').length > 1",
                           arg=id_, timeout=30000)
    href = page.get_attribute("#" + id_, "href")
    r = page.request.get("http://127.0.0.1:%d/%s" % (port, href.lstrip("/")), timeout=120000)
    return r.body()


@pytest.fixture
def browser_page():
    """yield a function (app_path, tmp_path, width) -> (page, server); everything is closed after."""
    _need_browser()
    from playwright.sync_api import sync_playwright
    opened = []
    pw = sync_playwright().start()

    def _open(app_path, tmp_path, width=1280):
        srv = _Server(app_path, tmp_path)
        b = pw.chromium.launch(channel="chrome", headless=True)
        page = b.new_page(viewport={"width": width, "height": 900})
        opened.append((srv, b))
        page.goto("http://127.0.0.1:%d/" % srv.port)
        page.wait_for_function("() => window.Shiny && Shiny.shinyapp && Shiny.shinyapp.isConnected()",
                               timeout=30000)
        _idle(page)
        return page, srv
    yield _open
    for srv, b in opened:
        b.close()
        srv.stop()
    pw.stop()


def test_b_f9_browser_key_downloads_and_zip(browser_page, tmp_path):
    page, srv = browser_page(os.path.join(AG_DIR, "app_py.py"), tmp_path)
    page.click("#load_example"); _idle(page, 2)
    _tab(page, "B · Bland")
    z = zipfile.ZipFile(io.BytesIO(_download(page, srv.port, "dl_key_b")))
    assert "agreement_B_bland_altman_legend_key.svg" in z.namelist()
    _tab(page, "Both (A + B)")
    assert "mean bias" in page.inner_text("#key_text_both")
    _tab(page, "Statistics")
    allz = zipfile.ZipFile(io.BytesIO(_download(page, srv.port, "dl_all"))).namelist()
    for suffix in ("_legend_key.png", "_legend_key.svg", "_legend_key.pdf", "_legend_text.txt"):
        assert sum(n.endswith(suffix) for n in allz) == 3, (suffix, allz)


# =========================================================================== A: statistics app
def _wide(groups=("T4", "T7", "lambda"), mus=(2.6, 1.8, 3.1), plates=3, n=12, seed=2):
    rng = np.random.default_rng(seed)
    rows = []
    for g, mu in zip(groups, mus):
        for p_ in range(plates):
            for v in rng.normal(mu + rng.normal(0, 0.1), 0.25, n):
                rows.append({"group": g, "replicate": "plate%d" % (p_ + 1),
                             "diameter_mm": round(float(v), 3), "area_mm2": round(float(v * v * 0.785), 3)})
    return pd.DataFrame(rows)


def _write(tmp_path, name, df=None, text=None, sep=",", decimal="."):
    p = tmp_path / name
    if text is not None:
        p.write_text(text, encoding="utf-8")
    else:
        df.to_csv(p, index=False, sep=sep, decimal=decimal)
    return str(p)


def _sel(df, **kw):
    d = A.picker_defaults(df)
    s = dict(group=d["group"], value=d["value"], replicate=d["replicate"], subgroup=A.NONE,
             control=None, order=A.group_levels(df, d["group"]), compare="all", unit="auto",
             parametric="auto", equal_var="auto", center="mean", error="auto", violin_fill="auto",
             brackets="auto", palette_name="", palette_custom="", show_points=True, show_n=True,
             show_value=True, frame=False, log_y=False, log_drop=False, title="", ylabel="",
             width=9, height=5.4, place_key=True)
    s.update(kw)
    return s


def _read(tmp_path, name, df=None, **kw):
    return A.read_upload(_write(tmp_path, name, df, **kw), name)


def test_a_f1_second_file_with_other_columns_waits_then_runs(tmp_path):
    """F1: the previous file's picker values never reach the engine (it used to raise SystemExit
    and kill the session); the new file runs once its pickers are rebuilt."""
    first = _wide()
    df2, inf = _read(tmp_path, "toolkit.csv", first.rename(columns={
        "group": "PHAGE", "replicate": "PLATE", "diameter_mm": "DIAMETER_MM", "area_mm2": "AREA_MM2"}))
    stale = _sel(first)
    with pytest.raises(A.Stale):
        A.compute(df2, stale, inf)
    a = A.compute(df2, _sel(df2), inf)
    assert a["order"] == ["T4", "T7", "lambda"] and a["unit"] == "replicate"


def test_a_f1_header_only_file_is_a_message(tmp_path):
    df, inf = A.read_upload(_write(tmp_path, "h.csv", text="group,replicate,diameter_mm\n"))
    with pytest.raises(ps.StatsError, match="no data rows"):
        A.compute(df, _sel(df), inf)


def test_a_f2_uppercase_long_file_is_long_and_not_pooled(tmp_path):
    w = _wide()
    long_ = w.melt(id_vars=["group", "replicate"], var_name="METRIC", value_name="VALUE") \
             .rename(columns={"group": "GROUP", "replicate": "REPLICATE"})
    df, inf = _read(tmp_path, "long_upper.csv", long_)
    lay = A.layout_of(df)
    assert lay["long"] and lay["metric_col"] == "METRIC" and lay["metrics"] == ["diameter_mm", "area_mm2"]
    a = A.compute(df, _sel(df), inf)
    assert a["metric"] == "diameter_mm"
    assert len(a["d"]) == len(w)                                      # not 2 x pooled
    assert a["d"]["value"].mean() == pytest.approx(w["diameter_mm"].mean())
    with pytest.raises(ps.StatsError, match="holds 2 metrics"):       # VALUE itself is refused
        A.compute(df, _sel(df, value="VALUE"), inf) if "VALUE" in A.value_choices(df) else \
            ps.normalize(df, "GROUP", "VALUE", "REPLICATE", "metric")


def test_a_f2_metric_column_without_value_is_refused_not_pooled(tmp_path):
    w = _wide()
    long_ = w.melt(id_vars=["group", "replicate"], var_name="metric", value_name="measurement")
    df, inf = _read(tmp_path, "meas.csv", long_)
    with pytest.raises(ps.StatsError, match="would pool them"):
        A.compute(df, _sel(df), inf)


def test_a_f3_per_plate_without_plates_is_refused(tmp_path):
    df, inf = _read(tmp_path, "noplate.csv", _wide().drop(columns=["replicate"]))
    with pytest.raises(ps.StatsError) as ei:
        A.compute(df, _sel(df, unit="replicate"), inf)
    assert "Statistical unit = per plate needs a plate id" in A.message_of(ei.value)


def test_a_f4_semicolon_decimal_comma_and_one_column(tmp_path):
    w = _wide()
    df, inf = _read(tmp_path, "euro.csv", w, sep=";", decimal=",")
    assert inf["delimiter"] == ";" and inf["decimal"] == ","
    a = A.compute(df, _sel(df), inf)
    assert a["order"] == ["T4", "T7", "lambda"]
    assert a["d"]["value"].mean() == pytest.approx(w["diameter_mm"].mean())
    assert "semicolon-separated" in A.summary_lines(a)[0] and "WIDE" in A.summary_lines(a)[0]
    with pytest.raises(ps.StatsError, match="ONE column"):
        A.read_upload(_write(tmp_path, "one.csv", text="group|x\nT4|1\n".replace("|", " ")), "one.csv")


def test_a_f5_replicate_none_means_none(tmp_path):
    df, inf = _read(tmp_path, "w.csv", _wide())
    a = A.compute(df, _sel(df, replicate=A.NONE), inf)
    assert a["have_rep"] is False and a["unit"] == "plaque"
    assert A.replicate_arg(A.NONE) == A.NO_REPLICATE


def test_a_f8_samples_follow_the_picker_order(tmp_path):
    df, inf = _read(tmp_path, "w.csv", _wide())
    a = A.compute(df, _sel(df, order=["lambda", "T4"]), inf)
    assert a["order"] == ["lambda", "T4"] and a["omni"]["test"].lower().startswith(("welch", "student", "t"))
    assert any("not selected" in n for n in a["notes"])
    with pytest.raises(A.Stale):                                     # a name not in this file
        A.compute(df, _sel(df, order=["t4"]), inf)
    with pytest.raises(ps.StatsError, match="No sample is selected"):
        A.compute(df, _sel(df, order=[]), inf)


def test_a_f10_sentence_is_the_engines(tmp_path):
    df, inf = _read(tmp_path, "w.csv", _wide())
    a = A.compute(df, _sel(df), inf)
    assert "##" not in a["sentence"] and not a["sentence"].startswith(">")
    assert "diameter_mm" in a["sentence"] and "p = < " not in a["sentence"]
    o = ps._plot_opts(a["opts"])
    assert a["sentence"] == ps.paste_sentence("diameter_mm", a["summ"], a["omni"], a["unit"], True,
                                              a["opts"], centers=ps.center_table(a["d"], a["order"], o))


def _grouped_df():
    w = _wide(n=8)
    parts = []
    for i, host in enumerate(("WT", "dRecA")):
        x = w.copy(); x["host"] = host; x["diameter_mm"] = x["diameter_mm"] - 0.3 * i
        parts.append(x)
    return pd.concat(parts, ignore_index=True)


def test_a_f11_grouped_mode_passes_the_unit(tmp_path):
    df, inf = _read(tmp_path, "g.csv", _grouped_df())
    a = A.compute(df, _sel(df, subgroup="host"), inf)
    assert a["mode"] == "grouped" and a["unit"] == "replicate"
    b = A.compute(df, _sel(df, subgroup="host", unit="plaque"), inf)
    assert b["unit"] == "plaque"
    assert "plaques" in A.status_line(b)


def test_a_f13_palette_validation_and_theme_hint():
    pal, hint = A.palette_choice("", "ff0000; 00aa00 0000ff", 3)
    assert pal == ["#ff0000", "#00aa00", "#0000ff"] and hint == ""
    with pytest.raises(ps.StatsError, match="'zz' is not a colour"):
        A.palette_choice("", "ff0000,zz,0000ff", 3)
    with pytest.raises(ps.StatsError, match="needs 3"):
        A.palette_choice("", "red", 3)
    pal, hint = A.palette_choice("set2", "red", 3)
    assert pal == list(ps.PALETTES["set2"]) and "not used while a colour theme" in hint
    assert A.palette_choice("", ",,,", 3) == (list(ps.OKABE_ITO), "")


def test_a_f18_value_without_metric_is_wide(tmp_path):
    df, inf = _read(tmp_path, "v.csv", _wide().rename(columns={"diameter_mm": "value"}).drop(columns=["area_mm2"]))
    assert A.layout_of(df)["long"] is False and A.value_choices(df) == ["value"]
    assert A.compute(df, _sel(df), inf)["metric"] == "value"


def test_a_median_offers_only_iqr_ci_none_and_cli_words_are_translated():
    assert set(A.ERROR_CHOICES["median"]) == {"auto", "iqr", "ci95", "none"}
    assert "--" not in A.app_words("choose --equal-var no (Welch), or pass --log-y-drop-nonpositive")


def test_a_new_controls_dunnett_letters_variances(tmp_path):
    df, inf = _read(tmp_path, "w.csv", _wide())
    a = A.compute(df, _sel(df, compare="T7"), inf)
    assert a["omni"]["posthoc"] == "Dunnett" and a["omni"]["control"] == "T7"
    b = A.compute(df, _sel(df, equal_var="no"), inf)
    assert b["omni"]["equal_var"] in (False, "no") and "Welch" in b["omni"]["test"]
    c = A.compute(df, _sel(df, brackets="letters"), inf)
    fig = A.make_figure(c)
    assert "compact letter display" in getattr(fig, "annotation_note", "")
    plt.close(fig)


def test_a_log_y_nonpositive_message_and_drop(tmp_path):
    w = _wide(); w.loc[:2, "diameter_mm"] = 0.0
    df, inf = _read(tmp_path, "z.csv", w)
    with pytest.raises(ps.StatsError, match="zero or negative"):
        A.compute(df, _sel(df, log_y=True), inf)
    a = A.compute(df, _sel(df, log_y=True, log_drop=True), inf)
    assert any("not shown on the log axis" in n for n in a["notes"])


def test_a_f25_status_line(tmp_path):
    df, inf = _read(tmp_path, "w.csv", _wide())
    line = A.status_line(A.compute(df, _sel(df), inf))
    assert line.startswith("one-way ANOVA") and "plate means" in line
    assert "Bar: mean of the 3 plate means." in line and "Whisker: SEM of the plate means." in line


@pytest.mark.parametrize("grouped", [False, True])
def test_a_f23_zip_matches_screen(tmp_path, grouped):
    src = _grouped_df() if grouped else _wide()
    path = _write(tmp_path, "mydata.csv", src)
    df, inf = A.read_upload(path, "mydata.csv")
    sel = _sel(df, subgroup="host") if grouped else _sel(df, order=["lambda", "T4", "T7"])
    a = A.compute(df, sel, inf)
    z = zipfile.ZipFile(io.BytesIO(A.zip_bytes(df, a, sel, "mydata.csv", open(path, "rb").read())))
    names = z.namelist()
    base = A.file_base(a)
    assert "input_mydata.csv" in names
    for f in ("png", "svg", "pdf"):
        assert "%s.%s" % (base, f) in names and "%s_legend_key.%s" % (base, f) in names
    assert "%s_legend_text.txt" % base in names
    fig = A.make_figure(a)
    kz = zipfile.ZipFile(io.BytesIO(A.key_zip_bytes(fig, base))).namelist()
    plt.close(fig)
    assert set(kz) <= set(names)                       # single key download == the ZIP's names
    cfg = [n for n in names if n.startswith("run_config")]
    txt = z.read(cfg[0]).decode()
    assert str(tmp_path) not in txt and "/tmp" not in txt and "Temp" not in txt and '"out"' not in txt
    import json as _json
    c = _json.loads(txt)
    assert c["data"] == "mydata.csv" and c["groups"] == a["order"]
    rep = [n for n in names if "report" in n and n.endswith(".md")][0]
    head = "\n".join(z.read(rep).decode().splitlines()[:4])
    import re as _re
    assert _re.search(r"20\d\d-\d\d-\d\d \d\d:\d\d", head) and "Plaque Toolkit" in head, head
    if grouped:
        assert "grouped_table_diameter_mm.png" in names and "control_comparisons_table_diameter_mm.png" in names
    else:
        assert any(n.startswith("stats_table_") for n in names)


def test_a_browser_preview_equals_download_and_failed_upload(browser_page, tmp_path):
    """F12 (preview = PNG bytes), F19 (a failed upload clears results and stays), F24 (downloads
    disabled with nothing to download), F1 (a second file with other columns: no disconnect)."""
    import base64
    page, srv = browser_page(os.path.join(PS_DIR, "app_py.py"), tmp_path)
    off = "() => [...document.querySelectorAll('a.shiny-download-link.ct-off')].length"
    assert page.evaluate(off) == 8
    page.click("#load_example"); _idle(page, 3)
    assert page.evaluate(off) == 0
    src = page.get_attribute("#fig_preview img", "src")
    assert base64.b64decode(src.split(",", 1)[1]) == _download(page, srv.port, "dl_png")
    other = _write(tmp_path, "other.csv", _wide().rename(columns={
        "group": "PHAGE", "replicate": "PLATE", "diameter_mm": "DIAMETER_MM", "area_mm2": "AREA_MM2"}))
    page.set_input_files("#file", other); _idle(page, 3)
    assert page.query_selector("#shiny-disconnected-overlay") is None
    assert page.query_selector("#fig_preview img") is not None
    bad = _write(tmp_path, "bad.csv", text="just one column\nx\ny\n")
    page.set_input_files("#file", bad); _idle(page, 2)
    assert "Could not use bad.csv" in page.inner_text("#messages")
    assert page.query_selector("#fig_preview img") is None
    assert page.evaluate(off) == 8


# =========================================================================== B: agreement, the rest
def _agree_df(n=40):
    t, m = _pairs(n)
    return pd.DataFrame({"plaque_id": np.arange(1, n + 1), "toolkit_mm": t, "manual_mm": m})


def test_b_f4_semicolon_decimal_comma_and_one_column(tmp_path):
    df0 = _agree_df()
    p = _write(tmp_path, "euro.csv", df0, sep=";", decimal=",")
    df, note = B.read_paired(p, "euro.csv")
    assert "semicolon-separated" in note and "decimal commas" in note
    s = B.compute(df, *B.guess_columns(df))
    assert s["n"] == 40 and s["bias"] == pytest.approx(ag.full_stats(list(df0.toolkit_mm), list(df0.manual_mm))["bias"])
    with pytest.raises(ValueError, match="ONE column"):
        B.read_paired(_write(tmp_path, "one.csv", text="toolkit_mm\n1.0\n2.0\n"), "one.csv")


def test_b_f6_diameters_preferred_and_area_labelled(tmp_path):
    d = pd.DataFrame({"plaque_id": range(1, 11), "area_tool_mm2": np.linspace(1, 3, 10),
                      "area_fiji_mm2": np.linspace(1.1, 3.05, 10), "diam_tool_mm": np.linspace(1, 2, 10),
                      "diam_fiji_mm": np.linspace(1.02, 2.01, 10)})
    assert B.guess_columns(d) == ("diam_tool_mm", "diam_fiji_mm")
    assert B.unit_what_defaults("area_tool_mm2", "area_fiji_mm2", False) == ("mm²", "plaque area")
    assert B.unit_what_defaults("area_tool_mm2", "area_fiji_mm2", True) == ("mm", "plaque diameter")
    assert B.effective_unit(True, "µm") == "mm" and B.effective_unit(False, "µm") == "µm"


def test_b_f16_f17_plain_refusals():
    d = _agree_df()
    with pytest.raises(ValueError, match="same column"):
        B.compute(d, "toolkit_mm", "toolkit_mm")
    with pytest.raises(ValueError, match="at least 3 complete pairs; found 2|found 2 of 2"):
        B.compute(d.head(2), "toolkit_mm", "manual_mm")
    same = d.assign(manual_mm=d.toolkit_mm)
    with pytest.raises(ValueError, match="identical"):
        B.compute(same, "toolkit_mm", "manual_mm")
    assert B.id_like("plaque_id") and B.id_like("x", pd.Series(range(1, 30)))
    assert "plaque_id" not in B.guess_columns(d)
    d2 = d.copy(); d2.loc[:4, "manual_mm"] = np.nan
    s = B.compute(d2, "toolkit_mm", "manual_mm")
    assert (s["n"], s["_dropped"]) == (35, 5)
    assert "5 dropped" in B.stats_rows(s, "mm").iloc[0, 1]


def test_b_f17_icc_interval_cell_below_5_pairs():
    t, m = _pairs(4)
    s = ag.full_stats(t, m)
    assert "n/a (needs 5 pairs)" in B.icc_cell(s) and "nan" not in B.icc_cell(s)
    assert "nan" not in " ".join(B.stats_rows(s, "mm")["value"])


def test_b_f16_f22_f23_zip_is_the_screen(tmp_path):
    d = _agree_df()
    d.loc[0, "manual_mm"] = np.nan
    opts = {"label_tool": "Tool $x$ \\alpha $", "label_manual": "Fiji", "title": "Cost $5 vs $6",
            "unit": "mm", "what": "plaque diameter", "show_key": True, "show_stats": True,
            "convert_area": False}
    s = B.compute(d, "toolkit_mm", "manual_mm")
    z = zipfile.ZipFile(io.BytesIO(B.zip_bytes(d, "toolkit_mm", "manual_mm", opts, "mine.csv", b"raw")))
    names = z.namelist()
    assert "input_mine.csv" in names
    st = pd.read_csv(io.BytesIO(z.read("agreement_stats_plaque_diameter.csv")))
    assert int(st["n"][0]) == s["n"] == 39 and st["bias"][0] == pytest.approx(s["bias"])
    rep = z.read("agreement_report_plaque_diameter.md").decode()
    assert "proportional bias" in rep and "95% CI of each limit" in rep and "Tool $x$ \\alpha $" in rep
    import json as _json
    assert _json.loads(z.read("run_config_plaque_diameter.json"))["data"] == "mine.csv"
    with pytest.raises(ValueError, match="same column"):
        B.zip_bytes(d, "toolkit_mm", "toolkit_mm", opts)
    # a $ title / label never breaks the figure (F22)
    sf = B.labels(opts)
    fig = B.make_fig(s, "both", "mm", sf["label_tool"], sf["label_manual"], sf["title"])
    assert len(B.png_bytes(fig)) > 1000
    plt.close(fig)
    # one `$` in each label: the joined Bland-Altman axis label must not become mathtext
    sf = B.labels({"label_tool": "Tool $x", "label_manual": "Ref $y", "title": None})
    fig = B.make_fig(s, "bland", "mm", sf["label_tool"], sf["label_manual"], None)
    B.png_bytes(fig)
    assert fig.axes[0].yaxis.label.get_text() == "Tool \\$x - Ref \\$y (mm)"
    plt.close(fig)


def test_b_browser_preview_equals_download_area_and_failed_upload(browser_page, tmp_path):
    """F7 (preview = PNG bytes, no sideways scroll), F6 (area labels, Unit disabled while
    converting), F19 (failed upload clears and stays), F24 (downloads disabled)."""
    import base64
    page, srv = browser_page(os.path.join(AG_DIR, "app_py.py"), tmp_path, width=390)
    page.click("#load_example"); _idle(page, 3)
    src = page.get_attribute("#fig img", "src")
    assert base64.b64decode(src.split(",", 1)[1]) == _download(page, srv.port, "dl_png")
    assert page.evaluate("() => document.documentElement.scrollWidth") <= 390
    d = pd.DataFrame({"plaque_id": range(1, 21), "area_tool_mm2": np.linspace(1, 3, 20) + 0.01 * np.sin(range(20)),
                      "area_fiji_mm2": np.linspace(1.1, 3.05, 20)})
    page.set_input_files("#file", _write(tmp_path, "areas.csv", d)); _idle(page, 3)
    # the label update is a second server round trip: wait for it (a loaded machine is slow)
    page.wait_for_function("() => document.getElementById('unit').value === 'mm²'", timeout=30000)
    assert page.input_value("#what") == "plaque area"
    page.set_checked("#convert_area", True); _idle(page, 2)
    page.wait_for_function("() => document.getElementById('unit').value === 'mm' && "
                           "document.getElementById('unit').disabled", timeout=30000)
    page.set_input_files("#file", _write(tmp_path, "bad.csv", text="only\n1\n2\n")); _idle(page, 2)
    assert "Could not use bad.csv" in page.inner_text("#messages")
    assert page.query_selector("#fig img") is None
    assert page.evaluate("() => [...document.querySelectorAll('a.shiny-download-link.ct-off')].length") == 13
