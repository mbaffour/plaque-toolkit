"""CT-R2 web apps (Shiny for Python): plaque_stats/app_py.py ("A", statistics) and
plaque_stats/agreement/app_py.py ("B", agreement).

One test (or a few) per finding of the round-2 click-through (N1..N14). The server logic is in
module-level helpers of the two apps so most of it is tested without a browser; the browser tests
reuse the harness of tests/test_ct_r1_web.py and skip cleanly when Chrome / playwright is missing.
"""
import io
import json
import os
import re
import zipfile

import numpy as np
import pandas as pd
import pytest

import test_ct_r1_web as R1
from test_ct_r1_web import browser_page, _idle, _tab, _download      # noqa: F401  (fixture + helpers)

A, B, ag, ps, lk = R1.A, R1.B, R1.ag, R1.ps, R1.lk
AG_DIR, PS_DIR = R1.AG_DIR, R1.PS_DIR


# =========================================================================== data builders
def _area_diam_df(n=30, seed=5):
    """The tester's data/agree_area_diam.csv: plaque_id, AREA_MM2, fiji_area, DIAMETER_MM, fiji_diam."""
    rng = np.random.default_rng(seed)
    d_f = rng.uniform(1.0, 3.5, n)
    d_t = d_f * 0.98 + rng.normal(0, 0.04, n)
    return pd.DataFrame({"plaque_id": np.arange(1, n + 1),
                         "AREA_MM2": np.round(np.pi * d_t ** 2 / 4, 3),
                         "fiji_area": np.round(np.pi * d_f ** 2 / 4, 3),
                         "DIAMETER_MM": np.round(d_t, 3), "fiji_diam": np.round(d_f, 3)})


def _wide_like_df(n=12):
    """The shipped wide.xlsx layout (the statistics app's file): one diameter, one area, one
    turbidity column: there is no same-kind pair in it."""
    rng = np.random.default_rng(1)
    d = rng.uniform(1.0, 3.0, n)
    return pd.DataFrame({"group": ["T4"] * n, "replicate": ["plate1"] * n, "diameter_mm": d.round(3),
                         "area_mm2": (np.pi * d ** 2 / 4).round(3), "turbidity": rng.uniform(0, 1, n).round(3)})


def _near_zero_df(n=60, seed=2):
    """The tester's agree_negative.csv: tool negative, manual positive, the mean of the two near 0."""
    rng = np.random.default_rng(seed)
    m = rng.uniform(0.5, 1.6, n)
    t = -(m * 0.98 + rng.normal(0, 0.05, n))
    return pd.DataFrame({"plaque_id": np.arange(1, n + 1), "toolkit_mm": t.round(3), "manual_mm": m.round(3)})


def _pairs_df(n=40, seed=3):
    t, m = R1._pairs(n, seed)
    return pd.DataFrame({"toolkit_mm": t, "manual_mm": m})


OPTS = {"label_tool": "Plaque Toolkit", "label_manual": "Fiji / ImageJ", "title": "", "unit": "mm",
        "what": "diameters", "show_key": True, "show_stats": True, "convert_area": False}


def _zip(df, tool="toolkit_mm", manual="manual_mm", **kw):
    opts = dict(OPTS, **kw)
    return zipfile.ZipFile(io.BytesIO(B.zip_bytes(df, tool, manual, opts, "mine.csv", b"raw")))


def _md_table(report_text):
    rows = []
    for ln in report_text.splitlines():
        if ln.startswith("|") and not ln.startswith("|---") and not ln.startswith("| statistic"):
            cells = [c.strip() for c in ln.strip("|").split(" | ")]
            rows.append((cells[0].strip("| "), cells[1].strip(" |")))
    return rows


# =========================================================================== N1 (B): one quantity
def test_n1_guess_pairs_two_diameters_never_area_with_diameter():
    d = _area_diam_df()
    t, m = B.guess_columns(d)
    assert (t, m) == ("DIAMETER_MM", "fiji_diam")          # was AREA_MM2 vs fiji_diam
    assert not B.mixed_quantities(t, m)
    # no diameter pair: both areas
    t, m = B.guess_columns(d[["plaque_id", "AREA_MM2", "fiji_area"]])
    assert (t, m) == ("AREA_MM2", "fiji_area")
    # diameter pair next to an area pair: the diameters win
    assert B.guess_columns(d.drop(columns=["fiji_area"])) == ("DIAMETER_MM", "fiji_diam")


