"""Per-plaque quality flags: which rows deserve a second look.

The engines already compute everything needed to say *why* a plaque might be unreliable
(touching the rim, far larger than its neighbours, below the standard size gate, overlapping
another, a low classifier score) but threw that away: a CSV listed accepted plaques and
nothing else, so a user had to eyeball every one. These flags are **purely additive** and
never alter a measurement. On the CLI they are opt-in (`plaque_size_tool.py --qc`) so the
default `data-green-*.csv` stays byte-identical to the frozen baseline; in the desktop app's
table and batch exports they are always present as a `QC_FLAG` column.

Flags (several may apply, joined with `|`; `OK` when none):

* ``EDGE``     the plaque's area-equivalent disk touches the image border or reaches the LAWN
               edge, ``rim_frac`` (0.93) of the dish radius. (Until 2026-11 it was 0.98 of the
               radius, beyond where the lawn ends, so it never fired on a real plate; CT-R1 F11.)
* ``LARGE?``   area is more than ``merged_factor`` x the plate's median plaque area while the
               shape is normal -- a big plaque, worth a look, not necessarily two.
* ``MERGED?``  the outline is not one convex blob: solidity (raw contour area / convex-hull
               area) below ``min_solidity`` (0.9), or a fitted ellipse longer than
               ``max_axis_ratio`` (1.5) x its width -- likely two plaques, or an outline that
               did not close. (The old circularity test could never fire; CT-R1 F12.) A
               ``circularity`` below ``min_circularity`` still counts when it is given.
* ``NESTED``   its centre lies inside a LARGER plaque's outline (a core and its halo, or a plaque
               counted inside another; CT-R1 F14).
* ``TINY``     the plaque exists only because of the small-scale / sensitive gates: found only by
               the small pass of the Auto plaque size (``source`` "small"), or its enclosing
               diameter is at or below the standard gate (30 px; the reason gives it in mm when a
               scale is known). The app now passes the enclosing diameter (it never did: F13).
* ``BRIGHT``   the plaque interior is brighter than a ring around it by more than
               ``bright_margin`` grey levels: a bubble or glare, not a clearing (CT-R1 F19). Only
               when the brightness is known and the engine expects dark plaques.
* ``OVERLAP``  its disk overlaps another plaque's disk (sizes of both are unreliable).
* ``LOW_CONF`` the Precise classifier scored it below ``low_conf`` (only when a score exists).

Input is a list of dicts with ``x``, ``y``, ``area_px`` and optionally ``encl_diam_px``,
``circularity`` (0-1), ``solidity`` (0-1), ``axis_ratio`` (>= 1), ``hull`` (list of (x, y)),
``source``, ``inside_mean`` / ``ring_mean`` (grey levels) and ``p_plaque``; ``dish`` is
``(cx, cy, r)`` in pixels or ``None``; ``image_shape`` is ``(H, W)``.
"""
import math

STANDARD_ENCL_DIAM_MIN = 30      # plaque_size_tool.filter_contours: green_diam_min without -small
LAWN_EDGE_FRAC = 0.93            # where the lawn ends, as a fraction of the dish radius (F11)


