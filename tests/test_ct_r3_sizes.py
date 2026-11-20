"""Click-through round 3, group "sizes": regression tests for the round-3 sizes-flow report
(F1-F8) and the Validate status from the agreement tester.

Every test drives the real tab / editor offscreen (pytest-qt) or the shared engine functions
directly, with modal dialogs monkeypatched, and asserts values. The no-dish plate is the
tester's img/warn/sample_crop3.png: the bundled sample.tif with 3 % cut from each side, built
here exactly as the tester built it (identical pixels).
"""
import json
import os
import shutil
import sys

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import cv2                                          # noqa: E402
from PySide6.QtCore import QPointF                   # noqa: E402
from PySide6.QtWidgets import QMessageBox, QInputDialog, QFileDialog   # noqa: E402

import plaque_gui as pgui                            # noqa: E402
import plaque_qc                                     # noqa: E402
from app import ui as appui                          # noqa: E402
from app import engine_api                           # noqa: E402
from app import batch_measure                        # noqa: E402
from app import study_tab as ST                      # noqa: E402

TIMEOUT = 240_000
SAMPLE_TIF = os.path.join(ROOT, "app", "resources", "sample.tif")


# --------------------------------------------------------------------------- helpers
@pytest.fixture(autouse=True)
def _legend_key_as_package():
    """``from plaque_stats import legend_key`` must resolve to the package (see
    tests/test_ct_r1_measure.py for why)."""
    saved_path = list(sys.path)
    saved_mods = {k: v for k, v in sys.modules.items()
                  if k == "plaque_stats" or k.startswith("plaque_stats.") or k == "legend_key"}
    for k in saved_mods:
        del sys.modules[k]
    sys.path[:] = [p for p in sys.path if os.path.abspath(p) not in (
        os.path.join(ROOT, "plaque_stats"), os.path.join(ROOT, "plaque_stats", "agreement"))]
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    try:
        yield
    finally:
        for k in [k for k in sys.modules if k == "plaque_stats" or k.startswith("plaque_stats.")
                  or k == "legend_key"]:
            del sys.modules[k]
        sys.modules.update(saved_mods)
        sys.path[:] = saved_path


def _mode_index(key):
    return [k for _l, k, _h in appui.MODES].index(key)


class Dialogs:
    def __init__(self):
        self.seen = []
        self.question = QMessageBox.Discard
        self.questions = []
        self.open_path = ""
        self.open_paths = []
        self.double = (85.0, True)
        self.directory = ""


@pytest.fixture
def dialogs(monkeypatch):
    d = Dialogs()
    for name in ("warning", "information", "critical"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(
            lambda *a, _n=name, **k: d.seen.append((_n, a[1] if len(a) > 1 else "",
                                                    a[2] if len(a) > 2 else "")) or QMessageBox.Ok))

    def question(*a, **k):
        d.seen.append(("question", a[1] if len(a) > 1 else "", a[2] if len(a) > 2 else ""))
        return d.questions.pop(0) if d.questions else d.question
    monkeypatch.setattr(QMessageBox, "question", staticmethod(question))
    monkeypatch.setattr(QInputDialog, "getDouble", staticmethod(
        lambda *a, **k: d.seen.append(("getDouble", "", "")) or d.double))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(
        lambda *a, **k: (d.open_path, "")))
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", staticmethod(
        lambda *a, **k: (d.open_paths, "")))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(
        lambda *a, **k: d.directory))
    return d


@pytest.fixture
def window(qtbot, dialogs):
    win = appui.MainWindow()
    qtbot.addWidget(win)
    win.show()
    win.resize(1320, 880)
    qtbot.wait(50)
    return win


def _open(tab, qtbot, dialogs, path, mode="current", dish=100.0, scale="auto"):
    tab.mode.setCurrentIndex(_mode_index(mode))
    if scale:
        tab.scale_box.set_scale(scale)
    tab.plate.setValue(dish)
    dialogs.open_path = str(path)
    tab.det = None
    tab.open_btn.click()
    qtbot.waitUntil(lambda: tab.det is not None and not tab.busy, timeout=TIMEOUT)
    qtbot.wait(30)
    return tab.editor


def _tab(win, prefix):
    for i in range(win.tabs.count()):
        if win.tabs.tabText(i).strip().startswith(prefix):
            w = win.tabs.widget(i)
            return w.widget() if hasattr(w, "widget") and callable(w.widget) else w
    raise KeyError(prefix)


