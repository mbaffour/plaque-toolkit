"""CT-R1 fixer group "agreement-validate": Fiji agreement tab (parser, statistics, figure +
legend key, save paths), Compare vs Fiji auto-align, Validate tab, table display, About/Help.

Maths tests run anywhere; GUI tests need PySide6 + pytest-qt (skipped otherwise)."""
import math
import os
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "plaque_stats", "agreement"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import agreement as ap            # noqa: E402

EX_TOOL = [1.24, 0.98, 1.51, 0.62, 1.80, 1.11, 0.75, 1.35, 2.02, 0.90, 1.44, 1.19, 0.68, 1.60, 1.05]
EX_FIJI = [1.27, 0.96, 1.55, 0.60, 1.84, 1.09, 0.79, 1.38, 2.05, 0.93, 1.41, 1.22, 0.71, 1.57, 1.02]


import importlib.util as _ilu   # noqa: E402


@pytest.fixture
def qt(request):
    """qtbot when PySide6 + pytest-qt are there; otherwise the GUI test is SKIPPED (not an error)."""
    if _ilu.find_spec("PySide6") is None:
        pytest.skip("needs PySide6")
    try:
        return request.getfixturevalue("qtbot")
    except pytest.FixtureLookupError:
        pytest.skip("needs pytest-qt")


