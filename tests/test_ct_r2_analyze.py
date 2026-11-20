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


# --------------------------------------------------------------------------- F5
@pytest.mark.parametrize("name,text,lines", [
    ("long_bad.csv",
     "group,subgroup,replicate,metric,value\nA,,p1,diameter_mm,1.2\nA,,p2,diameter_mm,abc\n"
     "A,,p2,diameter_mm,2.4\nB,,p1,diameter_mm,-1.0\nB,,p1,diameter_mm,1.0\nB,,p2,diameter_mm,0\n"
     "B,,p2,diameter_mm,2.2\nB,,p2,turbidity,0\n",
     ["line 3", "line 5", "line 7"]),
    ("wide_neg.csv",
     "group,replicate,diameter_mm\nA,p1,1.2\nA,p2,-0.5\nA,p3,1.4\n\nB,p1,0\nB,p2,2.1\nB,p3,2.3\n",
     ["line 3", "line 6"]),
])
def test_load_study_refuses_text_zero_and_negative_sizes(st, dialogs, tmp_path, name, text, lines):
    """CT-R2 F5: Load study applies Add CSV(s)'s value rules. Text, zero and negative sizes
    are refused with the file, the line and the cell named, and the study on screen is kept
    (a turbidity 0 in a Long file is not a size and is not refused)."""
    _fill(st, [("keep", "", [1.0, 1.1])])
    before = _snap(st)
    f = tmp_path / name
    f.write_text(text)
    st._dirty = False
    dialogs["open"].append((str(f), ""))
    st.load_study_btn.click()
    msg = st.err.text()
    assert msg.startswith("Not loaded: %s" % name), msg
    for ln in lines:
        assert ln in msg, msg
    assert "turbidity" not in msg
    assert _snap(st) == before                              # nothing replaced
    assert st._last is None


def test_load_study_keeps_blank_placeholder_rows(st, dialogs, tmp_path):
    """Blank value cells (an empty plate, an empty sample) stay legal."""
    f = tmp_path / "ok.csv"
    f.write_text("group,subgroup,replicate,diameter_mm,area_mm2,source\nA,,p1,1.0,0.8,\nA,,p2,,,\nB,,,,,\n")
    dialogs["open"].append((str(f), ""))
    st.load_study_btn.click()
    assert st.err.text() == ""
    assert _snap(st) == [("A", "", [("p1", [1.0], [0.8]), ("p2", [], [])]), ("B", "", [])]


# --------------------------------------------------------------------------- F3 / F7 / F8 / F9 / F1 / F10
def _all_plaques(tmp_path, name="all_plaques.csv", flag_col="QC_FLAG"):
    """A Batch all_plaques.csv: 2 images; Plate_6 has 4 sized + 2 CORE? + 1 NO_SIZE,
    sample.tif has 3 sized + 1 CORE?."""
    rows = ([("Plate_6.tif", 1.0 + 0.1 * i, "OK") for i in range(4)]
            + [("Plate_6.tif", 0.4, "CORE?"), ("Plate_6.tif", 0.5, "EDGE|CORE?"), ("Plate_6.tif", 0.9, "NO_SIZE")]
            + [("sample.tif", 2.0 + 0.1 * i, "OK" if i else "LARGE?") for i in range(3)]
            + [("sample.tif", 0.3, "CORE?")])
    df = pd.DataFrame(rows, columns=["IMAGE", "DIAMETER_MM", flag_col])
    df.insert(1, "INDEX", range(1, len(df) + 1))
    df["AREA_MM2"] = (df["DIAMETER_MM"] ** 2).round(4)
    df["SOURCE"] = "auto"                                   # how found, NOT a plate column
    p = tmp_path / name
    df.to_csv(p, index=False)
    return str(p)


def _assign_exec(monkeypatch, answers):
    """Fill the REAL assign dialog's table: answers[i] = sample for row i ('' = leave blank)."""
    seen = {}

    def exec_(self):
        seen["rows"] = [self.table.item(i, 0).text() for i in range(self.table.rowCount())]
        seen["n"] = [self.table.item(i, 1).text() for i in range(self.table.rowCount())]
        for i, a in enumerate(answers):
            self.table.cellWidget(i, 2).setCurrentText(a)
        return ST.QDialog.Accepted
    monkeypatch.setattr(ST._AssignDialog, "exec", exec_)
    return seen


def test_multi_image_table_is_one_plate_per_image_in_add_csv(win, st, dialogs, tmp_path):
    """CT-R2 F3: Batch's all_plaques.csv (IMAGE column, 2 values) used to become ONE pooled
    plate. Now each image is a plate, the status says so, and each plate keeps its own left-out
    account (CT-R2 F7)."""
    _fill(st, [("T4", "", [])])
    st._select_sample(0)
    dialogs["openN"].append(([_all_plaques(tmp_path)], ""))
    st.add_csv_btn.click()
    plates = st._plates_of(st._samples[0])
    assert [(p["replicate"], len(p["diam"]), p["left_out"]) for p in plates] == \
        [("plate1", 4, 3), ("plate2", 3, 1)]
    assert plates[0]["source"] == "all_plaques.csv · Plate_6.tif"
    assert "all_plaques.csv holds 2 images: added as 2 plate(s)" in _status(win)
    assert "QC_FLAG" not in _status(win)                    # it has one


