"""CT-R3 statistics front-ends (Python side): the engine / command line plaque_stats/plaque_stats.py,
the Shiny-for-Python web app plaque_stats/app_py.py and the desktop Analyze tab app/study_tab.py.

Each test pins one finding of the round-3 "stats four ways" tester (F1, F2, F4, F8, F9, F10, F12,
the stats N3 / N11 leftovers, the gate sentence, the detect box and the default figure size). The
data files tests/fixtures/ct_r3_*.csv are the tester's own (j_dirty, u20_upper_missing,
f_one_plate, k_zeros). Expected numbers come from the command-line path of the same engine, from
scipy, or from the file itself, never from a previous run of the changed code.
"""
import importlib.util
import io
import json
import os
import re
import struct
import sys
import zipfile

import numpy as np
import pandas as pd
import pytest

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PS_DIR = os.path.join(ROOT, "plaque_stats")
if PS_DIR not in sys.path:
    sys.path.insert(0, PS_DIR)
FX = os.path.join(ROOT, "tests", "fixtures")

import plaque_stats as ps  # noqa: E402
import legend_key as lk  # noqa: E402

J_DIRTY = os.path.join(FX, "ct_r3_j_dirty.csv")
U20 = os.path.join(FX, "ct_r3_u20_upper_missing.csv")
F_ONE = os.path.join(FX, "ct_r3_f_one_plate.csv")
K_ZEROS = os.path.join(FX, "ct_r3_k_zeros.csv")


def _web():
    pytest.importorskip("shiny")
    name = "ct_web_stats_app"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, os.path.join(PS_DIR, "app_py.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _sel(A, df, **kw):
    d = A.picker_defaults(df)
    s = dict(group=d["group"], value=d["value"], replicate=d["replicate"], subgroup=A.NONE,
             control=None, order=A.group_levels(df, d["group"]), compare="all", unit="auto",
             parametric="auto", equal_var="auto", center="mean", error="auto", violin_fill="auto",
             brackets="auto", palette_name="", palette_custom="", show_points=True, show_n=True,
             show_value=True, frame=False, log_y=False, log_drop=False, title="", ylabel="",
             width=8, height=5.2, place_key=True)
    s.update(kw)
    return s


def _cli(tmp_path, path, **kw):
    a = dict(ps.DEFAULTS)
    a.update({"data": path, "out": str(tmp_path / "cli"), "formats": ["png"], "_stamp": "",
              "stats_table": False, "legend_key": False, "dpi": 40})
    a.update(kw)
    return ps.run(a)


def _report(res):
    md = [f for f in os.listdir(res["out"]) if f.startswith("report_")][0]
    with open(os.path.join(res["out"], md), encoding="utf-8") as fh:
        return fh.read()


# =========================================================================== 1. F1 (web)
def test_f1_mostly_numeric_rule():
    """CT-R3 F1: a column is offered when at least half of its non-empty cells are numbers."""
    df = pd.DataFrame({"g": ["a"] * 6, "half": ["1", "2", "3", "x", "y", "z"],
                       "less": ["1", "2", "x", "y", "z", ""], "clean": [1.0] * 6,
                       "text": list("abcdef")})
    assert ps.value_columns(df) == ["half", "clean"]
    assert ps.numeric_columns(df) == ["clean"]             # the CLI's automatic pick stays strict


def test_f1_dirty_diameter_column_is_offered_default_and_matches_the_cli(tmp_path):
    """CT-R3 F1: data/j_dirty.csv (5 % of the diameter cells blank / NA / '2.5mm'): the web app used
    to offer only area_mm2 and analyse it ('635 rows used'). The diameter column is now offered and
    is the default, the dropped cells are counted with the engine's note, and the means and p are
    the command line's."""
    A = _web()
    df, inf = A.read_upload(J_DIRTY)
    assert "diameter_mm" in A.value_choices(df, ("group", "replicate"))
    assert A.picker_defaults(df)["value"] == "diameter_mm"
    a = A.compute(df, _sel(A, df), inf)
    lines = A.summary_lines(a)
    assert "Note: 31 rows dropped: no numeric diameter_mm value (20 not a number, 11 empty)." in lines
    assert any("604 of 635 rows used" in ln for ln in lines), lines
    assert not any("635 rows used" in ln and "of 635" not in ln for ln in lines), lines
    cli = _cli(tmp_path, J_DIRTY, value="diameter_mm")
    assert a["omni"]["test"] == cli["omni"]["test"]
    assert a["omni"]["p"] == pytest.approx(cli["omni"]["p"], rel=1e-9)
    want = cli["summary"].set_index("group")["unit_mean"].to_dict()
    for g, m in a["unit_means"].items():
        assert m == pytest.approx(want[g], rel=1e-12)
    assert want["WT"] == pytest.approx(2.03, abs=0.005) and want["mutB"] == pytest.approx(1.89, abs=0.005)


def test_f1_upper_case_headers_with_dirty_cells_analyse_and_zip(tmp_path):
    """CT-R3 F1: u20_upper_missing.csv (GROUP / REPLICATE / DIAMETER_MM, NA and empty cells): the
    value is offered, analysed, and the ZIP holds the report and the figure (the download used to
    abort with Shiny's SilentException because nothing could be analysed)."""
    A = _web()
    df, inf = A.read_upload(U20)
    sel = _sel(A, df)
    assert sel["value"] == "DIAMETER_MM" and sel["group"] == "GROUP"
    a = A.compute(df, sel, inf)
    assert any("rows dropped: no numeric DIAMETER_MM value" in n for n in a["notes"])
    z = zipfile.ZipFile(io.BytesIO(A.zip_bytes(df, a, sel, "u20.csv", b"x")))
    names = z.namelist()
    assert "report_DIAMETER_MM.md" in names and "violin_DIAMETER_MM.png" in names
    assert "rows dropped: no numeric DIAMETER_MM value" in z.read("report_DIAMETER_MM.md").decode()


# =========================================================================== desktop fixtures
@pytest.fixture
def dialogs(monkeypatch):
    """Queue answers for the modal dialogs (as tests/test_ct_r2_analyze.py)."""
    pytest.importorskip("pytestqt")
    from PySide6.QtWidgets import QMessageBox, QFileDialog, QInputDialog
    q = {"save": [], "open": [], "openN": [], "question": [], "seen": []}

    def pop(key, default):
        return q[key].pop(0) if q[key] else default
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: pop("save", ("", ""))))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: pop("open", ("", ""))))
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", staticmethod(lambda *a, **k: pop("openN", ([], ""))))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(
        lambda *a, **k: q["seen"].append(("question", a[2] if len(a) > 2 else "")) or pop("question", QMessageBox.No)))
    for name in ("warning", "information", "critical"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(
            lambda *a, _n=name, **k: q["seen"].append((_n, a[2] if len(a) > 2 else "")) or QMessageBox.Ok))
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("", False)))
    return q