@pytest.fixture
def no_dialogs(qt, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    seen = []
    for name in ("warning", "information", "critical"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(
            lambda *a, _n=name, **k: seen.append((_n, a[1] if len(a) > 1 else "",
                                                  a[2] if len(a) > 2 else "")) or QMessageBox.Ok))
    return seen


@pytest.fixture
def agreement_tab(qt):
    from PySide6.QtWidgets import QMainWindow
    from app import ui as appui
    win = QMainWindow()
    tab = appui.AgreementTab()
    win.setCentralWidget(tab)
    qt.addWidget(win)
    tab._test_window = win          # keep the window alive for the test
    yield tab
    win.close()


# =========================================================================== 1. DA-F7 parser
@pytest.mark.parametrize("text,expected", [
    ("AREA_MM2\n1.24\n0.98\n1.51", [1.24, 0.98, 1.51]),            # digit in the header is not data
    ("Diameter (mm)\n1.2\n1.3", [1.2, 1.3]),
    ("7\t1.24\n8\t0.98\n9\t1.10", [1.24, 0.98, 1.10]),            # row numbers start at 7
    ("1\t1,27\n2\t0,98\n3\t1,10", [1.27, 0.98, 1.10]),            # decimal comma inside a tabbed table
    ("1;1,27\n2;0,98", [1.27, 0.98]),                              # semicolon + decimal comma
    (".62\n.5", [0.62, 0.5]),
    ("1,234.5\n2.5", [1234.5, 2.5]),
    ("1.24\t0.98\t1.51", [1.24, 0.98, 1.51]),                      # values on one line
    ("1.24 0.98 1.51", [1.24, 0.98, 1.51]),
    ("1.24; 0.98; 1.51", [1.24, 0.98, 1.51]),
    ("1.24, 0.98, 1.51", [1.24, 0.98, 1.51]),
])
def test_parser_reads_the_measurements(text, expected):
    vals, _notes = ap.parse_values(text)
    assert vals == pytest.approx(expected)


def test_parser_picks_the_area_column_in_a_fiji_table_and_says_so():
    text = " \tMean\tArea\tFeret\n7\t100\t1.27\t1.4\n8\t90\t1.5\t1.6\n9\t80\t2\t2.1"
    vals, notes = ap.parse_values(text)
    assert vals == [1.27, 1.5, 2.0]
    joined = " ".join(notes)
    assert "header" in joined and "row number" in joined and 'column 3 "Area"' in joined


def test_parser_refuses_a_word_in_the_middle_naming_the_line():
    with pytest.raises(ValueError, match=r"Line 3 \(\"n/a\"\)"):
        ap.parse_values("Area\n1.2\nn/a\n1.4")


def test_parser_refuses_ragged_rows():
    with pytest.raises(ValueError, match="Line 2 has 1 value but line 1 has 2 values"):
        ap.parse_values("1\t2\n3")


def test_agreement_tab_header_digit_no_longer_shifts_the_pairs(agreement_tab):
    tab = agreement_tab
    tab.tool_in.setPlainText("AREA_MM2\n" + "\n".join(map(str, EX_TOOL[:6])))
    tab.fiji_in.setPlainText("Area\n" + "\n".join(map(str, EX_FIJI[:6])))
    tab.unit.setCurrentIndex(0)
    tab._compute()
    assert tab.err.text() == ""
    assert tab._metrics["n"].text() == "6"
    assert float(tab._metrics["icc"].text()) > 0.99
    assert tab.preview.rowCount() == 6
    assert tab.preview.item(0, 0).text() == "1.24" and tab.preview.item(0, 1).text() == "1.27"
    assert 'Skipped the header line "AREA_MM2"' in tab.parse_notes.text()


def test_agreement_tab_refuses_unequal_lengths_naming_both_counts(agreement_tab):
    tab = agreement_tab
    tab._example()
    assert tab.savefig_btn.isEnabled()
    tab.tool_in.setPlainText("\n".join(map(str, EX_TOOL)))
    tab.fiji_in.setPlainText("\n".join(map(str, EX_FIJI[:14])))
    tab._compute()
    assert "15 Plaque Toolkit vs 14 Fiji / ImageJ" in tab.err.text()
    assert tab._last is None and tab.canvas is None
    assert not tab.savefig_btn.isEnabled() and tab._metrics["n"].text() == "—"
    assert tab.preview.rowCount() == 15


def test_agreement_tab_names_a_bad_middle_line(agreement_tab):
    tab = agreement_tab
    tab.tool_in.setPlainText("1.2\n1.3\nabc\n1.5")
    tab.fiji_in.setPlainText("1.2\n1.3\n1.4\n1.5")
    tab._compute()
    assert tab.err.text().startswith('Plaque Toolkit box: Line 3 ("abc") is not a number')


# =========================================================================== 2. statistics honesty
import agreement as cli_ag                # noqa: E402  plaque_stats/agreement/agreement.py
from scipy import stats as st             # noqa: E402

MARK_A, MARK_B = "# >>> SHARED AGREEMENT CORE >>>", "# <<< SHARED AGREEMENT CORE <<<"


def _shared_block(path):
    text = open(path, encoding="utf-8").read()
    return text[text.index(MARK_A):text.index(MARK_B)]


def test_the_two_copies_share_one_core_text_for_text():
    a = _shared_block(os.path.join(ROOT, "app", "agreement.py"))
    b = _shared_block(os.path.join(ROOT, "plaque_stats", "agreement", "agreement.py"))
    assert a == b
    for name in ("report_sentence", "icc_ci", "compute", "prediction_interval", "full_stats",
                 "icc_interval_note"):
        assert "def %s(" % name in a


def _icc_ref(x, y):
    """Independent ICC(A,1) + McGraw & Wong 1996 F interval from the ANOVA table (matrix form)."""
    M = np.column_stack([x, y]).astype(float); n, k = M.shape
    gm = M.mean(); rm = M.mean(axis=1); cm = M.mean(axis=0)
    MSR = k * ((rm - gm) ** 2).sum() / (n - 1)
    MSC = n * ((cm - gm) ** 2).sum() / (k - 1)
    MSE = ((M - rm[:, None] - cm[None, :] + gm) ** 2).sum() / ((n - 1) * (k - 1))
    icc = (MSR - MSE) / (MSR + (k - 1) * MSE + k / n * (MSC - MSE))
    a = k * icc / (n * (1 - icc)); b = 1 + k * icc * (n - 1) / (n * (1 - icc))
    v = (a * MSC + b * MSE) ** 2 / ((a * MSC) ** 2 / (k - 1) + (b * MSE) ** 2 / ((n - 1) * (k - 1)))
    Fl = st.f.ppf(0.975, n - 1, v); Fu = st.f.ppf(0.975, v, n - 1)
    lo = n * (MSR - Fl * MSE) / (Fl * (k * MSC + (k * n - k - n) * MSE) + n * MSR)
    hi = n * (Fu * MSR - MSE) / (k * MSC + (k * n - k - n) * MSE + n * Fu * MSR)
    return icc, lo, hi


def test_icc_interval_is_the_exact_mcgraw_wong_f_interval_in_both_copies():
    rng = np.random.default_rng(11)
    for _ in range(200):
        n = int(rng.integers(5, 60))
        t = rng.normal(1.5, .5, n); a = t + rng.normal(0.03, .08, n); b = t + rng.normal(0, .08, n)
        icc, lo, hi = _icc_ref(b, a)
        for mod in (ap, cli_ag):
            s = mod.full_stats(list(a), list(b))
            assert s["icc"] == pytest.approx(icc, abs=1e-9)
            assert s["icc_lo"] == pytest.approx(lo, abs=1e-9)
            assert s["icc_hi"] == pytest.approx(hi, abs=1e-9)


def test_no_icc_interval_below_five_pairs():
    s = ap.full_stats([1.0, 2.0, 3.1, 4.2], [1.1, 2.0, 3.0, 4.0])
    assert math.isnan(s["icc_lo"]) and math.isnan(s["icc_hi"])
    assert "n too small for an interval" in ap.report_sentence(s)


def test_icc_interval_coverage_is_close_to_95_percent():
    """Seeded simulation, true ICC 0.9 (no rater bias), n = 10: the old bootstrap covered ~0.89."""
    rng = np.random.default_rng(2026)
    hits, sims = 0, 400
    for _ in range(sims):
        t = rng.normal(0, math.sqrt(0.9), 10)
        x = t + rng.normal(0, math.sqrt(0.1), 10); y = t + rng.normal(0, math.sqrt(0.1), 10)
        lo, hi = ap.icc_ci(list(x), list(y))
        hits += lo <= 0.9 <= hi
    assert 0.92 <= hits / sims <= 0.985


def test_limits_of_agreement_are_bias_196_sd_at_every_n_with_a_prediction_interval_below_20():
    """Supervisor decision (CT-R1 follow-up): the headline limits are bias +/- 1.96 SD at every n
    (no jump between 19 and 20 pairs); below 20 pairs a 95% prediction interval is ADDED."""
    rng = np.random.default_rng(5)
    inside, sims, n = 0, 3000, 5
    for _ in range(sims):
        d = rng.normal(0, 1, n)
        lo, hi = ap.prediction_interval(d.mean(), d.std(ddof=1), n)
        inside += lo <= rng.normal() <= hi
    assert 0.93 <= inside / sims <= 0.97                 # +/-1.96 SD gives ~0.85 here
    for mod in (ap, cli_ag):
        s = mod.full_stats(EX_TOOL, EX_FIJI)             # the tab's own n = 15 example
        assert (s["loa_lo"], s["loa_hi"]) == pytest.approx((-0.0688, 0.0488), abs=1e-12)
        h = st.t.ppf(.975, 14) * s["sd"] * math.sqrt(1 + 1 / 15)
        assert (s["pred_lo"], s["pred_hi"]) == pytest.approx((s["bias"] - h, s["bias"] + h), rel=1e-12)
        assert s["loa_ci_halfwidth"] == pytest.approx(
            st.t.ppf(.975, 14) * s["sd"] * math.sqrt(1 / 15 + 1.96 ** 2 / 28), rel=1e-12)
        sent = mod.report_sentence(s)
        assert "95% limits of agreement of -0.069 to +0.049 mm" in sent
        assert ("With only 15 pairs, a new difference is expected within %+.3f to %+.3f mm "
                "(95%% prediction interval)." % (s["pred_lo"], s["pred_hi"])) in sent
    rng = np.random.default_rng(3)
    t = list(rng.normal(1.5, .4, 20)); f = [v + e for v, e in zip(t, rng.normal(0, .05, 20))]
    s19, s20 = ap.full_stats(t[:19], f[:19]), ap.full_stats(t, f)
    for s_ in (s19, s20):
        assert s_["loa_hi"] == pytest.approx(s_["bias"] + 1.96 * s_["sd"], rel=1e-12)
    assert math.isfinite(s19["pred_lo"]) and math.isnan(s20["pred_lo"])
    assert "prediction interval" not in ap.report_sentence(s20)


def test_icc_interval_note_for_a_systematic_offset():
    rng = np.random.default_rng(11)
    big = rng.normal(1.5, .5, 200)
    s = ap.full_stats(list(big * 1.02 + rng.normal(0, .001, 200)), list(big))
    assert s["t_p"] < 0.05 and s["icc"] - s["icc_lo"] > 0.10
    note = ap.icc_interval_note(s)
    assert note == ("The ICC interval is wide because the two methods differ by a systematic offset "
                    "(bias %+.3f mm): with two methods that offset is estimated from a single "
                    "contrast. Judge agreement from the bias and the limits of agreement." % s["bias"])
    import pandas as pd
    df = pd.read_csv(os.path.join(ROOT, "validation", "paired_toolkit_vs_fiji.csv"), comment="#")
    assert ap.icc_interval_note(ap.full_stats(df["diam_tool_mm"].tolist(), df["diam_fiji_mm"].tolist())) == ""


def test_icc_note_shows_under_the_chips_and_in_the_report(agreement_tab):
    rng = np.random.default_rng(11)
    big = rng.normal(1.5, .5, 200)
    tab = agreement_tab
    tab.tool_in.setPlainText("\n".join("%.6f" % v for v in big * 1.02 + rng.normal(0, .001, 200)))
    tab.fiji_in.setPlainText("\n".join("%.6f" % v for v in big))
    tab._compute()
    assert tab.icc_note.text().startswith("The ICC interval is wide because") and not tab.icc_note.isHidden()
    assert "Note: The ICC interval is wide" in tab.report.toPlainText()
    tab._example()
    assert tab.icc_note.isHidden() and "Note:" not in tab.report.toPlainText()


def test_shipped_validation_point_estimates_do_not_move():
    import pandas as pd
    df = pd.read_csv(os.path.join(ROOT, "validation", "paired_toolkit_vs_fiji.csv"), comment="#")
    s = cli_ag.full_stats(df["diam_tool_mm"].tolist(), df["diam_fiji_mm"].tolist())
    assert s["icc"] == pytest.approx(0.9743432483079868, abs=1e-12)
    assert s["bias"] == pytest.approx(-0.02844900000000001, abs=1e-12)
    assert s["r"] == pytest.approx(0.9788270521032845, abs=1e-12)
    assert s["ccc"] == pytest.approx(0.9740908038041612, abs=1e-12)
    assert (s["loa_lo"], s["loa_hi"]) == pytest.approx((-0.14565328366494346, 0.08875528366494342), abs=1e-12)
    assert (s["icc_lo"], s["icc_hi"]) == pytest.approx((0.94928, 0.98546), abs=1e-5)   # was 0.9627-0.9821 (bootstrap)


def test_one_sentence_everywhere_with_three_decimals_and_no_double_plaque():
    s = ap.full_stats(EX_TOOL, EX_FIJI)
    a = ap.report_sentence(s, "mm", "plaque diameters")
    b = cli_ag.report_sentence(cli_ag.full_stats(EX_TOOL, EX_FIJI), "mm", "plaque diameters",
                               "Plaque Toolkit", "Fiji / ImageJ")
    assert a == b
    assert a.startswith("Plaque diameters measured with Plaque Toolkit agreed closely with Fiji / ImageJ")
    assert "Plaque plaque" not in a and "r = 0.997" in a and "ICC(A,1) = 0.997" in a
    assert "No proportional bias was detected" in a and "each limit ±" in a      # CT-R2 N8 wording


def test_a_constant_offset_is_not_called_significant_from_float_noise():
    base = [0.8, 1.1, 1.5, 1.9, 2.4, 2.2, 1.3]
    for mod in (ap, cli_ag):
        s = mod.full_stats([v + 0.1 for v in base], base)
        assert s["sd"] == 0.0 and math.isnan(s["t_p"]) and math.isnan(s["ba_slope_p"])
        sent = mod.report_sentence(s)
        assert "significantly different" not in sent and "difference from zero not testable" in sent
        assert "depend on plaque size" not in sent and "spread is zero" in sent


def test_nan_p_values_read_not_testable_never_significant():
    base = [0.8, 1.1, 1.5, 1.9, 2.4, 2.2, 1.3]
    s = ap.full_stats([v + 0.1 for v in base], base)            # constant offset
    s["t_p"] = float("nan")
    sent = ap.report_sentence(s)
    assert "p = nan" not in sent and "significantly different" not in sent
    assert "difference from zero not testable" in sent
    assert ap._pstr(float("nan")) == "p not testable"


@pytest.mark.parametrize("tool,ref,msg", [
    ([1.2, 1.5, 0.9, 1.1], [1.2, 1.5, 0.9, 1.1], "identical"),
    ([1.5] * 7, [0.8, 1.1, 1.5, 1.9, 2.4, 2.2, 1.3], "Every tool value is the same"),
    ([1.5] * 7, [1.5] * 7, "identical"),
    ([1.0, 2.0], [1.1, 2.0], "at least 3"),
])
def test_degenerate_input_is_refused_in_plain_words(tool, ref, msg):
    for mod in (ap, cli_ag):
        with pytest.raises(ValueError, match=msg):
            mod.compute(tool, ref)


def test_small_n_wording_is_softened():
    s = ap.full_stats([1.0, 2.0, 3.1, 1.6, 2.4, 0.9], [1.1, 2.0, 3.0, 1.5, 2.5, 1.0])
    sent = ap.report_sentence(s, "mm", "plaque diameters")
    assert sent.startswith("With only 6 pairs (too few for precise estimates), plaque diameters")
    assert "appeared to agree" in sent


# =========================================================================== 3. figure + legend key
LK = ap._lk                                  # the same helper the figure uses
from matplotlib import colors as mcolors    # noqa: E402


def _outlier_stats(mod=ap):
    rng = np.random.default_rng(1)
    f = rng.uniform(0.5, 2.5, 30); t = f + rng.normal(0, .03, 30); t[3] += .25; t[17] -= .2
    return mod.full_stats(list(t), list(f))


def _drawn_styles(fig):
    """(colour hex, kind) of every point set and line actually drawn on the axes."""
    out = set()
    for ax in fig.axes:
        for coll in ax.collections:
            out.add((mcolors.to_hex(coll.get_facecolor()[0]).upper(), "marker"))
        for ln in ax.lines:
            out.add((mcolors.to_hex(ln.get_color()).upper(), "line", ln.get_linestyle()))
    return out


@pytest.mark.parametrize("mod", [ap, cli_ag], ids=["desktop", "cli"])
def test_key_lists_every_encoding_drawn_and_nothing_else(mod):
    s = _outlier_stats(mod)
    fig = mod.make_figure(s, "mm", show_key=False)
    key = LK.from_figure(fig)
    labels = [e["label"] for e in key["entries"]]
    assert labels == ["within the limits of agreement", "outside the 95% limits of agreement",
                      "line of identity (y = x)", "least-squares fit", "zero difference",
                      "mean bias", "95% limits of agreement"]
    drawn = _drawn_styles(fig)
    keyed = set()
    for e in key["entries"]:
        if e["kind"] == "marker":
            keyed.add((e["colour"], "marker"))
        else:
            keyed.add((e["colour"], "line", e["linestyle"]))
    assert drawn == keyed
    # one colour for 'within limits' in both panels (DA-F4)
    within = {mcolors.to_hex(ax.collections[0].get_facecolor()[0]) for ax in fig.axes}
    assert len(within) == 1
    # no outliers -> no 'outside' row
    s2 = mod.full_stats(EX_TOOL, EX_FIJI)
    assert "outside the 95% limits of agreement" not in [e["label"] for e in LK.from_figure(mod.make_figure(s2))["entries"]]


def test_embedded_key_equals_standalone_key():
    s = _outlier_stats()
    fig = ap.make_figure(s, "mm", show_key=True)
    key = LK.from_figure(fig)
    leg = fig.legends[0]
    assert [t.get_text() for t in leg.get_texts()] == [e["label"] for e in key["entries"]]
    kf = LK.key_figure(key)
    assert [t.get_text() for t in kf.legends[0].get_texts()] == [t.get_text() for t in leg.get_texts()]
    for h_emb, h_std in zip(leg.legend_handles, kf.legends[0].legend_handles):
        assert mcolors.to_hex(h_emb.get_color() if hasattr(h_emb, "get_color") else h_emb.get_facecolor()) == \
            mcolors.to_hex(h_std.get_color() if hasattr(h_std, "get_color") else h_std.get_facecolor())
    assert leg.get_texts()[0].get_fontfamily() == kf.legends[0].get_texts()[0].get_fontfamily()
    assert not ap.make_figure(s, "mm", show_key=False).legends
    # panel keys are subsets
    a = [e["label"] for e in LK.from_figure(ap.make_panel(s, "scatter"))["entries"]]
    b = [e["label"] for e in LK.from_figure(ap.make_panel(s, "bland"))["entries"]]
    assert "mean bias" not in a and "least-squares fit" in a
    assert "least-squares fit" not in b and "mean bias" in b


def _render(fig, tmp_path, name):
    p = str(tmp_path / name)
    ap.save_figure(fig, p, dpi=100)
    agg = fig.canvas.__class__.__name__
    fig.canvas.draw()                       # a redraw OUTSIDE figure_rc (as the Qt canvas does)
    return open(p, "rb").read(), bytes(fig.canvas.buffer_rgba()), agg


def test_figure_is_identical_before_and_after_other_plots_change_rcparams(tmp_path):
    import matplotlib
    import matplotlib.pyplot as plt
    s = _outlier_stats()
    before = _render(ap.make_figure(s), tmp_path, "a.png")
    saved = dict(matplotlib.rcParams)
    try:
        # what plaque_stats.plot_violin does, and worse
        plt.rcParams.update({"font.size": 12, "font.family": "serif", "axes.linewidth": 2.5,
                             "lines.linewidth": 4, "xtick.labelsize": 15, "xtick.major.size": 9,
                             "axes.facecolor": "#eeeeee", "figure.facecolor": "#ffeeee"})
        after = _render(ap.make_figure(s), tmp_path, "b.png")
    finally:
        matplotlib.rcParams.update(saved)
    assert before[0] == after[0]            # saved PNG bytes
    assert before[1] == after[1]            # canvas pixels after a redraw outside the context


def test_cli_writes_key_files_beside_every_figure(tmp_path):
    src = tmp_path / "pairs.csv"
    src.write_text("id,toolkit_mm,manual_mm\n" + "".join(
        "%d,%.3f,%.3f\n" % (i + 1, t, f) for i, (t, f) in enumerate(zip(EX_TOOL, EX_FIJI))))
    out = tmp_path / "out"
    cli_ag.main([str(src), "--out", str(out), "--formats", "png,svg", "--legend-key", "--key-on-figure"])
    names = set(os.listdir(out))
    for base in ("agreement_diameters", "agreement_diameters_A_method_comparison",
                 "agreement_diameters_B_bland_altman"):
        assert {base + ".png", base + "_legend_key.png", base + "_legend_key.svg",
                base + "_legend_text.txt"} <= names
    txt = (out / "agreement_diameters_legend_text.txt").read_text()
    assert txt.startswith("within the limits of agreement (bluish green, filled circles")
    out2 = tmp_path / "out2"
    cli_ag.main([str(src), "--out", str(out2), "--formats", "png", "--no-legend-key"])
    assert not [n for n in os.listdir(out2) if "legend" in n]


def test_agreement_tab_key_controls_follow_the_current_figure(agreement_tab, tmp_path):
    tab = agreement_tab
    tab._example()
    assert tab.key_btn.isEnabled() and tab.key_text.text().startswith("within the limits of agreement (")
    assert "outside" not in tab.key_text.text()
    assert tab.canvas.figure.legends                      # placed on the figure by default
    tab.key_cb.setChecked(False)
    assert not tab.canvas.figure.legends
    p = tab._save_key(str(tmp_path / "k.svg"))
    assert p and os.path.exists(p) and "within the limits of agreement" in open(p).read()
    # the stand-alone key follows the CURRENT data (an outlier appears)
    s = _outlier_stats()
    tab.tool_in.setPlainText("\n".join("%.6f" % v for v in s["tool"]))
    tab.fiji_in.setPlainText("\n".join("%.6f" % v for v in s["fiji"]))
    tab._compute()
    assert "outside the 95% limits of agreement (" in tab.key_text.text()


# =========================================================================== 4. DA-F8 Compare vs Fiji
def _synthetic_plate(n=27, seed=4):
    import pandas as pd
    rng = np.random.default_rng(seed)
    pts = []
    while len(pts) < n:                                       # well-separated plaques in an 80 mm dish
        p = rng.uniform(-38, 38, 2)
        if np.hypot(*p) < 38 and all(np.hypot(*(p - q)) > 6 for q in pts):
            pts.append(p)
    pts = np.array(pts) + 42.5
    d = rng.uniform(0.8, 2.4, n)
    return pd.DataFrame({"INDEX": np.arange(1, n + 1), "X": pts[:, 0], "Y": pts[:, 1], "DIAMETER": d})


def _fiji_pixels(app, scale_px_per_mm=12.5, deg=20.0, shift=(300.0, 150.0), drop=3, seed=5):
    import pandas as pd
    rng = np.random.default_rng(seed)
    perm = rng.permutation(len(app))[: len(app) - drop]
    th = math.radians(deg); R = np.array([[math.cos(th), -math.sin(th)], [math.sin(th), math.cos(th)]])
    xy = (app[["X", "Y"]].to_numpy()[perm] @ R.T) * scale_px_per_mm + np.array(shift)
    xy += rng.normal(0, 0.3, xy.shape)                        # sub-pixel centroid noise
    dpx = app["DIAMETER"].to_numpy()[perm] * scale_px_per_mm * 1.02
    return pd.DataFrame({" ": np.arange(1, len(perm) + 1), "Area": np.pi * dpx ** 2 / 4,
                         "Mean": 120.0, "X": xy[:, 0], "Y": xy[:, 1], "Feret": dpx * 1.05})


def test_auto_align_recovers_pixel_scale_rotation_and_shift_from_a_tab_separated_file(tmp_path):
    from app import fiji_match
    app_df = _synthetic_plate()
    fj = _fiji_pixels(app_df)
    path = tmp_path / "Results.xls"                            # Fiji's own Save As: tab-separated
    fj.to_csv(path, sep="\t", index=False)
    fiji_df = fiji_match.load_fiji_results(str(path))
    res = fiji_match.match(app_df, fiji_df, align="auto")
    s = res["summary"]
    assert s["n_matched"] == len(fj) and not s["low_match"]
    assert s["scale"] == pytest.approx(1 / 12.5, rel=0.02)
    assert s["bias_mean_mm"] == pytest.approx(-0.02 * app_df["DIAMETER"].mean(), abs=0.03)


def test_semicolon_decimal_comma_and_center_of_mass_headers_load(tmp_path):
    from app import fiji_match
    app_df = _synthetic_plate()
    fj = _fiji_pixels(app_df, scale_px_per_mm=1.0, deg=0, shift=(0, 0)).rename(columns={"X": "XM", "Y": "YM"})
    path = tmp_path / "res.csv"
    fj.to_csv(path, sep=";", decimal=",", index=False)
    fiji_df = fiji_match.load_fiji_results(str(path))
    assert len(fiji_df) == len(fj)
    assert fiji_df["fx"].to_numpy() == pytest.approx(fj["XM"].to_numpy())
    res = fiji_match.match(app_df, fiji_df, align="none")
    assert res["summary"]["n_matched"] == len(fj)


def test_a_poor_match_warns_and_cannot_be_saved(qt, tmp_path, monkeypatch):
    import pandas as pd
    from PySide6.QtWidgets import QFileDialog
    from app import fiji_dialog
    app_df = _synthetic_plate()
    rng = np.random.default_rng(9)
    junk = pd.DataFrame({"X": rng.uniform(0, 85, 27), "Y": rng.uniform(0, 85, 27), "Area": 1.0})
    path = tmp_path / "junk.csv"; junk.to_csv(path, index=False)
    dlg = fiji_dialog.FijiCompareDialog(app_df, calibrated=True)
    qt.addWidget(dlg)
    dlg.align.setCurrentIndex(1)                               # auto-align on unrelated points
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(path), "")))
    dlg._choose()
    assert dlg.result["summary"]["low_match"]
    assert not dlg.save_btn.isEnabled()
    assert "probably wrong and cannot be saved" in dlg.summary.text()


