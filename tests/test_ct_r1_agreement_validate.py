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