@pytest.fixture
def st(qtbot):
    pytest.importorskip("pytestqt")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    from app import ui as appui
    w = appui.MainWindow()
    qtbot.addWidget(w)
    return w.study_tab


def _fill(st, spec, n=25, seed=0, sd=0.08):
    """spec: [(sample, subgroup, [plate mean, ...]), ...] -> samples + plates (area = d^2)."""
    rng = np.random.default_rng(seed)
    for g, sub, mus in spec:
        st._samples.append({"group": g, "subgroup": sub})
        si = len(st._samples) - 1
        for mu in mus:
            d = np.clip(mu + rng.normal(0, sd, n), 0.05, None).round(3).tolist()
            st._add_plate(si, d, [round(x * x, 4) for x in d])
    st._refresh_tree()


def _zip(st, dialogs, tmp_path, name="z.zip"):
    p = str(tmp_path / name)
    dialogs["save"].append((p, "ZIP (*.zip)"))
    st.zip_btn.click()
    assert os.path.exists(p), st.err.text()
    return zipfile.ZipFile(p)


THREE = [("WT", "", [1.0, 1.1, 1.05]), ("mutA", "", [1.5, 1.6, 1.55]), ("mutB", "", [1.2, 1.25, 1.3])]
ONE_PLATE = [("WT", "", [1.0, 1.1, 1.05]), ("mutA", "", [1.5, 1.6, 1.55]), ("mutB", "", [1.2])]


# =========================================================================== 2. F2 sensitivity
def test_f2_engine_sensitivity_on_the_testable_samples_when_one_has_one_plate(tmp_path):
    """CT-R3 F2: f_one_plate.csv (mutB has one plate). The line is computed on WT and mutA and
    says so; the tester's numbers: ANOVA p = 0.00193, Welch p = 0.0177. It used to be absent."""
    from scipy import stats as sst
    res = _cli(tmp_path, F_ONE, value="diameter_mm")
    sens = res["omni"]["sensitivity"]
    rm = res["replicate_means"]
    wt, mu = (rm.loc[rm["group"] == g, "value"].values for g in ("WT", "mutA"))
    assert sens["p_equal"] == pytest.approx(sst.f_oneway(wt, mu).pvalue, rel=1e-9)
    assert sens["p_equal"] == pytest.approx(0.00193, abs=5e-6)
    assert sens["p_welch"] == pytest.approx(sst.ttest_ind(wt, mu, equal_var=False).pvalue, rel=1e-9)
    assert sens["p_welch"] == pytest.approx(0.0177, abs=5e-5)
    assert sens["text"].startswith("on the 2 samples that can be tested (WT, mutA; mutB cannot: "
                                   "fewer than 2 plates), omnibus p = 0.002 with equal variances")
    md = _report(res)
    assert "- **Sensitivity:** on the 2 samples that can be tested" in md
    # in the comparison section, not in the Figure section (which the desktop ZIP rewrites)
    assert md.index("- **Sensitivity:**") < md.index("## Figure")