# =========================================================================== 5. DA-F19/F20 agreement part
def test_clear_and_failed_compute_leave_no_stale_result(agreement_tab):
    tab = agreement_tab
    tab._example()
    assert tab.canvas is not None and tab.report.toPlainText()
    tab._clear()
    assert tab.canvas is None and tab.fig_placeholder is not None
    assert tab.report.toPlainText() == "" and tab.key_text.text() == ""
    assert all(v.text() == "—" for v in tab._metrics.values())
    assert not any(b.isEnabled() for b in tab._result_buttons())
    tab._example()
    tab.tool_in.setPlainText("1.5\n1.5\n1.5"); tab.fiji_in.setPlainText("1.0\n1.2\n1.4")
    tab._compute()
    assert "Every tool value is the same" in tab.err.text()
    assert tab.canvas is None and tab._last is None and not tab.savefig_btn.isEnabled()


@pytest.mark.parametrize("typed,filt,expected", [
    ("pairs_0.5x", "PNG image — 300 dpi (*.png)", "pairs_0.5x.png"),
    ("typed.pdf", "PNG image — 300 dpi (*.png)", "typed.pdf"),
    ("fig_0.5MOI", "SVG — vector, editable in Illustrator/Inkscape (*.svg)", "fig_0.5MOI.svg"),
])
def test_save_figure_honours_a_typed_extension_and_keeps_dotted_names(agreement_tab, tmp_path,
                                                                     monkeypatch, typed, filt, expected):
    from PySide6.QtWidgets import QFileDialog
    tab = agreement_tab
    tab._example()
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(tmp_path / typed), filt)))
    p = tab._save_fig()
    assert p == str(tmp_path / expected) and os.path.exists(p)


