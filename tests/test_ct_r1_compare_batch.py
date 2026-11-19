"""Click-through round 1, fixer group "compare-batch": regression tests for the Compare
turbidity tab, the Batch tab, the worker threads, the turbidity figures and the titer interval
(tester findings F1-F5, F13, F17, F18, F21, F23 + the statistics tester's titer-interval finding).

Engine-level tests run everywhere; the GUI tests need PySide6 + pytest-qt (offscreen) and are
skipped without them, like tests/test_app_gui.py.
"""
import importlib.util
import json
import math
import os
import re
import shutil
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import plaque_turbidity as ptb          # noqa: E402

HAVE_QT = (importlib.util.find_spec("PySide6") is not None
           and importlib.util.find_spec("pytestqt") is not None)
needs_qt = pytest.mark.skipif(not HAVE_QT, reason="needs PySide6 + pytest-qt")
if HAVE_QT:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

TIMEOUT = 90_000


# =========================================================================== engine: titer
def test_poisson_interval_matches_the_exact_garwood_limits_from_scipy():
    """n +/- 1.96*sqrt(n) gave [0, 0] for no plaques and was far too narrow below 10."""
    chi2 = pytest.importorskip("scipy.stats").chi2
    for n in (0, 3, 30):
        lo, hi = ptb.poisson_ci95(n)
        want_lo = 0.0 if n == 0 else chi2.ppf(0.025, 2 * n) / 2.0
        want_hi = chi2.ppf(0.975, 2 * n + 2) / 2.0
        assert lo == pytest.approx(want_lo, abs=1e-9)
        assert hi == pytest.approx(want_hi, rel=1e-9)


def test_poisson_interval_known_values_without_scipy():
    lo, hi = ptb.poisson_ci95(0)
    assert lo == 0.0 and hi == pytest.approx(3.688879454, rel=1e-8)     # not [0, 0]
    lo, hi = ptb.poisson_ci95(3)
    assert lo == pytest.approx(0.618672123, rel=1e-8) and hi == pytest.approx(8.767273070, rel=1e-8)
    with pytest.raises(ValueError):
        ptb.poisson_ci95(-1)


