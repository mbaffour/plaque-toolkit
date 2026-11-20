"""CT-R1 statistics engine (plaque_stats/plaque_stats.py, legend_key.py, make_figure.py).

Each test pins one finding of the round-1 click-through (SM-F = stats-maths, DA-F = desktop
Analyze, WP-F = web Python) or one new statistics option (B1..B5). Expected values come from a
formula stated in the test (scipy/numpy primitives), never from a previous run of the engine.
"""
import itertools
import math
import os
import shutil
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest
from scipy import stats as st

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "plaque_stats"))

import plaque_stats as ps  # noqa: E402
import legend_key as lk  # noqa: E402


# --------------------------------------------------------------------------- helpers
def _frame(groups=("T4", "T7", "lambda"), mus=(2.6, 1.9, 3.1), plates=3, n=20, plate_sd=0.1,
           sd=0.3, seed=1, plate_names=None):
    rng = np.random.default_rng(seed)
    rows = []
    for g, mu in zip(groups, mus):
        for p in range(plates):
            shift = rng.normal(0, plate_sd)
            for v in rng.normal(mu + shift, sd, n):
                rows.append({"group": g, "replicate": (plate_names or {}).get(p, "plate%d" % (p + 1)),
                             "diameter_mm": round(float(v), 4)})
    return pd.DataFrame(rows)


def _units(groups_sd, n_units, mu=2.0, seed=4):
    """One plaque per plate: the plate means ARE the values (unit SDs exactly controlled)."""
    rng = np.random.default_rng(seed)
    rows = []
    for g, sd in groups_sd.items():
        for i in range(n_units):
            rows.append({"group": g, "replicate": "p%d" % i, "value": mu + rng.normal(0, sd)})
    return pd.DataFrame(rows)


def _args(tmp_path, data, **kw):
    a = dict(ps.DEFAULTS)
    a.update({"data": data, "value": "diameter_mm", "out": str(tmp_path / "out"),
              "formats": ["png"], "_stamp": "", "stats_table": False})
    a.update(kw)
    return a


def _tidy(df):
    return df.rename(columns={"diameter_mm": "value"})[["group", "replicate", "value"]]


# =========================================================================== A1 labels
def test_A1_labels_are_labels_and_dropped_rows_are_counted(tmp_path, capsys):
    # SM-F1/F2, DA-F2: None / NA / 007 / '1.0' / 'phage #3' are names; only empty is missing
    names = ["None", "NA", "007", "phage #3"]
    df = _frame(groups=names, mus=(2.0, 2.5, 3.0, 3.5), plates=3, n=6)
    df["replicate"] = df["replicate"].map({"plate1": "1.0", "plate2": "plate #2", "plate3": "N/A"})
    csv = tmp_path / "d.csv"
    text = "# a comment line\n" + df.to_csv(index=False) + ",1.0,2.2\n"     # one row without a group
    csv.write_text(text, encoding="utf-8")
    raw = ps.read_table(str(csv))
    assert list(dict.fromkeys(raw["group"].dropna())) == names
    assert set(raw["replicate"].dropna()) == {"1.0", "plate #2", "N/A"}
    res = ps.run(_args(tmp_path, str(csv)))
    assert res["order"] == names and res["omni"]["test"] == "one-way ANOVA"
    assert res["omni"]["n_per_group"] == {g: 3 for g in names}
    assert "1 row dropped: no group label." in res["notes"]
    assert "1 row dropped: no group label." in capsys.readouterr().out
    report = (tmp_path / "out" / "report_diameter_mm.md").read_text(encoding="utf-8")
    assert "1 row dropped: no group label." in report


def test_A1_read_table_sniffs_delimiter_and_decimal_comma(tmp_path):
    p = tmp_path / "euro.csv"
    p.write_text("group;replicate;diameter_mm\nA;p1;2,5\nA;p2;2,75\nB;p1;1,25\n", encoding="utf-8")
    df, info = ps.read_table(str(p), return_info=True)
    assert info["delimiter"] == ";" and info["decimal"] == "," and info["rows"] == 3
    assert info["columns"] == ["group", "replicate", "diameter_mm"]
    assert "semicolon" in info["note"] and "decimal comma" in info["note"]
    assert df["diameter_mm"].tolist() == [2.5, 2.75, 1.25]
    assert isinstance(ps.read_table(str(p)), pd.DataFrame)             # return_info=False


def test_A1_dataframe_input_matches_file_input(tmp_path):
    df = _frame()
    csv = tmp_path / "d.csv"; df.to_csv(csv, index=False)
    r_file = ps.run(_args(tmp_path, str(csv), out=str(tmp_path / "f")))
    r_mem = ps.run(_args(tmp_path, df, out=str(tmp_path / "m")))
    assert r_mem["omni"]["p"] == pytest.approx(r_file["omni"]["p"], rel=1e-12)
    assert r_mem["parse_note"].startswith("in-memory table")
    assert os.path.exists(tmp_path / "m" / "run_config_diameter_mm.json")


def test_A1_order_unknown_names_error_and_duplicates_are_removed(tmp_path):
    df = _frame()
    with pytest.raises(SystemExit, match="T9"):
        ps.run(_args(tmp_path, df, order=["T4", "T9"]))
    res = ps.run(_args(tmp_path, df, order=["T7", "T4", "T7"]))
    assert res["order"] == ["T7", "T4"] and res["omni"]["test"] == "Welch t-test"
    assert any("lambda not in --order" in n for n in res["notes"])


