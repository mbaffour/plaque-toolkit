"""Click-through round 1, desktop Analyze tab (app/study_tab.py): regression tests.

Every test drives the real widgets of a real MainWindow (offscreen): buttons are CLICKED, combo
boxes and check boxes are set the way a user sets them, and only the modal dialogs (file
pickers, message boxes, input dialogs) are replaced. Finding ids are the tester's (CT-R1 F1..F25).
"""
import io
import json
import os
import sys
import zipfile

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")
pytest.importorskip("scipy")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QMessageBox, QFileDialog, QInputDialog, QScrollArea  # noqa: E402

from app import ui as appui                # noqa: E402
from app import study_tab as ST            # noqa: E402


# --------------------------------------------------------------------------- fixtures
@pytest.fixture
def dialogs(monkeypatch):
    """Queue answers for the modal dialogs; record every message box."""
    q = {"save": [], "open": [], "openN": [], "question": [], "item": [], "text": [], "seen": []}

    def pop(key, default):
        return q[key].pop(0) if q[key] else default

    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: pop("save", ("", ""))))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: pop("open", ("", ""))))
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", staticmethod(lambda *a, **k: pop("openN", ([], ""))))

    def question(*a, **k):
        q["seen"].append(("question", a[2] if len(a) > 2 else ""))
        return pop("question", QMessageBox.No)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(question))
    for name in ("warning", "information", "critical"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(
            lambda *a, _n=name, **k: q["seen"].append((_n, a[2] if len(a) > 2 else "")) or QMessageBox.Ok))
    q["offered"] = []
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(
        lambda *a, **k: q["offered"].append(list(a[3])) or pop("item", ("", False))))
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: pop("text", ("", False))))
    return q


@pytest.fixture
def win(qtbot):
    w = appui.MainWindow()
    qtbot.addWidget(w)
    return w


@pytest.fixture
def st(win):
    return win.study_tab


def _fill(st, spec, n=25, seed=0):
    """spec: [(sample, subgroup, [plate mean, ...]), ...] -> samples + plates (area = d^2)."""
    rng = np.random.default_rng(seed)
    for g, sub, mus in spec:
        st._samples.append({"group": g, "subgroup": sub})
        si = len(st._samples) - 1
        for mu in mus:
            d = np.clip(mu + rng.normal(0, 0.08, n), 0.05, None).round(3).tolist()
            st._add_plate(si, d, [x * x for x in d])
    st._refresh_tree()


def _zip(st, dialogs, tmp_path, name="z.zip"):
    p = str(tmp_path / name)
    dialogs["save"].append((p, "ZIP (*.zip)"))
    st.zip_btn.click()
    assert os.path.exists(p), st.err.text()
    return zipfile.ZipFile(p)


def _csv(z, name):
    return pd.read_csv(io.BytesIO(z.read(name)), dtype=str, keep_default_na=False)


# --------------------------------------------------------------------------- F1 / F2 / F14
NAMES = ["phage #3", "NA", "None", "007", "1.0"]


def test_zip_single_factor_equals_screen_and_uses_the_in_memory_table(st, dialogs, tmp_path):
    """CT-R1 F1/F2: the ZIP's samples, order and statistics are the screen's; the engine gets
    the in-memory table (no temp CSV path in run_config) and records the Toolkit version."""
    _fill(st, [(n, "", [1.0 + 0.2 * i, 1.05 + 0.2 * i, 0.95 + 0.2 * i]) for i, n in enumerate(NAMES)])
    st.analyse_btn.click()
    assert st._last is not None, st.err.text()
    z = _zip(st, dialogs, tmp_path)
    assert _csv(z, "summary_by_group_diameter_mm.csv")["group"].tolist() == NAMES
    omni = pd.read_csv(io.BytesIO(z.read("omnibus_test_diameter_mm.csv")))
    assert omni["test"][0] == st._chips["test"].text()
    assert abs(float(omni["p"][0]) - float(st._last[1]["omni"]["p"])) < 1e-12
    cfg = json.loads(z.read("run_config_diameter_mm.json"))
    text = json.dumps(cfg)
    assert "plaque_zip_" not in text and "compiled.csv" not in text      # no temp paths
    assert cfg["groups"] == NAMES
    assert str(cfg["toolkit_version"]).startswith("Plaque Toolkit")
    # the key files travel with the figure
    assert "violin_diameter_mm_legend_key.png" in z.namelist()
    assert z.read("violin_diameter_mm_legend_text.txt").decode().strip() == st.key_text.text()