def test_save_paired_csv_adds_csv_only_when_needed_and_rounds(agreement_tab, tmp_path):
    tab = agreement_tab
    tab._example()
    p = tab._save_csv(str(tmp_path / "pairs_0.5x"))
    assert p.endswith("pairs_0.5x.csv")
    text = open(p).read()
    assert "-0.03\n" in text and "000000000" not in text
    assert tab._save_csv(str(tmp_path / "kept.csv")).endswith("kept.csv")


# =========================================================================== 6. DA-F22 Validate
import json as _json   # noqa: E402

PLAQUES = [(380, 380), (520, 400), (430, 540), (560, 550), (350, 500)]


def _label_folder(tmp_path, img):
    """A label folder: one good label file, one with a plaque lacking coordinates, one whose
    image is missing, and a non-label JSON (run_metadata)."""
    d = tmp_path / "labels"; d.mkdir()
    mmpp = 90.0 / 760.0
    recs = [{"index": i + 1, "x_px": float(x), "y_px": float(y), "r_px": 26.0,
             "area_px": math.pi * 26 ** 2, "diam_mm": round(52 * mmpp, 3), "source": "auto",
             "kind": "plaque"} for i, (x, y) in enumerate(PLAQUES)]
    meta = {"image": os.path.basename(img), "image_path": img, "mm_per_px": mmpp,
            "dish_diam_px": 760, "schema": "plaque-groundtruth-v1"}
    (d / "labels_good.json").write_text(_json.dumps({"meta": meta, "plaques": recs}))
    bad = [dict(r) for r in recs]; del bad[2]["x_px"]
    (d / "labels_nocoords.json").write_text(_json.dumps({"meta": meta, "plaques": bad}))
    gone = dict(meta, image="missing.tif", image_path=str(tmp_path / "missing.tif"))
    (d / "labels_noimage.json").write_text(_json.dumps({"meta": gone, "plaques": recs}))
    (d / "run_metadata.json").write_text(_json.dumps({"tool": "plaque toolkit", "meta": {}}))
    return d