def test_n1_file_without_a_same_kind_pair_still_picks_and_warns():
    d = _wide_like_df()
    t, m = B.guess_columns(d.drop(columns=["group", "replicate"]))
    assert t and m and t != m                              # never a blank wait
    assert B.mixed_quantities("diameter_mm", "area_mm2") and B.mixed_quantities("fiji_area", "DIAMETER_MM")
    assert not B.mixed_quantities("toolkit_mm", "manual_mm")        # unnamed kinds: no warning
    assert not B.mixed_quantities("area_tool", "area_fiji")


def test_n1_download_gate_and_compared_line():
    assert B.downloads_blocked("AREA_MM2", "fiji_diam", False)
    assert not B.downloads_blocked("AREA_MM2", "fiji_diam", True)           # "Compare anyway"
    assert not B.downloads_blocked("DIAMETER_MM", "fiji_diam", False)
    assert B.compared_text("DIAMETER_MM", "fiji_diam", False, "mm") == "Compared: diameter (mm) vs diameter (mm)"
    assert B.compared_text("AREA_MM2", "fiji_area", False, "mm²") == "Compared: area (mm²) vs area (mm²)"
    assert "converted from area" in B.compared_text("AREA_MM2", "fiji_area", True, "mm")
    assert "one column looks like an area and the other like a diameter: agreement between different " \
           "quantities is meaningless" in B.MIXED_WARNING


def test_n1_browser_mixed_pair_warns_disables_downloads_until_compare_anyway(browser_page, tmp_path):
    page, srv = browser_page(os.path.join(AG_DIR, "app_py.py"), tmp_path)
    p = R1._write(tmp_path, "agree_area_diam.csv", _area_diam_df())
    page.set_input_files("#file", p); _idle(page, 3)
    assert page.input_value("#tool") == "DIAMETER_MM" and page.input_value("#manual") == "fiji_diam"
    assert "Compared: diameter (mm) vs diameter (mm)" in page.inner_text("#compared_line")
    assert "agreement between different quantities" not in page.inner_text("#messages")
    off = "() => [...document.querySelectorAll('a.shiny-download-link.ct-off')].length"
    assert page.evaluate(off) == 0
    page.select_option("#tool", "AREA_MM2"); _idle(page, 2)               # now an area vs a diameter
    page.wait_for_function(off + " > 0", timeout=20000)
    assert "agreement between different quantities is meaningless" in page.inner_text("#messages")
    page.set_checked("#compare_anyway", True); _idle(page, 2)
    page.wait_for_function(off + " === 0", timeout=20000)
    page.set_input_files("#file", p); _idle(page, 3)                      # a new file: the tick is gone
    page.select_option("#tool", "AREA_MM2"); _idle(page, 2)
    page.wait_for_function(off + " > 0", timeout=20000)


# =========================================================================== N2 (B): screen == ZIP
@pytest.mark.parametrize("n", [10, 40])
def test_n2_screen_table_is_the_zip_report_table(n):
    d = _pairs_df(n)
    s = B.compute(d, "toolkit_mm", "manual_mm")
    screen = [tuple(r) for r in B.stats_rows(s, "mm").itertuples(index=False)]
    rep = _zip(d).read("agreement_report_diameters.md").decode()
    assert _md_table(rep)[:len(screen)] == screen
    labels_ = [r[0] for r in screen]
    assert any("prediction interval" in x for x in labels_) == (n < 20)    # the row the screen lacked
    assert "95% CI of each limit" in labels_
    assert not re.search(r"-0\.0+(?!\d)", " ".join(r[1] for r in screen))


def test_n2_no_negative_zero_one_number_format():
    s = B.compute(_pairs_df(), "toolkit_mm", "manual_mm")
    s = dict(s, ba_slope=-0.00001, intercept=-0.0000001, bias=-0.0001)
    vals = " ".join(r[1] for r in B.report_rows(s, "mm"))
    assert "-0.000" not in vals and "slope +0.0000," in vals
    rep = _zip(_pairs_df(10)).read("agreement_report_diameters.md").decode()
    assert not re.search(r"(?<![\w.])-0\.0+(?!\d)", rep)


