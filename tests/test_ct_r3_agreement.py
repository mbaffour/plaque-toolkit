"""CT-R3 method agreement (tool vs manual tracing): the command line (plaque_stats/agreement/
agreement.py), the desktop tab (app/agreement.py, app/fiji_*.py, AgreementTab) and the web app
(plaque_stats/agreement/app_py.py) share one engine. One test (or a few) per finding F1..F10 of the
round-3 click-through; the fixtures are the tester's own files (tests/fixtures/ct_r3_agree/).
"""
import contextlib
import io
import os
import re
import sys

import numpy as np
import pandas as pd
import pytest

import test_ct_r1_web as R1
from test_ct_r1_web import browser_page, _idle, _download      # noqa: F401  (fixture + helpers)

B, ag = R1.B, R1.ag
ROOT = R1.ROOT
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from app import agreement as dag          # noqa: E402  the desktop copy of the shared core

FX = os.path.join(ROOT, "tests", "fixtures", "ct_r3_agree")
SHIPPED = os.path.join(ROOT, "validation", "paired_toolkit_vs_fiji.csv")


def _fx(name):
    return os.path.join(FX, name + ".csv")


def _stats(path, tool="toolkit_mm", manual="manual_mm"):
    df, _ = ag.read_paired(path)
    t, m, _rows, _drop = ag.pair_values(df, tool, manual)
    return df, ag.full_stats(t, m)


def _sentence(name, what="plaque diameters"):
    cols = ("diam_tool_mm", "diam_fiji_mm") if name == "tiny_plaques" else ("toolkit_mm", "manual_mm")
    return ag.report_sentence(_stats(_fx(name), *cols)[1], "mm", what)


def _run_cli(tmp_path, path, **kw):
    a = vars(ag.build_args().parse_args([path, "--out", str(tmp_path / "o")]))
    a["formats"] = ["png"]
    a.update(kw)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        s = ag.run(a)
    rep = [f for f in os.listdir(tmp_path / "o") if f.endswith(".md")][0]
    csv = [f for f in os.listdir(tmp_path / "o") if f.startswith("agreement_stats")][0]
    return s, buf.getvalue(), (tmp_path / "o" / rep).read_text(encoding="utf-8"), \
        (tmp_path / "o" / csv).read_text(encoding="utf-8")


def _sent_of_report(rep):
    return [ln for ln in rep.splitlines() if ln.startswith("> ")][0][2:]


# =========================================================================== F2: near-zero mean
@pytest.mark.parametrize("name", ["nearzero", "agree_negative"])
def test_f2_no_percentage_over_a_near_zero_mean_in_all_three_front_ends(name, tmp_path):
    df, s = _stats(_fx(name))
    assert np.isnan(s["pct_bias"])                              # the engine's rule (was the web app's)
    cli = ag.report_sentence(s, "mm", "diameters")
    desk = dag.report_sentence(dag.full_stats(s["tool"], s["fiji"]), "mm", "diameters")
    web = B.sentence_of(B.compute(df, "toolkit_mm", "manual_mm"), "mm", "diameters",
                        "Plaque Toolkit", "Fiji / ImageJ")
    assert cli == desk == web
    assert not re.search(r"\(-?\d+\.\d%[;)]", cli)              # no "(35.3%;" / "(-15304.7%;"
    s2, out, rep, csv = _run_cli(tmp_path, _fx(name))
    assert "n/a: mean near zero" in rep and "n/a: mean near zero" in out
    assert _sent_of_report(rep) == ag.report_sentence(s2, "mm", "diameters")
    assert not re.search(r"\|\s*mean bias[^|]*\|[^|]*\d%\)", rep)
    row = pd.read_csv(io.StringIO(csv)).iloc[0]
    assert np.isnan(row["pct_bias"])                           # blank in the CSV, not -15304.7


def test_f2_shipped_validation_percentage_is_unchanged():
    _, s = _stats(SHIPPED, "diam_tool_mm", "diam_fiji_mm")
    assert s["pct_bias"] == pytest.approx(-1.8, abs=0.05)
    assert "(-1.8%;" in ag.report_sentence(s, "mm", "diameters")


