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


# =========================================================================== N1
CMP_A = (("Plate_1", "T4_1"), ("Plate_11", "T4_10"))


@pytest.fixture(scope="module")
def cmp_folder(tmp_path_factory):
    """Two of the tester's work/cmpA plates (small Plate_1 as T4_1, Plate_11 as T4_10: 0
    plaques with the old Standard default) under phage names."""
    d = tmp_path_factory.mktemp("cmpA")
    for src, dst in CMP_A:
        shutil.copy(os.path.join(SMALL_PLATES, src + ".tif"), str(d / (dst + ".tif")))
    return d


@pytest.mark.parametrize("scale", ["auto", "standard", "small"])
def test_n1_compare_finds_the_plaques_batch_finds(cmp_folder, tmp_path, scale):
    """For every Plaque size, Compare's per-plate count AND n sized equal Batch's (engine
    Current), and its plaque list is Batch's, plaque for plaque (area and QC flag)."""
    b = batch_measure.batch_measure(str(cmp_folder), plate_mm=55, mode="current", scale=scale,
                                    out_dir=str(tmp_path / "b"))
    res = engine_api.run_compare(str(cmp_folder), plate_mm=55, scale=scale, group_by_prefix=True,
                                 dilution=1e6, volume_ul=100, out_dir=str(tmp_path / "c"))
    q = pd.read_csv(tmp_path / "c" / "qc.csv").set_index("PLATE")
    per = b["summary_df"].set_index("image")
    for _src, name in CMP_A:
        assert int(q.loc[name, "N_PLAQUES"]) == int(per.loc[name + ".tif", "n_plaques"])
        assert int(q.loc[name, "N_SIZED"]) == int(per.loc[name + ".tif", "n_sized"])
        assert q.loc[name, "PLAQUE_SIZE"] == scale
        assert q.loc[name, "PFU_PER_ML"] == pytest.approx(int(per.loc[name + ".tif", "n_plaques"]) * 1e7)
    allp = b["all_df"]
    df = res["df"]
    for _src, name in CMP_A:
        a = allp[allp["IMAGE"] == name + ".tif"]
        c = df[df["PLATE"] == name]
        assert list(c["AREA_PXL"].round(2)) == list(a["AREA_PXL"].round(2))
        assert list(c["DIAMETER_MM"]) == list(a["DIAMETER_MM"])
        assert list(c["QC_FLAG"]) == list(a["QC_FLAG"])
    meta = json.load(open(tmp_path / "c" / "run_metadata.json"))
    assert meta["args"]["plaque_size"] == scale


def test_n1_sizes_and_turbidity_leave_out_core_and_no_size(tmp_path):
    """CORE? / NO_SIZE rows count (N_PLAQUES) but stay out of the per-phage summary and plots."""
    df = pd.DataFrame({"PHAGE": ["T4"] * 4, "PLATE": ["T4_1"] * 4, "PLATE_INDEX": [1, 2, 3, 4],
                       "AREA_PXL": [1, 1, 1, 1], "DIAMETER_MM": [1.0, 2.0, 9.0, 9.0],
                       "MEAN_GRAY": [1, 1, 1, 1], "TRANSMITTANCE": [1.0, 2.0, 50.0, 50.0],
                       "OD": [""] * 4, "OD_LAWN": [""] * 4, "TURBIDITY": [""] * 4,
                       "CLARITY": [""] * 4, "QC_FLAG": ["OK", "EDGE", "CORE?", "SPLIT|NO_SIZE"]})
    s = ptb.summarise(df).iloc[0]
    assert s["N_PLAQUES"] == 4 and s["N_SIZED"] == 2 and s["TRANSMITTANCE_PLAQUE_MEAN"] == 1.5
    from matplotlib.axes import Axes
    seen = []
    real = Axes.boxplot
    import unittest.mock as _m
    with _m.patch.object(Axes, "boxplot", lambda self, x, **k: seen.append([len(v) for v in x]) or real(self, x, **k)):
        figs = ptb.write_plots(df, str(tmp_path), formats=("png",))
    assert figs and seen and all(n == [2] for n in seen)        # 2 sized plaques per box plot
    assert len(ptb.sized_rows(df)) == 2
    # the default (no QC_FLAG column) summary is exactly as before
    s0 = ptb.summarise(df.drop(columns=["QC_FLAG"])).iloc[0]
    assert "N_SIZED" not in s0.index and s0["TRANSMITTANCE_PLAQUE_MEAN"] == pytest.approx(25.75)


