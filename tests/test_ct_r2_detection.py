"""Click-through round 2, detection group: regression tests.

Part 1 (plumbing, CT-R2 N1 / N7): --multiscale always writes QC_FLAG / QC_REASON; the three
summary tools size only plaque_qc.size_ok rows of a table that has QC_FLAG and say "sizes from
N of M plaques"; no dish found is a warning.
"""
import json
import os
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

from conftest import REPO_ROOT, SAMPLE_TIF


def _run(script, args, cwd, timeout=600):
    return subprocess.run([sys.executable, os.path.join(REPO_ROOT, script)] + list(args),
                          cwd=str(cwd), capture_output=True, text=True, timeout=timeout)


@pytest.fixture
def mixed_plate(tmp_path):
    """tests/test_ct_r1_detection.py's plate: one 6 mm disc and five 1 mm discs on a 90 mm dish."""
    import cv2
    img = np.zeros((2000, 2000, 3), np.uint8)
    cv2.circle(img, (1000, 1000), 900, (150, 150, 150), -1)
    cv2.circle(img, (700, 700), 60, (70, 70, 70), -1)
    for c in [(1300, 700), (1300, 1300), (700, 1300), (1000, 1400), (1400, 1000)]:
        cv2.circle(img, c, 10, (70, 70, 70), -1)
    img = cv2.GaussianBlur(img, (5, 5), 0)
    path = str(tmp_path / "mixed_plate.png")
    cv2.imwrite(path, img)
    return path


@pytest.fixture
def empty_plate(tmp_path):
    import cv2
    img = np.zeros((2000, 2000, 3), np.uint8)
    cv2.circle(img, (1000, 1000), 900, (150, 150, 150), -1)
    img = cv2.GaussianBlur(img, (5, 5), 0)
    path = str(tmp_path / "empty_plate.png")
    cv2.imwrite(path, img)
    return path


@pytest.fixture
def no_dish_plate(tmp_path):
    """Lawn to the frame edge (the rim cropped away), four 3 mm-ish plaques."""
    import cv2
    img = np.full((1600, 1600, 3), 150, np.uint8)
    for c in [(400, 400), (1200, 400), (400, 1200), (1200, 1200)]:
        cv2.circle(img, c, 30, (70, 70, 70), -1)
    img = cv2.GaussianBlur(img, (5, 5), 0)
    path = str(tmp_path / "no_dish.png")
    cv2.imwrite(path, img)
    return path


# --------------------------------------------------------------------------- #
#  Part 1.1: --multiscale always writes QC_FLAG / QC_REASON (N1)
# --------------------------------------------------------------------------- #
def test_p1_multiscale_writes_qc_flag_without_qc(tmp_path, mixed_plate):
    r = _run("plaque_size_tool.py", ["-i", mixed_plate, "-p", "90", "-o", "m", "--multiscale"], tmp_path)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    df = pd.read_csv(tmp_path / "m" / "data-green-mixed_plate.csv")
    assert list(df.columns[-3:]) == ["SOURCE", "QC_FLAG", "QC_REASON"]
    assert df["QC_FLAG"].tolist() == ["LARGE?"] + ["OK"] * 5
    # the default run is untouched: no SOURCE, no QC columns
    r = _run("plaque_size_tool.py", ["-i", mixed_plate, "-p", "90", "-o", "d"], tmp_path)
    d = pd.read_csv(tmp_path / "d" / "data-green-mixed_plate.csv")
    assert "QC_FLAG" not in d.columns and "SOURCE" not in d.columns


def test_p1_multiscale_zero_plaques_still_has_the_columns(tmp_path, empty_plate):
    r = _run("plaque_size_tool.py", ["-i", empty_plate, "-p", "90", "-o", "m", "--multiscale"], tmp_path)
    assert r.returncode == 0
    df = pd.read_csv(tmp_path / "m" / "data-green-empty_plate.csv")
    assert len(df) == 0 and "QC_FLAG" in df.columns and "QC_REASON" in df.columns


