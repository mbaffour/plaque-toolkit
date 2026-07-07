"""app/fiji_match.py — pair the app's plaques with Fiji/ImageJ measurements by position.

Registration by centroid, so "plaque #k in the app" is compared against the SAME physical
plaque measured independently in Fiji — regardless of the two tools' numbering. Two regimes:

  * **Direct** (align="none") — Fiji opened the app's calibrated crop, so both are in the
    same millimetre frame: nearest-centroid matching, exact.
  * **Auto** (align="auto") — your own image, possibly translated / scaled / rotated: a
    robust similarity alignment (RANSAC over point pairs + Procrustes refine) brings the
    Fiji centroids into the app's frame first, then matches. (Reflection is not fitted —
    if you mirrored the plate, match orientation with the app's Orient tool first.)

Diameters use the area-equivalent d = 2*sqrt(area/pi), matching the app. Pure numpy/pandas.
"""
import numpy as np
import pandas as pd


# --------------------------------------------------------------------------- #
#  Parsing a Fiji "Results" CSV
# --------------------------------------------------------------------------- #
def _fiji_diam(df, cols):
    """Area-equivalent diameter (preferred) or a caliper/axis fallback, in Fiji's units."""
    if "Area" in cols:
        a = pd.to_numeric(df[cols["Area"]], errors="coerce")
        return 2.0 * np.sqrt(a.clip(lower=0) / np.pi)
    for k in ("Feret", "Major", "MinFeret", "Minor"):
        if k in cols:
            return pd.to_numeric(df[cols[k]], errors="coerce")
    return pd.Series(np.full(len(df), np.nan))


def load_fiji_results(path):
    """Parse a Fiji Results CSV into columns: frow, fx, fy, fdiam.

    Requires X and Y centroids (enable 'Centroid' in Analyze > Set Measurements) plus Area
    (or Feret/Major) for the diameter."""
    df = pd.read_csv(path)
    cols = {str(c).strip(): c for c in df.columns}
    if "X" not in cols or "Y" not in cols:
        raise ValueError(
            "This Fiji CSV has no X/Y centroid columns. In Fiji: Analyze > Set Measurements, "
            "tick 'Centroid' (and 'Area'), then Measure again and re-export.")
    out = pd.DataFrame({
        "frow": np.arange(1, len(df) + 1),
        "fx": pd.to_numeric(df[cols["X"]], errors="coerce"),
        "fy": pd.to_numeric(df[cols["Y"]], errors="coerce"),
        "fdiam": _fiji_diam(df, cols),
    }).dropna(subset=["fx", "fy"]).reset_index(drop=True)
    if out.empty:
        raise ValueError("No usable rows (X/Y) found in the Fiji CSV.")
    return out


# --------------------------------------------------------------------------- #
#  Geometry: similarity alignment + greedy nearest-centroid matching
# --------------------------------------------------------------------------- #
def _umeyama(src, dst):
    """Least-squares similarity (rotation + uniform scale + translation) src->dst.
    Returns (scale, R(2x2), t(2,)). No reflection (proper rotation only)."""
    src = np.asarray(src, float); dst = np.asarray(dst, float)
    mu_s, mu_d = src.mean(0), dst.mean(0)
    s, d = src - mu_s, dst - mu_d
    cov = (d.T @ s) / len(src)
    U, D, Vt = np.linalg.svd(cov)
    S = np.eye(2)
    if np.linalg.det(U) * np.linalg.det(Vt) < 0:
        S[-1, -1] = -1
    R = U @ S @ Vt
    var_s = (s ** 2).sum() / len(src)
    scale = (D * np.diag(S)).sum() / var_s if var_s > 1e-12 else 1.0
    t = mu_d - scale * (R @ mu_s)
    return scale, R, t


def _apply(scale, R, t, pts):
    pts = np.asarray(pts, float)
    return (scale * (R @ pts.T).T) + t


def _two_point_similarity(f0, f1, a0, a1):
    """Similarity mapping f0->a0, f1->a1 (scale+rotation+translation)."""
    df, da = f1 - f0, a1 - a0
    nf = np.hypot(*df)
    if nf < 1e-9:
        return None
    scale = np.hypot(*da) / nf
    ang = np.arctan2(da[1], da[0]) - np.arctan2(df[1], df[0])
    c, s = np.cos(ang), np.sin(ang)
    R = np.array([[c, -s], [s, c]])
    t = a0 - scale * (R @ f0)
    return scale, R, t