# =========================================================================== F6: verb = interval grade
BASE = dict(n=30, r=0.99, r2=0.98, pearson_p=1e-9, icc=0.9, ccc=0.9, bias=0.01, pct_bias=1.0, t_p=0.5,
            loa_lo=-0.1, loa_hi=0.12, slope=1.0, sd=0.05, loa_ci_halfwidth=0.02)


@pytest.mark.parametrize("lo,hi,verb", [(0.92, 0.99, "agreed closely with"), (0.80, 0.99, "agreed well with"),
                                        (0.60, 0.99, "agreed moderately with"),
                                        (0.20, 0.99, "did not agree reliably with")])
def test_f6_the_verb_is_the_band_of_the_interval_lower_limit(lo, hi, verb):
    for mod in (ag, dag):
        s = dict(BASE, icc=0.95, icc_lo=lo, icc_hi=hi)
        sent = mod.report_sentence(s, "mm", "diameters")
        assert (" %s " % verb) in sent
        assert "agreed well with" not in sent or verb == "agreed well with"


def test_f6_no_verb_that_contradicts_the_printed_interval():
    for name in ("offset02", "propbias115", "n6"):
        sent = _sentence(name)
        m = re.search(r"\(95% CI (-?[\d.]+) to (-?[\d.]+)\): ([a-z]+(?: to [a-z]+)?) agreement", sent)
        low = m.group(3).split(" to ")[0]
        want = {"excellent": "agreed closely", "good": "agreed well", "moderate": "agreed moderately",
                "poor": "did not agree reliably"}[low]
        head = sent.split(":")[0]
        assert want.replace("agreed", "appeared to agree") in head or want in head, (name, head)
    assert "agreed well" not in _sentence("offset02")
    assert "agreed closely" not in _sentence("propbias115")
    assert "appeared to agree closely" not in _sentence("n6")


def test_f6_soft_wording_for_5_to_9_pairs_and_no_verb_below_5():
    s6 = _sentence("n6")
    assert s6.startswith("With only 6 pairs (too few for precise estimates), plaque diameters measured "
                         "with Plaque Toolkit appeared to agree well with")
    for n in ("n3", "n4"):
        sent = _sentence(n)
        assert "too few pairs for a verdict" in sent
        assert not re.search(r"agree|did not|correlated", sent.split(": ", 1)[0])


# =========================================================================== F7: wording a statistician signs
def test_f7_a_significant_proportional_bias_is_in_the_opening_with_the_verb():
    sent = _sentence("propbias115")
    opening = sent.split(": very strongly correlated")[0]
    assert "a proportional bias (Bland-Altman slope +0.140, p < 0.001)" in opening
    assert "(n = 30)" in opening and "Fiji / ImageJ" in opening


def test_f7_a_large_systematic_bias_is_in_the_opening_and_a_small_one_is_not():
    # the limits of agreement exclude zero and the bias is significant
    assert "a systematic bias of +0.150 mm (the limits of agreement exclude zero)" in \
        _sentence("propbias115").split(": very strongly")[0]
    # the shipped validation: significant (n = 100) but the limits include zero: no qualification
    _, s = _stats(SHIPPED, "diam_tool_mm", "diam_fiji_mm")
    sent = ag.report_sentence(s, "mm", "diameters")
    assert sent.split(": very strongly")[0].endswith("(n = 100)")


def test_f7_a_non_significant_slope_is_no_evidence_with_the_low_power_caveat_below_20_pairs():
    n15 = _sentence("n15")
    assert "There is no evidence of a proportional bias (Bland-Altman slope +0.002, p = 0.936; with 15 " \
           "pairs there is little power to detect one)." in n15
    n19 = ag.report_sentence(ag.full_stats(*_pairs(19)), "mm", "diameters")
    n20 = ag.report_sentence(ag.full_stats(*_pairs(20)), "mm", "diameters")
    assert "with 19 pairs there is little power" in n19
    assert "little power" not in n20 and "There is no evidence of a proportional bias" in n20
    assert "No proportional bias was detected" not in n15 + n19 + n20


