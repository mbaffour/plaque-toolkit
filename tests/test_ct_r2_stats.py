"""CT-R2 statistics engine and agreement wording (plaque_stats/plaque_stats.py,
plaque_stats/agreement/agreement.py, app/agreement.py).

Each test pins one finding of the round-2 stats-maths tester (N1..N11) or one of the two small
additions (--detect, the sensitivity line). Expected values come from scipy / statsmodels / a
formula stated in the test, never from a previous run of the engine.
"""
import io
import contextlib
import itertools
import math
import os
import sys

import numpy as np
import pandas as pd
import pytest
from scipy import stats as st

import matplotlib
matplotlib.use("Agg")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "plaque_stats"))

import plaque_stats as ps  # noqa: E402


# --------------------------------------------------------------------------- helpers
def _units(groups, plaques=2):
    """{group: unit values} -> a frame whose plate means ARE those values (2 identical plaques
    per plate, so the plate is the unit and its mean is exact)."""
    rows = []
    for g, vals in groups.items():
        for i, v in enumerate(vals):
            for _ in range(plaques):
                rows.append({"group": g, "replicate": "%s_p%d" % (g, i), "value": float(v)})
    return pd.DataFrame(rows)


def _args(tmp_path, data, **kw):
    a = dict(ps.DEFAULTS)
    a.update({"data": data, "group": "group", "value": "value", "replicate": "replicate",
              "out": str(tmp_path / "out"), "formats": ["png"], "_stamp": "", "stats_table": False,
              "legend_key": False, "dpi": 40})
    a.update(kw)
    return a


