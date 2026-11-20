"""Score detection modes and sizing rules on the FROZEN benchmark (CT-R2 detection, Part 2).

    python validation/detection_benchmark/score.py --out <folder> [--parts synth,split,plates,perturb]

Detection runs once per scene and mode and is cached in <folder>/raw/ (delete it to re-detect).
Modes: ``standard`` = the CLI default, ``small`` = CLI -small (every row sized), ``auto`` = the
app's Auto detection. A sizing RULE decides which detected rows are sized; the Auto rules are
pure functions of the cached Auto rows, so every rule is judged on identical detections:

* ``auto``   -- the rule in the code right now (plaque_qc.size_ok on QC_FLAG)
* ``r1``     -- the round-1 rule, frozen here: every Auto row sized unless CORE? or NO_SIZE
* ``S``      -- only standard-pass outlines (SOURCE auto) are sized; every other row is counted
* ``S+``     -- S, but on a "small-plaque plate" (S sizes fewer than half the plaques AND no
                small-pass addition lies on a standard-mask blob) the small-pass rows are sized too
* (the "message only" alternative sizes exactly as S; it adds only a message)

Writes <folder>/scorecard.csv (long: section, group, mode_rule, metric, value), plates.csv
(per bundled plate: plaques, sized, median mm per mode/rule) and prints the tables.
"""
import argparse
import math
import os
import pickle
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as H  # noqa: E402
import perturb as P  # noqa: E402
import scenes as SC  # noqa: E402
import cv2  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

KEEP = ["X", "Y", "DIAMETER_PXL", "DIAMETER_MM", "AREA_PXL", "SOURCE", "QC_FLAG", "CORE_ONLY",
        "SIZE_UNRELIABLE", "IN_STD_BLOB"]
AUTO_RULES = ("auto", "r1", "S", "S+")
TOL5 = 0.05


# ----------------------------------------------------------------------------- detection
def _detect(path, mm, mode):
    """Rows of one image in one mode, reduced to KEEP columns, plus the dish px."""
    if mode in ("standard", "small"):
        g, dish = H.cli_run(path, mm, small=(mode == "small"))
        g["SIZE_UNRELIABLE"] = False
        g["IN_STD_BLOB"] = None
        if not len(g):
            return pd.DataFrame(columns=KEEP), dish
        g["DIAMETER_PXL"] = pd.to_numeric(g["DIAMETER_PXL"], errors="coerce")
        return g[KEEP].reset_index(drop=True), dish
    det = H.app_run(path, mm, "auto")
    df = det["df"]
    if not len(df):
        return pd.DataFrame(columns=KEEP), (det["plate"]["diam_px"] if det["plate"] else None)
    df["SIZE_UNRELIABLE"] = [bool(p.get("size_unreliable")) for p in det["plaques"]]
    return df[KEEP].reset_index(drop=True), (det["plate"]["diam_px"] if det["plate"] else None)


def _cached(raw, key, fn):
    p = os.path.join(raw, key.replace("/", "_") + ".pkl")
    if os.path.exists(p):
        with open(p, "rb") as fh:
            return pickle.load(fh)
    v = fn()
    with open(p, "wb") as fh:
        pickle.dump(v, fh)
    return v


def _write_tmp(img, name):
    p = os.path.join(tempfile.gettempdir(), "bench_%d_%s.png" % (os.getpid(), name))
    cv2.imwrite(p, img)
    return p


# ----------------------------------------------------------------------------- rules
def sized(df, rule):
    """Boolean array: which rows of one plate/scene the rule sizes."""
    n = len(df)
    if n == 0:
        return np.zeros(0, bool)
    src = df["SOURCE"].astype(str).values
    core = df["CORE_ONLY"].astype(bool).values
    if rule in ("standard", "small"):
        return np.ones(n, bool)
    if rule == "auto":
        import plaque_qc
        return np.array([plaque_qc.size_ok(f) for f in df["QC_FLAG"]], bool)
    if rule == "r1":
        return ~(core | df["SIZE_UNRELIABLE"].astype(bool).values)
    s = (src == "auto") & ~core
    if rule == "S":
        return s
    if rule == "S+":
        return s | (small_plaque_plate(df) & (src == "small") & ~core)
    raise ValueError(rule)


