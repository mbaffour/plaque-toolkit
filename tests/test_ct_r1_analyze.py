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
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *a, **k: pop("item", ("", False))))
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
        "semicolon.csv": "INDEX_COL;DIAMETER_MM;AREA_MM2\n1;2,34;4,30\n2;1,90;2,84\n",
        "data.json": '{"DIAMETER_MM": [1, 2]}\n',
        "binary.csv": b"\x89PNG\r\n\x1a\n\x00\x00\x00",
        "negative.csv": "DIAMETER_MM\n1.2\n-0.5\n",
        "header_only.csv": "INDEX_COL,DIAMETER_MM\n",
    }
    paths = [_plate_csv(tmp_path, n, t) for n, t in files.items()]
    dialogs["openN"].append((paths, ""))
    dialogs["item"] += [("", False), ("", False)]           # area_only, microns: user cancels
    dialogs["question"].append(QMessageBox.No)              # header_only: not a 0-plaque plate
    st.add_csv_btn.click()
    plates = st._plates_of(st._samples[0])
    assert [p["diam"] for p in plates] == [[2.34, 1.90]]    # only the semicolon file
    assert plates[0]["area"] == [4.30, 2.84] and plates[0]["source"] == "semicolon.csv"
    err = st.err.text()
    for name in ("area_only.csv", "microns.csv", "data.json", "binary.csv", "negative.csv",
                 "header_only.csv"):
        assert name in err, (name, err)
    assert "JSON" in err and "binary" in err and "zero or negative" in err
    # the user CAN name the column, and confirm an empty plate
    dialogs["openN"].append(([paths[1], paths[-1]], ""))
    dialogs["item"].append(("Diameter (µm)", True))
    dialogs["question"].append(QMessageBox.Yes)
    st.add_csv_btn.click()
    plates = st._plates_of(st._samples[0])
    assert [p["diam"] for p in plates] == [[2.34, 1.90], [1500.0, 1700.0], []]


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
    st._refresh_tree()
    st.analyse_btn.click()
    assert st._chips["plates"].text() == "6"
    assert st._chips["effect"].text().startswith("Cohen's d = ")
    float(st._chips["effect"].text().split("= ")[1])