def _run(tmp_path, data, **kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        res = ps.run(_args(tmp_path, data, **kw))
    return res, buf.getvalue()


def _report(res):
    out = res["out"]
    name = [f for f in os.listdir(out) if f.endswith(".md")][0]
    with open(os.path.join(out, name), encoding="utf-8") as fh:
        return fh.read()


def _skewed_c(n=9, seed=4):
    """A, B normal; C lognormal sigma 1 (clearly skewed: Shapiro rejects it far below 0.05/3)."""
    r = np.random.default_rng(seed)
    while True:
        g = {"A": r.normal(2.0, 0.2, n), "B": r.normal(2.3, 0.2, n), "C": r.lognormal(np.log(2.6), 1.0, n)}
        ps_ = {k: st.shapiro(v).pvalue for k, v in g.items()}
        if ps_["C"] < 0.001 and ps_["A"] > 0.2 and ps_["B"] > 0.2:
            return g


# =========================================================================== 1. wording
def test_N1_dunnett_override_describes_what_ran():
    g = _skewed_c()
    om = ps.run_stats(_units(g), list("ABC"), "auto", "auto", posthoc="dunnett", control="A")[0]
    assert om["posthoc"] == "Dunnett" and om["parametric_used"]
    assert "rank-based test is used" not in om["choice_note"]
    assert "Dunnett's test (parametric) was run because you chose it" in om["choice_note"]
    assert "rejects normality for C" in om["choice_note"]


def test_N2_levene_p_goes_through_p_text(tmp_path):
    # Levene p < 0.001: one sample 100x more spread than the others
    lin = np.linspace(-1, 1, 12)
    g = {"A": 2 + 0.01 * lin, "B": 2 + lin, "C": 2.5 + 0.01 * lin}
    assert st.levene(*g.values()).pvalue < 0.001
    res, out = _run(tmp_path, _units(g), parametric="parametric")
    rep = _report(res)
    om = res["omni"]
    texts = [om["variance_rule"], om["choice_note"], rep, out] + om["warnings"] + om["notes"]
    assert not any("p = <" in t or "p = >" in t for t in texts)
    assert "Levene p < 0.001" in om["variance_rule"] and "Levene p < 0.001" in rep
    assert any(w.startswith("Levene p < 0.001: group variances differ") for w in om["warnings"])


def test_N7_dunnett_spread_advice_can_be_followed():
    # 3 plates: the note; and a clear spread difference at 8 plates: the warning
    g3 = {"A": [2.0, 2.1, 2.2], "B": [2.5, 2.9, 3.4], "C": [3.0, 3.05, 3.1]}
    om = ps.run_stats(_units(g3), list("ABC"), "auto", "auto", posthoc="dunnett", control="A")[0]
    note = [n for n in om["notes"] if n.startswith("ANOVA and Dunnett's test assume")]
    assert note and note[0].endswith("If you expect the groups to differ in spread, drop --posthoc "
                                     "dunnett and use --equal-var no (Welch ANOVA + Games-Howell).")
    r = np.random.default_rng(11)
    g8 = {"A": r.normal(2, 0.5, 8), "B": r.normal(2, 0.05, 8), "C": r.normal(2, 0.05, 8)}
    om = ps.run_stats(_units(g8), list("ABC"), "auto", "parametric", posthoc="dunnett", control="A")[0]
    w = [x for x in om["warnings"] if x.startswith("The spread differs")]
    assert w and w[0].endswith("Welch ANOVA + Games-Howell is the safer analysis (drop --posthoc "
                               "dunnett and use --equal-var no).")
    # the advice must be accepted by the engine: drop dunnett, --equal-var no -> Welch + GH
    om2 = ps.run_stats(_units(g8), list("ABC"), "auto", "parametric", equal_var="no")[0]
    assert om2["test"] == "Welch ANOVA" and om2["posthoc"] == "Games-Howell"


def test_N9_zero_variance_fallback_never_recommends_welch():
    g = {"A": [2.0, 2.0, 2.0], "B": [2.4, 2.6, 2.9], "C": [3.0, 3.2, 3.1]}
    om = ps.run_stats(_units(g), list("ABC"), "auto", "auto", equal_var="no")[0]
    assert om["test"] == "one-way ANOVA" and om["posthoc"] == "Tukey HSD"       # the fallback
    texts = om["warnings"] + om["notes"]
    assert not any("safer analysis" in t or "choose --equal-var no" in t for t in texts)
    assert any("Welch's ANOVA is not an alternative here: A has no spread" in t for t in texts)
    assert "Welch's ANOVA is undefined here (a sample has zero variance)" in om["variance_rule"]


def test_N11_spread_note_counts_testable_samples_and_grammar():
    g = {"A": [2.0, 2.1, 2.2], "B": [2.5, 2.9, 3.4], "C": [3.0]}       # C: 1 plate, untestable
    om = ps.run_stats(_units(g), list("ABC"), "auto", "auto")[0]
    note = [n for n in om["notes"] if n.startswith("ANOVA and Tukey assume")]
    assert note and "With 3 plates per group" in note[0]
    assert not any("With 1 plates" in n for n in om["notes"])
    assert ps._plural(1, "plate") == "1 plate"


def test_N11_tost_and_power_say_what_they_are_not(tmp_path):
    g = {"A": [2.0, 2.1, 2.2, 2.05], "B": [2.05, 2.12, 2.2, 2.1], "C": [2.6, 2.7, 2.8, 2.75]}
    res, _ = _run(tmp_path, _units(g), equivalence_margin=0.3)
    rep = _report(res)
    assert "TOST p-values are per pair, not adjusted across pairs." in rep
    s = ps.power_sentence(res["omni"]["power"], "replicate")
    assert s.startswith("**Power:**")
    assert "for a single two-sample comparison, without multiplicity adjustment" in s


def test_equal_var_help_describes_the_real_rule():
    h = " ".join(ps.build_args().format_help().split())
    assert "3-fold" not in h
    assert "Levene p < 0.05" in h and "Bonferroni-adjusted F test" in h


@pytest.mark.parametrize("name,content", [("fake.xlsx", b"group,replicate,value\nA,p1,1\n"),
                                          ("empty.xlsx", b"")])
def test_unreadable_workbook_is_a_plain_error(tmp_path, name, content):
    p = tmp_path / name
    p.write_bytes(content)
    with pytest.raises(ps.StatsError) as e:
        ps.read_table(str(p))
    assert "could not read %s as an Excel workbook" % name in str(e.value)
    with pytest.raises(ps.StatsError):
        ps.read_table(str(tmp_path / "missing.csv"))


# =========================================================================== 2. comment lines
def _hash_csv(tmp_path, names, fname, comments=()):
    r = np.random.default_rng(5)
    lines = list(comments) + ["group,replicate,value"]
    for g, mu in zip(names, (2.0, 2.4, 2.9)):
        for p in range(3):
            for v in r.normal(mu, 0.2, 4):
                lines.append("%s,plate%d,%.4f" % (g, p + 1, v))
    path = tmp_path / fname
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def test_N6_hash_names_after_the_header_are_data(tmp_path):
    a = _hash_csv(tmp_path, ["#1", "#2", "#3"], "hash.csv", comments=["# exported by X", "# 2026"])
    b = _hash_csv(tmp_path, ["s1", "s2", "s3"], "plain.csv")
    df, info = ps.read_table(a, return_info=True)
    assert info["rows"] == 36 and info["comment_lines"] == 2
    assert "2 lines starting with # skipped" in info["note"]
    assert list(dict.fromkeys(df["group"])) == ["#1", "#2", "#3"]
    ra, _ = _run(tmp_path / "a", a)
    rb, _ = _run(tmp_path / "b", b)
    assert ra["order"] == ["#1", "#2", "#3"]
    assert ra["omni"]["test"] == rb["omni"]["test"]
    assert ra["omni"]["p"] == pytest.approx(rb["omni"]["p"], rel=1e-12)
    pa = [r["p_adj"] for r in ra["omni"]["pairwise"]]
    pb = [r["p_adj"] for r in rb["omni"]["pairwise"]]
    assert pa == pytest.approx(pb, rel=1e-12)


def test_N6_a_hash_group_row_in_the_middle_is_kept(tmp_path):
    # as the tester's labels2.csv: a sample literally called '#' between other samples
    p = tmp_path / "mid.csv"
    p.write_text("group,replicate,value\nA,p1,1.0\n#,p1,2.0\n#,p2,2.5\nA,p2,1.5\n", encoding="utf-8")
    df, info = ps.read_table(str(p), return_info=True)
    assert len(df) == 4 and info["comment_lines"] == 0 and "skipped" not in info["note"]
    assert sorted(df["group"]) == ["#", "#", "A", "A"]
