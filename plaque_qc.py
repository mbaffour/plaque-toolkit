"""Per-plaque quality flags: which rows deserve a second look.

The engines already compute everything needed to say *why* a plaque might be unreliable
(touching the rim, far larger than its neighbours, below the standard size gate, overlapping
another, a low classifier score) but threw that away: a CSV listed accepted plaques and
nothing else, so a user had to eyeball every one. These flags are **purely additive** and
never alter a measurement. On the CLI they are opt-in (`plaque_size_tool.py --qc`) so the
default `data-green-*.csv` stays byte-identical to the frozen baseline; in the desktop app's
table and batch exports they are always present as a `QC_FLAG` column.

Flags (several may apply, joined with `|`; `OK` when none):

* ``EDGE``     the plaque's area-equivalent disk touches the image border or the dish rim.
* ``MERGED?``  area is more than ``merged_factor`` × the plate's median plaque area, or the
               shape is far from round (circularity below ``min_circularity``) -- likely two
               plaques counted as one.
* ``TINY``     the enclosing diameter is at or below the standard (non-``-small``) gate, so
               the plaque exists only because of ``-small`` / ``--sensitive``.
* ``OVERLAP``  its disk overlaps another plaque's disk (sizes of both are unreliable).
* ``LOW_CONF`` the Precise classifier scored it below ``low_conf`` (only when a score exists).

Input is a list of dicts with ``x``, ``y``, ``area_px`` and optionally ``encl_diam_px``,
``circularity`` (0-1, 1 = perfect circle) and ``p_plaque``; ``dish`` is ``(cx, cy, r)`` in
pixels or ``None``; ``image_shape`` is ``(H, W)``.
"""
import math

STANDARD_ENCL_DIAM_MIN = 30      # plaque_size_tool.filter_contours: green_diam_min without -small


def flag_plaques(plaques, image_shape, dish=None, merged_factor=2.5, min_circularity=0.6,
                 low_conf=0.6, rim_frac=0.98, standard_encl_diam_min=STANDARD_ENCL_DIAM_MIN):
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
    for i in range(n):
        xi, yi, ri, _ = geo[i]
        for j in range(i + 1, n):
            xj, yj, rj, _ = geo[j]
            if ri > 0 and rj > 0 and math.hypot(xi - xj, yi - yj) < ri + rj:
                overlap[i] = overlap[j] = True

    out = []
    for i, p in enumerate(plaques):
        x, y, r, a = geo[i]
        flags, why = [], []
        if x - r <= 0 or y - r <= 0 or x + r >= W - 1 or y + r >= H - 1:
            flags.append("EDGE"); why.append("touches the image border")
        elif dish is not None:
            cx, cy, dr = dish
            if dr and math.hypot(x - cx, y - cy) + r >= rim_frac * dr:
                flags.append("EDGE"); why.append("touches the dish rim")
        merged = []
        if median_area > 0 and n >= 4 and a > merged_factor * median_area:
            merged.append("area %.1fx the plate median" % (a / median_area))
        circ = p.get("circularity")
        if circ is not None and circ < min_circularity:
            merged.append("circularity %.2f" % float(circ))
        if merged:
            flags.append("MERGED?"); why.append("; ".join(merged))
        ed = p.get("encl_diam_px")
        if ed is not None and float(ed) <= standard_encl_diam_min:
            flags.append("TINY"); why.append("enclosing diameter %.0f px is at/below the standard gate (%d px)" % (float(ed), standard_encl_diam_min))
        if overlap[i]:
            flags.append("OVERLAP"); why.append("disk overlaps another plaque")
        pp = p.get("p_plaque")
        if pp is not None and pp == pp and float(pp) < low_conf:
            flags.append("LOW_CONF"); why.append("classifier P(plaque) = %.2f" % float(pp))
        out.append(("|".join(flags) if flags else "OK", "; ".join(why)))
    return out


def flags_for_dataframe(df, image_shape, dish=None, **kw):
    """plaque_size_tool-style frame (ENCL_CENTER, AREA_PXL, ENCL_DIAMETER_PXL, optional
    circularity proxy) -> two lists aligned with df.index."""
    plaques = []
    for _, row in df.iterrows():
        cx, cy = row["ENCL_CENTER"][0], row["ENCL_CENTER"][1]
        rec = {"x": cx, "y": cy, "area_px": float(row["AREA_PXL"]),
               "encl_diam_px": float(row.get("ENCL_DIAMETER_PXL", 0) or 0)}
        try:
            encl_area = math.pi * (float(row["ENCL_DIAMETER_PXL"]) ** 2) / 4.0
            # the tool's own roundness statistic: area / enclosing-circle area
            rec["circularity"] = float(row["AREA_PXL"]) / encl_area if encl_area > 0 else None
        except Exception:
            pass
        plaques.append(rec)
    res = flag_plaques(plaques, image_shape, dish=dish, **kw)
    return [f for f, _ in res], [w for _, w in res]


def flags_for_plaque_dicts(plaques, image_shape, plate=None, circularities=None, **kw):
    """App-side plaque dicts (center, area_pxl, kind, optional p_plaque) -> list of flags."""
    recs = []
    for i, p in enumerate(plaques):
        cx, cy = p["center"]
        recs.append({"x": float(cx), "y": float(cy), "area_px": float(p.get("area_pxl", 0.0) or 0.0),
                     "circularity": (circularities[i] if circularities is not None else None),
                     "p_plaque": p.get("p_plaque")})
    dish = None
    if plate and plate.get("center") and plate.get("radius"):
        dish = (float(plate["center"][0]), float(plate["center"][1]), float(plate["radius"]))
    return flag_plaques(recs, image_shape, dish=dish, **kw)