def test_validate_scores_only_label_files_and_fails_bad_ones_with_reasons(neutral_plate_tif, tmp_path):
    from app import validate as V
    d = _label_folder(tmp_path, neutral_plate_tif)
    res = V.validate(str(d), modes=("current",))
    assert res["n_label_files"] == 3 and res["skipped"] == ["run_metadata.json"]
    pp = res["per_plate_df"].set_index("label_file")
    assert pp.loc["labels_good.json", "error"] == ""
    assert "1 of 5 labelled plaques have no x_px/y_px" in pp.loc["labels_nocoords.json", "error"]
    assert "could not locate the plate image" in pp.loc["labels_noimage.json", "error"]
    pm = res["per_mode_df"].iloc[0]
    good = pp.loc["labels_good.json"]
    assert pm["n_plates"] == 1 and pm["tp"] == good["tp"] and pm["fn"] == good["fn"]   # failed rows excluded
    assert V.summary_status(res) == ("Scored 3 plates x 1 engine; 2 failed (see the last column). "
                                     "Skipped 1 JSON file that is not a plaque label file.")
    from app import __version__
    sent = V.report_sentence(res, {"current": "Current (corrected)"}, __version__)
    assert sent.startswith("Against 1 hand-corrected plate (5 plaques), the Current (corrected) "
                           "engine of Plaque Toolkit %s detected plaques with precision" % __version__)