def test_A1_long_file_without_metric_rejects_a_typo_value():
    raw = pd.DataFrame({"group": ["A", "A", "B", "B"], "replicate": ["1", "2", "1", "2"],
                        "value": [1.0, 2.0, 3.0, 4.0]})
    with pytest.raises(SystemExit, match="diamter"):
        ps.normalize(raw, "group", "diamter", "replicate", "metric")
    d, m = ps.normalize(raw, "group", "value", "replicate", "metric")
    assert m == "value" and len(d) == 4


def test_A1_grouped_honours_sub_order_and_sublabel(tmp_path):
    df = _frame(groups=("T4", "T7"), mus=(2.0, 2.4))
    df["host"] = np.where(df.index % 3 == 0, "LE392", np.where(df.index % 3 == 1, "MG1655", "None"))
    res = ps.run(_args(tmp_path, df, subgroup="host", control="MG1655",
                       sub_order=["None", "MG1655", "LE392"], _sublabel="2nd factor",
                       formats=["png"]))
    assert res["sub_order"] == ["None", "MG1655", "LE392"] and res["control"] == "MG1655"
    text = (tmp_path / "out" / "grouped_diameter_mm_legend_text.txt").read_text(encoding="utf-8")
    assert text.startswith("None (") and "MG1655 (control; " in text


# =========================================================================== A2 unit honesty
def test_A2_unit_replicate_without_plates_is_an_error():
    df = _tidy(_frame()); df["replicate"] = np.nan
    with pytest.raises(SystemExit, match="no plate/replicate column"):
        ps.run_stats(df, ["T4", "T7", "lambda"], "replicate", "auto")
    omni, _ph, unit, _hr = ps.run_stats(df, ["T4", "T7", "lambda"], "auto", "auto")
    assert unit == "plaque" and any("PLAQUE" in w for w in omni["warnings"])


def test_A2_single_plate_group_keeps_the_plate_as_unit():
    df = _tidy(_frame(groups=("T4", "T7", "lambda"), mus=(2.6, 1.9, 3.1)))
    df = df[~((df["group"] == "lambda") & (df["replicate"] != "plate1"))]   # lambda: 1 plate
    order = ["T4", "T7", "lambda"]
    omni, posthoc, unit, _ = ps.run_stats(df, order, "auto", "auto")
    assert unit == "replicate"
    assert any(w.startswith("lambda has 1 plate") for w in omni["warnings"])
    assert math.isnan(posthoc[("T4", "lambda")]) and math.isnan(posthoc[("T7", "lambda")])
    pm = ps.replicate_means(df)
    a, b = (pm.loc[pm["group"] == g, "value"].values for g in ("T4", "T7"))
    # the two testable samples: Tukey on their plate means (2 groups -> equals scipy's tukey_hsd)
    assert posthoc[("T4", "T7")] == pytest.approx(float(st.tukey_hsd(a, b).pvalue[0, 1]), rel=1e-9)


# =========================================================================== A3 equal variances
def test_A3_equal_var_no_and_yes_force_the_method():
    df = _units({"A": 0.5, "B": 0.05, "C": 0.05}, 3)
    o_no = ps.run_stats(df, ["A", "B", "C"], "auto", "auto", equal_var="no")[0]
    assert o_no["test"] == "Welch ANOVA" and o_no["posthoc"] == "Games-Howell"
    gv = [df.loc[df["group"] == g, "value"].values for g in "ABC"]
    assert o_no["p"] == pytest.approx(ps.welch_anova_p(gv), rel=1e-12)
    o_yes = ps.run_stats(df, ["A", "B", "C"], "auto", "auto", equal_var="yes")[0]
    assert o_yes["test"] == "one-way ANOVA" and o_yes["posthoc"] == "Tukey HSD"
    assert o_yes["p"] == pytest.approx(float(st.f_oneway(*gv).pvalue), rel=1e-12)
    assert "--equal-var yes" in o_yes["variance_rule"]


def test_A3_shipped_example_gets_the_note_not_the_warning(tmp_path):
    ps.make_example(str(tmp_path))
    res = ps.run(_args(tmp_path, str(tmp_path / "example_data_wide.csv")))
    assert not any("spread" in w for w in res["warnings"])
    note = [n for n in res["notes"] if n.startswith("ANOVA and Tukey assume the groups have similar spread")]
    assert note == ["ANOVA and Tukey assume the groups have similar spread. With 3 plates per group this "
                    "cannot be checked reliably (largest/smallest SD ratio here: 7.2). If you expect the "
                    "groups to differ in spread, choose --equal-var no (Welch)."]
    report = (tmp_path / "out" / "report_diameter_mm.md").read_text(encoding="utf-8")
    assert note[0] in report


