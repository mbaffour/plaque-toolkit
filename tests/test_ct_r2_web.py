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