def test_validate_with_no_label_files_has_no_zero_row(tmp_path):
    from app import validate as V
    (tmp_path / "run_metadata.json").write_text("{}")
    res = V.validate(str(tmp_path), modes=("current",))
    assert res["n_label_files"] == 0 and res["per_mode_df"].empty and res["per_plate_df"].empty


@pytest.fixture
def validate_tab(qt, monkeypatch):
    from PySide6.QtCore import QThreadPool
    from PySide6.QtWidgets import QMainWindow
    from app import ui as appui
    monkeypatch.setattr(appui.engine_api, "precise_available", lambda: (False, "torch is not installed."))
    win = QMainWindow()
    tab = appui.ValidateTab(QThreadPool())
    win.setCentralWidget(tab); qt.addWidget(win)
    tab._test_window = win
    yield tab
    win.close()


def test_unavailable_precise_is_unticked_disabled_and_stays_disabled(validate_tab):
    cb = validate_tab.mode_checks["precise"]
    assert not cb.isChecked() and not cb.isEnabled() and "torch is not installed" in cb.toolTip()
    validate_tab._set_busy(True); validate_tab._set_busy(False)
    assert not cb.isEnabled() and validate_tab.mode_checks["current"].isEnabled()


def test_available_precise_stays_offered(qt, monkeypatch):
    from PySide6.QtCore import QThreadPool
    from app import ui as appui
    monkeypatch.setattr(appui.engine_api, "precise_available", lambda: (True, ""))
    tab = appui.ValidateTab(QThreadPool()); qt.addWidget(tab)
    assert tab.mode_checks["precise"].isEnabled() and tab.mode_checks["precise"].isChecked()


