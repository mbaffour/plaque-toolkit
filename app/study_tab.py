"""Analyze tab — a publication-grade plotting workbench that lives inside the app.

The workflow the lab actually does:
  1. Measure several plates (Measure tab) or save per-plaque CSVs.
  2. **Create a SAMPLE, then add its plates into it as replicates** — e.g. sample "WT" with three
     replicate plates. Replicates live *inside* their sample, so the grouping is structural.
  3. Analyze: a publication-ready violin SuperPlot + the correct statistics, computed on the
     PLATE as the experimental unit (avoiding pseudoreplication) — with full plot customization,
     on-screen summary tables, and one-click exports.

Two analysis modes, chosen automatically:
  • Single-factor  (samples only)          → violin + one-way ANOVA/Tukey (or t-test / Mann–Whitney).
  • Grouped control-comparison (sample carries an optional 2nd factor) → each value tested vs a control.

The maths + figures are the SAME validated engine as the standalone Plaque Stats app
(`plaque_stats/plaque_stats.py`), reused here directly, so results are identical.
"""
import os
import tempfile
import zipfile

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit, QPushButton,
    QComboBox, QCheckBox, QFrame, QTreeWidget, QTreeWidgetItem, QHeaderView, QFileDialog,
    QMessageBox, QPlainTextEdit, QAbstractItemView, QGraphicsDropShadowEffect, QTabWidget,
    QTableView, QDoubleSpinBox, QSpinBox, QDialog, QDialogButtonBox, QToolButton, QMenu,
    QSizePolicy, QScrollArea, QTableWidget, QTableWidgetItem,
)

from app import style
from app.widgets import PandasTableModel


def _stats_available():
    """True if the statistics engine can run here (SciPy + plaque_stats present).
    The Full build bundles both; the Light build omits SciPy, so analysis is disabled there
    while compiling samples still works."""
    import importlib.util
    try:
        return (importlib.util.find_spec("scipy") is not None
                and importlib.util.find_spec("plaque_stats") is not None)
    except Exception:
        return False


# ------------------------------------------------------------------ small helpers
def _shadow(widget, blur=18, dy=2, alpha=40):
    try:
        eff = QGraphicsDropShadowEffect(widget)
        eff.setBlurRadius(blur); eff.setXOffset(0); eff.setYOffset(dy)
        eff.setColor(QColor(0, 0, 0, alpha)); widget.setGraphicsEffect(eff)
    except Exception:
        pass


def _diam_col(df):
    """Find the diameter column in a per-plaque CSV (case-insensitive)."""
    for c in df.columns:
        cl = str(c).lower()
        if "diam" in cl and "pxl" not in cl and "pix" not in cl:
            return c
    return None


def _area_col(df):
    for c in df.columns:
        cl = str(c).lower()
        if "area" in cl and "pxl" not in cl and "pix" not in cl:
            return c
    return None


def _round_df(df, n=4):
    """Round numeric columns for on-screen display without touching the saved data."""
    try:
        out = df.copy()
        for c in out.columns:
            if pd.api.types.is_float_dtype(out[c]):
                out[c] = out[c].round(n)
        return out
    except Exception:
        return df


class _SampleDialog(QDialog):
    """Create / edit a sample: a name (the group / x-axis category) + an optional 2nd factor."""
    def __init__(self, parent, name="", subgroup=""):
        super().__init__(parent)
        self.setWindowTitle("Sample")
        lay = QVBoxLayout(self)
        form = QGridLayout()
        self.name_in = QLineEdit(name); self.name_in.setPlaceholderText("e.g. WT")
        self.sub_in = QLineEdit(subgroup); self.sub_in.setPlaceholderText("optional, e.g. LE392")
        form.addWidget(QLabel("Sample name (group):"), 0, 0); form.addWidget(self.name_in, 0, 1)
        form.addWidget(QLabel("2nd factor (optional):"), 1, 0); form.addWidget(self.sub_in, 1, 1)
        hint = QLabel("Leave the 2nd factor blank for a normal sample. Set it (e.g. host) on two or "
                      "more samples to run a control-comparison.")
        hint.setObjectName("Placeholder"); hint.setWordWrap(True)
        lay.addLayout(form); lay.addWidget(hint)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.name_in.setMinimumWidth(240)

    def values(self):
        return self.name_in.text().strip(), self.sub_in.text().strip()


def _sample_guess(stem):
    """Guess the sample name from a plate CSV's filename by stripping a trailing
    plate/rep/replicate token + number (so 'WT_plate2' → 'WT', 'T65I-3' → 'T65I')."""
    import re
    g = re.sub(r"[ _\-]*(plate|rep|replicate|r)?[ _\-]*\d+$", "", str(stem), flags=re.I).strip(" _-")
    return g or str(stem)