def test_n1_default_cli_path_has_no_new_columns(phage_folder, tmp_path):
    df = ptb.run_batch(str(phage_folder), "90", False, None, None, str(tmp_path), make_plots=False)
    assert list(df.columns) == ptb.PLAQUE_COLUMNS
    assert list(pd.read_csv(tmp_path / "plaques_all.csv").columns) == ptb.PLAQUE_COLUMNS
    q = pd.read_csv(tmp_path / "qc.csv")
    assert "N_SIZED" not in q.columns and "PLAQUE_SIZE" not in q.columns
    assert "plaque_size" not in json.load(open(tmp_path / "run_metadata.json"))["args"]


def test_n1_qc_note_never_passes_a_plate_with_no_plaques():
    q = pd.DataFrame({"PLATE": ["T4_1", "T4_10"], "N_PLAQUES": [46, 0], "DISH_FOUND": [True, True],
                      "ABSOLUTE_OD": [False, False], "POLARITY_OK": [True, True], "ILLUM_CV": ["", ""]})
    note = appui.compare_qc_note(q, titer=True, scale="standard",
                                 flags=["OK", "CORE?", "OK", "SPLIT|NO_SIZE"])
    assert "QC passed" not in note
    assert ("⚠ 0 plaques: T4_10. If this plate has plaques, run again with Plaque size Small "
            "(plaques under ~2.5 mm) or Auto (both scales), and check the Dish size.") in note
    assert ("Sizes and turbidity from 2 of 4 plaques (1 outlined at the dark centre only and 1 "
            "split piece whose size is not reliable are counted, and in the titer, but left out "
            "of the summaries and plots).") in note


def test_n1_compare_tab_has_the_plaque_size_box_and_a_sized_column(window, qtbot, cmp_folder, dialogs,
                                                                   monkeypatch, tmp_path):
    tab = _compare_tab(window)
    assert not hasattr(tab, "small")
    assert [tab.scale_box.itemData(i) for i in range(tab.scale_box.count())] == ["auto", "standard", "small"]
    assert tab.scale_box.scale() == engine_api.DEFAULT_PLAQUE_SIZE
    folder = tmp_path / "one"
    _copy(os.path.join(str(cmp_folder), "T4_1.tif"), folder)
    tab.folder["edit"].setText(str(folder))
    tab.plate.setValue(55)
    tab.scale_box.set_scale("auto")
    tab.run()
    qtbot.waitUntil(lambda: tab.run_btn.isEnabled(), timeout=TIMEOUT)
    assert not [d for d in dialogs.seen if d[0] == "critical"]
    hdr, rows = _table(tab.plate_table)
    assert hdr[:4] == ["Plate", "Phage", "Plaques", "Sized"]
    b = batch_measure.batch_measure(str(folder), plate_mm=55, out_dir=str(tmp_path / "b"))
    assert rows[0][2:4] == [str(b["summary_df"]["n_plaques"][0]), str(b["summary_df"]["n_sized"][0])]
    assert json.load(open(folder / "out_turbidity" / "run_metadata.json"))["args"]["plaque_size"] == "auto"


# =========================================================================== coordinator A
def test_one_default_plaque_size_for_every_tab_and_table(qtbot, monkeypatch, neutral_plate_tif, tmp_path):
    import re
    from app import validate
    monkeypatch.setattr(engine_api, "DEFAULT_PLAQUE_SIZE", "standard")
    win = appui.MainWindow()
    qtbot.addWidget(win)
    assert win.measure_tab.scale_box.scale() == "standard"
    assert _batch_tab(win).scale_box.scale() == "standard"
    assert _compare_tab(win).scale_box.scale() == "standard"
    seen = []
    real = engine_api.detect_single
    monkeypatch.setattr(engine_api, "detect_single", lambda *a, **k: seen.append(k.get("scale")) or real(*a, **k))
    folder = tmp_path / "p"
    _copy(neutral_plate_tif, folder)
    r = batch_measure.batch_measure(str(folder), plate_mm=90, mode="current", out_dir=str(tmp_path / "o"))
    assert seen[-1] == "standard"
    assert json.load(open(os.path.join(r["out_dir"], "run_metadata.json")))["settings"]["plaque_size"] == "standard"
    lab = tmp_path / "labels_neutral_plate.json"
    lab.write_text(json.dumps({"meta": {"image_path": str(folder / "neutral_plate.tif")},
                               "plaques": [{"x_px": 380, "y_px": 380, "r_px": 26}]}))
    seen.clear()
    validate.score_label_file(str(lab), mode="current")
    assert seen == ["standard"]
    # no other literal default: the mode tables carry no plaque size, the box reads the constant
    for f in ("app/batch_measure.py", "app/validate.py", "app/ui.py"):
        src = open(os.path.join(ROOT, f)).read()
        assert not re.search(r'["\']scale["\']\s*:\s*["\']auto["\']', src), f
        assert not re.search(r'["\']other["\']\s*:\s*["\']auto["\']', src), f