def _point_in_poly(x, y, poly):
    """Ray casting; ``poly`` is a sequence of (x, y)."""
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = float(poly[i][0]), float(poly[i][1])
        xj, yj = float(poly[j][0]), float(poly[j][1])
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def flag_plaques(plaques, image_shape, dish=None, merged_factor=2.5, min_circularity=0.6,
                 low_conf=0.6, rim_frac=LAWN_EDGE_FRAC, standard_encl_diam_min=STANDARD_ENCL_DIAM_MIN,
                 min_solidity=0.9, max_axis_ratio=1.5, bright_margin=5.0, mm_per_px=None,
                 expect_dark=True):
    """Return a list of (QC_FLAG, QC_REASON) strings, one per plaque, in input order."""
    n = len(plaques)
    if n == 0:
        return []
    H, W = int(image_shape[0]), int(image_shape[1])
    geo = []
    for p in plaques:
        a = max(float(p.get("area_px", 0.0) or 0.0), 0.0)
        r = math.sqrt(a / math.pi) if a > 0 else 0.0
        geo.append((float(p["x"]), float(p["y"]), r, a))
    areas = sorted(g[3] for g in geo if g[3] > 0)
    median_area = areas[len(areas) // 2] if areas else 0.0

    # pairwise overlap of area-equivalent disks (O(n^2); plates have at most a few hundred)
    overlap = [False] * n
    nested = [False] * n
    for i in range(n):
        xi, yi, ri, ai = geo[i]
        for j in range(i + 1, n):
            xj, yj, rj, aj = geo[j]
            if ri > 0 and rj > 0 and math.hypot(xi - xj, yi - yj) < ri + rj:
                overlap[i] = overlap[j] = True
                # NESTED: the smaller one's centre inside the larger one's outline (its hull, or
                # its area-equivalent disk when no outline is given)
                if ai != aj:
                    s, b = (i, j) if ai < aj else (j, i)
                    hb = plaques[b].get("hull")
                    xs, ys = geo[s][0], geo[s][1]
                    if hb is not None and len(hb) >= 3:
                        inside = _point_in_poly(xs, ys, hb)
                    else:
                        inside = math.hypot(xs - geo[b][0], ys - geo[b][1]) < geo[b][2]
                    if inside:
                        nested[s] = True

    out = []
    for i, p in enumerate(plaques):
        x, y, r, a = geo[i]
        flags, why = [], []
        if x - r <= 0 or y - r <= 0 or x + r >= W - 1 or y + r >= H - 1:
            flags.append("EDGE"); why.append("touches the image border")
        elif dish is not None:
            cx, cy, dr = dish
            if dr and math.hypot(x - cx, y - cy) + r >= rim_frac * dr:
                flags.append("EDGE"); why.append("reaches the lawn edge (%.2f of the dish radius)" % rim_frac)
        # Size and shape are separate questions (click-through round 1, F24): a ROUND plaque
        # that is merely big used to be called "MERGED?" too. Big + normal shape = LARGE?;
        # not one convex blob = MERGED? (its reason also says how big it is, when it is big).
        big = median_area > 0 and n >= 4 and a > merged_factor * median_area
        shape_why = []
        sol = p.get("solidity")
        if sol is not None and sol == sol and float(sol) < min_solidity:
            shape_why.append("solidity %.2f" % float(sol))
        ar = p.get("axis_ratio")
        if ar is not None and ar == ar and float(ar) > max_axis_ratio:
            shape_why.append("elongated (axis ratio %.2f)" % float(ar))
        circ = p.get("circularity")
        if circ is not None and circ == circ and float(circ) < min_circularity:
            shape_why.append("circularity %.2f" % float(circ))
        if shape_why:
            why_m = "; ".join(shape_why)
            if big:
                why_m = "area %.1fx the plate median; " % (a / median_area) + why_m
            flags.append("MERGED?"); why.append(why_m)
        elif big:
            flags.append("LARGE?"); why.append("area %.1fx the plate median" % (a / median_area))
        if nested[i]:
            flags.append("NESTED"); why.append("its centre lies inside a larger plaque")
        ed = p.get("encl_diam_px")
        if p.get("source") == "small":
            flags.append("TINY"); why.append("found only by the small-scale pass")
        elif ed is not None and float(ed) <= standard_encl_diam_min:
            if mm_per_px:
                why.append("enclosing diameter %.2f mm is at/below the standard gate (%.2f mm)"
                           % (float(ed) * mm_per_px, standard_encl_diam_min * mm_per_px))
            else:
                why.append("enclosing diameter %.0f px is at/below the standard gate (%d px)"
                           % (float(ed), standard_encl_diam_min))
            flags.append("TINY")
        im, rm = p.get("inside_mean"), p.get("ring_mean")
        if expect_dark and im is not None and rm is not None and float(im) - float(rm) > bright_margin:
            flags.append("BRIGHT")
            why.append("brighter inside than around it (%+.0f grey levels): a bubble or glare?"
                       % (float(im) - float(rm)))
        if overlap[i]:
            flags.append("OVERLAP"); why.append("disk overlaps another plaque")
        pp = p.get("p_plaque")
        if pp is not None and pp == pp and float(pp) < low_conf:
            flags.append("LOW_CONF"); why.append("classifier P(plaque) = %.2f" % float(pp))
        out.append(("|".join(flags) if flags else "OK", "; ".join(why)))
    return out


def outline_geometry(contour):
    """(axis_ratio, hull points) of an outline (Nx2 / Nx1x2 points), via OpenCV."""
    import cv2
    import numpy as np
    c = np.asarray(contour, dtype=np.int32).reshape(-1, 2)
    ar = None
    if len(c) >= 5:
        try:
            (_c, (a1, a2), _ang) = cv2.fitEllipse(c.astype(np.float32))
            lo, hi = min(a1, a2), max(a1, a2)
            ar = (hi / lo) if lo > 0 else None
        except Exception:
            ar = None
    hull = cv2.convexHull(c.reshape(-1, 1, 2)).reshape(-1, 2)
    return ar, [(float(px), float(py)) for px, py in hull]


def inside_and_ring_mean(gray, mask_fn, x, y, r):
    """Mean grey inside a plaque and in a ring of width ~r/2 around it, computed in a window
    around the plaque (not the whole image: the table refreshes on every edit). ``mask_fn``
    draws the plaque into a given (shape, offset) and returns a uint8 mask."""
    import cv2
    import numpy as np
    k = max(3, int(round(0.5 * r)))
    H, W = gray.shape[:2]
    x0, y0 = max(0, int(x - r - k - 2)), max(0, int(y - r - k - 2))
    x1, y1 = min(W, int(x + r + k + 3)), min(H, int(y + r + k + 3))
    if x1 - x0 < 3 or y1 - y0 < 3:
        return None, None
    win = gray[y0:y1, x0:x1]
    m = mask_fn(win.shape, (x0, y0))
    dil = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * k + 1, 2 * k + 1)))
    ring = (dil > 0) & (m == 0)
    if not (m > 0).any() or not ring.any():
        return None, None
    return float(win[m > 0].mean()), float(win[ring].mean())