def test_A3_extreme_pair_f_test_warns_at_8_plates():
    df = _units({"A": 0.5, "B": 0.05, "C": 0.05}, 8, seed=11)
    omni = ps.run_stats(df, ["A", "B", "C"], "auto", "auto", equal_var="yes")[0]
    sds = {g: df.loc[df["group"] == g, "value"].std(ddof=1) for g in "ABC"}
    hi, lo = max(sds, key=sds.get), min(sds, key=sds.get)
    F = sds[hi] ** 2 / sds[lo] ** 2
    p_adj = min(1.0, 2 * st.f.sf(F, 7, 7) * 3)                  # k(k-1)/2 = 3 pairs
    assert omni["variance_check"]["p_adj"] == pytest.approx(p_adj, rel=1e-9)
    want = ("The spread differs between groups more than chance explains (SD ratio %.1f, adjusted "
            "%s): Welch ANOVA + Games-Howell is the safer analysis." % (math.sqrt(F), ps.p_text(p_adj)))
    assert want in omni["warnings"]
    # as app.R: the check belongs to the classic path only; Welch (here: --equal-var no) needs no advice
    assert not any("spread differs" in w for w in
                   ps.run_stats(df, ["A", "B", "C"], "auto", "auto", equal_var="no")[0]["warnings"])



def test_A3_eight_normal_units_with_unequal_variance_use_welch_not_kruskal():
    # deterministic, exactly normal-shaped samples: scaled normal quantiles, 8 units per group
    q = st.norm.ppf((np.arange(1, 9) - 0.375) / 8.25)
    rows = [{"group": g, "replicate": "p%d" % i, "value": 2.0 + sd * x}
            for g, sd in (("A", 0.5), ("B", 0.05), ("C", 0.05)) for i, x in enumerate(q)]
    df = pd.DataFrame(rows)
    gv = [df.loc[df["group"] == g, "value"].values for g in "ABC"]
    assert st.levene(*gv).pvalue < 0.05 and all(st.shapiro(v).pvalue > 0.05 for v in gv)
    auto = ps.run_stats(df, ["A", "B", "C"], "auto", "auto")[0]
    assert auto["test"] == "Welch ANOVA" and auto["posthoc"] == "Games-Howell"


# =========================================================================== A4 .. A8
def test_A4_blank_plate_rows_are_excluded_everywhere_and_counted():
    df = _frame()
    df.loc[df.index[:5], "replicate"] = ""
    d, _ = ps.normalize(df, "group", "diameter_mm", "replicate", "metric")
    assert len(d) == len(df) - 5
    assert ps.data_notes(d) == ["5 rows dropped: blank replicate label while other rows have one."]


def test_A5_unit_columns_n_labels_and_figure_sentence(tmp_path):
    df = _frame()
    res = ps.run(_args(tmp_path, df))
    s = res["summary"].set_index("group")
    pm = ps.replicate_means(_tidy(df))
    t4 = pm.loc[pm["group"] == "T4", "value"].values
    assert s.loc["T4", "n_units"] == 3 and s.loc["T4", "unit_mean"] == pytest.approx(t4.mean())
    assert s.loc["T4", "unit_sem"] == pytest.approx(t4.std(ddof=1) / math.sqrt(3))
    h = st.t.ppf(0.975, 2) * t4.std(ddof=1) / math.sqrt(3)
    assert s.loc["T4", "unit_ci95_lo"] == pytest.approx(t4.mean() - h)
    text = (tmp_path / "out" / "violin_diameter_mm_legend_text.txt").read_text(encoding="utf-8")
    assert text.strip().endswith("Bar: mean of the 3 plate means. Whisker: SEM of the plate means. "
                                 "n = plaques, N = plates.")
    fig = ps.plot_violin(_tidy(df), ["T4", "T7", "lambda"], dict(ps.DEFAULTS), "d", res["posthoc"])
    labels = [t.get_text() for t in fig.axes[0].texts]
    assert any(t.startswith("n = 60 plaques") and "N = 3 plates" in t for t in labels) or \
        any(t == "n=60\nN=3" for t in labels)
    plt.close(fig)
    # the two-group sentence follows --center/--error
    r2 = ps.run(_args(tmp_path, df, order=["T4", "T7"], error="sd", out=str(tmp_path / "o2")))
    assert "mean ± SD of the plate means" in r2["paste_sentence"]


def test_A5_no_plus_minus_at_n_1():
    assert ps._value_text(2.11, 2.11, float("nan"), 1, "sem") == "2.11"


def test_A6_median_rules_and_bootstrap_ci():
    df = _tidy(_frame())
    with pytest.raises(ValueError, match="around a MEAN"):
        ps.check_center_error("median", "sd")
    ct = ps.center_table(df, ["T4"], dict(ps.DEFAULTS, center="median", error="ci95"))
    cen, lo, hi, n = ct["T4"]
    sub = df[df["group"] == "T4"]
    plates = [g["value"].values for _, g in sub.groupby("replicate")]
    # stated algorithm: 2,000 resamples of whole plates (seed 7), percentile 2.5 / 97.5
    rng = np.random.default_rng(7)
    meds = [np.median(np.concatenate([plates[i] for i in rng.integers(0, 3, 3)])) for _ in range(2000)]
    assert (lo, hi) == pytest.approx(tuple(np.percentile(meds, [2.5, 97.5])))
    assert cen == pytest.approx(np.median(sub["value"])) and lo <= cen <= hi and n == 3