# =========================================================================== N2
def _sized_median(df):
    d = df[[plaque_qc.size_ok(f) for f in df["QC_FLAG"]]]
    return float(pd.to_numeric(d["DIAMETER_MM"]).median())


def test_n2_data_green_carries_qc_flags_and_gives_the_screen_median(window, qtbot, dialogs, tmp_path):
    """sample.tif, Current + Auto: data-green-sample.csv (Save results and Batch) ends with
    QC_FLAG, QC_REASON; the median over its size_ok rows is the median on screen and in
    per_plate.csv, before and after hand edits."""
    tab = window.measure_tab
    img = _copy(SAMPLE_TIF, tmp_path / "m")
    ed = _open(tab, qtbot, dialogs, img, mode="current", dish=100.0, scale="auto")
    tab.save()
    csv = os.path.join(ed.out_dir, "data-green-sample.csv")
    d = pd.read_csv(csv)
    assert list(d.columns) == ["INDEX_COL", "AREA_PXL", "DIAMETER_PXL", "AREA_MM2", "DIAMETER_MM",
                               "MEAN_GRAY", "TURBIDITY_REL", "SOURCE", "QC_FLAG", "QC_REASON"]
    screen = ed.table(with_reason=True)
    assert list(d["QC_FLAG"]) == list(screen["QC_FLAG"])
    assert list(d["QC_REASON"].fillna("")) == list(screen["QC_REASON"].fillna(""))
    assert list(d["DIAMETER_MM"]) == list(screen["DIAMETER_MM"])
    med = _sized_median(d)
    assert tab._metrics["median"].text() == "%.2f" % med
    assert not all(plaque_qc.size_ok(f) for f in d["QC_FLAG"])       # the rule matters here

    b = batch_measure.batch_measure(os.path.dirname(img), plate_mm=100, scale="auto",
                                    out_dir=str(tmp_path / "b"))
    assert b["summary_df"]["median_diam_mm"][0] == pytest.approx(med)
    bd = pd.read_csv(tmp_path / "b" / "sample" / "data-green-sample.csv")
    assert list(bd.columns)[-2:] == ["QC_FLAG", "QC_REASON"] and list(bd["QC_FLAG"]) == list(d["QC_FLAG"])

    # hand edits: erase two plaques, add a circle, save again
    for p in list(ed.plaques[:2]):
        ed._erase_at(QPointF(*p["center"]))
    ed._add_circle(QPointF(600.0, 600.0), 20.0)
    tab.save()
    d2 = pd.read_csv(csv)
    assert len(d2) == len(d) - 1
    assert list(d2["QC_FLAG"]) == list(ed.table()["QC_FLAG"])
    assert tab._metrics["median"].text() == "%.2f" % _sized_median(d2)


# =========================================================================== N3 + N9 + N5
@pytest.fixture
def sample_editor(window, qtbot, dialogs, tmp_path):
    img = _copy(SAMPLE_TIF, tmp_path / "s")
    ed = _open(window.measure_tab, qtbot, dialogs, img, mode="current", dish=100.0, scale="auto")
    return window.measure_tab, ed


def _idx(ed, flag):
    return [i for i, p in enumerate(ed.plaques) if plaque_qc.has_flag(p.get("qc_flag"), flag)]