# =========================================================================== N4 (B): CLI sentence
def test_n4_default_sentence_is_the_cli_sentence_word_for_word(tmp_path):
    d = _pairs_df(30)
    csv = R1._write(tmp_path, "pairs.csv", d)
    out = str(tmp_path / "cli")
    ag.main([csv, "--tool", "toolkit_mm", "--manual", "manual_mm", "--out", out, "--formats", "png"])
    rep = open([os.path.join(out, f) for f in os.listdir(out) if f.endswith(".md")][0], encoding="utf-8").read()
    cli = [ln[2:] for ln in rep.splitlines() if ln.startswith("> ")][0]
    mine = B.sentence_of(B.compute(d, "toolkit_mm", "manual_mm"), "mm", B.DIAM_WHAT, "Plaque Toolkit", "Fiji / ImageJ")
    assert mine == cli and mine.startswith("Diameters measured with")
    # the ZIP says the same, whatever the box holds
    z = _zip(d, what="")
    assert "agreement_measurements.png" in z.namelist()
    assert ("> " + B.sentence_of(B.compute(d, "toolkit_mm", "manual_mm"), "mm", "", "Plaque Toolkit",
                                  "Fiji / ImageJ")) in z.read("agreement_report_measurements.md").decode()


# =========================================================================== N8 (B): key names + dpi
@pytest.mark.parametrize("k", ["both", "a", "b"])
def test_n8_standalone_key_has_the_names_of_the_zip_and_the_figures_dpi(k):
    d = _pairs_df(25)
    s = B.compute(d, "toolkit_mm", "manual_mm")
    fig = B.make_fig(s, B.FIGURES[k][1])
    kz = zipfile.ZipFile(io.BytesIO(B.key_zip_bytes(fig, B.fig_base(k, "diameters"))))
    allz = _zip(d)
    key_names = sorted(kz.namelist())
    assert key_names and all(n in allz.namelist() for n in key_names)
    # the same file, byte for byte in content type and pixel size (the key PNG is at the figure's dpi)
    from PIL import Image
    png = [n for n in key_names if n.endswith(".png")][0]
    a_img, b_img = Image.open(io.BytesIO(kz.read(png))), Image.open(io.BytesIO(allz.read(png)))
    assert a_img.size == b_img.size
    assert round(a_img.info["dpi"][0]) == round(b_img.info["dpi"][0]) == B.FIG_DPI
    assert kz.read([n for n in key_names if n.endswith(".txt")][0]) == allz.read([n for n in key_names if n.endswith(".txt")][0])
    # the figure files themselves carry the same stem
    assert B.fig_base(k, "diameters") + ".png" in allz.namelist()
    R1.plt.close(fig)


# =========================================================================== N9 (B)
def test_n9_icc_interval_na_always_says_why():
    d = _near_zero_df()
    s = B.compute(d, "toolkit_mm", "manual_mm")
    assert not (ag._finite(s["icc_lo"]) and ag._finite(s["icc_hi"]))       # the engine has no interval here
    cell = B.icc_cell(s)
    assert re.search(r"\[n/a \([a-z].{10,}\)\]", cell), cell
    assert "[n/a]" not in B.stats_rows(s, "mm")["value"].iloc[3]
    t, m = R1._pairs(4)
    assert "needs 5 pairs" in B.icc_cell(ag.full_stats(t, m))


def test_n9_percentage_bias_blank_when_the_mean_is_near_zero():
    d = _near_zero_df()
    s = B.compute(d, "toolkit_mm", "manual_mm")
    assert abs(s["pct_bias"]) > 1000                                      # the engine's number
    row = dict(B.report_rows(s, "mm"))["mean bias (mm)"]
    assert "n/a: mean near zero" in row and "%" not in row
    z = _zip(d)
    rep = z.read("agreement_report_diameters.md").decode()
    assert "n/a: mean near zero" in rep and "15" not in re.findall(r"\| mean bias.*", rep)[0]
    csv = pd.read_csv(io.BytesIO(z.read("agreement_stats_diameters.csv")))
    assert csv["pct_bias"].isna().all()
    assert "%" not in B.sentence_of(s, "mm", "diameters", "T", "M").split("mean bias of")[1].split("with 95%")[0]
    # an ordinary file keeps its percentage
    s2 = B.compute(_pairs_df(), "toolkit_mm", "manual_mm")
    assert re.search(r"\([+-]?\d+\.\d%\)", dict(B.report_rows(s2, "mm"))["mean bias (mm)"])