def test_validate_tab_warns_when_the_folder_has_no_label_files(validate_tab, tmp_path, no_dialogs):
    (tmp_path / "run_metadata.json").write_text("{}")
    validate_tab.labels.setText(str(tmp_path))
    validate_tab._run()
    assert no_dialogs and no_dialogs[0][0] == "warning" and no_dialogs[0][1] == "No label files"
    assert "1 other JSON file skipped" in no_dialogs[0][2]
    assert validate_tab.mode_model.rowCount() == 0 and not validate_tab.save_btn.isEnabled()


def test_validate_tab_run_status_sentence_and_csv(validate_tab, qt, neutral_plate_tif, tmp_path, no_dialogs):
    import pandas as pd
    d = _label_folder(tmp_path, neutral_plate_tif)
    validate_tab.labels.setText(str(d))
    validate_tab._run()
    qt.waitUntil(lambda: validate_tab._res is not None, timeout=120_000)
    assert validate_tab.status.text().startswith("Scored 3 plates x 1 engine; 2 failed (see the last column).")
    from app import __version__
    assert "Plaque Toolkit %s" % __version__ in validate_tab.sentence.text()
    out = validate_tab._save(str(tmp_path / "res.csv"))
    assert out == (str(tmp_path / "res_per_engine.csv"), str(tmp_path / "res_per_plate.csv"))
    assert len(pd.read_csv(out[1])) == 3 and len(pd.read_csv(out[0])) == 1


# =========================================================================== 7. DA-F11 table display
def test_table_shows_4_significant_digits_but_sorts_and_copies_raw_values(qt):
    import pandas as pd
    from PySide6.QtCore import Qt
    from app.widgets import PandasTableModel, NumericSortProxy, CopyableTableView
    df = pd.DataFrame({"pair": ["A-B", "A-C", "B-C"], "p_adj": [0.0004, 0.0234567, float("nan")],
                       "f1": [0.3751082334679884, 12.5, 15234.7], "tp": [5, 12, 3]})
    m = PandasTableModel(); m.set_dataframe(df)
    shown = [[m.data(m.index(r, c), Qt.DisplayRole) for c in range(4)] for r in range(3)]
    assert shown == [["A-B", "< 0.001", "0.3751", "5"], ["A-C", "0.02346", "12.5", "12"],
                     ["B-C", "", "15235", "3"]]
    proxy = NumericSortProxy(); proxy.setSourceModel(m)
    view = CopyableTableView(); view.setModel(proxy); qt.addWidget(view)
    proxy.sort(2, Qt.DescendingOrder)
    assert [proxy.data(proxy.index(r, 0)) for r in range(3)] == ["B-C", "A-C", "A-B"]
    text, n = view.selection_tsv(all_rows=True)
    lines = text.split("\r\n")
    assert n == 3 and lines[0] == "pair\tp_adj\tf1\ttp"
    assert lines[1] == "B-C\t\t15234.7\t3" and lines[3] == "A-B\t0.0004\t0.3751082334679884\t5"


