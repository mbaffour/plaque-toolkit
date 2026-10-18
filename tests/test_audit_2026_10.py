"""Regression tests for the findings of AUDIT-2026-10.md (PT-23 .. PT-46).

Every test here pins a behaviour that was wrong at v1.1.0 and is fixed on this branch.
The synthetic plates come from conftest.py; no checked-in artefact is used as an oracle,
so an expected value is derived from first principles (or from a formula the test states),
never from a previous run of the code under test.
"""
import json
import math
import os
import shutil
import subprocess
import sys

import cv2
import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "plaque_stats"))
sys.path.insert(0, os.path.join(ROOT, "plaque_stats", "agreement"))

import plaque_size_tool as pst          # noqa: E402
import plaque_turbidity as ptb          # noqa: E402
import plaque_gui as pgui               # noqa: E402
import provenance                       # noqa: E402
import scalebar                         # noqa: E402
import summarize_plates                 # noqa: E402


def _run_size_tool(argv, out_dir, cwd=None):
    """Drive plaque_size_tool.main() like the CLI, writing into out_dir."""
    saved_out, saved_argv = pst.out_dir_path, sys.argv
    pst.out_dir_path = str(out_dir)
    sys.argv = ["plaque_size_tool.py"] + list(argv)
    try:
        pst.main()
    finally:
        pst.out_dir_path, sys.argv = saved_out, saved_argv


# ----------------------------------------------------------------------------- PT-23
def test_same_named_images_in_two_subfolders_both_get_a_csv(neutral_plate_tif, tmp_path):
    root = tmp_path / "batch"
    (root / "a").mkdir(parents=True)
    (root / "b").mkdir()
    shutil.copy(neutral_plate_tif, root / "a" / "Plate_1.tif")
    shutil.copy(neutral_plate_tif, root / "b" / "Plate_1.tif")
    out = tmp_path / "out"
    _run_size_tool(["-d", str(root), "-p", "90"], out)
    csvs = sorted(p for p in os.listdir(out) if p.endswith(".csv"))
    assert csvs == ["data-green-a__Plate_1.csv", "data-green-b__Plate_1.csv"]
    meta = json.load(open(out / "run_metadata.json"))
    assert sorted(i["csv"] for i in meta["images"]) == csvs


def test_a_single_image_keeps_its_plain_output_name(neutral_plate_tif, tmp_path):
    out = tmp_path / "out"
    _run_size_tool(["-i", str(neutral_plate_tif), "-p", "90"], out)
    assert (out / ("data-green-%s.csv" % os.path.splitext(os.path.basename(neutral_plate_tif))[0])).exists()


# ----------------------------------------------------------------------------- -p validation
@pytest.mark.parametrize("bad", ["0", "-5", "90mm"])
def test_plate_size_must_be_a_positive_number(neutral_plate_tif, tmp_path, bad):
    with pytest.raises(SystemExit):
        _run_size_tool(["-i", str(neutral_plate_tif), "-p", bad], tmp_path / "out")


# ----------------------------------------------------------------------------- PT-25
def test_earlier_runs_in_the_same_folder_are_kept_in_provenance(neutral_plate_tif, tmp_path):
    out = tmp_path / "out"
    _run_size_tool(["-i", str(neutral_plate_tif), "-p", "90"], out)
    _run_size_tool(["-i", str(neutral_plate_tif), "-p", "90", "-published"], out)
    meta = json.load(open(out / "run_metadata.json"))
    assert meta["engine"] == "Published"
    assert [p["engine"] for p in meta["previous_runs"]] == ["Current"]