def _pairs(n, seed=4, lo=0.6, hi=2.6):
    r = np.random.default_rng(seed)
    ref = r.uniform(lo, hi, n)
    return list(ref + r.normal(0, 0.1, n)), list(ref)


def test_f7_a_narrow_size_range_says_a_proportional_bias_could_not_be_seen():
    sent = _sentence("tiny_plaques")
    assert re.search(r"The sizes span a narrow range \(0\.380 to 0\.477 mm\), so a proportional bias "
                     r"could not be seen\.", sent)
    wide = ag.report_sentence(ag.full_stats(*_pairs(30)), "mm", "diameters")
    assert "narrow range" not in wide


def test_f7_below_5_pairs_only_descriptive_numbers():
    for name, n in (("n3", 3), ("n4", 4)):
        s = _stats(_fx(name))[1]
        for mod in (ag, dag):
            sent = mod.report_sentence(s, "mm", "plaque diameters")
            assert "mean bias" in sent and "SD of the differences" in sent and "differences from" in sent
            for banned in ("Pearson", "p =", "p <", "ICC(A,1) =", "CCC", "slope", "prediction", "agreed"):
                assert banned not in sent.split(" Pearson r, the ICC")[0], (name, banned)
            assert ("(n = %d)" % n) in sent


def test_f7_zero_spread_says_the_methods_differ_by_a_constant():
    base = [0.8, 1.1, 1.5, 1.9, 2.4, 2.2, 1.3]
    exact = ag.report_sentence(ag.full_stats([v + 0.2 for v in base], base), "mm", "diameters")
    near = _sentence("offset02")
    for sent in (exact, near):
        assert "the two methods differ by a constant +0.200 mm" in sent
        assert "limits of agreement of" not in sent and "each limit" not in sent
        assert "±0.000" not in sent and "+0.200 to +0.200" not in sent
    assert "a constant offset of +0.200 mm" in near.split(": very strongly")[0]


def test_f7_intervals_are_a_to_b_never_a_dash():
    for name in ("n15", "n6", "propbias115", "tiny_plaques"):
        sent = _sentence(name)
        assert not re.search(r"\d-\d|\d–\d", sent), (name, re.findall(r".{12}\d-\d.{8}", sent))
    assert "95% CI -0.013 to 0.981" in _sentence("propbias115")
    s = _stats(_fx("n15"))[1]
    assert ("95%% CI %.3f to %.3f" % (s["icc_lo"], s["icc_hi"])) in ag._icc_ci_text(s)


def test_f7_never_minus_zero_in_the_sentence_the_cli_report_or_the_tables(tmp_path):
    s = dict(BASE, bias=-0.0001, loa_lo=-0.2, loa_hi=0.2, slope=-0.0004, intercept=-0.0002, r=-0.0002,
             r2=0.0, icc=-0.0003, icc_lo=-0.0004, icc_hi=0.4, ccc=-0.0001, pct_bias=-0.03,
             ba_slope=-0.00004, ba_slope_p=0.9, pred_lo=float("nan"), pred_hi=float("nan"))
    for mod in (ag, dag):
        sent = mod.report_sentence(s, "mm", "diameters")
        assert not re.search(r"-0\.0+(?!\d)", sent), re.findall(r".{20}-0\.0+.{5}", sent)
    # the CLI report on the tester's negzero file and the web table
    s2, out, rep, _ = _run_cli(tmp_path, _fx("negzero"))
    assert not re.search(r"-0\.0+(?!\d)", rep + out)
    assert not re.search(r"-0\.0+(?!\d)", B.report_table_md(B.compute(_stats(_fx("negzero"))[0], "toolkit_mm",
                                                                      "manual_mm"), "mm"))


