"""FROZEN synthetic scenes of the detection benchmark (CT-R2 detection, Part 2).

These are the round-2 tester's scenes exactly as written (c_synth.py and c_split.py), only
refactored into functions so they can be imported. DO NOT change a scene, add easier ones or drop
hard ones: the benchmark exists to judge sizing rules on scenes nobody tuned them on. A new
scene goes in a new, separately named group, never into these.

synth (c_synth.py) -- lawn model calibrated on the bundled plates; truth = the outer diameter D:
  sharp : one uniform clearing of diameter D (depth 25 % of the lawn)
  halo  : dark core 0.37 D (depth 55 %) inside a paler halo D (depth 22 %)  [sample.tif-like]
  isolated singles 0.5-8 mm x 3, touching pairs at centre distance 0.8 D and 1.0 D (D = 2, 4,
  6 mm), triangles of 3 at 0.9 D (D = 3 mm); 12, 23.5 and 34 px/mm on a 90 mm dish.
split (c_split.py) -- the split sweep's drawing (core 70 / halo 110 / lawn 150, core 0.37 D,
  3 reference plaques) outside the sweep: unequal neighbours (0.6x, 1.6x), soft edges + noise,
  two neighbours 90 degrees apart; D = 80, 120 px; s = 0.7-1.0; 40 scenes.
"""
import math

import cv2
import numpy as np

# ----------------------------------------------------------------------------- synth (C1)
DISH_MM = 90.0
LAWN_FRAC = 0.95
SINGLES = [0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0]
SYNTH_PPMS = (12.0, 23.5, 34.0)
SYNTH_TYPES = ("sharp", "halo")


def groups(rng):
    g = []
    for D in SINGLES:
        for _ in range(3):
            g.append([(0.0, 0.0, D, "single")])
    for D in (2.0, 4.0, 6.0):
        for s in (0.8, 1.0):
            g.append([(-s * D / 2, 0.0, D, "pair%.1f" % s), (s * D / 2, 0.0, D, "pair%.1f" % s)])
    for _ in range(2):
        D, s = 3.0, 0.9
        g.append([(s * D / math.sqrt(3) * math.cos(a), s * D / math.sqrt(3) * math.sin(a), D, "tri0.9")
                  for a in (math.pi / 2, math.pi / 2 + 2 * math.pi / 3, math.pi / 2 + 4 * math.pi / 3)])
    return g


def layout(rng, max_r=DISH_MM / 2 * 0.80, gap=2.0):
    out, placed = [], []
    gs = groups(rng)
    gs.sort(key=lambda gr: -max(math.hypot(x, y) + D / 2 for x, y, D, _ in gr))
    for gr in gs:
        br = max(math.hypot(x, y) + D / 2 for x, y, D, _ in gr)
        for _ in range(20000):
            a, rr = rng.uniform(0, 2 * math.pi), max_r * math.sqrt(rng.uniform(0, 1))
            x, y = rr * math.cos(a), rr * math.sin(a)
            if rr + br > max_r:
                continue
            if all(math.hypot(x - px, y - py) > br + pb + gap + 0.5 * max(br, pb) for px, py, pb in placed):
                placed.append((x, y, br))
                rot = rng.uniform(0, 2 * math.pi)
                for gx, gy, D, kind in gr:
                    out.append((x + gx * math.cos(rot) - gy * math.sin(rot),
                                y + gx * math.sin(rot) + gy * math.cos(rot), D, kind, len(placed)))
                break
        else:
            print("could not place group", gr[0])
    return out