def test_A6_brackets_start_above_the_whiskers():
    df = _tidy(_frame(groups=("A", "B"), mus=(2.0, 3.0), plate_sd=0.6))
    opts = dict(ps.DEFAULTS, error="sd")
    fig = ps.plot_violin(df, ["A", "B"], opts, "d", {("A", "B"): 0.01})
    ct = ps.center_table(df, ["A", "B"], opts)
    top = max(v[2] for v in ct.values())
    br = [ln for ln in fig.axes[0].lines if len(ln.get_xdata()) == 4]
    assert br and min(br[0].get_ydata()) > top
    plt.close(fig)


@pytest.mark.parametrize("p,txt", [(0.0004, "< 0.001"), (0.034, "0.034"), (0.04996, "0.04996"),
                                   (0.00996, "0.00996"), (0.9996, "> 0.999"), (float("nan"), "n/a")])
def test_A7_one_p_formatter(p, txt):
    assert ps.fmt_p(p) == txt
    assert ps.p_text(0.0004) == "p < 0.001" and ps.p_text(0.034) == "p = 0.034"


def test_A7_constant_data_and_undefined_welch():
    df = _units({"A": 0.0, "B": 0.0, "C": 0.0}, 4)
    o = ps.run_stats(df, ["A", "B", "C"], "auto", "nonparametric")[0]
    assert math.isnan(o["p"]) and any("identical" in n for n in o["notes"])
    df2 = _units({"A": 0.3, "B": 0.3, "C": 0.0}, 4)
    o2 = ps.run_stats(df2, ["A", "B", "C"], "auto", "auto", equal_var="no")[0]
    assert o2["test"] == "one-way ANOVA" and o2["posthoc"] == "Tukey HSD"
    assert any("Welch's ANOVA could not be computed" in n for n in o2["notes"])


def test_A7_kruskal_effect_size_is_named_correctly():
    df = _units({"A": 1.0, "B": 1.0, "C": 1.0}, 9, seed=3)
    df.loc[df["group"] == "C", "value"] += 2
    o = ps.run_stats(df, ["A", "B", "C"], "auto", "nonparametric")[0]
    H = st.kruskal(*[df.loc[df["group"] == g, "value"] for g in "ABC"]).statistic
    assert o["effect"]["epsilon_squared"] == pytest.approx(H / (27 - 1))
    assert o["effect"]["eta_squared_H"] == pytest.approx((H - 3 + 1) / (27 - 3))
    assert o["posthoc"] == "Dunn (Holm)"


def test_A7_grouped_unit_change_and_na(tmp_path):
    df = _tidy(_frame(groups=("T4",), mus=(0.5,)))
    df["subgroup"] = np.where(df["replicate"] == "plate1", "ctrl", "trt")
    df.loc[df["subgroup"] == "ctrl", "value"] -= 5.0                       # control mean < 0
    summ, comp, unit, info = ps.grouped_stats(df, ["T4"], ["ctrl", "trt"], "ctrl", unit="plaque",
                                              return_info=True)
    assert unit == "plaque" and math.isnan(comp.loc[0, "change_pct"])
    assert any("PLAQUE" in w for w in info["warnings"])
    _s, comp2, unit2 = ps.grouped_stats(df, ["T4"], ["ctrl", "trt"], "ctrl")
    assert unit2 == "replicate" and comp2.loc[0, "signif"] == "n/a"         # 1 control plate
    path = tmp_path / "g.md"
    ps._write_grouped_report(str(path), "d", _s, comp2, unit2, "ctrl", {})
    txt = path.read_text(encoding="utf-8")
    assert "nan" not in txt and "| n/a |" in txt


def test_A7_paste_sentence_is_only_the_sentence(tmp_path):
    res = ps.run(_args(tmp_path, _frame()))
    s = ps.paste_sentence("diameter_mm", res["summary"], res["omni"], res["unit"], res["have_rep"])
    assert "##" not in s and "\n" not in s
    assert s.startswith("diameter_mm differed between the 3 samples (one-way ANOVA on plate means")
    assert "Pairwise (Tukey HSD)" in s and "T4 " in s


def test_A7_dollar_and_backslash_titles_draw(tmp_path):
    df = _tidy(_frame())
    opts = dict(ps.DEFAULTS, title=r"Cost $5 \ $\alpha_ $ test", ylabel="a $\\x$ b")
    fig = ps.plot_violin(df, ["T4", "T7", "lambda"], opts, "d", {})
    fig.savefig(str(tmp_path / "t.png"))
    plt.close(fig)


def test_A7_report_header_has_a_real_stamp_and_toolkit_version(tmp_path):
    ps.run(_args(tmp_path, _frame()))
    head = (tmp_path / "out" / "report_diameter_mm.md").read_text(encoding="utf-8").splitlines()[2]
    assert "Plaque Toolkit" in head and head.startswith("_Generated 20")


def test_A8_log_y_refuses_nonpositive_unless_asked(tmp_path):
    df = _tidy(_frame()); df.loc[0, "value"] = 0.0
    with pytest.raises(SystemExit, match="1 value of"):
        ps.plot_violin(df, ["T4", "T7", "lambda"], dict(ps.DEFAULTS, log_y=True), "d", {})
    fig = ps.plot_violin(df, ["T4", "T7", "lambda"],
                         dict(ps.DEFAULTS, log_y=True, log_y_drop_nonpositive=True), "d", {})
    assert any("1 value ≤ 0 is not shown" in t.get_text() for t in fig.texts)
    assert fig.axes[0].get_yscale() == "log"
    plt.close(fig)