def test_f7_cli_table_below_5_pairs_has_no_r_icc_or_slope(tmp_path):
    s, out, rep, _ = _run_cli(tmp_path, _fx("n4"))
    row = {k.strip(): v.strip() for k, v in
           (r.strip("|").split("|", 1) for r in rep.splitlines() if r.startswith("| ") and "---" not in r)}
    for k in ("Pearson r (p)", "ICC(A,1)", "Lin's CCC", "proportional bias (difference ~ mean)"):
        assert row[k].startswith("n/a (needs 5 pairs)"), (k, row[k])
    web = dict(B.report_rows(B.compute(_stats(_fx("n4"))[0], "toolkit_mm", "manual_mm"), "mm"))
    assert web["ICC(A,1) [95% CI]"].startswith("n/a (needs 5 pairs)")


# =========================================================================== F3 / F9 desktop tab
import test_ct_r1_agreement_validate as V1                                  # noqa: E402
from test_ct_r1_agreement_validate import agreement_tab, qt                 # noqa: E402,F401


def _fill(tab, tool, fiji):
    tab.tool_in.setPlainText(tool)
    tab.fiji_in.setPlainText(fiji)
    tab._compute()


def test_f3_parse_values_keeps_a_blank_line_inside_the_column_as_a_missing_value():
    vals, notes = dag.parse_values("1.0\n1.5\n\n2.0\n2.5\n")
    assert vals == [1.0, 1.5, None, 2.0, 2.5]            # position kept; the trailing blank line ignored
    assert any("1 blank line inside the column read as missing value" in n for n in notes)
    assert dag.parse_values("\n\n1.0\n2.0\n\n\n")[0] == [1.0, 2.0]
    assert dag.parse_values("Area\n1.0\n\n2.0")[0] == [1.0, None, 2.0]


def test_f3_a_blank_in_each_box_drops_those_pairs_and_counts_them(agreement_tab):
    """The tester's case: tool blank in row 3, Fiji blank in row 5: 7 lines each, 5 pairs, said so."""
    tab = agreement_tab
    tool = "1.0\n1.5\n\n2.0\n2.6\n3.1\n0.7"
    fiji = "1.1\n1.4\n1.9\n2.1\n\n3.0\n0.8"
    _fill(tab, tool, fiji)
    assert tab.err.text() == "", tab.err.text()
    s = tab._last[0]
    assert s["n"] == 5
    assert s["tool"] == [1.0, 1.5, 2.0, 3.1, 0.7] and s["fiji"] == [1.1, 1.4, 2.1, 3.0, 0.8]   # still paired by row
    assert "2 pairs dropped: a value missing" in tab.parse_notes.text()
    assert "2 pairs dropped: a value missing" in tab.report.toPlainText()
    assert tab.preview.rowCount() == 7 and tab.preview.item(2, 0).text() == ""


def test_f3_trailing_blank_lines_are_ignored(agreement_tab):
    tab = agreement_tab
    _fill(tab, "1.0\n1.6\n2.2\n3.0\n\n\n", "1.1\n1.5\n2.3\n2.9\n")
    assert tab.err.text() == "" and tab._last[0]["n"] == 4
    assert "dropped" not in tab.parse_notes.text()


def test_f9_three_vs_two_values_gets_the_unequal_counts_message(agreement_tab):
    tab = agreement_tab
    _fill(tab, "1.0\n1.6\n2.2", "1.1\n1.5")
    assert "3 Plaque Toolkit vs 2 Fiji / ImageJ" in tab.err.text()
    assert "Enter at least 3" not in tab.err.text()
    _fill(tab, "1.0\n1.6\n2.2\n3.3\n4.0\n5.0\n6.1", "1.1\n1.5\n2.3\n3.2\n4.1\n5.1")
    assert "7 Plaque Toolkit vs 6 Fiji / ImageJ" in tab.err.text()
    _fill(tab, "1.0\n1.6", "1.1\n1.5")                      # equal but too few: the old message
    assert "Enter at least 3" in tab.err.text()


