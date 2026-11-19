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


@pytest.fixture
def qt(qtbot):
    pytest.importorskip("PySide6")
    return qtbot


@pytest.fixture
def no_dialogs(monkeypatch):
    pytest.importorskip("PySide6")
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
    for name in ("report_sentence", "icc_ci", "compute", "loa_multiplier", "full_stats"):
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


def test_small_n_limits_of_agreement_are_prediction_limits_with_the_b_and_a_1999_ci():
    rng = np.random.default_rng(5)
    inside, sims, n = 0, 3000, 5
    for _ in range(sims):
        d = rng.normal(0, 1, n)
        k = ap.loa_multiplier(n)
        inside += abs(rng.normal() - d.mean()) <= k * d.std(ddof=1)
    assert 0.93 <= inside / sims <= 0.97                 # +/-1.96 SD gave ~0.85 here
    assert ap.loa_multiplier(5) == pytest.approx(st.t.ppf(.975, 4) * math.sqrt(1.2))
    assert ap.loa_multiplier(20) == 1.96 and ap.loa_multiplier(100) == 1.96
    hw = ap._loa_ci_halfwidth(1.0, 100)
    assert hw == pytest.approx(st.t.ppf(.975, 99) * math.sqrt(1 / 100 + 1.96 ** 2 / 198), rel=1e-12)
    s = ap.full_stats(EX_TOOL, EX_FIJI)                  # n = 15 -> t-based limits, said so
    k = st.t.ppf(.975, 14) * math.sqrt(1 + 1 / 15)
    assert s["loa_hi"] == pytest.approx(s["bias"] + k * s["sd"], rel=1e-12)
    assert "t-based prediction limits, as n < 20" in ap.report_sentence(s)


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
    assert "The difference did not depend on plaque size" in a and "each limit ±" in a


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
