"""Paper style for the R Shiny app (plaque_stats/app.R, 1.3.0): the paper_style.json that
CFU Plot Studio 0.4.0 writes gives every figure of a paper the same sample colours (keyed by
NAME) and font. Drives tests/r_paper_style_check.R with Rscript (shiny::testServer); skipped
where R or the app's packages are missing, exactly as test_legend_key::test_r_shiny_app_key.

The byte-identity check renders the default violins with the 1.2.0 app.R (commit 176656b) and
with this one, each in its own Rscript, and compares the SVG files byte for byte; it skips with
a note when that commit is not in this clone (shallow clone, release archive).
"""
import os
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(ROOT, "tests", "fixtures")


@pytest.fixture(scope="module")
def r_output(tmp_path_factory):
    rscript = shutil.which("Rscript")
    if not rscript:
        pytest.skip("R not installed")
    pkgs = 'c("shiny","ggplot2","dplyr","tidyr","readr","DT","rstatix","ggpubr","svglite","jsonlite")'
    ok = subprocess.run([rscript, "-e", "q(status = !all(sapply(%s, requireNamespace, "
                         "quietly = TRUE)))" % pkgs], capture_output=True)
    if ok.returncode != 0:
        pytest.skip("the R app's packages are not installed")
    out_dir = tmp_path_factory.mktemp("paper_style")
    r = subprocess.run([rscript, os.path.join(ROOT, "tests", "r_paper_style_check.R")],
                       cwd=os.path.join(ROOT, "plaque_stats"), capture_output=True, text=True,
                       env=dict(os.environ, OUT_DIR=str(out_dir)), timeout=600)
    assert r.returncode == 0, r.stderr[-3000:]
    got = dict(line.split("=", 1) for line in r.stdout.splitlines() if "=" in line)
    got["_out_dir"] = str(out_dir)
    return got


def _pairs(s):
    return dict(x.split(":", 1) for x in s.split("|"))


def test_fixtures_are_the_cfu_shape():
    import json
    for name in ("paper_style_times.json", "paper_style_missing_font.json"):
        with open(os.path.join(FIXTURES, name)) as fh:
            doc = json.load(fh)
        assert doc["kind"] == "paper_style" and doc["app"] == "CFU Plot Studio"
        s = doc["settings"]
        assert {"font_family", "font_size", "axis_color", "axis_line_width", "sample_palette"} <= set(s)
        # cfu-only keys the R app must ignore are present in the fixture
        assert {"plot_title", "legend_position", "x_angle", "download_width", "y_min", "time_palette"} <= set(s)


def test_r_shiny_defaults_byte_identical(r_output):
    """1. With every input at its UI default the violins and the error bars of the mean (layer data)
    are byte-identical to 1.2.0, and a paper style that changes nothing changes nothing at all.

    CT-R1 deliberately changed the default FIGURE's bytes (the SVGs are NOT pinned to 1.2.0 any more):
    F6 the centre line is drawn (it had stroke width 0 under ggplot2 4.x), F7 brackets start
    above the tallest plaque, F23 the jitter is seeded and the n row / stars follow the base
    size; the colour-by-sample view (F18) draws plates in greys, so its key differs too.
    CT-R3 changed it again (F7): under grey violins the plates take the Okabe-Ito colours of the Python
    engine, the n label reads "n = 70 plaques / N = 3 plates", the value sits next to every bar, and the
    legend text starter carries the Python wording and the bar / whisker sentence; so the n-label layer
    and the default key files (svg + text) are no longer identical to 1.2.0 (pins moved to "differ").
    "A paper style does nothing at the defaults" is now pinned against THIS app.R rendered with an inert
    style file (INERT_*): every output is byte-identical."""
    if "BYTE_SKIP" in r_output:
        pytest.skip("byte-identity vs 1.2.0 skipped: " + r_output["BYTE_SKIP"])
    assert r_output["BYTE_RENDER"] == "TRUE|TRUE"
    for name in ("layers_violin", "layers_errorbar"):
        assert r_output["BYTE_" + name] == "identical", name
    # the deliberate changes are real (CT-R1: the figure; CT-R3 F7: the n label and the default key)
    for name in ("layers_ntext", "default_legend_key", "default_legend_text", "default_key_on", "default_key_off"):
        assert r_output["BYTE_" + name] == "differ", name
    assert r_output["INERT_RENDER"] == "TRUE"
    inert = {k: v for k, v in r_output.items() if k.startswith("INERT_") and k != "INERT_RENDER"}
    assert len(inert) == 11 and set(inert.values()) == {"identical"}, inert