def test_f9_the_desktop_sentence_is_the_engines_with_the_clis_opening(agreement_tab, tmp_path):
    tab = agreement_tab
    tab._example()
    sent = tab.report.toPlainText().split("\n\nNote:")[0]
    s = ag.full_stats(tab._last[0]["tool"], tab._last[0]["fiji"])
    assert sent == ag.report_sentence(s, "mm", ag.DEFAULT_WHAT)
    assert sent.startswith("Diameters measured with Plaque Toolkit ")
    # the same opening as the command line and the web app for the same numbers
    web = B.sentence_of(s, "mm", B.DIAM_WHAT, "Plaque Toolkit", "Fiji / ImageJ")
    assert sent == web


def test_f7_desktop_chips_show_no_r_icc_slope_below_5_pairs(agreement_tab):
    tab = agreement_tab
    _fill(tab, "1.0\n1.6\n2.2\n3.0", "1.1\n1.5\n2.3\n2.9")
    assert tab.err.text() == ""
    for k in ("icc", "r", "slope"):
        assert tab._metrics[k].text() == "—"
    assert tab._metrics["bias"].text() != "—" and "Pearson r =" not in tab.report.toPlainText()


def test_f11_the_legend_text_starter_wraps_and_is_reachable_at_1024x700(qt):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QPlainTextEdit, QScrollArea
    from app import ui as appui
    from PySide6.QtWidgets import QMainWindow
    win = QMainWindow()
    sa = appui._scrollable(appui.AgreementTab())          # how MainWindow hosts the tab
    win.setCentralWidget(sa)
    qt.addWidget(win)
    win.resize(1024, 640)                                 # a 1024x700 window minus the tab bar / status bar
    win.show()
    tab = sa.widget()
    tab._example()
    from PySide6.QtWidgets import QApplication
    QApplication.processEvents()
    assert isinstance(tab.key_text, QPlainTextEdit) and tab.key_text.isReadOnly()
    assert tab.key_text.lineWrapMode() == QPlainTextEdit.WidgetWidth
    assert tab.key_text.toPlainText().startswith("within the limits of agreement (")
    assert tab.key_text.height() >= 50
    sa.ensureWidgetVisible(tab.key_text)
    vp = sa.viewport()
    top = tab.key_text.mapTo(vp, tab.key_text.rect().topLeft()).y()
    bottom = tab.key_text.mapTo(vp, tab.key_text.rect().bottomLeft()).y()
    assert 0 <= top and bottom <= vp.height() + 2, (top, bottom, vp.height())
    assert tab.key_copy_btn.isVisible()
    win.close()


# =========================================================================== F9 Fiji dialog
def _fiji_dialog(qt, n_plaques):
    from app import fiji_dialog
    app_df = V1._synthetic_plate(n=n_plaques)
    dlg = fiji_dialog.FijiCompareDialog(app_df, calibrated=True)
    qt.addWidget(dlg)
    dlg.align.setCurrentIndex(1)
    return dlg, app_df


def _choose(dlg, monkeypatch, path):
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(path), "")))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: None))
    dlg._choose()


def test_f9_fiji_dialog_says_when_a_second_file_fails_and_the_old_result_stays(qt, tmp_path, monkeypatch):
    dlg, app_df = _fiji_dialog(qt, 27)
    good = tmp_path / "good.csv"
    V1._fiji_pixels(app_df).to_csv(good, index=False)
    _choose(dlg, monkeypatch, good)
    assert dlg.result is not None and not dlg.fail_note.isVisibleTo(dlg)
    bad = tmp_path / "bad.csv"
    pd.DataFrame({"a": [1, 2], "b": [3, 4]}).to_csv(bad, index=False)       # no Centroid / Area columns
    _choose(dlg, monkeypatch, bad)
    note = dlg.fail_note.text()
    assert dlg.fail_note.isVisibleTo(dlg) and "Could not use bad.csv" in note
    assert "still the result for good.csv" in note and "NOT for this file" in note
    assert dlg.result is not None and dlg.file_lbl.text() == "good.csv"
    _choose(dlg, monkeypatch, good)                                          # a good file clears the note
    assert not dlg.fail_note.isVisibleTo(dlg)