def test_p1_multiscale_on_sample_says_sizes_from_n_of_m(tmp_path):
    r = _run("plaque_size_tool.py", ["-i", SAMPLE_TIF, "-p", "100", "-o", "m", "--multiscale"], tmp_path)
    assert r.returncode == 0
    df = pd.read_csv(tmp_path / "m" / "data-green-sample.csv")
    import plaque_qc
    ok = [plaque_qc.size_ok(f) for f in df["QC_FLAG"]]
    assert 0 < sum(ok) < len(df)
    assert ("sizes from %d of %d plaques" % (sum(ok), len(df))) in r.stdout
    # summarize_plates on that folder: count = every row, sizes = size_ok rows only
    s = _run("summarize_plates.py", ["-o", "m"], tmp_path)
    assert s.returncode == 0, s.stdout + s.stderr
    summ = pd.read_csv(tmp_path / "m" / "summary.csv")
    row = summ.iloc[0]
    assert row["N_PLAQUES"] == len(df) and row["N_SIZED"] == sum(ok)
    sized = df.loc[ok, "DIAMETER_MM"]
    assert row["DIAM_MM_MEDIAN"] == round(sized.median(), 3)
    assert row["DIAM_MM_MEDIAN"] != round(df["DIAMETER_MM"].median(), 3)
    assert "sizes from %d of %d plaques" % (sum(ok), len(df)) in s.stdout


# --------------------------------------------------------------------------- #
#  Part 1.2: summarize_plates / compile_excel / make_figure use size_ok rows (N1)
# --------------------------------------------------------------------------- #
FLAGS = ["OK", "CORE?", "EDGE", "SPLIT|NO_SIZE", "OK"]
DIAMS = [2.0, 0.5, 3.0, 9.0, 4.0]          # sized: 2, 3, 4 -> median 3.0 (all five: 3.0 too)
DIAMS_ALL = [2.0, 0.5, 2.5, 0.6, 4.0]      # sized: 2, 2.5, 4 -> 2.5; all five: 2.0


def _table(diams, flags=None):
    d = pd.DataFrame({"INDEX_COL": range(1, len(diams) + 1), "AREA_PXL": 100.0,
                      "DIAMETER_PXL": 10.0, "AREA_MM2": [x * x for x in diams],
                      "DIAMETER_MM": diams, "MEAN_GRAY": 80.0, "TURBIDITY_REL": 0.5})
    if flags is not None:
        d["QC_FLAG"] = flags
    return d


def test_p1_summarize_plates_sizes_only_size_ok_rows(tmp_path):
    import summarize_plates as sp
    out = tmp_path / "out"
    out.mkdir()
    _table(DIAMS_ALL, FLAGS).to_csv(out / "data-green-A.csv", index=False)
    _table(DIAMS_ALL).to_csv(out / "data-green-B.csv", index=False)
    sp.summarize(str(out))
    s = pd.read_csv(out / "summary.csv").set_index("PLATE")
    assert s.loc["A", "N_PLAQUES"] == 5 and s.loc["A", "N_SIZED"] == 3
    assert s.loc["A", "DIAM_MM_MEDIAN"] == 2.5 and s.loc["A", "DIAM_MM_MIN"] == 2.0
    # a table without QC_FLAG: every row sized, as before
    assert s.loc["B", "N_SIZED"] == 5 and s.loc["B", "DIAM_MM_MEDIAN"] == 2.0


def test_p1_summarize_plates_without_qc_flag_is_unchanged(tmp_path):
    """No QC_FLAG anywhere: no N_SIZED column (the frozen summary.csv keeps its columns)."""
    import summarize_plates as sp
    out = tmp_path / "out"
    out.mkdir()
    _table(DIAMS_ALL).to_csv(out / "data-green-B.csv", index=False)
    sp.summarize(str(out))
    s = pd.read_csv(out / "summary.csv")
    assert list(s.columns) == ["PLATE", "N_PLAQUES", "DIAM_MM_MEAN", "DIAM_MM_MEDIAN", "DIAM_MM_MIN",
                               "DIAM_MM_MAX", "AREA_MM2_MEAN", "MM_CALIBRATED", "CSV_FOUND"]