def make_plate(ppm, discs, typ, seed=0, psf=1.2, noise=1.4):
    rng = np.random.default_rng(seed)
    R = DISH_MM * ppm / 2.0
    W = int(round(2 * R / 0.70)); Hh = int(round(W * 0.75))
    cx, cy = W / 2.0, Hh / 2.0
    yy, xx = np.mgrid[0:Hh, 0:W].astype(np.float32)
    r = np.hypot(xx - cx, yy - cy)
    Rl = LAWN_FRAC * R
    rho = np.clip(r / Rl, 0, 1.2)
    lawn = 80.0 + 50.0 * rho ** 4 + 60.0 * rho ** 14
    halo = np.zeros((Hh, W), np.float32); core = np.zeros((Hh, W), np.float32)
    truth = []
    for (xm, ym, D, kind, gid) in discs:
        px, py = cx + xm * ppm, cy + ym * ppm
        for layer, rad in ((halo, D * ppm / 2.0), (core, 0.37 * D * ppm / 2.0)):
            if typ == "sharp" and layer is core:
                continue
            pad = int(rad + 4)
            x0, x1 = max(int(px) - pad, 0), min(int(px) + pad + 1, W)
            y0, y1 = max(int(py) - pad, 0), min(int(py) + pad + 1, Hh)
            ss = 4
            gy, gx = np.mgrid[y0 * ss:y1 * ss, x0 * ss:x1 * ss].astype(np.float32)
            d = np.hypot((gx + 0.5) / ss - 0.5 - px, (gy + 0.5) / ss - 0.5 - py)
            c = cv2.resize((d <= rad).astype(np.float32), (x1 - x0, y1 - y0), interpolation=cv2.INTER_AREA)
            layer[y0:y1, x0:x1] = np.maximum(layer[y0:y1, x0:x1], c)
        truth.append(dict(x=px, y=py, D_mm=D, D_px=D * ppm, kind=kind, gid=gid))
    if typ == "sharp":
        img = lawn * (1.0 - 0.25 * halo)
    else:
        img = lawn * (1.0 - 0.22 * halo - 0.33 * core)
    tex = cv2.GaussianBlur(rng.normal(0, 1, (Hh, W)).astype(np.float32), (0, 0), 8.0)
    img += tex / (tex.std() + 1e-9)
    img[r > Rl] = 170.0
    img[r > 0.985 * R] = 250.0
    img[r > R] = 4.0
    img = cv2.GaussianBlur(img, (0, 0), psf)
    img += rng.normal(0, noise, (Hh, W)).astype(np.float32)
    u8 = np.clip(img + 0.5, 0, 255).astype(np.uint8)
    return cv2.cvtColor(u8, cv2.COLOR_GRAY2BGR), truth, 2 * R


def synth_scene(ppm, typ):
    """(BGR image, truth list of dicts, true dish px) for one synth plate, with the tester's seeds."""
    rng = np.random.default_rng(int(ppm * 10) + (0 if typ == "sharp" else 1))
    discs = layout(rng)
    return make_plate(ppm, discs, typ, seed=int(ppm))


def synth_tolerance(truth):
    """The tester's matching tolerance per true disc (px)."""
    return np.array([max(4.0, 0.35 * d["D_px"]) for d in truth])


# ----------------------------------------------------------------------------- split (C2)
SPLIT_C = (800, 800)
SPLIT_REFS = ((500, 400), (1100, 400), (800, 1300))
SPLIT_MM = 90


def split_draw(discs, refD, soft=0.0, noise=0.0, seed=0):
    C = SPLIT_C
    img = np.zeros((1600, 1600), np.float32)
    cv2.circle(img, C, 720, 150, -1)
    halo = np.zeros_like(img); core = np.zeros_like(img)
    for (x, y, D) in discs + [(rx, ry, refD) for rx, ry in SPLIT_REFS]:
        cv2.circle(halo, (int(round(x)), int(round(y))), int(round(D / 2)), 1.0, -1)
        cv2.circle(core, (int(round(x)), int(round(y))), int(round(0.37 * D / 2)), 1.0, -1)
    if soft:
        halo = cv2.GaussianBlur(halo, (0, 0), soft); core = cv2.GaussianBlur(core, (0, 0), soft * 0.5)
    inside = img > 0
    img = np.where(inside, 150 - 40 * halo - 40 * core, 0)
    img = cv2.GaussianBlur(img, (7, 7), 0)
    if noise:
        img += np.random.default_rng(seed).normal(0, noise, img.shape)
        img = cv2.GaussianBlur(img, (3, 3), 0)
    return cv2.cvtColor(np.clip(img, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)


def split_cases():
    """[(var, D, s, discs, soft, noise)] in the tester's order (the index is the noise seed)."""
    C = SPLIT_C
    cases = []
    for D in (80, 120):
        for s in (0.7, 0.8, 0.9, 1.0):
            for r in (0.6, 1.6):
                Dn = r * D; dist = s * (D + Dn) / 2
                cases.append(("unequal r=%.1f" % r, D, s, [(C[0], C[1], D), (C[0] + dist, C[1], Dn)], 0, 0))
            for k in (1, 2):
                ds = [(C[0], C[1], D)] + [(C[0] + s * D * math.cos(a), C[1] + s * D * math.sin(a), D)
                                          for a in ([0.0] if k == 1 else [0.0, math.pi])]
                cases.append(("soft k=%d" % k, D, s, ds, 0.05 * D, 6.0))
            ds = [(C[0], C[1], D), (C[0] + s * D, C[1], D), (C[0], C[1] + s * D, D)]
            cases.append(("angle90 k=2", D, s, ds, 0, 0))
    return cases


def split_scene(i):
    """(BGR image, discs [(x, y, D_px)], case tuple) for split case i (0-39)."""
    case = split_cases()[i]
    var, D, s, discs, soft, noise = case
    return split_draw(discs, D, soft, noise, seed=i), discs, case
