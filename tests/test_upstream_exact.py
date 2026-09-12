"""PT-1: --published vs --upstream-exact.

The claim these tests pin down is the one docs/UPSTREAM_EXACT.md makes:

  * on NEUTRAL-GREY input the two modes are identical (so the citable Published
    numbers on the bundled plates and the Fiji validation set are safe), and
  * on COLOUR-CAST input the two brightness statistics diverge, which is the
    mechanism behind the measured 0.5 mm diameter divergence.
"""
import io
import os
import sys
import contextlib

import cv2
import numpy as np
import pandas as pd
import pytest

import plaque_size_tool as pst


def _run(image_path, out_dir, extra_args):
    """Run the size CLI in-process and return the green-plaque CSV as a DataFrame."""
    os.makedirs(out_dir, exist_ok=True)
    saved_out, saved_argv = pst.out_dir_path, sys.argv
    pst.out_dir_path = out_dir
    sys.argv = ["plaque_size_tool.py", "-i", image_path, "-p", "90"] + extra_args
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            pst.main()
    finally:
        pst.out_dir_path, sys.argv = saved_out, saved_argv
    stem = os.path.splitext(os.path.basename(image_path))[0]
    return pd.read_csv(os.path.join(out_dir, "data-green-%s.csv" % stem))


def test_published_equals_upstream_exact_on_neutral_tiff(neutral_plate_tif, tmp_path):
    """The load-bearing guarantee: on neutral-grey TIFF input the citable Published
    numbers ARE the original upstream numbers."""
    pub = _run(neutral_plate_tif, str(tmp_path / "pub"), ["--published"])
    exact = _run(neutral_plate_tif, str(tmp_path / "exact"), ["--upstream-exact"])
    assert len(pub) == len(exact) > 0
    for col in ("AREA_PXL", "DIAMETER_PXL", "AREA_MM2", "DIAMETER_MM"):
        assert list(pub[col]) == list(exact[col]), "column %s diverged" % col


def test_brightness_statistics_agree_on_neutral_and_differ_on_colour_cast(
        neutral_plate_tif, amber_plate_png):
    """Upstream's red-channel mean vs BT.601 luma: identical on neutral input,
    materially different under a colour cast (the root cause of PT-1)."""
    neutral_red = pst.get_brightness(neutral_plate_tif)
    neutral_luma = pst.brightness_luma(cv2.imread(neutral_plate_tif))
    assert neutral_red == pytest.approx(neutral_luma, abs=0.5)

    amber_red = pst.get_brightness(amber_plate_png)
    amber_luma = pst.brightness_luma(cv2.imread(amber_plate_png))
    assert amber_red - amber_luma > 5.0, (
        "colour cast should push the red-channel mean well above luma; got "
        "red=%.2f luma=%.2f" % (amber_red, amber_luma))


def test_upstream_exact_read_path_matches_upstream_literally(amber_plate_png):
    """read_and_dim_upstream_exact() must reproduce upstream's read block byte for byte.

    The expected value is computed here from upstream's own source lines, not from a
    stored artefact, so this stays a real comparison.
    """
    from PIL import Image, ImageStat, ImageEnhance

    # --- upstream plaque_size_tool.py main(), verbatim -----------------------
    im = Image.open(amber_plate_png)
    im.convert('L')                                   # upstream discards this (its bug)
    expected_brightness = ImageStat.Stat(im).mean[0]
    expected = cv2.imread(amber_plate_png)
    tmp = amber_plate_png + '.tmp' + os.path.splitext(amber_plate_png)[1]
    if expected_brightness > 70:
        ImageEnhance.Brightness(Image.open(amber_plate_png)).enhance(0.5).save(tmp)
        expected = cv2.imread(tmp)
        os.remove(tmp)
    # ------------------------------------------------------------------------

    pst.upstream_exact = True
    got, _orig, got_brightness = pst.read_and_dim(amber_plate_png)

    assert got_brightness == pytest.approx(expected_brightness)
    assert np.array_equal(got, expected)
    assert not os.path.exists(tmp), "the temp file must be cleaned up"


def test_upstream_exact_implies_published(neutral_plate_tif, tmp_path):
    """--upstream-exact must also switch the measurement maths to the published ones
    (2-dp string formatting is the visible signature)."""
    _run(neutral_plate_tif, str(tmp_path / "o"), ["--upstream-exact"])
    assert pst.use_published is True
    assert pst.upstream_exact is True


def test_upstream_exact_refuses_heic_instead_of_silently_falling_back(tmp_path):
    """Upstream had no HEIC support; this mode must say so rather than take a path
    upstream never had."""
    fake = tmp_path / "plate.heic"
    fake.write_bytes(b"not really a heic file")
    pst.upstream_exact = True
    with pytest.raises(ValueError, match="upstream-exact"):
        pst.read_and_dim(str(fake))