def small_plaque_plate(df):
    """S+'s plate test: S sizes fewer than half the plaques Auto counts AND no small-pass
    addition (SOURCE small, not CORE?) lies on a standard-mask blob."""
    src = df["SOURCE"].astype(str).values
    core = df["CORE_ONLY"].astype(bool).values
    n_s = int(((src == "auto") & ~core).sum())
    adds = (src == "small") & ~core
    blob = np.array([bool(v) for v in df["IN_STD_BLOB"].values])
    return bool(n_s < 0.5 * len(df) and adds.any() and not (blob & adds).any())


def mode_rules(parts_modes):
    out = []
    for m in parts_modes:
        if m == "auto":
            out += [("auto", r) for r in AUTO_RULES]
        else:
            out.append((m, m))
    return out


# ----------------------------------------------------------------------------- scenes
def run_synth(raw, modes):
    recs = []                     # one per (truth disc, mode, rule)
    for ppm in SC.SYNTH_PPMS:
        for typ in SC.SYNTH_TYPES:
            img, truth, dish_px = SC.synth_scene(ppm, typ)
            path = None
            tp = np.array([[d["x"], d["y"]] for d in truth])
            tol = SC.synth_tolerance(truth)
            for mode in modes:
                def _go():
                    nonlocal path
                    path = path or _write_tmp(img, "synth")
                    return _detect(path, SC.DISH_MM, mode)
                df, _dish = _cached(raw, "synth_%s_%g_%s" % (typ, ppm, mode), _go)
                pp = df[["X", "Y"]].values.astype(float) if len(df) else np.zeros((0, 2))
                pairs = dict(H.match(tp, pp, tol))
                for rule in ([r for m, r in mode_rules([mode])]):
                    ok = sized(df, rule)
                    for i, d in enumerate(truth):
                        j = pairs.get(i)
                        rec = dict(section="synth", group="%s %g px/mm" % (typ, ppm), typ=typ, ppm=ppm,
                                   D_mm=d["D_mm"], D_px=d["D_px"], kind=d["kind"], mode=mode, rule=rule,
                                   detected=j is not None, n_fp=len(df) - len(pairs))
                        if j is not None:
                            rec.update(bias=float(df["DIAMETER_PXL"].iloc[j]) / d["D_px"] - 1,
                                       sized=bool(ok[j]), src=("core" if df["CORE_ONLY"].iloc[j]
                                                               else df["SOURCE"].iloc[j]),
                                       flag=df["QC_FLAG"].iloc[j])
                        recs.append(rec)
            if path:
                os.remove(path)
            print("synth", typ, ppm, "done", flush=True)
    return pd.DataFrame(recs)


def run_split(raw, modes):
    recs = []
    for i, case in enumerate(SC.split_cases()):
        var, D, s, discs, soft, noise = case
        img = None
        path = None
        for mode in modes:
            def _go():
                nonlocal path, img
                if path is None:
                    img = SC.split_scene(i)[0]
                    path = _write_tmp(img, "split")
                return _detect(path, SC.SPLIT_MM, mode)
            df, _dish = _cached(raw, "split_%02d_%s" % (i, mode), _go)
            for rule in [r for m, r in mode_rules([mode])]:
                ok = sized(df, rule)
                for k, (x, y, Dt) in enumerate(discs):
                    j = None
                    if len(df):
                        dd = np.hypot(df["X"].astype(float) - x, df["Y"].astype(float) - y)
                        j = int(dd.idxmin()) if dd.min() < 0.35 * Dt else None
                    rec = dict(section="split", group=var, case=i, D=D, s=s,
                               disc=("centre" if k == 0 else "nbr%d" % k), D_true=Dt, mode=mode,
                               rule=rule, detected=j is not None)
                    if j is not None:
                        rec.update(bias=float(df["DIAMETER_PXL"].iloc[j]) / Dt - 1, sized=bool(ok[j]),
                                   src=("core" if df["CORE_ONLY"].iloc[j] else df["SOURCE"].iloc[j]),
                                   flag=df["QC_FLAG"].iloc[j])
                    recs.append(rec)
        if path:
            os.remove(path)
    print("split done", flush=True)
    return pd.DataFrame(recs)