def _reflect(F):
    """Mirror a point set across the x-axis (negate y). Combined with the rotation search
    this covers every mirror-flip, so alignment handles all 8 dihedral orientations."""
    G = np.asarray(F, float).copy()
    G[:, 1] = -G[:, 1]
    return G


def _ransac_similarity(F, A, tol, iters=4000, seed=12345):
    """Best proper-rotation similarity mapping F into A's frame (no reflection).
    Returns (scale, R, t, n_inliers) or None."""
    n, m = len(F), len(A)
    if n < 2 or m < 2:
        return None
    rng = np.random.default_rng(seed)
    best, best_in = None, -1
    for _ in range(int(iters)):
        i0, i1 = rng.integers(0, n, 2)
        j0, j1 = rng.integers(0, m, 2)
        if i0 == i1 or j0 == j1:
            continue
        cand = _two_point_similarity(F[i0], F[i1], A[j0], A[j1])
        if cand is None:
            continue
        scale, R, t = cand
        if not (0.2 < scale < 5.0):        # reject absurd scales
            continue
        Ft = _apply(scale, R, t, F)
        d = np.linalg.norm(Ft[:, None, :] - A[None, :, :], axis=2)
        inl = int((d.min(axis=1) <= tol).sum())
        if inl > best_in:
            best_in, best = inl, (scale, R, t)
    if best is None or best_in < 2:
        return None
    scale, R, t = best                      # refine on the inlier correspondences
    d = np.linalg.norm(_apply(scale, R, t, F)[:, None, :] - A[None, :, :], axis=2)
    jmin = d.argmin(axis=1)
    keep = d[np.arange(n), jmin] <= tol
    if keep.sum() >= 2:
        scale, R, t = _umeyama(F[keep], A[jmin[keep]])
    return scale, R, t, best_in


def _ransac_align(F, A, tol, iters=4000, seed=12345):
    """Align Fiji points F into the app frame A, trying BOTH orientations (direct and
    mirror-flipped) so a flipped plate still matches. Returns a dict with a transform
    callable ``tf``, ``scale`` and ``reflected`` — or None."""
    best = None
    for reflected in (False, True):
        G = _reflect(F) if reflected else np.asarray(F, float)
        res = _ransac_similarity(G, A, tol, iters, seed)
        if res is None:
            continue
        scale, R, t, inl = res
        if best is None or inl > best["inliers"]:
            best = {"scale": float(scale), "R": R, "t": t,
                    "reflected": reflected, "inliers": int(inl)}
    if best is None:
        return None
    scale, R, t, reflected = best["scale"], best["R"], best["t"], best["reflected"]

    def tf(pts):
        P = _reflect(pts) if reflected else np.asarray(pts, float)
        return (scale * (R @ P.T).T) + t

    best["tf"] = tf
    return best


def _greedy_match(A, B, tol):
    """Greedy nearest-centroid matching. A,B: (n,2)/(m,2). Returns [(i,j,dist), ...]."""
    if len(A) == 0 or len(B) == 0:
        return []
    D = np.linalg.norm(A[:, None, :] - B[None, :, :], axis=2)
    order = np.dstack(np.unravel_index(np.argsort(D, axis=None), D.shape))[0]
    used_a, used_b, pairs = set(), set(), []
    for i, j in order:
        i, j = int(i), int(j)
        if D[i, j] > tol:
            break
        if i in used_a or j in used_b:
            continue
        used_a.add(i); used_b.add(j)
        pairs.append((i, j, float(D[i, j])))
    return pairs


