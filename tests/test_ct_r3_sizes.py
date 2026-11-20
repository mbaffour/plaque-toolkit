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


# =========================================================================== F2
def test_f2_small_tooltip_says_what_the_apps_small_is_on_every_tab(window):
    from PySide6.QtCore import Qt
    want = ("The small-plaque pass, with the dish taken from the standard pass and plaques outlined "
            "twice counted once; the command line's -small differs in both.")
    boxes = [window.measure_tab.scale_box, _tab(window, "Batch").scale_box,
             _tab(window, "Compare").scale_box]
    for box in boxes:
        box.set_engine("current")
        box.set_scale("small")
        assert box.toolTip().startswith("Plaque size. " + want)
        assert box.itemData(box.findData("small"), Qt.ToolTipRole).startswith(want)
        assert "(the command line's -small)" not in box.toolTip()
    # Published's Small IS the command line's --published -small (one pass, its own dish)
    box = window.measure_tab.scale_box
    box.set_engine("published"); box.set_scale("small")
    assert "exactly the command line's --published -small" in box.toolTip()
    assert "differs" not in box.toolTip()
    box.set_engine("current")
    assert box.scale() == "small" and box.toolTip().startswith("Plaque size. " + want)


# =========================================================================== F5
def _beside(fig, img_shape, patch):
    """The key region of a figure whose plate image had ``img_shape``."""
    x, y = pgui.key_origin(img_shape, patch.shape)
    assert x >= img_shape[1] or y >= img_shape[0]             # outside the image
    return fig[y:y + patch.shape[0], x:x + patch.shape[1]]


@pytest.fixture(scope="module")
def sample_det():
    return engine_api.detect_single(SAMPLE_TIF, plate_mm=100, scale="auto")


def test_f5_measure_figure_key_sits_beside_the_image_and_covers_nothing(sample_det, window, qtbot, dialogs, tmp_path):
    det = sample_det
    orig, H, W = det["orig_bgr"], det["orig_bgr"].shape[0], det["orig_bgr"].shape[1]
    plaques = engine_api.reading_order(det["plaques"])
    off = pgui.annotate_plaques(orig, plaques, det["pxl_per_mm"], plate=det["plate"], key=False)
    on = pgui.annotate_plaques(orig, plaques, det["pxl_per_mm"], plate=det["plate"], key=True)
    assert off.shape == orig.shape and on.shape[1] >= W and on.shape[0] >= H
    assert on.shape[0] * on.shape[1] > H * W
    # the image part (outlines, every label, the scale bar) is EXACTLY the figure without a key
    np.testing.assert_array_equal(on[:H, :W], off)
    tagged = [dict(p) for p in plaques]
    pgui.tag_qc(tagged, orig, det["pxl_per_mm"], plate=det["plate"])
    patch = pgui.key_image_for(orig.shape, pgui.plate_key(tagged))
    np.testing.assert_array_equal(_beside(on, orig.shape, patch), patch)
    # the app's Measure figure: the same, and the canvas shows the key at that same place
    img = os.path.join(str(tmp_path / "m"), "sample.tif")
    os.makedirs(os.path.dirname(img)); shutil.copy(SAMPLE_TIF, img)
    ed = _open(window.measure_tab, qtbot, dialogs, img)
    ed.key_cb.setChecked(True)
    fig = cv2.imread(ed.export_figure(str(tmp_path / "with_key.png")))
    ed.key_cb.setChecked(False)
    fig0 = cv2.imread(ed.export_figure(str(tmp_path / "no_key.png")))
    np.testing.assert_array_equal(fig[:H, :W], fig0)
    patch = pgui.key_image_for(orig.shape, ed.legend_key())
    np.testing.assert_array_equal(_beside(fig, orig.shape, patch), patch)
    # the standalone key lists the same entries as the embedded one (one builder)
    from plaque_stats import legend_key
    assert legend_key.entries_signature(ed.legend_key()) == legend_key.entries_signature(pgui.plate_key(tagged))
    # the canvas: the scene grows to hold the key beside the image, and shrinks back
    ed.key_cb.setChecked(True)
    r = ed.scene.sceneRect()
    assert (r.width(), r.height()) == (fig.shape[1], fig.shape[0])
    x, y = pgui.key_origin(orig.shape, patch.shape)
    assert ed._key_rect[:2] == (x, y) and (x > W or y > H)
    ed.key_cb.setChecked(False)
    assert (ed.scene.sceneRect().width(), ed.scene.sceneRect().height()) == (W, H)
    # the side-by-side figure still builds with the key on
    ed.key_cb.setChecked(True)
    cmp = ed.export_comparison(str(tmp_path / "cmp.png"))
    assert cmp and cv2.imread(cmp).shape[1] >= 2 * W


