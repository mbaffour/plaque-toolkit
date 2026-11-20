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


# =========================================================================== 3. normality gate
def _borderline(k=3, n=8, seed=21):
    """k normal samples of n plates; the first has a Shapiro p between 0.05/k and 0.05, all the
    others p > 0.2: the old per-sample rule called it non-normal, Bonferroni does not."""
    r = np.random.default_rng(seed)
    while True:
        g = {"S%d" % i: r.normal(2.0, 0.3, n) for i in range(k)}
        p = [st.shapiro(v).pvalue for v in g.values()]
        if 0.05 / k < p[0] < 0.05 and min(p[1:]) > 0.2:
            return g, p


@pytest.mark.parametrize("k", [2, 3, 5])
def test_item3_bonferroni_gate_keeps_borderline_normal_data_parametric(k):
    g, p = _borderline(k)
    om = ps.run_stats(_units(g), list(g), "auto", "auto")[0]
    assert om["parametric_used"] and om["test"] in ("one-way ANOVA", "Welch ANOVA", "Welch t-test")
    assert ("Shapiro–Wilk (Bonferroni over %d samples) does not reject normality (smallest %s, "
            "threshold 0.05/%d = %.3g)" % (k, ps.p_text(min(p)), k, 0.05 / k)) in om["choice_note"]


def test_item3_bonferroni_gate_still_catches_a_skewed_sample():
    g = _skewed_c()
    om = ps.run_stats(_units(g), list("ABC"), "auto", "auto")[0]
    assert om["test"] == "Kruskal–Wallis"
    pc = st.shapiro(g["C"]).pvalue
    assert ("Shapiro–Wilk (Bonferroni over 3 samples) rejects normality for C (%s, threshold 0.05/3 = "
            "0.0167), so a rank-based test is used" % ps.p_text(pc)) in om["choice_note"]


def test_item3_below_8_plates_nothing_changes():
    g, _ = _borderline(3, n=7)
    g["S0"] = np.exp(g["S0"] * 3)                       # even a skewed sample stays parametric
    om = ps.run_stats(_units(g), list(g), "auto", "auto")[0]
    assert om["parametric_used"] and om["choice_note"].startswith("With fewer than 8 plates per sample (here 7)")


# =========================================================================== 6. agreement wording
sys.path.insert(0, os.path.join(ROOT, "plaque_stats", "agreement"))
import agreement as cli_ag  # noqa: E402
sys.path.insert(0, ROOT)
from app import agreement as app_ag  # noqa: E402


def _pairs(n, seed=2, offset=0.0, noise=0.08):
    r = np.random.default_rng(seed)
    ref = r.uniform(0.6, 2.6, n)
    return list(ref + offset + r.normal(0, noise, n)), list(ref)


def test_N8_icc_graded_on_the_interval_in_both_copies():
    assert cli_ag.icc_grade_interval(0.709, 0.986) == "moderate to excellent"
    assert cli_ag.icc_grade_interval(0.95, 0.99) == "excellent"
    assert cli_ag.icc_grade_interval(float("nan"), 0.9) == ""
    tool, ref = _pairs(15, noise=0.35)
    for mod in (cli_ag, app_ag):
        s = mod.full_stats(tool, ref)
        sent = mod.report_sentence(s, "mm", "plaque diameters")
        want = ("ICC(A,1) = %.3f (95%% CI %.3f-%.3f): %s agreement, graded on the interval (Koo & Li 2016)"
                % (s["icc"], s["icc_lo"], s["icc_hi"], cli_ag.icc_grade_interval(s["icc_lo"], s["icc_hi"])))
        assert want in sent
        assert "(%s agreement)" % cli_ag.icc_grade(s["icc"]) not in sent


def test_N8_no_grade_without_an_interval_and_no_verdict_below_5_pairs():
    tool, ref = [1.0, 1.52, 2.1, 0.8], [1.02, 1.5, 2.0, 0.9]
    s = cli_ag.full_stats(tool, ref)
    sent = cli_ag.report_sentence(s, "mm", "plaque diameters")
    assert sent.startswith("With only 4 pairs (too few pairs for a verdict), plaque diameters measured with "
                           "Plaque Toolkit were compared with Fiji / ImageJ (n = 4): Pearson r = ")
    for verdict in ("agreed", "appeared to agree", "did NOT", "interchangeably", "correlated",
                    "excellent", "good agreement", "poor agreement"):
        assert verdict not in sent
    assert "n too small for an interval, so no agreement grade" in sent
    # a poor ICC from 3 pairs: still numbers only
    s3 = cli_ag.full_stats([1.0, 2.0, 1.5], [1.6, 1.2, 1.9])
    assert "cannot be used interchangeably" not in cli_ag.report_sentence(s3)


def test_N8_proportional_bias_clause_and_small_n_power():
    tool, ref = _pairs(8)
    s = cli_ag.full_stats(tool, ref)
    assert s["ba_slope_p"] >= 0.05
    sent = cli_ag.report_sentence(s, "mm", "plaque diameters")
    assert ("No proportional bias was detected (Bland-Altman slope %+.3f, %s; with 8 pairs there is "
            "little power to detect one)." % (s["ba_slope"], cli_ag._pstr(s["ba_slope_p"]))) in sent
    assert "did not depend on plaque size" not in sent
    assert "approximate 95% CI" in sent                          # N11: LoA limits below 10 pairs
    tool, ref = _pairs(30)
    s = cli_ag.full_stats(tool, ref)
    sent = cli_ag.report_sentence(s)
    assert "No proportional bias was detected (Bland-Altman slope %+.3f, %s)." % (
        s["ba_slope"], cli_ag._pstr(s["ba_slope_p"])) in sent
    assert "approximate 95% CI" not in sent and ", 95% CI)" in sent


def test_N8_cli_report_grades_the_interval(tmp_path):
    tool, ref = _pairs(15, noise=0.35)
    csv = tmp_path / "pairs.csv"
    pd.DataFrame({"toolkit_mm": tool, "manual_mm": ref}).to_csv(csv, index=False)
    with contextlib.redirect_stdout(io.StringIO()):
        a = vars(cli_ag.build_args().parse_args([str(csv), "--tool", "toolkit_mm", "--manual",
                                                  "manual_mm", "--out", str(tmp_path / "o")]))
        a["formats"] = ["png"]
        s = cli_ag.run(a)
    rep = [f for f in os.listdir(tmp_path / "o") if f.endswith(".md")][0]
    txt = (tmp_path / "o" / rep).read_text(encoding="utf-8")
    g = cli_ag.icc_grade_interval(s["icc_lo"], s["icc_hi"])
    assert "; %s, graded on the interval) |" % g in txt
    stats_csv = [f for f in os.listdir(tmp_path / "o") if f.startswith("agreement_stats")][0]
    assert pd.read_csv(tmp_path / "o" / stats_csv)["icc_grade_ci"].iloc[0] == g