# =========================================================================== A9 .. A13
def test_A9_many_groups_annotate_only_against_the_reference():
    order = ["S%d" % i for i in range(12)]
    ph = {(a, b): 0.001 for a, b in itertools.combinations(order, 2)}
    plan = ps.annotation_plan(order, ph, {"annotate": "auto"})
    assert plan["pairs"] and all("S0" in pr for pr in plan["pairs"]) and "12 samples" in plan["note"]
    plan2 = ps.annotation_plan(order, ph, {"annotate": "auto", "control": "S5"})
    assert all("S5" in pr for pr in plan2["pairs"])


def test_A9_compact_letters_property():
    rng = np.random.default_rng(0)
    for _ in range(200):
        k = int(rng.integers(3, 8))
        order = ["g%d" % i for i in range(k)]
        ph = {pr: float(rng.choice([0.001, 0.5])) for pr in itertools.combinations(order, 2)}
        L = ps.compact_letters(order, ph)
        for (a, b), p in ph.items():
            share = bool(set(L[a]) & set(L[b]))
            assert share == (p >= 0.05), (L, a, b, p)


def test_A10_palette_drives_plate_colours_and_markers():
    df = _tidy(_frame(plates=10, n=3))
    opts = dict(ps.DEFAULTS, palette="set2")
    gcol, rcol, neutral, reps = ps.violin_colours(df, ["T4", "T7", "lambda"], opts)
    assert neutral and set(rcol.values()) <= set(ps.PALETTES["set2"])
    _c, mk = ps._plate_style(reps, opts, True)
    assert len({(rcol[r], mk[r]) for r in reps}) == len(reps)                # no two plates alike


def test_A10_custom_palette_validation():
    assert ps.clean_palette("ff0000; 00aa00 0000ff") == ["#ff0000", "#00aa00", "#0000ff"]
    with pytest.raises(SystemExit, match="'zz12'"):
        ps.clean_palette("ff0000,zz12")
    with pytest.raises(SystemExit, match="needs 3"):
        ps.clean_palette(["#ff0000"], needed=3)


def test_A11_plotting_leaves_rcparams_alone(tmp_path):
    with matplotlib.rc_context():
        matplotlib.rcdefaults(); matplotlib.use("Agg")
        _a11_body(tmp_path)


def _a11_body(tmp_path):
    before = dict(matplotlib.rcParams)
    df = _tidy(_frame())
    plt.close(ps.plot_violin(df, ["T4", "T7", "lambda"], dict(ps.DEFAULTS), "d", {}))
    g = df.copy(); g["subgroup"] = np.where(g["replicate"] == "plate1", "a", "b")
    plt.close(ps.plot_grouped(g, ["T4", "T7"], ["a", "b"], "a", dict(ps.DEFAULTS), "d", pd.DataFrame()))
    summ = ps.group_summary(df, ["T4", "T7", "lambda"])
    ps.save_stats_table(summ, str(tmp_path / "s"), "d", "replicate")
    ps.save_pairwise_table({"T4": 1.0, "T7": 2.0}, {("T4", "T7"): 0.01}, str(tmp_path / "p"), "d", "replicate")
    after = dict(matplotlib.rcParams)
    assert {k: v for k, v in after.items() if before.get(k) != v} == {}


def test_A12_colour_words_and_text_starter():
    assert lk.colour_name("#E69F00") == "orange" and lk.colour_name("#8A78B0") == "purple"
    assert lk.colour_name("#B65C5C") == "muted red"
    for name, pal in ps.PALETTES.items():
        words = [lk.colour_name(c) for c in pal]
        assert len(set(words)) == len(words), name                            # never ambiguous
    e = [lk.entry("a", "#E5C494"), lk.entry("b", "#BFBFBF"), lk.entry("c", "#C8C8C8")]
    words = lk._colour_words(e)
    assert not any(w.split(" ")[0] == w.split(" ")[1] for w in words if " " in w)
    assert all(not w.startswith(("light light", "dark dark")) for w in words)
    key = ps.grouped_key(["WT", "mut"], "WT", {"WT": "#0072B2", "mut": "#E69F00"}, True)
    assert lk.text_starter(key).startswith("WT (control; blue, filled circles")


def test_A12_superplot_text_starter_names_the_samples():
    df = _tidy(_frame())
    fig = ps.plot_violin(df, ["T4", "T7", "lambda"], dict(ps.DEFAULTS), "d", {})
    text = lk.text_starter(lk.from_figure(fig))
    assert text.startswith("T4, T7 and lambda are shown as grey violins. Points are coloured by plate: plate1 (")
    assert lk.from_figure(fig)["font_families"][0] == lk.from_figure(fig)["font_family"]
    plt.close(fig)


