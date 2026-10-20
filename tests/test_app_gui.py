"""Headless tests of the desktop app (PySide6 with the offscreen platform plugin).

Until the 2026-10 audit the 7,000-line app had no automated coverage: every UI finding was a
static read. These tests drive the real tabs through their real worker threads on the
synthetic plates from conftest.py. They are skipped where PySide6 or pytest-qt is missing
(the CI image has neither), so run them locally with both installed.
"""
import json
import os
import shutil
import sys

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QMessageBox  # noqa: E402

from app import ui as appui              # noqa: E402
from app import engine_api               # noqa: E402

TIMEOUT = 60_000


def _mode_index(key):
    for i, (_label, k, _help) in enumerate(appui.MODES):
        if k == key:
            return i
    raise KeyError(key)


@pytest.fixture
def window(qtbot):
    win = appui.MainWindow()
    qtbot.addWidget(win)
    return win


@pytest.fixture
def no_dialogs(monkeypatch):
    """Record modal message boxes instead of showing them (they would block offscreen)."""
    seen = []
    for name in ("warning", "information", "critical"):
        monkeypatch.setattr(QMessageBox, name,
                            staticmethod(lambda *a, _n=name, **k: seen.append((_n, a[1] if len(a) > 1 else "")) or QMessageBox.Ok))
    return seen


# --------------------------------------------------------------------------- main window
def test_main_window_has_the_seven_documented_tabs(window):
    titles = [window.tabs.tabText(i).strip() for i in range(window.tabs.count())]
    assert titles == ["Measure", "Batch", "Compare turbidity", "Analyze", "Validate",
                      "Fiji agreement", "About"]


# --------------------------------------------------------------------------- measure tab
def test_measure_tab_detects_and_fills_the_table(window, qtbot, neutral_plate_tif):
    tab = window.measure_tab
    tab.mode.setCurrentIndex(_mode_index("published"))
    tab.plate.setValue(90)
    tab.image_path = str(neutral_plate_tif)
    tab._detect()
    assert tab.busy
    qtbot.waitUntil(lambda: tab.det is not None and not tab.busy, timeout=TIMEOUT)
    assert tab.det["published"] is True and tab.det["small"] is False
    assert tab.det["n_plaques"] > 0
    assert tab.model.rowCount() == tab.det["n_plaques"]
    assert tab.editor is not None and tab.editor.image_path == str(neutral_plate_tif)
    assert str(tab.det["n_plaques"]) in window.statusBar().currentMessage()

    # switching engine and re-detecting carries the new engine flags with the result
    tab.mode.setCurrentIndex(_mode_index("current"))
    tab.det = None
    tab.redetect()
    qtbot.waitUntil(lambda: tab.det is not None and not tab.busy, timeout=TIMEOUT)
    assert tab.det["published"] is False and tab.det["small"] is True


def test_measure_tab_is_not_left_busy_when_the_editor_fails(window, monkeypatch):
    tab = window.measure_tab
    tab.busy = True
    monkeypatch.setattr(tab, "_mount_editor", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        tab.on_detected({"n_plaques": 0, "plaques": [], "orig_bgr": None})
    assert tab.busy is False


def test_orient_keeps_image_labels_and_editor_consistent(window, qtbot, neutral_plate_tif, tmp_path):
    """PT-34: after Orient, exported labels must point at an image in the same orientation."""
    from app import validate as V
    work = tmp_path / "plate"
    work.mkdir()
    img = work / "P.tif"
    shutil.copy(neutral_plate_tif, img)
    tab = window.measure_tab
    tab.mode.setCurrentIndex(_mode_index("current"))
    tab.plate.setValue(90)
    tab.image_path = str(img)
    tab._detect()
    qtbot.waitUntil(lambda: tab.det is not None and not tab.busy, timeout=TIMEOUT)
    n_before = tab.det["n_plaques"]

    tab.det = None
    tab._orient("cw")
    qtbot.waitUntil(lambda: tab.det is not None and not tab.busy, timeout=TIMEOUT)
    assert tab._detect_src.endswith("_oriented.png") and os.path.exists(tab._detect_src)
    assert tab.editor.image_path == tab._detect_src
    assert tab.det["n_plaques"] == n_before          # a rotation must not change the count

    labels = tmp_path / "labels_P.json"
    tab.editor.export_groundtruth(str(labels))
    meta = json.load(open(labels))["meta"]
    assert meta["image_path"] == os.path.abspath(tab._detect_src)
    score = V.score_label_file(str(labels), mode="current")
    assert score["recall"] > 0.9 and score["precision"] > 0.9


# --------------------------------------------------------------------------- batch tab
def _batch_tab(window):
    return window.tabs.widget(1).widget()


def test_batch_tab_warns_instead_of_running_without_a_folder(window, no_dialogs):
    tab = _batch_tab(window)
    tab.folder.setText("")
    tab._run()
    assert no_dialogs and no_dialogs[0][0] == "warning"


def test_batch_published_matches_the_cli_unless_small_is_ticked(window, qtbot, neutral_plate_tif, tmp_path, no_dialogs):
    """PT-33: Batch-tab Published must not add -small on its own."""
    folder = tmp_path / "plates"
    folder.mkdir()
    shutil.copy(neutral_plate_tif, folder / "P.tif")
    tab = _batch_tab(window)
    tab.folder.setText(str(folder))
    tab.mode.setCurrentIndex(_mode_index("published"))
    tab.plate.setValue(90)
    tab.small.setChecked(False)
    tab._run()
    qtbot.waitUntil(lambda: tab.last_out is not None, timeout=TIMEOUT)
    meta = json.load(open(os.path.join(tab.last_out, "run_metadata.json")))
    assert meta["engine"] == "Published" and meta["settings"]["small"] is False
    assert tab.model.rowCount() == 1
    n_plain = int(meta["images"][0]["n_plaques"])

    tab.last_out = None
    tab.small.setChecked(True)
    tab._run()
    qtbot.waitUntil(lambda: tab.last_out is not None, timeout=TIMEOUT)
    meta = json.load(open(os.path.join(tab.last_out, "run_metadata.json")))
    assert meta["settings"]["small"] is True
    assert int(meta["images"][0]["n_plaques"]) >= n_plain   # the small gates only ever add


# --------------------------------------------------------------------------- compare tab
def _compare_tab(window):
    return window.tabs.widget(2).widget()


def test_compare_tab_survives_a_zero_plaque_folder(window, qtbot, tmp_path, no_dialogs):
    """PT-56: header-only turbidity CSVs must load; the 1-byte files used to raise."""
    import cv2
    import numpy as np
    folder = tmp_path / "blank"
    folder.mkdir()
    cv2.imwrite(str(folder / "blank_1.png"), np.full((300, 300, 3), 120, np.uint8))
    tab = _compare_tab(window)
    tab.folder["edit"].setText(str(folder))
    tab.plate.setValue(90)
    tab.run()
    assert not tab.run_btn.isEnabled()                 # busy while the worker runs
    qtbot.waitUntil(lambda: tab.run_btn.isEnabled(), timeout=TIMEOUT)   # on_done ran
    out_dir = folder / "out_turbidity"
    assert (out_dir / "per_phage.csv").exists()
    assert tab.model.rowCount() == 0                    # header-only, loaded without error
    assert not [d for d in no_dialogs if d[0] == "critical"]