# =========================================================================== 8. DA-F23 About + Help viewer
HELP_MD = ["USER_GUIDE.md", "VALIDATION_GUIDE.md", "HOW_IT_WAS_BUILT.md", "ENGINES.md",
           "PUBLICATION.md", "CREDITS_AND_LINEAGE.md", "LICENSING.md"]


def test_about_lists_the_seven_real_tabs_the_legend_key_and_only_real_menu_items(qt):
    import re
    from app import ui as appui
    win = appui.MainWindow(); qt.addWidget(win)
    from PySide6.QtWidgets import QLabel
    body = next(l for l in win.about_tab.findChildren(QLabel) if l.objectName() == "AboutBody").text()
    tabs = [win.tabs.tabText(i).strip() for i in range(win.tabs.count())]
    listed = re.findall(r"<li><b>([^<]+)</b> —", body.split("<p><b>The tabs</b></p>")[1].split("</ul>")[0])
    assert listed == tabs
    assert "Legend key" in body and "legend text starter" in body and "Place key on figure" in body
    assert "interactive guide" not in body
    from PySide6.QtWidgets import QMenu
    help_menu = next(m for m in win.menuBar().findChildren(QMenu) if m.title() == "&Help")
    items = {a.text() for a in help_menu.actions()}
    footer = body.split("Full guides live in the <b>Help</b> menu (")[1].split("; and more")[0]
    for name in footer.replace("&amp;", "&").split("; "):
        assert name in items, name


@pytest.mark.parametrize("doc", HELP_MD)
def test_every_table_of_contents_link_in_the_help_markdown_finds_its_heading(qt, doc):
    import re
    from app import ui as appui
    v = appui.DocViewer(doc); qt.addWidget(v)
    text = open(appui._resolve_doc(doc)[0], encoding="utf-8").read()
    for frag in re.findall(r"\]\(#([^)\s]+)\)", text):
        assert v._find_anchor(frag) is not None, frag


def test_toc_link_scrolls_and_relative_doc_link_opens_in_the_viewer(qt):
    from PySide6.QtCore import QUrl
    from app import ui as appui
    v = appui.DocViewer("USER_GUIDE.md"); qt.addWidget(v)
    v.resize(900, 600); v.show()
    sb = v.browser.verticalScrollBar()
    assert sb.value() == 0
    v._on_anchor(QUrl("#10-special-modes"))                  # a shortened slug in the shipped TOC
    assert sb.value() > 0
    block = v.browser.document().findBlock(v._find_anchor("10-special-modes"))
    assert block.text().startswith("10. Special modes")
    n0 = len(appui._DOC_VIEWERS)
    v._on_anchor(QUrl("VALIDATION_GUIDE.md"))
    assert len(appui._DOC_VIEWERS) == n0 + 1
    opened = appui._DOC_VIEWERS[-1]
    assert opened._path.endswith("VALIDATION_GUIDE.md") and opened.browser.toPlainText()
    opened.close()


def test_cli_unknown_column_is_one_line_listing_the_numeric_columns_exit_2(capsys):
    data = os.path.join(ROOT, "validation", "paired_toolkit_vs_fiji.csv")
    with pytest.raises(SystemExit) as ex:
        cli_ag.main([data, "--tool", "diam_toolkit_mm", "--out", os.devnull])
    assert ex.value.code == 2
    err = capsys.readouterr().err.strip()
    assert "\n" not in err and "Traceback" not in err
    assert err == ("agreement.py: error: --tool 'diam_toolkit_mm' is not a numeric column of "
                   "paired_toolkit_vs_fiji.csv. Numeric columns: plaque_id, area_tool_mm2, "
                   "area_fiji_mm2, diam_tool_mm, diam_fiji_mm.")


def test_compare_vs_fiji_limits_equal_the_agreement_tab_limits():
    """Both report bias +/- 1.96 SD (CT-R1 follow-up). The dialog works on 3-decimal pairs and
    rounds bias/SD to 4 decimals, so agreement is checked to that precision and as displayed."""
    from app import fiji_match
    app_df = _synthetic_plate(n=15)
    fj = _fiji_pixels(app_df, scale_px_per_mm=1.0, deg=0, shift=(0, 0), drop=0)
    fiji_df = fiji_match.load_fiji_results(_write(fj))
    res = fiji_match.match(app_df, fiji_df, align="none")
    p, sm = res["paired"], res["summary"]
    assert sm["n_matched"] == 15
    s = ap.compute(p["APP_DIAM_MM"].tolist(), p["FIJI_DIAM_MM"].tolist())
    assert sm["loa_low_mm"] == pytest.approx(s["loa_lo"], abs=3e-4)
    assert sm["loa_high_mm"] == pytest.approx(s["loa_hi"], abs=3e-4)
    assert "%+.3f" % sm["loa_low_mm"] == "%+.3f" % s["loa_lo"]
    assert "%+.3f" % sm["loa_high_mm"] == "%+.3f" % s["loa_hi"]


def _write(df):
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".csv"); os.close(fd)
    df.to_csv(path, index=False)
    return path
