"""Unit test for the mm/px calibration unit trap.

plaque_gui's "pxl_per_mm" is mm-per-pixel (plate_mm / dish_diam_px). The dish JSON
written by pst_front.py stores it as mm_per_px and stores the dish diam_px. The
round-trip invariant that proves units are consistent is:

    dish_diam_px * mm_per_px  ==  plate_mm     (here, 100 mm)

Run in EITHER env (pure stdlib + json). Usage:
  python test_calibration.py PST_JSON [PST_JSON ...]
"""
import sys
import json


def check(path):
    d = json.load(open(path))
    plate = d.get("plate")
    mm_per_px = d.get("mm_per_px")
    plate_mm = d.get("plate_mm", 100.0)
    assert plate is not None, "%s: no dish detected" % path
    assert mm_per_px, "%s: no calibration" % path
    diam_px = plate["diam_px"]
    recovered = diam_px * mm_per_px
    err = abs(recovered - plate_mm)
    ok = err <= 0.5  # within 0.5 mm of the 100 mm plate
    print("%-28s diam_px=%9.2f  mm_per_px=%.6f  diam_px*mm_per_px=%.4f mm  err=%.4f  %s" % (
        d.get("image", path).split("\\")[-1], diam_px, mm_per_px, recovered, err,
        "PASS" if ok else "FAIL"))
    assert ok, "%s: calibration round-trip off by %.4f mm (expected ~%.1f)" % (
        path, err, plate_mm)
    # px_per_mm sanity: 1/mm_per_px should be a few tens of px per mm for these plates
    px_per_mm = 1.0 / mm_per_px
    assert 10 < px_per_mm < 60, "%s: px_per_mm=%.2f out of expected range" % (path, px_per_mm)
    return True


if __name__ == "__main__":
    paths = sys.argv[1:]
    if not paths:
        raise SystemExit("usage: python test_calibration.py PST_JSON [PST_JSON ...]")
    n = 0
    for p in paths:
        check(p)
        n += 1
    print("ALL %d CALIBRATION TESTS PASSED" % n)