def test_f2_web_screen_and_zip_show_sensitivity():
    A = _web()
    df, inf = A.read_upload(F_ONE)
    sel = _sel(A, df)
    a = A.compute(df, sel, inf)
    lines = A.detail_lines(a)
    sens = [x for x in lines if x.startswith("Sensitivity: on the 2 samples that can be tested")]
    assert sens, lines
    md = zipfile.ZipFile(io.BytesIO(A.zip_bytes(df, a, sel, "f.csv", b"x"))).read(
        "report_diameter_mm.md").decode()
    assert "- **Sensitivity:** " + sens[0][len("Sensitivity: "):] in md


def test_f2_desktop_report_and_zip_show_sensitivity(st, dialogs, tmp_path):
    _fill(st, THREE)
    st.analyse_btn.click()
    rep = st.report.toPlainText()
    line = next((ln for ln in rep.split("\n") if ln.startswith("Sensitivity: omnibus p")), None)
    assert line, rep
    md = _zip(st, dialogs, tmp_path).read("report_diameter_mm.md").decode()
    assert "- **Sensitivity:** " + line[len("Sensitivity: "):] in md


def test_f2_desktop_one_plate_sample_still_gets_the_line(st, dialogs):
    _fill(st, ONE_PLATE)
    st.analyse_btn.click()
    assert "Sensitivity: on the 2 samples that can be tested (WT, mutA; mutB cannot: fewer than 2 " \
           "plates)" in st.report.toPlainText()


# =========================================================================== 3. gate sentence + detect box
def test_web_screen_shows_the_test_choice_sentence():
    """CT-R3: the engine's test-choice / normality-gate sentence was only in the web ZIP."""
    A = _web()
    df, inf = A.read_upload(J_DIRTY)
    a = A.compute(df, _sel(A, df), inf)
    lines = A.detail_lines(a)
    assert lines[0].startswith("Test choice: one-way ANOVA, followed by Tukey HSD. Every sample has at "
                               "least 8 plates and Shapiro–Wilk (Bonferroni over 3 samples) does not "
                               "reject normality"), lines
    assert lines[0] == A.app_words(re.sub(r"\s+", " ", "Test choice: %s, followed by %s. %s %s" % (
        a["omni"]["test"], a["omni"]["posthoc"], a["omni"]["choice_note"],
        a["omni"]["variance_rule"])).strip())
    assert "Override with Test type" in lines[0] and "--" not in "\n".join(lines)


def test_desktop_difference_to_detect_feeds_the_engine(st, dialogs, tmp_path):
    """CT-R3: ONE optional field 'Difference to detect' (hidden in grouped mode) gives the same
    power sentence as the engine's --detect; a value <= 0 gives a plain message."""
    _fill(st, THREE)
    st.detect_in.setText("0.2")
    st.analyse_btn.click()
    pl = st._last[1]
    assert pl["omni"]["power"]["detect"] == 0.2
    want = ps.power_sentence(pl["omni"]["power"], pl["unit"]).replace("**", "")
    assert want.startswith("Power: to detect a difference of 0.2 (the difference you named)")
    assert want in st.report.toPlainText()
    md = _zip(st, dialogs, tmp_path).read("report_diameter_mm.md").decode()
    assert "to detect a difference of 0.2 (the difference you named)" in md
    st.detect_in.setText("-1")
    st.analyse_btn.click()
    assert "Difference to detect must be a number greater than 0" in st.err.text()
    assert "--" not in st.err.text()
    assert st.detect_in.text() == "0.2"                     # set back with the result it belongs to
    st.detect_in.setText("")
    st.analyse_btn.click()
    assert st._last[1]["omni"]["power"].get("detect") is None and st.err.text() == ""


def test_desktop_detect_field_hidden_in_grouped_mode(st, dialogs):
    _fill(st, THREE)
    assert not st.detect_in.isHidden()
    _fill(st, [("WT", "host2", [1.0, 1.1])])
    assert st.detect_in.isHidden() and st.detect_cap.isHidden()

