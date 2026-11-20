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
        want = ("ICC(A,1) = %.3f (95%% CI %.3f to %.3f): %s agreement, graded on the interval (Koo & Li 2016)"
                % (s["icc"], s["icc_lo"], s["icc_hi"], cli_ag.icc_grade_interval(s["icc_lo"], s["icc_hi"])))
        assert want in sent
        assert "(%s agreement)" % cli_ag.icc_grade(s["icc"]) not in sent


def test_N8_no_grade_without_an_interval_and_no_verdict_below_5_pairs():
    tool, ref = [1.0, 1.52, 2.1, 0.8], [1.02, 1.5, 2.0, 0.9]
    s = cli_ag.full_stats(tool, ref)
    sent = cli_ag.report_sentence(s, "mm", "plaque diameters")
    assert sent.startswith("With only 4 pairs (too few pairs for a verdict), plaque diameters measured with "
                           "Plaque Toolkit were compared with Fiji / ImageJ (n = 4): mean bias ")
    for verdict in ("agreed", "appeared to agree", "did NOT", "did not", "interchangeably", "correlated",
                    "excellent", "good agreement", "poor agreement", "ICC(A,1) =", "Pearson r =", "p ="):
        assert verdict not in sent                       # CT-R3 F7: descriptive numbers only below 5 pairs
    assert "SD of the differences" in sent and "differences from" in sent
    # a poor ICC from 3 pairs: still numbers only
    s3 = cli_ag.full_stats([1.0, 2.0, 1.5], [1.6, 1.2, 1.9])
    assert "cannot be used interchangeably" not in cli_ag.report_sentence(s3)


