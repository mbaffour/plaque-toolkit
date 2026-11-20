"""Synthetic sweep: are the sizes of Auto's SPLIT plaques good enough for size summaries?
(CT-R1 detection D10c.)

Haloed discs (dark core 70 inside a paler halo 110 on a 150 lawn; core diameter 0.37 x the halo
diameter D, as on sample.tif) are drawn as a centre disc touched by k = 1, 2 or 3 neighbours at
centre distance s x D, for D = 40, 80, 120, 200 px, s = 0.6 ... 1.2, with and without mild noise
+ blur. Three isolated reference plaques of the same D sit on the plate (real plates have
standard plaques; they set Auto's size cap). Each plate is run through the app's Auto
(engine_api.detect_single(scale="auto")) and every SPLIT piece is matched to its true disc.

Writes split_size_sweep.csv (one row per true disc) and prints the summary tables. Run from the
repo root:  python validation/split_sweep/split_size_sweep.py [OUT_DIR]
"""
import math
import os
import sys
import tempfile

import cv2
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

DS = (40, 80, 120, 200)
KS = (1, 2, 3)
SS = (0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2)
NOISE = (False, True)
CENTRE = (800, 800)
REFS = ((500, 400), (1100, 400), (800, 1300))


def draw(D, k, s, noisy, seed=0):
    R, r = D / 2.0, 0.37 * D / 2.0
    img = np.zeros((1600, 1600, 3), np.uint8)
    cv2.circle(img, CENTRE, 720, (150, 150, 150), -1)
    angles = {1: [0.0], 2: [0.0, 180.0], 3: [0.0, 120.0, 240.0]}[k]
    discs = [CENTRE] + [(int(round(CENTRE[0] + s * D * math.cos(math.radians(a)))),
                         int(round(CENTRE[1] + s * D * math.sin(math.radians(a))))) for a in angles]
    for c in discs + list(REFS):
        cv2.circle(img, c, int(round(R)), (110, 110, 110), -1)
    for c in discs + list(REFS):
        cv2.circle(img, c, int(round(r)), (70, 70, 70), -1)
    img = cv2.GaussianBlur(img, (7, 7), 0)
    if noisy:
        rng = np.random.default_rng(seed)
        img = np.clip(img.astype(np.float32) + rng.normal(0, 4, img.shape), 0, 255).astype(np.uint8)
        img = cv2.GaussianBlur(img, (5, 5), 0)
    cuts = [k] + [1] * k
    return img, discs, cuts


def run(out_dir):
    from app import engine_api
    rows = []
    tmp = tempfile.mkdtemp(prefix="split_sweep_")
    for D in DS:
        for k in KS:
            for s in SS:
                for noisy in NOISE:
                    img, discs, cuts = draw(D, k, s, noisy, seed=D * 100 + k * 10 + int(s * 10))
                    path = os.path.join(tmp, "p.png")
                    cv2.imwrite(path, img)
                    det = engine_api.detect_single(path, plate_mm=90, scale="auto")
                    for i, (c, ct) in enumerate(zip(discs, cuts)):
                        hit = [p for p in det["plaques"]
                               if math.hypot(p["center"][0] - c[0], p["center"][1] - c[1]) < 0.35 * D]
                        p = min(hit, key=lambda q: math.hypot(q["center"][0] - c[0], q["center"][1] - c[1])) \
                            if hit else None
                        outcome = ("lost" if p is None else "CORE?" if p.get("core_only") else p["source"])
                        d = 2 * math.sqrt(p["area_pxl"] / math.pi) if p is not None else float("nan")
                        rows.append({"D_px": D, "k_neighbours": k, "s": s, "noisy": noisy,
                                     "disc": "centre" if i == 0 else "neighbour", "cuts_true": ct,
                                     "outcome": outcome, "d_px": round(d, 2),
                                     "bias": round(d / D - 1.0, 4) if p is not None else float("nan"),
                                     "cut_by": (p or {}).get("cut_by"),
                                     "cut_ratio": (round(p["cut_ratio"], 3)
                                                   if p is not None and p.get("cut_ratio") else None)})
                    print(D, k, s, noisy, [r["outcome"] for r in rows[-len(discs):]], flush=True)
    df = pd.DataFrame(rows)
    os.makedirs(out_dir, exist_ok=True)
    df.to_csv(os.path.join(out_dir, "split_size_sweep.csv"), index=False)
    return df


def summarise(df):
    sp = df[df["outcome"] == "split"]
    t1 = sp.groupby(["cuts_true", "s"])["bias"].agg(["count", "mean", "std"]).round(3)
    t2 = df.groupby(["cuts_true", "s"])["outcome"].value_counts().unstack(fill_value=0)
    sp = sp.assign(ratio_bin=pd.cut(sp["cut_ratio"], [0, 0.6, 0.7, 0.8, 0.9, 1.0, 2.0]))
    t3 = sp.groupby(["cut_by", "ratio_bin"], observed=True)["bias"].agg(["count", "mean", "std"]).round(3)
    return t1, t2, t3


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
    df = run(out)
    for t in summarise(df):
        print(t.to_string())
