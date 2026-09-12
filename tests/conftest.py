"""Shared fixtures for the Plaque Toolkit test suite.

Design notes:
  * The engine modules keep their settings in module-level globals (inherited from
    upstream). Every test that touches them must restore them, so `engine_reset`
    is autouse.
  * Synthetic images are generated rather than committed, so the suite stays small
    and the expected values are derived from first principles rather than from a
    previous run of the code under test.
"""
import os
import sys

import numpy as np
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

TEST_PLATES = os.path.join(REPO_ROOT, "Test_plates")
SAMPLE_TIF = os.path.join(REPO_ROOT, "app", "resources", "sample.tif")


@pytest.fixture(autouse=True)
def engine_reset():
    """Restore plaque_size_tool's module-level settings after every test."""
    import plaque_size_tool as pst
    names = ("small_plaques", "debug_mode", "use_published", "watershed_enabled",
             "sensitive", "upstream_exact", "out_dir_path")
    saved = {n: getattr(pst, n) for n in names}
    yield
    for n, v in saved.items():
        setattr(pst, n, v)


@pytest.fixture
def neutral_plate_tif(tmp_path):
    """A neutral-grey synthetic plate: grey dish on black, with darker circular plaques.

    Perfectly neutral (R == G == B), so upstream's red-channel brightness statistic and
    the toolkit's BT.601 luma must agree exactly -- which is the premise of the
    'Published == upstream on neutral input' claim.
    """
    import cv2
    h = w = 900
    img = np.zeros((h, w, 3), dtype=np.uint8)
    cv2.circle(img, (w // 2, h // 2), 380, (150, 150, 150), -1)      # the lawn/dish
    for (cx, cy) in [(380, 380), (520, 400), (430, 540), (560, 550), (350, 500)]:
        cv2.circle(img, (cx, cy), 26, (70, 70, 70), -1)              # plaques
    path = str(tmp_path / "neutral_plate.tif")
    cv2.imwrite(path, img)
    return path


@pytest.fixture
def amber_plate_png(neutral_plate_tif, tmp_path):
    """The same plate with a warm amber colour cast (red boosted, blue cut).

    This is the case where upstream's red-channel brightness mean and BT.601 luma
    disagree -- see docs/UPSTREAM_EXACT.md.
    """
    import cv2
    img = cv2.imread(neutral_plate_tif)                              # BGR
    b, g, r = cv2.split(img.astype(np.float32))
    warm = cv2.merge([np.clip(b * 0.55, 0, 255),
                      np.clip(g * 0.95, 0, 255),
                      np.clip(r * 1.45, 0, 255)]).astype(np.uint8)
    path = str(tmp_path / "amber_plate.png")
    cv2.imwrite(path, warm)
    return path


@pytest.fixture
def blank_plate_png(tmp_path):
    """A featureless plate: a dish, no plaques. Must yield zero plaques, not a crash."""
    import cv2
    img = np.zeros((900, 900, 3), dtype=np.uint8)
    cv2.circle(img, (450, 450), 380, (150, 150, 150), -1)
    path = str(tmp_path / "blank_plate.png")
    cv2.imwrite(path, img)
    return path