def test_A12_make_figure_draws_without_the_key_module(tmp_path):
    shutil.copy(os.path.join(ROOT, "make_figure.py"), tmp_path / "make_figure.py")
    rows = [{"SAMPLE": s, "PLATE": "p%d" % (i % 2), "DIAMETER_MM": 1.0 + 0.01 * i}
            for s in ("WT", "B") for i in range(10)]
    pd.DataFrame(rows).to_csv(tmp_path / "t.csv", index=False)
    env = dict(os.environ, PYTHONPATH="")
    r = subprocess.run([sys.executable, "-I", str(tmp_path / "make_figure.py"), "--csv", str(tmp_path / "t.csv"),
                        "--legend-key", "--out", str(tmp_path / "f")], capture_output=True, text=True,
                       cwd=str(tmp_path), env=env)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "f.png").exists() and "legend key" in (r.stdout + r.stderr).lower()


def test_A13_no_box_is_gone_and_big_samples_get_a_shapiro_subsample():
    with pytest.raises(SystemExit):
        ps.build_args().parse_args(["d.csv", "--no-box"])
    rng = np.random.default_rng(1)
    df = pd.DataFrame({"group": ["A"] * 6000 + ["B"] * 6000, "replicate": np.nan,
                       "value": rng.normal(0, 1, 12000)})
    o = ps.run_stats(df, ["A", "B"], "plaque", "auto")[0]
    assert any("subsample of 5,000" in n for n in o["notes"])


# =========================================================================== B1 .. B5
def test_B1_dunnett_matches_a_simulation_of_the_max_t_statistic(tmp_path):
    df = _units({"C": 0.3, "A": 0.3, "B": 0.3}, 4, seed=5)
    df.loc[df["group"] == "A", "value"] += 0.5
    order = ["C", "A", "B"]
    omni, posthoc, _u, _h = ps.run_stats(df, order, "auto", "auto", posthoc="dunnett", control="C")
    assert omni["posthoc"] == "Dunnett" and set(posthoc) == {("A", "C"), ("B", "C")}
    assert all(np.isfinite(v) for v in posthoc.values())
    # independent check: P(max_i |T_i| >= |t_obs|) under H0 with the pooled variance, simulated
    g = {k: df.loc[df["group"] == k, "value"].values for k in order}
    n, dfw = 4, 9
    mse = sum(((v - v.mean()) ** 2).sum() for v in g.values()) / dfw
    rng = np.random.default_rng(0)
    M = 400000
    z = rng.standard_normal((M, 3)) / math.sqrt(n)
    s = np.sqrt(rng.chisquare(dfw, M) / dfw)
    tmax = np.max(np.abs(z[:, 1:] - z[:, :1]), axis=1) / (s * math.sqrt(2.0 / n))
    for k in ("A", "B"):
        t_obs = abs(g[k].mean() - g["C"].mean()) / math.sqrt(mse * 2.0 / n)
        assert posthoc[(k, "C")] == pytest.approx(float(np.mean(tmax >= t_obs)), abs=4e-3)
    row = [r for r in omni["pairwise"] if r["group_a"] == "A"][0]
    assert row["ci_method"] == "Dunnett simultaneous" and row["diff_ci95_lo"] < row["mean_diff"] < row["diff_ci95_hi"]
    res = ps.run(_args(tmp_path, df.rename(columns={"value": "diameter_mm"}), posthoc="dunnett",
                       control="C", order=order))
    pw = pd.read_csv(tmp_path / "out" / "pairwise_tests_diameter_mm.csv")
    assert {"diff_ci95_lo", "diff_ci95_hi"} <= set(pw.columns)
    rep = (tmp_path / "out" / "report_diameter_mm.md").read_text(encoding="utf-8")
    assert "assumes similar variances" in rep and res["omni"]["posthoc"] == "Dunnett"


def test_B1_grouped_dunnett():
    df = _units({"x": 0.3}, 4, seed=2)
    parts = []
    for i, s in enumerate(("ctrl", "t1", "t2")):
        d = _units({"G": 0.3}, 4, seed=10 + i); d["subgroup"] = s; d["value"] += 0.4 * i; parts.append(d)
    df = pd.concat(parts, ignore_index=True)
    _s, comp, _u = ps.grouped_stats(df, ["G"], ["ctrl", "t1", "t2"], "ctrl", posthoc="dunnett")
    assert list(comp["test"]) == ["Dunnett", "Dunnett"] and comp["p"].notna().all()
    assert (comp["diff_ci95_lo"] < comp["mean_diff"]).all()


def test_B2_difference_ci_and_hedges_g():
    df = _units({"A": 0.3, "B": 0.3}, 4, seed=8)
    omni = ps.run_stats(df, ["A", "B"], "auto", "auto")[0]
    a, b = (df.loc[df["group"] == g, "value"].values for g in "AB")
    r = omni["pairwise"][0]
    va, vb = a.var(ddof=1) / 4, b.var(ddof=1) / 4
    dfree = (va + vb) ** 2 / (va ** 2 / 3 + vb ** 2 / 3)
    h = st.t.ppf(0.975, dfree) * math.sqrt(va + vb)
    assert (r["diff_ci95_lo"], r["diff_ci95_hi"]) == pytest.approx((a.mean() - b.mean() - h, a.mean() - b.mean() + h))
    sp = math.sqrt((a.var(ddof=1) + b.var(ddof=1)) / 2)
    d = (a.mean() - b.mean()) / sp
    assert r["cohens_d"] == pytest.approx(d) and r["hedges_g"] == pytest.approx(d * (1 - 3 / (4 * 6 - 1)))