@pytest.mark.parametrize("tags,control", [(["IPTG", "None"], "None"), (["0", "0.10", "1.0"], "0")])
def test_zip_grouped_equals_screen(st, dialogs, tmp_path, tags, control):
    """CT-R1 F1/F2/F14: grouped tags stay as typed ('None', '0.10', '1.0'); a control that is not
    the first tag is drawn and coloured as on screen; the key title is '2nd factor'."""
    spec = []
    for g, base in (("T4", 1.0), ("T7", 2.0)):
        for i, t in enumerate(tags):
            spec.append((g, t, [base + 0.3 * i, base + 0.3 * i + 0.05, base + 0.3 * i - 0.05]))
    _fill(st, spec)
    st.control_sel.setCurrentText(control)
    st.analyse_btn.click()
    assert st._last is not None and st._last[0] == "grouped", st.err.text()
    z = _zip(st, dialogs, tmp_path)
    comp = _csv(z, "control_comparisons_diameter_mm.csv")
    assert set(comp["subgroup"]) == set(t for t in tags if t != control)
    assert set(comp["control"]) == {control}
    assert z.read("grouped_diameter_mm_legend_text.txt").decode().strip() == st.key_text.text()
    lk = ST._legend_key()
    assert lk.from_figure(st._last_fig)["title"] == "2nd factor"
    cfg = json.loads(z.read("run_config_diameter_mm.json"))
    assert cfg["subgroups"] == st._last[1]["sub_order"] and cfg["control"] == control
    assert "plaque_zip_" not in json.dumps(cfg) and "in-memory" in cfg["data"]
    assert st.err.text() == ""


def test_engine_exit_is_a_message_not_a_dead_app(st, dialogs, tmp_path, monkeypatch):
    """CT-R1 F1: a bare SystemExit from the engine (Analyze, ZIP) is shown in the tab."""
    ps = ST._engine()
    _fill(st, [("WT", "", [1.0, 1.1, 0.9]), ("mut", "", [1.5, 1.6, 1.4])])
    st.analyse_btn.click()
    assert st.zip_btn.isEnabled()
    real_run = ps.run
    monkeypatch.setattr(ps, "run", lambda args: (_ for _ in ()).throw(SystemExit("[error] engine said no")))
    dialogs["save"].append((str(tmp_path / "x.zip"), ""))
    st.zip_btn.click()
    assert "engine said no" in st.err.text() and not os.path.exists(tmp_path / "x.zip")
    monkeypatch.setattr(ps, "run", real_run)
    monkeypatch.setattr(ps, "run_stats", lambda *a, **k: (_ for _ in ()).throw(SystemExit("[error] stats said no")))
    st.analyse_btn.click()
    assert "stats said no" in st.err.text()
    # CT-R1 F19: the failed compute removed the old results and disabled every export
    assert st._last is None and st._last_fig is None and not st.zip_btn.isEnabled()
    assert st._chips["test"].text() == "—"


# --------------------------------------------------------------------------- F3
def test_legend_key_button_works_when_clicked(st, dialogs, tmp_path):
    """CT-R1 F3: clicked(bool) used to arrive as the key's path (False) -> TypeError."""
    _fill(st, [("WT", "", [1.0, 1.1, 0.9]), ("mut", "", [1.5, 1.6, 1.4])])
    st.analyse_btn.click()
    p = str(tmp_path / "key.svg")
    dialogs["save"].append((p, "SVG — vector, editable (*.svg)"))
    st.key_btn.click()
    assert os.path.exists(p) and st.err.text() == ""
    assert "plate1" in open(p, encoding="utf-8").read()


# --------------------------------------------------------------------------- F5 / F25 study file
def _snapshot(st):
    return ([(s["group"], s["subgroup"]) for s in st._samples],
            [(p["group"], p["subgroup"], p["replicate"], [round(x, 6) for x in p["diam"]],
              [round(x, 6) for x in p["area"]]) for p in st._plates_in_order()])