def test_f9_fiji_dialog_lists_at_most_ten_unmatched_indices(qt, tmp_path, monkeypatch):
    dlg, app_df = _fiji_dialog(qt, 27)
    rng = np.random.default_rng(9)
    junk = pd.DataFrame({"X": rng.uniform(0, 85, 41), "Y": rng.uniform(0, 85, 41), "Area": 1.0})
    path = tmp_path / "junk.csv"
    junk.to_csv(path, index=False)
    _choose(dlg, monkeypatch, path)
    txt = dlg.summary.text()
    assert re.search(r"App plaques with no Fiji match: (\d+, ){9}\d+ and \d+ more\.", txt), txt
    assert re.search(r"Fiji rows with no app match: (\d+, ){9}\d+ and \d+ more\.", txt), txt
    assert dlg._idx_text([1, 2, 3]) == "1, 2, 3" and dlg._idx_text(range(10)).count(",") == 9
    assert dlg._idx_text(range(11)).endswith("and 1 more")


def test_f9_fiji_summary_has_the_few_pairs_caveat_below_20_pairs(qt, tmp_path, monkeypatch):
    for n_app, expect in ((12, True), (27, False)):
        dlg, app_df = _fiji_dialog(qt, n_app)
        path = tmp_path / ("res%d.csv" % n_app)
        V1._fiji_pixels(app_df, drop=0).to_csv(path, index=False)
        _choose(dlg, monkeypatch, path)
        s = dlg.result["summary"]
        txt = dlg.summary.text()
        assert ("With only %d pairs, a new difference is expected within" % s["n_matched"] in txt) is expect
        if expect:
            assert "(95% prediction interval)" in txt


# =========================================================================== F8: one reader
def test_f8_read_paired_reads_semicolon_decimal_comma_and_text():
    df, note = ag.read_paired(_fx("semicolon_comma"))
    assert list(df.columns) == ["plaque_id", "toolkit_mm", "manual_mm"]
    assert df["toolkit_mm"].iloc[0] == pytest.approx(1.562) and "semicolon-separated" in note
    assert "decimal commas" in note
    df2, _ = ag.read_paired("a;b\n1,5;2,5\n2,5;2,6\n3,5;3,4\n", name="pasted")      # the TEXT of a file
    assert df2["a"].tolist() == [1.5, 2.5, 3.5]
    t, m, rows, drop = ag.pair_values(df, "toolkit_mm", "manual_mm")
    assert (rows, drop) == (len(df), 0) and len(t) == len(df)
    # the web app calls the engine's reader (one implementation)
    for fn in ("read_paired", "guess_columns"):          # the web app's names ARE the engine's functions
        assert getattr(B, fn).__code__.co_filename == getattr(ag, fn).__code__.co_filename
        assert getattr(B, fn).__code__.co_filename.endswith(os.path.join("agreement", "agreement.py"))


def test_f8_cli_reads_a_semicolon_file_and_reports_dropped_rows(tmp_path):
    s, out, rep, _ = _run_cli(tmp_path, _fx("semicolon_comma"))
    assert "columns: tool = 'toolkit_mm'" in out and s["n"] >= 3
    # missing values: the same words on stdout, in the report and in the web app
    df, _ = ag.read_paired(_fx("missing3"))
    _t, _m, rows, drop = ag.pair_values(df, "toolkit_mm", "manual_mm")
    assert drop >= 1
    msg = "%d of %d rows dropped: a value missing or not a number" % (drop, rows)
    assert ag.drop_text(drop, rows) == msg
    tmp2 = tmp_path / "m"
    tmp2.mkdir()
    s2, out2, rep2, _ = _run_cli(tmp2, _fx("missing3"))
    assert msg + "." in out2 and msg in rep2 and s2["n"] == rows - drop
    assert B.compute(df, "toolkit_mm", "manual_mm")["_dropped"] == drop