def test_f5_batch_and_turbidity_overlays_keep_the_key_off_the_plate(tmp_path):
    import plaque_turbidity as ptb
    folder = tmp_path / "b"; folder.mkdir()
    shutil.copy(SAMPLE_TIF, str(folder / "sample.tif"))
    orig = cv2.imread(SAMPLE_TIF)
    H, W = orig.shape[:2]
    outs = {}
    for on in (False, True):
        res = batch_measure.batch_measure(str(folder), plate_mm=100, mode="current", scale="auto",
                                          out_dir=str(tmp_path / ("on" if on else "off")), key_on_figure=on)
        outs[on] = cv2.imread(os.path.join(res["out_dir"], "sample", "out_sample.tif"))
    assert outs[False].shape[:2] == (H, W) and outs[True].shape[0] * outs[True].shape[1] > H * W
    np.testing.assert_array_equal(outs[True][:H, :W], outs[False])
    det = engine_api.detect_single(SAMPLE_TIF, plate_mm=100, scale="auto")
    key = pgui.plate_key([dict(p, qc_flag=f) for p, f in zip(
        engine_api.reading_order(det["plaques"]),
        engine_api.measure_table(engine_api.reading_order(det["plaques"]), det["orig_bgr"],
                                 det["pxl_per_mm"], det["lawn_gray"], plate=det["plate"])["QC_FLAG"])])
    patch = pgui.key_image_for(orig.shape, key)
    np.testing.assert_array_equal(_beside(outs[True], orig.shape, patch), patch)
    # turbidity overlay (Compare): drawn once, re-drawn with and without the key
    recs = []
    cdir = tmp_path / "c"; cdir.mkdir(); shutil.copy(SAMPLE_TIF, str(cdir / "sample.tif"))
    ptb.run_batch(str(cdir), "100", False, None, None, str(tmp_path / "t"), make_plots=False,
                  key_on_figure=True, overlay_records=recs, scale="auto")
    with_key = cv2.imread(str(tmp_path / "t" / "overlay_sample.png"))
    ptb.redraw_overlays(recs, str(tmp_path / "t"), key_on_figure=False)
    no_key = cv2.imread(str(tmp_path / "t" / "overlay_sample.png"))
    assert no_key.shape[:2] == (H, W) and with_key.shape[0] * with_key.shape[1] > H * W
    np.testing.assert_array_equal(with_key[:H, :W], no_key)
    patch = pgui.key_image_for(orig.shape, ptb.overlay_key(recs[0]))
    np.testing.assert_array_equal(_beside(with_key, orig.shape, patch), patch)


# =========================================================================== F6 + Validate status
import math as _math   # noqa: E402

_PLAQUES = [(380, 380), (520, 400), (430, 540), (560, 550), (350, 500)]


def _label(path, img_name, img_path):
    mmpp = 90.0 / 760.0
    recs = [{"index": i + 1, "x_px": float(x), "y_px": float(y), "r_px": 26.0,
             "area_px": _math.pi * 26 ** 2, "diam_mm": round(52 * mmpp, 3), "source": "auto",
             "kind": "plaque"} for i, (x, y) in enumerate(_PLAQUES)]
    meta = {"image": img_name, "image_path": img_path, "mm_per_px": mmpp, "dish_diam_px": 760,
            "schema": "plaque-groundtruth-v1"}
    with open(str(path), "w") as fh:
        json.dump({"meta": meta, "plaques": recs}, fh)