def test_save_and_load_study_reproduce_it_exactly(st, dialogs, tmp_path):
    """CT-R1 F5: labels stay text, sample order survives (even when the plates were added to the
    2nd sample first), empty plates and empty samples are kept."""
    for g in ("None", "007", "1.0", "empty"):
        st._samples.append({"group": g, "subgroup": ""})
    st._add_plate(1, [1.5, 1.6, 1.7], [2.2, 2.5, 2.9])     # 2nd sample's plate added FIRST
    st._add_plate(0, [1.0, 1.1], [1.0, 1.2])
    st._add_plate(0, [], [])                               # a zero-plaque plate
    st._add_plate(1, [1.4, 1.45], [2.0, 2.1])
    st._add_plate(2, [0.9, 0.95], [0.8, 0.9])
    st._refresh_tree()
    before = _snapshot(st)
    p = str(tmp_path / "study.csv")
    dialogs["save"].append((p, "CSV (*.csv)"))
    st.save_study_btn.click()
    assert os.path.exists(p) and not st._dirty
    dialogs["question"].append(QMessageBox.Yes)
    st.clear_btn.click()
    assert st._samples == []
    dialogs["open"].append((p, ""))
    st.load_study_btn.click()
    assert _snapshot(st) == before
    assert [s["group"] for s in st._samples] == ["None", "007", "1.0", "empty"]
    assert not st._dirty


def test_load_study_asks_before_replacing_an_unsaved_study(st, dialogs, tmp_path):
    _fill(st, [("WT", "", [1.0, 1.1])])
    assert st._dirty
    other = tmp_path / "other.csv"
    other.write_text("group,replicate,diameter_mm\nX,plate1,1.0\n", encoding="utf-8")
    dialogs["open"].append((str(other), ""))
    dialogs["question"].append(QMessageBox.No)              # keep the current study
    st.load_study_btn.click()
    assert [s["group"] for s in st._samples] == ["WT"]
    assert any(k == "question" for k, _ in dialogs["seen"])
    dialogs["question"].append(QMessageBox.Yes)
    st.load_study_btn.click()
    assert [s["group"] for s in st._samples] == ["X"]


def test_the_tabs_own_long_export_loads(st, dialogs, tmp_path):
    """CT-R1 F25: Load study used to reject the tab's own 'Long' export."""
    _fill(st, [("NA", "", [1.0, 1.1]), ("T7 #2", "", [1.5, 1.6])])
    before = _snapshot(st)
    p = str(tmp_path / "long.csv")
    dialogs["save"].append((p, ""))
    long_action = [a for a in st.savedata_btn.menu().actions() if a.text().startswith("Long")][0]
    long_action.trigger()
    assert os.path.exists(p)
    dialogs["question"].append(QMessageBox.Yes)
    dialogs["open"].append((p, ""))
    st.load_study_btn.click()
    assert _snapshot(st) == before


# --------------------------------------------------------------------------- F6 CSV import
def _plate_csv(tmp_path, name, text):
    p = tmp_path / name
    if isinstance(text, bytes):
        p.write_bytes(text)
    else:
        p.write_text(text, encoding="utf-8")
    return str(p)


def test_add_csv_needs_a_diameter_in_mm_column_and_sane_values(st, dialogs, tmp_path):
    """CT-R1 F6: area-only / micrometre / count files are not read as mm diameters without the
    user naming the column; ';' + decimal commas are read; JSON, binary and values <= 0 are
    refused; a file with no plaques becomes a zero-plaque plate only after a Yes."""
    _fill(st, [("WT", "", [])])
    st._select_sample(0)
    files = {
        "area_only.csv": "INDEX_COL,AREA_MM2\n1,2.5\n2,3.1\n",
        "microns.csv": "id,Diameter (µm)\n1,1500\n2,1700\n",
        "plain.csv": "id,size\n1,1.3\n2,1.5\n",
        "semicolon.csv": "INDEX_COL;DIAMETER_MM;AREA_MM2\n1;2,34;4,30\n2;1,90;2,84\n",
        "data.json": '{"DIAMETER_MM": [1, 2]}\n',
        "binary.csv": b"\x89PNG\r\n\x1a\n\x00\x00\x00",
        "negative.csv": "DIAMETER_MM\n1.2\n-0.5\n",
        "header_only.csv": "INDEX_COL,DIAMETER_MM\n",
    }
    paths = [_plate_csv(tmp_path, n, t) for n, t in files.items()]
    dialogs["openN"].append((paths, ""))
    dialogs["item"] += [("", False), ("", False), ("", False)]   # area_only, microns, plain: cancel
    dialogs["question"].append(QMessageBox.No)              # header_only: not a 0-plaque plate
    st.add_csv_btn.click()
    plates = st._plates_of(st._samples[0])
    assert [p["diam"] for p in plates] == [[2.34, 1.90]]    # only the semicolon file
    assert plates[0]["area"] == [4.30, 2.84] and plates[0]["source"] == "semicolon.csv"
    err = st.err.text()
    assert all("Diameter (µm)" not in o for o in dialogs["offered"])   # never offered as mm
    for name in ("area_only.csv", "microns.csv", "plain.csv", "data.json", "binary.csv", "negative.csv",
                 "header_only.csv"):
        assert name in err, (name, err)
    assert "JSON" in err and "binary" in err and "zero or negative" in err
    # the user CAN name the column, and confirm an empty plate
    dialogs["openN"].append(([paths[2], paths[-1]], ""))
    dialogs["item"].append(("size", True))
    dialogs["question"].append(QMessageBox.Yes)
    st.add_csv_btn.click()
    plates = st._plates_of(st._samples[0])
    assert [p["diam"] for p in plates] == [[2.34, 1.90], [1.3, 1.5], []]
    assert st.err.text() == ""