def test_multi_image_table_is_one_plate_per_image_in_import_and_assign(win, st, dialogs, tmp_path,
                                                                       monkeypatch):
    """CT-R2 F3 + F9: Import & assign offers one row per image, and the left-out count in the
    status is the one of the rows actually imported (the 2nd image is left without a sample)."""
    seen = _assign_exec(monkeypatch, ["T4", ""])
    dialogs["openN"].append(([_all_plaques(tmp_path)], ""))
    st.assign_btn.click()
    assert seen["rows"] == ["all_plaques · Plate_6.tif", "all_plaques · sample.tif"]
    assert seen["n"] == ["4", "3"]
    assert [(p["group"], len(p["diam"]), p["left_out"]) for p in st._plates] == [("T4", 4, 3)]
    msg = _status(win)
    assert "Imported 1 plate(s)" in msg
    # 2 dark-centre + 1 split piece of Plate_6 only; sample.tif's CORE? is not counted
    assert "2 outlined at the dark centre only" in msg and "1 split piece" in msg, msg
    assert "3 outlined" not in msg


def test_left_out_account_reaches_tree_report_zip_and_study_file(win, st, dialogs, tmp_path):
    """CT-R2 F7: each plate remembers how many plaques were left out and why: tree tooltip,
    Report, ZIP report and the study file (survives Save / Load)."""
    _fill(st, [("T4", "", []), ("WT", "", [1.5, 1.6, 1.55])])
    st._select_sample(0)
    dialogs["openN"].append(([_all_plaques(tmp_path)], ""))
    st.add_csv_btn.click()
    st._add_plate(0, [1.2, 1.3, 1.25], [1.4, 1.7, 1.6])         # a 3rd T4 plate, nothing left out
    st._refresh_tree()
    child = st.tree.topLevelItem(0).child(0)
    assert "plate1: 4 plaques sized, 3 left out (2 outlined at the dark centre only" in child.toolTip(0)
    assert child.text(2) == "4 (+3 left out)"
    st.analyse_btn.click()
    rep = st.report.toPlainText()
    assert "T4 · plate1: 4 plaques sized, 3 left out (" in rep
    assert "T4 · plate2: 3 plaques sized, 1 left out (" in rep
    z = _zip(st, dialogs, tmp_path)
    md = z.read("report_diameter_mm.md").decode()
    assert "T4 · plate1: 4 plaques sized, 3 left out (" in md
    study = tmp_path / "s.csv"
    dialogs["save"].append((str(study), ""))
    st.save_study_btn.click()
    st._dirty = False
    dialogs["open"].append((str(study), ""))
    st.load_study_btn.click()
    t4 = st._plates_of(st._samples[0])
    assert [(p["left_out"], bool(p["left_out_why"])) for p in t4] == [(3, True), (1, True), (0, False)]
    assert "3 left out" in st.tree.topLevelItem(0).child(0).toolTip(0)


ALLFLAG = pd.DataFrame({"INDEX_COL": [1, 2, 3, 4], "DIAMETER_MM": [0.4, 0.5, 0.6, 0.3],
                        "AREA_MM2": [0.1, 0.2, 0.3, 0.1], "QC_FLAG": ["CORE?"] * 3 + ["NO_SIZE"]})


def test_all_flagged_plate_asks_the_same_question_on_both_routes(win, st, dialogs, tmp_path):
    """CT-R2 F8: 'All 4 plaques of X are flagged as not sizeable…' on Add CSV(s) and on Add
    current plate; No adds nothing; Yes adds one plate without sizes, and Add current does not
    add a second empty copy on the next click."""
    _fill(st, [("T4", "", [])])
    st._select_sample(0)
    f = tmp_path / "allflag.csv"
    ALLFLAG.to_csv(f, index=False)
    dialogs["openN"].append(([str(f)], ""))
    dialogs["question"].append(QMessageBox.No)
    st.add_csv_btn.click()
    q_csv = [t for k, t in dialogs["seen"] if k == "question"][-1]
    assert q_csv.startswith("All 4 plaques of allflag.csv are flagged as not sizeable (")
    assert q_csv.rstrip().endswith("counted in the statistics.") and "Add it as a plate without sizes?" in q_csv
    assert st._plates == []

    mt = win.measure_tab
    mt.model.set_dataframe(ALLFLAG.copy())
    mt.image_path = str(tmp_path / "Plate_6.tif")
    st._select_sample(0)
    dialogs["question"].append(QMessageBox.Yes)
    st.add_cur_btn.click()
    q_cur = [t for k, t in dialogs["seen"] if k == "question"][-1]
    assert q_cur.startswith("All 4 plaques of Plate_6.tif are flagged as not sizeable (")
    assert q_cur.replace("Plate_6.tif", "X") == q_csv.replace("allflag.csv", "X")   # one question
    assert [(len(p["diam"]), p["left_out"]) for p in st._plates] == [(0, 4)]
    st._select_sample(0)
    dialogs["question"].append(QMessageBox.No)                # "already added": keep one copy
    st.add_cur_btn.click()
    assert len(st._plates) == 1
    assert [t for k, t in dialogs["seen"] if k == "question"][-1].startswith("This measurement")