def bias_metrics(d):
    """Scorecard numbers for one group of per-truth records (one mode + rule)."""
    n = len(d)
    det = d[d["detected"]]
    sz = det[det["sized"].astype(bool)] if len(det) else det
    b = sz["bias"].astype(float).values if len(sz) else np.zeros(0)
    worst = float(b[np.argmax(np.abs(b))]) if len(b) else float("nan")
    return {"n_truth": n, "detected_pct": 100.0 * len(det) / n if n else float("nan"),
            "sized_pct_of_detected": 100.0 * len(sz) / len(det) if len(det) else float("nan"),
            "n_sized": len(sz),
            "sized_median_bias_pct": 100.0 * float(np.median(b)) if len(b) else float("nan"),
            "sized_beyond5_pct": 100.0 * float(np.mean(np.abs(b) > TOL5)) if len(b) else float("nan"),
            "sized_worst_bias_pct": 100.0 * worst}


def scene_scorecard(recs):
    rows = []
    if recs is None or not len(recs):
        return rows
    for (section, mode, rule), d in recs.groupby(["section", "mode", "rule"], sort=False):
        groups = [(g, dd) for g, dd in d.groupby("group", sort=False)] + [("ALL " + section, d)]
        for g, dd in groups:
            for k, v in bias_metrics(dd).items():
                rows.append(dict(section=section, group=g, mode_rule=_mr(mode, rule), metric=k, value=v))
    return rows


def _mr(mode, rule):
    return mode if mode == rule else "auto:" + rule


# ----------------------------------------------------------------------------- bundled plates
def _median_mm(df, ok):
    v = pd.to_numeric(df["DIAMETER_MM"], errors="coerce").values[ok] if len(df) else np.zeros(0)
    v = v[np.isfinite(v) & (v > 0)]
    return float(np.median(v)) if len(v) else float("nan")


def run_plates(raw, modes):
    rows = []
    for name, path, mm in H.bundled_plates():
        for mode in modes:
            df, dish = _cached(raw, "plate_%s_%s" % (name, mode), lambda: _detect(path, mm, mode))
            for rule in [r for m, r in mode_rules([mode])]:
                ok = sized(df, rule)
                rows.append(dict(plate=name, mode_rule=_mr(mode, rule), n=len(df), n_sized=int(ok.sum()),
                                 median_mm=_median_mm(df, ok),
                                 small_plate=(small_plaque_plate(df) if mode == "auto" else None)))
        print("plate", name, "done", flush=True)
    return pd.DataFrame(rows)


def common_median(a, b, ok_a, ok_b, tol):
    """Medians (mm) of a and b over the plaques BOTH size (one-to-one centre match)."""
    if not len(a) or not len(b):
        return float("nan"), float("nan"), 0
    ia = np.where(ok_a)[0]
    ib = np.where(ok_b)[0]
    pa = a[["X", "Y"]].values.astype(float)[ia]
    pb = b[["X", "Y"]].values.astype(float)[ib]
    pr = H.match(pa, pb, tol)
    if not pr:
        return float("nan"), float("nan"), 0
    da = pd.to_numeric(a["DIAMETER_MM"], errors="coerce").values[ia[[i for i, _ in pr]]]
    db = pd.to_numeric(b["DIAMETER_MM"], errors="coerce").values[ib[[j for _, j in pr]]]
    return float(np.median(da)), float(np.median(db)), len(pr)


def run_perturb(raw, modes):
    plates = {n: (p, mm) for n, p, mm in H.bundled_plates()}
    rows = []
    for name in P.PERTURB_PLATES:
        path, mm = plates[name]
        img0 = cv2.imread(path, cv2.IMREAD_UNCHANGED)
        if img0.ndim == 2:
            img0 = cv2.cvtColor(img0, cv2.COLOR_GRAY2BGR)
        for mode in modes:
            base, _d0 = _cached(raw, "plate_%s_%s" % (name, mode), lambda: _detect(path, mm, mode))
            for pn in P.PERTS:
                img, fwd = P.perturb(pn, img0)

                def _go():
                    tp = _write_tmp(img, "pert")
                    try:
                        return _detect(tp, mm, mode)
                    finally:
                        os.remove(tp)
                df, _dish = _cached(raw, "pert_%s_%s_%s" % (name, pn, mode), _go)
                bx = np.array([fwd(x, y) for x, y in base[["X", "Y"]].values.astype(float)]) \
                    if len(base) else np.zeros((0, 2))
                tol = np.maximum(np.sqrt(pd.to_numeric(base["AREA_PXL"]).values.astype(float) / np.pi)
                                 * P.scale_factor(pn) * 0.5, 4) if len(base) else 4
                pr = H.match(bx, df[["X", "Y"]].values.astype(float) if len(df) else np.zeros((0, 2)), tol)
                for rule in [r for m, r in mode_rules([mode])]:
                    o0, o1 = sized(base, rule), sized(df, rule)
                    n_ok = sum(1 for i, j in pr if o0[i] != o1[j])
                    n_cls = sum(1 for i, j in pr if _cls(base, i) != _cls(df, j))
                    m0, m1 = _median_mm(base, o0), _median_mm(df, o1)
                    rows.append(dict(plate=name, pert=pn, mode_rule=_mr(mode, rule), n0=len(base), n=len(df),
                                     sized0=int(o0.sum()), sized=int(o1.sum()), matched=len(pr),
                                     cls_switch=n_cls, ok_switch=n_ok, med0=m0, med=m1,
                                     dmed_pct=100.0 * (m1 / m0 - 1) if (m0 == m0 and m1 == m1 and m0) else float("nan")))
            print("perturb", name, mode, "done", flush=True)
    return pd.DataFrame(rows)