def test_n3_size_not_used_has_its_own_outline_label_and_key_on_canvas_and_export(sample_editor, monkeypatch):
    tab, ed = sample_editor
    table = ed.table()
    assert [p["qc_flag"] for p in ed.plaques] == list(table["QC_FLAG"])
    core, nos = _idx(ed, "CORE?"), [i for i in _idx(ed, "NO_SIZE") if i not in _idx(ed, "CORE?")]
    assert len(core) == 10 and len(nos) == 10
    ed.set_label_mode("numbers + mm")
    texts = [t for t, _s, _b in ed._label_layout()]
    assert texts[core[0]] == "%d (core)" % (core[0] + 1)
    assert texts[nos[0]] == "%d (split)" % (nos[0] + 1)
    ok = [i for i in range(len(texts)) if i not in core + nos][0]
    assert texts[ok].endswith(" mm")
    # canvas outline: dotted for the size-not-used plaques only
    from PySide6.QtWidgets import QAbstractGraphicsShapeItem, QGraphicsSimpleTextItem
    shapes = [it for it in ed._overlay if isinstance(it, QAbstractGraphicsShapeItem)
              and not isinstance(it, QGraphicsSimpleTextItem)]
    assert shapes[core[0]].pen().style() == Qt.DotLine and shapes[nos[0]].pen().style() == Qt.DotLine
    assert shapes[ok].pen().style() != Qt.DotLine
    # key: canvas == export, with the class and both reasons
    key = ed.legend_key()
    nosize = [e for e in key["entries"] if e["label"].startswith("size not used")]
    assert nosize and nosize[0]["label"] == ("size not used: outlined at the dark centre only / "
                                             "split piece too overlapped")
    assert nosize[0]["linestyle"] == ":"
    assert "size not used: outlined at the dark centre only / split piece too overlapped (" in ed.key_text.text()
    assert "dotted line" in ed.key_text.text()
    drawn = []
    real = pgui._draw_texts
    monkeypatch.setattr(pgui, "_draw_texts", lambda img, items: drawn.extend(it[0] for it in items) or real(img, items))
    ed.key_cb.setChecked(True)
    img = pgui.annotate_plaques(ed.orig_bgr, [dict(p) for p in ed.plaques], ed.ppm,
                                labels="numbers + mm", **ed._figure_kwargs())
    assert all(t in drawn for t in texts)
    assert "%d (core)" % (core[0] + 1) in drawn and "%d (split)" % (nos[0] + 1) in drawn
    patch = pgui.key_image_for(img.shape, key)
    assert np.array_equal(_key_region(img, patch), patch)
    # the export draws the dotted outline in the class colour (cyan), not the auto green
    rgb = pgui.PLAQUE_CLASSES["nosize"][1]
    img = pgui.annotate_plaques(ed.orig_bgr, [dict(p) for p in ed.plaques], ed.ppm, labels="none",
                                plate=ed.plate)

    def has(i, bgr):
        x0, y0, x1, y1 = [int(round(v)) for v in pgui.plaque_bbox(ed.plaques[i])]
        roi = img[max(0, y0 - 4):y1 + 5, max(0, x0 - 4):x1 + 5].astype(int)
        return bool((np.abs(roi - np.array(bgr)).sum(axis=2) < 12).any())
    assert has(core[0], (rgb[2], rgb[1], rgb[0])) and has(nos[0], (rgb[2], rgb[1], rgb[0]))
    assert not has(ok, (rgb[2], rgb[1], rgb[0]))


def test_n5_n9_flag_line_and_sources_follow_the_current_plaques(sample_editor, tmp_path):
    import re
    tab, ed = sample_editor
    c0 = pgui.source_counts_now(ed.plaques)
    flag = tab.flag_label.text()
    m = re.search(r"Edges: (\d+) auto \(standard pass\), (\d+) split, (\d+) small "
                  r"\(10 of them outlined at the dark centre only\)\.", flag)
    assert m and [int(g) for g in m.groups()] == [c0["auto"], c0["split"], c0["small"]]
    assert sum(c0[k] for k in ("auto", "split", "standard-relaxed", "small")) == len(ed.plaques)
    # edit: erase one auto plaque, add a circle -> the line and the metadata follow
    a = next(p for p in ed.plaques if p["source"] == "auto")
    ed._erase_at(QPointF(*a["center"]))
    ed._add_circle(QPointF(400.0, 1000.0), 15.0)
    flag = tab.flag_label.text()
    assert "Edges: %d auto (standard pass)" % (c0["auto"] - 1) in flag
    assert "1 manual (added by hand)" in flag
    tab.save()
    meta = json.load(open(os.path.join(ed.out_dir, "run_metadata.json")))
    src = meta["images"][0]["sources"]
    assert src["auto"] == c0["auto"] - 1 and src["manual"] == 1 and src["core"] == 10


def test_n5_singular_grammar_in_the_sizes_sentence(sample_editor):
    tab, ed = sample_editor
    drop = _idx(ed, "CORE?") + [i for i in _idx(ed, "NO_SIZE") if i not in _idx(ed, "CORE?")][1:]
    ed.selected = set(ed.plaques[i]["_uid"] for i in drop)
    ed._remove_selected()
    n = len(ed.plaques)
    assert ("Sizes from %d of %d plaques (1 split piece whose size is not reliable is counted but "
            "left out of the size summary)." % (n - 1, n)) in tab.flag_label.text()