def test_p1_compile_excel_sizes_only_size_ok_rows(tmp_path):
    pytest.importorskip("openpyxl")
    root = tmp_path / "root"
    for sample, flags in (("WT", FLAGS), ("MUT", None)):
        pdir = root / sample / "p1"
        pdir.mkdir(parents=True)
        _table(DIAMS_ALL, flags).to_csv(pdir / "p1_normal.csv", index=False)
        _table(DIAMS_ALL).to_csv(pdir / "p1_sensitive.csv", index=False)   # both modes are expected
    r = _run("compile_excel.py", ["--root", str(root), "--out", str(tmp_path / "x.xlsx")], tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "WT / p1 (normal): sizes from 3 of 5 plaques" in r.stdout
    x = pd.read_excel(tmp_path / "x.xlsx", sheet_name="Summary (per replicate)").set_index("SAMPLE")
    assert x.loc["WT", "normal_count"] == 5 and x.loc["WT", "normal_n_sized"] == 3
    assert x.loc["WT", "normal_median_mm"] == 2.5
    assert x.loc["MUT", "normal_median_mm"] == 2.0          # no QC_FLAG: every row
    assert np.isnan(x.loc["MUT", "normal_n_sized"])


def test_p1_make_figure_plots_only_size_ok_sizes(tmp_path):
    rows = []
    for sample, flags in (("WT", FLAGS), ("MUT", ["OK"] * 5)):
        t = _table(DIAMS_ALL, flags)
        t["SAMPLE"], t["PLATE"], t["MODE"] = sample, "p1", "normal"
        rows.append(t)
    pd.concat(rows).to_csv(tmp_path / "tidy.csv", index=False)
    r = _run("make_figure.py", ["--csv", str(tmp_path / "tidy.csv"), "--ymax", "0", "--out", "fig"],
             tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Sizes from 8 of 10 plaques" in r.stdout
    assert "| 8 plaques" in r.stdout
    # turbidity is not a size: every row is plotted
    r = _run("make_figure.py", ["--csv", str(tmp_path / "tidy.csv"), "--metric", "TURBIDITY_REL",
                                "--ymax", "0", "--out", "fig_t"], tmp_path)
    assert r.returncode == 0 and "Sizes from" not in r.stdout and "| 10 plaques" in r.stdout


# --------------------------------------------------------------------------- #
#  Part 1.3: no dish found is a warning (N7)
# --------------------------------------------------------------------------- #
def test_p1_no_dish_warning_rule():
    import plaque_qc
    w = plaque_qc.dish_plausibility(None, (2000, 2000, 3))
    assert w == [plaque_qc.NO_DISH_WARNING]
    assert "No dish found: sizes are in pixels only" in w[0]
    assert "whole dish is in the frame" in w[0]
    assert plaque_qc.dish_plausibility((1000, 1000, 900), (2000, 2000)) == []


def test_p1_cli_prints_no_dish_warning_once_without_touching_the_csv(tmp_path, no_dish_plate):
    for mode, extra in (("d", []), ("m", ["--multiscale"])):
        r = _run("plaque_size_tool.py", ["-i", no_dish_plate, "-p", "90", "-o", mode] + extra, tmp_path)
        assert r.returncode == 0
        assert r.stdout.count("No dish found: sizes are in pixels only") == 1, r.stdout
        assert "-p was given but no Petri dish" not in r.stdout
        meta = json.load(open(tmp_path / mode / "run_metadata.json"))
        assert any("No dish found" in w for w in meta["images"][0]["dish_warnings"])
    d = pd.read_csv(tmp_path / "d" / "data-green-no_dish.csv")
    assert "QC_FLAG" not in d.columns and (d["DIAMETER_MM"] == 0).all()


def test_p1_app_detection_carries_the_no_dish_warning(no_dish_plate):
    from app import engine_api
    det = engine_api.detect_single(no_dish_plate, plate_mm=90, scale="auto")
    assert det["plate"] is None
    assert any(w.startswith("No dish found") for w in det["dish_warnings"])


# --------------------------------------------------------------------------- #
#  Part 2: the frozen detection benchmark (validation/detection_benchmark) -- a few
#  headline numbers, so a change to a scene or to the harness is seen (under ~30 s)
# --------------------------------------------------------------------------- #
SYNTH_SHARP_12_SUM = 315469509
SPLIT_3_SUM = 728237916
# (scene, mode, true discs matched of 48, rows sized incl. false positives): CLI default vs
# Auto with the round-1 rule
SYNTH_12_HEADLINE = [("sharp", "standard", 16, 16), ("sharp", "auto", 31, 31),
                     ("halo", "standard", 17, 17), ("halo", "auto", 38, 41)]


@pytest.fixture(scope="module")
def bench():
    d = os.path.join(REPO_ROOT, "validation", "detection_benchmark")
    if d not in sys.path:
        sys.path.insert(0, d)
    import score
    return score


def test_p2_benchmark_scenes_are_the_frozen_ones(bench):
    import scenes
    assert len(scenes.split_cases()) == 40
    img, truth, dish = scenes.synth_scene(12.0, "sharp")
    assert len(truth) == 48 and img.shape == (1157, 1543, 3) and round(dish) == 1080
    # a pixel checksum of two scenes: any edit to the drawing or the seeds changes it
    assert int(img.astype(np.int64).sum()) == SYNTH_SHARP_12_SUM
    simg, discs, case = scenes.split_scene(3)
    assert case[0] == "soft k=2" and len(discs) == 3
    assert int(simg.astype(np.int64).sum()) == SPLIT_3_SUM


def test_p2_benchmark_headline_numbers(bench, tmp_path):
    import cv2
    import scenes
    # synth sharp + halo at 12 px/mm: standard (CLI default) vs Auto detection
    recs = []
    for typ in ("sharp", "halo"):
        img, truth, _ = scenes.synth_scene(12.0, typ)
        p = str(tmp_path / ("s_%s.png" % typ))
        cv2.imwrite(p, img)
        tp = np.array([[d["x"], d["y"]] for d in truth])
        for mode in ("standard", "auto"):
            df, _d = bench._detect(p, scenes.DISH_MM, mode)
            pairs = bench.H.match(tp, df[["X", "Y"]].values.astype(float), scenes.synth_tolerance(truth))
            recs.append((typ, mode, len(pairs), int(bench.sized(df, "r1" if mode == "auto" else mode).sum())))
    assert recs == SYNTH_12_HEADLINE
    # split scene 1 (neighbour 1.6x larger, 0.7 apart): the big one is outlined at its core (-60 %)
    img, discs, _ = scenes.split_scene(1)
    p = str(tmp_path / "split1.png")
    cv2.imwrite(p, img)
    df, _d = bench._detect(p, scenes.SPLIT_MM, "auto")
    x, y, D = discs[1]
    j = int(np.hypot(df["X"] - x, df["Y"] - y).idxmin())
    assert round(float(df["DIAMETER_PXL"].iloc[j]) / D - 1, 3) == -0.901


# --------------------------------------------------------------------------- #
#  Part 3 (N2): the standard pass outlines haloed plaques >= ~140 px at their dark centre --
#  a limit of the frozen engine, so the CLI / app warn instead of changing a number
# --------------------------------------------------------------------------- #
def test_p3_standard_pass_measures_large_haloed_discs_at_the_centre(bench, tmp_path):
    """The CLI default itself (not Auto): 120 px haloed disc within +-5 %, 170 px at -60 %."""
    import cv2
    import scenes
    ppm = 34.0
    discs = [(-15.0, 0.0, 120 / ppm, "single", 1), (15.0, 0.0, 170 / ppm, "single", 2),
             (0.0, 20.0, 170 / ppm, "single", 3)]
    img, truth, _ = scenes.make_plate(ppm, discs, "halo", seed=1)
    p = str(tmp_path / "big_halo.png")
    cv2.imwrite(p, img)
    df, _d = bench._detect(p, scenes.DISH_MM, "standard")
    tp = np.array([[d["x"], d["y"]] for d in truth])
    pairs = dict(bench.H.match(tp, df[["X", "Y"]].values.astype(float), scenes.synth_tolerance(truth)))
    bias = [float(df["DIAMETER_PXL"].iloc[pairs[i]]) / d["D_px"] - 1 for i, d in enumerate(truth)]
    assert abs(bias[0]) < 0.05
    assert bias[1] < -0.55 and bias[2] < -0.55


def test_p3_large_plaque_warning_rule():
    import plaque_qc
    assert plaque_qc.large_plaque_warning([40.0, 99.0]) == []
    w = plaque_qc.large_plaque_warning([40.0, 120.4], mm_per_px=0.05)
    assert len(w) == 1
    assert w[0].startswith("Plaques wider than about 135 px (6.8 mm at this image's scale) may be "
                           "outlined at their dark centre (the largest here is 120 px)")
    assert "photograph at lower magnification or resize the image" in w[0]
    assert plaque_qc.plate_warnings([150.0])[0].startswith("Plaques wider than about 135 px may")


def test_p3_cli_warns_in_every_mode_without_touching_the_csv(tmp_path, mixed_plate):
    """The 6 mm disc of mixed_plate is ~120 px across: every CLI mode prints the warning and
    records it in run_metadata.json; the default CSV has no new column."""
    for out, extra in (("d", []), ("s", ["-small"]), ("p", ["--published"]), ("m", ["--multiscale"])):
        r = _run("plaque_size_tool.py", ["-i", mixed_plate, "-p", "90", "-o", out] + extra, tmp_path)
        assert r.returncode == 0
        assert r.stdout.count("Plaques wider than about 135 px") == (0 if out == "s" else 1), (out, r.stdout)
        meta = json.load(open(tmp_path / out / "run_metadata.json"))
        assert len(meta["images"][0]["plate_warnings"]) == (0 if out == "s" else 1)
    d = pd.read_csv(tmp_path / "d" / "data-green-mixed_plate.csv")
    assert list(d.columns) == ["INDEX_COL", "AREA_PXL", "DIAMETER_PXL", "AREA_MM2", "DIAMETER_MM",
                               "MEAN_GRAY", "TURBIDITY_REL"]


# --------------------------------------------------------------------------- #
#  Part 4: whatever rule is adopted, a plate with fewer than half its plaques sized says so
# --------------------------------------------------------------------------- #
def test_p4_few_sized_warning():
    import plaque_qc
    assert plaque_qc.few_sized_warning(["OK", "CORE?"]) == []            # exactly half: no
    w = plaque_qc.few_sized_warning(["OK", "CORE?", "SPLIT|NO_SIZE", "EDGE|CORE?"])
    assert w == ["sizes from 1 of 4 plaques: the size summary may not represent the plate (left out: "
                 "2 outlined at the dark centre only and 1 split pieces whose size is not reliable)."]
    assert plaque_qc.few_sized_warning([]) == []
    # plate_warnings carries it next to the large-plaque warning, for every front end
    assert plaque_qc.plate_warnings([20.0], None, ["CORE?", "CORE?", "OK"]) == \
        plaque_qc.few_sized_warning(["CORE?", "CORE?", "OK"])
    assert plaque_qc.plate_warnings([20.0], None, None) == []

