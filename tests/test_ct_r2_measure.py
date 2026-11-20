"""Click-through round 2, group "measure": regression tests for the Measure, Batch and Compare
tabs (findings N1-N14 of the round-2 desktop-measure report, and the coordinator's additions).

Every test drives the real tab / editor offscreen (pytest-qt) or the shared engine functions
directly, with modal dialogs monkeypatched, and asserts values.
"""
import json
import math
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
from PySide6.QtCore import Qt, QPointF               # noqa: E402
from PySide6.QtWidgets import QMessageBox, QInputDialog, QFileDialog   # noqa: E402

import plaque_gui as pgui                            # noqa: E402
import plaque_qc                                     # noqa: E402
import plaque_turbidity as ptb                       # noqa: E402
from app import ui as appui                          # noqa: E402
from app import engine_api                           # noqa: E402
from app import batch_measure                        # noqa: E402

TIMEOUT = 240_000
SAMPLE_TIF = os.path.join(ROOT, "app", "resources", "sample.tif")
SMALL_PLATES = os.path.join(ROOT, "Test_plates", "small")


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
        self.open_path = ""
        self.double = (85.0, True)
        self.directory = ""


@pytest.fixture
def dialogs(monkeypatch):
    d = Dialogs()
    for name in ("warning", "information", "critical"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(
            lambda *a, _n=name, **k: d.seen.append((_n, a[1] if len(a) > 1 else "",
                                                    a[2] if len(a) > 2 else "")) or QMessageBox.Ok))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(
        lambda *a, **k: d.seen.append(("question", a[1] if len(a) > 1 else "",
                                       a[2] if len(a) > 2 else "")) or d.question))
    monkeypatch.setattr(QInputDialog, "getDouble", staticmethod(
        lambda *a, **k: d.seen.append(("getDouble", "", "")) or d.double))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(
        lambda *a, **k: (d.open_path, "")))
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


def _open(tab, qtbot, dialogs, path, mode="current", dish=90.0, scale=None):
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


def _copy(src, folder, name=None):
    os.makedirs(str(folder), exist_ok=True)
    dst = os.path.join(str(folder), name or os.path.basename(src))
    shutil.copy(src, dst)
    return dst


def _compare_tab(window):
    return window.tabs.widget(2).widget()


def _batch_tab(window):
    return window.tabs.widget(1).widget()


def _table(view):
    m = view.model()
    hdr = [m.headerData(c, Qt.Horizontal, Qt.DisplayRole) for c in range(m.columnCount())]
    rows = [[m.data(m.index(r, c), Qt.DisplayRole) for c in range(m.columnCount())]
            for r in range(m.rowCount())]
    return hdr, rows


@pytest.fixture
def phage_folder(neutral_plate_tif, tmp_path):
    folder = tmp_path / "phages"
    folder.mkdir()
    for name in ("T4_1", "T4_2", "T7_1"):
        shutil.copy(neutral_plate_tif, folder / (name + ".tif"))
    return folder


def _key_region(img, patch):
    x, y = pgui.key_origin(img.shape, patch.shape)
    return img[y:y + patch.shape[0], x:x + patch.shape[1]]


# =========================================================================== N8
def test_n8_batch_overlay_ships_its_key_text_and_honours_place_key_on_figure(neutral_plate_tif, tmp_path):
    """Every Batch overlay gets a stand-alone key in its own format (+ PNG) and a legend text
    starter beside it; with key_on_figure the key drawn on the overlay IS the stand-alone key."""
    folder = tmp_path / "plates"
    _copy(neutral_plate_tif, folder)
    det = engine_api.detect_single(str(folder / "neutral_plate.tif"), plate_mm=90, scale="auto")
    key = pgui.plate_key(engine_api.reading_order(det["plaques"]))

    off = batch_measure.batch_measure(str(folder), plate_mm=90, out_dir=str(tmp_path / "off"))
    d = os.path.join(off["out_dir"], "neutral_plate")
    for f in ("out_neutral_plate_legend_key.tif", "out_neutral_plate_legend_key.png"):
        assert os.path.getsize(os.path.join(d, f)) > 500, f
    text = open(os.path.join(d, "out_neutral_plate_legend_text.txt")).read().strip()
    assert text == pgui.key_text(engine_api.reading_order(det["plaques"])) and "auto-detected (green" in text
    patch = pgui.key_image_for(det["orig_bgr"].shape, key)
    img_off = cv2.imread(os.path.join(d, "out_neutral_plate.tif"))
    assert not np.array_equal(_key_region(img_off, patch), patch)

    on = batch_measure.batch_measure(str(folder), plate_mm=90, out_dir=str(tmp_path / "on"),
                                     key_on_figure=True)
    img_on = cv2.imread(os.path.join(on["out_dir"], "neutral_plate", "out_neutral_plate.tif"))
    assert np.array_equal(_key_region(img_on, patch), patch)
    meta = json.load(open(os.path.join(on["out_dir"], "run_metadata.json")))
    assert meta["settings"]["key_on_figure"] is True