# =========================================================================== F10: one role guess
def test_f10_unhinted_columns_are_tool_then_reference_in_file_order_everywhere(tmp_path):
    df, _ = ag.read_paired(_fx("unnamed2"))                    # x, y: no hint at all
    assert ag.guess_columns(df) == ("x", "y") == B.guess_columns(df)
    s, out, rep, _ = _run_cli(tmp_path, _fx("unnamed2"))
    assert "tool = 'x', manual/reference = 'y'" in out
    web = B.compute(df, *B.guess_columns(df))
    assert np.sign(web["bias"]) == np.sign(s["bias"]) and web["bias"] == pytest.approx(s["bias"])


def test_f10_ids_are_never_guessed_and_hints_still_win():
    df, _ = ag.read_paired(_fx("agree_unnamed"))               # plaque_id, x, y
    assert ag.guess_columns(df) == ("x", "y")
    df2, _ = ag.read_paired(_fx("idcol_ab"))                   # plaque_id, A, B
    assert ag.guess_columns(df2) == ("A", "B")
    d3 = pd.DataFrame({"hand": [1.0, 2.0, 3.1, 4.0], "auto": [1.1, 2.0, 3.0, 4.2]})   # file order is reversed
    assert ag.guess_columns(d3) == ("auto", "hand")
    # --tool / --manual given: the other role is the remaining column
    assert ag.guess_columns(df, tool="y") == ("y", "x") and ag.guess_columns(df, manual="y") == ("x", "y")


# =========================================================================== F1 / F4 / F5: web gates
def test_f1_convert_area_on_columns_that_are_not_areas_is_a_blocking_mixed_state():
    d = pd.read_csv(_fx("n15"))                                # toolkit_mm / manual_mm: lengths in mm
    msg = B.convert_problem(d, "toolkit_mm", "manual_mm", True)
    assert "“Convert area” is ticked" in msg and "toolkit_mm" in msg and "downloads stay off" in msg
    assert B.convert_problem(d, "toolkit_mm", "manual_mm", False) == ""
    assert B.downloads_blocked("toolkit_mm", "manual_mm", False, d, True)
    assert not B.downloads_blocked("toolkit_mm", "manual_mm", True, d, True)              # Compare anyway
    assert not B.downloads_blocked("toolkit_mm", "manual_mm", False, d, False)
    ar = pd.DataFrame({"area_tool_mm2": [1.0, 2.0, 3.0], "area_fiji_mm2": [1.1, 2.1, 2.9]})
    assert B.convert_problem(ar, "area_tool_mm2", "area_fiji_mm2", True) == ""           # real areas pass
    neg = pd.DataFrame({"tool": [1.0, -2.0, 3.0], "ref": [1.1, 2.1, 2.9]})               # an area cannot be < 0
    assert "negative" in B.convert_problem(neg, "tool", "ref", True)


def test_f5_the_compared_line_never_says_converted_from_area_for_a_diameter():
    for name in ("DIAMETER_MM", "fiji_diam", "toolkit_mm"):
        assert "converted from area" not in B.quantity_text(name, True, "mm")
        assert "as if it were an area" in B.quantity_text(name, True, "mm")
    assert "converted from area" in B.quantity_text("AREA_MM2", True, "mm")
    assert "converted from area" in B.quantity_text("tool_area", True, "mm")


def _port_9040(monkeypatch):
    """The web test servers of this file use ports 9040-9059 only."""
    import socket

    def free():
        for p in range(9040, 9060):
            with socket.socket() as so:
                try:
                    so.bind(("127.0.0.1", p))
                    return p
                except OSError:
                    continue
        raise RuntimeError("no free port in 9040-9059")
    monkeypatch.setattr(R1, "_free_port", free)


_OFF = "() => [...document.querySelectorAll('a.shiny-download-link.ct-off')].length"