def make_crop3(folder):
    """The tester's sample_crop3.png: sample.tif with int(3 %) cut from every side (the dish
    rim is lost, so there is no mm scale)."""
    os.makedirs(str(folder), exist_ok=True)
    a = cv2.imread(SAMPLE_TIF, cv2.IMREAD_UNCHANGED)
    H, W = a.shape[:2]
    dy, dx = int(0.03 * H), int(0.03 * W)
    p = os.path.join(str(folder), "sample_crop3.png")
    cv2.imwrite(p, a[dy:H - dy, dx:W - dx])
    return p


def _read(path):
    return pd.read_csv(path, keep_default_na=False, dtype=str)


@pytest.fixture
def crop3_editor(window, qtbot, dialogs, tmp_path):
    img = make_crop3(tmp_path / "m")
    ed = _open(window.measure_tab, qtbot, dialogs, img)
    assert ed.ppm is None and ed.plate is None          # the premise: no dish, no mm scale
    return window.measure_tab, ed


# =========================================================================== F1
def test_f1_add_current_plate_refuses_a_plate_without_a_mm_scale(window, crop3_editor, dialogs):
    tab, ed = crop3_editor
    st = window.study_tab
    st._samples.append({"group": "S", "subgroup": ""})
    st._refresh_tree(); st._select_sample(0)
    for _ in range(2):                                   # nothing is added, also on a second click
        st._select_sample(0)
        st.add_cur_btn.click()
        assert st._plates == []
        assert st.err.text() == (
            "Not added: this plate has no millimetre scale (no dish was found): set the dish or "
            "use the Ruler on the Measure tab, then add it.")
    assert not [k for k, *_ in dialogs.seen if k == "question"]   # refused, not asked


def test_f1_measure_save_and_export_all_leave_mm_blank(crop3_editor):
    tab, ed = crop3_editor
    tab.save()
    out = ed.out_dir
    dg = _read(os.path.join(out, "data-green-sample_crop3.csv"))
    ed._open_folder = lambda *_a, **_k: None
    ed.export_all()
    da = _read(os.path.join(out, "data_sample_crop3.csv"))
    for d in (dg, da):
        assert len(d) == 41
        assert set(d["DIAMETER_MM"]) == {""} and set(d["AREA_MM2"]) == {""}   # not 0.0
        assert (d["DIAMETER_PXL"].astype(float) > 0).all() and (d["AREA_PXL"].astype(float) > 0).all()
    # with a scale the same writers fill the mm columns (the change is the no-scale case only)
    ed._apply_ruler_scale(0.05)
    tab.save()
    dg = _read(os.path.join(out, "data-green-sample_crop3.csv"))
    assert (dg["DIAMETER_MM"].astype(float) > 0).all()


def test_f1_batch_files_leave_mm_blank_and_compare_app_path_too(tmp_path):
    img = make_crop3(tmp_path / "b")
    shutil.copy(SAMPLE_TIF, str(tmp_path / "b" / "sample.tif"))
    res = batch_measure.batch_measure(str(tmp_path / "b"), plate_mm=100, mode="current", scale="auto")
    od = res["out_dir"]
    ap = _read(os.path.join(od, "all_plaques.csv"))
    crop = ap[ap["IMAGE"] == "sample_crop3.png"]
    assert len(crop) == 41 and set(crop["DIAMETER_MM"]) == {""} and set(crop["AREA_MM2"]) == {""}
    whole = ap[ap["IMAGE"] == "sample.tif"]
    assert (whole["DIAMETER_MM"].astype(float) > 0).all()     # a plate with a dish keeps its mm
    dg = _read(os.path.join(od, "sample_crop3", "data-green-sample_crop3.csv"))
    assert set(dg["DIAMETER_MM"]) == {""} and (dg["DIAMETER_PXL"].astype(float) > 0).all()
    # Compare (app path: engine_api.run_compare with the tab's plaque size)
    cdir = tmp_path / "c"; cdir.mkdir()
    shutil.copy(img, str(cdir))
    r = engine_api.run_compare(str(cdir), plate_mm=100, out_dir=str(cdir / "out_turbidity"),
                               scale="auto")
    pa = _read(os.path.join(str(cdir / "out_turbidity"), "plaques_all.csv"))
    assert len(pa) == 41 and set(pa["DIAMETER_MM"]) == {""}
    assert len(r["df"]) == 41


def test_f1_cli_default_turbidity_path_still_writes_its_frozen_zero(tmp_path):
    """The command line's default turbidity path (frozen) is untouched: no QC_FLAG column and
    its 0.0 diameters where there is no dish, exactly as before."""
    import plaque_turbidity as ptb
    img = make_crop3(tmp_path / "t")
    det = ptb.detect_plate(img, "100", False)
    assert det["plaques"] and all(p["diameter_mm"] == 0.0 for p in det["plaques"])