def test_r_shiny_colours_keyed_by_name(r_output):
    """2. Load WT/T7/lambda, then a file with T7/lambda/T7mut: T7 and lambda keep their colours,
    T7mut takes the first colour no name holds (WT still holds #0072B2); key == drawn fills."""
    a = _pairs(r_output["KEY_A"]); b = _pairs(r_output["KEY_B"])
    assert a["WT"] == "#0072B2" and a["T7"] == "#E69F00" and a["lambda"] == "#009E73"
    assert list(b) == ["T7", "lambda", "T7mut", "plate1", "plate2"]
    assert b["T7"] == a["T7"] and b["lambda"] == a["lambda"]
    assert b["T7mut"] == "#CC79A7"
    assert set(b.values()) == set(r_output["DRAWN_B"].split("|"))
    reg = _pairs(r_output["REGISTRY_B"])
    assert reg["WT"] == "#0072B2"          # a name that left the data keeps its colour
    assert r_output["STATUS2"].startswith("No paper style (looked for ")


def test_r_shiny_paper_style_times(r_output):
    """3. paper_style_times.json via CFU_PAPER_STYLE: the allowlisted settings reach the theme,
    the n row, the brackets and the key; the sample colours come from the file by name; the
    figure's own settings are untouched."""
    path = os.path.join(FIXTURES, "paper_style_times.json")
    assert r_output["STATUS3"].startswith("Paper style: " + path + ", saved 2026-11-09")
    applied = _pairs(r_output["APPLIED3"])
    assert applied == {"font_family": "Times New Roman", "font_family_custom": "",
                       "base_size": "13", "axis_color": "#333333", "axis_line_width": "0.8"}
    pal = _pairs(r_output["PALETTE3"])
    assert pal["WT"] == "#0072B2" and pal["Strain only in the paper style"] == "#CC79A7"
    assert r_output["FONT3"] == "Times New Roman" and r_output["FONT_STATUS3"] == ""
    assert r_output["THEME_FAMILY3"] == "Times New Roman"
    assert r_output["KEY_FAMILY3"] == "Times New Roman|Times New Roman|Times New Roman"
    assert r_output["NROW_FAMILY3"] == "Times New Roman"
    assert r_output["THEME_SIZE3"] == "13"
    assert r_output["AXIS_COL3"] == "#333333"
    assert r_output["AXIS_LW3"] == "0.8" and r_output["TICK_LW3"] == "0.8"
    # the violins are coloured by the paper palette even with plates and vfill = auto
    assert r_output["NEUTRAL3"] == "FALSE"
    assert r_output["FILL_WT3"] == "#0072B2"
    key = _pairs(r_output["KEY3"])
    assert key["WT"] == "#0072B2" and key["T7"] == "#E69F00" and key["lambda"] == "#009E73"
    assert set(key.values()) == set(r_output["DRAWN3"].split("|"))
    assert r_output["UNTOUCHED3"] == "Figure-specific title|10|TRUE|auto"
    assert "WT (" in r_output["TEXT3"]


def test_r_shiny_paper_style_missing_font(r_output):
    """4. paper_style_missing_font.json asks for Segoe UI (absent here): drawn with the default
    sans and the status line says the font was not found; the other settings still apply."""
    req, fam, avail = r_output["FONT4"].split("|")
    assert req == "Segoe UI" and fam == "sans" and avail == "FALSE"
    assert "Segoe UI" in r_output["FONT_STATUS4"] and "not found" in r_output["FONT_STATUS4"]
    assert r_output["THEME_FAMILY4"] in ("", "sans")
    assert r_output["THEME_SIZE4"] == "13"
    assert _pairs(r_output["APPLIED4"])["font_family_custom"] == "Segoe UI"
    assert r_output["STATUS4"].startswith("Paper style: ")


def test_r_shiny_no_paper_style(r_output):
    """5. No file where CFU_PAPER_STYLE points: the status says so, nothing is applied, the
    defaults are drawn."""
    assert r_output["STATUS5"].startswith("No paper style (looked for ")
    assert r_output["STATUS5"].endswith("no_paper_style.json).")
    assert r_output["APPLIED5"] == "0" and r_output["FONT_STATUS5"] == ""
    assert r_output["THEME5"] == "|14|#33413c|0.6"
    key = _pairs(r_output["KEY5"])
    assert key["WT"] == "#0072B2" and key["T7"] == "#E69F00" and key["lambda"] == "#009E73"
