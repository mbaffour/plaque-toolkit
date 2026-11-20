"""Plaque-size scales: the ONE implementation of the app's Auto plaque size, shared by the
desktop app (plaque_gui.run_detection) and the command line's opt-in --multiscale
(plaque_size_tool), so the two cannot drift apart (CT-R1 detection D10b).

* merge_scales / dedupe_by_containment -- the dual-scale merge (D1, F14);
* resolve_halos -- one definition of the plaque edge per plate: the standard threshold's halo
  edge wherever its mask holds the plaque, clusters split among their cores (D8);
* roundest_dish_idx / plate_from_row / drop_outside_dish -- the app's dish rule and the
  outside-dish drop (D2, D3).

Pure OpenCV / numpy on plaque dicts and the detector's DataFrames: it imports neither
plaque_size_tool nor plaque_gui, and the CLI imports it only when --multiscale is given, so
the default and --published paths never load it.
"""
import math
import os

import cv2
import imutils
import numpy as np


def _area_diff(row):
    """plaque_size_tool.calc_AREA_PXL_diff, verbatim (1 - area / enclosing-circle area)."""
    encl = 3.1415 * (row['ENCL_DIAMETER_PXL'] ** 2) / 4
    return abs(1 - row['AREA_PXL'] / encl)


CONCENTRIC_PX = 5          # plaque_size_tool.check_duplicate_plaques' centre tolerance


def _contour_center(contour, fallback):
    m = cv2.moments(contour)
    if m["m00"] != 0:
        return (m["m10"] / m["m00"], m["m01"] / m["m00"])
    return (float(fallback[0]), float(fallback[1]))



def roundest_dish_idx(plate_df):
    """The app's dish rule (unchanged): the ROUNDEST large contour, largest among ties."""
    if plate_df is None or plate_df.empty:
        return None
    try:
        _ad = plate_df.apply(_area_diff, axis=1)
        cand = plate_df[_ad <= float(_ad.min()) + 0.05]
        return cand["ENCL_DIAMETER_PXL"].idxmax()
    except Exception:
        return plate_df["ENCL_DIAMETER_PXL"].idxmax()


def plate_from_row(plate_df, idx):
    plate_hull = np.asarray(plate_df.loc[idx, "HULL"], dtype=np.int32)
    (pcx, pcy), prad = cv2.minEnclosingCircle(plate_hull)
    axis_ratio = None
    try:
        if len(plate_hull) >= 5:
            (_c, (_a1, _a2), _ang) = cv2.fitEllipse(plate_hull)
            lo, hi = min(_a1, _a2), max(_a1, _a2)
            axis_ratio = (hi / lo) if lo > 0 else None
    except Exception:
        axis_ratio = None
    return {"hull": plate_hull.reshape(-1, 2), "center": (float(pcx), float(pcy)),
            "radius": float(prad), "diam_px": float(plate_df.loc[idx, "ENCL_DIAMETER_PXL"]),
            "axis_ratio": axis_ratio}


def _plaque_dicts(green_df, source=None):
    out = []
    for _, row in green_df.iterrows():
        src = row.get("SOURCE", "auto")
        if source is not None and src == "auto":
            src = source
        hull = np.asarray(row["HULL"], dtype=np.int32)
        p = {"source": src, "kind": "contour", "contour": hull,
             "area_pxl": float(row["AREA_PXL"]),
             "center": _contour_center(row["CONTOURS"], row["ENCL_CENTER"]),
             "encl_diam_px": float(row["ENCL_DIAMETER_PXL"])}
        try:
            # shape of the RAW outline (the hull is convex by construction, so its solidity is
            # always 1): feeds the QC MERGED? flag (CT-R1 detection D5)
            raw = np.asarray(row["CONTOURS"], dtype=np.int32)
            ha = float(row["AREA_PXL"])
            p["solidity"] = round(float(cv2.contourArea(raw)) / ha, 4) if ha > 0 else None
        except Exception:
            pass
        out.append(p)
    return out


def _inside(contour, pt):
    return cv2.pointPolygonTest(np.asarray(contour, dtype=np.int32).reshape(-1, 1, 2),
                                (float(pt[0]), float(pt[1])), False) >= 0