# =========================================================================== N4
def test_n4_drawing_the_halo_of_a_core_plaque_replaces_it(sample_editor):
    tab, ed = sample_editor
    i = _idx(ed, "CORE?")[0]
    core = ed.plaques[i]
    n0, uid = len(ed.plaques), core["_uid"]
    x0, y0, x1, y1 = pgui.plaque_bbox(core)
    r = 1.6 * max(x1 - x0, y1 - y0) / 2.0          # a circle round its (larger) halo
    ed._add_circle(QPointF(*core["center"]), r)
    assert len(ed.plaques) == n0                     # the count does not grow
    assert uid not in [p["_uid"] for p in ed.plaques]
    assert "replaced plaque %d (dark centre only) with your outline" % (i + 1) in ed.hint.text()
    new = [p for p in ed.plaques if p["source"] == "manual"]
    assert len(new) == 1 and not plaque_qc.has_flag(new[0]["qc_flag"], "NESTED")
    ed._undo_last()                                  # ONE step restores both
    assert len(ed.plaques) == n0 and uid in [p["_uid"] for p in ed.plaques]
    assert not [p for p in ed.plaques if p["source"] == "manual"]


def test_n4_a_circle_round_an_ordinary_plaque_does_not_remove_it(sample_editor):
    tab, ed = sample_editor
    ok = next(p for p in ed.plaques if p["qc_flag"] == "OK")
    n0 = len(ed.plaques)
    ed._add_circle(QPointF(*ok["center"]), 60.0)
    assert len(ed.plaques) == n0 + 1 and ok["_uid"] in [p["_uid"] for p in ed.plaques]


# =========================================================================== N6 N7 N13 N12
def test_n6_dish_change_is_its_own_undo_step_and_the_hint_says_so(sample_editor, qtbot):
    tab, ed = sample_editor
    ppm100 = ed.ppm
    a = ed.plaques[0]
    ed._erase_at(QPointF(*a["center"]))              # a plaque edit ...
    n_after_erase = len(ed.plaques)
    tab.plate.setValue(8)                            # ... then typing "85" in the Dish box
    tab.plate.setValue(85)
    assert ed.ppm == pytest.approx(ppm100 * 0.85)
    ed._undo_last()                                  # undoes the Dish change only (one step)
    assert ed.ppm == pytest.approx(ppm100) and len(ed.plaques) == n_after_erase
    assert "undid the Dish size change (100 mm → 85 mm)" in ed.hint.text()
    assert tab.plate.value() == pytest.approx(100.0)
    ed._undo_last()                                  # then the erase, calibration untouched
    assert ed.ppm == pytest.approx(ppm100) and len(ed.plaques) == n_after_erase + 1
    assert "undid the erase of plaque 1" in ed.hint.text()


def test_n7_calibration_source_is_the_last_one_used(sample_editor, dialogs):
    tab, ed = sample_editor
    dialogs.double = (10.0, True)
    ed._set_tool("scale")
    ed._scale_click(QPointF(100, 100)); ed._scale_click(QPointF(200, 100))
    assert ed.export_state()["edits"]["calibration"] == "ruler"
    tab.plate.setValue(90)
    assert ed.export_state()["edits"]["calibration"] == "dish"
    tab.save()
    meta = json.load(open(os.path.join(ed.out_dir, "run_metadata.json")))
    assert meta["images"][0]["edits"]["calibration"] == "dish"


def test_n13_undo_after_save_marks_the_result_unsaved(sample_editor):
    tab, ed = sample_editor
    ed._erase_at(QPointF(*ed.plaques[0]["center"]))
    tab.save()
    assert not ed.dirty
    ed._undo_last()
    assert ed.dirty and "unsaved edits" in ed.hint.text()
    tab.save()
    ed._redo_last()
    assert ed.dirty