def test_n9_id_like_and_convert_on_diameter_columns_warn():
    d = _pairs_df().assign(plaque_id=range(1, 41))
    w = B.column_warnings(d, "plaque_id", "manual_mm", False)
    assert len(w) == 1 and "plaque_id" in w[0] and "identifier" in w[0]
    assert B.column_warnings(d, "toolkit_mm", "manual_mm", False) == []
    w = B.column_warnings(_area_diam_df(), "DIAMETER_MM", "fiji_diam", True)
    assert len(w) == 2 and all("looks like a diameter" in x for x in w)
    assert B.column_warnings(_area_diam_df(), "AREA_MM2", "fiji_area", True) == []


# =========================================================================== A: shared helpers
def _wide(**kw):
    return R1._wide(**kw)


def _with_host(df, hosts=("a", "b")):
    g = df.copy()
    g["host"] = [hosts[i % len(hosts)] for i in range(len(g))]
    return g


def _app_texts(df, sel, with_zip=True):
    """Everything the app shows or writes for one analysis that came from the engine."""
    a = A.compute(df, sel)
    out = {"sentence": a["sentence"], "status": A.status_line(a), "summary": "\n".join(A.summary_lines(a))}
    fig = A.make_figure(a)
    try:
        out["key text"] = A.app_words(lk.text_starter(lk.from_figure(fig)) or "")
        kz = zipfile.ZipFile(io.BytesIO(A.key_zip_bytes(fig, A.file_base(a))))
        for n in kz.namelist():
            if n.endswith(".txt"):
                out["key zip " + n] = kz.read(n).decode("utf-8")
    finally:
        R1.plt.close(fig)
    if with_zip:
        z = zipfile.ZipFile(io.BytesIO(A.zip_bytes(df, a, sel, "x.csv", b"")))
        for n in z.namelist():
            if n.endswith((".md", ".txt", ".csv", ".json")):
                out["zip " + n] = z.read(n).decode("utf-8", "replace")
    return out


_SCENARIOS = {
    "default": {}, "equal": dict(equal_var="yes"), "unequal": dict(equal_var="no"),
    "per plaque": dict(unit="plaque"), "per plate": dict(unit="replicate"),
    "non-parametric": dict(parametric="nonparametric"), "dunnett": dict(compare="T4"),
    "median": dict(center="median", error="iqr"), "letters": dict(brackets="letters"),
    "all pairs": dict(brackets="all"), "palette": dict(palette_name="okabe"),
    "log": dict(log_y=True), "unequal parametric": dict(parametric="parametric", equal_var="no"),
}


# =========================================================================== N5 + N13 (A)
@pytest.mark.parametrize("name", list(_SCENARIOS))
def test_n5_no_cli_option_in_anything_the_app_shows_or_writes(name):
    df = _wide()
    for tag, d in (("wide", df), ("no plates", df.drop(columns=["replicate"]))):
        sel = R1._sel(d, **_SCENARIOS[name])
        try:
            texts = _app_texts(d, sel, with_zip=(tag == "wide" or name == "default"))   # the ZIP is slow
        except (ps.StatsError, SystemExit) as e:
            texts = {"message": A.message_of(e)}
        for where, t in texts.items():
            assert not re.search(r"--[a-z]", t), (name, tag, where, re.search(r".{0,50}--[a-z].{0,50}", t.replace("\n", " ")).group(0))


def test_n5_one_plate_per_group_grouped_and_unequal_spread_files_too():
    df = _wide()
    one = df.assign(replicate="p1")
    g = _with_host(df)
    uv = pd.read_csv(os.path.join(R1.ROOT, "tests", "fixtures", "ct_r1_parity_unequalvar_3x8.csv"))
    for d, kw in ((one, {}), (g, dict(subgroup="host")), (g, dict(subgroup="host", unit="plaque")),
                  (uv, {}), (uv, dict(equal_var="yes"))):
        for where, t in _app_texts(d, R1._sel(d, **kw)).items():
            assert not re.search(r"--[a-z]", t), (kw, where)


