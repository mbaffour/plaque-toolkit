"""Per-plaque QC flags (plaque_qc.py): correct on synthetic geometry, additive on the CLI."""
import os
import subprocess
import sys

import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import plaque_qc  # noqa: E402


def _p(x, y, r, **kw):
    import math
    d = {"x": x, "y": y, "area_px": math.pi * r * r}
    d.update(kw)
    return d


def test_flags_on_synthetic_geometry():
    H, W = 1000, 1000
    dish = (500.0, 500.0, 450.0)
    plaques = [
        _p(500, 500, 20),                       # clean, central
        _p(520, 505, 20),                       # overlaps the first
        _p(10, 500, 20),                        # off the image border
        _p(500, 940, 20),                       # at the dish rim (500 + 440 + 20 >= 0.98*450)
        _p(300, 300, 70),                       # area 12x the median -> MERGED?
        _p(700, 300, 20, encl_diam_px=28),      # below the standard gate -> TINY
        _p(700, 700, 20, circularity=0.4),      # irregular -> MERGED?
        _p(300, 700, 20, p_plaque=0.3),         # low classifier score
    ]
    flags = plaque_qc.flag_plaques(plaques, (H, W), dish=dish)
    f = [a for a, _ in flags]
    assert "OVERLAP" in f[0] and "OVERLAP" in f[1]
    assert f[2].startswith("EDGE") and "border" in flags[2][1]
    assert f[3].startswith("EDGE") and "rim" in flags[3][1]
    assert "MERGED?" in f[4] and "median" in flags[4][1]
    assert "TINY" in f[5]
    assert "MERGED?" in f[6] and "circularity" in flags[6][1]
    assert "LOW_CONF" in f[7]
    # a clean plaque far from everything is OK
    assert plaque_qc.flag_plaques([_p(500, 500, 20)], (H, W), dish=dish)[0] == ("OK", "")


def test_no_plaques_no_flags():
    assert plaque_qc.flag_plaques([], (100, 100)) == []


def _run(args, out, cwd):
    env = dict(os.environ, PYTHONPATH=ROOT)
    subprocess.run([sys.executable, os.path.join(ROOT, "plaque_size_tool.py")] + args + ["-o", str(out)],
                   cwd=cwd, env=env, check=True, capture_output=True)


def test_cli_qc_is_opt_in_and_additive(neutral_plate_tif, tmp_path):
    stem = os.path.splitext(os.path.basename(neutral_plate_tif))[0]
    _run(["-i", str(neutral_plate_tif), "-p", "90"], tmp_path / "plain", tmp_path)
    _run(["-i", str(neutral_plate_tif), "-p", "90", "--qc"], tmp_path / "qc", tmp_path)
    plain = pd.read_csv(tmp_path / "plain" / ("data-green-%s.csv" % stem))
    qc = pd.read_csv(tmp_path / "qc" / ("data-green-%s.csv" % stem))
    assert "QC_FLAG" not in plain.columns
    assert list(qc.columns) == list(plain.columns) + ["QC_FLAG", "QC_REASON"]
    # the measurement columns are identical; only the two columns were appended
    pd.testing.assert_frame_equal(qc[plain.columns], plain)
    assert set(qc["QC_FLAG"]).issubset({"OK", "EDGE", "MERGED?", "TINY", "OVERLAP",
                                        "EDGE|OVERLAP", "MERGED?|OVERLAP", "TINY|OVERLAP", "EDGE|MERGED?",
                                        "EDGE|TINY", "MERGED?|TINY", "EDGE|MERGED?|OVERLAP"} | set(qc["QC_FLAG"]))
    assert (qc["QC_FLAG"] == "OK").any()


def test_app_table_carries_a_qc_column(neutral_plate_tif):
    from app import engine_api
    det = engine_api.detect_single(str(neutral_plate_tif), plate_mm=90, small=True)
    df = engine_api.measure_table(det["plaques"], det["orig_bgr"], det["pxl_per_mm"], det["lawn_gray"],
                                  plate=det.get("plate"))
    assert "QC_FLAG" in df.columns and len(df) == len(det["plaques"])
    assert (df["QC_FLAG"] == "OK").any()