def test_n12_only_the_pointer_grabs_the_scale_bar_and_an_empty_detect_area_is_no_edit(sample_editor, monkeypatch):
    tab, ed = sample_editor
    g = ed._sb_g
    start = (g["x0"] + g["length_px"] / 2.0, g["y0"] + g["thickness"] / 2.0)
    assert ed._sb_hit(QPointF(*start))
    monkeypatch.setattr(engine_api, "detect_region", lambda *a, **k: [])
    from PySide6.QtCore import QEvent, QPoint
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    def drag(a, b):
        vp = ed.view.viewport()
        pa, pb = ed.view.mapFromScene(QPointF(*a)), ed.view.mapFromScene(QPointF(*b))
        for typ, pt, btns in ((QEvent.MouseButtonPress, pa, Qt.LeftButton),
                              (QEvent.MouseMove, pb, Qt.LeftButton),
                              (QEvent.MouseButtonRelease, pb, Qt.NoButton)):
            QApplication.sendEvent(vp, QMouseEvent(typ, QPointF(pt), QPointF(vp.mapToGlobal(pt)),
                                                   Qt.LeftButton, btns, Qt.NoModifier))
    before = (g["x0"], g["y0"])
    ed._set_tool("region")
    drag(start, (start[0] - 150, start[1] - 150))
    assert (ed._sb_g["x0"], ed._sb_g["y0"]) == before and ed._scalebar_anchor is None
    assert not ed.dirty and not ed.edited and "(edited)" not in tab._status_text()
    ed._set_tool("select")
    drag(start, (start[0] - 150, start[1] - 150))
    assert (ed._sb_g["x0"], ed._sb_g["y0"]) != before and ed.dirty


# =========================================================================== N11 N14
def test_n11_compare_and_batch_use_one_rule_for_sub_folders(window, qtbot, phage_folder, dialogs, tmp_path):
    old = phage_folder / "old"
    old.mkdir()
    shutil.copy(str(phage_folder / "T4_1.tif"), str(old / "T4_1.tif"))
    names = [os.path.basename(p) for p in engine_api.compare_images(str(phage_folder))]
    assert names == [os.path.basename(p) for p in batch_measure.find_images(str(phage_folder))]
    assert names == ["T4_1.tif", "T4_2.tif", "T7_1.tif"]
    assert batch_measure.unsearched_subfolders(str(phage_folder)) == ["old"]
    note = "1 sub-folder was not searched (old): only the images directly in the folder are measured."
    tab = _compare_tab(window)
    tab.folder["edit"].setText(str(phage_folder))
    tab.plate.setValue(90)
    tab.run()
    qtbot.waitUntil(lambda: tab.run_btn.isEnabled(), timeout=TIMEOUT)
    q = pd.read_csv(phage_folder / "out_turbidity" / "qc.csv")
    assert list(q["PLATE"]) == ["T4_1", "T4_2", "T7_1"]          # no "old__T4_1"
    assert note in tab.qc.text()
    b = _batch_tab(window)
    b.folder.setText(str(phage_folder))
    b._run()
    qtbot.waitUntil(lambda: b.run_btn.isEnabled(), timeout=TIMEOUT)
    assert note in b.status.text()


def test_n14_the_status_bar_message_belongs_to_its_tab(window, qtbot, dialogs, tmp_path, neutral_plate_tif):
    tab = window.measure_tab
    _open(tab, qtbot, dialogs, _copy(neutral_plate_tif, tmp_path / "m"))
    msg = window.statusBar().currentMessage()
    assert "detected" in msg
    window.tabs.setCurrentIndex(1); qtbot.wait(30)
    assert window.statusBar().currentMessage() == ""
    window.tabs.setCurrentIndex(2); qtbot.wait(30)
    assert window.statusBar().currentMessage() == ""
    window.tabs.setCurrentIndex(0); qtbot.wait(30)
    assert window.statusBar().currentMessage() == msg


def test_n14_batch_problem_column_is_visible_at_1024(window, qtbot, dialogs, tmp_path, neutral_plate_tif):
    window.resize(1024, 700)
    folder = tmp_path / "b"
    _copy(neutral_plate_tif, folder)
    (folder / "broken.tif").write_bytes(b"not an image")
    b = _batch_tab(window)
    window.tabs.setCurrentIndex(1)
    b.folder.setText(str(folder))
    b._run()
    qtbot.waitUntil(lambda: b.run_btn.isEnabled(), timeout=TIMEOUT)
    qtbot.wait(50)
    hdr, rows = _table(b.table)
    assert hdr[:2] == ["Image", "Problem"]
    i = hdr.index("Problem")
    x = b.table.columnViewportPosition(i)
    assert 0 <= x and x + 60 < b.table.viewport().width()
    assert rows[0][1].startswith("not a readable image")
    assert list(pd.read_csv(folder / "out_batch" / "per_plate.csv").columns)[-1] == "error"


# =========================================================================== N10
def _wheel(widget, delta=-120, mods=Qt.NoModifier):
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtWidgets import QApplication
    vp = widget.viewport()
    c = QPointF(vp.width() / 2.0, vp.height() / 2.0)
    ev = QWheelEvent(c, QPointF(vp.mapToGlobal(c.toPoint())), QPoint(0, 0), QPoint(0, delta),
                     Qt.NoButton, mods, Qt.NoScrollPhase, False)
    QApplication.sendEvent(vp, ev)