def test_n8_batch_tab_has_the_switch_and_passes_it(window, monkeypatch, tmp_path, neutral_plate_tif):
    tab = _batch_tab(window)
    seen = {}
    monkeypatch.setattr(batch_measure, "batch_measure",
                        lambda *a, **k: seen.update(k) or {"summary_df": pd.DataFrame({"image": []}),
                                                           "out_dir": str(tmp_path), "n_images": 0})
    _copy(neutral_plate_tif, tmp_path / "b")
    tab.folder.setText(str(tmp_path / "b"))
    tab.key_cb.setChecked(True)
    tab._run()
    from PySide6.QtCore import QThreadPool
    window.pool.waitForDone(10000)
    assert seen.get("key_on_figure") is True


def test_n8_turbidity_overlay_has_key_text_readable_labels_and_plate_index(phage_folder, tmp_path, monkeypatch):
    drawn = []
    real = pgui._draw_texts
    monkeypatch.setattr(pgui, "_draw_texts", lambda img, items: drawn.append(list(items)) or real(img, items))
    recs = []
    out = tmp_path / "out"
    df = ptb.run_batch(str(phage_folder), "90", False, None, None, str(out), make_plots=False,
                       key_on_figure=True, overlay_records=recs)
    assert [r["plate"] for r in recs] == ["T4_1", "T4_2", "T7_1"]
    img = cv2.imread(str(out / "overlay_T4_1.png"))
    m = pgui.figure_metrics(img.shape)
    # labels = PLATE_INDEX, in the figure font at the figure's size (the old ones were ~10 px)
    rows = df[df["PLATE"] == "T4_1"]
    assert [it[0] for it in drawn[0]] == [str(i) for i in rows["PLATE_INDEX"]]
    assert all(it[3] == m["font_px"] >= 12 for it in drawn[0])
    # key: stand-alone (PNG, the overlay's format) + legend text, embedded == stand-alone
    key = ptb.overlay_key(recs[0])
    text = (out / "overlay_T4_1_legend_text.txt").read_text().strip()
    assert text.startswith("dish rim (") and "plaque (no turbidity: needs a blank-agar image) (" in text
    assert os.path.getsize(out / "overlay_T4_1_legend_key.png") > 500
    patch = pgui.key_image_for(img.shape, key)
    assert np.array_equal(_key_region(img, patch), patch)
    # the switch off: re-drawn from the records, no key on the overlay, files still there
    ptb.redraw_overlays(recs, str(out), key_on_figure=False)
    img2 = cv2.imread(str(out / "overlay_T4_1.png"))
    assert not np.array_equal(_key_region(img2, patch), patch)
    assert (out / "overlay_T4_1_legend_text.txt").read_text().strip() == text


def test_n8_turbidity_overlay_classes_are_the_clarity_bins():
    det = {"orig": np.zeros((200, 200, 3), np.uint8), "dish_center": (100, 100), "dish_r": 90,
           "plaques": [{"hull": [[x - 6, 50], [x + 6, 50], [x + 6, 62], [x - 6, 62]]} for x in (30, 70, 110, 150)]}
    rows = [{"PLATE_INDEX": i + 1, "CLARITY": c} for i, c in enumerate(("clear", "turbid", "", "intermediate"))]
    rec = ptb.overlay_record(det, rows, "P", size_ok=[True, True, True, False])
    assert rec["classes"] == ["clear", "turbid", "unmeasured", "nosize"]
    names = [e["label"] for e in ptb.overlay_key(rec)["entries"]]
    assert names == ["dish rim", ptb.OVERLAY_CLASSES["clear"][0], ptb.OVERLAY_CLASSES["turbid"][0],
                     ptb.OVERLAY_CLASSES["unmeasured"][0], ptb.OVERLAY_CLASSES["nosize"][0]]
    assert ptb.overlay_key(rec)["entries"][-1]["linestyle"] == ":"


def test_n8_compare_key_switch_redraws_the_overlays(window, qtbot, phage_folder, dialogs):
    tab = _compare_tab(window)
    tab.folder["edit"].setText(str(phage_folder))
    tab.plate.setValue(90)
    tab.key_cb.setChecked(True)
    tab.run()
    qtbot.waitUntil(lambda: tab.run_btn.isEnabled(), timeout=TIMEOUT)
    out = phage_folder / "out_turbidity"
    assert len(tab._overlays) == 3
    img = cv2.imread(str(out / "overlay_T4_1.png"))
    patch = pgui.key_image_for(img.shape, ptb.overlay_key(tab._overlays[0]))
    assert np.array_equal(_key_region(img, patch), patch)
    tab.key_cb.setChecked(False)
    qtbot.waitUntil(lambda: tab.run_btn.isEnabled(), timeout=TIMEOUT)
    qtbot.wait(50)
    img2 = cv2.imread(str(out / "overlay_T4_1.png"))
    assert not np.array_equal(_key_region(img2, patch), patch)