def test_N8_proportional_bias_clause_and_small_n_power():
    tool, ref = _pairs(8)
    s = cli_ag.full_stats(tool, ref)
    assert s["ba_slope_p"] >= 0.05
    sent = cli_ag.report_sentence(s, "mm", "plaque diameters")
    assert ("There is no evidence of a proportional bias (Bland-Altman slope %+.3f, %s; with 8 pairs "
            "there is little power to detect one)." % (s["ba_slope"], cli_ag._pstr(s["ba_slope_p"]))) in sent
    assert "did not depend on plaque size" not in sent
    assert "approximate 95% CI" in sent                          # N11: LoA limits below 10 pairs
    tool, ref = _pairs(30)
    s = cli_ag.full_stats(tool, ref)
    sent = cli_ag.report_sentence(s)
    assert "There is no evidence of a proportional bias (Bland-Altman slope %+.3f, %s)." % (
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


# =========================================================================== 4. grouped mode options
def _grouped_frame(plates=3, seed=8):
    r = np.random.default_rng(seed)
    rows = []
    for g, base in (("T4", 2.0), ("T7", 2.6)):
        for s, shift in (("ctrl", 0.0), ("hostB", 0.4), ("hostC", -0.1)):
            for p in range(plates):
                m = base + shift + r.normal(0, 0.15)
                for v in r.normal(m, 0.2, 5):
                    rows.append({"group": g, "subgroup": s, "replicate": "p%d" % p, "value": float(v)})
    return pd.DataFrame(rows)


def test_N5_grouped_mode_says_which_options_it_does_not_use(tmp_path):
    res, out = _run(tmp_path, _grouped_frame(), subgroup="subgroup", control="ctrl",
                    equivalence_margin=0.2, equal_var="no", annotate="letters", detect=0.3)
    rep = _report(res)
    for start in ("--equivalence-margin is not used in grouped mode", "--equal-var no is not used in grouped mode",
                  "--annotate letters is not available in grouped mode", "--detect is not used in grouped mode"):
        assert any(n.startswith(start) for n in res["notes"]), start
        assert start in out and start in rep
    # the defaults the apps pass: no note
    res2, out2 = _run(tmp_path / "d", _grouped_frame(), subgroup="subgroup", control="ctrl")
    assert not any("grouped mode" in n for n in res2["notes"]) and "grouped mode" not in out2


# =========================================================================== 5. intervals and labels
def test_N4_grouped_ci_is_labelled_unadjusted_and_csv_has_ci_method(tmp_path):
    res, _ = _run(tmp_path, _grouped_frame(), subgroup="subgroup", control="ctrl")
    comp = res["comparisons"]
    assert set(comp["ci_method"]) == {"Welch t, unadjusted"}
    csv = [f for f in os.listdir(res["out"]) if f.startswith("control_comparisons")][0]
    assert "ci_method" in pd.read_csv(os.path.join(res["out"], csv)).columns
    rep = _report(res)
    assert "difference (95 % CI (unadjusted))" in rep
    assert "a CI that excludes 0 beside a Holm-adjusted 'ns' is not a contradiction" in rep
    resd, _ = _run(tmp_path / "d", _grouped_frame(), subgroup="subgroup", control="ctrl", posthoc="dunnett")
    assert set(resd["comparisons"]["ci_method"]) == {"Dunnett simultaneous"}
    assert "difference (simultaneous 95 % CI)" in _report(resd)


def test_N10_rank_rows_have_no_parametric_ci_or_effect_sizes(tmp_path):
    g = _skewed_c()
    res, _ = _run(tmp_path, _units(g))
    om = res["omni"]
    assert om["test"] == "Kruskal–Wallis" and om["p_method"] == "asymptotic"
    for r in om["pairwise"]:
        assert all(math.isnan(r[k]) for k in ("diff_ci95_lo", "diff_ci95_hi", "cohens_d", "hedges_g"))
        assert r["median_diff"] == pytest.approx(np.median(g[r["group_a"]]) - np.median(g[r["group_b"]]))
    rep = _report(res)
    assert "Kruskal–Wallis (asymptotic p), p" in rep
    assert "Difference and effect sizes are not shown for rank tests" in rep
    assert "difference of medians (A−B)" in rep
    # grouped mode: Mann-Whitney rows too
    rg, _ = _run(tmp_path / "g", _grouped_frame(), subgroup="subgroup", control="ctrl", parametric="nonparametric")
    c = rg["comparisons"]
    assert c["hedges_g"].isna().all() and c["diff_ci95_lo"].isna().all() and (c["ci_method"] == "").all()


def test_N10_mann_whitney_says_exact_or_asymptotic():
    a, b = [1.0, 1.2, 1.4, 1.1], [2.0, 2.2, 2.1, 2.5]          # 4 vs 4, no ties: exact, 2/70
    om = ps.run_stats(_units({"A": a, "B": b}), ["A", "B"], "auto", "nonparametric")[0]
    assert om["p_method"] == "exact"
    assert om["p"] == pytest.approx(st.mannwhitneyu(a, b, method="exact").pvalue) == pytest.approx(2 / 70)
    assert om["effect"] == {} and any(n.startswith("Mann–Whitney U p is exact") for n in om["notes"])
    om = ps.run_stats(_units({"A": a + [1.0], "B": b}), ["A", "B"], "auto", "nonparametric")[0]
    assert om["p_method"] == "asymptotic"                       # a tie


def test_N3_plate_bootstrap_of_the_median_is_approximate_below_10_plates(tmp_path):
    def frame(plates):
        r = np.random.default_rng(1)
        return pd.DataFrame([{"group": g, "replicate": "p%d" % p, "value": float(v)}
                             for g, mu in (("A", 2.0), ("B", 2.5)) for p in range(plates)
                             for v in r.normal(mu + r.normal(0, .1), .3, 6)])
    res, _ = _run(tmp_path, frame(4), center="median", error="ci95")
    fs, rep = res["figure_sentence"], _report(res)
    want = "bootstrap interval of the median (approximate: too narrow with fewer than about 10 plates)"
    assert want in fs and "95 % CI" not in fs
    assert "median (%s) of all plaques" % want in res["paste_sentence"] and "95 % CI" not in res["paste_sentence"]
    assert want in rep
    res10, _ = _run(tmp_path / "ten", frame(10), center="median", error="ci95")
    assert "95 % CI of the median (plates resampled" in res10["figure_sentence"]
    assert "approximate" not in res10["figure_sentence"]
    # no plates: the plaque bootstrap keeps its name (its coverage is 0.93-0.95)
    assert "95 % CI of the median (2,000 bootstrap resamples of the plaques" in ps.figure_sentence(
        {"center": "median", "error": "ci95"}, False, [4, 4])


# =========================================================================== 7. --detect, sensitivity
@pytest.mark.parametrize("detect", [0.05, 0.2, 0.6, 3.0])
def test_detect_plates_needed_matches_statsmodels(tmp_path, detect):
    from statsmodels.stats.power import TTestIndPower
    g = {"A": [2.0, 2.1, 2.25, 2.05], "B": [2.3, 2.2, 2.45, 2.35], "C": [2.6, 2.7, 2.5, 2.65]}
    om = ps.run_stats(_units(g), list("ABC"), "auto", "auto", detect=detect)[0]
    pw = om["power"]
    sd = math.sqrt(np.mean([np.var(v, ddof=1) for v in g.values()]))      # equal n: pooled SD
    assert pw["pooled_sd"] == pytest.approx(sd, rel=1e-12)
    # statsmodels' power of a two-sided two-sample t-test: n is the smallest n with power >= 0.8
    # (solve_power is unreliable for very large effects, so the power function itself is checked)
    tt, d = TTestIndPower(), detect / sd
    n_sm = next(n for n in range(2, 2000) if tt.power(effect_size=d, nobs1=n, alpha=0.05) >= 0.8)
    assert pw["n_for_detect"] == max(3, n_sm)
    s = ps.power_sentence(pw, "replicate")
    assert s.startswith("**Power:** to detect a difference of %.3g (the difference you named) with 80 %% "
                        "power" % detect)
    assert "you need %s per sample (you have 4)." % ps._plural(max(3, n_sm), "plate") in s
    assert "Detecting the largest" not in s and "the largest observed difference" in s


def test_detect_from_the_cli_and_bad_values(tmp_path):
    a = ps.build_args().parse_args(["x.csv", "--detect", "0.2"])
    assert a.detect == 0.2
    g = {"A": [2.0, 2.1, 2.25], "B": [2.3, 2.2, 2.45], "C": [2.6, 2.7, 2.5]}
    res, _ = _run(tmp_path, _units(g), detect=0.2)
    rep = _report(res)
    design = rep.split("## Design and power")[1]
    assert design.lstrip().startswith("- **Power:** to detect a difference of 0.2 (the difference you named)")
    for bad in (0, -1, "abc"):
        with pytest.raises(ps.StatsError):
            ps.run_stats(_units(g), list("ABC"), "auto", "auto", detect=bad)


def test_sensitivity_line_equal_vs_unequal_variances(tmp_path):
    g = {"A": [2.0, 2.1, 2.2, 2.05], "B": [2.3, 2.9, 1.9, 2.6], "C": [2.6, 2.7, 2.65, 2.62]}
    res, _ = _run(tmp_path, _units(g))
    sens = res["omni"]["sensitivity"]
    gv = [np.asarray(v) for v in g.values()]
    assert sens["p_equal"] == pytest.approx(st.f_oneway(*gv).pvalue, rel=1e-12)
    assert sens["p_welch"] == pytest.approx(ps.welch_anova_p(gv), rel=1e-12)
    t = st.tukey_hsd(*gv).pvalue
    gh = ps.games_howell(g)
    labels = list(g)
    want = []
    for i, j in itertools.combinations(range(3), 2):
        a, b = labels[i], labels[j]
        if (t[i, j] < 0.05) and not (gh[(a, b)] < 0.05):
            want.append("%s vs %s is significant only with equal variances assumed (Tukey HSD)" % (a, b))
        if (gh[(a, b)] < 0.05) and not (t[i, j] < 0.05):
            want.append("%s vs %s is significant only without that assumption (Games-Howell)" % (a, b))
    for w in want:
        assert w in sens["text"]
    if not want and (sens["p_equal"] < 0.05) == (sens["p_welch"] < 0.05):
        assert sens["text"].endswith("conclusions are the same under both (Tukey HSD and Games-Howell, "
                                     "adjusted p < 0.05).")
    assert "- **Sensitivity:** omnibus p" in _report(res)
    # not on the rank path, not with 2 samples
    assert ps.run_stats(_units(g), list("ABC"), "auto", "nonparametric")[0]["sensitivity"] is None
    assert ps.run_stats(_units({"A": g["A"], "B": g["B"]}), ["A", "B"], "auto", "auto")[0]["sensitivity"] is None


def test_sensitivity_line_names_a_pair_that_differs():
    # seeded search for 3 x 4 plates where Tukey and Games-Howell disagree on a pair
    r = np.random.default_rng(0)
    for _ in range(5000):
        g = {"A": r.normal(2.0, 0.05, 4), "B": r.normal(2.3, 0.6, 4), "C": r.normal(2.25, 0.05, 4)}
        t = st.tukey_hsd(*g.values()).pvalue
        gh = ps.games_howell(g)
        if (t[0, 2] < 0.05) != (gh[("A", "C")] < 0.05):
            break
    else:
        pytest.fail("no disagreeing case found")
    om = ps.run_stats(_units(g), list("ABC"), "auto", "parametric")[0]
    only = "equal variances assumed (Tukey HSD)" if t[0, 2] < 0.05 else "without that assumption (Games-Howell)"
    assert "A vs C is significant only %s" % (("with " + only) if t[0, 2] < 0.05 else only) in om["sensitivity"]["text"]
    assert "conclusions are the same" not in om["sensitivity"]["text"]


# =========================================================================== 8. figures (desktop tester)
def _fig_args(**kw):
    o = dict(ps.DEFAULTS)
    o.update(kw)
    return o


def test_g8a_caption_fits_the_final_width_and_final_size_is_exposed(tmp_path):
    r = np.random.default_rng(1)
    names = ["Escherichia phage T%d with a long name" % i for i in range(12)]
    df = pd.DataFrame([{"group": g, "replicate": "p%d" % p, "value": float(v)}
                       for g in names for p in range(3) for v in r.normal(2, .3, 5)])
    res, _ = _run(tmp_path, df, violin_fill="group", width=6.0, height=5.4, dpi=60)
    w, h = res["figure_size_in_final"]
    assert h > 5.4 + 0.5                                  # the key went below: the figure grew
    from PIL import Image
    im = Image.open(os.path.join(res["out"], "violin_value.png"))
    assert im.size[0] / 60 == pytest.approx(w, abs=0.1) and im.size[1] / 60 == pytest.approx(h, abs=0.1)
    assert w <= 6.0 + 0.25                                # nothing (caption) runs past the width
    import json
    cfg = json.load(open(os.path.join(res["out"], "run_config_value.json")))
    assert cfg["figure_size_in_final"] == pytest.approx([w, h])
    fig = ps.plot_violin(ps.normalize(df, "group", "value", "replicate", "metric")[0], names,
                         _fig_args(violin_fill="group", width=6.0, height=5.4), "value", {})
    cap = [t for t in fig.texts if t.get_position() == (0.012, 0.008)]
    rend = fig.canvas.get_renderer()
    assert cap and cap[0].get_window_extent(rend).x1 <= fig.bbox.width + 0.5
    import matplotlib.pyplot as plt
    plt.close(fig)


def test_g8b_a_key_taller_than_the_axes_goes_below(tmp_path):
    r = np.random.default_rng(1)
    df = pd.DataFrame([{"group": g, "replicate": "plate%02d" % p, "value": float(v)}
                       for g in "ABC" for p in range(15) for v in r.normal(2, .3, 4)])
    fig = ps.plot_violin(df, list("ABC"), _fig_args(width=8.4, height=3.6), "value", {})
    assert fig.key_placement == "below" and fig.get_size_inches()[1] > 3.6
    ah = ps._axes_in(fig, fig.axes[0])[1]
    assert ah > 2.0                                        # the plot area is not squeezed
    import matplotlib.pyplot as plt
    plt.close(fig)
    # the saved file keeps the key even without a caption line under it
    res, _ = _run(tmp_path, df, width=8.4, height=3.6, dpi=60)
    assert res["figure_size_in_final"][1] > 3.6 + 0.4
    # a short key still sits at the right
    fig = ps.plot_violin(df[df["replicate"] <= "plate02"], list("ABC"), _fig_args(), "value", {})
    assert fig.key_placement == "right"
    plt.close(fig)


def test_g8c_log_axis_marks_come_from_the_drawn_values(tmp_path):
    rows = [("A", "p1", 0.0), ("A", "p1", 1.2), ("A", "p2", 1.0), ("A", "p2", 1.4), ("A", "p3", 0.9),
            ("A", "p3", 1.1), ("B", "p1", 2.0), ("B", "p1", 2.4), ("B", "p2", 2.2), ("B", "p2", 2.6),
            ("B", "p3", 2.1), ("B", "p3", 2.3)]
    df = pd.DataFrame(rows, columns=["group", "replicate", "value"])
    o = _fig_args(log_y=True, log_y_drop_nonpositive=True)
    fig = ps.plot_violin(df, ["A", "B"], o, "value", {})
    ax = fig.axes[0]
    big = [c for c in ax.collections if c.get_sizes().size and c.get_sizes()[0] > 50]   # plate means
    ys = np.concatenate([c.get_offsets()[:, 1] for c in big])
    drawn = {1.2, 1.2, 1.2, 2.2, 2.4, 2.2}
    assert 0.6 not in np.round(ys, 6)                                  # not the mean of {0, 1.2}
    assert sorted(np.round(ys, 6)) == sorted([1.2, 1.2, 1.0, 2.2, 2.4, 2.2])
    lo, hi = ax.get_ylim()
    assert lo <= min(ys) and lo <= 0.9 and hi >= max(ys)
    bar_a = [l for l in ax.lines if len(l.get_xdata()) == 2 and l.get_ydata()[0] == l.get_ydata()[1]
             and abs(np.mean(l.get_xdata()) - 1) < 0.01]
    assert bar_a and bar_a[0].get_ydata()[0] == pytest.approx(np.mean([1.2, 1.2, 1.0]))
    import matplotlib.pyplot as plt
    plt.close(fig)
    res, _ = _run(tmp_path, df, log_y=True, log_y_drop_nonpositive=True)
    note = "1 value ≤ 0 is not shown on the log axis: the plotted plate means, bar and whisker leave it out, the statistics include it."
    assert note in res["notes"] and note in _report(res)


def test_g8d_no_global_matplotlib_settings_leak(tmp_path):
    import importlib
    import matplotlib
    matplotlib.rcdefaults()
    before = dict(matplotlib.rcParams)
    importlib.reload(ps)
    importlib.reload(cli_ag)
    g = {"A": [2.0, 2.1, 2.2], "B": [2.5, 2.6, 2.4], "C": [3.0, 3.1, 2.9]}
    with contextlib.redirect_stdout(io.StringIO()):
        ps.run(_args(tmp_path, _units(g), formats=["png", "svg", "pdf", "tiff"], stats_table=True,
                     legend_key=True))
    after = dict(matplotlib.rcParams)
    changed = {k: (before[k], after[k]) for k in before if before[k] != after[k]}
    assert changed == {}


def test_g8e_grey_words_unique_and_close_palette_note(tmp_path):
    r = np.random.default_rng(1)
    df = pd.DataFrame([{"group": "S%d" % i, "replicate": "p%d" % p, "value": float(v)}
                       for i in range(12) for p in range(3) for v in r.normal(2, .3, 4)])
    res, _ = _run(tmp_path, df, palette=list(ps.PALETTES["grays"]), violin_fill="group", legend_key=True)
    import legend_key as lk
    fig = ps.plot_violin(ps.normalize(df, "group", "value", "replicate", "metric")[0], res["order"],
                         _fig_args(palette=list(ps.PALETTES["grays"]), violin_fill="group"), "value", {})
    key = lk.from_figure(fig)
    import matplotlib.pyplot as plt
    plt.close(fig)
    words = lk._colour_words(key["entries"])
    seen = {}
    for e, w in zip(key["entries"], words):
        sig = (e.get("colour"), e.get("hatch"), e.get("marker"))
        seen.setdefault(w + "|" + str(e.get("hatch")) + "|" + str(e.get("marker")), set()).add(sig)
    assert all(len(v) == 1 for v in seen.values())           # one word+hatch+marker = one look
    grey = [w for w in words if w.startswith("grey ")]
    assert "grey 1 of 8 (darkest)" in grey and "grey 8 of 8 (lightest)" in grey
    assert len({w for e, w in zip(key["entries"], words) if not e.get("hatch") and w in grey}) == 8
    note = [n for n in res["notes"] if n.startswith("The grays palette's colours are hard to tell apart")]
    assert note and "below 10" in note[0] and note[0] in _report(res)
    # okabe with 5 samples: no note
    assert ps.palette_close_note(list("ABCDE"), {"palette": ps.OKABE_ITO}) is None


# =========================================================================== 9. R / Python agreement
def test_g9_rank_tests_count_ties_like_R():
    # plate means equal on paper but not in floating point: mean(0.1, 0.2, 0.3) is
    # 0.19999999999999998 and mean(0.2, 0.2, 0.2) is 0.20000000000000004 (both 0.2)
    rows = []
    plates = {"A": [[0.1, 0.2, 0.3], [0.05, 0.1, 0.15], [0.12, 0.14, 0.16]],
              "B": [[0.25, 0.3, 0.35], [0.2, 0.2, 0.2], [0.3, 0.35, 0.4]],
              "C": [[0.5, 0.6, 0.7], [0.45, 0.5, 0.55], [0.6, 0.65, 0.7]]}
    for g, pl in plates.items():
        for i, vals in enumerate(pl):
            rows += [{"group": g, "replicate": "%s%d" % (g, i), "value": v} for v in vals]
    df = pd.DataFrame(rows)
    rm = ps.replicate_means(df)
    a0 = rm[(rm["group"] == "A") & (rm["replicate"] == "A0")]["value"].iloc[0]
    b1 = rm[(rm["group"] == "B") & (rm["replicate"] == "B1")]["value"].iloc[0]
    assert a0 != b1 and round(a0, 12) == round(b1, 12) == 0.2      # the trap is armed
    typed = {g: [round(float(np.mean(v)), 10) for v in pl] for g, pl in plates.items()}
    om = ps.run_stats(df, list("ABC"), "auto", "nonparametric")[0]
    om_t = ps.run_stats(_units(typed), list("ABC"), "auto", "nonparametric")[0]
    assert om["p"] == pytest.approx(om_t["p"], rel=1e-12)
    assert om["p"] == pytest.approx(st.kruskal(*typed.values()).pvalue, rel=1e-12)
    assert [r["p_adj"] for r in om["pairwise"]] == pytest.approx([r["p_adj"] for r in om_t["pairwise"]])
    om2 = ps.run_stats(df[df["group"] != "C"], ["A", "B"], "auto", "nonparametric")[0]
    assert om2["p"] == pytest.approx(st.mannwhitneyu(typed["A"], typed["B"]).pvalue, rel=1e-12)
    assert om2["p_method"] == "asymptotic"                     # the tie is seen


def test_g9_untestable_comparison_with_the_reference_is_na_not_ns():
    groups = {"S%d" % i: [2.0 + 0.01 * i, 2.1, 2.05] for i in range(6)}
    groups["S6"] = [2.3]                                          # one plate: cannot be tested
    om, post, _u, _h = ps.run_stats(_units(groups), list(groups), "auto", "auto")
    plan = ps.annotation_plan(list(groups), post, {"annotate": "auto"})
    assert plan["mode"] == "vsref" and plan["letters"]["S6"] == "n/a"
    assert "n/a = could not be tested, fewer than 2 plates" in plan["note"]


@pytest.mark.parametrize("token", ["NA", "nan", "n/a", "-"])
def test_g9_text_in_a_value_cell_is_not_a_number(tmp_path, token):
    p = tmp_path / "v.csv"
    p.write_text("group,replicate,value\nA,p1,1.0\nA,p2,%s\nA,p3,1.2\nB,p1,2.0\nB,p2,\nB,p3,2.2\nB,p4,2.1\n" % token,
                 encoding="utf-8")
    res, _ = _run(tmp_path, str(p))
    assert "2 rows dropped: no numeric value (1 not a number, 1 empty)." in res["notes"]


# =========================================================================== 8 (web tester): f, g, h
def test_g8f_agreement_report_names_the_toolkit_version(tmp_path):
    ns = {}
    exec(open(os.path.join(ROOT, "_version.py"), encoding="utf-8").read(), ns)
    want = "Plaque Toolkit %s (agreement.py)" % ns["__version__"]
    assert cli_ag.version_label() == want == app_ag.version_label()
    tool, ref = _pairs(12)
    csv = tmp_path / "pairs.csv"
    pd.DataFrame({"toolkit_mm": tool, "manual_mm": ref}).to_csv(csv, index=False)
    a = vars(cli_ag.build_args().parse_args([str(csv), "--tool", "toolkit_mm", "--manual", "manual_mm",
                                             "--out", str(tmp_path / "o")]))
    a["formats"] = ["png"]
    with contextlib.redirect_stdout(io.StringIO()):
        cli_ag.run(a)
    rep = [f for f in os.listdir(tmp_path / "o") if f.endswith(".md")][0]
    assert "| %s_" % want in (tmp_path / "o" / rep).read_text(encoding="utf-8")
    import json
    cfg = [f for f in os.listdir(tmp_path / "o") if f.startswith("run_config")][0]
    assert json.load(open(tmp_path / "o" / cfg))["version"] == want


@pytest.mark.parametrize("content", [b"PK\x03\x04\x14\x00\x00\x00fake xlsx", b"\xd0\xcf\x11\xe0\xa1\xb1old xls",
                                     b"a,b\n1\x002\n", b"a\n1\n2,3,4\n5,6\n"])
def test_g8g_a_non_table_with_a_csv_name_is_a_plain_error(tmp_path, content):
    p = tmp_path / "data.csv"
    p.write_bytes(content)
    with pytest.raises(ps.StatsError) as e:
        ps.read_table(str(p))
    assert ("data.csv does not look like a CSV table (is it an Excel or binary file saved with a .csv "
            "name?)") in str(e.value)
    assert "tokenizing" not in str(e.value)


def test_g8g_no_doubled_word_in_the_dropped_rows_note():
    df = pd.DataFrame({"group": ["A", "A", "B", "B"], "replicate": ["p1", "p2", "p1", "p2"],
                       "value": ["1.0", "x", "2.0", "2.1"]})
    out, _ = ps.normalize(df, "group", None, "replicate", "metric")
    assert ps.data_notes(out) == ["1 row dropped: no numeric value (1 not a number, 0 empty)."]


def _long_names_frame():
    r = np.random.default_rng(3)
    names = ["MG1655 + phage variant %02d (long name for test)" % i for i in range(1, 13)]
    df = pd.DataFrame([{"group": g, "replicate": "plate%d" % p, "value": float(v)}
                       for k, g in enumerate(names) for p in range(1, 4) for v in r.normal(1.5 + .08 * k, .3, 8)])
    return df, names


def test_g8h_long_tick_labels_leave_the_axes_45_percent_and_use_the_key(tmp_path):
    import matplotlib.pyplot as plt
    df, names = _long_names_frame()
    o = ps._plot_opts(dict(violin_fill="group", palette=list(ps.PALETTES["tab10"])))
    fig = ps.plot_violin(df, names, o, "value", {})
    W, H = fig.get_size_inches()
    ax = fig.axes[0]
    assert ps._axes_in(fig, ax)[1] >= 0.45 * H - 0.01
    ticks = [t.get_text() for t in ax.get_xticklabels()]
    assert all(len(t) <= ps.TICK_SHORT_MAX for t in ticks) and len(set(ticks)) == 12
    assert any("01" in t for t in ticks) and all("…" in t for t in ticks)
    assert ax.get_position().x0 * W < 2.0                         # no blank left third
    cap = [t.get_text() for t in fig.texts if t.get_position() == (0.012, 0.008)]
    assert cap and "Full sample names are in the key" in cap[0].replace("\n", " ")
    from legend_key import from_figure
    assert [e["label"] for e in from_figure(fig)["entries"][:12]] == names     # the key keeps them
    plt.close(fig)
    # grey violins, no key on the figure: the names stay complete (wrapped), axes still >= 45 %
    fig = ps.plot_violin(df, names, ps._plot_opts(dict(legend=False)), "value", {})
    W, H = fig.get_size_inches()
    ticks = [t.get_text().replace("\n", " ") for t in fig.axes[0].get_xticklabels()]
    assert ticks == names
    assert ps._axes_in(fig, fig.axes[0])[1] >= 0.45 * H - 0.01
    plt.close(fig)


def test_g8h_short_labels_stay_distinct():
    n = ["MG1655 + phage variant %02d (long name for test)" % i for i in range(1, 4)] + ["WT"]
    s = ps.short_labels(n)
    assert s[-1] == "WT" and len(set(s)) == 4 and all(len(x) <= ps.TICK_SHORT_MAX for x in s)
    name = "Escherichia coli K-12 MG1655 plus T4"
    assert ps.short_labels([name, "B"]) == [name[:10] + "…" + name[-11:], "B"]   # ellipsis in the middle