# --------------------------------------------------------------------------- #
#  Public: match an app registration frame to a Fiji results frame
# --------------------------------------------------------------------------- #
def match(app_df, fiji_df, align="auto", tol=None):
    """Pair app plaques (columns INDEX, X, Y, DIAMETER) with Fiji rows (frow, fx, fy, fdiam).

    Returns a dict: {paired (DataFrame), unmatched_app, unmatched_fiji, summary}.
    `align`: "none" (shared calibrated frame) or "auto" (estimate a similarity first).
    `tol`: match radius in the app's units; defaults to 0.6 * median app diameter."""
    A = app_df[["X", "Y"]].to_numpy(float)
    F = fiji_df[["fx", "fy"]].to_numpy(float)
    a_idx = app_df["INDEX"].to_numpy()
    a_diam = pd.to_numeric(app_df["DIAMETER"], errors="coerce").to_numpy(float)
    f_diam = pd.to_numeric(fiji_df["fdiam"], errors="coerce").to_numpy(float)

    med = np.nanmedian(a_diam) if np.isfinite(a_diam).any() else None
    if tol is None:
        tol = 0.6 * med if med and med > 0 else None

    scale = 1.0
    Ft = F
    aligned = False
    reflected = False
    if align == "auto" and len(A) >= 2 and len(F) >= 2:
        # tolerance for RANSAC in the app frame; if we don't know app scale yet, use a
        # generous span-based fallback
        rtol = tol if tol else 0.15 * float(np.linalg.norm(A.max(0) - A.min(0)) or 1.0)
        al = _ransac_align(F, A, rtol)
        if al is not None:
            scale = al["scale"]
            reflected = al["reflected"]
            Ft = al["tf"](F)
            aligned = True
    if tol is None:
        tol = 0.6 * med if med and med > 0 else 0.1 * float(np.linalg.norm(A.max(0) - A.min(0)) or 1.0)

    pairs = _greedy_match(A, Ft, tol)
    f_diam_conv = f_diam * scale           # bring Fiji diameters into app units

    rows = []
    for i, j, dist in pairs:
        ad, fd = a_diam[i], f_diam_conv[j]
        rows.append({
            "APP_INDEX": a_idx[i], "FIJI_ROW": int(fiji_df["frow"].iloc[j]),
            "APP_DIAM_MM": round(float(ad), 3) if np.isfinite(ad) else None,
            "FIJI_DIAM_MM": round(float(fd), 3) if np.isfinite(fd) else None,
            "DELTA_MM": round(float(ad - fd), 3) if np.isfinite(ad) and np.isfinite(fd) else None,
            "MATCH_DIST": round(float(dist), 3),
        })
    paired = pd.DataFrame(rows, columns=["APP_INDEX", "FIJI_ROW", "APP_DIAM_MM",
                                         "FIJI_DIAM_MM", "DELTA_MM", "MATCH_DIST"])
    if not paired.empty:
        paired = paired.sort_values("APP_INDEX").reset_index(drop=True)

    matched_a = {i for i, _, _ in pairs}
    matched_f = {j for _, j, _ in pairs}
    unmatched_app = [int(a_idx[i]) for i in range(len(A)) if i not in matched_a]
    unmatched_fiji = [int(fiji_df["frow"].iloc[j]) for j in range(len(F)) if j not in matched_f]

    deltas = pd.to_numeric(paired["DELTA_MM"], errors="coerce").dropna().to_numpy()
    ad = pd.to_numeric(paired["APP_DIAM_MM"], errors="coerce")
    fd = pd.to_numeric(paired["FIJI_DIAM_MM"], errors="coerce")
    summary = {
        "n_app": int(len(A)), "n_fiji": int(len(F)), "n_matched": int(len(pairs)),
        "n_unmatched_app": len(unmatched_app), "n_unmatched_fiji": len(unmatched_fiji),
        "tol": round(float(tol), 3), "aligned": aligned, "reflected": bool(reflected),
        "scale": round(float(scale), 5),
        "bias_mean_mm": round(float(np.mean(deltas)), 4) if deltas.size else None,
        "bias_sd_mm": round(float(np.std(deltas, ddof=1)), 4) if deltas.size > 1 else None,
        "loa_low_mm": None, "loa_high_mm": None,
        "rmse_mm": round(float(np.sqrt(np.mean(deltas ** 2))), 4) if deltas.size else None,
        "pearson_r": None,
    }
    if deltas.size > 1:
        b, sd = summary["bias_mean_mm"], summary["bias_sd_mm"]
        summary["loa_low_mm"] = round(b - 1.96 * sd, 4)
        summary["loa_high_mm"] = round(b + 1.96 * sd, 4)
        pair_mask = ad.notna() & fd.notna()
        if pair_mask.sum() > 1 and ad[pair_mask].std() > 0 and fd[pair_mask].std() > 0:
            summary["pearson_r"] = round(float(np.corrcoef(ad[pair_mask], fd[pair_mask])[0, 1]), 4)

    return {"paired": paired, "unmatched_app": unmatched_app,
            "unmatched_fiji": unmatched_fiji, "summary": summary}