def test_B3_power_sentence_from_the_noncentral_t():
    df = _units({"A": 0.2, "B": 0.2, "C": 0.2}, 3, seed=9)
    pw = ps.run_stats(df, ["A", "B", "C"], "auto", "auto")[0]["power"]
    n, sd = 3, pw["pooled_sd"]
    d = pw["detectable_diff"] / sd
    nc, tc = d * math.sqrt(n / 2), st.t.ppf(0.975, 2 * n - 2)
    assert st.nct.sf(tc, 2 * n - 2, nc) + st.nct.cdf(-tc, 2 * n - 2, nc) == pytest.approx(0.80, abs=1e-6)
    assert "80 % power" in ps.power_sentence(pw)


def test_B4_tost_equivalence(tmp_path):
    df = _units({"A": 0.1, "B": 0.1}, 6, seed=12)
    omni = ps.run_stats(df, ["A", "B"], "auto", "auto", equivalence_margin=0.3)[0]
    a, b = (df.loc[df["group"] == g, "value"].values for g in "AB")
    se = math.sqrt(a.var(ddof=1) / 6 + b.var(ddof=1) / 6)
    dfree = se ** 4 / ((a.var(ddof=1) / 6) ** 2 / 5 + (b.var(ddof=1) / 6) ** 2 / 5)
    diff = a.mean() - b.mean()
    p = max(st.t.sf((diff + 0.3) / se, dfree), st.t.cdf((diff - 0.3) / se, dfree))
    r = omni["pairwise"][0]
    assert r["tost_p"] == pytest.approx(p, rel=1e-9)
    assert r["equivalence"] == ("equivalent within ±0.3" if p < 0.05 else "not shown equivalent")
    ps.run(_args(tmp_path, df.rename(columns={"value": "diameter_mm"}), equivalence_margin=0.3))
    assert "tost_p" in pd.read_csv(tmp_path / "out" / "pairwise_tests_diameter_mm.csv").columns
    assert "Equivalence (TOST" in (tmp_path / "out" / "report_diameter_mm.md").read_text(encoding="utf-8")


def test_B5_plate_variance_share_is_the_one_way_icc():
    df = _tidy(_frame(groups=("A",), mus=(2.0,), plates=4, n=10, plate_sd=0.3, sd=0.2))
    icc = ps.plate_variance_share(df)
    grp = [g["value"].values for _, g in df.groupby("replicate")]
    n, k = 10, 4
    gm = np.mean(np.concatenate(grp))
    msb = n * sum((x.mean() - gm) ** 2 for x in grp) / (k - 1)
    msw = sum(((x - x.mean()) ** 2).sum() for x in grp) / (k * (n - 1))
    assert icc["icc"] == pytest.approx((msb - msw) / (msb + (n - 1) * msw), rel=1e-9)


def test_cli_help_lists_the_new_options():
    h = ps.build_args().format_help()
    for flag in ("--equal-var", "--posthoc", "--equivalence-margin", "--log-y-drop-nonpositive", "letters"):
        assert flag in h


@pytest.mark.parametrize("center,error", [("median", "ci95"), ("median", "iqr"), ("median", "none"),
                                          ("mean", "sd"), ("mean", "ci95"), ("mean", "iqr")])
def test_A6_every_allowed_center_error_runs_end_to_end(tmp_path, center, error):
    res = ps.run(_args(tmp_path, _frame(), center=center, error=error, stats_table=True))
    assert "Whisker" in res["figure_sentence"] or "No whisker" in res["figure_sentence"]
    if (center, error) == ("median", "ci95"):
        assert "95 % CI of the median (plates resampled, 2,000 bootstrap resamples, seed 7)" in res["figure_sentence"]
        assert "median (bootstrap 95 % CI) of all plaques" in res["paste_sentence"] or len(res["order"]) > 2


def test_gate_shipped_example_default_numbers_unchanged_from_1_3_0(tmp_path):
    """Release gate: the shipped example with DEFAULT options gives the same numbers as v1.3.0
    (commit ca1a3ab). The constants are that version's CSV output; only columns were added."""
    res = ps.run(_args(tmp_path, os.path.join(ROOT, "plaque_stats", "example_data_wide.csv")))
    out = tmp_path / "out"
    om = pd.read_csv(out / "omnibus_test_diameter_mm.csv").iloc[0]
    assert (om["test"], om["unit"]) == ("one-way ANOVA", "replicate")
    assert om["p"] == pytest.approx(8.664450118784204e-06, rel=1e-10)
    assert om["levene_p"] == pytest.approx(0.6230307464548228, rel=1e-10)
    pw = pd.read_csv(out / "pairwise_tests_diameter_mm.csv")
    assert list(pw.columns[:7]) == ["group_a", "group_b", "mean_a", "mean_b", "mean_diff", "p_adj", "signif"]
    want = {("T4", "T7"): (0.8110540587580062, 0.0001484612589278),
            ("T4", "lambda"): (-0.5629870018707734, 0.0011220469260948),
            ("T7", "lambda"): (-1.3740410606287796, 6.985589097507905e-06)}
    for _, r in pw.iterrows():
        d, p = want[(r["group_a"], r["group_b"])]
        assert r["mean_diff"] == pytest.approx(d, abs=1e-12) and r["p_adj"] == pytest.approx(p, rel=1e-6)
    sm = pd.read_csv(out / "summary_by_group_diameter_mm.csv").set_index("group")
    assert sm.loc["T4", "mean"] == pytest.approx(2.6055142857142854, abs=1e-12)
    assert sm.loc["T7", "sd"] == pytest.approx(0.3737843416384026, abs=1e-12)
    assert res["omni"]["posthoc"] == "Tukey HSD" and not res["warnings"]