# --------------------------------------------------------------------------- F17 plate ids
def test_plate_ids_default_to_plate_n_and_can_be_renamed(st, dialogs, tmp_path):
    """CT-R1 F17: plate ids are plate1..n per sample (file name kept as the source, shown as the
    tooltip and in the export); a plate can be renamed; 'data-green-' is not a sample name."""
    _fill(st, [("WT", "", [])])
    st._select_sample(0)
    paths = [_plate_csv(tmp_path, "data-green-Plate_%d.csv" % n,
                        "INDEX_COL,DIAMETER_MM\n1,%.1f\n2,%.1f\n" % (n / 10, n / 10 + 0.1)) for n in (14, 10, 12)]
    dialogs["openN"].append((paths, ""))
    st.add_csv_btn.click()
    plates = st._plates_of(st._samples[0])
    assert [p["replicate"] for p in plates] == ["plate1", "plate2", "plate3"]
    assert [p["source"] for p in plates] == [os.path.basename(x) for x in paths]
    child = st.tree.topLevelItem(0).child(1)
    assert "data-green-Plate_10.csv" in child.toolTip(0)
    st.tree.setCurrentItem(child)
    dialogs["text"].append(("dish B", True))
    st.edit_btn.click()
    assert [p["replicate"] for p in st._plates_of(st._samples[0])] == ["plate1", "dish B", "plate3"]
    p = str(tmp_path / "wide.csv")
    dialogs["save"].append((p, ""))
    [a for a in st.savedata_btn.menu().actions() if a.text().startswith("Wide")][0].trigger()
    wide = pd.read_csv(p, dtype=str, keep_default_na=False)
    assert set(wide["source"]) == {os.path.basename(x) for x in paths}
    assert ST._sample_guess("data-green-WT_plate2") == "WT"
    assert ST._sample_guess("data-green-Plate_10") != "data-green"


def test_import_and_assign_numbers_plates_per_sample(st, dialogs, tmp_path, monkeypatch):
    paths = [_plate_csv(tmp_path, "data-green-%s_%d.csv" % (g, i), "DIAMETER_MM\n1.%d\n1.%d\n" % (i, i + 1))
             for g in ("WT", "mut") for i in (1, 2)]
    monkeypatch.setattr(ST._AssignDialog, "exec", lambda self: ST.QDialog.Accepted)
    dialogs["openN"].append((paths, ""))
    st.assign_btn.click()
    assert [(p["group"], p["replicate"]) for p in st._plates_in_order()] == [
        ("WT", "plate1"), ("WT", "plate2"), ("mut", "plate1"), ("mut", "plate2")]


# --------------------------------------------------------------------------- F25 smaller gaps
def test_add_current_plate_twice_asks(win, st, dialogs):
    mt = win.measure_tab
    mt.model.set_dataframe(pd.DataFrame({"INDEX_COL": [1, 2, 3], "DIAMETER_MM": [1.2, 1.4, 1.3],
                                         "AREA_MM2": [1.1, 1.5, 1.3]}))
    _fill(st, [("WT", "", [])])
    st._select_sample(0)
    st.add_cur_btn.click()
    st._select_sample(0)
    dialogs["question"].append(QMessageBox.No)
    st.add_cur_btn.click()
    assert len(st._plates) == 1 and any(k == "question" for k, _ in dialogs["seen"])
    st._select_sample(0)
    dialogs["question"].append(QMessageBox.Yes)            # the user says it IS another plate
    st.add_cur_btn.click()
    assert len(st._plates) == 2


