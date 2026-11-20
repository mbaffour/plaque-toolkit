"""Click-through round 1, group "measure": regression tests for the Measure tab and its
plate figure (findings F6-F12, F14-F16, F19, F20, F22, F24, F25 of the desktop-measure report).

Every test drives the real Measure tab / editor offscreen (pytest-qt) or the shared figure
functions directly, with modal dialogs monkeypatched, and asserts values -- files written,
metadata fields, pixel colours, label positions -- rather than "does not raise".
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
from PySide6.QtWidgets import (QMessageBox, QInputDialog, QFileDialog,   # noqa: E402
                               QGraphicsSimpleTextItem, QGraphicsPixmapItem)
from PySide6.QtTest import QTest                     # noqa: E402

import plaque_gui as pgui                            # noqa: E402
import scalebar as sbmod                             # noqa: E402
from app import ui as appui                          # noqa: E402
from app import engine_api                           # noqa: E402
from app import widgets                              # noqa: E402

TIMEOUT = 120_000
SAMPLE_TIF = os.path.join(ROOT, "app", "resources", "sample.tif")


# --------------------------------------------------------------------------- helpers
@pytest.fixture(autouse=True)
def _legend_key_as_package():
    """The app imports ``from plaque_stats import legend_key``. test_audit_2026_10 puts
    plaque_stats/ itself on sys.path, which turns ``plaque_stats`` into the flat engine module
    for the rest of the session; undo that for these tests (as tests/test_legend_key.py does)."""
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
    """Every modal the code under test would open, answered without blocking."""

    def __init__(self):
        self.seen = []
        self.question = QMessageBox.Discard
        self.open_path = ""
        self.double = (85.0, True)


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
    return d


@pytest.fixture
def window(qtbot, dialogs):
    win = appui.MainWindow()
    qtbot.addWidget(win)
    win.show()
    win.resize(1320, 880)
    qtbot.wait(50)
    return win


def _open(tab, qtbot, dialogs, path, mode="current", dish=90.0):
    """Open `path` through the real Open button (file dialog patched) and wait for it."""
    tab.mode.setCurrentIndex(_mode_index(mode))
    tab.plate.setValue(dish)
    dialogs.open_path = str(path)
    tab.det = None
    tab.open_btn.click()
    qtbot.waitUntil(lambda: tab.det is not None and not tab.busy, timeout=TIMEOUT)
    qtbot.wait(30)
    return tab.editor


def _copy(src, folder):
    os.makedirs(folder, exist_ok=True)
    dst = os.path.join(str(folder), os.path.basename(src))
    shutil.copy(src, dst)
    return dst


def _screen_df(tab):
    """The table as the user sees it (display strings), in model column order."""
    m = tab.model
    cols = [m.headerData(c, Qt.Horizontal, Qt.DisplayRole) for c in range(m.columnCount())]
    rows = [[m.data(m.index(r, c), Qt.DisplayRole) for c in range(m.columnCount())]
            for r in range(m.rowCount())]
    return pd.DataFrame(rows, columns=cols)


def _circle(cx, cy, r, source="auto"):
    return {"source": source, "kind": "circle", "center": (float(cx), float(cy)),
            "radius": float(r), "area_pxl": float(math.pi * r * r)}


def _plain_plate(h=900, w=1200):
    img = np.full((h, w, 3), 140, np.uint8)
    return img


# =========================================================================== F6 + F7
def test_f6_f7_every_export_uses_the_results_own_engine_and_matches_the_screen(
        window, qtbot, dialogs, tmp_path):
    """The tester's sequence: Sensitive on Measure, a Published detect_single elsewhere (as
    the Batch tab does), then Save / Data table CSV / Export all / labels must still say
    Sensitive and equal the on-screen table."""
    tab = window.measure_tab
    img = _copy(SAMPLE_TIF, tmp_path / "s1")
    ed = _open(tab, qtbot, dialogs, img, mode="sensitive", dish=100.0)
    n = len(ed.plaques)
    assert tab.det["sensitive"] is True and n > 0
    on_screen = pd.to_numeric(tab.model.dataframe()["DIAMETER_MM"]).to_numpy()

    # another tab runs the Published engine: the engine module's globals flip
    engine_api.detect_single(img, plate_mm=100, published=True)
    import plaque_size_tool as pst
    assert pst.use_published is True

    out = os.path.join(os.path.dirname(img), "out")
    tab.save()
    meta = json.load(open(os.path.join(out, "run_metadata.json")))
    assert meta["engine"] == "Sensitive"
    st = meta["settings"]
    # CT-R1 detection D1: Sensitive runs the Auto plaque size, not forced -small
    assert st["sensitive"] is True and st["small_plaque"] is False and st["published"] is False
    assert st["plaque_size"] == "auto"
    assert st["watershed"] is False
    assert st["plate_size_mm"] == pytest.approx(100.0, abs=0.01)     # used to be null
    assert st["edited"] is False
    assert st["source_image"] == img and st["orientation"] == []
    assert meta["images"][0]["n_plaques"] == n
    saved = pd.read_csv(os.path.join(out, "data-green-sample.csv"))
    np.testing.assert_allclose(saved["DIAMETER_MM"].to_numpy(), on_screen, atol=1e-9)

    # More > Data table (CSV) -- used to size two plaques by the Published rule
    csv = str(tmp_path / "table.csv")
    ed.export_csv(csv)
    more = pd.read_csv(csv)
    np.testing.assert_allclose(more["DIAMETER_MM"].to_numpy(), on_screen, atol=1e-9)
    assert list(more["QC_FLAG"]) == list(tab.model.dataframe()["QC_FLAG"])   # EDGE computed too

    # Export all
    ed.export_all()
    meta = json.load(open(os.path.join(out, "run_metadata.json")))
    assert meta["engine"] == "Sensitive" and meta["settings"]["plate_size_mm"] == pytest.approx(100.0, abs=0.01)
    data = pd.read_csv(os.path.join(out, "data_sample.csv"))
    np.testing.assert_allclose(data["DIAMETER_MM"].to_numpy(), on_screen, atol=1e-9)

    # ground-truth labels
    gt = str(tmp_path / "labels.json")
    ed.export_groundtruth(gt)
    recs = json.load(open(gt))["plaques"]
    np.testing.assert_allclose([r["diam_mm"] for r in recs], on_screen, atol=0.006)


def test_f6_edited_is_recorded_for_plaque_and_calibration_edits(window, qtbot, dialogs, tmp_path,
                                                                neutral_plate_tif):
    tab = window.measure_tab
    img = _copy(neutral_plate_tif, tmp_path / "e")
    ed = _open(tab, qtbot, dialogs, img, mode="current", dish=90.0)
    out = os.path.join(os.path.dirname(img), "out")

    def meta():
        tab.save()
        return json.load(open(os.path.join(out, "run_metadata.json")))

    assert meta()["settings"]["edited"] is False
    # erase two detections: the set now differs from the detection result
    for p in list(ed.plaques)[:2]:
        ed._erase_at(QPointF(*p["center"]))
    m = meta()
    assert m["settings"]["edited"] is True
    assert m["images"][0]["edits"]["n_removed"] == 2
    # undo both: back to the detection result
    ed._undo_last(); ed._undo_last()
    assert meta()["settings"]["edited"] is False
    # a hand calibration alone also makes the result "edited"
    pl = ed.plate
    ed._apply_dish(pl["center"][0], pl["center"][1], pl["radius"], diam_mm=85.0)
    m = meta()
    assert m["settings"]["edited"] is True
    assert m["images"][0]["edits"]["calibration"] == "set plate"
    assert m["settings"]["plate_size_mm"] == pytest.approx(85.0, abs=0.01)


def test_f6_save_results_keeps_its_positional_contract(tmp_path, neutral_plate_tif):
    """app/batch_measure.py and measure_samples.py call save_results positionally and unpack
    three values; the new keywords are optional."""
    det = engine_api.detect_single(neutral_plate_tif, plate_mm=90, published=True)
    csv_path, img_path, n = pgui.save_results(det["plaques"], det["orig_bgr"], neutral_plate_tif,
                                              str(tmp_path / "o"), det["pxl_per_mm"], det["lawn_gray"])
    assert os.path.exists(csv_path) and os.path.exists(img_path) and n == len(det["plaques"])
    meta = json.load(open(os.path.join(str(tmp_path / "o"), "run_metadata.json")))
    assert meta["engine"] == "Published"
    # explicit keywords win over the module globals
    pgui.save_results(det["plaques"], det["orig_bgr"], neutral_plate_tif, str(tmp_path / "k"),
                      det["pxl_per_mm"], det["lawn_gray"], published=False, sensitive=True,
                      small=True, plate_mm=90.0, edited=True, orientation=["cw"],
                      source_image="/x/orig.tif")
    st = json.load(open(os.path.join(str(tmp_path / "k"), "run_metadata.json")))["settings"]
    assert st["sensitive"] is True and st["edited"] is True and st["plate_size_mm"] == 90.0
    assert st["orientation"] == ["cw"] and st["source_image"] == "/x/orig.tif"


# =========================================================================== F9 / F12 / F19 / F22
def _editor_on(window, qtbot, dialogs, tmp_path, neutral_plate_tif, mode="current"):
    tab = window.measure_tab
    img = _copy(neutral_plate_tif, tmp_path / "fig")
    return tab, _open(tab, qtbot, dialogs, img, mode=mode, dish=90.0)


def test_f9_one_class_map_drives_the_canvas_and_the_export(window, qtbot, dialogs, tmp_path,
                                                           neutral_plate_tif):
    tab, ed = _editor_on(window, qtbot, dialogs, tmp_path, neutral_plate_tif)
    # one plaque of every class, far apart; two overlapping ones for the dashed class
    ed._push_undo()
    ed._plaques = [dict(_circle(150, 150, 20, "auto"), _uid=101),
                   dict(_circle(300, 150, 20, "manual"), _uid=102),
                   dict(_circle(450, 150, 20, "region"), _uid=103),
                   dict(_circle(600, 150, 20, "watershed"), _uid=104),
                   dict(_circle(300, 600, 25, "auto"), _uid=105),
                   dict(_circle(330, 600, 25, "auto"), _uid=106)]
    ed._changed("test")
    want = {101: "auto", 102: "manual", 103: "region", 104: "watershed", 105: "overlap", 106: "overlap"}
    # canvas: each outline is drawn in the map's colour and line style
    from PySide6.QtWidgets import QGraphicsEllipseItem
    items = [it for it in ed._overlay if isinstance(it, QGraphicsEllipseItem)]
    assert len(items) == 6
    by_x = {}
    for it in items:
        r = it.rect()
        by_x[(round(r.center().x()), round(r.center().y()))] = it.pen()
    for p in ed.plaques:
        pen = by_x[(round(p["center"][0]), round(p["center"][1]))]
        _n, rgb, style = pgui.PLAQUE_CLASSES[want[p["_uid"]]]
        assert (pen.color().red(), pen.color().green(), pen.color().blue()) == rgb
        assert (pen.style() == Qt.DashLine) == (style == "dashed")
    # export: the same classes, the same RGB on the outline
    assert pgui.plaque_classes(ed.plaques) == [want[p["_uid"]] for p in ed.plaques]
    fig = pgui.annotate_plaques(ed.orig_bgr, ed.plaques, ed.ppm, labels="none", scalebar=False)
    for p in ed.plaques[:4]:
        _n, rgb, _s = pgui.PLAQUE_CLASSES[want[p["_uid"]]]
        x = int(round(p["center"][0] + p["radius"]))
        y = int(round(p["center"][1]))
        assert tuple(int(v) for v in fig[y, x][::-1]) == rgb
    # the old export drew only (0,255,0) / pure blue
    assert not ((fig[..., 0] == 255) & (fig[..., 1] == 0) & (fig[..., 2] == 0)).any()


def test_f9_labels_scale_with_the_image_and_sit_outside_the_outline():
    small, big = pgui.figure_metrics((900, 1200)), pgui.figure_metrics((3000, 4000))
    assert big["font_px"] >= 3 * small["font_px"] * 0.95          # scales with the width
    assert pgui.text_size("12", big["font_px"])[1] > 2.5 * pgui.text_size("12", small["font_px"])[1]
    plaques = [_circle(400, 400, 30), _circle(470, 400, 30), _circle(435, 460, 30), _circle(800, 300, 15)]
    m = small
    texts = [str(i) for i in range(1, 5)]
    sizes = [pgui.text_size(t, m["font_px"], m["stroke"]) for t in texts]
    placed = pgui.layout_labels(plaques, sizes, (900, 1200), m["gap"])
    rects = [r for _s, r in placed]
    for p, r in zip(plaques, rects):
        cx, cy = p["center"]
        # the label does not cover its own plaque's centre
        assert not (r[0] <= cx <= r[2] and r[1] <= cy <= r[3])
    for i in range(len(rects)):                                     # no two labels overlap
        for j in range(i + 1, len(rects)):
            a, b = rects[i], rects[j]
            assert min(a[2], b[2]) <= max(a[0], b[0]) or min(a[3], b[3]) <= max(a[1], b[1])
    # white text with a dark outline in the export
    img = _plain_plate()
    fig = pgui.annotate_plaques(img, plaques, 0.08, scalebar=False)
    r = rects[3]
    patch = fig[int(r[1]):int(r[3]) + 1, int(r[0]):int(r[2]) + 1]
    assert (patch.min(axis=2) >= 245).any() and (patch.max(axis=2) <= 30).any()


def test_f9_labels_mode_drives_screen_and_export(window, qtbot, dialogs, tmp_path, neutral_plate_tif):
    tab, ed = _editor_on(window, qtbot, dialogs, tmp_path, neutral_plate_tif)
    assert ed.label_combo.currentData() == "numbers"                  # default
    texts = lambda: sorted(it.text() for it in ed._overlay if isinstance(it, QGraphicsSimpleTextItem))
    assert texts() == sorted(str(i) for i in range(1, len(ed.plaques) + 1))
    ed.set_label_mode("numbers + mm")
    dm = tab.model.dataframe()["DIAMETER_MM"].tolist()
    assert texts() == sorted("%d: %.2f mm" % (i, d) for i, d in enumerate(dm, start=1))
    ed.set_label_mode("none")
    assert texts() == []
    # the export follows the box: 'none' draws no white glyphs at all
    p_none = ed.export_figure(str(tmp_path / "none.png"))
    ed.set_label_mode("numbers")
    p_num = ed.export_figure(str(tmp_path / "num.png"))
    white = lambda p: int((cv2.imread(p).min(axis=2) >= 250).sum())
    assert white(p_num) > white(p_none) + 50


def test_f19_scale_bar_geometry_is_shared_and_clamped(window, qtbot, dialogs, tmp_path, neutral_plate_tif):
    tab, ed = _editor_on(window, qtbot, dialogs, tmp_path, neutral_plate_tif)
    H, W = ed.orig_bgr.shape[:2]
    ed.scale_combo.setCurrentIndex([v for _l, v in appui_scale_options()].index(100.0))
    g = ed._sb_g
    assert g == sbmod.bar_geometry(ed.orig_bgr.shape, ed.ppm, anchor=ed._scalebar_anchor,
                                   length_mm=100.0, plate=ed.plate)
    assert g["x0"] >= 0 and g["x0"] + g["length_px"] <= W        # never off the image
    assert g["shortened"] and "does not fit" in ed.hint.text()
    # dragged far past the bottom-right corner: still wholly inside
    ed._move_scalebar(10 * W, 10 * H)
    g = ed._sb_g
    assert g["x0"] + g["length_px"] <= W and g["y0"] + g["thickness"] <= H
    # the export draws the bar exactly where the canvas has it
    fig = pgui.annotate_plaques(ed.orig_bgr, [], ed.ppm, **{k: v for k, v in ed._figure_kwargs().items()
                                                          if k not in ("key",)})
    y = g["y0"] + g["thickness"] // 2
    row = fig[y, g["x0"]:g["x0"] + g["length_px"]]
    assert (row.min(axis=1) >= 250).mean() > 0.95


def appui_scale_options():
    from app import plaque_canvas
    return plaque_canvas._SCALE_OPTIONS


def test_f12_legend_key_follows_the_plate_and_matches_on_figure(window, qtbot, dialogs, tmp_path,
                                                                neutral_plate_tif):
    tab, ed = _editor_on(window, qtbot, dialogs, tmp_path, neutral_plate_tif)
    assert ed.key_text.text() == "auto-detected (green, solid line)."
    # add a hand circle far from the others: the key gains a class
    ed._add_circle(QPointF(150, 150), 12)
    assert "added by hand" in ed.key_text.text() and "blue" in ed.key_text.text()
    names = [e["label"] for e in ed.legend_key()["entries"]]
    assert names == ["auto-detected", "added by hand"]
    # the standalone key file
    kp = ed.export_legend_key(str(tmp_path / "key.svg"))
    assert kp and os.path.getsize(kp) > 500 and "added by hand" in open(kp).read()
    # removing it drops the class again -- never a stale key
    ed._undo_last()
    assert "added by hand" not in ed.key_text.text()
    # place on figure: the embedded key is pixel-for-pixel the key picture
    ed.key_cb.setChecked(True)
    out = ed.export_figure(str(tmp_path / "with_key.png"))
    fig = cv2.imread(out)
    patch = pgui.key_image_for(fig.shape, ed.legend_key())
    x, y = pgui.key_origin(fig.shape, patch.shape)
    np.testing.assert_array_equal(fig[y:y + patch.shape[0], x:x + patch.shape[1]], patch)
    # ... and the canvas shows that same picture at that same place
    items = [it for it in ed.scene.items() if isinstance(it, QGraphicsPixmapItem) and it.zValue() == 24]
    assert len(items) == 1 and (items[0].pos().x(), items[0].pos().y()) == (x, y)
    qimg = items[0].pixmap().toImage().convertToFormat(items[0].pixmap().toImage().Format.Format_RGB888)
    arr = np.frombuffer(qimg.constBits(), np.uint8).reshape(qimg.height(), qimg.bytesPerLine())[:, :qimg.width() * 3]
    np.testing.assert_array_equal(arr.reshape(qimg.height(), qimg.width(), 3), cv2.cvtColor(patch, cv2.COLOR_BGR2RGB))
    # standalone key files ship with Export all and Save results
    ed.export_all()
    od = ed.out_dir
    assert os.path.getsize(os.path.join(od, "figure_neutral_plate_legend_key.png")) > 500
    assert open(os.path.join(od, "figure_neutral_plate_legend_text.txt")).read().strip() == ed.key_text.text()
    tab.save()
    assert os.path.exists(os.path.join(od, "out_neutral_plate_legend_key.png"))
    # the More menu offers it
    assert any("Legend key" in a.text() for a in ed.more_menu.actions())


@pytest.mark.parametrize("ext", [".png", ".jpg", ".tif", ".pdf", ".svg"])
def test_f22_annotated_figure_formats(window, qtbot, dialogs, tmp_path, neutral_plate_tif, ext):
    tab, ed = _editor_on(window, qtbot, dialogs, tmp_path, neutral_plate_tif)
    path = str(tmp_path / ("fig" + ext))
    out = ed.export_figure(path)
    assert out == path and os.path.getsize(out) > 1000
    head = open(out, "rb").read(8)
    if ext == ".pdf":
        assert head.startswith(b"%PDF")
    if ext == ".svg":
        assert b"<svg" in open(out, "rb").read(2000) or head.startswith(b"<?xml")
    assert "saved the annotated figure" in ed.hint.text()


def test_f22_unknown_extension_and_failure_are_reported(window, qtbot, dialogs, tmp_path,
                                                        neutral_plate_tif, monkeypatch):
    tab, ed = _editor_on(window, qtbot, dialogs, tmp_path, neutral_plate_tif)
    out = ed.export_figure(str(tmp_path / "fig.heic"))
    assert out == str(tmp_path / "fig.png") and os.path.exists(out)
    assert "saved as fig.png" in ed.hint.text()
    monkeypatch.setattr(pgui, "write_figure", lambda *a, **k: (_ for _ in ()).throw(IOError("disk full")))
    assert ed.export_figure(str(tmp_path / "x.png")) is None
    assert "could not save" in ed.hint.text() and "disk full" in ed.hint.text()


# =========================================================================== F8 / F20 / F25
def test_f8_dirty_editor_asks_once_before_redetect_orient_and_open(window, qtbot, dialogs, tmp_path,
                                                                   neutral_plate_tif):
    tab, ed = _editor_on(window, qtbot, dialogs, tmp_path, neutral_plate_tif)
    assert ed.dirty is False
    tab.redetect()                                 # clean: no question, detection runs
    assert not [d for d in dialogs.seen if d[0] == "question"]
    qtbot.waitUntil(lambda: not tab.busy, timeout=TIMEOUT)
    ed = tab.editor
    ed._erase_at(QPointF(*ed.plaques[0]["center"]))
    assert ed.dirty is True
    n = len(ed.plaques)
    dialogs.question = QMessageBox.Cancel
    for action in (tab.redetect, lambda: tab._orient("cw"), tab.open_image):
        dialogs.seen.clear()
        dialogs.open_path = str(neutral_plate_tif)
        action()
        assert [d[0] for d in dialogs.seen] == ["question"]
        assert not tab.busy and tab.editor is ed and len(ed.plaques) == n
    # Save clears it: the edits are in a file now
    tab.save()
    assert ed.dirty is False
    dialogs.seen.clear()
    tab.redetect()
    assert not [d for d in dialogs.seen if d[0] == "question"]
    qtbot.waitUntil(lambda: not tab.busy, timeout=TIMEOUT)


def test_f8_scale_bar_change_counts_as_an_edit(window, qtbot, dialogs, tmp_path, neutral_plate_tif):
    tab, ed = _editor_on(window, qtbot, dialogs, tmp_path, neutral_plate_tif)
    ed.scale_combo.setCurrentIndex(3)
    assert ed.dirty is True


def test_f20_calibration_is_undoable_and_updates_the_dish_box(window, qtbot, dialogs, tmp_path,
                                                              neutral_plate_tif):
    tab, ed = _editor_on(window, qtbot, dialogs, tmp_path, neutral_plate_tif)
    ppm0 = ed.ppm
    pl = dict(ed.plate)
    calls = []
    orig = ed.set_plate_mm
    ed.set_plate_mm = lambda mm: calls.append(mm) or orig(mm)
    ed._apply_dish(pl["center"][0], pl["center"][1], pl["radius"], diam_mm=85.0)
    assert tab.plate.value() == pytest.approx(85.0)            # the Dish box follows
    assert calls == []                                         # ... without a re-scale loop
    assert ed.ppm == pytest.approx(85.0 / (2 * pl["radius"]))
    assert tab._metrics["cal"].text().startswith("%.4f" % ed.ppm)
    ed._undo_last()
    assert ed.ppm == pytest.approx(ppm0) and tab.plate.value() == pytest.approx(90.0, abs=0.01)
    ed._redo_last()
    assert ed.ppm == pytest.approx(85.0 / (2 * pl["radius"])) and tab.plate.value() == pytest.approx(85.0)
    # the ruler: same undo stack
    ed._apply_ruler_scale(0.05)
    assert ed.ppm == 0.05
    ed._undo_last()
    assert ed.ppm == pytest.approx(85.0 / (2 * pl["radius"]))
    # the two-point ruler tool has a toolbar button
    from app.plaque_canvas import TOOL_SCALE
    ed._btns[TOOL_SCALE].click()
    assert ed.tool == TOOL_SCALE and ed._btns[TOOL_SCALE].text() == "Ruler"


def test_f25_ctrl_z_undoes_one_step_and_ctrl_shift_z_redoes(window, qtbot, dialogs, tmp_path,
                                                            neutral_plate_tif):
    tab, ed = _editor_on(window, qtbot, dialogs, tmp_path, neutral_plate_tif)
    n = len(ed.plaques)
    ed._add_circle(QPointF(150, 150), 10)
    ed._add_circle(QPointF(150, 750), 10)
    assert len(ed.plaques) == n + 2
    ed.view.setFocus()
    QTest.keyClick(ed.view, Qt.Key_Z, Qt.ControlModifier)
    assert len(ed.plaques) == n + 1                          # exactly one step
    QTest.keyClick(ed.view, Qt.Key_Z, Qt.ControlModifier | Qt.ShiftModifier)
    assert len(ed.plaques) == n + 2
    QTest.keyClick(ed.view, Qt.Key_U)                        # 'u' still works
    assert len(ed.plaques) == n + 1


def test_f20_detect_area_uses_the_results_engine_and_the_status_says_so(
        window, qtbot, dialogs, tmp_path, neutral_plate_tif, monkeypatch):
    tab, ed = _editor_on(window, qtbot, dialogs, tmp_path, neutral_plate_tif, mode="published")
    seen = []

    def fake(orig_bgr, roi, **kw):
        seen.append(kw)
        return [dict(_circle(150, 150, 10, "region"))]
    monkeypatch.setattr(engine_api, "detect_region", fake)
    n = len(ed.plaques)
    ed._detect_region((100, 100, 100, 100))
    assert seen == [{"sensitive": False, "small": False, "published": True}]
    msg = window.statusBar().currentMessage()
    assert msg == "%d detected + 1 detect-area · Published (edited)" % n
    assert "Published gates" in ed.hint.text()


def test_f25_small_state_slips(window, qtbot, dialogs, tmp_path, neutral_plate_tif):
    tab, ed = _editor_on(window, qtbot, dialogs, tmp_path, neutral_plate_tif)
    # "erased an auto plaque" grammar, in plain words
    ed._erase_at(QPointF(*ed.plaques[0]["center"]))
    assert ed.hint.text().startswith("erased 1 plaque (auto-detected)")
    # no dish label written over the image; the facts are in the line above it
    texts = [it.text() for it in ed.scene.items() if isinstance(it, QGraphicsSimpleTextItem)]
    assert not [t for t in texts if "dish" in t]
    assert "dish Ø" in ed.hint.text()
    # Watershed is unticked (not just greyed) under Published
    tab.mode.setCurrentIndex(_mode_index("current"))
    tab.watershed.setChecked(True)
    tab.mode.setCurrentIndex(_mode_index("published"))
    assert not tab.watershed.isChecked() and not tab.watershed.isEnabled()
    # engine changed without a new detection: the tab says the result is stale
    assert tab.stale_label.isVisibleTo(tab) and "Re-detect" in tab.stale_label.text()
    tab.mode.setCurrentIndex(_mode_index("current"))
    assert not tab.stale_label.isVisibleTo(tab)
    tab.watershed.setChecked(True)
    assert tab.stale_label.isVisibleTo(tab)


# =========================================================================== F15
def test_f15_failed_open_keeps_the_image_on_screen(window, qtbot, dialogs, tmp_path, neutral_plate_tif,
                                                   monkeypatch):
    tab, ed = _editor_on(window, qtbot, dialogs, tmp_path, neutral_plate_tif)
    a = tab.image_path
    # B through an engine that is not installed
    monkeypatch.setattr(engine_api, "precise_available", lambda: (False, "no torch"))
    b = _copy(neutral_plate_tif, tmp_path / "B")
    tab.mode.setCurrentIndex(_mode_index("precise"))
    dialogs.open_path = b
    tab.open_btn.click()
    assert tab.image_path == a and tab.editor is ed
    assert "was NOT opened" in window.statusBar().currentMessage()
    # a corrupt file
    bad = tmp_path / "bad.tif"
    bad.write_bytes(b"not an image")
    tab.mode.setCurrentIndex(_mode_index("current"))
    dialogs.open_path = str(bad)
    tab.open_btn.click()
    qtbot.waitUntil(lambda: not tab.busy, timeout=TIMEOUT)
    assert tab.image_path == a and tab.editor is ed
    assert [d[0] for d in dialogs.seen if d[0] == "critical"]
    # Save writes A's results into A's folder
    tab.save()
    assert os.path.exists(os.path.join(os.path.dirname(a), "out", "data-green-neutral_plate.csv"))


def test_f15_precise_marked_not_installed(qtbot, monkeypatch, dialogs):
    monkeypatch.setattr(engine_api, "precise_available", lambda: (False, "no torch"))
    win = appui.MainWindow()
    qtbot.addWidget(win)
    tab = win.measure_tab
    i = _mode_index("precise")
    assert tab.mode.itemText(i).endswith("(not installed)")
    assert tab.mode.currentIndex() != i


# =========================================================================== F14
def test_f14_no_mm_scale_shows_pixels_and_says_why(window, qtbot, dialogs, tmp_path, neutral_plate_tif):
    tab, ed = _editor_on(window, qtbot, dialogs, tmp_path, neutral_plate_tif)
    # no dish outline on this image (as on a cropped lawn): no mm scale
    ed.plate = None
    ed.ppm = None
    ed._sync_det()
    tab.refresh_table()
    assert tab._metric_caps["median"].text() == "MEDIAN Ø (px)"
    px = pd.to_numeric(tab.model.dataframe()["DIAMETER_PXL"]).median()
    assert tab._metrics["median"].text() == "%.1f" % px
    # CT-R2 (coordinator B): the Batch Problem column's words
    assert ("No dish found: sizes in px only (check that the whole dish is in the frame). Or use "
            "Set plate or the Ruler to calibrate.") in tab.flag_label.text()
    shown = _screen_df(tab)
    assert set(shown["DIAMETER_MM"]) == {"—"} and set(shown["AREA_MM2"]) == {"—"}
    # the 85 button explains why nothing happened
    tab._quick_dish(85)
    assert "nothing to rescale" in window.statusBar().currentMessage()
    assert ed.ppm is None


# =========================================================================== F16
def test_f16_add_and_draw_guard_the_image(window, qtbot, dialogs, tmp_path, neutral_plate_tif):
    tab, ed = _editor_on(window, qtbot, dialogs, tmp_path, neutral_plate_tif)
    H, W = ed.orig_bgr.shape[:2]
    n = len(ed.plaques)
    ed._add_circle(QPointF(-40, 300), 20)                      # centre off the image
    assert len(ed.plaques) == n and "outside the image" in ed.hint.text()
    ed._add_circle(QPointF(5, 300), 20)                        # crosses the left edge
    p = [q for q in ed.plaques if q["source"] == "manual"][0]
    full = math.pi * 20 * 20
    assert 0.45 * full < p["area_pxl"] < 0.75 * full           # only the part on the image
    assert "only the part on the image" in ed.hint.text()
    # a figure-eight is refused, a plain loop accepted
    t = np.linspace(0, 2 * np.pi, 60)
    eight = [QPointF(200 + 60 * np.sin(a), 200 + 30 * np.sin(2 * a)) for a in t]
    m = len(ed.plaques)
    ed._add_freehand(eight)
    assert len(ed.plaques) == m and "crosses itself" in ed.hint.text()
    loop = [QPointF(200 + 30 * np.cos(a), 700 + 30 * np.sin(a)) for a in t]
    ed._add_freehand(loop)
    assert len(ed.plaques) == m + 1
    tip = widgets.COLUMN_TOOLTIPS["TURBIDITY_REL"]
    assert "1 − |plaque − lawn|" in tip and "0 = the clearest plaque" in tip and "÷ surrounding lawn" not in tip


# =========================================================================== F10 / F11
def test_f10_fit_on_first_layout_and_on_resize_until_the_user_zooms(window, qtbot, dialogs, tmp_path,
                                                                    neutral_plate_tif):
    tab, ed = _editor_on(window, qtbot, dialogs, tmp_path, neutral_plate_tif)
    qtbot.wait(100)

    def fit():
        vp = ed.view.viewport().rect()
        sr = ed.scene.sceneRect()
        return min(vp.width() / sr.width(), vp.height() / sr.height())
    assert ed.view.transform().m11() == pytest.approx(fit(), rel=0.03)
    window.resize(1600, 1000)
    qtbot.wait(150)
    assert ed.view.transform().m11() == pytest.approx(fit(), rel=0.03)
    ed.view.zoom_by(1.5)
    z = ed.view.transform().m11()
    window.resize(1320, 880)
    qtbot.wait(150)
    assert ed.view.transform().m11() == pytest.approx(z)      # the user's zoom is kept


def test_f11_hint_above_canvas_and_tab_fits_the_window(window, qtbot, dialogs, tmp_path, neutral_plate_tif):
    tab, ed = _editor_on(window, qtbot, dialogs, tmp_path, neutral_plate_tif)
    qtbot.wait(100)
    assert ed.hint.geometry().bottom() < ed.view.geometry().top()
    sa = window.tabs.widget(0)
    assert tab.height() <= sa.viewport().height() + 1           # no scrolling at 1320x880
    assert ed.view.height() >= 300
    # small window: the tab scrolls instead of piling widgets on each other
    window.resize(900, 600)
    qtbot.wait(200)
    lay = ed.layout()
    geo = [lay.itemAt(i).geometry() for i in range(lay.count())]
    for a, b in zip(geo, geo[1:]):
        assert a.bottom() < b.top()                            # toolbar, hint, view, key row stacked
    assert ed.view.height() >= ed.view.minimumHeight()


# =========================================================================== F24
def test_f24_qc_flag_is_explained_tinted_and_shown_second(window, qtbot, dialogs, tmp_path,
                                                          neutral_plate_tif):
    tab, ed = _editor_on(window, qtbot, dialogs, tmp_path, neutral_plate_tif)
    # a plaque on the image border gets EDGE
    ed._add_circle(QPointF(3, 450), 6)
    df = tab.model.dataframe()
    assert list(df.columns) == ["INDEX", "AREA_PXL", "DIAMETER_PXL", "AREA_MM2", "DIAMETER_MM",
                                "MEAN_GRAY", "TURBIDITY_REL", "CIRCULARITY", "OVERLAP", "SOURCE",
                                "QC_FLAG"]                     # CSV order unchanged
    qc = list(df.columns).index("QC_FLAG")
    assert tab.table.horizontalHeader().visualIndex(qc) == 1  # shown second on screen
    tip = tab.model.headerData(qc, Qt.Horizontal, Qt.ToolTipRole)
    for word in ("EDGE", "LARGE?", "MERGED?", "TINY", "OVERLAP", "LOW_CONF"):
        assert word in tip
    r = df.index[df["QC_FLAG"].str.contains("EDGE")][0]
    assert "border" in tab.model.data(tab.model.index(r, qc), Qt.ToolTipRole)
    assert tab.model.data(tab.model.index(r, 0), Qt.BackgroundRole) is not None
    ok = df.index[df["QC_FLAG"] == "OK"][0]
    assert tab.model.data(tab.model.index(ok, 0), Qt.BackgroundRole) is None
    csv = str(tmp_path / "t.csv")
    ed.export_csv(csv)
    assert list(pd.read_csv(csv).columns) == list(df.columns)