def test_a_plate_with_no_plaques_gets_a_nonzero_upper_titer_limit(blank_plate_png, tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    shutil.copy(blank_plate_png, folder / "T7_1.png")
    ptb.run_batch(str(folder), "90", False, None, None, str(tmp_path / "o"),
                  make_overlays=False, make_plots=False, dilution=1e6, volume_ul=100)
    q = pd.read_csv(tmp_path / "o" / "qc.csv").iloc[0]
    per_ml = 1e6 / 0.1
    assert q["N_PLAQUES"] == 0 and q["PFU_PER_ML"] == 0
    assert q["PFU_PER_ML_CI95_LO"] == 0
    assert q["PFU_PER_ML_CI95_HI"] == pytest.approx(3.688879454 * per_ml, rel=1e-6)


@pytest.mark.parametrize("volume", [0, -100, float("inf")])
def test_engine_rejects_a_volume_that_is_not_positive(neutral_plate_tif, tmp_path, volume):
    """F3: volume -100 gave a negative PFU/mL with its interval upside down."""
    folder = tmp_path / "in"
    folder.mkdir()
    shutil.copy(neutral_plate_tif, folder / "T4.tif")
    with pytest.raises(SystemExit, match="volume-ul must be the plated volume"):
        ptb.run_batch(str(folder), "90", False, None, None, str(tmp_path / "o"),
                      make_overlays=False, make_plots=False, dilution=1e6, volume_ul=volume)
    assert not (tmp_path / "o" / "qc.csv").exists()          # stopped before writing anything


# =========================================================================== engine: figures
def _plot_df(turbidity_for=("T4", "T7", "lambda")):
    rng = np.random.default_rng(1)
    rows = []
    for phage, mu, sd in (("T4", 1.0, 0.05), ("T7", 2.0, 0.50), ("lambda", 1.5, 0.2)):
        for v in rng.normal(mu, sd, 40):
            rows.append({"PHAGE": phage, "PLATE": phage + "_1", "DIAMETER_MM": round(abs(v), 3),
                         "TRANSMITTANCE": round(0.5 + 0.1 * abs(v), 4),
                         "OD": "", "TURBIDITY": (round(min(abs(v) / 3, 1), 3)
                                                 if phage in turbidity_for else "")})
    return pd.DataFrame(rows)


def _svg_texts(path):
    import xml.etree.ElementTree as ET
    out = []
    for el in ET.parse(path).getroot().iter():
        if el.tag.endswith("}text") or el.tag.endswith("}tspan") or el.tag in ("text", "tspan"):
            if el.text and el.text.strip():
                out.append(el.text.strip())
    return out


def test_write_plots_removes_only_its_own_stale_figures_and_returns_what_it_wrote(tmp_path):
    """F4: a run without TURBIDITY (blank removed) left the earlier run's turbidity figures."""
    stale = ["compare_TURBIDITY.png", "hist_TURBIDITY.png", "hist_TURBIDITY.svg",
             "hist_TURBIDITY_legend_key.png", "hist_TURBIDITY_legend_text.txt",
             "compare_OD.pdf"]
    keep = ["compare_notes.png", "my_hist_TURBIDITY.png", "hist_TURBIDITY_v2.png", "plaques_all.csv"]
    for n in stale + keep:
        (tmp_path / n).write_text("old")
    df = _plot_df().drop(columns=["TURBIDITY"])
    figs = ptb.write_plots(df, str(tmp_path))
    for n in stale:
        assert not (tmp_path / n).exists(), n
    for n in keep:
        assert (tmp_path / n).read_text() == "old", n
    assert [(f["kind"], f["metric"]) for f in figs] == [
        ("compare", "DIAMETER_MM"), ("compare", "TRANSMITTANCE"),
        ("hist", "DIAMETER_MM"), ("hist", "TRANSMITTANCE")]
    for f in figs:                                   # PNG + SVG + PDF, and the key in the same
        assert [os.path.splitext(p)[1] for p in f["files"]] == [".png", ".svg", ".pdf"]
        assert [os.path.basename(p).split("_legend_")[1] for p in f["key_files"]] == [
            "key.png", "key.svg", "key.pdf", "text.txt"]
        assert all(os.path.getsize(p) > 0 for p in f["files"] + f["key_files"])

    # a run with nothing to plot shows nothing and leaves nothing behind
    assert ptb.write_plots(df.iloc[0:0], str(tmp_path)) == []
    assert ptb.own_figure_files(str(tmp_path)) == []
    assert (tmp_path / "compare_notes.png").exists()


def test_histograms_of_one_figure_share_one_set_of_bin_edges(tmp_path, monkeypatch):
    """F21: bins=20 per phage gave the narrow distribution narrow bins."""
    from matplotlib.axes import Axes
    seen = []
    real = Axes.hist

    def spy(self, x, bins=None, **kw):
        seen.append((np.asarray(x), np.asarray(bins)))
        return real(self, x, bins=bins, **kw)

    monkeypatch.setattr(Axes, "hist", spy)
    df = _plot_df()[["PHAGE", "PLATE", "DIAMETER_MM"]]
    ptb.write_plots(df, str(tmp_path), formats=("png",))
    assert len(seen) == 3                                    # one call per phage
    edges = seen[0][1]
    assert edges.ndim == 1 and len(edges) == 21
    assert all(np.array_equal(edges, b) for _x, b in seen)
    allv = df["DIAMETER_MM"].to_numpy()
    assert edges[0] == pytest.approx(allv.min()) and edges[-1] == pytest.approx(allv.max())


def test_axis_labels_are_words_with_units_not_column_names(tmp_path):
    df = _plot_df()
    ptb.write_plots(df, str(tmp_path))
    texts = {n: _svg_texts(str(tmp_path / n)) for n in os.listdir(tmp_path) if n.endswith(".svg")
             and "_legend_key" not in n}
    assert "Plaque diameter (mm)" in texts["compare_DIAMETER_MM.svg"]
    assert "Plaque diameter (mm)" in texts["hist_DIAMETER_MM.svg"]
    assert "Number of plaques" in texts["hist_DIAMETER_MM.svg"]
    assert "Turbidity (0 = clear, 1 = lawn)" in texts["compare_TURBIDITY.svg"]
    assert "Transmittance (relative to lawn)" in texts["hist_TRANSMITTANCE.svg"]   # no OD: no blank
    for name, tx in texts.items():
        assert not [t for t in tx if re.search(r"DIAMETER_MM|TURBIDITY|TRANSMITTANCE", t)], name
    assert ptb.metric_label("OD") == "Optical density (OD)"
    with_blank = df.assign(OD=0.3)
    assert ptb.metric_label("TRANSMITTANCE", with_blank) == "Transmittance (relative to blank agar)"


def test_box_plot_key_explains_the_marks_and_uses_the_histogram_colours(tmp_path):
    """F13: nothing said the triangle is the mean and the line the median."""
    lk = ptb._legend_key_module()
    figs = {(f["kind"], f["metric"]): f for f in ptb.write_plots(_plot_df(), str(tmp_path))}
    box, hist = figs[("compare", "DIAMETER_MM")], figs[("hist", "DIAMETER_MM")]
    labels = [e["label"] for e in box["key"]["entries"]]
    assert labels[:5] == ["T4", "T7", "lambda", "mean", "median"]
    by = {e["label"]: e for e in box["key"]["entries"]}
    assert (by["mean"]["kind"], by["mean"]["marker"]) == ("marker", "^")
    assert (by["median"]["kind"], by["median"]["linestyle"]) == ("line", "-")
    assert by["mean"]["colour"] == by["median"]["colour"] == "#000000"   # never a phage colour
    cols = {p: lk.to_hex(c) for p, c in ptb.phage_colours(["T4", "T7", "lambda"]).items()}
    assert {e["label"]: e["colour"] for e in box["key"]["entries"][:3]} == cols
    assert {e["label"]: e["colour"] for e in hist["key"]["entries"]} == cols
    assert "mean (black, filled triangles (up)); median (black, solid line)" in box["legend_text"]
    assert box["legend_text"].startswith("T4 (%s, filled box)" % lk.colour_name(cols["T4"]))
    assert hist["legend_text"].startswith("T4 (%s, filled bars)" % lk.colour_name(cols["T4"]))


def test_a_phage_keeps_one_colour_in_every_figure_of_a_run(tmp_path):
    """T7 has no TURBIDITY here; lambda must not take over T7's colour in those figures."""
    figs = ptb.write_plots(_plot_df(turbidity_for=("T4", "lambda")), str(tmp_path), formats=("png",))
    colour = {}
    for f in figs:
        for e in f["key"]["entries"]:
            if e["label"] in ("T4", "T7", "lambda"):
                colour.setdefault(e["label"], set()).add(e["colour"])
    assert {k: len(v) for k, v in colour.items()} == {"T4": 1, "T7": 1, "lambda": 1}
    assert len({next(iter(v)) for v in colour.values()}) == 3
    turb = [f for f in figs if f["metric"] == "TURBIDITY" and f["kind"] == "hist"][0]
    assert [e["label"] for e in turb["key"]["entries"]] == ["T4", "lambda"]


def test_key_on_the_figure_matches_the_standalone_key_and_can_be_switched_off(tmp_path):
    on, off = tmp_path / "on", tmp_path / "off"
    on.mkdir(); off.mkdir()
    df = _plot_df()
    f_on = ptb.write_plots(df, str(on), key_on_figure=True)
    f_off = ptb.write_plots(df, str(off), key_on_figure=False)
    for name in ("compare_DIAMETER_MM", "hist_TURBIDITY"):
        key_texts = _svg_texts(str(on / (name + "_legend_key.svg")))
        fig_on = _svg_texts(str(on / (name + ".svg")))
        fig_off = _svg_texts(str(off / (name + ".svg")))
        assert {"T4", "T7", "lambda"} <= set(key_texts)
        # every row of the stand-alone key is on the figure, in the same order ...
        assert [t for t in fig_on if t in key_texts][-len(key_texts):] == key_texts
        # ... and with the switch off the figure carries none of them
        assert not {"T4", "T7", "lambda", "mean", "median"} & {t for t in fig_off if "\n" not in t
                                                                and not t.startswith("(")
                                                                and t not in _tick_names(name)}
        # the stand-alone key is the same file either way
        assert _svg_texts(str(off / (name + "_legend_key.svg"))) == key_texts
    assert [f["key"] for f in f_on] == [f["key"] for f in f_off]
    assert [f["legend_text"] for f in f_on] == [f["legend_text"] for f in f_off]
    assert "Box plot marks" in _svg_texts(str(on / "compare_DIAMETER_MM.svg"))
    assert "Box plot marks" not in _svg_texts(str(off / "compare_DIAMETER_MM.svg"))
    # same colours on the figure as in its key
    key_svg = (on / "compare_DIAMETER_MM_legend_key.svg").read_text()
    fig_svg = (on / "compare_DIAMETER_MM.svg").read_text()
    for c in ptb.phage_colours(["T4", "T7", "lambda"]).values():
        assert c.lower() in key_svg.lower() and c.lower() in fig_svg.lower()


def _tick_names(name):
    """Phage names legitimately on a box plot without its key: the x tick labels."""
    return {"T4", "T7", "lambda"} if name.startswith("compare_") else set()


# =========================================================================== batch (no Qt)
def test_qc_flag_counts_per_plate():
    from app import batch_measure
    df = pd.DataFrame({"QC_FLAG": ["OK", "EDGE|OVERLAP", "MERGED?", "OVERLAP", "", "TINY|MERGED?"]})
    assert batch_measure.qc_flag_counts(df) == {"n_edge": 1, "n_overlap": 2, "n_merged": 2,
                                                "n_split": 0, "n_core": 0}   # + CT-R1 D8
    assert batch_measure.qc_flag_counts(pd.DataFrame()) == {"n_edge": 0, "n_overlap": 0, "n_merged": 0,
                                                             "n_split": 0, "n_core": 0}


def test_batch_error_text_names_the_file_then_the_reason_then_the_path():
    from app import batch_measure
    path = "/a/very/long/folder/of/plates/zero.jpg"
    msg = batch_measure.friendly_error(OSError("cannot identify image file %r" % path), path)
    assert msg.startswith("zero.jpg: not a readable image")
    assert msg.endswith("[%s]" % path) and msg.count(path) == 1
    msg = batch_measure.friendly_error(ValueError("dish radius is zero in %s" % path), path)
    assert msg == "zero.jpg: dish radius is zero in  [%s]" % path


def test_images_are_listed_in_natural_order(tmp_path):
    from app import batch_measure
    for n in ("Plate_10.tif", "Plate_2.tif", "plate_1.tif", "Plate_11.png", "notes.txt"):
        (tmp_path / n).write_bytes(b"x")
    names = [os.path.basename(p) for p in batch_measure.find_images(str(tmp_path))]
    assert names == ["plate_1.tif", "Plate_2.tif", "Plate_10.tif", "Plate_11.png"]


def test_turbidity_overlay_label_equals_plate_index_of_the_csv_row(tmp_path, monkeypatch):
    """F17 decision: the overlay exists to find a plaques_all.csv row on the plate, so the number
    drawn must be that row's PLATE_INDEX (engine order, frozen), not a reading-order rank."""
    import numpy as np
    drawn = []
    real = ptb.cv2.putText
    monkeypatch.setattr(ptb.cv2, "putText", lambda img, text, *a, **k: drawn.append(text) or real(img, text, *a, **k))
    def hull(cx, cy):
        return [[cx - 5, cy - 5], [cx + 5, cy - 5], [cx + 5, cy + 5], [cx - 5, cy + 5]]
    det = {"orig": np.zeros((120, 120, 3), np.uint8), "dish_center": None, "dish_r": 0,
           "plaques": [{"hull": hull(50, 90)}, {"hull": hull(10, 10)}, {"hull": hull(70, 10)}]}
    rows = [{"PLATE_INDEX": i, "TURBIDITY": 0.5} for i in (1, 2, 3)]
    ptb.annotate_plate(det, rows, str(tmp_path), "P")
    assert drawn == ["1", "2", "3"] and (tmp_path / "overlay_P.png").exists()


def test_batch_numbers_plaques_top_to_bottom_like_the_measure_tab(neutral_plate_tif, tmp_path):
    """F17: batch CSVs and the annotated image used the engine's order (#1 at the bottom)."""
    from app import batch_measure, engine_api
    folder = tmp_path / "f"
    folder.mkdir()
    shutil.copy(neutral_plate_tif, folder / "P.tif")
    # the Batch tab's Current = the Auto plaque size (CT-R1 detection D1)
    det = engine_api.detect_single(str(folder / "P.tif"), plate_mm=90, scale="auto")
    centres = [tuple(p["center"]) for p in det["plaques"]]
    ordered = sorted(det["plaques"], key=lambda p: (p["center"][1], p["center"][0]))
    assert len(centres) >= 4 and centres != [tuple(p["center"]) for p in ordered], \
        "the fixture must come out of the engine in a different order, or this proves nothing"
    assert engine_api.reading_order(det["plaques"]) == ordered
    assert [tuple(p["center"]) for p in det["plaques"]] == centres       # input left untouched

    res = batch_measure.batch_measure(str(folder), plate_mm=90, mode="current")
    want = engine_api.measure_table(ordered, det["orig_bgr"], det["pxl_per_mm"], det["lawn_gray"],
                                    published=False, plate=det.get("plate"))
    allp = pd.read_csv(os.path.join(res["out_dir"], "all_plaques.csv"))
    assert allp["INDEX"].tolist() == list(range(1, len(ordered) + 1))
    assert allp["AREA_PXL"].tolist() == want["AREA_PXL"].tolist()
    assert allp["MEAN_GRAY"].tolist() == want["MEAN_GRAY"].tolist()
    per_image = pd.read_csv(os.path.join(res["out_dir"], "P", "data-green-P.csv"))
    assert per_image["AREA_PXL"].tolist() == want["AREA_PXL"].tolist()
    assert per_image["INDEX_COL"].tolist() == allp["INDEX"].tolist()


def test_batch_csv_has_whole_counts_flag_counts_and_only_applied_options(neutral_plate_tif, tmp_path):
    from app import batch_measure
    folder = tmp_path / "f"
    folder.mkdir()
    shutil.copy(neutral_plate_tif, folder / "P_2.tif")
    (folder / "bad.png").write_text("this is not an image")
    res = batch_measure.batch_measure(str(folder), plate_mm=90, mode="published", watershed=True)
    text = open(os.path.join(res["out_dir"], "per_plate.csv")).read().splitlines()
    assert text[0] == ("image,n_plaques,mm_per_px,median_diam_mm,mean_diam_mm,axis_ratio,"
                       "tilt_flag,n_edge,n_overlap,n_merged,n_split,n_core,error")   # + D8 counts
    bad, good = text[1].split(",", 12), text[2].split(",")
    assert bad[0] == "bad.png" and bad[1:12] == [""] * 11         # blanks, not "nan"
    assert bad[12].strip('"').startswith("bad.png: not a readable image")
    assert bad[12].strip('"').endswith("[%s]" % (folder / "bad.png"))
    assert good[0] == "P_2.tif" and good[1] == "5"                 # "5", not "5.0"
    assert [int(v) for v in good[7:10]] == [0, 0, 0]
    allp = pd.read_csv(os.path.join(res["out_dir"], "all_plaques.csv"))
    assert int(good[8]) == int(allp["QC_FLAG"].fillna("").str.contains("OVERLAP").sum())
    assert res["errors"][0]["reason"].startswith("not a readable image")
    # Published never splits plaques: the record must not say it did
    meta = json.load(open(os.path.join(res["out_dir"], "run_metadata.json")))
    assert meta["settings"]["watershed"] is False and meta["settings"]["small"] is False
    res2 = batch_measure.batch_measure(str(folder), plate_mm=90, mode="current", watershed=True,
                                       out_dir=str(tmp_path / "o2"))
    meta2 = json.load(open(os.path.join(res2["out_dir"], "run_metadata.json")))
    # CT-R1 detection D1: Current runs the Auto plaque size, not forced -small
    assert meta2["settings"]["watershed"] is True and meta2["settings"]["small"] is False
    assert meta2["settings"]["plaque_size"] == "auto"


def test_batch_cli_says_no_images_found(tmp_path, capsys):
    from app import batch_measure
    assert batch_measure.main([str(tmp_path)]) == 1
    assert "No images found in %s" % tmp_path in capsys.readouterr().out
    assert not (tmp_path / "out_batch").exists()


# =========================================================================== GUI
if HAVE_QT:
    from PySide6.QtCore import Qt                                  # noqa: E402
    from PySide6.QtGui import QDesktopServices                     # noqa: E402
    from PySide6.QtWidgets import QFileDialog, QLabel, QLineEdit, QMessageBox  # noqa: E402

    from app import ui as appui                                    # noqa: E402
    from app import engine_api                                     # noqa: E402
    from app.workers import Worker                                 # noqa: E402


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
def dialogs(monkeypatch):
    """Record (kind, title, text) of every modal message box instead of showing it."""
    seen = []
    for name in ("warning", "information", "critical"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(
            lambda *a, _n=name, **k: seen.append((_n, a[1] if len(a) > 1 else "",
                                                  a[2] if len(a) > 2 else "")) or QMessageBox.Ok))
    return seen


@pytest.fixture
def phage_folder(neutral_plate_tif, tmp_path):
    """T4_1, T4_2, T7_1: the conftest synthetic plate (5 plaques) under phage-style names."""
    folder = tmp_path / "phages"
    folder.mkdir()
    for name in ("T4_1", "T4_2", "T7_1"):
        shutil.copy(neutral_plate_tif, folder / (name + ".tif"))
    return folder


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


def _run_compare(tab, qtbot, folder, **fields):
    tab.folder["edit"].setText(str(folder))
    tab.plate.setValue(90)
    tab.blank["edit"].setText(fields.get("blank", ""))
    tab.flat["edit"].setText(fields.get("flat", ""))
    tab.dilution.setText(fields.get("dil", ""))
    tab.volume.setText(fields.get("vol", ""))
    tab.run()
    assert not tab.run_btn.isEnabled(), "the run did not start"
    qtbot.waitUntil(lambda: tab.run_btn.isEnabled(), timeout=TIMEOUT)


# ----------------------------------------------------------------------------- F1
@needs_qt
def test_worker_threads_get_a_16_mb_stack(window):
    """F1: Qt's default 512 KB pool-thread stack on macOS is overflowed by numpy/OpenBLAS under
    matplotlib; the Compare tab died with 'Bus error' on any folder that had plaques."""
    assert window.pool.stackSize() >= 16 * 1024 * 1024
    assert window.pool.maxThreadCount() == 1          # engine flags are process-global


@needs_qt
def test_compare_tab_plots_a_folder_with_plaques_on_the_worker(window, qtbot, phage_folder, dialogs):
    """F1 (+F4, F23): the existing test only covered a zero-plaque folder, which returns before
    any plotting. This one makes the figures on the pool thread and checks what the tab shows."""
    tab = _compare_tab(window)
    _run_compare(tab, qtbot, phage_folder)
    assert not dialogs
    out = phage_folder / "out_turbidity"
    assert tab.last_out == str(out) and tab.open_btn.isEnabled() and tab.key_btn.isEnabled()

    # the figures of THIS run, each as PNG + SVG + PDF with its key, and one pixmap per figure
    assert [os.path.basename(f["png"]) for f in tab._figures] == [
        "compare_DIAMETER_MM.png", "compare_TRANSMITTANCE.png",
        "hist_DIAMETER_MM.png", "hist_TRANSMITTANCE.png"]
    for f in tab._figures:
        for p in f["files"] + f["key_files"]:
            assert os.path.getsize(p) > 0, p
    shown = [w for w in tab.figs.findChildren(QLabel) if w.pixmap() is not None and not w.pixmap().isNull()]
    assert len(shown) == 4 and all(w.pixmap().width() >= 300 for w in shown)
    starters = [w.text() for w in tab.figs.findChildren(QLineEdit)]
    assert starters == [f["legend_text"] for f in tab._figures]
    assert starters[0].startswith("T4 (") and "T7 (" in starters[0] and "median (" in starters[0]
    assert starters[2].startswith("T4 (") and starters[2].endswith("filled bars).")

    # per-phage table: only columns that hold something, short labels, ascending by phage
    hdr, rows = _table(tab.table)
    assert hdr == ["Phage", "Plates", "Plaques", "Transm. pooled", "Transm. plate mean", "Transm. plate SD"]
    assert [r[:3] for r in rows] == [["T4", "2", "10"], ["T7", "1", "5"]]
    per = pd.read_csv(out / "per_phage.csv")
    assert "OD_PLAQUE_MEAN" in per.columns and "TURBIDITY_PLATE_SD" in per.columns   # CSV unchanged
    t4 = per[per["PHAGE"] == "T4"].iloc[0]
    assert rows[0][3] == "%.4g" % t4["TRANSMITTANCE_PLAQUE_MEAN"]
    assert rows[1][5] == ""                                     # one plate: no SD, and not "nan"
    assert not [c for r in rows for c in r if "nan" in c.lower()]
    tip = tab.model.headerData(4, Qt.Horizontal, Qt.ToolTipRole)
    assert "TRANSMITTANCE_PLATE_MEAN" in tip and "per-plate means" in tip

    # per-plate table from qc.csv
    hdr, rows = _table(tab.plate_table)
    assert hdr == ["Plate", "Phage", "Plaques", "Countable (30–300)", "OD reference"]
    assert rows == [["T4_1", "T4", "5", "no", "lawn-relative"],
                    ["T4_2", "T4", "5", "no", "lawn-relative"],
                    ["T7_1", "T7", "5", "no", "lawn-relative"]]


# ----------------------------------------------------------------------------- F2
@needs_qt
def test_worker_reports_systemexit_and_other_base_exceptions_as_errors(qtbot):
    got = {"error": [], "finished": []}

    def run(fn):
        w = Worker(fn)
        w.signals.error.connect(got["error"].append)
        w.signals.finished.connect(got["finished"].append)
        w.run()

    def stop():
        raise SystemExit("No images found in /some/folder")

    run(stop)
    assert got["error"] == ["No images found in /some/folder"] and not got["finished"]

    def stop_with_status():
        raise SystemExit(3)

    run(stop_with_status)
    assert "exit status 3" in got["error"][-1]

    class Odd(BaseException):
        pass

    def odd():
        raise Odd("odd thing")

    run(odd)
    assert got["error"][-1].startswith("odd thing") and "Traceback" in got["error"][-1]

    def interrupt():
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        Worker(interrupt).run()

    run(lambda: 42)
    assert got["finished"] == [42] and len(got["error"]) == 3


@needs_qt
def test_an_engine_refusal_becomes_a_message_and_frees_the_run_button(window, qtbot, phage_folder,
                                                                      dialogs, monkeypatch):
    """F2: SystemExit on the worker used to segfault the app or leave Run disabled for ever."""
    def refuse(directory, **kw):
        raise SystemExit("--blank /x/blank.tif could not be read: damaged file")

    monkeypatch.setattr(engine_api, "run_compare", refuse)
    tab = _compare_tab(window)
    _run_compare(tab, qtbot, phage_folder)
    assert tab.run_btn.isEnabled() and not tab.progress.isVisible()
    assert [d[0] for d in dialogs] == ["critical"]
    assert dialogs[0][1] == "Comparison failed"
    assert "--blank /x/blank.tif could not be read: damaged file" in dialogs[0][2]
    assert window.statusBar().currentMessage() == "Comparison failed."


_BAD_INPUTS = [
    # (fields, expected dialog title, text the dialog must contain)
    (dict(empty=True), "No images found", "No images found in "),
    (dict(blank="/nonexistent/blank.tif"), "Blank-agar image not found", "/nonexistent/blank.tif"),
    (dict(flat="/nonexistent/flat.tif"), "Flat-field image not found", "/nonexistent/flat.tif"),
    (dict(dil="1e-6", vol="100"), "Dilution factor", "RECIPROCAL of the dilution"),
    (dict(dil="0", vol="100"), "Dilution factor", "1e6"),
    (dict(dil="abc", vol="100"), "Dilution factor", "You typed “abc”"),
    (dict(dil="1,000,000", vol="100"), "Dilution factor", "You typed “1,000,000”"),
    (dict(dil="1e6", vol="0"), "Plated volume", "greater than 0"),
    (dict(dil="1e6", vol="-100"), "Plated volume", "You typed “-100”"),
    (dict(dil="1e6", vol="lots"), "Plated volume", "microlitres"),
    (dict(dil="1e6"), "Titer needs both values", "Fill in the plated volume"),
    (dict(vol="100"), "Titer needs both values", "Fill in the dilution factor"),
]


@needs_qt
@pytest.mark.parametrize("fields,title,needle", _BAD_INPUTS, ids=[t[1] + ":" + str(sorted(t[0].items())) for t in _BAD_INPUTS])
def test_compare_tab_checks_its_inputs_before_starting(window, phage_folder, tmp_path, dialogs,
                                                       monkeypatch, fields, title, needle):
    """F2/F3: every input the engine refuses is caught with a plain message, nothing starts."""
    started = []
    monkeypatch.setattr(engine_api, "run_compare", lambda *a, **k: started.append(a) or {})
    tab = _compare_tab(window)
    folder = phage_folder
    if fields.get("empty"):
        folder = tmp_path / "empty"
        folder.mkdir()
        (folder / "out_turbidity").mkdir()                 # an old output folder is not "images"
        (folder / "out_turbidity" / "overlay_T4.png").write_bytes(b"x")
    tab.folder["edit"].setText(str(folder))
    tab.blank["edit"].setText(fields.get("blank", ""))
    tab.flat["edit"].setText(fields.get("flat", ""))
    tab.dilution.setText(fields.get("dil", ""))
    tab.volume.setText(fields.get("vol", ""))
    tab.run()
    assert len(dialogs) == 1 and dialogs[0][0] == "warning"
    assert dialogs[0][1] == title
    assert needle in dialogs[0][2]
    assert tab.run_btn.isEnabled() and not tab.progress.isVisible()
    assert not started and window.pool.activeThreadCount() == 0


@needs_qt
def test_titer_boxes_accept_the_usual_ways_to_write_a_number():
    assert appui.parse_number("1e6") == 1e6
    assert appui.parse_number(" 1000000 ") == 1e6
    assert appui.parse_number("10^6") == 1e6
    assert appui.parse_number("2.5x10^6") == 2.5e6
    assert appui.parse_number("1,000,000") is None       # ambiguous: refused, never guessed
    assert appui.parse_number("abc") is None and appui.parse_number("inf") is None


# ----------------------------------------------------------------------------- F3
@needs_qt
def test_compare_tab_shows_the_titer_per_plate(window, qtbot, phage_folder, dialogs):
    tab = _compare_tab(window)
    _run_compare(tab, qtbot, phage_folder, dil="10^6", vol="100")
    assert not dialogs
    hdr, rows = _table(tab.plate_table)
    assert hdr == ["Plate", "Phage", "Plaques", "PFU/mL", "95 % low", "95 % high",
                   "Countable (30–300)", "OD reference"]
    lo, hi = ptb.poisson_ci95(5)
    per_ml = 1e6 / 0.1
    assert rows[0] == ["T4_1", "T4", "5", "%.2e" % (5 * per_ml), "%.2e" % (lo * per_ml),
                       "%.2e" % (hi * per_ml), "no", "lawn-relative"]
    assert [r[0] for r in rows] == ["T4_1", "T4_2", "T7_1"]
    assert "No titer" not in tab.qc.text()
    q = pd.read_csv(phage_folder / "out_turbidity" / "qc.csv")       # the CSV keeps full numbers
    assert q["PFU_PER_ML"].tolist() == [5 * per_ml] * 3
    assert {"COUNT", "PFU_PER_ML_CI95_LO", "PFU_PER_ML_CI95_HI", "COUNT_IN_RANGE_30_300"} <= set(q.columns)
    tip = tab.plate_model.headerData(4, Qt.Horizontal, Qt.ToolTipRole)
    assert "PFU_PER_ML_CI95_LO" in tip and "Poisson" in tip


# ----------------------------------------------------------------------------- F4 + F5
@needs_qt
def test_a_zero_plaque_rerun_shows_no_figures_and_names_the_empty_plates(window, qtbot, phage_folder,
                                                                         blank_plate_png, dialogs):
    tab = _compare_tab(window)
    _run_compare(tab, qtbot, phage_folder)
    out = phage_folder / "out_turbidity"
    assert len(tab._figures) == 4 and (out / "hist_DIAMETER_MM.png").exists()
    assert "0 plaques" not in tab.qc.text()
    assert "Lawn-relative only (no blank): polarity not assessed." in tab.qc.text()
    assert "polarity fail" not in tab.qc.text()

    # same folder, T7's plate now has no plaques: T7 leaves per_phage.csv but not the tab
    shutil.copy(blank_plate_png, phage_folder / "T7_1.tif")
    _run_compare(tab, qtbot, phage_folder)
    assert "0 plaques: T7_1." in tab.qc.text()
    assert [r[0] for r in _table(tab.table)[1]] == ["T4"]
    assert ["T7_1", "T7", "0", "no", "lawn-relative"] in _table(tab.plate_table)[1]
    assert all("T7" not in f["legend_text"] for f in tab._figures)

    # now nothing has plaques: no figure on screen, none left in the folder
    for name in ("T4_1", "T4_2"):
        shutil.copy(blank_plate_png, phage_folder / (name + ".tif"))
    _run_compare(tab, qtbot, phage_folder)
    assert tab._figures == [] and not tab.key_btn.isEnabled()
    assert not [w for w in tab.figs.findChildren(QLabel) if w.pixmap() is not None and not w.pixmap().isNull()]
    assert not tab.figs.findChildren(QLineEdit)
    assert "No figures" in tab.figs_placeholder.text()
    assert ptb.own_figure_files(str(out)) == []
    assert tab.model.rowCount() == 0 and tab.plate_model.rowCount() == 3
    assert "0 plaques: T4_1, T4_2, T7_1." in tab.qc.text()
    assert not [d for d in dialogs if d[0] == "critical"]


@needs_qt
def test_qc_note_reports_polarity_only_for_plates_measured_against_a_blank():
    base = {"PHAGE": "T4", "DISH_FOUND": True, "N_PLAQUES": 40, "ILLUM_CV": ""}
    rel = pd.DataFrame([dict(base, PLATE="T4_1", ABSOLUTE_OD=False, POLARITY_OK=False),
                        dict(base, PLATE="T4_2", ABSOLUTE_OD=False, POLARITY_OK=False)])
    note = appui.compare_qc_note(rel)
    assert "polarity fail" not in note
    assert "Lawn-relative only (no blank): polarity not assessed." in note
    assert "✓ QC passed (dish found)." in note and "No titer" in note

    absolute = pd.DataFrame([dict(base, PLATE="T4_1", ABSOLUTE_OD=True, POLARITY_OK=False),
                             dict(base, PLATE="T4_2", ABSOLUTE_OD=True, POLARITY_OK=True),
                             dict(base, PLATE="T7_1", ABSOLUTE_OD=True, POLARITY_OK=True, N_PLAQUES=0)])
    note = appui.compare_qc_note(absolute, titer=True)
    assert "polarity fail (plaques darker than the lawn; check that the plates were back-lit): T4_1." in note
    assert "0 plaques: T7_1." in note and "QC passed" not in note and "No titer" not in note

    ok = appui.compare_qc_note(absolute.iloc[1:2], titer=True)
    assert ok == "1 plate analysed.  ✓ QC passed (dish found, polarity)."
    failed = appui.compare_qc_note(pd.DataFrame(), failed=["bad_1"], titer=True)
    assert failed == "0 plates analysed.  ⚠ 1 image could not be read (see errors.csv): bad_1."


# ----------------------------------------------------------------------------- F13
@needs_qt
def test_legend_key_button_key_switch_and_open_folder(window, qtbot, phage_folder, tmp_path,
                                                      dialogs, monkeypatch):
    tab = _compare_tab(window)
    assert not tab.key_btn.isEnabled() and not tab.open_btn.isEnabled() and tab.key_cb.isChecked()
    _run_compare(tab, qtbot, phage_folder)
    out = phage_folder / "out_turbidity"
    box_svg = out / "compare_DIAMETER_MM.svg"
    assert "Box plot marks" in _svg_texts(str(box_svg))

    # "Legend key…": one click, one folder, the key of every shown figure in every format
    dest = tmp_path / "keys"
    dest.mkdir()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(dest)))
    tab.key_btn.click()
    want = sorted("%s_legend_%s" % (os.path.splitext(os.path.basename(f["png"]))[0], tail)
                  for f in tab._figures for tail in ("key.png", "key.svg", "key.pdf", "text.txt"))
    assert sorted(os.listdir(dest)) == want and len(want) == 16
    assert (dest / "compare_DIAMETER_MM_legend_text.txt").read_text().strip() == tab._figures[0]["legend_text"]
    assert _svg_texts(str(dest / "compare_DIAMETER_MM_legend_key.svg")) == \
        _svg_texts(str(out / "compare_DIAMETER_MM_legend_key.svg"))
    assert "Legend keys of 4 figures saved" in window.statusBar().currentMessage()

    # "Place key on figure" off: the shown figures are re-drawn without it, the key files stay
    tab.key_cb.setChecked(False)
    assert not tab.run_btn.isEnabled()
    qtbot.waitUntil(lambda: tab.run_btn.isEnabled(), timeout=TIMEOUT)
    assert "Box plot marks" not in _svg_texts(str(box_svg))
    assert (out / "compare_DIAMETER_MM_legend_key.svg").exists() and len(tab._figures) == 4
    assert [w.text() for w in tab.figs.findChildren(QLineEdit)] == [f["legend_text"] for f in tab._figures]
    tab.key_cb.setChecked(True)
    qtbot.waitUntil(lambda: tab.run_btn.isEnabled(), timeout=TIMEOUT)
    assert "Box plot marks" in _svg_texts(str(box_svg))

    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda u: opened.append(u.toLocalFile()) or True))
    tab.open_btn.click()
    assert opened == [str(out)]
    assert not dialogs