def _cls(df, i):
    return "core" if bool(df["CORE_ONLY"].iloc[i]) else df["SOURCE"].iloc[i]


def perturb_scorecard(pt):
    rows = []
    if pt is None or not len(pt):
        return rows
    for mr, d in pt.groupby("mode_rule", sort=False):
        g1 = d[d["pert"].isin(["gain+1", "gain-1"])]
        rows.append(dict(section="perturb", group="gain +-1 %", mode_rule=mr, metric="ok_switches",
                         value=int(g1["ok_switch"].sum())))
        rows.append(dict(section="perturb", group="gain +-1 %", mode_rule=mr, metric="class_switches",
                         value=int(g1["cls_switch"].sum())))
        for pn, dd in d.groupby("pert", sort=False):
            v = dd["dmed_pct"].abs()
            rows.append(dict(section="perturb", group=pn, mode_rule=mr, metric="max_abs_median_shift_pct",
                             value=float(v.max()) if v.notna().any() else float("nan")))
            rows.append(dict(section="perturb", group=pn, mode_rule=mr, metric="ok_switches",
                             value=int(dd["ok_switch"].sum())))
    return rows


# ----------------------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True, help="folder for the cache, scorecard.csv and plates.csv")
    ap.add_argument("--parts", default="synth,split,plates,perturb")
    ap.add_argument("--modes", default="standard,small,auto")
    a = ap.parse_args(argv)
    raw = os.path.join(a.out, "raw")
    os.makedirs(raw, exist_ok=True)
    parts = a.parts.split(",")
    modes = a.modes.split(",")
    t0 = time.time()
    card = []
    if "synth" in parts:
        sy = run_synth(raw, modes)
        sy.to_csv(os.path.join(a.out, "synth_rows.csv"), index=False)
        card += scene_scorecard(sy)
    if "split" in parts:
        spl = run_split(raw, modes)
        spl.to_csv(os.path.join(a.out, "split_rows.csv"), index=False)
        card += scene_scorecard(spl)
    if "plates" in parts:
        pl = run_plates(raw, modes)
        pl.to_csv(os.path.join(a.out, "plates.csv"), index=False)
        print("\nBundled plates: plaques / sized / median mm")
        t = pl.assign(cell=lambda d: ["%d/%d/%s" % (n, s, ("%.2f" % m) if m == m else "-")
                                      for n, s, m in zip(d["n"], d["n_sized"], d["median_mm"])])
        print(t.pivot(index="plate", columns="mode_rule", values="cell").to_string())
    if "perturb" in parts:
        pt = run_perturb(raw, modes)
        pt.to_csv(os.path.join(a.out, "perturb_rows.csv"), index=False)
        card += perturb_scorecard(pt)
    cd = pd.DataFrame(card)
    cd.to_csv(os.path.join(a.out, "scorecard.csv"), index=False)
    if len(cd):
        pd.set_option("display.width", 250)
        for section, d in cd.groupby("section", sort=False):
            print("\n== %s" % section)
            tab = d.pivot_table(index=["group", "metric"], columns="mode_rule", values="value",
                                aggfunc="first", sort=False)
            print(tab.round(1).to_string())
    print("\n%.0f s" % (time.time() - t0))
    return cd


if __name__ == "__main__":
    main()
