"""Part 3 (CT-R2 detection N2): the pixel range the STANDARD pass (CLI default) outlines well.

Not a benchmark scene: a finer size sweep drawn with the frozen scenes' own plate model
(scenes.make_plate: same lawn, halo / sharp disc types, blur and noise), isolated discs only,
measured by the CLI default. For each disc type and diameter in pixels it reports how many of the
replicates were found and their size bias, so one can read off

* the smallest diameter the standard pass finds, and from where it finds every disc;
* the largest diameter it still outlines within +-5 % every time, and the smallest that failed.

    python validation/detection_benchmark/standard_range.py --out <folder>
"""
import argparse
import math
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as H  # noqa: E402
import scenes as SC  # noqa: E402
import cv2  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

PPM = 34.0          # 90 mm dish = 3060 px; the standard pass's window is in pixels, not mm
SIZES_PX = {"halo": [100, 110, 120, 125, 130, 135, 140, 145, 150, 160, 170, 185, 200],
            "sharp": [16, 20, 24, 28, 32, 36, 40, 50, 60, 70, 80, 200, 225, 250, 275, 300, 350, 400]}
REPS = 3


def _discs(sizes_px):
    """Isolated discs on rings inside the lawn, well apart (mm coordinates for make_plate)."""
    out, gid = [], 0
    items = [(d / PPM) for d in sizes_px for _ in range(REPS)]
    items.sort(reverse=True)
    max_r = SC.DISH_MM / 2 * 0.80
    placed = []
    rng = np.random.default_rng(7)
    for D in items:
        for _k in range(200000):
            rr, a = max_r * math.sqrt(rng.uniform(0, 1)), rng.uniform(0, 2 * math.pi)
            x, y = rr * math.cos(a), rr * math.sin(a)
            if rr + D / 2 > max_r:
                continue
            if all(math.hypot(x - px, y - py) > (D + pd_) / 2 + 2.0 for px, py, pd_ in placed):
                placed.append((x, y, D))
                gid += 1
                out.append((x, y, D, "single", gid))
                break
        else:
            raise RuntimeError("could not place a %.1f px disc" % (D * PPM))
    return out


def run(out_dir):
    rows = []
    for typ, sizes in SIZES_PX.items():
        # three plates per type so the discs fit with room around each
        half = [sizes[0::3], sizes[1::3], sizes[2::3]]
        for k, ss in enumerate(half):
            discs = _discs(ss)
            img, truth, _dish = SC.make_plate(PPM, discs, typ, seed=100 + k)
            p = os.path.join(tempfile.gettempdir(), "std_range_%d_%s_%d.png" % (os.getpid(), typ, k))
            cv2.imwrite(p, img)
            try:
                g, _ = H.cli_run(p, SC.DISH_MM, small=False)
            finally:
                os.remove(p)
            tp = np.array([[d["x"], d["y"]] for d in truth])
            pp = g[["X", "Y"]].values.astype(float) if len(g) else np.zeros((0, 2))
            pairs = dict(H.match(tp, pp, SC.synth_tolerance(truth)))
            for i, d in enumerate(truth):
                j = pairs.get(i)
                rows.append(dict(typ=typ, D_px=round(d["D_px"], 1), found=j is not None,
                                 bias=(float(g["DIAMETER_PXL"].iloc[j]) / d["D_px"] - 1) if j is not None else None))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out_dir, "standard_range.csv"), index=False)
    for typ, d in df.groupby("typ"):
        print("\n==", typ)
        for D, dd in d.groupby("D_px"):
            b = dd["bias"].dropna()
            print("  %6.1f px  found %d/%d  bias %s" % (D, dd["found"].sum(), len(dd),
                                                         " ".join("%+.3f" % v for v in b)))
    return df


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    run(a.out)
