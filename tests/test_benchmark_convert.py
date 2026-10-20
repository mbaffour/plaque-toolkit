"""The VACVPlaque converter must turn instance masks into correct toolkit labels.

Synthetic plate: two wells (ids 1, 2) with known plaque discs; the labels written for each
well must list exactly its plaques, with centres, areas and radii that scale with --scale.
"""
import json
import math
import os
import sys

import numpy as np
import pytest
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "validation", "benchmarks"))

import vacvplaque_convert as vc  # noqa: E402


def _disc(mask, cx, cy, r, value):
    yy, xx = np.ogrid[: mask.shape[0], : mask.shape[1]]
    mask[(xx - cx) ** 2 + (yy - cy) ** 2 <= r * r] = value


@pytest.fixture
def synthetic_plate(tmp_path):
    H, W = 400, 800
    img = np.full((H, W, 3), 90, np.uint8)
    wells = np.zeros((H, W), np.uint16)
    plaques = np.zeros((H, W), np.uint16)
    _disc(wells, 200, 200, 150, 1)          # well 1, left
    _disc(wells, 600, 200, 150, 2)          # well 2, right
    _disc(plaques, 180, 190, 8, 1)          # two plaques in well 1
    _disc(plaques, 240, 230, 12, 2)
    _disc(plaques, 610, 170, 10, 3)         # one plaque in well 2
    split = tmp_path / "split"
    for sub in ("images", "plaque_masks", "well_masks"):
        (split / sub).mkdir(parents=True)
    Image.fromarray(img).save(split / "images" / "P.tif")
    Image.fromarray(plaques).save(split / "plaque_masks" / "P.tif")
    Image.fromarray(wells).save(split / "well_masks" / "P.tif")
    return split


def _labels(out_dir):
    out = {}
    for fn in sorted(os.listdir(out_dir)):
        if fn.startswith("labels_") and fn.endswith(".json"):
            out[fn] = json.load(open(os.path.join(out_dir, fn)))
    return out


def test_each_well_gets_only_its_own_plaques(synthetic_plate, tmp_path):
    out = tmp_path / "out"
    assert vc.main([str(synthetic_plate), str(out)]) == 0
    labels = _labels(out)
    assert sorted(labels) == ["labels_P_w1.json", "labels_P_w2.json"]
    w1, w2 = labels["labels_P_w1.json"], labels["labels_P_w2.json"]
    assert w1["meta"]["n_plaques"] == 2 and w2["meta"]["n_plaques"] == 1
    areas = sorted(p["area_px"] for p in w1["plaques"])
    assert areas[0] == pytest.approx(math.pi * 8 ** 2, rel=0.08)
    assert areas[1] == pytest.approx(math.pi * 12 ** 2, rel=0.08)
    # the well's equivalent diameter and the nominal mm/px follow from the well mask
    assert w1["meta"]["dish_diam_px"] == pytest.approx(300, rel=0.02)
    assert w1["meta"]["mm_per_px"] == pytest.approx(34.8 / 300, rel=0.02)
    assert os.path.exists(os.path.join(out, w1["meta"]["image"]))
    assert os.path.exists(os.path.join(out, "manifest.csv"))


def test_scale_factor_scales_every_coordinate(synthetic_plate, tmp_path):
    out1, out3 = tmp_path / "x1", tmp_path / "x3"
    vc.main([str(synthetic_plate), str(out1)])
    vc.main([str(synthetic_plate), str(out3), "--scale", "3"])
    a = _labels(out1)["labels_P_w2.json"]
    b = _labels(out3)["labels_P_w2.json"]
    pa, pb = a["plaques"][0], b["plaques"][0]
    assert pb["x_px"] == pytest.approx(3 * pa["x_px"], abs=0.2)
    assert pb["y_px"] == pytest.approx(3 * pa["y_px"], abs=0.2)
    assert pb["r_px"] == pytest.approx(3 * pa["r_px"], rel=1e-3)
    assert pb["area_px"] == pytest.approx(9 * pa["area_px"], rel=1e-3)
    assert pb["diam_mm"] == pytest.approx(pa["diam_mm"], rel=1e-3)      # mm is scale-free
    img_b = Image.open(os.path.join(out3, b["meta"]["image"]))
    img_a = Image.open(os.path.join(out1, a["meta"]["image"]))
    assert img_b.size[0] == pytest.approx(3 * img_a.size[0], abs=2)
