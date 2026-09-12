"""PT-3: a plate with zero plaques is an observation, not an absence of data.

Before this fix `write_one_data` had `if df.empty != True:`, so a blank plate wrote
no CSV at all and then vanished from summarize_plates.py's glob -- biasing every
mean count and titer upward and silently defeating the negative-control protocol
docs/PUBLICATION.md prescribes.
"""
import io
import os
import sys
import contextlib

import pandas as pd
import pytest

import plaque_size_tool as pst
import summarize_plates


def _run(image_path, out_dir, extra=()):
    os.makedirs(out_dir, exist_ok=True)
    saved_out, saved_argv = pst.out_dir_path, sys.argv
    pst.out_dir_path = out_dir
    sys.argv = ["plaque_size_tool.py", "-i", image_path, "-p", "90"] + list(extra)
    try:
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            pst.main()
    finally:
        pst.out_dir_path, sys.argv = saved_out, saved_argv
    return buf.getvalue()


@pytest.mark.parametrize("mode", [[], ["--published"], ["--upstream-exact"]])
def test_blank_plate_writes_a_header_only_csv(blank_plate_png, tmp_path, mode):
    out = str(tmp_path / ("out" + "".join(mode)))
    log = _run(blank_plate_png, out, mode)
    assert "0 plaques were found" in log
    csv = os.path.join(out, "data-green-blank_plate.csv")
    assert os.path.exists(csv), "a zero-plaque plate must still produce a CSV"
    df = pd.read_csv(csv)
    assert len(df) == 0
    assert list(df.columns) == pst.MEASUREMENT_COLUMNS


def test_zero_plaque_plate_appears_in_summary_with_count_zero(
        blank_plate_png, neutral_plate_tif, tmp_path):
    out = str(tmp_path / "out")
    _run(blank_plate_png, out)
    _run(neutral_plate_tif, out)
    with contextlib.redirect_stdout(io.StringIO()):
        summarize_plates.summarize(out)
    df = pd.read_csv(os.path.join(out, "summary.csv"))
    plates = dict(zip(df["PLATE"], df["N_PLAQUES"]))
    assert plates["blank_plate"] == 0
    assert plates["neutral_plate"] > 0
    assert len(df) == 2


def test_summary_can_flag_an_image_that_produced_no_csv(neutral_plate_tif, tmp_path):
    """--images enumerates the inputs, so a plate that failed outright is a visible
    gap (CSV_FOUND = False) rather than silently absent."""
    images = tmp_path / "imgs"
    images.mkdir()
    import shutil
    shutil.copy(neutral_plate_tif, images / "measured.tif")
    shutil.copy(neutral_plate_tif, images / "never_processed.tif")
    out = str(tmp_path / "out")
    _run(str(images / "measured.tif"), out)

    with contextlib.redirect_stdout(io.StringIO()) as buf:
        summarize_plates.summarize(out, str(images))
    df = pd.read_csv(os.path.join(out, "summary.csv")).set_index("PLATE")
    assert bool(df.loc["measured", "CSV_FOUND"]) is True
    assert bool(df.loc["never_processed", "CSV_FOUND"]) is False
    assert int(df.loc["never_processed", "N_PLAQUES"]) == 0
    assert "WARNING" in buf.getvalue()