DISH_MIN_FRAC = 0.30        # dish diameter below this fraction of the short side: implausible
DISH_OFFCENTRE_FRAC = 0.25  # dish centre further than this fraction of the short side from the centre
MIN_SHORT_SIDE_PX = 600     # below this the pixel size gates swallow most plaques (CT-R1 F23)


def _dish_tuple(dish):
    if dish is None:
        return None
    if isinstance(dish, dict):
        if not dish.get("center") or not dish.get("radius"):
            return None
        return float(dish["center"][0]), float(dish["center"][1]), float(dish["radius"])
    cx, cy, r = dish
    return float(cx), float(cy), float(r)


def dish_too_small(dish, image_shape):
    """True when the 'dish' is under DISH_MIN_FRAC of the image's short side: most likely a
    plaque or another round object taken for the dish (a close-up with no rim; CT-R1 F9)."""
    d = _dish_tuple(dish)
    if d is None:
        return False
    return 2.0 * d[2] < DISH_MIN_FRAC * min(int(image_shape[0]), int(image_shape[1]))


def dish_plausibility(dish, image_shape):
    """Plain-language warnings about the dish the calibration scales from, and about images
    too small to measure reliably (CT-R1 detection D4: F4, F9, F23). Never changes a number:
    the app shows them under the summary, the CLI prints them, both record them in
    run_metadata.json. ``dish`` is the app's plate dict, ``(cx, cy, r)`` in px, or None;
    ``image_shape`` is (H, W[, C])."""
    H, W = int(image_shape[0]), int(image_shape[1])
    short = min(H, W)
    out = []
    if short < MIN_SHORT_SIDE_PX:
        out.append("The image is only %d px on its short side: plaques under ~30 px are not "
                   "detected and the dish may be missed. Use a higher-resolution photo." % short)
    d = _dish_tuple(dish)
    if d is None:
        return out
    cx, cy, r = d
    if dish_too_small(d, image_shape):
        out.append("The dish found is only %.0f%% of the image's short side, so it is probably a "
                   "plaque or another round object, not the dish: mm sizes are likely wrong. Use "
                   "Set plate on the real rim, or photograph the whole dish."
                   % (100.0 * 2.0 * r / short))
    off = math.hypot(cx - W / 2.0, cy - H / 2.0)
    if off > DISH_OFFCENTRE_FRAC * short:
        out.append("The dish found is far from the image centre (%.0f px off); check that its "
                   "circle sits on the real rim." % off)
    if cx - r < 2 or cy - r < 2 or cx + r > W - 3 or cy + r > H - 3:
        out.append("The dish touches or runs past the edge of the photo, so its rim may be cut "
                   "off and the mm scale biased. Leave a margin around the dish.")
    return out


