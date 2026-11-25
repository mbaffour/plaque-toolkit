"""Power / detectable-difference maths on every supported SciPy (CI 2026-11).

On SciPy 1.17 ``scipy.stats.nct.sf`` / ``cdf`` return NaN for some moderate-to-large
noncentralities where SciPy 1.13 returns 1.0 / 0.0, and ``brentq`` (which now refuses NaN)
stopped EVERY analysis inside power_summary(). These tests pin:

* the power function against an independent reference (a numerical integral of the noncentral t
  over the chi-square scale; statsmodels too when it is installed and finite);
* the detectable difference / plates needed with SciPy 1.17's NaNs SIMULATED on any SciPy
  (monkeypatched nct.sf / nct.cdf), so the regression is caught on the developer's 3.9 machine;
* that a failure inside the power / sensitivity / variance-share extras never fails the analysis.
"""
import contextlib
import io
import math
import os
import sys

import numpy as np
import pandas as pd
import pytest
from scipy import integrate
from scipy import stats as st

import matplotlib
matplotlib.use("Agg")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "plaque_stats"))

import plaque_stats as ps  # noqa: E402


# --------------------------------------------------------------------------- reference
def _power_reference(d, n, alpha=0.05):
    """Two-sided two-sample t-test power written out from the definition of the noncentral t,
    T = (Z + nc) / S with S = sqrt(V / df), V ~ chi2(df): power = E_S[Phi(nc - tc S) +
    Phi(-tc S - nc)], integrated over V directly (no scipy noncentral distribution involved)."""
    df = 2 * n - 2
    nc = d * math.sqrt(n / 2.0)
    tc = st.t.ppf(1 - alpha / 2.0, df)
    lo, hi = st.chi2.ppf(1e-17, df), st.chi2.isf(1e-17, df)

    def f(v):
        s = math.sqrt(v / df)
        return st.chi2.pdf(v, df) * (st.norm.cdf(nc - tc * s) + st.norm.cdf(-tc * s - nc))
    pts = [x for x in (df * (nc / tc) ** 2, float(df)) if lo < x < hi]
    val, _ = integrate.quad(f, lo, hi, points=pts or None, limit=500, epsabs=1e-14, epsrel=1e-12)
    return min(1.0, max(0.0, val))


GRID_N = [2, 3, 4, 6, 8, 12, 15, 30, 60, 200, 6000]
GRID_D = [0.0, 0.05, 0.3, 0.8, 1.5, 3.0, 5.0, 10.0, 20.0, 50.0, 200.0, 1e4]


def test_power_matches_the_definition_on_a_grid():
    """The power function against its definition on a (n, d) grid that crosses the noncentralities
    where SciPy 1.17's nct returns NaN. The message lists every miss, so one CI run shows them all."""
    bad = []
    for n in GRID_N:
        for d in GRID_D:
            got = ps._power_two_sample(d, n)
            ref = _power_reference(d, n)
            if not (math.isfinite(got) and abs(got - ref) <= 1e-7):
                bad.append("n=%d (df %d) d=%g nc=%.4g: got %r, reference %r"
                           % (n, 2 * n - 2, d, d * math.sqrt(n / 2.0), got, ref))
    assert not bad, "\n".join(bad)


def test_power_is_alpha_at_zero_monotone_and_reaches_one():
    for n in GRID_N:
        assert ps._power_two_sample(0.0, n) == pytest.approx(0.05, abs=1e-9)
        ps_ = [ps._power_two_sample(d, n) for d in GRID_D]
        assert all(0.0 <= p <= 1.0 for p in ps_)
        assert all(b >= a - 1e-12 for a, b in zip(ps_, ps_[1:])), (n, ps_)
        assert ps._power_two_sample(1e4, n) == pytest.approx(1.0, abs=1e-12)


@pytest.mark.parametrize("d,n", [(-0.1, 3), (float("nan"), 3), (0.5, 1), (0.5, 0)])
def test_power_refuses_arguments_outside_its_domain(d, n):
    with pytest.raises(ValueError):
        ps._power_two_sample(d, n)


def test_power_matches_statsmodels_where_statsmodels_is_finite():
    """statsmodels' TTestIndPower computes the same power (it also calls scipy's nct, so on a
    SciPy where that is NaN the point is skipped -- the definition test above covers it).
    statsmodels evaluates the noncentral t through a different route and differs from both scipy
    and the definition by up to 2.4e-7 (n = 2, d = 20), hence 1e-6 here; the definition test
    above holds the engine to 1e-7."""
    power_mod = pytest.importorskip("statsmodels.stats.power")
    tt = power_mod.TTestIndPower()
    checked = 0
    for n in GRID_N:
        for d in GRID_D[1:]:
            ref = float(tt.power(effect_size=d, nobs1=n, alpha=0.05, ratio=1.0))
            if not math.isfinite(ref):
                continue
            checked += 1
            assert ps._power_two_sample(d, n) == pytest.approx(ref, abs=1e-6), (n, d)
    assert checked > len(GRID_N)


# --------------------------------------------------------------------------- SciPy 1.17, simulated
# Points where SciPy 1.17.1 returned NaN in CI run 44719040150 (n per group, noncentrality):
# (60, 10.56), (15, 10.56), (6, 13.35), (3, 18.89), (4, 21.81), (8, 30.84), (12, 37.77),
# (6000, 26.39). The smallest is nc = 10.56. 1.17 is NaN in a band (it gave finite values at some
# larger nc); the simulation makes EVERY nc >= 10 NaN, a superset of every failing point, so it
# is stricter than 1.17 itself. The "band" variant keeps large nc finite, as 1.17 sometimes did.
NAN_FROM_NC = 10.0