# ----------------------------------------------------------------------------- F17
@needs_qt
def test_batch_and_measure_number_the_same_plate_the_same_way(window, qtbot, neutral_plate_tif, tmp_path, dialogs):
    folder = tmp_path / "plates"
    folder.mkdir()
    shutil.copy(neutral_plate_tif, folder / "P.tif")
    mt = window.measure_tab
    mt.mode.setCurrentIndex(_mode_index("current"))
    mt.plate.setValue(90)
    mt.image_path = str(folder / "P.tif")
    mt._detect()
    qtbot.waitUntil(lambda: mt.det is not None and not mt.busy, timeout=TIMEOUT)
    measure = mt.model.dataframe()

    bt = _batch_tab(window)
    bt.folder.setText(str(folder))
    bt.mode.setCurrentIndex(_mode_index("current"))
    bt.plate.setValue(90)
    bt._run()
    qtbot.waitUntil(lambda: bt.last_out is not None, timeout=TIMEOUT)
    batch = pd.read_csv(os.path.join(bt.last_out, "all_plaques.csv"))
    assert len(batch) == len(measure) >= 4
    assert batch["INDEX"].tolist() == [int(v) for v in measure["INDEX"]]
    for col in ("AREA_PXL", "DIAMETER_MM", "MEAN_GRAY"):
        assert batch[col].tolist() == [float(v) for v in measure[col]], col