def test_f6_validate_names_the_plaque_size_and_says_plainly_when_the_image_is_missing(neutral_plate_tif, tmp_path):
    from app import validate as V
    d = tmp_path / "labels"; d.mkdir()
    shutil.copy(neutral_plate_tif, str(d / "plate0.tif"))
    # the label names an image path from another computer: found by name in the folder
    _label(d / "labels_plate0.json", "plate0.tif", r"C:\Users\x\Downloads\plate0.tif")
    _label(d / "labels_gone.json", "IMG_3907.jpeg", r"C:\Users\x\Downloads\IMG_3907.jpeg")
    res = V.validate(str(d), modes=("current", "published"))
    pp = res["per_plate_df"]
    assert list(pp.columns[:5]) == ["label_file", "image", "mode", "engine", "plaque_size"]
    ok = pp[pp["error"] == ""]
    assert list(ok["engine"]) == ["Current, Auto", "Published, Standard"]
    assert list(ok["plaque_size"]) == ["auto", "standard"]
    gone = pp[pp["label_file"] == "labels_gone.json"]
    assert set(gone["error"]) == {
        "FileNotFoundError: the image named in this label file (IMG_3907.jpeg) was not found next "
        "to it or in the chosen folder; put the photo there and run again"}
    assert list(gone["engine"]) == ["Current, Auto", "Published, Standard"]
    # a label file elsewhere: its image is also looked for in the chosen folder
    other = tmp_path / "elsewhere"; other.mkdir()
    _label(other / "labels_plate0.json", "plate0.tif", "/nowhere/plate0.tif")
    r = V.score_label_file(str(other / "labels_plate0.json"), mode="current", search_dir=str(d))
    assert r["image"] == "plate0.tif" and r["engine"] == "Current, Auto"
    # the bundled validation/ground_truth labels name photos that are not in the repository
    gt = os.path.join(ROOT, "validation", "ground_truth")
    res = V.validate(gt, modes=("current",))
    assert res["n_label_files"] == 2
    assert V.summary_status(res).startswith("No plate could be scored: all 2 plates failed")
    assert all("was not found next to it or in the chosen folder" in e
               for e in res["per_plate_df"]["error"])


def test_f6_validate_status_counts_plates_and_save_follows(neutral_plate_tif, tmp_path, monkeypatch, qtbot):
    from app import validate as V
    d = tmp_path / "labels"; d.mkdir()
    for i in range(2):
        shutil.copy(neutral_plate_tif, str(d / ("plate%d.tif" % i)))
        _label(d / ("labels_plate%d.json" % i), "plate%d.tif" % i, str(d / ("plate%d.tif" % i)))
    for i in range(2):
        _label(d / ("labels_gone%d.json" % i), "IMG_39%02d.jpeg" % i, r"C:\x\IMG_39%02d.jpeg" % i)
    res = V.validate(str(d), modes=("current", "published"))
    assert V.summary_status(res) == ("Scored 2 of 4 plates x 2 engines; 2 plates failed (see the "
                                     "last column).")
    pm = res["per_mode_df"]
    assert list(pm["engine"]) == ["Current, Auto", "Published, Standard"]
    sent = V.report_sentence(res, {"current": "Current (corrected)", "published": "Published (validated)"}, "9.9")
    assert "the Current (corrected) engine (plaque size Auto) of Plaque Toolkit 9.9" in sent
    assert "the Published (validated) engine (plaque size Standard) of Plaque Toolkit 9.9" in sent
    # one engine fails on one plate: that plate is a failed plate, and said so
    real = V.score_label_file

    def flaky(f, mode="precise", **k):
        if mode == "published" and f.endswith("labels_plate1.json"):
            raise RuntimeError("engine fell over")
        return real(f, mode=mode, **k)
    monkeypatch.setattr(V, "score_label_file", flaky)
    res2 = V.validate(str(d), modes=("current", "published"))
    assert V.summary_status(res2) == ("Scored 1 of 4 plates x 2 engines; 3 plates failed (1 of them "
                                      "for some engines only) (see the last column).")
    # the saved CSVs carry the engine column
    from app import ui as appui
    from PySide6.QtCore import QThreadPool
    from PySide6.QtWidgets import QMainWindow
    win = QMainWindow(); tab = appui.ValidateTab(QThreadPool()); win.setCentralWidget(tab)
    qtbot.addWidget(win)
    tab._done(res)
    assert tab.status.text().startswith("Scored 2 of 4 plates x 2 engines; 2 plates failed")
    assert tab.save_btn.isEnabled()
    out = tab._save(str(tmp_path / "res.csv"))
    assert list(pd.read_csv(out[0])["engine"]) == ["Current, Auto", "Published, Standard"]
    assert "Current, Auto" in set(pd.read_csv(out[1])["engine"])
    # every plate fails: said plainly, nothing to save
    monkeypatch.setattr(V, "score_label_file", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("x")))
    res3 = V.validate(str(d), modes=("current", "published"))
    tab._done(res3)
    assert tab.status.text() == "No plate could be scored: all 4 plates failed (see the last column)."
    assert not tab.save_btn.isEnabled() and tab.sentence.text() == ""