def test_f1_f4_browser_gates_reset_on_new_file_example_and_pair_change(browser_page, tmp_path, monkeypatch):
    _port_9040(monkeypatch)
    page, srv = browser_page(os.path.join(R1.AG_DIR, "app_py.py"), tmp_path)
    n15 = _fx("n15")
    page.set_input_files("#file", n15); _idle(page, 3)
    page.set_checked("#convert_area", True); _idle(page, 2)               # diameters ticked as areas
    page.wait_for_function(_OFF + " > 0", timeout=20000)
    assert "“Convert area” is ticked" in page.inner_text("#messages")
    assert "converted from area" not in page.inner_text("#compared_line")
    page.set_checked("#compare_anyway", True); _idle(page, 2)
    page.wait_for_function(_OFF + " === 0", timeout=20000)
    page.set_input_files("#file", _fx("n20")); _idle(page, 3)             # a NEW file: both ticks are gone
    assert not page.is_checked("#convert_area")
    assert page.evaluate(_OFF) == 0
    page.set_checked("#convert_area", True); _idle(page, 2)
    page.click("#load_example"); _idle(page, 3)                           # "Load example data" too
    assert not page.is_checked("#convert_area")
    # F4: a stale "Compare anyway" never carries over to the same mixed pair
    ad = tmp_path / "agree_area_diam.csv"
    ad.write_text(open(_fx("agree_area_diam")).read())
    page.set_input_files("#file", str(ad)); _idle(page, 3)
    page.select_option("#tool", "AREA_MM2"); _idle(page, 2)
    page.wait_for_function(_OFF + " > 0", timeout=20000)
    page.set_checked("#compare_anyway", True); _idle(page, 2)
    page.wait_for_function(_OFF + " === 0", timeout=20000)
    page.select_option("#tool", "DIAMETER_MM"); _idle(page, 2)            # a valid pair
    page.wait_for_function(_OFF + " === 0", timeout=20000)
    page.select_option("#tool", "AREA_MM2"); _idle(page, 2)               # mixed again: needs a new tick
    page.wait_for_function(_OFF + " > 0", timeout=20000)
    assert not page.is_checked("#compare_anyway")
    # and "Convert area" is reset by a change of the pair
    page.select_option("#tool", "DIAMETER_MM"); _idle(page, 2)
    page.set_checked("#convert_area", True); _idle(page, 2)
    page.select_option("#manual", "fiji_area"); _idle(page, 2)
    assert not page.is_checked("#convert_area")


def test_f5_a_blocked_download_says_why_instead_of_starting(browser_page, tmp_path, monkeypatch):
    _port_9040(monkeypatch)
    page, srv = browser_page(os.path.join(R1.AG_DIR, "app_py.py"), tmp_path)
    ad = tmp_path / "ad.csv"
    ad.write_text(open(_fx("agree_area_diam")).read())
    page.set_input_files("#file", str(ad)); _idle(page, 3)
    page.select_option("#tool", "AREA_MM2"); _idle(page, 2)
    page.wait_for_function(_OFF + " > 0", timeout=20000)
    started = []
    page.on("download", lambda d: started.append(d))
    page.click("#dl_png", force=True); _idle(page, 1)     # force: a real click on a disabled-looking link
    msg = page.inner_text("#ct_dl_msg")
    assert "downloads are off" in msg and "Compare anyway" in msg and page.is_visible("#ct_dl_msg")
    assert started == []                                                   # nothing started, nothing cancelled


def test_f11_phone_width_every_figure_preview_has_an_open_full_size_link(browser_page, tmp_path, monkeypatch):
    _port_9040(monkeypatch)
    page, srv = browser_page(os.path.join(R1.AG_DIR, "app_py.py"), tmp_path, width=390)
    page.click("#load_example"); _idle(page, 3)
    assert page.locator("a.ct-full", has_text="open full size").count() == 3      # one per figure tab
    for tab in ("Both (A + B)", "A · Method", "B · Bland"):
        R1._tab(page, tab)
        link = page.locator(".tab-pane.active .tab-pane.active a.ct-full").first
        assert link.is_visible()
        with page.context.expect_page() as pop:
            link.click()
        new = pop.value
        new.wait_for_load_state()
        assert new.url.startswith("blob:")                                  # the preview image itself
        new.close()