def test_samples_can_be_reordered_and_the_figure_follows(st, dialogs):
    _fill(st, [("A", "", [1.0, 1.1, 1.05]), ("B", "", [1.5, 1.6, 1.55]), ("C", "", [2.0, 2.1, 2.05])])
    st._select_sample(2)
    st.up_btn.click()
    assert [s["group"] for s in st._samples] == ["A", "C", "B"]
    st._select_sample(0)
    st.down_btn.click()
    assert [s["group"] for s in st._samples] == ["C", "A", "B"]
    st.analyse_btn.click()
    ax = st._last_fig.axes[0]
    assert [t.get_text() for t in ax.get_xticklabels()] == ["C", "A", "B"]


def test_closing_with_an_unsaved_study_asks(win, st, dialogs, qtbot):
    win.show()
    qtbot.waitExposed(win)
    _fill(st, [("WT", "", [1.0, 1.1])])
    dialogs["question"].append(QMessageBox.No)
    win.close()
    assert win.isVisible()
    dialogs["question"].append(QMessageBox.Yes)
    win.close()
    assert not win.isVisible()


def test_plates_chip_counts_plates_with_plaques_and_effect_chip_reads(st, dialogs):
    _fill(st, [("WT", "", [1.0, 1.1, 1.05]), ("mut", "", [1.5, 1.6, 1.55])])
    st._add_plate(0, [], [])                               # an empty plate
    st._samples.append({"group": "resistant", "subgroup": ""})
    st._add_plate(2, [], [])                               # a sample whose only plate is empty
    st._refresh_tree()
    st.analyse_btn.click()
    assert st._chips["plates"].text() == "6"
    assert "resistant has no diameter values" in st.warn_lbl.text()
    assert st._chips["effect"].text().startswith("Cohen's d = ")
    float(st._chips["effect"].text().split("= ")[1])


# --------------------------------------------------------------------------- F9 / F12 / new options
def _table(view):
    return view.model().dataframe().copy()


def test_one_plate_sample_keeps_the_plate_unit_and_says_so_on_screen(st, dialogs):
    """CT-R1 F9: one sample with a single plate no longer switches everything to per-plaque
    statistics; the warning is visible beside the result and its comparisons read n/a."""
    _fill(st, [("WT", "", [1.0, 1.1, 1.05]), ("mutA", "", [1.5, 1.6, 1.55]), ("mutB", "", [2.0])])
    st.analyse_btn.click()
    assert st._chips["unit"].text() == "plate"
    assert "mutB has 1 plate" in st.warn_lbl.text() and st.warn_lbl.isVisibleTo(st)
    cmp_ = _table(st.tbl_cmp)
    nb = cmp_[(cmp_["sample A"] == "mutB") | (cmp_["sample B"] == "mutB")]
    assert len(nb) == 2 and set(nb["p (adjusted)"]) == {"n/a"} and set(nb["signif"]) == {"n/a"}
    ok = cmp_[(cmp_["sample A"] != "mutB") & (cmp_["sample B"] != "mutB")]
    assert ok["p (adjusted)"].iloc[0] != "n/a"
    assert "mutB has 1 plate" in st.report.toPlainText()


def test_summary_has_plate_level_rows_and_the_figure_sentence_is_shown(st, dialogs):
    """CT-R1 F12: plate mean / SD / SEM beside the per-plaque numbers; the figure sentence under
    the figure and in the Report; p-values via the engine's fmt_p."""
    ps = ST._engine()
    _fill(st, [("WT", "", [1.0, 1.1, 1.05]), ("mut", "", [1.5, 1.6, 1.55]), ("T7", "", [1.2, 1.3, 1.25])])
    st.analyse_btn.click()
    summ = _table(st.tbl_group)
    for c in ("N plates", "plate mean", "plate SD", "plate SEM", "n plaques", "plaque mean"):
        assert c in summ.columns, c
    raw = st._last[1]["summary"]
    assert np.allclose(summ["plate mean"].astype(float), raw["unit_mean"].round(4))
    assert np.allclose(summ["plate SEM"].astype(float), raw["unit_sem"].round(4))
    cap = st.fig_caption.text()
    assert cap.startswith("Violins: all plaques.") and "Bar: mean of the 3 plate means" in cap
    assert "Whisker: SEM of the plate means" in cap
    assert "Figure: " + cap in st.report.toPlainText()
    assert st._chips["p"].text() == ps.fmt_p(st._last[1]["omni"]["p"])
    assert "Power:" in st.report.toPlainText()