def test_n10_small_windows_keep_the_key_row_and_the_wheel_scrolls_the_page(window, qtbot, dialogs, tmp_path):
    tab = window.measure_tab
    ed = _open(tab, qtbot, dialogs, _copy(SAMPLE_TIF, tmp_path / "s"), dish=100.0, scale="auto")
    page = window.tabs.widget(0)
    window.resize(1320, 880); qtbot.wait(200)
    assert not tab._params_collapsed and tab.plate.isVisible()
    window.resize(1024, 700); qtbot.wait(300)
    # the parameter rows fold into one line, and the legend-key row is on screen
    assert tab._params_collapsed and tab.params_summary.isVisible() and not tab.plate.isVisible()
    assert "sample.tif" in tab.params_summary.text() and "Dish 100 mm" in tab.params_summary.text()
    assert tab.open_btn.isVisible() and tab.save_btn.isVisible()
    kr = ed.key_cb
    bottom = kr.mapTo(page.viewport(), kr.rect().bottomLeft()).y()
    assert page.verticalScrollBar().maximum() == 0 and bottom <= page.viewport().height()
    window.resize(900, 600); qtbot.wait(300)
    sb = page.verticalScrollBar()
    assert sb.maximum() > 0 and ed.view.height() >= 170
    # wheel over the image scrolls the page (the image does not have the focus) ...
    window.activateWindow(); tab.open_btn.setFocus()
    sb.setValue(0)
    z = ed.view.transform().m11()
    _wheel(ed.view)
    assert sb.value() > 0 and ed.view.transform().m11() == pytest.approx(z)
    # ... and zooms with Ctrl held
    _wheel(ed.view, delta=120, mods=Qt.ControlModifier)
    assert ed.view.transform().m11() > z
    assert "hold Ctrl to zoom" in ed.hint.toolTip()
    # the user's own choice wins over the window height
    tab.params_toggle.click()
    assert not tab._params_collapsed and tab.plate.isVisible()
    window.resize(880, 590); qtbot.wait(100)
    assert not tab._params_collapsed


# =========================================================================== coordinator B + C
@pytest.fixture(scope="module")
def cropped_sample(tmp_path_factory):
    img = cv2.imread(SAMPLE_TIF)
    h, w = img.shape[:2]
    dy, dx = int(round(0.03 * h)), int(round(0.03 * w))
    d = tmp_path_factory.mktemp("crop")
    p = str(d / "sample_crop3.png")
    cv2.imwrite(p, img[dy:h - dy, dx:w - dx])
    return p


def test_b_no_dish_no_millimetres_in_batch_and_measure(cropped_sample, tmp_path, window, qtbot, dialogs):
    r = batch_measure.batch_measure(os.path.dirname(cropped_sample), plate_mm=100,
                                    out_dir=str(tmp_path / "o"))
    row = pd.read_csv(tmp_path / "o" / "per_plate.csv").iloc[0]
    assert row["n_plaques"] > 0 and pd.isna(row["mm_per_px"])
    assert pd.isna(row["median_diam_mm"]) and pd.isna(row["mean_diam_mm"])
    assert row["error"] == plaque_qc.NO_DISH_WARNING
    assert r["errors"] == []                                   # measured: not a failure
    b = _batch_tab(window)
    b._done(r)
    hdr, rows = _table(b.table)
    assert rows[0][hdr.index("Median (mm)")] == "" and rows[0][hdr.index("Problem")] == row["error"]
    _open(window.measure_tab, qtbot, dialogs, cropped_sample, dish=100.0, scale="auto")
    flag = window.measure_tab.flag_label.text()
    assert flag.count(plaque_qc.NO_DISH_WARNING) == 1       # said once


def test_c_per_plate_counts_add_up(tmp_path):
    folder = tmp_path / "s"
    _copy(SAMPLE_TIF, folder)
    r = batch_measure.batch_measure(str(folder), plate_mm=100, scale="auto", out_dir=str(tmp_path / "o"))
    row = pd.read_csv(tmp_path / "o" / "per_plate.csv").iloc[0]
    cols = list(pd.read_csv(tmp_path / "o" / "per_plate.csv").columns)
    assert cols.index("n_no_size") == cols.index("n_core") + 1
    assert (row["n_plaques"], row["n_sized"], row["n_core"], row["n_no_size"]) == (41, 21, 10, 10)
    assert row["n_plaques"] == row["n_sized"] + row["n_core"] + row["n_no_size"]
    assert "n_no_size" in appui.BATCH_COLUMNS