def flags_for_dataframe(df, image_shape, dish=None, gray=None, **kw):
    """plaque_size_tool-style frame (ENCL_CENTER, AREA_PXL, ENCL_DIAMETER_PXL, CONTOURS, HULL)
    -> two lists aligned with df.index. ``gray`` (the original image in grey) enables BRIGHT."""
    import numpy as np
    plaques = []
    for _, row in df.iterrows():
        cx, cy = row["ENCL_CENTER"][0], row["ENCL_CENTER"][1]
        rec = {"x": cx, "y": cy, "area_px": float(row["AREA_PXL"]),
               "encl_diam_px": float(row.get("ENCL_DIAMETER_PXL", 0) or 0),
               "source": row.get("SOURCE")}
        try:
            import cv2
            raw = np.asarray(row["CONTOURS"], dtype=np.int32)
            ha = float(row["AREA_PXL"])
            rec["solidity"] = float(cv2.contourArea(raw)) / ha if ha > 0 else None
            rec["axis_ratio"], rec["hull"] = outline_geometry(row["HULL"])
            if gray is not None:
                hull = np.asarray(row["HULL"], dtype=np.int32).reshape(-1, 2)

                def _mask(shape, off, _h=hull):
                    m = np.zeros(shape[:2], np.uint8)
                    cv2.drawContours(m, [(_h - np.array(off, dtype=np.int32)).reshape(-1, 1, 2)], -1, 255, -1)
                    return m
                r = math.sqrt(max(ha, 1.0) / math.pi)
                rec["inside_mean"], rec["ring_mean"] = inside_and_ring_mean(gray, _mask, cx, cy, r)
        except Exception:
            pass
        plaques.append(rec)
    res = flag_plaques(plaques, image_shape, dish=dish, **kw)
    return [f for f, _ in res], [w for _, w in res]


def flags_for_plaque_dicts(plaques, image_shape, plate=None, circularities=None, gray=None,
                           mm_per_px=None, **kw):
    """App-side plaque dicts (center, area_pxl, kind, contour / radius, optional source,
    solidity, encl_diam_px, p_plaque) -> list of (flag, reason). ``gray`` enables BRIGHT;
    ``mm_per_px`` puts TINY's reason in millimetres. The enclosing diameter is now passed for
    every plaque (CT-R1 F13: it never was, so TINY never fired in the app)."""
    import numpy as np
    recs = []
    for i, p in enumerate(plaques):
        cx, cy = p["center"]
        a = float(p.get("area_pxl", 0.0) or 0.0)
        rec = {"x": float(cx), "y": float(cy), "area_px": a,
               "circularity": (circularities[i] if circularities is not None else None),
               "p_plaque": p.get("p_plaque"), "source": p.get("source"),
               "solidity": p.get("solidity"), "encl_diam_px": p.get("encl_diam_px")}
        try:
            import cv2
            if p.get("kind") == "circle" and p.get("radius"):
                rad = float(p["radius"])
                if rec["encl_diam_px"] is None:
                    rec["encl_diam_px"] = 2.0 * rad

                def _mask(shape, off, _c=(cx, cy), _r=rad):
                    m = np.zeros(shape[:2], np.uint8)
                    cv2.circle(m, (int(round(_c[0] - off[0])), int(round(_c[1] - off[1]))),
                               int(round(_r)), 255, -1)
                    return m
            else:
                c = np.asarray(p["contour"], dtype=np.int32).reshape(-1, 2)
                if rec["encl_diam_px"] is None and len(c):
                    rec["encl_diam_px"] = 2.0 * float(cv2.minEnclosingCircle(c.reshape(-1, 1, 2))[1])
                rec["axis_ratio"], rec["hull"] = outline_geometry(c)

                def _mask(shape, off, _c=c):
                    m = np.zeros(shape[:2], np.uint8)
                    cv2.drawContours(m, [(_c - np.array(off, dtype=np.int32)).reshape(-1, 1, 2)], -1, 255, -1)
                    return m
            # BRIGHT only for the classic detectors, which look for dark clearings; Precise's
            # model plaques (they carry p_plaque) are not judged on polarity
            if gray is not None and p.get("p_plaque") is None:
                rec["inside_mean"], rec["ring_mean"] = inside_and_ring_mean(
                    gray, _mask, cx, cy, math.sqrt(max(a, 1.0) / math.pi))
        except Exception:
            pass
        recs.append(rec)
    dish = None
    if plate and plate.get("center") and plate.get("radius"):
        dish = (float(plate["center"][0]), float(plate["center"][1]), float(plate["radius"]))
    return flag_plaques(recs, image_shape, dish=dish, mm_per_px=mm_per_px, **kw)