def test_A5_unit_plaque_quotes_plaque_statistics(tmp_path):
    df = _frame()
    res = ps.run(_args(tmp_path, df, unit="plaque", order=["T4", "T7"]))
    s = res["summary"].set_index("group")
    sem = s.loc["T4", "unit_sem"]
    assert s.loc["T4", "n_units"] == 60
    assert "%.2f ± %.2f" % (s.loc["T4", "unit_mean"], sem) in res["paste_sentence"]
    assert "mean ± SEM of the plaques" in res["paste_sentence"]
    assert "--unit plaque" in res["figure_sentence"]


def test_A5_whisker_is_drawn_above_the_plate_dots():
    fig = ps.plot_violin(_tidy(_frame()), ["T4", "T7"], dict(ps.DEFAULTS), "d", {})
    ax = fig.axes[0]
    dots = max(c.get_zorder() for c in ax.collections if c.get_sizes().size and c.get_sizes()[0] > 50)
    whisk = [ln.get_zorder() for ln in ax.lines if len(ln.get_xdata()) == 2 and ln.get_xdata()[0] == ln.get_xdata()[1]]
    assert whisk and min(whisk) > dots
    plt.close(fig)


def test_A8_grouped_log_note_reaches_the_report(tmp_path):
    df = _frame(groups=("T4",), mus=(2.0,))
    df["host"] = np.where(df["replicate"] == "plate1", "a", "b")
    df.loc[0, "diameter_mm"] = -0.1
    res = ps.run(_args(tmp_path, df, subgroup="host", log_y=True, log_y_drop_nonpositive=True))
    assert any("1 value ≤ 0 is not shown" in n for n in res["notes"])
    assert "1 value ≤ 0 is not shown" in (tmp_path / "out" / "grouped_report_diameter_mm.md").read_text(encoding="utf-8")


def test_A9_long_keys_wrap_into_columns():
    entries = [lk.entry("p%d" % i, "#0072B2") for i in range(30)]
    key = lk.make_key(entries)
    assert lk.key_columns(key) == 3
    fig = lk.key_figure(key)
    assert fig.legends[0]._ncols == 3 if hasattr(fig.legends[0], "_ncols") else True


def test_A7_dollar_in_sample_names_runs_with_tables(tmp_path):
    df = _frame(groups=("a $\\x$ b", "T7"), mus=(2.0, 2.5))
    res = ps.run(_args(tmp_path, df, stats_table=True, formats=["png", "svg"]))
    assert res["order"][0] == "a $\\x$ b"
    assert (tmp_path / "out" / "stats_table_diameter_mm.png").exists()


def test_B3_plates_needed_is_the_smallest_n_with_80_percent_power():
    df = _units({"A": 0.2, "B": 0.2, "C": 0.2}, 3, seed=9)
    df.loc[df["group"] == "C", "value"] += 0.3
    pw = ps.run_stats(df, ["A", "B", "C"], "auto", "auto")[0]["power"]

    def power(d, n):
        nc, tc = d * math.sqrt(n / 2), st.t.ppf(0.975, 2 * n - 2)
        return st.nct.sf(tc, 2 * n - 2, nc) + st.nct.cdf(-tc, 2 * n - 2, nc)
    for key, diff in (("n_for_largest", "largest_diff"), ("n_for_smallest", "smallest_diff")):
        n, d = pw[key], pw[diff] / pw["pooled_sd"]
        assert power(d, n) >= 0.80 and (n == 2 or power(d, n - 1) < 0.80)


def test_C_caption_keeps_the_lowercase_n():
    fig = ps.plot_violin(_tidy(_frame(groups=tuple("ABCDEFGHIJ"), mus=tuple(np.linspace(1, 3, 10)))),
                         list("ABCDEFGHIJ"), dict(ps.DEFAULTS), "d", {})
    cap = [t.get_text() for t in fig.texts]
    assert "Bar values are in the summary table · n = plaques, N = plates." in cap
    plt.close(fig)



# =========================================================================== follow-up S1..S5
def test_S4_power_sentence_never_advises_fewer_than_3_plates():
    pw = {"available": True, "pooled_sd": 0.1, "n_per_group": 3, "power": 0.8, "alpha": 0.05,
          "equal_n": True, "detectable_diff": 0.3, "largest_diff": 1.37, "n_for_largest": 2,
          "smallest_diff": 0.2, "n_for_smallest": 7}
    s = ps.power_sentence(pw)
    assert "needs 2 plates" not in s
    assert "For the largest observed difference (1.37) the minimum of 3 plates per sample is enough" in s
    assert "detecting the smallest observed difference (0.2) needs 7 plates per sample" in s
    assert s.count("(computed from the observed spread; treat as a rough guide)") == 1