# ----------------------------------------------------------------------------- F18
@needs_qt
def test_batch_table_is_readable(window, qtbot, neutral_plate_tif, tmp_path, dialogs):
    folder = tmp_path / "plates"
    folder.mkdir()
    for n in ("Plate_10", "Plate_2"):
        shutil.copy(neutral_plate_tif, folder / (n + ".tif"))
    (folder / "bad.png").write_text("not an image")
    tab = _batch_tab(window)
    tab.folder.setText(str(folder))
    tab.mode.setCurrentIndex(_mode_index("current"))
    tab.plate.setValue(90)
    tab._run()
    qtbot.waitUntil(lambda: tab.last_out is not None, timeout=TIMEOUT)
    hdr, rows = _table(tab.table)
    assert hdr == ["Image", "Plaques", "mm/pixel", "Median (mm)", "Mean (mm)", "Axis ratio",
                   "Tilted?", "Edge", "Overlap", "Merged?", "Split", "Core only",   # + CT-R1 D8
                   "Problem"]
    assert [r[0] for r in rows] == ["bad.png", "Plate_2.tif", "Plate_10.tif"]     # natural, ascending
    assert rows[0][1:12] == [""] * 11
    assert rows[0][12].startswith("not a readable image")                          # reason first
    assert rows[1][1] == "5" and rows[1][6] == "no" and rows[1][7:12] == ["0"] * 5
    assert rows[1][12] == ""
    per = pd.read_csv(os.path.join(tab.last_out, "per_plate.csv"))
    good = per[per["image"] == "Plate_2.tif"].iloc[0]
    assert rows[1][2] == "%.4g" % good["mm_per_px"] and len(rows[1][2]) <= 8      # 4 significant digits
    assert rows[1][3] == "%.4g" % good["median_diam_mm"]
    assert not [c for r in rows for c in r if c.lower() in ("nan", "none", "<na>") or c.endswith(".0")]
    tip = tab.model.headerData(8, Qt.Horizontal, Qt.ToolTipRole)
    assert "n_overlap" in tip and "OVERLAP" in tip
    # every header is shown in full: each column is at least as wide as its header text needs
    hv = tab.table.horizontalHeader()
    fm = hv.fontMetrics()
    assert all(hv.sectionSize(c) >= fm.horizontalAdvance(hdr[c]) for c in range(len(hdr)))
    assert "2 images measured" in tab.status.text()
    assert "1 could not be measured (see the Problem column)" in tab.status.text()
    assert not dialogs