def dedupe_by_containment(plaques):
    """Drop a plaque's CORE when it was also found as its halo: a plaque whose centre lies
    inside a LARGER plaque's outline that contains no other plaque (CT-R1 F14). The larger
    outline is kept, as the standard pass would. When a larger outline contains two or more
    plaques it is a cluster outlined as one blob, and the plaques inside are real: nothing is
    dropped (the QC flag NESTED marks them). Returns (kept, n_dropped); order is preserved."""
    n = len(plaques)
    inner = {k: [i for i in range(n) if i != k
                 and plaques[i]["area_pxl"] < plaques[k]["area_pxl"]
                 and _inside(plaques[k]["contour"], plaques[i]["center"])]
             for k in range(n)}
    drop = {lst[0] for lst in inner.values() if len(lst) == 1}
    return [p for i, p in enumerate(plaques) if i not in drop], len(drop)


def merge_scales(standard, small):
    """Dual-scale merge (CT-R1 detection D1, tester improvement I2). EVERY standard-pass plaque
    is kept with its standard (block-231) outline, so its size is exactly what the standard
    pass measures. A small-pass (block-49) plaque is ADDED only when its centre is not inside
    any standard plaque's outline and not within the concentric tolerance of a standard
    centre; the additions are de-duplicated by containment among themselves (F14) and marked
    source "small". Returns (merged, n_added)."""
    add = []
    for p in small:
        c = p["center"]
        if any(_inside(s["contour"], c) for s in standard):
            continue
        if any(abs(c[0] - s["center"][0]) <= CONCENTRIC_PX and abs(c[1] - s["center"][1]) <= CONCENTRIC_PX
               for s in standard):
            continue
        add.append(p)
    add, _n = dedupe_by_containment(add)
    for p in add:
        if p.get("source") in (None, "auto"):
            p["source"] = "small"
    return list(standard) + add, len(add)


def standard_mask(high_contrast):
    """The standard pass's own binary mask (block 231, before its Laplacian edge step and the
    shape gates): plaque_size_tool.process_image thresholds exactly this image this way, so
    Laplacian(standard_mask) is the edge image its contours come from."""
    return cv2.adaptiveThreshold(high_contrast, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                 cv2.THRESH_BINARY_INV, 231, 2)


SPLIT_SOURCE = "split"                 # one of several plaques separated by the watershed
RELAXED_SOURCE = "standard-relaxed"    # one plaque: the standard blob's own outline, which only
                                       # the shape/size gates had rejected
HALO_MIN_SOLIDITY = 0.85
HALO_MAX_FACTOR = 3.0
HALO_RELAXED_MIN_GROWTH = 1.3          # a single blob no bigger than this x the core: no halo
HALO_MIN_GROWTH = 2.0                  # a halo region must be at least this x its core's area (a
                                       # haloed plaque's halo is ~4-6x its core; a sliver cut off a
                                       # cluster is not a halo: sample.tif 3.86 mm piece, 1.9x)
HALO_MIN_ROUNDNESS = 0.79              # area / enclosing-circle area: the standard pass's own gate
HALO_SPLIT_MIN_ROUNDNESS = 0.6         # a split piece is a disc cut by its neighbour (half disc: 0.5)
HALO_MIN_RATIO = 0.3                   # halo_ratio at or above this: the core has a paler halo (gap 0.18-0.32 on sample.tif; sharp Plate_11 cores <= 0.21 bar one)
SECOND_CORE_LEVEL = 0.35               # darker than core + this x (lawn - core): another core