class _AssignDialog(QDialog):
    """Map many per-plaque CSVs to samples — EACH CSV IS ONE REPLICATE PLATE. One row per file:
    pick its sample (reuse an existing name or type a new one), an optional 2nd factor, and the
    replicate id. This is how you tell the tool which plate belongs to which sample, so replicates
    are real (no pseudoreplication)."""
    def __init__(self, parent, parsed, existing):
        super().__init__(parent)
        self.setWindowTitle("Assign CSVs to samples")
        self._parsed = parsed
        lay = QVBoxLayout(self)
        info = QLabel("Each CSV is one <b>replicate plate</b>. Assign each to a sample — reuse a name "
                      "to make plates replicates of the same sample, or type a new name. The 2nd "
                      "factor is optional (for control-comparison).")
        info.setWordWrap(True); lay.addWidget(info)

        top = QHBoxLayout()
        self.all_sample = QLineEdit(); self.all_sample.setPlaceholderText("set every Sample to…")
        apply_btn = QPushButton("Apply to all"); apply_btn.clicked.connect(self._apply_all)
        top.addWidget(QLabel("Quick:")); top.addWidget(self.all_sample); top.addWidget(apply_btn); top.addStretch()
        lay.addLayout(top)

        groups = []
        for s in existing:
            if s["group"] and s["group"] not in groups:
                groups.append(s["group"])
        self.table = QTableWidget(len(parsed), 5)
        self.table.setHorizontalHeaderLabels(["File", "N plaques", "Sample", "2nd factor", "Replicate id"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for c in (1, 2, 3, 4):
            self.table.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeToContents)
        for i, p in enumerate(parsed):
            f = QTableWidgetItem(p["stem"]); f.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(i, 0, f)
            n = QTableWidgetItem(str(p["n"])); n.setFlags(Qt.ItemIsEnabled); n.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(i, 1, n)
            cb = QComboBox(); cb.setEditable(True)
            for g in groups:
                cb.addItem(g)
            cb.setCurrentText(_sample_guess(p["stem"]))
            cb.setMinimumWidth(140)
            self.table.setCellWidget(i, 2, cb)
            self.table.setItem(i, 3, QTableWidgetItem(""))
            self.table.setItem(i, 4, QTableWidgetItem(p["stem"]))
        lay.addWidget(self.table)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.resize(720, 420)

    def _apply_all(self):
        v = self.all_sample.text().strip()
        if not v:
            return
        for i in range(self.table.rowCount()):
            self.table.cellWidget(i, 2).setCurrentText(v)

    def rows(self):
        out = []
        for i, p in enumerate(self._parsed):
            out.append({"sample": self.table.cellWidget(i, 2).currentText().strip(),
                        "subgroup": self.table.item(i, 3).text().strip(),
                        "replicate": self.table.item(i, 4).text().strip(),
                        "diam": p["diam"], "area": p["area"]})
        return out


# --------------------------------------------------------------------- the tab
class StudyTab(QWidget):
    METRICS = [("Diameter (mm)", "diam"), ("Area (mm²)", "area")]
    PALETTES_UI = [("Okabe–Ito (default)", "okabe"), ("Set2", "set2"), ("Tab10", "tab10"),
                   ("Warm", "warm"), ("Cool", "cool"), ("Grays", "grays")]

    def __init__(self, measure_tab=None):
        super().__init__()
        self.measure_tab = measure_tab
        self._samples = []        # list of {"group": str, "subgroup": str} — the containers (may be empty)
        self._plates = []         # list of {group, subgroup, replicate, diam[], area[]}
        self.canvas = None
        self.toolbar = None
        self._fig_container = None
        self._last_fig = None
        self._last = None         # (kind, payload) cache for redraw + saving
        self._building = True     # guard so wiring customize controls doesn't trigger redraw
        self._stats_ok = _stats_available()

        intro = QLabel(
            "Compile your results, then analyze them without leaving the app. <b>Create a sample</b> and "
            "<b>add its plates into it</b> — three replicate plates of one sample sit together under it. "
            "Add the plate you just measured, or import saved per-plaque CSVs. Then <b>Analyze</b> for a "
            "publication-ready violin plot + the right statistics (plate = experimental unit), fully "
            "customizable, with the summary tables shown right here.")
        intro.setObjectName("ModeHelp"); intro.setWordWrap(True)

        learn = QLabel('<a href="STATS_EXPLAINED.html" style="color:#0a5c43;font-weight:600;'
                       'text-decoration:none;">&#128218; New to these statistics? Read the plain-language '
                       'guide (plate = unit, ANOVA vs t-test, control comparison) &rarr;</a>')
        learn.setTextFormat(Qt.RichText); learn.setOpenExternalLinks(False)
        learn.linkActivated.connect(lambda _=None: self._open_doc("STATS_EXPLAINED.html"))

        lay = QVBoxLayout(self); lay.setContentsMargins(14, 12, 14, 12); lay.setSpacing(10)
        lay.addWidget(intro); lay.addWidget(learn)
        lay.addWidget(self._build_compile_card())
        lay.addWidget(self._build_analyse_card(), 1)
        self._building = False
        self._refresh_tree()

    # ================================================================ COMPILE
    def _build_compile_card(self):
        card = QFrame(); card.setObjectName("Card"); _shadow(card)
        v = QVBoxLayout(card); v.setContentsMargins(14, 12, 14, 12); v.setSpacing(8)
        v.addWidget(self._heading("1 · Compile — build your samples"))

        self.new_sample_btn = QPushButton("＋  New sample"); self.new_sample_btn.setObjectName("Primary")
        self.new_sample_btn.setToolTip("Create a sample (a genotype/condition). Then add its plates into it.")
        self.new_sample_btn.clicked.connect(self._new_sample)
        self.add_cur_btn = QPushButton("Add current plate")
        self.add_cur_btn.setToolTip("Add the plate you just measured (Measure tab) as a replicate of the "
                                    "selected sample.")
        self.add_cur_btn.clicked.connect(self._add_current)
        self.add_csv_btn = QPushButton("Add CSV(s)…")
        self.add_csv_btn.setToolTip("Add saved per-plaque CSV(s) as replicate plates of the selected "
                                    "sample. Each file = one replicate.")
        self.add_csv_btn.clicked.connect(self._add_csvs)
        self.assign_btn = QPushButton("Import & assign…"); self.assign_btn.setObjectName("Primary")
        self.assign_btn.setToolTip("Pick many plate CSVs at once and map each to a sample in one table "
                                   "(each CSV = one replicate plate). No sample needs to be selected first.")
        self.assign_btn.clicked.connect(self._import_assign)
        self.edit_btn = QPushButton("Rename / edit…"); self.edit_btn.clicked.connect(self._edit_sample)
        self.remove_btn = QPushButton("Remove"); self.remove_btn.clicked.connect(self._remove_selected)
        row = QHBoxLayout()
        for b in (self.new_sample_btn, self.add_cur_btn, self.add_csv_btn, self.assign_btn):
            row.addWidget(b)
        row.addSpacing(10); row.addWidget(self.edit_btn); row.addWidget(self.remove_btn); row.addStretch()
        v.addLayout(row)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["Sample / plate", "2nd factor", "N plaques", "Mean Ø (mm)"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        for c in (1, 2, 3):
            self.tree.header().setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tree.setMinimumHeight(180)
        self.tree.setRootIsDecorated(True)
        self.tree.itemSelectionChanged.connect(self._on_tree_selection)
        v.addWidget(self.tree)

        self.count_lbl = QLabel("No samples yet — click “New sample”, then add its plates.")
        self.count_lbl.setObjectName("Placeholder")
        self.clear_btn = QPushButton("Clear all"); self.clear_btn.clicked.connect(self._clear_all)
        self.save_study_btn = QPushButton("Save study…"); self.save_study_btn.clicked.connect(self._save_study)
        self.load_study_btn = QPushButton("Load study…"); self.load_study_btn.clicked.connect(self._load_study)
        brow = QHBoxLayout(); brow.addWidget(self.count_lbl); brow.addStretch()
        for b in (self.clear_btn, self.save_study_btn, self.load_study_btn):
            brow.addWidget(b)
        v.addLayout(brow)
        return card

    # ================================================================ ANALYZE
    def _build_analyse_card(self):
        card = QFrame(); card.setObjectName("Card"); _shadow(card)
        v = QVBoxLayout(card); v.setContentsMargins(14, 12, 14, 12); v.setSpacing(8)
        v.addWidget(self._heading("2 · Analyze"))

        self.mode_lbl = QLabel("Create samples and add plates, then Analyze. The mode is chosen "
                               "automatically from your samples.")
        self.mode_lbl.setObjectName("Placeholder"); self.mode_lbl.setWordWrap(True)
        v.addWidget(self.mode_lbl)

        # analyze controls: metric + control + test + Analyze
        row = QHBoxLayout()
        self.metric_sel = QComboBox()
        for lab, key in self.METRICS:
            self.metric_sel.addItem(lab, key)
        self.metric_sel.setToolTip("Which measurement to analyze (both are stored per plate).")
        self.metric_sel.currentIndexChanged.connect(self._reanalyse_if_ready)
        self.ctrl_cap = QLabel("Control:"); self.ctrl_cap.setObjectName("FieldLabel")
        self.control_sel = QComboBox(); self.control_sel.setMinimumWidth(120)
        self.control_sel.setToolTip("Grouped mode: every other 2nd-factor value is compared to THIS one.")
        self.control_sel.currentIndexChanged.connect(self._reanalyse_if_ready)
        self.param_sel = QComboBox()
        self.param_sel.addItem("Auto test", "auto")
        self.param_sel.addItem("Parametric (t / ANOVA)", "parametric")
        self.param_sel.addItem("Non-parametric (MWU / KW)", "nonparametric")
        self.param_sel.setToolTip("Auto uses a parametric test on plate means at small n (SuperPlot "
                                  "recommendation); else normality checks decide.")
        self.param_sel.currentIndexChanged.connect(self._reanalyse_if_ready)
        self.analyse_btn = QPushButton("  Analyze  "); self.analyse_btn.setObjectName("Primary")
        self.analyse_btn.clicked.connect(self._analyse)
        row.addWidget(QLabel("Metric:")); row.addWidget(self.metric_sel)
        row.addSpacing(8); row.addWidget(self.ctrl_cap); row.addWidget(self.control_sel)
        row.addSpacing(8); row.addWidget(QLabel("Test:")); row.addWidget(self.param_sel)
        row.addStretch(); row.addWidget(self.analyse_btn)
        v.addLayout(row)

        self.err = QLabel(""); self.err.setWordWrap(True)
        self.err.setStyleSheet("color:%s;font-weight:600" % style.LIGHT["warn"])
        v.addWidget(self.err)

        # stat chips
        self.stat_card = QFrame(); self.stat_card.setObjectName("SummaryCard"); _shadow(self.stat_card)
        grid = QGridLayout(self.stat_card); grid.setContentsMargins(16, 10, 16, 10)
        grid.setHorizontalSpacing(22); grid.setVerticalSpacing(2)
        self._chips = {}
        for col, (key, lab) in enumerate([("groups", "SAMPLES"), ("plates", "PLATES"),
                                          ("unit", "UNIT"), ("test", "TEST"),
                                          ("p", "OMNIBUS p"), ("effect", "EFFECT")]):
            cap = QLabel(lab); cap.setObjectName("SummaryHeading")
            val = QLabel("—"); val.setStyleSheet("font-size:17px;font-weight:700;")
            grid.addWidget(cap, 0, col); grid.addWidget(val, 1, col)
            self._chips[key] = val
        v.addWidget(self.stat_card)

        # results sub-tabs: Plot / Summary / Comparisons / Report
        self.results = QTabWidget()
        self.results.addTab(self._build_plot_tab(), "  Plot  ")
        self.results.addTab(self._build_summary_tab(), "  Summary  ")
        self.results.addTab(self._build_comparisons_tab(), "  Comparisons  ")
        self.results.addTab(self._build_report_tab(), "  Report  ")
        v.addWidget(self.results, 1)

        # export bar
        self.savefig_btn = QPushButton("Save figure…"); self.savefig_btn.clicked.connect(self._save_fig)
        self.savesum_btn = QPushButton("Save summary CSV…"); self.savesum_btn.clicked.connect(self._save_summary)
        self.savedata_btn = QToolButton(); self.savedata_btn.setText("Save compiled data ▾")
        self.savedata_btn.setPopupMode(QToolButton.InstantPopup)
        dmenu = QMenu(self.savedata_btn)
        dmenu.addAction("Wide — one row per plaque", self._save_data_wide)
        dmenu.addAction("Long — group/replicate/metric/value (standalone-ready)", self._save_data_long)
        self.savedata_btn.setMenu(dmenu)
        self.zip_btn = QPushButton("Export everything (ZIP)…"); self.zip_btn.clicked.connect(self._export_zip)
        self.zip_btn.setToolTip("Figure in every format + summaries + pairwise + report + provenance, "
                                "the same bundle as the standalone app.")
        s = QHBoxLayout()
        for b in (self.savefig_btn, self.savesum_btn, self.savedata_btn, self.zip_btn):
            s.addWidget(b)
        s.addStretch()
        v.addLayout(s)
        self._export_buttons = [self.savefig_btn, self.savesum_btn, self.savedata_btn, self.zip_btn]
        for b in self._export_buttons:
            b.setEnabled(False)

        if not self._stats_ok:
            self.analyse_btn.setEnabled(False)
            self.analyse_btn.setToolTip("Statistics need the Full build (bundles SciPy).")
            self.mode_lbl.setText("Compiling samples works here, but the statistics + violin plot need "
                                  "the Full build (this Light build omits SciPy). Save the study and open "
                                  "it in the Full app or the standalone Plaque Stats app.")
        self._refresh_mode()
        return card

    def _build_plot_tab(self):
        w = QWidget(); outer = QVBoxLayout(w); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(6)
        outer.addWidget(self._build_customize_panel())
        # figure area, in its own scroll so the pinned-size canvas scrolls instead of stretching
        self.fig_scroll = QScrollArea(); self.fig_scroll.setWidgetResizable(True)
        self.fig_scroll.setFrameShape(QFrame.NoFrame)
        self.fig_holder = QWidget()
        self.fig_layout = QVBoxLayout(self.fig_holder)
        self.fig_layout.setContentsMargins(4, 4, 4, 4); self.fig_layout.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.fig_placeholder = QLabel("The violin plot appears here after you click Analyze.")
        self.fig_placeholder.setObjectName("Placeholder"); self.fig_placeholder.setAlignment(Qt.AlignCenter)
        self.fig_placeholder.setMinimumHeight(360)
        self.fig_layout.addWidget(self.fig_placeholder)
        self.fig_scroll.setWidget(self.fig_holder)
        outer.addWidget(self.fig_scroll, 1)
        return w

    def _build_customize_panel(self):
        box = QFrame(); box.setObjectName("SummaryCard")
        g = QGridLayout(box); g.setContentsMargins(12, 8, 12, 8); g.setHorizontalSpacing(12); g.setVerticalSpacing(4)

        def add(r, c, label, widget):
            cap = QLabel(label); cap.setObjectName("FieldLabel")
            g.addWidget(cap, r, c * 2); g.addWidget(widget, r, c * 2 + 1)

        # combos
        self.palette_sel = QComboBox()
        for lab, key in self.PALETTES_UI:
            self.palette_sel.addItem(lab, key)
        self.palette_custom = QLineEdit(); self.palette_custom.setPlaceholderText("or #hex,#hex,…")
        self.palette_custom.setMaximumWidth(150)
        self.fill_sel = QComboBox()
        for lab, key in [("Auto", "auto"), ("Neutral (grey)", "neutral"), ("Colored", "group")]:
            self.fill_sel.addItem(lab, key)
        self.center_sel = QComboBox()
        for lab, key in [("Mean", "mean"), ("Median", "median")]:
            self.center_sel.addItem(lab, key)
        self.error_sel = QComboBox()
        for lab, key in [("Auto", "auto"), ("SEM", "sem"), ("95% CI", "ci95"), ("SD", "sd"),
                         ("IQR", "iqr"), ("None", "none")]:
            self.error_sel.addItem(lab, key)
        self.annot_sel = QComboBox()
        for lab, key in [("Auto brackets", "auto"), ("All pairs", "all"), ("Adjacent", "adjacent"),
                         ("None", "none")]:
            self.annot_sel.addItem(lab, key)
        self.theme_sel = QComboBox()
        for lab, key in [("Clean", "clean"), ("Grid", "grid")]:
            self.theme_sel.addItem(lab, key)

        # text
        self.title_in = QLineEdit(); self.title_in.setPlaceholderText("(optional)")
        self.ylabel_in = QLineEdit(); self.ylabel_in.setPlaceholderText("(defaults to metric)")
        self.xlabel_in = QLineEdit(); self.xlabel_in.setPlaceholderText("(optional)")

        # numbers
        self.point_size = QDoubleSpinBox(); self.point_size.setRange(2, 40); self.point_size.setValue(16); self.point_size.setSingleStep(1)
        self.jitter = QDoubleSpinBox(); self.jitter.setRange(0, 0.30); self.jitter.setValue(0.08); self.jitter.setSingleStep(0.01); self.jitter.setDecimals(2)
        self.alpha = QDoubleSpinBox(); self.alpha.setRange(0.05, 1.0); self.alpha.setValue(0.55); self.alpha.setSingleStep(0.05); self.alpha.setDecimals(2)
        self.width_in = QDoubleSpinBox(); self.width_in.setRange(4, 16); self.width_in.setValue(8.4); self.width_in.setSingleStep(0.2); self.width_in.setDecimals(1)
        self.height_in = QDoubleSpinBox(); self.height_in.setRange(3, 12); self.height_in.setValue(5.4); self.height_in.setSingleStep(0.2); self.height_in.setDecimals(1)
        self.dpi_in = QSpinBox(); self.dpi_in.setRange(72, 600); self.dpi_in.setValue(300); self.dpi_in.setSingleStep(50)
        self.seed_in = QSpinBox(); self.seed_in.setRange(0, 9999); self.seed_in.setValue(7)

        # checkboxes
        self.show_points = QCheckBox("raw plaques"); self.show_points.setChecked(True)
        self.show_n = QCheckBox("n labels"); self.show_n.setChecked(True)
        self.show_value = QCheckBox("center value"); self.show_value.setChecked(True)
        self.legend_cb = QCheckBox("legend"); self.legend_cb.setChecked(True)
        self.logy_cb = QCheckBox("log Y"); self.logy_cb.setChecked(False)
        self.frame_cb = QCheckBox("full frame"); self.frame_cb.setChecked(False)

        # layout: 4 rows × 3 label/widget pairs
        add(0, 0, "Palette", self.palette_sel); add(0, 1, "Custom", self.palette_custom); add(0, 2, "Violin fill", self.fill_sel)
        add(1, 0, "Center", self.center_sel); add(1, 1, "Error bars", self.error_sel); add(1, 2, "Brackets", self.annot_sel)
        add(2, 0, "Title", self.title_in); add(2, 1, "Y label", self.ylabel_in); add(2, 2, "X label", self.xlabel_in)
        add(3, 0, "Point size", self.point_size); add(3, 1, "Jitter", self.jitter); add(3, 2, "Transparency", self.alpha)
        add(4, 0, "Width (in)", self.width_in); add(4, 1, "Height (in)", self.height_in); add(4, 2, "Export DPI", self.dpi_in)
        add(5, 0, "Theme", self.theme_sel); add(5, 1, "Seed", self.seed_in)
        cbrow = QHBoxLayout()
        for cb in (self.show_points, self.show_n, self.show_value, self.legend_cb, self.logy_cb, self.frame_cb):
            cbrow.addWidget(cb)
        cbrow.addStretch()
        g.addLayout(cbrow, 5, 4, 1, 2)

        # wire every cosmetic control to a live redraw
        for c in (self.palette_sel, self.fill_sel, self.center_sel, self.error_sel, self.annot_sel, self.theme_sel):
            c.currentIndexChanged.connect(self._on_cosmetic)
        for e in (self.palette_custom, self.title_in, self.ylabel_in, self.xlabel_in):
            e.editingFinished.connect(self._on_cosmetic)
        for sp in (self.point_size, self.jitter, self.alpha, self.width_in, self.height_in, self.dpi_in, self.seed_in):
            sp.valueChanged.connect(self._on_cosmetic)
        for cb in (self.show_points, self.show_n, self.show_value, self.legend_cb, self.logy_cb, self.frame_cb):
            cb.toggled.connect(self._on_cosmetic)
        return box

    def _table_view(self):
        tv = QTableView(); tv.setModel(PandasTableModel())
        tv.setAlternatingRowColors(True)
        tv.horizontalHeader().setStretchLastSection(True)
        tv.setSelectionBehavior(QAbstractItemView.SelectRows)
        tv.setEditTriggers(QAbstractItemView.NoEditTriggers)
        return tv

    def _build_summary_tab(self):
        w = QWidget(); v = QVBoxLayout(w); v.setContentsMargins(4, 6, 4, 4); v.setSpacing(4)
        v.addWidget(self._heading("Per sample"))
        self.tbl_group = self._table_view(); v.addWidget(self.tbl_group, 1)
        v.addWidget(self._heading("Per replicate plate (the experimental unit)"))
        self.tbl_rep = self._table_view(); v.addWidget(self.tbl_rep, 1)
        return w

    def _build_comparisons_tab(self):
        w = QWidget(); v = QVBoxLayout(w); v.setContentsMargins(4, 6, 4, 4); v.setSpacing(4)
        self.cmp_cap = self._heading("Pairwise comparisons")
        v.addWidget(self.cmp_cap)
        self.tbl_cmp = self._table_view(); v.addWidget(self.tbl_cmp, 1)
        return w

    def _build_report_tab(self):
        w = QWidget(); v = QVBoxLayout(w); v.setContentsMargins(4, 6, 4, 4); v.setSpacing(6)
        self.report = QPlainTextEdit(); self.report.setReadOnly(True)
        self.report.setStyleSheet("QPlainTextEdit{background:#ffffff;color:#1f2430;"
                                  "border:1px solid #c7ccd6;border-radius:8px;padding:8px;}")
        v.addWidget(self.report, 1)
        self.copy_btn = QPushButton("Copy report"); self.copy_btn.clicked.connect(self._copy_report)
        r = QHBoxLayout(); r.addWidget(self.copy_btn); r.addStretch()
        v.addLayout(r)
        return w

    @staticmethod
    def _heading(text):
        lab = QLabel(text); lab.setObjectName("SummaryHeading"); return lab

    # ================================================================ SAMPLE MODEL
    def _new_sample(self):
        dlg = _SampleDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        name, sub = dlg.values()
        if not name:
            self._warn("A sample needs a name."); return
        if any(s["group"] == name and s.get("subgroup", "") == sub for s in self._samples):
            self._warn("A sample '%s'%s already exists." % (name, (" · " + sub) if sub else "")); return
        self._samples.append({"group": name, "subgroup": sub})
        self._refresh_tree()
        self._select_sample(len(self._samples) - 1)
        self.window().statusBar().showMessage("Sample '%s' created — now add its plates." % name, 5000)

    def _edit_sample(self):
        idx = self._selected_sample_index()
        if idx is None:
            self._warn("Select a sample to edit."); return
        s = self._samples[idx]
        dlg = _SampleDialog(self, s["group"], s.get("subgroup", ""))
        if dlg.exec() != QDialog.Accepted:
            return
        name, sub = dlg.values()
        if not name:
            self._warn("A sample needs a name."); return
        if any(i != idx and o["group"] == name and o.get("subgroup", "") == sub
               for i, o in enumerate(self._samples)):
            self._warn("Another sample '%s'%s already exists." % (name, (" · " + sub) if sub else "")); return
        old_g, old_s = s["group"], s.get("subgroup", "")
        s["group"], s["subgroup"] = name, sub
        for p in self._plates:                       # move this sample's plates with it
            if p["group"] == old_g and p.get("subgroup", "") == old_s:
                p["group"], p["subgroup"] = name, sub
        self._refresh_tree()

    def _target_sample_index(self):
        """Where new plates go: the selected sample (or the sample of a selected plate), else the
        only sample if there's exactly one, else None."""
        idx = self._selected_sample_index()
        if idx is not None:
            return idx
        if len(self._samples) == 1:
            return 0
        return None

    def _add_current(self):
        idx = self._target_sample_index()
        if idx is None:
            self._warn("Create or select a sample first, then add the plate to it."); return
        mt = self.measure_tab
        if mt is None or getattr(mt, "model", None) is None:
            self._warn("Measure tab isn't ready yet."); return
        df = mt.model.dataframe()
        if df is None or len(df) == 0:
            self._warn("No measured plaques on the Measure tab. Open an image and detect first."); return
        dc, ac = _diam_col(df), _area_col(df)
        if dc is None:
            self._warn("Couldn't find a diameter column on the current measurement."); return
        diam = pd.to_numeric(df[dc], errors="coerce").dropna().tolist()
        area = pd.to_numeric(df[ac], errors="coerce").dropna().tolist() if ac else []
        self._add_plate(idx, diam, area)
        self._refresh_tree(); self._select_sample(idx)
        s = self._samples[idx]
        self.window().statusBar().showMessage(
            "Added a plate to '%s' (%d plaques)." % (s["group"], len(diam)), 5000)

    def _add_csvs(self):
        idx = self._target_sample_index()
        if idx is None:
            self._warn("Create or select a sample first, then add CSV(s) to it."); return
        paths, _ = QFileDialog.getOpenFileNames(self, "Add per-plaque CSV(s) as replicate plates", "",
                                                "CSV files (*.csv);;All files (*.*)")
        if not paths:
            return
        added = 0
        for p in paths:
            r = self._parse_csv(p)
            if r is None:
                continue
            self._add_plate(idx, r[0], r[1], rep=os.path.splitext(os.path.basename(p))[0])
            added += 1
        if added:
            self._refresh_tree(); self._select_sample(idx)
            self.window().statusBar().showMessage("Added %d replicate plate(s)." % added, 5000)

    def _parse_csv(self, path):
        """Read a per-plaque CSV → (diam list, area list), or None with a warning."""
        try:
            df = pd.read_csv(path)
        except Exception as e:
            self._warn("Could not read %s: %s" % (os.path.basename(path), e)); return None
        dc, ac = _diam_col(df), _area_col(df)
        if dc is None:
            num = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
            if len(num) == 1:
                dc = num[0]
            else:
                self._warn("No diameter column in %s — skipped." % os.path.basename(path)); return None
        diam = pd.to_numeric(df[dc], errors="coerce").dropna().tolist()
        area = pd.to_numeric(df[ac], errors="coerce").dropna().tolist() if ac else []
        return diam, area

    def _import_assign(self):
        """Pick many plate CSVs and map each (one plate) to a sample in one dialog → real replicates."""
        paths, _ = QFileDialog.getOpenFileNames(self, "Import plate CSVs and assign to samples", "",
                                                "CSV files (*.csv);;All files (*.*)")
        if not paths:
            return
        parsed = []
        for p in paths:
            r = self._parse_csv(p)
            if r is None:
                continue
            parsed.append({"path": p, "stem": os.path.splitext(os.path.basename(p))[0],
                           "n": len(r[0]), "diam": r[0], "area": r[1]})
        if not parsed:
            return
        dlg = _AssignDialog(self, parsed, self._samples)
        if dlg.exec() != QDialog.Accepted:
            return
        self._apply_assignments(dlg.rows())

    def _apply_assignments(self, rows):
        """rows: [{sample, subgroup, replicate, diam, area}] — each becomes ONE plate under its sample
        (created if new). The many-CSVs → real-replicates flow (each CSV is a plate)."""
        added = 0
        for r in rows:
            g = (r.get("sample") or "").strip()
            if not g:
                continue
            sub = (r.get("subgroup") or "").strip()
            si = next((i for i, s in enumerate(self._samples)
                       if s["group"] == g and s.get("subgroup", "") == sub), None)
            if si is None:
                self._samples.append({"group": g, "subgroup": sub}); si = len(self._samples) - 1
            self._add_plate(si, r["diam"], r.get("area") or [], rep=(r.get("replicate") or "").strip() or None)
            added += 1
        if added:
            self._refresh_tree()
            self.window().statusBar().showMessage(
                "Imported %d plate(s) across %d sample(s)." % (added, len(self._samples)), 6000)
        return added

    def _next_auto_rep(self, group, subgroup=""):
        """A plate id not already used within this sample (group, subgroup). Per-sample uniqueness
        keeps the stats engine from ever pooling two plates into one mean, and survives Load study."""
        used = {p["replicate"] for p in self._plates
                if p["group"] == group and p.get("subgroup", "") == subgroup}
        i = 1
        while ("plate%d" % i) in used:
            i += 1
        return "plate%d" % i

    def _add_plate(self, s_idx, diam, area, rep=None):
        s = self._samples[s_idx]
        g, sub = s["group"], s.get("subgroup", "")
        if not rep or any(p["group"] == g and p.get("subgroup", "") == sub and p["replicate"] == rep
                          for p in self._plates):
            rep = self._next_auto_rep(g, sub)        # blank or clashing id → next free one
        self._plates.append({"group": g, "subgroup": sub, "replicate": rep,
                             "diam": list(diam), "area": list(area)})

    def _plates_of(self, s):
        return [p for p in self._plates
                if p["group"] == s["group"] and p.get("subgroup", "") == s.get("subgroup", "")]

    # ---------------------------------------------------------------- tree view
    def _refresh_tree(self):
        self._invalidate_analysis()
        self.tree.blockSignals(True)
        self.tree.clear()
        total_plates = 0
        for si, s in enumerate(self._samples):
            plates = self._plates_of(s)
            total_plates += len(plates)
            means = [float(np.mean(p["diam"])) for p in plates if p.get("diam")]
            roll = np.mean(means) if means else float("nan")
            top = QTreeWidgetItem([
                s["group"],
                s.get("subgroup", "") or "—",
                "%d plate(s) · %d plaques" % (len(plates), sum(len(p.get("diam") or []) for p in plates)),
                ("%.3f" % roll) if means else "—"])
            top.setData(0, Qt.UserRole, ("sample", si))
            f = top.font(0); f.setBold(True)
            for c in range(4):
                top.setFont(c, f)
            self.tree.addTopLevelItem(top)
            for p in plates:
                d = p.get("diam") or []
                child = QTreeWidgetItem(["    " + p["replicate"], "",
                                         str(len(d)), ("%.3f" % np.mean(d)) if d else "—"])
                child.setData(0, Qt.UserRole, ("plate", id(p)))
                top.addChild(child)
            top.setExpanded(True)
        self.tree.blockSignals(False)
        n = len(self._samples)
        if n == 0:
            self.count_lbl.setText("No samples yet — click “New sample”, then add its plates.")
        else:
            self.count_lbl.setText("%d sample(s) · %d plate(s) compiled." % (n, total_plates))
        self._refresh_mode()

    def _on_tree_selection(self):
        pass    # selection just drives where "Add" goes; nothing else to do

    def _selected_sample_index(self):
        it = self.tree.currentItem()
        if it is None:
            return None
        data = it.data(0, Qt.UserRole)
        if not data:
            return None
        kind, ref = data
        if kind == "sample":
            return ref
        # a plate is selected → its parent sample
        parent = it.parent()
        if parent is not None:
            pd_ = parent.data(0, Qt.UserRole)
            if pd_ and pd_[0] == "sample":
                return pd_[1]
        return None

    def _select_sample(self, idx):
        if 0 <= idx < self.tree.topLevelItemCount():
            self.tree.setCurrentItem(self.tree.topLevelItem(idx))

    def _remove_selected(self):
        it = self.tree.currentItem()
        if it is None:
            self._warn("Select a sample or a plate to remove."); return
        kind, ref = it.data(0, Qt.UserRole)
        if kind == "sample":
            s = self._samples[ref]
            self._plates = [p for p in self._plates if not (p["group"] == s["group"]
                            and p.get("subgroup", "") == s.get("subgroup", ""))]
            del self._samples[ref]
        else:   # a single plate — match by identity
            self._plates = [p for p in self._plates if id(p) != ref]
        self._refresh_tree()

    def _clear_all(self):
        if not self._samples and not self._plates:
            return
        if QMessageBox.question(self, "Clear all",
                                "Remove all samples and plates?") == QMessageBox.Yes:
            self._samples = []; self._plates = []
            self._refresh_tree()

    # ================================================================ PERSISTENCE
    def _tidy_frame(self):
        rows = []
        for pl in self._plates:
            diam = pl.get("diam") or []
            area = pl.get("area") or []
            for i in range(max(len(diam), len(area))):
                rows.append({"group": pl["group"], "subgroup": pl.get("subgroup", ""),
                             "replicate": pl["replicate"],
                             "diameter_mm": diam[i] if i < len(diam) else np.nan,
                             "area_mm2": area[i] if i < len(area) else np.nan})
        return pd.DataFrame(rows, columns=["group", "subgroup", "replicate", "diameter_mm", "area_mm2"])

    def _long_frame(self):
        """Standalone-ready LONG format: one row per (plaque, metric)."""
        rows = []
        for pl in self._plates:
            for metric, key in (("diameter_mm", "diam"), ("area_mm2", "area")):
                for val in (pl.get(key) or []):
                    rows.append({"group": pl["group"], "subgroup": pl.get("subgroup", ""),
                                 "replicate": pl["replicate"], "metric": metric, "value": val})
        return pd.DataFrame(rows, columns=["group", "subgroup", "replicate", "metric", "value"])

    def _save_study(self):
        if not self._plates:
            self._warn("Nothing to save yet."); return
        path, _ = QFileDialog.getSaveFileName(self, "Save study", "plaque_study.csv", "CSV (*.csv)")
        if not path:
            return
        self._tidy_frame().to_csv(path, index=False)
        self.window().statusBar().showMessage("Study saved: %s" % path, 5000)

    def _load_study(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load study", "", "CSV (*.csv);;All files (*.*)")
        if not path:
            return
        try:
            df = pd.read_csv(path)
        except Exception as e:
            self._warn("Could not read study: %s" % e); return
        self._load_frame(df, os.path.basename(path))

    def _load_frame(self, df, source="study"):
        df = df.copy()
        df.columns = [str(c).strip().lower() for c in df.columns]
        if "group" not in df.columns:
            self._warn("The study file needs a 'group' column."); return
        scol = "subgroup" if "subgroup" in df.columns else None
        rcol = "replicate" if "replicate" in df.columns else None
        dcol = _diam_col(df); acol = _area_col(df)
        if dcol is None and acol is None:
            self._warn("The study file needs a diameter or area column."); return
        self._plates = []; self._samples = []
        has_rep = rcol is not None
        keys = ["group"] + ([scol] if scol else []) + ([rcol] if has_rep else [])
        # sort=False preserves the saved sample/plate order (drives x-axis + the default control)
        for key, sub in df.groupby(keys, dropna=False, sort=False):
            key = key if isinstance(key, tuple) else (key,)
            kd = dict(zip(keys, key))
            g = str(kd.get("group", ""))
            sg = "" if not scol or pd.isna(kd.get(scol)) else str(kd.get(scol))
            diam = pd.to_numeric(sub[dcol], errors="coerce").dropna().tolist() if dcol else []
            area = pd.to_numeric(sub[acol], errors="coerce").dropna().tolist() if acol else []
            # NO replicate column → all plaques of a sample are ONE pooled plate, so the stats fall
            # back to the plaque unit + the pseudoreplication warning. Never fabricate a fake plate
            # per plaque (that would report per-plaque stats as if they were valid plate-level stats).
            rep = str(kd.get(rcol, "")) if has_rep else "plate1"
            self._plates.append({"group": g, "subgroup": sg, "replicate": rep, "diam": diam, "area": area})
            if not any(x["group"] == g and x["subgroup"] == sg for x in self._samples):
                self._samples.append({"group": g, "subgroup": sg})
        self._refresh_tree()
        self.window().statusBar().showMessage(
            "Loaded %d sample(s) · %d plate(s) from %s"
            % (len(self._samples), len(self._plates), source), 5000)

    # ================================================================ ANALYSIS
    @staticmethod
    def _is_tagged(sub):
        s = str(sub).strip()
        return bool(s) and s.lower() != "nan"

    def _ordered_groups(self, present=None):
        out = []
        for s in self._samples:
            g = s["group"]
            if g and g not in out and (present is None or g in present):
                out.append(g)
        return out

    def _ordered_subs(self, present=None):
        out = []
        for s in self._samples:
            sub = (s.get("subgroup") or "").strip()
            if sub and sub not in out and (present is None or sub in present):
                out.append(sub)
        return out

    def _opts(self, metric_key):
        from plaque_stats import plaque_stats as ps
        o = dict(ps.DEFAULTS)
        # palette: custom hex wins, else named
        custom = self.palette_custom.text().strip()
        cols = [c.strip() for c in custom.split(",") if c.strip()] if custom else []
        o["palette"] = cols if cols else ps.PALETTES.get(self.palette_sel.currentData(), ps.OKABE_ITO)
        o["violin_fill"] = self.fill_sel.currentData()
        o["center"] = self.center_sel.currentData()
        o["error"] = self.error_sel.currentData()
        o["annotate"] = self.annot_sel.currentData()
        o["theme"] = self.theme_sel.currentData()
        o["show_points"] = self.show_points.isChecked()
        o["show_n"] = self.show_n.isChecked()
        o["show_value"] = self.show_value.isChecked()
        o["legend"] = self.legend_cb.isChecked()
        o["log_y"] = self.logy_cb.isChecked()
        o["frame"] = self.frame_cb.isChecked()
        o["point_size"] = float(self.point_size.value())
        o["jitter"] = float(self.jitter.value())
        o["violin_alpha"] = float(self.alpha.value())
        o["width"] = float(self.width_in.value())
        o["height"] = float(self.height_in.value())
        o["dpi"] = int(self.dpi_in.value())
        o["seed"] = int(self.seed_in.value())
        default_y = "Diameter (mm)" if metric_key == "diam" else "Area (mm²)"
        o["ylabel"] = self.ylabel_in.text().strip() or default_y
        o["title"] = self.title_in.text().strip() or None
        o["xlabel"] = self.xlabel_in.text().strip()
        return o

    def _reanalyse_if_ready(self, *_):
        if not self._building and self._last is not None:
            self._analyse()

    def _on_cosmetic(self, *_):
        if not self._building and self._last is not None:
            self._redraw()

    def _analyse(self):
        self.err.setText("")
        if len(self._plates) < 2:
            self._warn("Add at least two plates (ideally ≥2 samples) before analyzing."); return
        metric_key = self.metric_sel.currentData()
        vcol = "diameter_mm" if metric_key == "diam" else "area_mm2"
        metric_name = "Diameter (mm)" if metric_key == "diam" else "Area (mm²)"
        tidy = self._tidy_frame()
        df = tidy.rename(columns={vcol: "value"})[["group", "subgroup", "replicate", "value"]].copy()
        df = df.dropna(subset=["value"])
        if df.empty:
            self._warn("No %s values found — did you measure that metric?" % metric_name); return
        # decide the mode from the SAMPLE tags, not from the (metric-filtered) rows — so switching
        # metric can't silently flip grouped↔single just because some tagged plates lack that metric
        has_sub = any(self._is_tagged(p.get("subgroup", "")) for p in self._plates)
        try:
            ok = (self._analyse_grouped(df, metric_name, metric_key) if has_sub
                  else self._analyse_single(df.drop(columns=["subgroup"]), metric_name, metric_key))
        except Exception as e:
            self._warn("Analysis failed: %s" % e); return
        for b in self._export_buttons:
            b.setEnabled(bool(ok))

    def _analyse_single(self, df, metric_name, metric_key):
        from plaque_stats import plaque_stats as ps
        present = set(df["group"])
        order = self._ordered_groups(present) or list(dict.fromkeys(df["group"].tolist()))
        parametric = self.param_sel.currentData()
        omni, posthoc, unit, have_rep = ps.run_stats(df, order, "auto", parametric)
        summ = ps.group_summary(df, order)
        rep = ps.replicate_means(df)
        src = rep if (unit == "replicate" and rep is not None) else df
        unit_means = src.groupby("group")["value"].mean().to_dict()
        pairwise = pd.DataFrame([{"group_a": a, "group_b": b,
                                  "mean_a": round(unit_means.get(a, float("nan")), 4),
                                  "mean_b": round(unit_means.get(b, float("nan")), 4),
                                  "diff": round(unit_means.get(a, float("nan")) - unit_means.get(b, float("nan")), 4),
                                  "p_adj": p, "signif": ps.stars(p)}
                                 for (a, b), p in posthoc.items()])
        self._last = ("single", {"df": df, "order": order, "posthoc": posthoc,
                                  "metric_name": metric_name, "metric_key": metric_key,
                                  "summary": summ, "replicates": rep, "pairwise": pairwise})
        self._redraw()

        self._chips["groups"].setText(str(len(order)))
        self._chips["plates"].setText(str(len(self._plates)))
        self._chips["unit"].setText("plate" if unit == "replicate" else "plaque")
        self._chips["test"].setText(str(omni.get("test", "—")))
        self._chips["p"].setText(self._pfmt(omni.get("p")))
        eff = omni.get("effect", {}) or {}
        ek = next(iter(eff), None)
        self._chips["effect"].setText(("%s=%.2f" % (ek.split("_")[0], eff[ek])) if ek else "—")

        self._set_table(self.tbl_group, _round_df(summ))
        self._set_table(self.tbl_rep, _round_df(rep) if rep is not None else pd.DataFrame())
        self.cmp_cap.setText("Pairwise comparisons")
        self._set_table(self.tbl_cmp, pairwise)

        lines = []
        unit_note = ("plate means (the plate is the experimental unit; avoids pseudoreplication)"
                     if unit == "replicate" else
                     "per-plaque values (NO replicate structure — add plate ids for defensible stats)")
        lines.append("%s across %d samples, on %s." % (metric_name, len(order), unit_note))
        lines.append("Omnibus: %s, p = %s%s." % (omni.get("test", "—"), self._pfmt(omni.get("p")),
                     ("; %s = %.3f" % (ek.replace("_", " "), eff[ek])) if ek else ""))
        if posthoc:
            lines.append("Post-hoc — " + "; ".join(
                "%s vs %s: p = %s (%s)" % (a, b, self._pfmt(p), ps.stars(p))
                for (a, b), p in posthoc.items()) + ".")
        for w in omni.get("warnings", []):
            lines.append("⚠ " + w)
        self.report.setPlainText("\n".join(lines))
        self.window().statusBar().showMessage("Analyzed %d samples (%s)." % (len(order), omni.get("test")), 5000)
        return True

    def _analyse_grouped(self, df, metric_name, metric_key):
        from plaque_stats import plaque_stats as ps
        df = df.copy(); df["subgroup"] = df["subgroup"].astype(str).str.strip()
        df = df[df["subgroup"].map(self._is_tagged)]
        analyzed = int(df.drop_duplicates(["group", "subgroup", "replicate"]).shape[0])
        excluded = sum(1 for p in self._plates if not self._is_tagged(p.get("subgroup", "")))
        group_order = self._ordered_groups(set(df["group"])) or list(dict.fromkeys(df["group"].tolist()))
        sub_order = self._ordered_subs(set(df["subgroup"])) or list(dict.fromkeys(df["subgroup"].tolist()))
        if not sub_order:
            self._warn("No plates carry a 2nd-factor tag."); return False
        control = self.control_sel.currentText().strip() or sub_order[0]
        if control not in sub_order:
            self._warn("Pick a control value that exists in your 2nd-factor tags."); return False
        if len(sub_order) < 2:
            self._warn("Only one 2nd-factor value ('%s') after excluding untagged plates — nothing to "
                       "compare against the control. Clear the 2nd-factor tags to analyze these as "
                       "single-factor samples instead." % control); return False
        parametric = self.param_sel.currentData()
        summ, comp, unit = ps.grouped_stats(df, group_order, sub_order, control, parametric)
        pm = ps._plate_means_gs(df)
        self._last = ("grouped", {"df": df, "group_order": group_order, "sub_order": sub_order,
                                  "control": control, "comparisons": comp,
                                  "metric_name": metric_name, "metric_key": metric_key,
                                  "summary": summ, "replicates": pm})
        self._redraw()

        self._chips["groups"].setText("%d×%d" % (len(group_order), len(sub_order)))
        self._chips["plates"].setText(str(analyzed))
        self._chips["unit"].setText("plate" if unit == "replicate" else "plaque")
        self._chips["test"].setText(str(comp["test"].iloc[0]) if len(comp) else "—")
        self._chips["p"].setText("per row" if len(comp) else "—")
        self._chips["effect"].setText("vs %s" % control)

        self._set_table(self.tbl_group, _round_df(summ))
        self._set_table(self.tbl_rep, _round_df(pm) if pm is not None else pd.DataFrame())
        self.cmp_cap.setText("Control comparisons (vs %s)" % control)
        self._set_table(self.tbl_cmp, _round_df(comp))

        lines = ["%s — each 2nd-factor value vs the control '%s', within each sample, on %s." % (
            metric_name, control,
            "plate means (plate = unit)" if unit == "replicate" else "per-plaque values (no replicates)")]
        for _, r in comp.iterrows():
            lines.append("%s · %s: %+.1f%% vs control (%s, p = %s, %s; Cohen's d = %.2f)." % (
                r["group"], r["subgroup"], r["change_pct"], r["test"], self._pfmt(r["p"]),
                r["signif"], r["cohens_d"]))
        if unit != "replicate":
            lines.append("⚠ No replicate structure — add plate ids for defensible stats.")
        if excluded:
            lines.append("⚠ %d plate(s) without a 2nd-factor tag were EXCLUDED (%d analyzed). Clear all "
                         "2nd-factor tags to compare every plate as single-factor samples." % (excluded, analyzed))
            self.err.setText("Note: %d untagged plate(s) excluded; %d analyzed — see the report."
                             % (excluded, analyzed))
        self.report.setPlainText("\n".join(lines))
        self.window().statusBar().showMessage(
            "Grouped comparison vs '%s' across %d sample(s)." % (control, len(group_order)), 5000)
        return True

    # ---------------------------------------------------------------- figure
    def _build_fig(self, opts):
        from plaque_stats import plaque_stats as ps
        kind, pl = self._last
        if kind == "single":
            return ps.plot_violin(pl["df"], pl["order"], opts, pl["metric_name"], pl["posthoc"])
        o = dict(opts); o["_sublabel"] = "2nd factor"
        return ps.plot_grouped(pl["df"], pl["group_order"], pl["sub_order"], pl["control"], o,
                               pl["metric_name"], pl["comparisons"])

    def _redraw(self):
        if self._last is None:
            return
        import matplotlib.pyplot as plt
        opts = self._opts(self._last[1]["metric_key"])
        before = set(plt.get_fignums())
        try:
            fig = self._build_fig(opts)
        except Exception as e:
            for n in set(plt.get_fignums()) - before:    # close any half-built figure the error left open
                plt.close(n)
            self._warn("Could not draw: %s" % e); return
        self._show_fig(fig)

    def _clear_fig_area(self, restore_placeholder=False):
        """Remove the current figure container (or placeholder) from the plot area and close its
        figure. Optionally restore the 'appears here' placeholder."""
        import matplotlib.pyplot as plt
        if self._fig_container is not None:
            self.fig_layout.removeWidget(self._fig_container); self._fig_container.setParent(None)
            self._fig_container = None
        self.canvas = None; self.toolbar = None
        if self.fig_placeholder is not None:
            self.fig_layout.removeWidget(self.fig_placeholder); self.fig_placeholder.setParent(None)
            self.fig_placeholder = None
        if self._last_fig is not None:
            try:
                plt.close(self._last_fig)
            except Exception:
                pass
            self._last_fig = None
        if restore_placeholder:
            self.fig_placeholder = QLabel("The violin plot appears here after you click Analyze.")
            self.fig_placeholder.setObjectName("Placeholder"); self.fig_placeholder.setAlignment(Qt.AlignCenter)
            self.fig_placeholder.setMinimumHeight(360)
            self.fig_layout.addWidget(self.fig_placeholder)

    def _show_fig(self, fig):
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
        from matplotlib.backends.backend_qtagg import NavigationToolbar2QT
        self._clear_fig_area()
        # pin the canvas to the figure's true pixel size so its aspect never distorts; scroll if big
        w_in, h_in = fig.get_size_inches()
        px_w, px_h = int(round(w_in * 96)), int(round(h_in * 96))
        container = QWidget()
        cl = QVBoxLayout(container); cl.setContentsMargins(0, 0, 0, 0); cl.setSpacing(2)
        canvas = FigureCanvas(fig)
        canvas.setFixedSize(px_w, px_h)
        # parent the toolbar to the CONTAINER (not the tab) so it embeds above the figure and never
        # pops out as a floating window
        toolbar = NavigationToolbar2QT(canvas, container)
        cl.addWidget(toolbar); cl.addWidget(canvas)
        container.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.fig_layout.addWidget(container, 0, Qt.AlignHCenter | Qt.AlignTop)
        self._fig_container = container
        self.canvas, self.toolbar, self._last_fig = canvas, toolbar, fig
        canvas.draw()

    # ---------------------------------------------------------------- results helpers
    def _set_table(self, view, df):
        model = view.model()
        if isinstance(model, PandasTableModel):
            model.set_dataframe(df if df is not None else pd.DataFrame())
        else:
            view.setModel(PandasTableModel(df))

    def _invalidate_analysis(self):
        """A change to the compiled samples makes a prior analysis stale — clear everything shown or
        saved so nothing that no longer matches the data survives. Re-Analyze to recompute."""
        self._last = None
        if getattr(self, "_fig_container", None) is not None or getattr(self, "fig_placeholder", None) is None:
            self._clear_fig_area(restore_placeholder=True)
        for v in getattr(self, "_chips", {}).values():
            v.setText("—")
        for name in ("tbl_group", "tbl_rep", "tbl_cmp"):
            tv = getattr(self, name, None)
            if tv is not None:
                self._set_table(tv, pd.DataFrame())
        if hasattr(self, "report"):
            self.report.clear()
        for b in getattr(self, "_export_buttons", []):
            b.setEnabled(False)

    def _refresh_mode(self):
        subs = [p.get("subgroup", "").strip() for p in self._plates]
        has_sub = any(subs)
        uniq_sub = self._ordered_subs()
        cur = self.control_sel.currentText()
        self.control_sel.blockSignals(True)
        self.control_sel.clear()
        for s in uniq_sub:
            self.control_sel.addItem(s)
        if cur in uniq_sub:
            self.control_sel.setCurrentText(cur)
        self.control_sel.blockSignals(False)
        for w in (self.ctrl_cap, self.control_sel):
            w.setVisible(has_sub)
        groups = self._ordered_groups()
        if not self._stats_ok:
            return
        if not self._plates:
            self.mode_lbl.setText("Create samples and add plates, then Analyze. The mode is chosen "
                                  "automatically from your samples.")
        elif has_sub:
            self.mode_lbl.setText("Grouped control-comparison: %d sample name(s) × %d values of the 2nd "
                                  "factor — each value tested against the control you pick." %
                                  (len(groups), len(uniq_sub)))
        else:
            self.mode_lbl.setText("Single-factor: %d sample(s) compared (violin + ANOVA/Tukey or t-test). "
                                  "Give samples a 2nd factor to switch to control-comparison." % len(groups))

    # ================================================================ EXPORTS
    def _save_fig(self):
        if self._last is None:
            return
        path, sel = QFileDialog.getSaveFileName(
            self, "Save figure", "plaque_figure.png",
            "PNG image (*.png);;SVG — vector, editable (*.svg);;PDF — vector (*.pdf);;"
            "TIFF — journal raster (*.tiff);;EPS — vector (*.eps)")
        if not path:
            return
        ext_for = {"PNG": ".png", "SVG": ".svg", "PDF": ".pdf", "TIFF": ".tiff", "EPS": ".eps"}
        want = next((e for k, e in ext_for.items() if (sel or "").startswith(k)), None)
        if want:
            path = os.path.splitext(path)[0] + want
        ext = os.path.splitext(path)[1].lower()
        import matplotlib as mpl
        mpl.rcParams["svg.fonttype"] = "none"; mpl.rcParams["pdf.fonttype"] = 42; mpl.rcParams["ps.fonttype"] = 42
        opts = self._opts(self._last[1]["metric_key"])
        dpi = 600 if ext in (".tif", ".tiff") else int(opts["dpi"])
        # render a FRESH figure at exactly the configured size/dpi (independent of the on-screen canvas)
        import matplotlib.pyplot as plt
        fig = None
        try:
            fig = self._build_fig(opts)
            kw = {"dpi": dpi, "bbox_inches": "tight", "facecolor": "white"}
            if ext in (".tif", ".tiff"):
                kw["pil_kwargs"] = {"compression": "tiff_lzw"}
            fig.savefig(path, **kw)
        except Exception as e:
            self._warn("Could not save figure: %s" % e); return
        finally:
            if fig is not None:
                plt.close(fig)                    # always release the export figure
        self.window().statusBar().showMessage("Figure saved (%s, %d dpi): %s" % (ext.lstrip("."), dpi, path), 6000)

    def _save_summary(self):
        if self._last is None:
            return
        kind, pl = self._last
        path, _ = QFileDialog.getSaveFileName(self, "Save summary", "plaque_summary.csv", "CSV (*.csv)")
        if not path:
            return
        pl["summary"].to_csv(path, index=False)
        extra = "comparisons" if kind == "grouped" else "pairwise"
        if pl.get(extra) is not None and len(pl[extra]):
            pl[extra].to_csv(os.path.splitext(path)[0] + "_" + extra + ".csv", index=False)
        self.window().statusBar().showMessage("Summary (+ %s) saved next to it." % extra, 5000)

    def _save_data_wide(self):
        if not self._plates:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save compiled data (wide)", "plaque_compiled_wide.csv", "CSV (*.csv)")
        if path:
            self._tidy_frame().to_csv(path, index=False)
            self.window().statusBar().showMessage("Wide per-plaque data saved: %s" % path, 5000)

    def _save_data_long(self):
        if not self._plates:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save compiled data (long, standalone-ready)",
                                              "plaque_compiled_long.csv", "CSV (*.csv)")
        if path:
            self._long_frame().to_csv(path, index=False)
            self.window().statusBar().showMessage("Long-format data saved (drops into the standalone app): %s" % path, 6000)

    def _export_zip(self):
        if self._last is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export everything (ZIP)", "plaque_analysis.zip", "ZIP (*.zip)")
        if not path:
            return
        try:
            self._write_everything(path)
        except Exception as e:
            self._warn("Export failed: %s" % e); return
        self.window().statusBar().showMessage("Exported everything: %s" % path, 6000)

    def _write_everything(self, path):
        """Build the full standalone-parity bundle at `path` (figure in every format + summaries +
        pairwise + report.md + run_config.json + table images + compiled data)."""
        import shutil
        from datetime import datetime
        from plaque_stats import plaque_stats as ps
        kind, pl = self._last
        metric_key = pl["metric_key"]
        vcol = "diameter_mm" if metric_key == "diam" else "area_mm2"
        opts = self._opts(metric_key)
        tmp = tempfile.mkdtemp(prefix="plaque_zip_")
        try:
            data_csv = os.path.join(tmp, "compiled.csv")
            self._tidy_frame().to_csv(data_csv, index=False)
            out = os.path.join(tmp, "out"); os.makedirs(out, exist_ok=True)
            args = dict(opts)
            args.update({"data": data_csv, "group": "group", "value": vcol, "replicate": "replicate",
                         "metric": None, "unit": "auto", "parametric": self.param_sel.currentData(),
                         "formats": ["png", "svg", "pdf", "tiff"], "dpi": int(opts["dpi"]),
                         "stats_table": True, "out": out,
                         # use the SAME group order as the on-screen figure / Save-figure (not add order)
                         "order": pl["group_order"] if kind == "grouped" else pl["order"],
                         "_stamp": datetime.now().strftime("%Y-%m-%d %H:%M")})
            if kind == "grouped":
                args.update({"subgroup": "subgroup", "control": pl["control"]})
            ps.run(args)
            # also drop the standalone-ready long + wide CSVs in the bundle
            self._long_frame().to_csv(os.path.join(out, "compiled_long.csv"), index=False)
            self._tidy_frame().to_csv(os.path.join(out, "compiled_wide.csv"), index=False)
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
                for root, _dirs, files in os.walk(out):
                    for f in files:
                        fp = os.path.join(root, f)
                        z.write(fp, os.path.relpath(fp, out))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)     # never leak the working copy
        return path

    def _copy_report(self):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.report.toPlainText())
        self.window().statusBar().showMessage("Report copied to the clipboard.", 3000)

    # ================================================================ misc
    @staticmethod
    def _pfmt(p):
        try:
            p = float(p)
        except (TypeError, ValueError):
            return "—"
        if p != p:
            return "—"
        return "< 0.001" if p < 1e-3 else "%.3f" % p

    def _warn(self, msg):
        self.err.setText(msg)
        self.window().statusBar().showMessage(msg, 6000)

    def _open_doc(self, name):
        try:
            from app.ui import _open_doc
            _open_doc(name, self)
        except Exception:
            pass