def test_n5_the_option_mapping_covers_every_engine_option():
    for opt in ps.build_args()._option_string_actions:
        if opt.startswith("--"):
            out = A.app_words("Use `%s` or %s yes, then %s" % (opt, opt, opt))
            assert "--" not in out, (opt, out)
    assert A.app_words("(the statistical unit chosen: --unit plaque)") == "(Statistical unit = per plaque)"
    assert A.app_words("`--equal-var no`: Welch") == "Variances = unequal: Welch"
    assert A.app_words("see --nonsense-flag now") == "see nonsense flag now"


def test_n13_variances_choices_say_what_auto_can_detect():
    html = R1._html(A)
    assert "auto (Welch when Levene rejects equal spread; needs 8+ plates per sample to detect it)" in html
    assert "equal (ANOVA + Tukey)" in html and "unequal (Welch ANOVA + Games-Howell)" in html
    assert "auto (Levene test)" not in html


def test_n13_spread_warning_says_where_to_set_variances():
    uv = pd.read_csv(os.path.join(R1.ROOT, "tests", "fixtures", "ct_r1_parity_unequalvar_3x8.csv"))
    a = A.compute(uv, R1._sel(uv, equal_var="yes"))
    spread = [w for w in a["warnings"] if "safer analysis" in w]
    assert spread and spread[0].endswith("Set Variances to unequal to follow this advice.")
    assert "Set Variances to unequal to follow this advice." in "\n".join(A.summary_lines(a))
    assert A.with_advice(["x. Welch ANOVA + Games-Howell is the safer analysis."], "no") == \
        ["x. Welch ANOVA + Games-Howell is the safer analysis."]            # already chosen: no advice
    z = zipfile.ZipFile(io.BytesIO(A.zip_bytes(uv, a, R1._sel(uv, equal_var="yes"), "x.csv", b"")))
    rep = z.read([n for n in z.namelist() if n.startswith("report_")][0]).decode()
    assert "Set Variances to unequal to follow this advice." in rep


# =========================================================================== N11 (A)
def test_n11_subgroup_that_cannot_work_is_refused_in_plain_words():
    df = _with_host(_wide())
    base = R1._sel(df, subgroup="host")
    assert A.compute(df, base)["mode"] == "grouped"                              # a real subgroup works
    cases = [(dict(subgroup="group"), "same column as Group"),
             (dict(subgroup="replicate"), r"Replicate \(plate\) column"),
             (dict(subgroup="one"), "only one level"),
             (dict(subgroup="host", order=["T4"]), None)]
    one = df.assign(one="x")
    for kw, msg in cases[:3]:
        with pytest.raises(ps.StatsError, match=msg):
            A.compute(one, R1._sel(one, **kw))
    # a column where no sample has two levels: each sample has its own single host
    nested = df.assign(host=df["group"].map({"T4": "h1", "T7": "h2", "lambda": "h3"}))
    with pytest.raises(ps.StatsError, match="none of the selected samples"):
        A.compute(nested, R1._sel(nested, subgroup="host"))
    # judged on the SELECTED samples: only T4 selected with a host of one level -> one level
    sub = df.assign(host=np.where(df["group"] == "T4", "a", np.where(np.arange(len(df)) % 2, "b", "c")))
    with pytest.raises(ps.StatsError, match="only one level"):
        A.compute(sub, R1._sel(sub, subgroup="host", order=["T4"]))
    for kw, _ in cases[:3]:
        try:
            A.compute(one, R1._sel(one, **kw))
        except ps.StatsError as e:
            assert "comparisons tested" not in str(e) and "--" not in A.message_of(e)


# =========================================================================== N6 size line (A)
def test_n6_size_line_states_the_real_size_and_why():
    sel = R1._sel(_wide(), width=9, height=5.4)
    assert A.size_line((9.0, 7.4), sel) == \
        "figure: 9.0 x 7.4 in: the key is below the plot, so it is taller than the Height slider"
    assert A.size_line((9.0, 5.4), sel) == "figure: 9.0 x 5.4 in"
    assert A.size_line((9.0, 5.5), sel) == "figure: 9.0 x 5.5 in"                   # inside the tolerance
    assert "wider than the Width slider" in A.size_line((10.2, 5.4), sel)
    assert "the key is below" not in A.size_line((9.0, 7.4), dict(sel, place_key=False))


