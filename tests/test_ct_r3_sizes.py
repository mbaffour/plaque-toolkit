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