@needs_qt
def test_batch_tab_warns_about_a_folder_without_images(window, tmp_path, dialogs):
    folder = tmp_path / "empty"
    folder.mkdir()
    (folder / "notes.txt").write_text("x")
    tab = _batch_tab(window)
    tab.folder.setText(str(folder))
    tab._run()
    assert [d[:2] for d in dialogs] == [("warning", "No images found")]
    assert dialogs[0][2].startswith("No images found in %s" % folder)
    assert tab.status.text().startswith("No images found in %s" % folder)
    assert tab.run_btn.isEnabled() and tab.last_out is None and not tab.open_btn.isEnabled()
    assert not (folder / "out_batch").exists() and window.pool.activeThreadCount() == 0


@needs_qt
def test_batch_options_follow_the_engine_and_only_applied_ones_are_recorded(window, qtbot, neutral_plate_tif,
                                                                            tmp_path, dialogs):
    folder = tmp_path / "plates"
    folder.mkdir()
    shutil.copy(neutral_plate_tif, folder / "P.tif")
    tab = _batch_tab(window)

    def state():
        return (tab.watershed.isEnabled(), tab.watershed.isChecked(),
                tab.scale_box.isEnabled(), tab.scale_box.scale())

    # CT-R1 detection D1: "Plaque size" replaced the "Small plaques" box
    tab.mode.setCurrentIndex(_mode_index("current"))
    assert state() == (True, False, True, "auto")         # Auto (both scales) by default
    tab.watershed.setChecked(True)
    tab.mode.setCurrentIndex(_mode_index("sensitive"))
    assert state() == (True, True, True, "auto")
    tab.mode.setCurrentIndex(_mode_index("precise"))
    assert tab.scale_box.isEnabled() is False and tab.scale_box.scale() is None
    tab.mode.setCurrentIndex(_mode_index("published"))
    assert state() == (False, False, True, "standard")    # Published never splits; never Auto
    assert "not used by this engine" in tab.watershed.text()
    assert "Published never splits" in tab.watershed.toolTip()

    tab.folder.setText(str(folder))
    tab.plate.setValue(90)
    tab._run()
    assert not tab.scale_box.isEnabled() and not tab.watershed.isEnabled()      # busy
    qtbot.waitUntil(lambda: tab.last_out is not None, timeout=TIMEOUT)
    assert state() == (False, False, True, "standard")    # the run must not re-enable the wrong box
    meta = json.load(open(os.path.join(tab.last_out, "run_metadata.json")))
    assert meta["engine"] == "Published"
    assert meta["settings"]["watershed"] is False and meta["settings"]["small"] is False

    tab.mode.setCurrentIndex(_mode_index("current"))
    assert state() == (True, True, True, "auto")          # the earlier tick is remembered
    tab.last_out = None
    tab._run()
    qtbot.waitUntil(lambda: tab.last_out is not None, timeout=TIMEOUT)
    meta = json.load(open(os.path.join(tab.last_out, "run_metadata.json")))
    assert meta["settings"]["watershed"] is True and meta["settings"]["small"] is False
    assert meta["settings"]["plaque_size"] == "auto"
    assert not dialogs