def test_n6_figure_size_uses_the_engines_final_size_else_the_png():
    df = _wide()
    a = A.compute(df, R1._sel(df))
    fig = A.make_figure(a)
    png = A.fig_bytes(fig, "png")
    from PIL import Image
    w_px, h_px = Image.open(io.BytesIO(png)).size
    if not any(hasattr(fig, n) for n in ("final_size_in", "figure_size_in_final")):     # before the engine merge
        assert A.figure_size_in(fig, png) == (pytest.approx(w_px / 300.0), pytest.approx(h_px / 300.0))
    fig.final_size_in = (9.0, 7.4)                                  # what the engine will expose
    assert A.figure_size_in(fig, png) == (9.0, 7.4)
    del fig.final_size_in
    fig.figure_size_in_final = (8.0, 6.0)                           # the other name it may use
    assert A.figure_size_in(fig, png) == (8.0, 6.0)
    R1.plt.close(fig)


# =========================================================================== N7 literal labels (A)
def test_n7_dollar_and_backslash_in_labels_are_drawn_literally():
    import matplotlib.text as mtext
    df = _wide()
    title, yl = r"Run \1 $5 and $x$", r"Size $\mu$m \alpha"
    assert A.literal_text(title) == r"Run \1 \$5 and \$x\$" and A.literal_text(None) is None
    a = A.compute(df, R1._sel(df, title=title, ylabel=yl))
    fig = A.make_figure(a)
    found = {}
    for t in fig.findobj(mtext.Text):
        s_, math = t._preprocess_math(t.get_text())
        if "Run" in s_ or "Size" in s_:
            found[s_.split()[0]] = (s_, math)
    assert found["Run"] == (title, False) and found["Size"] == (yl, False)       # shown as typed, not maths
    assert len(A.fig_bytes(fig, "png")) > 1000
    R1.plt.close(fig)


# =========================================================================== N10 palette (A)
def test_n10_empty_custom_palette_is_no_palette_and_never_colours_the_violins():
    pal, hint = A.palette_choice("", ",,,", 3)
    assert pal is None and "no colours" in hint
    pal, hint = A.palette_choice("", " ; , ", 3)
    assert pal is None and hint
    df = _wide()
    a = A.compute(df, R1._sel(df, palette_custom=",,,"))
    assert a["opts"]["violin_fill"] == "auto" and list(a["opts"]["palette"]) == list(ps.DEFAULTS["palette"])
    assert "no colours" in "\n".join(A.summary_lines(a))
    # a real custom palette still switches the violins to sample colours; a named theme ignores ",,,"
    b = A.compute(df, R1._sel(df, palette_custom="#0072B2,#D55E00,#009E73"))
    assert b["opts"]["violin_fill"] == "group"
    assert A.palette_choice("okabe", ",,,", 3)[1] == ""


# =========================================================================== N12 (A)
def test_n12_a_non_csv_saved_as_csv_never_shows_pandas_text(tmp_path):
    xl = tmp_path / "renamed.csv"
    _wide().to_excel(str(tmp_path / "real.xlsx"), index=False)
    xl.write_bytes((tmp_path / "real.xlsx").read_bytes())
    for p in (xl,):
        with pytest.raises(ps.StatsError) as e:
            A.read_upload(str(p), p.name)
        msg = A.message_of(e.value)
        assert not re.search(r"tokenizing|C error|Expected \d+ fields|codec|utf-8", msg, re.I), msg
        assert p.name in msg or "CSV" in msg or "Excel" in msg
    # the fallback itself (what the app says when the engine raises a pandas error)
    import unittest.mock as um
    with um.patch.object(ps, "read_table", side_effect=RuntimeError("Error tokenizing data. C error: x")):
        with pytest.raises(ps.StatsError, match=r"does not look like a CSV table \(is it an Excel or binary file saved with a \.csv name\?\)"):
            A.read_upload("whatever.csv", "whatever.csv")


