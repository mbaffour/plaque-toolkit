"""R app vs Python engine parity: the same file and options must give the same test and p-values.

For every fixture x (parametric, equal_var) combination this runs the Python engine in-process
(plaque_stats.read_table + run_stats) and the R app's statistics through tests/r_parity_dump.R
(Rscript, plaque_run_stats on the same CSV), and compares the test family, the unit, the omnibus
p and every adjusted pairwise p. Skipped where R or the app's packages are missing, exactly as
tests/test_ct_r1_r_app.py.

Both UIs offer the same choices (unit auto; parametric auto / parametric / nonparametric;
equal_var auto / yes / no), so no combination is skipped for lack of an option. Combinations
where a rule makes an option moot (equal_var with 2 samples or with a rank test) are still run:
both sides must ignore it identically.

Fixtures (CSV, columns group, replicate, diameter_mm; 6 plaques per plate, seeded):
  plaque_stats/example_data_wide.csv, tests/fixtures/ct_r1_B_unequal.csv, ct_r1_D_two_12v14.csv,
  ct_r1_E_oneplate_group.csv   (already in the repo)
  ct_r1_parity_*.csv, generated once with (numpy default_rng, seed in brackets; the seed was the first
  one for which the stated expectation held on the Python engine, then frozen as CSV):
      def plate_draw(mu, sd): return lambda r, n: r.normal(mu, sd) + r.normal(0, 0.05, n)
      def skew_draw(mu, s):   return lambda r, n: r.lognormal(np.log(mu), s) + r.normal(0, 0.05, n)
      # build(spec, seed): for each (group, n_plates, draw) -> n_plates plates x draw(rng, 6) plaques,
      # values rounded to 4 decimals, rows (group, "plate%d", value)
      equalvar_3x8   [4]  A,B,C = plate_draw(2.0/2.3/2.6, 0.15), 8 plates   -> classic ANOVA + Tukey
      unequalvar_3x8 [1]  plate_draw(2.0, 0.5), plate_draw(2.3, 0.05), plate_draw(2.6, 0.05), 8 plates
                          -> Shapiro passes everywhere, Levene p < 0.01 -> Welch + Games-Howell
      skewed_3x10    [3]  A,B plate_draw(2.0/2.3, 0.15), C skew_draw(2.0, 1.0), 10 plates
                          -> Shapiro rejects C -> Kruskal-Wallis + Dunn-Holm
      skewed_2x9     [2]  skew_draw(2.0, 1.0), skew_draw(2.6, 1.0), 9 plates -> Mann-Whitney
"""
import itertools
import json
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "plaque_stats"))

import plaque_stats as ps  # noqa: E402

FX = os.path.join(ROOT, "tests", "fixtures")
FIXTURES = {
    "example_wide_3x3": os.path.join(ROOT, "plaque_stats", "example_data_wide.csv"),
    "B_unequal": os.path.join(FX, "ct_r1_B_unequal.csv"),
    "D_two_12v14": os.path.join(FX, "ct_r1_D_two_12v14.csv"),
    "E_oneplate_group": os.path.join(FX, "ct_r1_E_oneplate_group.csv"),
    "equalvar_3x8": os.path.join(FX, "ct_r1_parity_equalvar_3x8.csv"),
    "unequalvar_3x8": os.path.join(FX, "ct_r1_parity_unequalvar_3x8.csv"),
    "skewed_3x10": os.path.join(FX, "ct_r1_parity_skewed_3x10.csv"),
    "skewed_2x9": os.path.join(FX, "ct_r1_parity_skewed_2x9.csv"),
    # CT-R2: a sample with zero variance (Welch undefined -> classic ANOVA + Tukey) and tied plate means
    # (R and pandas differ in the last bits of a mean; the rank tests must see the same ties)
    "zerovar": os.path.join(FX, "ct_r2_zerovar.csv"),
    "ties": os.path.join(FX, "ct_r2_ties.csv"),
}
# Expected family under parametric=auto, equal_var=auto (guards against both sides drifting together)
EXPECT_AUTO = {"example_wide_3x3": "anova", "B_unequal": "welch_anova", "D_two_12v14": "welch_t",
               "E_oneplate_group": "anova", "equalvar_3x8": "anova", "unequalvar_3x8": "welch_anova",
               "skewed_3x10": "kruskal", "skewed_2x9": "mannwhitney",
               "zerovar": "anova", "ties": "anova"}