def test_a_corrupt_file_is_recorded_and_does_not_abort_the_batch(neutral_plate_tif, tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    shutil.copy(neutral_plate_tif, folder / "aa_good.tif")
    (folder / "zz_bad.tif").write_bytes(b"")
    out = tmp_path / "out"
    with pytest.raises(SystemExit) as exc:
        _run_size_tool(["-d", str(folder), "-p", "90"], out)
    assert exc.value.code == 1
    assert (out / "data-green-aa_good.csv").exists()
    meta = json.load(open(out / "run_metadata.json"))
    assert meta["n_failed"] == 1
    assert any("error" in i for i in meta["images"])
    assert not (out / "data-green-zz_bad.csv").exists()


# ----------------------------------------------------------------------------- walkers
def test_walker_skips_the_toolkits_own_outputs(neutral_plate_tif, tmp_path):
    folder = tmp_path / "in"
    (folder / "out").mkdir(parents=True)
    shutil.copy(neutral_plate_tif, folder / "Plate_1.tif")
    shutil.copy(neutral_plate_tif, folder / "out_Plate_1.tif")        # an annotated overlay
    shutil.copy(neutral_plate_tif, folder / "out" / "Plate_9.tif")    # inside an output dir
    found = [os.path.basename(p) for p in pst.get_image_paths(None, str(folder))]
    assert found == ["Plate_1.tif"]
    found = [os.path.basename(p) for p in ptb.list_images(str(folder))]
    assert found == ["Plate_1.tif"]


# ----------------------------------------------------------------------------- PT-20
def test_imwrite_checked_falls_back_when_cv2_reports_failure(tmp_path, monkeypatch):
    img = np.zeros((8, 8, 3), np.uint8)
    img[2:6, 2:6] = 200
    ref = tmp_path / "ref.png"
    assert cv2.imwrite(str(ref), img)
    monkeypatch.setattr(cv2, "imwrite", lambda *a, **k: False)
    target = tmp_path / "copy.png"
    pst.imwrite_checked(str(target), img)
    assert target.read_bytes() == ref.read_bytes()


# ----------------------------------------------------------------------------- scalebar
def test_scale_bar_never_overruns_and_is_shortened_to_a_nice_length():
    w = 500
    img = np.zeros((300, w, 3), np.uint8)
    out = scalebar.draw_scale_bar(img.copy(), 0.1, length_mm=50)   # 500 px requested, 450 allowed
    cols = np.where((out[:, :, 0] > 200).any(axis=0))[0]
    span = int(cols.max() - cols.min() + 1)
    assert span <= int(w * 0.9)
    assert abs(span - 200) <= 3        # 20 mm, the largest NICE_MM that fits at 0.1 mm/px


# ----------------------------------------------------------------------------- summarize
def test_summary_does_not_average_zero_mm_placeholders(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    pd.DataFrame({"INDEX_COL": [1, 2], "AREA_PXL": [10, 20], "DIAMETER_PXL": [3, 5],
                  "AREA_MM2": [0, 0], "DIAMETER_MM": [0, 0], "MEAN_GRAY": [1, 2],
                  "TURBIDITY_REL": [0, 1]}).to_csv(out / "data-green-Plate_10.csv", index=False)
    pd.DataFrame({"INDEX_COL": [1], "AREA_PXL": [10], "DIAMETER_PXL": [3],
                  "AREA_MM2": [1.5], "DIAMETER_MM": [1.38], "MEAN_GRAY": [1],
                  "TURBIDITY_REL": [0]}).to_csv(out / "data-green-Plate_2.csv", index=False)
    summarize_plates.summarize(str(out))
    df = pd.read_csv(out / "summary.csv")
    assert list(df["PLATE"]) == ["Plate_2", "Plate_10"]               # natural order
    row10 = df[df["PLATE"] == "Plate_10"].iloc[0]
    assert row10["N_PLAQUES"] == 2 and row10["MM_CALIBRATED"] == False   # noqa: E712
    assert pd.isna(row10["DIAM_MM_MEAN"])


# ----------------------------------------------------------------------------- turbidity
def test_dilution_below_one_is_rejected(neutral_plate_tif, tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    shutil.copy(neutral_plate_tif, folder / "T4.tif")
    with pytest.raises(SystemExit, match="reciprocal"):
        ptb.run_batch(str(folder), "90", False, None, None, str(tmp_path / "o"),
                      make_overlays=False, make_plots=False, dilution=1e-6, volume_ul=100)


def test_titer_carries_a_poisson_interval(neutral_plate_tif, tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    shutil.copy(neutral_plate_tif, folder / "T4.tif")
    ptb.run_batch(str(folder), "90", False, None, None, str(tmp_path / "o"),
                  make_overlays=False, make_plots=False, dilution=1e6, volume_ul=100)
    q = pd.read_csv(tmp_path / "o" / "qc.csv").iloc[0]
    n = q["N_PLAQUES"]
    per_ml = 1.0 / 0.1 * 1e6
    assert q["PFU_PER_ML"] == pytest.approx(n * per_ml, rel=1e-6)
    assert q["PFU_PER_ML_CI95_HI"] == pytest.approx((n + 1.96 * math.sqrt(n)) * per_ml, rel=1e-6)


def test_a_named_reference_that_cannot_be_read_stops_the_run(neutral_plate_tif, tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    shutil.copy(neutral_plate_tif, folder / "T4.tif")
    with pytest.raises(SystemExit, match="--dark"):
        ptb.run_batch(str(folder), "90", False, None, None, str(tmp_path / "o"),
                      dark_path=str(tmp_path / "missing.tif"), make_overlays=False, make_plots=False)


def test_a_flat_field_of_another_size_is_fitted_per_plate(neutral_plate_tif, tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    shutil.copy(neutral_plate_tif, folder / "T4.tif")
    flat = tmp_path / "flat.png"
    cv2.imwrite(str(flat), np.full((123, 321, 3), 200, np.uint8))
    ptb.run_batch(str(folder), "90", False, None, str(flat), str(tmp_path / "o"),
                  make_overlays=False, make_plots=False)
    q = pd.read_csv(tmp_path / "o" / "qc.csv")
    assert len(q) == 1 and bool(q.iloc[0]["FLAT_APPLIED"]) is True
    assert not (tmp_path / "o" / "errors.csv").exists()


def test_zero_plaque_run_writes_header_only_csvs(tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    cv2.imwrite(str(folder / "blank.png"), np.full((300, 300, 3), 120, np.uint8))
    ptb.run_batch(str(folder), "90", False, None, None, str(tmp_path / "o"),
                  make_overlays=False, make_plots=False)
    assert list(pd.read_csv(tmp_path / "o" / "plaques_all.csv").columns) == ptb.PLAQUE_COLUMNS
    assert list(pd.read_csv(tmp_path / "o" / "per_phage.csv").columns) == ptb.PER_PHAGE_COLUMNS


def test_plate_labels_disambiguate_duplicate_stems(tmp_path):
    (tmp_path / "rep1").mkdir()
    (tmp_path / "rep2").mkdir()
    imgs = [str(tmp_path / "rep1" / "T4.tif"), str(tmp_path / "rep2" / "T4.tif"), str(tmp_path / "T7.tif")]
    labels = ptb.plate_labels(imgs, str(tmp_path))
    assert labels[imgs[0]] == "rep1__T4" and labels[imgs[1]] == "rep2__T4" and labels[imgs[2]] == "T7"


def test_16bit_input_is_detected_exactly_like_the_size_tool(neutral_plate_tif, tmp_path):
    """PT-27: on a 16-bit TIFF the turbidity tool must find the same plaque set as
    plaque_size_tool.py reading the same file."""
    img8 = cv2.imread(str(neutral_plate_tif))
    img16 = (img8.astype(np.uint16) * 257)
    p16 = tmp_path / "plate16.tif"
    assert cv2.imwrite(str(p16), img16)
    out = tmp_path / "out"
    _run_size_tool(["-i", str(p16), "-p", "90"], out)
    n_cli = len(pd.read_csv(out / "data-green-plate16.csv"))
    det = ptb.detect_plate(str(p16), "90", False)
    assert det["read_info"]["bit_depth"] == 16
    assert len(det["plaques"]) == n_cli
    assert "cv2.imread" in det["read_info"]["detection_8bit"]


def test_saturation_is_assessed_per_channel():
    raw = np.full((50, 50, 3), 100, np.uint8)
    raw[:, :, 2] = 255                                  # red pinned at full scale everywhere
    det = {"orig": raw, "raw": raw, "shape": (50, 50), "dish_mask": np.ones((50, 50), np.uint8),
           "dish_center": (25.0, 25.0), "dish_r": 20.0, "lawn_mask": np.ones((50, 50), np.uint8),
           "plaques": [], "plaque_masks": [], "read_info": {"transfer": "srgb"}}
    _rows, qc = ptb.measure_plate(det, "x", "x", None, None, None)
    assert qc["FRAC_SATURATED"] == 1.0
    assert qc["NATIVE_MAX"] == 255 and qc["FULL_SCALE"] == 255


def test_detect_plate_resets_a_leaked_sensitive_flag(neutral_plate_tif):
    pst.sensitive = True
    ptb.detect_plate(str(neutral_plate_tif), "90", False)
    assert pst.sensitive is False


# ----------------------------------------------------------------------------- PT-30
def test_published_sizing_in_the_editor_matches_the_cli_formula():
    mpp = 0.0831
    for area in (1000.5, 1112.5, 14102.5, 23.0, 999.99):
        _dp, area_mm2, dia_mm = pgui.measure(area, mpp, published=True)
        expect = float("%.2f" % (np.sqrt(float("%.2f" % (area * mpp * mpp)) / np.pi) * 2))
        assert round(dia_mm, 2) == expect
        _dp, _a, dia_cur = pgui.measure(area, mpp, published=False)
        assert round(dia_cur, 2) == round(2 * np.sqrt(area * mpp * mpp / np.pi), 2)


# ----------------------------------------------------------------------------- PT-33
def test_batch_published_does_not_add_small_unless_asked(neutral_plate_tif, tmp_path, monkeypatch):
    from app import batch_measure, engine_api
    seen = []
    orig = cv2.imread(str(neutral_plate_tif))

    def fake_detect(path, plate_mm=None, **kw):
        seen.append(dict(kw))
        return {"plaques": [], "orig_bgr": orig, "pxl_per_mm": 0.08, "lawn_gray": 100.0,
                "plate": None, "published": kw.get("published", False)}

    monkeypatch.setattr(engine_api, "detect_single", fake_detect)
    folder = tmp_path / "f"
    folder.mkdir()
    shutil.copy(neutral_plate_tif, folder / "P.tif")
    batch_measure.batch_measure(str(folder), plate_mm=90, mode="published", out_dir=str(tmp_path / "o1"))
    assert seen[-1] == {"published": True}
    batch_measure.batch_measure(str(folder), plate_mm=90, mode="published", small=True,
                                out_dir=str(tmp_path / "o2"))
    assert seen[-1] == {"published": True, "small": True}
    meta = json.load(open(tmp_path / "o1" / "run_metadata.json"))
    assert meta["settings"]["small"] is False


# ----------------------------------------------------------------------------- PT-35
def test_pasted_fiji_results_table_uses_the_value_not_the_row_number():
    from app.agreement import parse_column
    assert parse_column("1\t1.24\n2\t0.98\n3\t1.10") == [1.24, 0.98, 1.10]
    assert parse_column("1,24\n0,98") == [1.24, 0.98]
    assert parse_column("header\n1.5\n2.5") == [1.5, 2.5]
    assert parse_column("0.5\t3\n1.2\t4") == [0.5, 1.2]           # first column is not 1..n


# ----------------------------------------------------------------------------- PT-37
def test_label_store_ids_never_collide(tmp_path, neutral_plate_tif, monkeypatch):
    import label_store
    monkeypatch.setenv("PLAQUE_TRAINING_DIR", str(tmp_path / "store"))
    meta = {"image": "P.tif", "image_path": str(neutral_plate_tif), "mm_per_px": 0.08}
    a = label_store.file_into_store(meta, [{"index": 1, "x_px": 1, "y_px": 2, "r_px": 3}],
                                    str(neutral_plate_tif), source="t")
    b = label_store.file_into_store(meta, [{"index": 1, "x_px": 9, "y_px": 2, "r_px": 3}],
                                    str(neutral_plate_tif), source="t")
    assert a != b
    with pytest.raises(FileExistsError):
        label_store.file_into_store(meta, [{"index": 1, "x_px": 1, "y_px": 2, "r_px": 3}],
                                    str(neutral_plate_tif), source="t")
    label_json = a if str(a).endswith(".json") else os.path.join(label_store.store_root(), "labels", a + ".json")
    stored = json.load(open(label_json))
    assert stored["meta"]["image_path"] == os.path.basename(str(neutral_plate_tif))


# ----------------------------------------------------------------------------- viralplaque
def test_failed_imagej_run_is_not_a_zero_count(neutral_plate_tif, tmp_path, monkeypatch):
    import run_viralplaque as rv

    class R:
        returncode = 1
        stderr = "boom"
        stdout = ""

    monkeypatch.setattr(rv.subprocess, "run", lambda *a, **k: R())
    res = rv.run_one(str(neutral_plate_tif), str(tmp_path / "o"), plate_mm=90.0)
    assert res["count"] is None and "imagej failed" in res["note"]


# ----------------------------------------------------------------------------- statistics
def test_long_format_requires_a_metric_and_filters_on_it():
    import plaque_stats as ps
    raw = pd.DataFrame({"group": ["A"] * 4 + ["B"] * 4, "replicate": [1, 1, 2, 2] * 2,
                        "metric": ["d", "a"] * 4, "value": [1, 10, 2, 20, 3, 30, 4, 40]})
    with pytest.raises(SystemExit, match="metrics"):
        ps.normalize(raw, "group", None, "replicate", "metric")
    d, m = ps.normalize(raw, "group", "d", "replicate", "metric")
    assert m == "d" and sorted(d["value"]) == [1, 2, 3, 4]
    with pytest.raises(SystemExit, match="not found"):
        ps.normalize(raw, "group", "zzz", "replicate", "metric")


def test_posthoc_with_a_single_value_group_reports_na_not_ns():
    import plaque_stats as ps
    out = ps.tukey({"A": [1.0], "B": [2.0, 3.0, 2.5], "C": [5.0, 6.0, 5.5]})
    assert math.isnan(out[("A", "B")]) and out[("B", "C")] < 0.05
    assert ps.stars(float("nan")) == "n/a"


def test_welch_anova_and_games_howell_match_a_reference_implementation():
    """Values cross-checked against pingouin 0.5 (welch_anova / pairwise_gameshowell)."""
    import plaque_stats as ps
    rng = np.random.default_rng(1)
    g = {"A": rng.normal(10, 1, 6), "B": rng.normal(11, 4, 5), "C": rng.normal(13, 0.5, 7)}
    assert ps.welch_anova_p(list(g.values())) == pytest.approx(0.000575725, rel=1e-5)
    gh = ps.games_howell(g)
    assert gh[("A", "B")] == pytest.approx(0.326772, rel=1e-5)
    assert gh[("A", "C")] == pytest.approx(0.000593536, rel=1e-5)
    assert gh[("B", "C")] == pytest.approx(0.283271, rel=1e-5)


def test_unequal_variances_switch_to_welch_anova_and_games_howell():
    import plaque_stats as ps
    rng = np.random.default_rng(3)
    rows = []
    for gname, sd in (("A", 0.05), ("B", 3.0), ("C", 0.05)):
        for rep in range(8):
            for _ in range(5):
                rows.append({"group": gname, "replicate": rep, "value": rng.normal(10, sd)})
    d = pd.DataFrame(rows)
    omni, post, unit, _ = ps.run_stats(d, ["A", "B", "C"], "replicate", "parametric")
    assert omni["levene_p"] < 0.05
    assert omni["test"] == "Welch ANOVA" and omni["posthoc"] == "Games-Howell"


def test_grouped_comparisons_are_holm_adjusted_within_group():
    import plaque_stats as ps
    rng = np.random.default_rng(5)
    rows = []
    for sub in ("ctrl", "s1", "s2", "s3"):
        for rep in range(4):
            for _ in range(5):
                rows.append({"group": "G", "subgroup": sub, "replicate": rep,
                             "value": rng.normal(10 + (0.5 if sub != "ctrl" else 0), 1)})
    d = pd.DataFrame(rows)
    summ, comp, unit = ps.grouped_stats(d, ["G"], ["ctrl", "s1", "s2", "s3"], "ctrl")
    assert "p_raw" in comp.columns and (comp["p"] >= comp["p_raw"] - 1e-12).all()


def test_agreement_picks_the_right_columns_and_never_the_same_one_twice():
    import agreement as ag
    cols = ["plaque_id", "area_tool_mm2", "area_fiji_mm2", "diam_tool_mm", "diam_fiji_mm"]
    t = ag._find_col(cols, ag.TOOL_HINTS, prefer="diam")
    m = ag._find_col(cols, ag.MANUAL_HINTS, exclude=(t,), prefer="diam")
    assert (t, m) == ("diam_tool_mm", "diam_fiji_mm")
    cols = ["plaque_id", "length_tool", "length_manual"]
    t = ag._find_col(cols, ag.TOOL_HINTS)
    m = ag._find_col(cols, ag.MANUAL_HINTS, exclude=(t,))
    assert (t, m) == ("length_tool", "length_manual")


def test_agreement_reports_proportional_bias():
    import agreement as ag
    ref = [float(x) for x in range(1, 21)]
    tool = [1.3 * x - 0.45 for x in ref]
    s = ag.compute(tool, ref)
    # diff = 0.3x - 0.45, mean = 1.15x - 0.225  ->  slope of diff on mean = 0.3 / 1.15
    assert s["ba_slope"] == pytest.approx(0.3 / 1.15, rel=1e-9)
    assert s["ba_slope_p"] < 1e-6
    sentence = ag.report_sentence(dict(s, r2=0.0, pearson_p=0.0, t_p=0.0, ccc=0.9, icc_lo=float("nan"),
                                       icc_hi=float("nan")), "mm", "diameters", "tool", "Fiji")
    assert "proportional bias" in sentence and "p < 0.001" in sentence