# =========================================================================== N14 (A)
def test_n14_group_and_replicate_are_never_value_choices():
    df = _wide().assign(group=lambda d: d["group"].map({"T4": 1, "T7": 2, "lambda": 3}),
                        replicate=lambda d: d["replicate"].str.replace("plate", "").astype(int))
    assert set(A.value_choices(df)) == {"group", "replicate", "diameter_mm", "area_mm2"}      # all numeric
    assert A.value_choices(df, ("group", "replicate")) == ["diameter_mm", "area_mm2"]
    d = A.picker_defaults(df)
    assert d["value"] == "diameter_mm" and d["group"] == "group"
    a = A.compute(df, R1._sel(df))
    assert a["order"] == ["1", "2", "3"]
    with pytest.raises(A.Stale):                                        # the value is still the group column
        A.compute(df, R1._sel(df, value="group"))
    only = pd.DataFrame({"g": [1, 1, 2, 2], "p": [1, 2, 1, 2]})
    with pytest.raises(ps.StatsError, match="every numeric column is also chosen as Group or Replicate"):
        A.compute(only, R1._sel(only, group="g", replicate="p", value="p"))


def test_n14_removed_control_falls_back_to_all_pairs_and_says_so():
    df = _wide()
    a = A.compute(df, R1._sel(df, compare="T4", order=["T7", "lambda"]))     # T4 removed from the samples
    assert a["opts"]["posthoc"] == "auto" and a["opts"]["control"] is None
    assert any("Compare to was “T4”" in n and "all pairs" in n for n in a["notes"])
    b = A.compute(df, R1._sel(df, compare="T4"))
    assert b["opts"]["posthoc"] == "dunnett" and b["opts"]["control"] == "T4"


def test_n14_zip_report_names_the_uploaded_file(tmp_path):
    df = _wide()
    sel = R1._sel(df)
    a = A.compute(df, sel)
    z = zipfile.ZipFile(io.BytesIO(A.zip_bytes(df, a, sel, "example_data_wide.csv", b"raw")))
    rep = z.read([n for n in z.namelist() if n.startswith("report_")][0]).decode()
    assert "example_data_wide.csv, 108 rows" in rep and "in-memory" not in rep
    cfg = json.loads(z.read([n for n in z.namelist() if n.startswith("run_config")][0]))
    assert cfg["data"] == "example_data_wide.csv"


def test_n14_browser_example_resets_file_box_and_value_choices_skip_labels(browser_page, tmp_path):
    page, srv = browser_page(os.path.join(PS_DIR, "app_py.py"), tmp_path)
    df = _wide().assign(group=lambda d: d["group"].map({"T4": 1, "T7": 2, "lambda": 3}),
                        replicate=lambda d: d["replicate"].str.replace("plate", "").astype(int))
    page.set_input_files("#file", R1._write(tmp_path, "numeric_names.csv", df)); _idle(page, 3)
    box = "() => document.querySelector('#file').closest('.input-group').querySelector('input[type=text]').value"
    assert page.evaluate(box) == "numeric_names.csv"
    opts = page.evaluate("() => [...document.getElementById('value').options].map(o => o.value)")
    assert opts == ["diameter_mm", "area_mm2"]
    page.click("#load_example"); _idle(page, 3)
    page.wait_for_function("() => document.querySelector('#file').closest('.input-group')"
                           ".querySelector('input[type=text]').value === ''", timeout=20000)
    assert page.inner_text("#size_line").startswith("figure: ")


def test_n14_browser_removing_the_control_sample_resets_compare_to(browser_page, tmp_path):
    page, srv = browser_page(os.path.join(PS_DIR, "app_py.py"), tmp_path)
    page.click("#load_example"); _idle(page, 3)
    names = page.evaluate("() => [...document.getElementById('compare').options].map(o => o.value)")
    ctl = names[1]
    page.select_option("#compare", ctl); _idle(page, 2)
    page.evaluate("(c) => document.getElementById('order').selectize.removeItem(c)", ctl); _idle(page, 3)
    page.wait_for_function("() => document.getElementById('compare').value === 'all'", timeout=20000)
    page.wait_for_function("(c) => document.getElementById('messages').innerText.includes('Compare to was')",
                           arg=ctl, timeout=20000)
    assert page.query_selector("#fig_preview img") is not None
