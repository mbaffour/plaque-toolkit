"""Click-through round 2, desktop Analyze tab (app/study_tab.py) and Validate tab: regression tests.

Every test drives the real widgets of a real MainWindow (offscreen): buttons are CLICKED, combo
boxes and check boxes are set the way a user sets them, and only the modal dialogs (file
pickers, message boxes, input dialogs) are replaced. Finding ids are the round-2 tester's
(CT-R2 F1..F20).
"""
import io
import json
import os
import re
import sys
import zipfile

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")
pytest.importorskip("scipy")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QMessageBox, QFileDialog, QInputDialog  # noqa: E402

from app import ui as appui                # noqa: E402
from app import study_tab as ST            # noqa: E402


# --------------------------------------------------------------------------- fixtures
@pytest.fixture
def dialogs(monkeypatch):
    """Queue answers for the modal dialogs; record every message box and question."""
    q = {"save": [], "open": [], "openN": [], "question": [], "item": [], "text": [], "seen": [],
         "offered": []}

    def pop(key, default):
        return q[key].pop(0) if q[key] else default

    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: pop("save", ("", ""))))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: pop("open", ("", ""))))
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", staticmethod(lambda *a, **k: pop("openN", ([], ""))))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: pop("open", "")))

    def question(*a, **k):
        q["seen"].append(("question", a[2] if len(a) > 2 else ""))
        return pop("question", QMessageBox.No)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(question))
    for name in ("warning", "information", "critical"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(
            lambda *a, _n=name, **k: q["seen"].append((_n, a[2] if len(a) > 2 else "")) or QMessageBox.Ok))
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(
        lambda *a, **k: q["offered"].append(list(a[3])) or pop("item", ("", False))))
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: pop("text", ("", False))))
    return q


@pytest.fixture
def win(qtbot):
    w = appui.MainWindow()
    qtbot.addWidget(w)
    return w


@pytest.fixture
def st(win):
    return win.study_tab


def _fill(st, spec, n=25, seed=0):
    """spec: [(sample, subgroup, [plate mean, ...]), ...] -> samples + plates (area = d^2)."""
    rng = np.random.default_rng(seed)
    for g, sub, mus in spec:
        st._samples.append({"group": g, "subgroup": sub})
        si = len(st._samples) - 1
        for mu in mus:
            d = np.clip(mu + rng.normal(0, 0.08, n), 0.05, None).round(3).tolist()
            st._add_plate(si, d, [round(x * x, 4) for x in d])
    st._refresh_tree()


def _snap(st):
    return [(s["group"], s.get("subgroup", ""),
             [(p["replicate"], p["diam"], p["area"]) for p in st._plates_of(s)]) for s in st._samples]


def _status(win):
    return win.statusBar().currentMessage()


def _zip(st, dialogs, tmp_path, name="z.zip"):
    p = str(tmp_path / name)
    dialogs["save"].append((p, "ZIP (*.zip)"))
    st.zip_btn.click()
    assert os.path.exists(p), st.err.text()
    return zipfile.ZipFile(p)


def _long_action(st):
    return next(a for a in st.savedata_btn.menu().actions() if a.text().startswith("Long"))


# --------------------------------------------------------------------------- F2
HASH3 = [("#3 phage", "", [1.0, 1.05, 0.95]), ("WT", "", [1.5, 1.55, 1.45]), ("mutB", "", [2.0, 2.1, 1.9])]


def test_hash_sample_survives_save_load_and_long_export(st, dialogs, tmp_path):
    """CT-R2 F2: a sample named '#3 phage' used to vanish on Load study and from the Long
    export (lines starting with # were comments everywhere). Now # is a comment only above the
    header, and the writers quote such a first cell, so the 3-sample ANOVA stays a 3-sample
    ANOVA after re-loading -- in this tab and in the statistics engine's own reader."""
    _fill(st, HASH3)
    st.analyse_btn.click()
    assert st._chips["groups"].text() == "3" and st._chips["test"].text() == "one-way ANOVA"
    p0 = float(st._last[1]["omni"]["p"])
    before = _snap(st)

    study = tmp_path / "study.csv"
    dialogs["save"].append((str(study), "CSV (*.csv)"))
    st.save_study_btn.click()
    text = study.read_text()
    assert '\n"#3 phage",' in text                          # quoted: never a comment line
    st._dirty = False
    dialogs["open"].append((str(study), ""))
    st.load_study_btn.click()
    assert _snap(st) == before, st.err.text()
    st.analyse_btn.click()
    assert st._chips["groups"].text() == "3" and st._chips["test"].text() == "one-way ANOVA"
    assert abs(float(st._last[1]["omni"]["p"]) - p0) < 1e-12

    long_p = tmp_path / "long.csv"
    dialogs["save"].append((str(long_p), "CSV (*.csv)"))
    _long_action(st).trigger()
    assert long_p.exists()
    st._dirty = False
    dialogs["open"].append((str(long_p), ""))
    st.load_study_btn.click()
    assert [s["group"] for s in st._samples] == ["#3 phage", "WT", "mutB"]
    assert [len(st._plates_of(s)) for s in st._samples] == [3, 3, 3]
    # the statistics engine reads the tab's Long export with all three samples too
    eng = ST._engine().read_table(str(long_p))
    assert "#3 phage" in set(eng["group"].astype(str))


def test_hash_row_after_the_header_is_data_and_before_it_a_comment(st, dialogs, tmp_path):
    """CT-R2 F2: the comment rule shared with the engine and the R app."""
    f = tmp_path / "typed.csv"
    f.write_text("# my study, typed by hand\ngroup,replicate,diameter_mm\n"
                 "#3 phage,p1,1.0\n#3 phage,p1,1.1\nWT,p1,2.0\nWT,p2,2.1\n")
    dialogs["open"].append((str(f), ""))
    st.load_study_btn.click()
    assert [(s["group"], [p["diam"] for p in st._plates_of(s)]) for s in st._samples] == \
        [("#3 phage", [[1.0, 1.1]]), ("WT", [[2.0], [2.1]])]