def test_variances_and_compare_to_options_reach_the_engine_and_the_zip(st, dialogs, tmp_path):
    """New options: Variances (auto / equal / unequal) and Compare (all pairs / vs a sample =
    Dunnett); the ZIP uses the same choices."""
    _fill(st, [("WT", "", [1.0, 1.1, 1.05]), ("mut", "", [1.5, 1.9, 1.2]), ("T7", "", [1.2, 1.3, 1.25])])
    st.analyse_btn.click()
    assert st._chips["test"].text() == "one-way ANOVA"
    st.var_sel.setCurrentIndex(st.var_sel.findData("no"))
    assert st._chips["test"].text() == "Welch ANOVA"
    assert "Games-Howell" in st.cmp_cap.text()
    st.var_sel.setCurrentIndex(st.var_sel.findData("auto"))
    st.cmp_to_sel.setCurrentIndex(st.cmp_to_sel.findData("mut"))
    assert "Dunnett" in st.cmp_cap.text() and "vs mut" in st.cmp_cap.text()
    cmp_ = _table(st.tbl_cmp)
    assert len(cmp_) == 2 and all("mut" in (a, b) for a, b in zip(cmp_["sample A"], cmp_["sample B"]))
    z = _zip(st, dialogs, tmp_path)
    omni = pd.read_csv(io.BytesIO(z.read("omnibus_test_diameter_mm.csv")))
    assert omni["posthoc"][0] == "Dunnett"
    pw = _csv(z, "pairwise_tests_diameter_mm.csv")
    assert len(pw) == 2
    # an engine refusal (Dunnett is parametric) is shown, not a traceback
    st.param_sel.setCurrentIndex(st.param_sel.findData("nonparametric"))
    assert "Dunnett" in st.err.text() and st._last is None
    assert "Test: Non-parametric" in st.err.text() and "--parametric" not in st.err.text()


def test_grouped_mode_hides_the_one_factor_options(st, dialogs):
    _fill(st, [("T4", "LB", [1.0, 1.1]), ("T4", "IPTG", [1.5, 1.6])])
    assert st.var_sel.isHidden() and st.cmp_to_sel.isHidden() and not st.control_sel.isHidden()
    assert not st.fill_sel.isEnabled()                      # F13: grouped violins are always grey


# --------------------------------------------------------------------------- F10/F13/F15/F16/F21
def _fig_texts(fig):
    from matplotlib.text import Text
    return [t.get_text() for t in fig.findobj(Text) if t.get_visible() and t.get_text()]


def test_median_offers_only_iqr_ci_or_none(st, dialogs):
    """CT-R1 F16: SD / SEM describe a mean; around a median they are greyed out."""
    _fill(st, [("WT", "", [1.0, 1.1, 1.05]), ("mut", "", [1.5, 1.6, 1.55])])
    st.analyse_btn.click()
    st.error_sel.setCurrentIndex(st.error_sel.findData("sem"))
    st.center_sel.setCurrentIndex(st.center_sel.findData("median"))
    m = st.error_sel.model()
    enabled = {st.error_sel.itemData(i): m.item(i).isEnabled() for i in range(st.error_sel.count())}
    assert enabled == {"auto": True, "sem": False, "ci95": True, "sd": False, "iqr": True, "none": True}
    assert st.error_sel.currentData() == "iqr" and st.err.text() == "" and st._last_fig is not None
    st.error_sel.setCurrentIndex(st.error_sel.findData("ci95"))
    assert "bootstrap interval of the median (approximate" in st.fig_caption.text()   # CT-R2 N3: 3 plates
    st.center_sel.setCurrentIndex(st.center_sel.findData("mean"))
    assert all(m.item(i).isEnabled() for i in range(st.error_sel.count()))


