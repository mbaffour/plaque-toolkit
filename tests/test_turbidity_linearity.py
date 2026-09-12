"""PT-2: the quantitative OD path must not silently truncate or gamma its input.

docs/PUBLICATION.md tells users that OD is a true absorbance only with
radiometrically linear input (camera RAW / linear TIFF). Before this fix that was
the WORST input: read_bgr() used cv2.imread's default IMREAD_COLOR, which drops a
16-bit TIFF to 8 bits, and to_linear_gray() then applied an inverse-sRGB gamma on
top of already-linear data -- 0.53-0.89 OD of error.

Expected values here are computed from the Beer-Lambert definition
(OD = -log10(I/I0)), not from a previous run of the code under test.
"""
import math
import os

import cv2
import numpy as np
import pytest

import plaque_turbidity as pt

# Known transmittances written into the synthetic plate.
PATCHES = (0.10, 0.40, 0.80)
REFERENCE = PATCHES[0]          # the patch the audit measured errors against


@pytest.fixture
def linear16_tif(tmp_path):
    """A 16-bit LINEAR TIFF: three patches at exactly 10 / 40 / 80 % of full scale."""
    img = np.zeros((60, 300, 3), dtype=np.uint16)
    for i, frac in enumerate(PATCHES):
        img[:, i * 100:(i + 1) * 100, :] = np.uint16(round(frac * 65535))
    path = str(tmp_path / "linear16.tif")
    assert cv2.imwrite(path, img)
    return path


def _patch_means(gray):
    return [float(np.mean(gray[:, i * 100:(i + 1) * 100])) for i in range(len(PATCHES))]


def test_16bit_tiff_is_read_at_native_depth(linear16_tif):
    raw, info = pt.read_bgr_raw(linear16_tif)
    assert raw.dtype == np.uint16, "a 16-bit TIFF must not be downconverted to 8-bit"
    assert info["bit_depth"] == 16
    assert info["reader"].startswith("cv2")


def test_auto_transfer_treats_16bit_as_linear_and_8bit_as_srgb(linear16_tif):
    raw16, _ = pt.read_bgr_raw(linear16_tif)
    assert pt.choose_transfer(raw16) == "linear"
    assert pt.choose_transfer(pt.to_8bit(raw16)) == "srgb"


def test_linear_16bit_recovers_the_true_transmittance(linear16_tif):
    """The whole point: linear in, linear out, scaled by the FORMAT full scale."""
    raw, info = pt.read_bgr_raw(linear16_tif)
    gray = pt.to_linear_gray(raw, transfer=info and pt.choose_transfer(raw))
    got = _patch_means(gray)
    for expected, actual in zip(PATCHES, got):
        assert actual == pytest.approx(expected, abs=1e-3), (PATCHES, got)


def test_od_error_against_a_known_reference_is_now_negligible(linear16_tif):
    """OD = -log10(I/I0). With a linear read these must come out at the textbook
    values; the pre-fix path was off by 0.53 and 0.89 OD on these same patches."""
    raw, _ = pt.read_bgr_raw(linear16_tif)
    gray = pt.to_linear_gray(raw, transfer="linear")
    got = _patch_means(gray)
    i0 = got[0]
    for expected_frac, actual in zip(PATCHES, got):
        expected_od = -math.log10(expected_frac / REFERENCE)
        actual_od = -math.log10(actual / i0)
        assert actual_od == pytest.approx(expected_od, abs=0.01)


def test_the_old_behaviour_really_was_wrong(linear16_tif):
    """Guard-rail: forcing the sRGB path on linear data must still be visibly wrong,
    so this test fails loudly if someone ever makes 'srgb' the unconditional default
    again."""
    raw, _ = pt.read_bgr_raw(linear16_tif)
    wrong = _patch_means(pt.to_linear_gray(raw, transfer="srgb"))
    od_error = abs(-math.log10(wrong[2] / wrong[0]) - -math.log10(PATCHES[2] / REFERENCE))
    assert od_error > 0.3, "expected the sRGB-on-linear path to be badly wrong"


def test_full_scale_not_image_max(tmp_path):
    """Scaling must use the format full scale. A dim 16-bit frame (nothing near
    65535) must come back dim -- normalising by the per-image max would make every
    plate look identically bright and destroy cross-plate comparability."""
    img = np.full((20, 20, 3), np.uint16(6553), dtype=np.uint16)   # 10 % of full scale
    path = str(tmp_path / "dim16.tif")
    cv2.imwrite(path, img)
    raw, _ = pt.read_bgr_raw(path)
    gray = pt.to_linear_gray(raw, transfer="linear")
    assert float(np.mean(gray)) == pytest.approx(0.10, abs=1e-3)


def test_transfer_choice_is_recorded_in_the_output(linear16_tif, tmp_path):
    """PT-2 requires the path taken to be visible in the output, not just correct."""
    det = pt.detect_plate(linear16_tif, None, False)
    assert det["read_info"]["transfer"] == "linear"
    assert det["read_info"]["transfer_source"] == "auto"
    det2 = pt.detect_plate(linear16_tif, None, False, transfer="srgb")
    assert det2["read_info"]["transfer"] == "srgb"
    assert det2["read_info"]["transfer_source"] == "explicit"


def test_8bit_srgb_input_still_gets_the_gamma_undone(tmp_path):
    """The 8-bit photo path is unchanged: mid-grey 128 decodes to ~0.216 linear."""
    img = np.full((20, 20, 3), 128, dtype=np.uint8)
    path = str(tmp_path / "mid.png")
    cv2.imwrite(path, img)
    raw, _ = pt.read_bgr_raw(path)
    gray = pt.to_linear_gray(raw)
    expected = ((128 / 255.0 + 0.055) / 1.055) ** 2.4
    assert float(np.mean(gray)) == pytest.approx(expected, abs=1e-4)