def _simulate_scipy_117(monkeypatch, band_top=None):
    nct = st.nct
    orig_sf, orig_cdf = nct.sf, nct.cdf

    def broken(fn):
        def wrapped(x, df, nc, *a, **k):
            out = np.asarray(fn(x, df, nc, *a, **k), dtype=float)
            ncv = np.broadcast_to(np.asarray(nc, dtype=float), out.shape)
            hit = ncv >= NAN_FROM_NC
            if band_top is not None:
                hit &= ncv < band_top
            out = np.where(hit, np.nan, out)
            return out[()] if out.ndim == 0 else out
        return wrapped
    monkeypatch.setattr(nct, "sf", broken(orig_sf))
    monkeypatch.setattr(nct, "cdf", broken(orig_cdf))


def _groups(n, k=3, seed=3):
    r = np.random.default_rng(seed)
    return {g: list(r.normal(2.0 + 0.2 * i, 0.3, n)) for i, g in enumerate("ABCDEFG"[:k])}


@pytest.mark.parametrize("band_top", [None, 100.0])
@pytest.mark.parametrize("n", [2, 3, 4, 6, 8, 12, 15, 60, 6000])
def test_detectable_difference_survives_nan_from_scipy(monkeypatch, n, band_top):
    g = _groups(n)
    ref = ps.power_summary(g, detect=0.05)
    with monkeypatch.context() as m:
        _simulate_scipy_117(m, band_top)
        assert math.isnan(float(st.nct.sf(1.0, 4, 50.0)))         # the simulation is active
        got = ps.power_summary(g, detect=0.05)
    assert got["available"] and ref["available"]
    assert got["detectable_diff"] == pytest.approx(ref["detectable_diff"], rel=1e-6)
    for key in ("n_for_largest", "n_for_smallest", "n_for_detect"):
        assert got.get(key) == ref.get(key), key


def test_power_with_scipy_117_nans_still_matches_the_definition(monkeypatch):
    """With nct NaN from nc = 10 on, every power value comes from the integral fallback."""
    _simulate_scipy_117(monkeypatch)
    bad = []
    for n in GRID_N:
        for d in GRID_D:
            got, ref = ps._power_two_sample(d, n), _power_reference(d, n)
            if not (math.isfinite(got) and abs(got - ref) <= 1e-7):
                bad.append("n=%d d=%g: got %r, reference %r" % (n, d, got, ref))
    assert not bad, "\n".join(bad)


@pytest.mark.parametrize("d", [0.05, 0.3, 1.0, 3.0, 8.0, 40.0])
def test_plates_needed_survives_nan_from_scipy(monkeypatch, d):
    ref = ps.plates_needed(d)
    with monkeypatch.context() as m:
        _simulate_scipy_117(m)
        got = ps.plates_needed(d)
    assert got == ref


def _example_frame():
    r = np.random.default_rng(11)
    rows = []
    for g, mu in (("T4", 2.6), ("T7", 1.9), ("lambda", 3.1)):
        for p in range(4):
            for v in r.normal(mu, 0.3, 15):
                rows.append({"group": g, "replicate": "plate%d" % p, "value": round(float(v), 4)})
    return pd.DataFrame(rows)


def _run_args(tmp_path, data):
    a = dict(ps.DEFAULTS)
    a.update({"data": data, "group": "group", "value": "value", "replicate": "replicate",
              "out": str(tmp_path / "out"), "formats": ["png"], "_stamp": "", "stats_table": False,
              "legend_key": False, "dpi": 40})
    return a


def test_a_whole_analysis_completes_with_scipy_117_nans(monkeypatch, tmp_path):
    df = _example_frame()
    with contextlib.redirect_stdout(io.StringIO()):
        ref = ps.run(_run_args(tmp_path / "ref", df))
        with monkeypatch.context() as m:
            _simulate_scipy_117(m)
            got = ps.run(_run_args(tmp_path / "sim", df))
    pr, pg = ref["omni"]["power"], got["omni"]["power"]
    assert pg["available"]
    assert pg["detectable_diff"] == pytest.approx(pr["detectable_diff"], rel=1e-6)
    assert got["paste_sentence"] == ref["paste_sentence"]


# --------------------------------------------------------------------------- defence in depth
@pytest.mark.parametrize("extra,func", [("power", "power_summary"), ("sensitivity", "sensitivity_check"),
                                        ("icc", "plate_variance_share")])
def test_a_failing_extra_never_fails_the_analysis(monkeypatch, tmp_path, extra, func):
    def boom(*a, **k):
        raise RuntimeError("simulated failure")
    monkeypatch.setattr(ps, func, boom)
    with contextlib.redirect_stdout(io.StringIO()):
        res = ps.run(_run_args(tmp_path, _example_frame()))
    om = res["omni"]
    assert om.get("p") is not None
    val = om[extra]
    assert val["available"] is False and "simulated failure" in val["reason"]
    assert any("simulated failure" in nt and "not available" in nt for nt in om["notes"]), om["notes"]
    if extra == "power":
        assert "not estimated (" in ps.power_sentence(val)
    if extra == "sensitivity":
        assert "not available" in ps.sensitivity_text(om)
    if extra == "icc":
        assert val["icc"] != val["icc"]