def test_log_y_with_values_at_or_below_zero(st, dialogs):
    """CT-R1 F15: the engine's message is shown (no stale figure) and 'hide ≤ 0' draws the rest."""
    _fill(st, [("WT", "", [1.0, 1.1, 1.05]), ("mut", "", [1.5, 1.6, 1.55])])
    st._add_plate(0, [0.0, 1.0, 1.1], [0.0, 1.0, 1.2])
    st._refresh_tree()
    st.analyse_btn.click()
    assert not st.logy_drop_cb.isEnabled()
    st.logy_cb.setChecked(True)
    assert "zero or negative" in st.err.text()
    assert "tick 'hide ≤ 0'" in st.err.text() and "--" not in st.err.text()   # the tab's words
    assert st._last_fig is None and not st.savefig_btn.isEnabled() and not st.key_btn.isEnabled()
    assert st.logy_drop_cb.isEnabled()
    st.logy_drop_cb.setChecked(True)
    assert st.err.text() == "" and st._last_fig is not None and st.savefig_btn.isEnabled()
    assert st._last_fig.axes[0].get_yscale() == "log"
    assert any("not shown on the log axis" in t for t in _fig_texts(st._last_fig))


def test_brackets_offer_letters(st, dialogs):
    """CT-R1 F10: a compact letter display instead of a bracket stack."""
    _fill(st, [("A", "", [1.0, 1.02, 0.98]), ("B", "", [1.5, 1.52, 1.48]), ("C", "", [2.0, 2.02, 1.98])])
    st.analyse_btn.click()
    st.annot_sel.setCurrentIndex(st.annot_sel.findData("letters"))
    texts = _fig_texts(st._last_fig)
    assert {"a", "b", "c"} <= set(texts)
    assert "compact letter display" in st.fig_caption.text()


def test_palette_drives_the_plate_colours_and_dead_controls_are_greyed(st, dialogs):
    """CT-R1 F13: with grey violins (the default) the palette colours the plates; 'Opacity'
    (was 'Transparency'); Jitter is greyed without raw plaques."""
    from PySide6.QtWidgets import QLabel
    lk = ST._legend_key()
    _fill(st, [("WT", "", [1.0, 1.1, 1.05]), ("mut", "", [1.5, 1.6, 1.55])])
    st.analyse_btn.click()
    c0 = [e["colour"] for e in lk.from_figure(st._last_fig)["entries"]]
    st.palette_sel.setCurrentIndex(st.palette_sel.findData("tab10"))
    c1 = [e["colour"] for e in lk.from_figure(st._last_fig)["entries"]]
    assert c0 != c1 and c1[0] == "#1F77B4"
    labels = [w.text() for w in st.findChildren(QLabel)]
    assert "Opacity" in labels and "Transparency" not in labels
    st.show_points.setChecked(False)
    assert not st.jitter.isEnabled()
    st.palette_custom.setText("#0072B2, notacolour")
    st.palette_custom.editingFinished.emit()               # what Return / focus-out sends
    assert "notacolour" in st.err.text() and "not a colour" in st.err.text()
    assert st._last_fig is None and not st.savefig_btn.isEnabled()
    st.palette_custom.setText("#000000")                    # one colour for 2 coloured violins
    st.fill_sel.setCurrentIndex(st.fill_sel.findData("group"))
    st.palette_custom.editingFinished.emit()
    assert "custom palette has 1 colour but this figure needs 2" in st.err.text()
    st.palette_custom.setText("")                           # CT-R1 F19: fixing it clears the error
    st.palette_custom.editingFinished.emit()
    assert st.err.text() == "" and st._last_fig is not None


def test_typed_y_label_belongs_to_its_metric(st, dialogs):
    """CT-R1 F21: a Y label typed for the diameter does not label the area figure."""
    _fill(st, [("WT", "", [1.0, 1.1, 1.05]), ("mut", "", [1.5, 1.6, 1.55])])
    st.analyse_btn.click()
    st.ylabel_in.setText("Plaque Ø (mm)")
    st.ylabel_in.editingFinished.emit()
    assert st._last_fig.axes[0].get_ylabel() == "Plaque Ø (mm)"
    st.metric_sel.setCurrentIndex(1)
    assert st.ylabel_in.text() == "" and st._last_fig.axes[0].get_ylabel() == "Area (mm²)"
    st.metric_sel.setCurrentIndex(0)
    assert st._last_fig.axes[0].get_ylabel() == "Plaque Ø (mm)"