def _second_core(gray, reg, core):
    """True when the region holds another dark core, away from its own: a blob of two plaques
    of which the small pass found only one core. Then the region is not one plaque's halo."""
    if gray is None:
        return False
    r = math.sqrt(max(core["area_pxl"], 1.0) / math.pi)
    c = core["center"]
    inner = _ring_median(gray, c, 0, 0.6 * r)
    lawn = _ring_median(gray, c, 3.0 * r, 4.0 * r)
    if not (inner == inner and lawn == lawn) or lawn - inner <= 1e-3:
        return False
    level = inner + SECOND_CORE_LEVEL * (lawn - inner)
    cnt = np.asarray(reg["contour"], np.int32).reshape(-1, 1, 2)
    x, y, w, h = cv2.boundingRect(cnt)
    H, W = gray.shape[:2]
    x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + w, W), min(y + h, H)
    if x1 - x0 < 3 or y1 - y0 < 3:
        return False
    win = gray[y0:y1, x0:x1]
    m = np.zeros(win.shape, np.uint8)
    cv2.drawContours(m, [cnt - np.array([x0, y0], np.int32)], -1, 255, -1)
    yy, xx = np.mgrid[y0:y1, x0:x1]
    far = np.hypot(xx - c[0], yy - c[1]) > 1.5 * r
    k = max(3, int(r) | 1)
    local_min = win <= cv2.erode(win, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    return bool(np.any((m > 0) & far & local_min & (win <= level)))


# CT-R1 detection D10c: when is a split piece's area-equivalent diameter good enough for a
# size summary? From the synthetic sweep validation/split_sweep (haloed discs, D = 80 / 120
# px where Auto splits; the bias is systematic, SD <= 0.5 %): the piece is undersized by
#   cut by 1 neighbour:  -7.8 % at centres 0.6 D apart (cut_ratio 0.65), -5.2 % at 0.7 D
#                        (0.74), -2.9 % at 0.8 D (0.82), -1.2 % at 0.9 D, -0.1 % at 1.0 D;
#   cut by 2:            -16.8 % at 0.6 D, -11.4 % at 0.7 D, -6.6 % at 0.8 D (0.86),
#                        -2.9 % at 0.9 D (0.93), -1.2 % at 1.0 D;
#   cut by 3:            -17.2 % at 0.7 D, -10.0 % at 0.8 D (0.88), -4.9 % at 0.9 D (0.94),
#                        -1.7 % at 1.0 D.
# cut_ratio (nearest cutting core distance / the piece's own diameter) is what can be measured
# on a real plate. A piece stays in size summaries when its expected bias is within +/-5 %:
SPLIT_MIN_CUT_RATIO = {1: 0.75, 2: 0.90, 3: 0.95}     # 3 or more neighbours: 0.95


def split_size_reliable(cut_by, cut_ratio):
    """(ok, reason) for a split piece: ok when the sweep's expected size bias at this many cuts
    and this overlap is within +/-5 % (SPLIT_MIN_CUT_RATIO); otherwise the reason says why."""
    if not cut_by:
        return True, None
    need = SPLIT_MIN_CUT_RATIO[min(int(cut_by), 3)]
    if cut_ratio is not None and cut_ratio >= need:
        return True, None
    return False, ("cut by %d neighbour%s%s" % (
        cut_by, "" if cut_by == 1 else "s",
        (", centres %.2f of its diameter apart" % cut_ratio) if cut_ratio is not None else ""))


def _ring_median(gray, c, r0, r1):
    x, y = float(c[0]), float(c[1])
    R = int(r1) + 2
    x0, y0 = max(int(x) - R, 0), max(int(y) - R, 0)
    win = gray[y0:int(y) + R + 1, x0:int(x) + R + 1].astype(np.float32)
    if win.size == 0:
        return float("nan")
    yy, xx = np.mgrid[y0:y0 + win.shape[0], x0:x0 + win.shape[1]]
    d = np.hypot(xx - x, yy - y)
    m = (d >= r0) & (d < r1)
    return float(np.median(win[m])) if m.any() else float("nan")


def halo_ratio(gray, core, lawn=None):
    """How much of a dark core's contrast its surroundings keep just outside it: (lawn -
    annulus) / (lawn - core), annulus at 1.2-2 core radii (medians). ``lawn`` is the plate's
    lawn grey (median of the dish); without it a ring at 3-4 radii is used, which reads low
    in a crowd (the ring then lies on the neighbours' halos). ~0 for a sharp plaque (Plate_11,
    Plate_1), 0.3-0.8 for a dark core with a paler halo (sample.tif, Plate_6, Plate_8)."""
    r = math.sqrt(max(core["area_pxl"], 1.0) / math.pi)
    c = core["center"]
    inner = _ring_median(gray, c, 0, 0.6 * r)
    ann = _ring_median(gray, c, 1.2 * r, 2.0 * r)
    if lawn is None:
        lawn = _ring_median(gray, c, 3.0 * r, 4.0 * r)
    den = lawn - inner
    if not (den == den) or den <= 1e-3 or not (ann == ann):
        return 0.0
    return (lawn - ann) / den


def source_counts(plaques):
    """{'standard', 'split', 'standard-relaxed', 'small', 'core', 'other'} counts for a result;
    they add up to the plaque count ('small' = genuine small plaques, 'core' = SOURCE small
    plaques measured at the core only, QC flag CORE?)."""
    out = {"standard": 0, SPLIT_SOURCE: 0, RELAXED_SOURCE: 0, "small": 0, "other": 0, "core": 0,
           "no_size": sum(1 for p in plaques if p.get("size_unreliable"))}
    for p in plaques:
        if p.get("core_only"):
            out["core"] += 1
            continue
        s = p.get("source")
        key = "standard" if s == "auto" else (s if s in out else "other")
        out[key] += 1
    return out


def _region_plaque(contour, pixel_area, source):
    """A plaque dict from a region outline, measured like the standard pass (convex hull)."""
    c = np.asarray(contour, dtype=np.int32).reshape(-1, 1, 2)
    hull = cv2.convexHull(c)
    ha = float(cv2.contourArea(hull))
    (_ex, _ey), er = cv2.minEnclosingCircle(hull)
    return {"source": source, "kind": "contour", "contour": hull.reshape(-1, 2).astype(np.int32),
            "area_pxl": ha, "center": _contour_center(hull, (_ex, _ey)),
            "encl_diam_px": 2.0 * float(er),
            "solidity": (round(float(pixel_area) / ha, 4) if ha > 0 else None)}


def _split_mask(mask, seeds, radii=None):
    """Partition one blob mask among its cores (crop coordinates). Every blob pixel goes to the
    core it is nearest to in units of that core's radius (a multiplicatively weighted Voronoi
    split: for two touching plaques of equal size the cut is the bisector of their centres, a
    bigger core claims proportionally more); each core keeps the connected piece around it.
    A marker watershed on the blob's distance transform was tried first and leaked: seeds at
    the cores are not distance-transform maxima, so one region swallowed its neighbour's halo
    (sample.tif: regions of 12,822 vs 818 px for two similar plaques, solidity down to 0.17).
    Returns one (contour, pixel_area, neighbours) per seed (None when a seed got no region);
    ``neighbours`` are the indices of the seeds whose regions touch this one (the cuts)."""
    H, W = mask.shape[:2]
    yy, xx = np.mgrid[0:H, 0:W]
    radii = radii or [1.0] * len(seeds)
    d = np.stack([np.hypot(xx - sx, yy - sy) / max(float(r), 1e-3)
                  for (sx, sy), r in zip(seeds, radii)])
    owner = np.argmin(d, axis=0)
    out = []
    for k, (sx, sy) in enumerate(seeds):
        region = np.uint8((owner == k) & (mask > 0)) * 255
        n_lbl, lab = cv2.connectedComponents(region, connectivity=8)
        ix, iy = min(max(int(round(sx)), 0), W - 1), min(max(int(round(sy)), 0), H - 1)
        lbl = int(lab[iy, ix])
        if lbl == 0:
            out.append(None)
            continue
        region = np.uint8(lab == lbl) * 255
        cnts = imutils.grab_contours(cv2.findContours(region, cv2.RETR_EXTERNAL,
                                                      cv2.CHAIN_APPROX_SIMPLE))
        ring = (cv2.dilate(region, np.ones((3, 3), np.uint8)) > 0) & (region == 0) & (mask > 0)
        nbrs = sorted(int(j) for j in np.unique(owner[ring]) if int(j) != k)
        out.append((max(cnts, key=cv2.contourArea), int(np.count_nonzero(region)), nbrs)
                   if cnts else None)
    return out


def resolve_halos(standard, small, std_mask, plate, image_shape, gray=None):
    """Auto (CT-R1 detection D8): give every plaque the STANDARD threshold's (halo) edge
    wherever the standard mask holds it, so one plate is not measured with two definitions of
    the plaque edge (halo for the plaques the standard gates accepted, core for the ones the
    small pass added).

    * A standard plaque holding at most one small-pass core is kept as it is (SOURCE auto).
    * A standard plaque, or a standard-mask blob the gates rejected, holding two or more
      small-pass cores is a CLUSTER: it is split by a marker watershed seeded at the cores and
      each region becomes a plaque (SOURCE "split"); the standard outline that hid it is
      dropped.
    * A rejected blob holding one core becomes that plaque with the blob's own outline
      (SOURCE "standard-relaxed") when it is clearly larger than the core (it has a halo);
      otherwise the plaque is a sharp small plaque and keeps its core outline.
    * A region that fails the plausibility checks (solidity >= 0.85, area between 2x the core's
      and 3x the largest standard plaque, clear of the lawn edge, blob not dish-scale, round
      enough, no second dark core inside) keeps
      the small-pass core outline (SOURCE "small") and is marked core_only (QC flag CORE?).
    * A small-pass plaque outside every standard blob, or with no halo (halo_ratio below
      HALO_MIN_RATIO: a sharp plaque), is a small plaque: unchanged.
    Regions must also pass the standard pass's own roundness gate (area >= 0.79 of the
    enclosing circle), so a blob that is really two plaques with one core found is not
    reported as one plaque. Returns (plaques, counts)."""
    small, _nd = dedupe_by_containment(list(small))
    # a small-pass outline holding two or more other cores is itself a cluster outline, not a
    # core: its inner cores are the seeds
    small = [c for c in small
             if sum(_inside(c["contour"], o["center"]) for o in small if o is not c) < 2]
    small = [dict(c, source="small") if c.get("source") in (None, "auto") else c for c in small]
    # the lawn grey AT each core: a morphological closing (removes dark plaques and their halos,
    # clusters included) of a 1/4-scale copy, so vignetting and crowding do not fake a halo
    has_halo = {}
    if gray is not None and small:
        ref = [p.get("encl_diam_px") or 2 * math.sqrt(p["area_pxl"] / math.pi) for p in standard] \
            or [2 * math.sqrt(p["area_pxl"] / math.pi) for p in small]
        k = int(max(15, 2.5 * float(np.median(ref)) / 4.0)) | 1
        q = cv2.resize(gray, (max(gray.shape[1] // 4, 1), max(gray.shape[0] // 4, 1)),
                       interpolation=cv2.INTER_AREA)
        bg = cv2.morphologyEx(q, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
        bg = cv2.GaussianBlur(bg, (0, 0), k / 4.0)
        for c in small:
            bx = min(max(int(c["center"][0] / 4), 0), bg.shape[1] - 1)
            by = min(max(int(c["center"][1] / 4), 0), bg.shape[0] - 1)
            has_halo[id(c)] = halo_ratio(gray, c, float(bg[by, bx])) >= HALO_MIN_RATIO
    H, W = std_mask.shape[:2]
    std_areas = sorted(p["area_pxl"] for p in standard)
    if len(std_areas) >= 3:
        cap = HALO_MAX_FACTOR * std_areas[-1]
    else:
        pool = std_areas or sorted(p["area_pxl"] for p in small)
        cap = HALO_MAX_FACTOR * (pool[len(pool) // 2] if pool else float("inf"))
        if std_areas:
            cap = max(cap, HALO_MAX_FACTOR * std_areas[-1])
    if plate is not None:
        dcx, dcy = plate["center"]
        lawn_r = 0.93 * float(plate["radius"])
        dish_area = math.pi * float(plate["radius"]) ** 2
    else:
        dcx = dcy = lawn_r = None
        dish_area = float(H * W)
    blob_max = min(100000.0, 0.02 * dish_area)

    def clear_of_edge(cnt):
        pts = np.asarray(cnt).reshape(-1, 2).astype(np.float64)
        if lawn_r is not None:
            return bool(np.all(np.hypot(pts[:, 0] - dcx, pts[:, 1] - dcy) <= lawn_r))
        return bool(pts[:, 0].min() > 1 and pts[:, 1].min() > 1
                    and pts[:, 0].max() < W - 2 and pts[:, 1].max() < H - 2)

    def plausible(reg, core):
        ed = reg.get("encl_diam_px") or 0.0
        roundness = reg["area_pxl"] / (math.pi * ed * ed / 4.0) if ed > 0 else 0.0
        return (reg["solidity"] is not None and reg["solidity"] >= HALO_MIN_SOLIDITY
                and roundness >= (HALO_SPLIT_MIN_ROUNDNESS if reg["source"] == SPLIT_SOURCE
                                  else HALO_MIN_ROUNDNESS)
                and not _second_core(gray, reg, core)
                and reg["area_pxl"] >= HALO_MIN_GROWTH * core["area_pxl"] and reg["area_pxl"] <= cap
                and clear_of_edge(reg["contour"]))

    def core_only(core):
        if not has_halo.get(id(core)):
            return core                    # a sharp plaque: its core IS its edge
        q = dict(core)
        q["source"], q["core_only"] = "small", True
        return q

    counts = {"clusters": 0, SPLIT_SOURCE: 0, RELAXED_SOURCE: 0, "core": 0, "small": 0}
    cluster_hulls = []

    def resolve_group(mask_full_blob, cores, bbox):
        """Split one blob (a full-image uint8 mask restricted to bbox) among its cores."""
        x0, y0, x1, y1 = bbox
        crop = np.ascontiguousarray(mask_full_blob[y0:y1, x0:x1])
        blob_px = int(np.count_nonzero(crop))
        out = []
        if blob_px > blob_max:
            return [core_only(c) for c in cores]
        if len(cores) == 1:
            cnts = imutils.grab_contours(cv2.findContours(crop.copy(), cv2.RETR_EXTERNAL,
                                                          cv2.CHAIN_APPROX_SIMPLE))
            if not cnts:
                return [cores[0]]
            reg = _region_plaque(max(cnts, key=cv2.contourArea) + np.array([x0, y0]), blob_px,
                                 RELAXED_SOURCE)
            if reg["area_pxl"] <= HALO_RELAXED_MIN_GROWTH * cores[0]["area_pxl"]:
                return [cores[0]]                     # no halo: a sharp small plaque
            return [reg if plausible(reg, cores[0]) else core_only(cores[0])]
        seeds = [(c["center"][0] - x0, c["center"][1] - y0) for c in cores]
        radii = [math.sqrt(max(c["area_pxl"], 1.0) / math.pi) for c in cores]
        for k, (core, res) in enumerate(zip(cores, _split_mask(crop, seeds, radii))):
            if res is None:
                out.append(core_only(core))
                continue
            reg = _region_plaque(res[0] + np.array([x0, y0]), res[1], SPLIT_SOURCE)
            # how the piece was cut (D10c): by how many neighbours, and how close the nearest
            # cutting core is, in units of the piece's own area-equivalent diameter
            reg["cut_by"] = len(res[2])
            dpiece = 2.0 * math.sqrt(max(reg["area_pxl"], 1.0) / math.pi)
            reg["cut_ratio"] = (min(math.hypot(seeds[k][0] - seeds[j][0], seeds[k][1] - seeds[j][1])
                                    for j in res[2]) / dpiece) if res[2] else None
            ok, why = split_size_reliable(reg["cut_by"], reg["cut_ratio"])
            if not ok:                         # D10c: counts, but its size is biased > 5 %
                reg["size_unreliable"], reg["size_reason"] = True, why
            out.append(reg if plausible(reg, core) else core_only(core))
        pts = [np.asarray(q["contour"]).reshape(-1, 2) for q in out if q.get("source") == SPLIT_SOURCE]
        if len(pts) >= 2:
            cluster_hulls.append(cv2.convexHull(np.vstack(pts).astype(np.int32)).reshape(-1, 2))
        return out

    # which cores sit inside which accepted standard outline
    inside_std = {i: [] for i in range(len(standard))}
    free = []
    for c in small:
        hit = [i for i, s in enumerate(standard) if _inside(s["contour"], c["center"])]
        if hit:
            for i in hit:
                inside_std[i].append(c)
        elif any(abs(c["center"][0] - s["center"][0]) <= CONCENTRIC_PX
                 and abs(c["center"][1] - s["center"][1]) <= CONCENTRIC_PX for s in standard):
            continue
        else:
            free.append(c)

    out = []
    for i, s in enumerate(standard):
        cores = inside_std[i]
        if len(cores) < 2:
            out.append(s)
            continue
        counts["clusters"] += 1
        m = np.zeros((H, W), np.uint8)
        cv2.drawContours(m, [np.asarray(s["contour"], np.int32).reshape(-1, 1, 2)], -1, 255, -1)
        m = cv2.bitwise_and(m, std_mask)
        x, y, w, h = cv2.boundingRect(np.asarray(s["contour"], np.int32).reshape(-1, 1, 2))
        out.extend(resolve_group(m, cores, (max(x - 2, 0), max(y - 2, 0),
                                            min(x + w + 2, W), min(y + h + 2, H))))

    # cores outside every accepted outline: the standard-mask blob (if any) holding each
    n_lab, lab, stats, _cent = cv2.connectedComponentsWithStats(std_mask, connectivity=8)
    groups = {}
    for c in free:
        cx = min(max(int(round(c["center"][0])), 0), W - 1)
        cy = min(max(int(round(c["center"][1])), 0), H - 1)
        groups.setdefault(int(lab[cy, cx]), []).append(c)
    for lbl, cores in groups.items():
        if lbl == 0 or not any(has_halo[id(c)] for c in cores):
            out.extend(cores)                         # outside every blob / no halo: small plaque
            continue
        if len(cores) >= 2:
            counts["clusters"] += 1
        bx, by, bw, bh, barea = (int(v) for v in stats[lbl])
        if barea > blob_max:
            out.extend(core_only(c) for c in cores)
            continue
        m = np.zeros((H, W), np.uint8)
        sub = (lab[by:by + bh, bx:bx + bw] == lbl)
        m[by:by + bh, bx:bx + bw][sub] = 255
        out.extend(resolve_group(m, cores, (bx, by, bx + bw, by + bh)))

    # a standard outline whose centre lies inside a split / relaxed region, or inside the
    # outline of a split cluster, is not a plaque of its own: it is the lawn hole between the
    # halos of a cluster (RETR_CCOMP's inner contour)
    regions = [p["contour"] for p in out if p.get("source") in (SPLIT_SOURCE, RELAXED_SOURCE)]
    regions += cluster_hulls
    std_ids = {id(s) for s in standard}
    dropped = [p for p in out if id(p) in std_ids
               and any(_inside(r, p["center"]) for r in regions)]
    if dropped:
        drop_ids = {id(p) for p in dropped}
        out = [p for p in out if id(p) not in drop_ids]
    counts["standard_dropped_inside_cluster"] = len(dropped)
    for p in out:
        if p.get("core_only"):
            counts["core"] += 1
        elif p.get("source") in (SPLIT_SOURCE, RELAXED_SOURCE, "small"):
            counts[p["source"]] += 1
    return out, counts


def drop_outside_dish(plaques, plate, image_shape):
    """CT-R1 F18 (D3): plaques whose centre lies outside the dish are dropped and counted --
    unless the "dish" is itself implausibly small (a plaque taken for the dish, F9), which
    would drop everything. Returns (kept, n_outside)."""
    if plate is None:
        return list(plaques), 0
    import plaque_qc
    if plaque_qc.dish_too_small(plate, image_shape):
        return list(plaques), 0
    inside = [p for p in plaques if _inside(plate["hull"], p["center"])]
    return inside, len(plaques) - len(inside)


def auto_plaques(standard, small, high_contrast, plate, orig_bgr):
    """The Auto plaque list from the two passes' plaque dicts: resolve_halos on the standard
    mask of ``high_contrast`` (the standard pass's own), with the blurred grey of the original
    image for the halo test. Returns (plaques, counts)."""
    gray = cv2.GaussianBlur(cv2.cvtColor(orig_bgr, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    return resolve_halos(standard, small, standard_mask(high_contrast), plate,
                         orig_bgr.shape, gray=gray)


def circularity(p):
    """4*pi*A / P^2 of a plaque's outline in [0, 1] (circles: 1.0) -- app.engine_api's
    CIRCULARITY, here so the CLI's --multiscale --qc flags rows with the same input."""
    if p.get("kind") == "circle":
        return 1.0
    c = np.asarray(p.get("contour"), dtype=np.int32).reshape(-1, 1, 2)
    per = cv2.arcLength(c, True)
    if per <= 0:
        return 0.0
    return round(min(1.0, 4.0 * math.pi * cv2.contourArea(c) / (per * per)), 3)