def test_f1_analyze_csv_import_says_the_file_has_no_mm_sizes(window, crop3_editor, dialogs):
    tab, ed = crop3_editor
    tab.save()
    path = os.path.join(ed.out_dir, "data-green-sample_crop3.csv")
    st = window.study_tab
    st._samples.append({"group": "S", "subgroup": ""})
    st._refresh_tree(); st._select_sample(0)
    dialogs.open_paths = [path]
    st.add_csv_btn.click()
    assert st._plates == []
    assert st.err.text() == ("data-green-sample_crop3.csv: no millimetre sizes in this file (it was "
                             "measured without a scale). Set the dish or use the Ruler on the "
                             "Measure tab and save it again. Skipped.")
    assert not [k for k, *_ in dialogs.seen if k == "question"]   # not a "plate without sizes"


def test_f1_analyze_mixed_all_plaques_export_all_and_import_assign(window, qtbot, dialogs, tmp_path, monkeypatch):
    """Every CSV route of Analyze: Batch's all_plaques.csv holding a no-scale image beside a
    plate with a dish (only the latter is added), Export all's data_*.csv, Import & assign."""
    folder = tmp_path / "b"
    make_crop3(folder)
    shutil.copy(SAMPLE_TIF, str(folder / "sample.tif"))
    res = batch_measure.batch_measure(str(folder), plate_mm=100, mode="current", scale="auto")
    ap = os.path.join(res["out_dir"], "all_plaques.csv")
    st = window.study_tab
    st._samples.append({"group": "S", "subgroup": ""})
    st._refresh_tree(); st._select_sample(0)
    dialogs.open_paths = [ap]
    st.add_csv_btn.click()
    assert [p["source"] for p in st._plates] == ["all_plaques.csv · sample.tif"]
    assert len(st._plates[0]["diam"]) == 21 and min(st._plates[0]["diam"]) > 0
    assert st.err.text() == ("all_plaques.csv · sample_crop3.png: no millimetre sizes in this image "
                             "(it was measured without a scale). Set the dish or use the Ruler on "
                             "the Measure tab and save it again. Skipped.")
    assert not [k for k, *_ in dialogs.seen if k == "question"]
    # Export all's data_<stem>.csv of the same plate, through Import & assign
    tab = window.measure_tab
    ed = _open(tab, qtbot, dialogs, os.path.join(str(folder), "sample_crop3.png"))
    ed._open_folder = lambda *_a, **_k: None
    ed.export_all()
    data = os.path.join(ed.out_dir, "data_sample_crop3.csv")
    opened = []
    monkeypatch.setattr(ST._AssignDialog, "exec", lambda self: opened.append(1) or ST.QDialog.Accepted)
    dialogs.open_paths = [data]
    n_before = len(st._plates)
    st.assign_btn.click()
    assert opened == [] and len(st._plates) == n_before          # nothing to assign
    assert st.err.text() == ("data_sample_crop3.csv: no millimetre sizes in this file (it was "
                             "measured without a scale). Set the dish or use the Ruler on the "
                             "Measure tab and save it again. Skipped.")


# =========================================================================== F3 F4 F8
@pytest.fixture
def sample_editor(window, qtbot, dialogs, tmp_path):
    img = os.path.join(str(tmp_path / "s"), "sample.tif")
    os.makedirs(os.path.dirname(img)); shutil.copy(SAMPLE_TIF, img)
    ed = _open(window.measure_tab, qtbot, dialogs, img)
    return window.measure_tab, ed


def _meta(ed):
    return json.load(open(os.path.join(ed.out_dir, "run_metadata.json")))["images"][0]


def test_f3_measure_run_metadata_records_the_size_record_of_the_current_plaques(sample_editor):
    tab, ed = sample_editor
    ed._open_folder = lambda *_a, **_k: None
    tab.save()
    m = _meta(ed)
    assert (m["n_plaques"], m["n_sized"], m["n_core"], m["n_no_size"]) == (41, 21, 10, 10)
    assert m["plate_warnings"] == []
    # erase sized plaques until fewer than half are sized: the CURRENT plaques decide
    while True:
        flags = list(ed.table()["QC_FLAG"])
        if 2 * sum(plaque_qc.size_ok(f) for f in flags) < len(flags):
            break
        i = next(i for i, f in enumerate(flags) if plaque_qc.size_ok(f))
        ed._erase_at(QPointF(*ed.plaques[i]["center"]))
    flags = list(ed.table()["QC_FLAG"])
    want = engine_api.plate_warnings(ed.plaques, ed.ppm, flags=flags)
    assert want and want[0].startswith("sizes from 19 of 39 plaques")
    for action in (tab.save, ed.export_all):
        action()
        m = _meta(ed)
        assert m["plate_warnings"] == want                       # not the detection-time []
        assert (m["n_plaques"], m["n_sized"], m["n_core"], m["n_no_size"]) == (39, 19, 10, 10)
        assert m["n_sized"] + m["n_core"] + m["n_no_size"] == m["n_plaques"]
    # Batch counts with the same helper
    assert engine_api.size_counts(flags) == {"n_sized": 19, "n_core": 10, "n_no_size": 10}