# --------------------------------------------------------------------------- F19 / F20 / F24
def test_clear_removes_results_and_an_error_is_cleared_by_the_next_action(st, dialogs):
    _fill(st, [("WT", "", [1.0, 1.1, 1.05])])
    st.analyse_btn.click()                                  # 3 plates but one sample: fine
    st._samples = []; st._plates = []; st._refresh_tree()
    st.analyse_btn.click()
    assert "at least two plates" in st.err.text()
    _fill(st, [("WT", "", [1.0, 1.1, 1.05]), ("mut", "", [1.5, 1.6, 1.55])])
    st.analyse_btn.click()
    assert st.err.text() == "" and st.zip_btn.isEnabled()
    dialogs["question"].append(QMessageBox.Yes)
    st.clear_btn.click()
    assert st._last is None and st._last_fig is None and not st.zip_btn.isEnabled()
    assert st.report.toPlainText() == "" and st.key_text.text() == "" and st.fig_caption.text() == ""


def test_save_figure_names_size_and_dpi(st, dialogs, tmp_path):
    """CT-R1 F20: dotted names keep their dots, a typed extension wins over the filter, the file
    has the chosen size, and TIFF uses the Export DPI like every other export (and the ZIP)."""
    from PIL import Image
    _fill(st, [("WT", "", [1.0, 1.1, 1.05]), ("mut", "", [1.5, 1.6, 1.55])])
    st.analyse_btn.click()
    st.dpi_in.setValue(100)
    dialogs["save"].append((str(tmp_path / "fig_0.5MOI"), "PNG image (*.png)"))
    st.savefig_btn.click()
    p = tmp_path / "fig_0.5MOI.png"
    assert p.exists()
    assert Image.open(p).size == (840, 540)                 # 8.4 x 5.4 in at 100 dpi, no crop
    dialogs["save"].append((str(tmp_path / "typed.pdf"), "PNG image (*.png)"))
    st.savefig_btn.click()
    assert (tmp_path / "typed.pdf").exists() and not (tmp_path / "typed.png").exists()
    dialogs["save"].append((str(tmp_path / "fig.tiff"), "TIFF — journal raster (*.tiff)"))
    st.savefig_btn.click()
    assert Image.open(tmp_path / "fig.tiff").size == (840, 540)
    z = _zip(st, dialogs, tmp_path)
    assert Image.open(io.BytesIO(z.read("violin_diameter_mm.png"))).size == (840, 540)
    assert Image.open(io.BytesIO(z.read("violin_diameter_mm.tiff"))).size == (840, 540)


def test_figure_is_not_squeezed_into_a_second_scroll_area(win, st, dialogs, qtbot):
    """CT-R1 F24: one scroll bar (the tab's); the figure area is as tall as the canvas."""
    win.resize(1320, 880); win.show(); qtbot.waitExposed(win)
    win.tabs.setCurrentIndex(3)
    _fill(st, [("WT", "", [1.0, 1.1, 1.05]), ("mut", "", [1.5, 1.6, 1.55])])
    st.analyse_btn.click()
    qtbot.wait(50)
    assert st.findChildren(QScrollArea) == []
    assert st.fig_holder.minimumHeight() >= st.canvas.height()
    assert st.fig_holder.height() >= st.canvas.height()


def test_screen_text_names_the_tabs_controls_not_command_line_flags(st, dialogs):
    """Engine notes ('--equal-var', '--annotate letters', '--parametric') are worded with the
    tab's own controls in the warning line, the caption and the Report."""
    _fill(st, [("S%d" % i, "", [1.0 + 0.1 * i, 1.05 + 0.1 * i, 0.95 + 0.1 * i]) for i in range(7)])
    st.analyse_btn.click()
    assert st.err.text() == ""
    for text in (st.report.toPlainText(), st.fig_caption.text(), st.warn_lbl.text()):
        assert "--" not in text and "`" not in text, text
    assert "Brackets: Letters" in st.fig_caption.text()


def test_rows_without_a_value_are_counted_in_the_report(st, dialogs):
    """Dropped rows appear in the Report: a plate measured without areas, analysed by area."""
    _fill(st, [("WT", "", [1.0, 1.1, 1.05]), ("mut", "", [1.5, 1.6, 1.55])])
    st._plates[0]["area"] = st._plates[0]["area"][:5]       # 20 of its 25 plaques have no area
    st.metric_sel.setCurrentIndex(1)
    st.analyse_btn.click()
    assert "Data: 20 plaque row(s) have no area value and are left out (plates: WT/plate1)." in \
        st.report.toPlainText()