COMBOS = list(itertools.product(("auto", "parametric", "nonparametric"), ("auto", "yes", "no")))

FAMILY = {"one-way anova": "anova", "welch anova": "welch_anova", "kruskal-wallis": "kruskal",
          "welch t-test": "welch_t", "mann-whitney u": "mannwhitney"}


def family(name):
    return FAMILY[name.replace("–", "-").lower()]


@pytest.fixture(scope="module")
def rscript():
    exe = shutil.which("Rscript")
    if not exe:
        pytest.skip("R not installed")
    pkgs = 'c("shiny","ggplot2","dplyr","tidyr","readr","DT","ggpubr","svglite","jsonlite")'
    ok = subprocess.run([exe, "-e", "q(status = !all(sapply(%s, requireNamespace, quietly = TRUE)))" % pkgs],
                        capture_output=True)
    if ok.returncode != 0:
        pytest.skip("the R app's packages are not installed")
    return exe


_cache = {}


def r_side(rscript, path, parametric, equal_var):
    key = (path, parametric, equal_var)
    if key not in _cache:
        r = subprocess.run([rscript, os.path.join(ROOT, "tests", "r_parity_dump.R"), path, "auto",
                            parametric, equal_var], cwd=os.path.join(ROOT, "plaque_stats"),
                           capture_output=True, text=True, timeout=300)
        assert r.returncode == 0, r.stderr[-2000:]
        _cache[key] = json.loads(r.stdout.strip().splitlines()[-1])
    return _cache[key]


def py_side(path, parametric, equal_var):
    df = ps.read_table(path).rename(columns={"diameter_mm": "value"})[["group", "replicate", "value"]]
    order = list(dict.fromkeys(df["group"]))
    omni, posthoc, unit, _ = ps.run_stats(df, order, "auto", parametric, equal_var=equal_var)
    pair = {"|".join(sorted(k)): v for k, v in posthoc.items()}
    return omni, unit, pair


def _close(a, b, rel, abs_):
    a_nan = a is None or a != a
    b_nan = b is None or b != b
    if a_nan or b_nan:
        return a_nan and b_nan
    return abs(a - b) <= max(abs_, rel * max(abs(a), abs(b)))


@pytest.mark.parametrize("parametric,equal_var", COMBOS)
@pytest.mark.parametrize("name", list(FIXTURES))
def test_r_and_python_agree(rscript, name, parametric, equal_var):
    omni, unit, pair = py_side(FIXTURES[name], parametric, equal_var)
    r = r_side(rscript, FIXTURES[name], parametric, equal_var)
    assert family(r["test"]) == family(omni["test"]), (r["test"], omni["test"], r["parametric_used"])
    assert r["unit"] == unit
    assert r["parametric_used"] == omni["parametric_used"]
    assert r["min_n"] == omni["min_n"]
    assert _close(r.get("levene_p"), omni["levene_p"], 1e-6, 1e-12)
    assert _close(r.get("p"), omni["p"], 1e-6, 1e-12), (r.get("p"), omni["p"])
    if parametric == "auto" and equal_var == "auto":
        assert family(omni["test"]) == EXPECT_AUTO[name]
    assert set(r["pairwise"]) == set(pair), (sorted(r["pairwise"]), sorted(pair))
    # Games-Howell and Tukey need the studentized-range CDF; R (ptukey) and Python (scipy) integrate it
    # numerically with different quadratures, so the adjusted pairwise p agree to ~1e-6, not to 1e-12.
    for k, v in pair.items():
        assert _close(r["pairwise"][k], v, 1e-5, 1e-9), (k, r["pairwise"][k], v)