def test_n7_a_hand_drawn_rim_stays_a_hand_calibration_after_the_dish_box(sample_editor, dialogs):
    tab, ed = sample_editor
    dialogs.double = (90.0, True)
    cx, cy = ed.plate["center"]; r = ed.plate["radius"]
    ed._set_tool("dish")
    for a in (0.0, 2.0, 4.0):
        ed._dish_click(QPointF(cx + r * math.cos(a), cy + r * math.sin(a)))
    assert ed.export_state()["edits"]["calibration"] == "set plate" and ed.edited
    tab.plate.setValue(85)
    assert ed.export_state()["edits"]["calibration"] == "set plate" and ed.edited


# =========================================================================== merged detection work
def test_plate_warnings_reach_measure_batch_metadata_and_compare(window, qtbot, dialogs, tmp_path, monkeypatch):
    """One call (engine_api.plate_warnings -> plaque_qc.plate_warnings) for every tab. The
    bundled sample.tif (largest outline 82 px here) gives no warning; at 1.6x its largest
    outline passes 100 px and the large-plaque warning appears."""
    assert engine_api.detect_single(SAMPLE_TIF, plate_mm=100, scale="auto")["plate_warnings"] == []
    folder = tmp_path / "s"
    folder.mkdir()
    src = cv2.imread(SAMPLE_TIF)
    img = str(folder / "sample.png")
    cv2.imwrite(img, cv2.resize(src, None, fx=1.6, fy=1.6, interpolation=cv2.INTER_CUBIC))
    det = engine_api.detect_single(img, plate_mm=100, scale="auto")
    w = det["plate_warnings"]
    assert w and any(x.startswith("Plaques wider than about 135 px") for x in w)
    calls = []
    real = plaque_qc.plate_warnings
    monkeypatch.setattr(plaque_qc, "plate_warnings", lambda *a, **k: calls.append(1) or real(*a, **k))
    # Measure flag line (wrapped label)
    tab = window.measure_tab
    _open(tab, qtbot, dialogs, img, dish=100.0, scale="auto")
    assert all(("⚠ " + x) in tab.flag_label.text() for x in w) and tab.flag_label.wordWrap()
    # Batch: Notes column + run_metadata.json
    r = batch_measure.batch_measure(str(folder), plate_mm=100, scale="auto", out_dir=str(tmp_path / "b"))
    per = pd.read_csv(tmp_path / "b" / "per_plate.csv")
    assert per["notes"][0] == "  ".join(w)
    meta = json.load(open(tmp_path / "b" / "run_metadata.json"))
    assert meta["images"][0]["plate_warnings"] == w
    b = _batch_tab(window); b._done(r)
    hdr, rows = _table(b.table)
    assert hdr[1] == "Notes" and rows[0][1] == "  ".join(w)
    # Compare: QC note and run_metadata.json
    res = engine_api.run_compare(str(folder), plate_mm=100, scale="auto", out_dir=str(tmp_path / "c"))
    assert res["plate_warnings"] == {"sample": w}
    assert json.load(open(tmp_path / "c" / "run_metadata.json"))["plate_warnings"] == {"sample": w}
    ct = _compare_tab(window)
    ct._last_df = res["df"]
    ct._load_tables(str(tmp_path / "c"))
    assert all(("⚠ sample: " + x) in ct.qc.text() for x in w)
    assert calls                                       # every tab went through the one call


def test_no_dish_warning_comes_after_the_embedded_scale_fallback(cropped_sample, tmp_path, monkeypatch):
    import plate_crop
    d = engine_api.detect_single(cropped_sample, plate_mm=100, scale="auto")
    assert d["pxl_per_mm"] is None and plaque_qc.NO_DISH_WARNING in d["dish_warnings"]
    monkeypatch.setattr(plate_crop, "read_mm_per_px", lambda path: 0.05)
    d2 = engine_api.detect_single(cropped_sample, plate_mm=100, scale="auto")
    assert d2["pxl_per_mm"] == 0.05
    assert plaque_qc.NO_DISH_WARNING not in d2["dish_warnings"]
    assert engine_api.EMBEDDED_SCALE_NOTE in d2["dish_warnings"]
    assert engine_api.EMBEDDED_SCALE_NOTE == "No dish found: the scale embedded in the image file is used."