def test_f4_a_dish_change_after_save_marks_the_plate_unsaved_and_open_asks(sample_editor, dialogs, tmp_path):
    tab, ed = sample_editor
    tab.save()
    assert not ed.dirty
    tab._quick_dish(100.0)                       # the same value again: nothing changed
    assert not ed.dirty
    tab.plate.setValue(90.0)
    assert ed.dirty and "unsaved edits" in ed.hint.text()
    other = os.path.join(str(tmp_path), "other.tif"); shutil.copy(SAMPLE_TIF, other)
    dialogs.open_path = other
    dialogs.question = QMessageBox.Cancel
    n_q = len([k for k, *_ in dialogs.seen if k == "question"])
    tab.open_btn.click()
    qs = [t for k, _ti, t in dialogs.seen if k == "question"]
    assert len(qs) == n_q + 1 and "a Dish size change" in qs[-1]
    assert tab.editor is ed and os.path.basename(tab.image_path) == "sample.tif"   # kept
    tab.save()
    assert not ed.dirty


NO_DISH = ("No dish found (no round contour larger than 100,000 px): sizes are in pixels only; make "
           "sure the whole dish is in the frame (or set the plate by hand in the app).")


def test_f8_no_dish_is_one_sentence_the_same_on_measure_batch_and_compare(crop3_editor, tmp_path):
    tab, ed = crop3_editor
    assert plaque_qc.no_dish_sentence(ed.det["dish_reason"]) == NO_DISH == plaque_qc.no_dish_sentence()
    flag = tab.flag_label.text()
    assert flag.count("No dish found") == 1 and ("⚠ " + NO_DISH) in flag
    folder = tmp_path / "b"
    make_crop3(folder)
    res = batch_measure.batch_measure(str(folder), plate_mm=100, mode="current", scale="auto")
    assert res["summary_df"].iloc[0]["error"] == NO_DISH
    q = pd.DataFrame({"PLATE": ["sample_crop3"], "DISH_FOUND": [False], "N_PLAQUES": [41]})
    note = appui.compare_qc_note(q)
    assert ("⚠ sample_crop3: " + NO_DISH) in note and note.count("No dish found") == 1


def test_f8_left_out_wording_is_grammatical_for_one_and_for_many(sample_editor, window):
    assert plaque_qc.left_out_said({"core": 1, "no_size": 0}, "left out of the sizes") == \
        "1 plaque outlined at the dark centre only was left out of the sizes"
    assert plaque_qc.left_out_said({"core": 9, "no_size": 1}, "left out of the sizes") == (
        "9 plaques outlined at the dark centre only and 1 split piece whose size is not reliable "
        "were left out of the sizes")
    assert plaque_qc.left_out_said({"core": 0, "no_size": 1}, "counted", present=True) == \
        "1 split piece whose size is not reliable is counted"
    # Measure flag line
    tab, ed = sample_editor
    assert ("Sizes from 21 of 41 plaques (10 plaques outlined at the dark centre only and 10 split "
            "pieces whose size is not reliable are counted but left out of the size summary).") \
        in tab.flag_label.text()
    # Compare QC note
    q = pd.DataFrame({"PLATE": ["p"], "DISH_FOUND": [True], "N_PLAQUES": [3]})
    assert ("Sizes and turbidity from 2 of 3 plaques (1 plaque outlined at the dark centre only is "
            "counted, and in the titer, but left out of the summaries and plots).") in \
        appui.compare_qc_note(q, flags=["OK", "OK", "CORE?"])
    # Analyze, Add current plate (a measurement with one CORE? plaque)
    st = window.study_tab
    st._samples.append({"group": "T4", "subgroup": ""})
    st._refresh_tree(); st._select_sample(0)
    tab.editor = None                      # the table alone, as test_ct_r1_detection d10a does
    tab.model.set_dataframe(pd.DataFrame({"INDEX": [1, 2, 3], "DIAMETER_MM": [5.1, 5.3, 2.4],
                                          "AREA_MM2": [20.4, 22.1, 4.5],
                                          "QC_FLAG": ["OK", "OK", "CORE?"]}))
    st.add_cur_btn.click()
    assert window.statusBar().currentMessage() == (
        "Added a plate to 'T4' (2 plaques; 1 plaque outlined at the dark centre only was left out "
        "of the sizes).")