def test_plates_without_sizes_are_counted_by_one_rule(win, st, dialogs):
    """CT-R2 F8: tree, compiled line, PLATES chip and Summary N agree (plates with at least one
    sized plaque); the plate without sizes is named in the warning and the Report."""
    _fill(st, [("T4", "", [1.0, 1.1]), ("WT", "", [1.5, 1.6, 1.55])])
    st._add_plate(0, [], [], left_out={"n": 89, "why": "89 outlined at the dark centre only"})
    st._refresh_tree()
    top = st.tree.topLevelItem(0)
    assert top.text(2).startswith("2 plate(s) + 1 without sizes")
    assert st.count_lbl.text().startswith("2 sample(s) · 5 plate(s) compiled; 1 plate(s) without sizes")
    assert "T4/plate3" in st.count_lbl.text()
    st.analyse_btn.click()
    assert st._chips["plates"].text() == "5"
    n_plates = st._last[1]["summary"]["n_units"].astype(int).tolist()
    assert n_plates == [2, 3]
    msg = "T4/plate3 has no sized plaques (89 left out: 89 outlined at the dark centre only)"
    assert msg in st.warn_lbl.text() and msg in st.report.toPlainText()


def test_import_without_qc_flag_column_says_so_once(win, st, dialogs, tmp_path):
    """CT-R2 F1 (tab part): a per-plaque table without QC_FLAG is used whole, and the import
    message says so once, naming the files."""
    _fill(st, [("T4", "", [])])
    st._select_sample(0)
    paths = []
    for i in (1, 2):
        p = tmp_path / ("data-green-p%d.csv" % i)
        p.write_text("INDEX_COL,DIAMETER_MM,AREA_MM2,SOURCE\n1,1.2,1.1,auto\n2,1.3,1.3,auto\n")
        paths.append(str(p))
    dialogs["openN"].append((paths, ""))
    st.add_csv_btn.click()
    msg = _status(win)
    assert msg.count("no QC_FLAG column") == 1, msg
    assert ("data-green-p1.csv, data-green-p2.csv have no QC_FLAG column: every row was used; "
            "plaques outlined at the dark centre only, if any, cannot be told apart.") in msg
    assert st.err.text() == ""                               # not a blocking error


def test_qc_flag_column_is_found_whatever_its_case_and_cells_go_to_plaque_qc(st, dialogs, tmp_path,
                                                                            monkeypatch):
    """CT-R2 F10 (tab side): 'qc_flag' / 'Qc_Flag' headers are read, and every cell reaches
    plaque_qc.size_ok exactly as it is in the file (the rule lives there, not in the tab)."""
    import plaque_qc
    got = []
    real = plaque_qc.size_ok
    monkeypatch.setattr(plaque_qc, "size_ok", lambda f: got.append(f) or real(f))
    _fill(st, [("T4", "", [])])
    st._select_sample(0)
    paths = [_all_plaques(tmp_path, "lower.csv", "qc_flag"), _all_plaques(tmp_path, "mixed.csv", "Qc_Flag")]
    dialogs["openN"].append((paths, ""))
    st.add_csv_btn.click()
    assert [len(p["diam"]) for p in st._plates] == [4, 3, 4, 3]
    assert "EDGE|CORE?" in got and "LARGE?" in got


# Depends on the detection fixer's plaque_qc change (tokens matched case- and space-tolerantly).
# Alone in this worktree plaque_qc still matches exact tokens, so this test is expected to fail
# (xfail) until both sides are merged; then it passes (and an unexpected pass is fine).
import plaque_qc as _pqc                                      # noqa: E402
_PQC_TOLERANT = bool(not _pqc.size_ok("core?") and not _pqc.size_ok("MERGED? | CORE?"))


@pytest.mark.xfail(not _PQC_TOLERANT, reason="needs the detection fixer's tolerant plaque_qc tokens "
                   "(CT-R2 F10, plaque_qc side)", strict=False)
def test_qc_flag_cells_edited_by_hand_are_still_recognised(st, dialogs, tmp_path):
    """CT-R2 F10: 'core?' and 'MERGED? | CORE?' (an edited file) are left out like 'CORE?'."""
    _fill(st, [("T4", "", [])])
    st._select_sample(0)
    f = tmp_path / "edited.csv"
    pd.DataFrame({"DIAMETER_MM": [1.0, 1.1, 0.4, 0.5], "QC_FLAG": ["OK", "", "core?", "MERGED? | CORE?"]}
                 ).to_csv(f, index=False)
    dialogs["openN"].append(([str(f)], ""))
    st.add_csv_btn.click()
    assert [(p["diam"], p["left_out"]) for p in st._plates] == [([1.0, 1.1], 2)]
