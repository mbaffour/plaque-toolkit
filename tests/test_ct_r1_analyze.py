"""Click-through round 1, desktop Analyze tab (app/study_tab.py): regression tests.

Every test drives the real widgets of a real MainWindow (offscreen): buttons are CLICKED, combo
boxes and check boxes are set the way a user sets them, and only the modal dialogs (file
pickers, message boxes, input dialogs) are replaced. Finding ids are the tester's (CT-R1 F1..F25).
"""
import io
import json
import os
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

from PySide6.QtWidgets import QMessageBox, QFileDialog, QInputDialog, QScrollArea  # noqa: E402

from app import ui as appui                # noqa: E402
from app import study_tab as ST            # noqa: E402


# --------------------------------------------------------------------------- fixtures
@pytest.fixture
def dialogs(monkeypatch):
    """Queue answers for the modal dialogs; record every message box."""
    q = {"save": [], "open": [], "openN": [], "question": [], "item": [], "text": [], "seen": []}

    def pop(key, default):
        return q[key].pop(0) if q[key] else default

    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: pop("save", ("", ""))))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: pop("open", ("", ""))))
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", staticmethod(lambda *a, **k: pop("openN", ([], ""))))

    def question(*a, **k):
        q["seen"].append(("question", a[2] if len(a) > 2 else ""))
        return pop("question", QMessageBox.No)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(question))
    for name in ("warning", "information", "critical"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(
            lambda *a, _n=name, **k: q["seen"].append((_n, a[2] if len(a) > 2 else "")) or QMessageBox.Ok))
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *a, **k: pop("item", ("", False))))
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
            st._add_plate(si, d, [x * x for x in d])
    st._refresh_tree()


def _zip(st, dialogs, tmp_path, name="z.zip"):
    p = str(tmp_path / name)
    dialogs["save"].append((p, "ZIP (*.zip)"))
    st.zip_btn.click()
    assert os.path.exists(p), st.err.text()
    return zipfile.ZipFile(p)


def _csv(z, name):
    return pd.read_csv(io.BytesIO(z.read(name)), dtype=str, keep_default_na=False)


# --------------------------------------------------------------------------- F1 / F2 / F14
NAMES = ["phage #3", "NA", "None", "007", "1.0"]


def test_zip_single_factor_equals_screen_and_uses_the_in_memory_table(st, dialogs, tmp_path):
    """CT-R1 F1/F2: the ZIP's samples, order and statistics are the screen's; the engine gets
    the in-memory table (no temp CSV path in run_config) and records the Toolkit version."""
    _fill(st, [(n, "", [1.0 + 0.2 * i, 1.05 + 0.2 * i, 0.95 + 0.2 * i]) for i, n in enumerate(NAMES)])
    st.analyse_btn.click()
    assert st._last is not None, st.err.text()
    z = _zip(st, dialogs, tmp_path)
    assert _csv(z, "summary_by_group_diameter_mm.csv")["group"].tolist() == NAMES
    omni = pd.read_csv(io.BytesIO(z.read("omnibus_test_diameter_mm.csv")))
    assert omni["test"][0] == st._chips["test"].text()
    assert abs(float(omni["p"][0]) - float(st._last[1]["omni"]["p"])) < 1e-12
    cfg = json.loads(z.read("run_config_diameter_mm.json"))
    text = json.dumps(cfg)
    assert "plaque_zip_" not in text and "compiled.csv" not in text      # no temp paths
    assert cfg["groups"] == NAMES
    assert str(cfg["toolkit_version"]).startswith("Plaque Toolkit")
    # the key files travel with the figure
    assert "violin_diameter_mm_legend_key.png" in z.namelist()
    assert z.read("violin_diameter_mm_legend_text.txt").decode().strip() == st.key_text.text()


@pytest.mark.parametrize("tags,control", [(["IPTG", "None"], "None"), (["0", "0.10", "1.0"], "0")])
def test_zip_grouped_equals_screen(st, dialogs, tmp_path, tags, control):
    """CT-R1 F1/F2/F14: grouped tags stay as typed ('None', '0.10', '1.0'); a control that is not
    the first tag is drawn and coloured as on screen; the key title is '2nd factor'."""
    spec = []
    for g, base in (("T4", 1.0), ("T7", 2.0)):
        for i, t in enumerate(tags):
            spec.append((g, t, [base + 0.3 * i, base + 0.3 * i + 0.05, base + 0.3 * i - 0.05]))
    _fill(st, spec)
    st.control_sel.setCurrentText(control)
    st.analyse_btn.click()
    assert st._last is not None and st._last[0] == "grouped", st.err.text()
    z = _zip(st, dialogs, tmp_path)
    comp = _csv(z, "control_comparisons_diameter_mm.csv")
    assert set(comp["subgroup"]) == set(t for t in tags if t != control)
    assert set(comp["control"]) == {control}
    assert z.read("grouped_diameter_mm_legend_text.txt").decode().strip() == st.key_text.text()
    lk = ST._legend_key()
    assert lk.from_figure(st._last_fig)["title"] == "2nd factor"
    cfg = json.loads(z.read("run_config_diameter_mm.json"))
    assert cfg["subgroups"] == st._last[1]["sub_order"] and cfg["control"] == control


def test_engine_exit_is_a_message_not_a_dead_app(st, dialogs, tmp_path, monkeypatch):
    """CT-R1 F1: a bare SystemExit from the engine (Analyze, ZIP) is shown in the tab."""
    ps = ST._engine()
    _fill(st, [("WT", "", [1.0, 1.1, 0.9]), ("mut", "", [1.5, 1.6, 1.4])])
    st.analyse_btn.click()
    assert st.zip_btn.isEnabled()
    real_run = ps.run
    monkeypatch.setattr(ps, "run", lambda args: (_ for _ in ()).throw(SystemExit("[error] engine said no")))
    dialogs["save"].append((str(tmp_path / "x.zip"), ""))
    st.zip_btn.click()
    assert "engine said no" in st.err.text() and not os.path.exists(tmp_path / "x.zip")
    monkeypatch.setattr(ps, "run", real_run)
    monkeypatch.setattr(ps, "run_stats", lambda *a, **k: (_ for _ in ()).throw(SystemExit("[error] stats said no")))
    st.analyse_btn.click()
    assert "stats said no" in st.err.text()
    # CT-R1 F19: the failed compute removed the old results and disabled every export
    assert st._last is None and st._last_fig is None and not st.zip_btn.isEnabled()
    assert st._chips["test"].text() == "—"


# --------------------------------------------------------------------------- F3
def test_legend_key_button_works_when_clicked(st, dialogs, tmp_path):
    """CT-R1 F3: clicked(bool) used to arrive as the key's path (False) -> TypeError."""
    _fill(st, [("WT", "", [1.0, 1.1, 0.9]), ("mut", "", [1.5, 1.6, 1.4])])
    st.analyse_btn.click()
    p = str(tmp_path / "key.svg")
    dialogs["save"].append((p, "SVG — vector, editable (*.svg)"))
    st.key_btn.click()
    assert os.path.exists(p) and st.err.text() == ""
    assert "plate1" in open(p, encoding="utf-8").read()
