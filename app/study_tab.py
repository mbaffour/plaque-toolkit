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
(`plaque_stats/plaque_stats.py`), reused here directly, so results are identical. The ZIP export
hands the engine the SAME in-memory table and the SAME options as the screen (CT-R1 F1/F2/F14).
"""
import csv
import io
import json
import os
import re
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
    QSizePolicy, QTableWidget, QTableWidgetItem, QInputDialog,
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


def _engine():
    """The statistics engine module (plaque_stats/plaque_stats.py). When something has already
    imported the engine FILE under the top-level name 'plaque_stats' (the standalone app's own
    layout), that module is the engine itself."""
    import sys
    try:
        from plaque_stats import plaque_stats as ps
        return ps
    except ImportError:
        m = sys.modules.get("plaque_stats")
        if m is not None and hasattr(m, "run_stats"):
            return m
        raise


def _legend_key():
    """The legend-key module the engine draws its keys with (see _engine)."""
    try:
        from plaque_stats import legend_key
        return legend_key
    except ImportError:
        return _engine()._lk


# ------------------------------------------------------------------ small helpers
def _shadow(widget, blur=18, dy=2, alpha=40):
    try:
        eff = QGraphicsDropShadowEffect(widget)
        eff.setBlurRadius(blur); eff.setXOffset(0); eff.setYOffset(dy)
        eff.setColor(QColor(0, 0, 0, alpha)); widget.setGraphicsEffect(eff)
    except Exception:
        pass


def _flow(items, hspace=8, vspace=6):
    """A widget laying `items` left to right and wrapping to the next line when out of width
    (CT-R2 F16: the Analyze tab needed ~1100 px, so buttons fell off narrow windows)."""
    from app.plaque_canvas import FlowLayout
    w = QWidget()
    fl = FlowLayout(w, margin=0, hspace=hspace, vspace=vspace)
    for it in items:
        fl.addWidget(it)
    return w


def _pair(label, widget, label_w=None, widget_w=None):
    """A caption and its control kept together on one line inside a flow."""
    w = QWidget()
    h = QHBoxLayout(w); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(6)
    if label is not None:
        if label_w:
            label.setFixedWidth(label_w)
        h.addWidget(label)
    if widget_w:
        widget.setFixedWidth(widget_w)
    h.addWidget(widget)
    return w


# CT-R1 F6: a column is the diameter only when its name says diameter AND millimetres
# ("DIAMETER_MM", "diameter_mm", "Diameter (mm)"). "Diameter (µm)", "DIAMETER_PXL", an area-only
# file or a lone "count" column used to be read as diameters in mm.
_MM_RE = re.compile(r"(^|[^a-z])mm(2|²|\^2)?([^a-z0-9]|$)")
_NOT_MM_RE = re.compile(r"px|pxl|pix|µm|um\b|micro|nm\b|cm\b")


def _flag_col(df):
    """The QC_FLAG column, whatever its case ('QC_FLAG', 'qc_flag', 'Qc_Flag'), or None
    (CT-R2 F10: a lower-case header used to be ignored and every flagged row kept)."""
    for c in getattr(df, "columns", []):
        if str(c).strip().lower() == "qc_flag":
            return c
    return None


def _size_mask(df):
    """(list of bools: may this row's size enter a summary, its flag cells or None). The rule is
    plaque_qc.size_ok, applied to each cell exactly as it is in the file -- never re-derived here
    (CT-R1 detection D10a: CORE? and NO_SIZE plaques count on their plate, but their diameter is
    another edge definition). A table without a QC_FLAG column keeps every row."""
    fc = _flag_col(df)
    if df is None or fc is None:
        return [True] * (0 if df is None else len(df)), None
    import plaque_qc
    flags = df[fc].tolist()
    return [bool(plaque_qc.size_ok(f)) for f in flags], flags


def _left_out_account(flags, keep):
    """{'n': plaques left out, 'counts': plaque_qc's counts (opaque here), 'why': its phrase}."""
    if flags is None:
        return {"n": 0, "counts": {}, "why": ""}
    import plaque_qc
    out = [f for f, k in zip(flags, keep) if not k]
    counts = plaque_qc.size_left_out_counts(out) if out else {}
    return {"n": len(out), "counts": counts,
            "why": plaque_qc.left_out_phrase(counts) if out else ""}


def _sum_counts(accounts):
    tot = {}
    for a in accounts:
        for k, v in (a.get("counts") or {}).items():
            tot[k] = tot.get(k, 0) + int(v or 0)
    return tot


def _left_out_text(accounts):
    """'; 26 plaques outlined at the dark centre only and 1 split piece … were left out of the
    sizes' over the plates actually added (CT-R2 F9), or ''. CT-R3 F8: the verb agrees with the
    number ('1 plaque outlined at the dark centre only was left out', not '1 … were')."""
    import plaque_qc
    accounts = list(accounts)
    n = sum(a.get("n", 0) for a in accounts)
    if not n:
        return ""
    said = plaque_qc.left_out_said(_sum_counts(accounts), "left out of the sizes")
    return "; %s" % (said or "%d flagged plaque%s %s left out of the sizes"
                     % (n, "" if n == 1 else "s", "was" if n == 1 else "were"))


_NO_QC_NOTE = ("%s %s no QC_FLAG column: every row was used; plaques outlined at the dark centre "
               "only, if any, cannot be told apart.")


def _no_qc_note(names):
    """CT-R2 F1 (tab part): said once per import, naming the files."""
    names = list(dict.fromkeys(names))
    if not names:
        return ""
    return _NO_QC_NOTE % (", ".join(names), "has" if len(names) == 1 else "have")


# CT-R2 F3: a per-plaque table with one of these columns holding several values holds several
# plates (Batch's all_plaques.csv: IMAGE). 'source' is NOT one: in the Measure / Batch files it
# says how a plaque was found (auto / small).
_PLATE_COLS = ("image", "plate", "plate_id", "replicate", "rep")
_PLATE_WORD = {"image": "image", "plate": "plate", "plate_id": "plate", "replicate": "replicate",
               "rep": "replicate"}


def _plate_account(p, name=None):
    """'plate1: 21 plaques sized, 20 left out (10 outlined at the dark centre only and 10 split
    pieces whose size is not reliable)' -- CT-R2 F7: the one account of a plate's plaques."""
    n, lo = len(p.get("diam") or []), int(p.get("left_out") or 0)
    s = "%s: %d plaque%s sized" % (name or p.get("replicate", "plate"), n, "" if n == 1 else "s")
    if lo:
        s += ", %d left out" % lo
        if p.get("left_out_why"):
            s += " (%s)" % p["left_out_why"]
    return s


def _plate_split_col(df):
    for want in _PLATE_COLS:
        for c in df.columns:
            if str(c).strip().lower() == want:
                vals = [v for v in df[c].astype(str).str.strip() if v]
                if len(set(vals)) > 1:
                    return c, _PLATE_WORD[want]
    return None, None


def _diam_col(df):
    """The diameter-in-millimetres column of a per-plaque table (case-insensitive), or None."""
    for c in df.columns:
        cl = str(c).strip().lower()
        if "diam" in cl and _MM_RE.search(cl) and not _NOT_MM_RE.search(cl):
            return c
    return None


def _area_col(df):
    """The area-in-mm² column, or None."""
    for c in df.columns:
        cl = str(c).strip().lower()
        if "area" in cl and _MM_RE.search(cl) and not _NOT_MM_RE.search(cl):
            return c
    return None


_DECIMAL_COMMA = re.compile(r"^[+-]?\d+,\d+$")


def _numbers(series):
    """(float Series, number of non-empty cells that are not numbers). Decimal commas ("2,34")
    are read as decimal points when every non-number cell is one (CT-R1 F6)."""
    txt = series.astype(str).str.strip()
    empty = txt.eq("") | series.isna()
    num = pd.to_numeric(txt.where(~empty), errors="coerce")
    bad = ~empty & num.isna()
    if bad.any() and txt[bad].str.match(_DECIMAL_COMMA).all():
        num = pd.to_numeric(txt.str.replace(",", ".", regex=False).where(~empty), errors="coerce")
        bad = ~empty & num.isna()
    return num.astype(float), int(bad.sum())


def _read_text_table(path):
    """Read a CSV / TSV the way it was typed: every cell as text (labels such as None, NA, 007,
    1.0 stay labels), delimiter , ; or tab sniffed from the header. A line starting with # is a
    comment ONLY before the header row; after it, a row whose first cell starts with # is data
    (CT-R2 F2: a sample named "#3 phage" used to vanish on Load study -- the same rule as the
    statistics engine and the R app). Raises ValueError with a plain message for files that are
    not text tables (binary, JSON, empty). Pandas only, so the Light build (no SciPy, no stats
    engine) can compile and load studies too (CT-R1 F5/F6).

    df.attrs["line_numbers"] holds the file line (1-based) of every data row, so a refusal can
    name the line (CT-R2 F5)."""
    name = os.path.basename(str(path))
    with open(path, "rb") as fh:
        raw = fh.read()
    if b"\x00" in raw[:4096]:
        raise ValueError("%s is not a text table (it is a binary file)." % name)
    text = raw.decode("utf-8-sig", errors="replace")
    lines, line_no = [], []
    for i, ln in enumerate(text.splitlines(), start=1):
        if not ln.strip():
            continue
        if not lines and ln.lstrip().startswith("#"):         # a comment above the header
            continue
        lines.append(ln); line_no.append(i)
    if not lines:
        raise ValueError("%s is empty (no header line)." % name)
    if lines[0].lstrip()[:1] in ("{", "["):
        raise ValueError("%s looks like JSON, not a CSV table." % name)
    counts = {d: 0 for d in (",", ";", "\t")}
    inq = False
    for ch in lines[0]:
        if ch == '"':
            inq = not inq
        elif not inq and ch in counts:
            counts[ch] += 1
    sep = max(counts, key=lambda d: (counts[d], d == ","))
    if not counts[sep]:
        sep = ","
    try:
        df = pd.read_csv(io.StringIO("\n".join(lines)), sep=sep, dtype=str, keep_default_na=False,
                         quoting=csv.QUOTE_MINIMAL, skip_blank_lines=True)
    except Exception as e:                                        # noqa: BLE001
        raise ValueError("could not read %s as a table: %s" % (name, e))
    df.columns = [str(c).strip() for c in df.columns]
    for c in df.columns:
        df[c] = df[c].astype(str).str.strip()
    # one physical line per row unless a quoted cell spans lines; then fall back to row numbers
    df.attrs["line_numbers"] = line_no[1:] if len(line_no) - 1 == len(df) else None
    return df


def _row_line(df, i):
    """'line 7' (the file line of data row i) or 'row 6' when the line is not known."""
    ln = (df.attrs or {}).get("line_numbers")
    return ("line %d" % ln[i]) if ln and i < len(ln) else ("row %d" % (i + 1))


def _write_csv(df, path):
    """Write a table the tab will read back, quoting a FIRST cell that starts with '#'
    (CT-R2 F2): '"#3 phage",…' starts with a quote, so no reader -- this tab, the statistics
    engine or the R app, before or after their own comment rule changed -- takes the row for a
    comment line."""
    text = df.to_csv(index=False)
    out, inq = [], False
    for ln in text.splitlines(keepends=True):
        if not inq and ln.startswith("#"):
            first, sep, rest = ln.partition(",")              # an unquoted first cell has no comma
            if sep:
                ln = '"%s",%s' % (first, rest)
            else:
                ln = '"%s"%s' % (first.rstrip("\r\n"), ln[len(first.rstrip("\r\n")):])
        if ln.count('"') % 2:
            inq = not inq                                      # a quoted cell spans lines
        out.append(ln)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write("".join(out))


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


def _stats_message(e):
    """The user-facing text of an engine refusal: StatsError.message, a bare SystemExit's code,
    or the exception text (CT-R1 F1: a SystemExit used to kill the whole app)."""
    msg = getattr(e, "message", None)
    if not msg and isinstance(e, SystemExit):
        code = e.code
        msg = str(code) if code not in (None, 0) else "the statistics engine stopped."
    msg = str(msg or e or e.__class__.__name__)
    if msg.startswith("[error] "):
        msg = msg[len("[error] "):]
    return _ui_words(msg)


def _ui_words(text, ref=None):
    """The engine speaks command-line ('--equal-var no'); the tab names its own controls instead
    (CT-R1 F9, brief rule 6), on screen AND in the ZIP's report (CT-R2 F13). Whole engine phrases
    are replaced first (longest first), so '--equal-var no (Welch)' becomes 'Variances: Unequal
    (Welch)', never '... (Welch) (Welch)'; `ref` is the Compare reference ('Compare: vs mutA
    (Dunnett)'). A bracket phrase repeated by any route is said once. Not applied to the legend
    text starter, which must stay identical to the ZIP's legend text file."""
    text = str(text or "").replace("`", "")
    pairs = list(_FLAG_WORDS)
    if ref:
        pairs = [("--posthoc dunnett", "Compare: vs %s (Dunnett)" % ref),
                 ("--control %s" % ref, "Compare: vs %s" % ref)] + pairs
    for flag, words in sorted(pairs, key=lambda fw: -len(fw[0])):
        text = text.replace(flag, words)
    return _DOUBLE_BRACKET.sub(r"\1", text)


# '(Welch) (Welch)', '(Dunnett)(Dunnett)': a bracket phrase said twice in a row
_DOUBLE_BRACKET = re.compile(r"(\([^()]{1,60}\))(?:\s*\1)+")

_FLAG_WORDS = [
    ("pass --log-y-drop-nonpositive", "tick 'hide ≤ 0'"),
    ("--equal-var no (Welch)", "Variances: Unequal (Welch)"),
    ("choose --equal-var no", "choose Variances: Unequal (Welch)"),
    ("--annotate letters gives a compact letter display, --annotate all every bracket",
     "choose Brackets: Letters for a compact letter display, or Brackets: All pairs for every bracket"),
    ("not in --order", "not in the sample order"),
    ("--log-y-drop-nonpositive", "'hide ≤ 0'"),
    ("--parametric nonparametric", "Test: Non-parametric"),
    ("--posthoc dunnett", "Compare: vs a sample (Dunnett)"),
    ("--equal-var no", "Variances: Unequal (Welch)"),
    ("--center median", "Center: Median"), ("--center mean", "Center: Mean"),
    ("--error iqr", "Error bars: IQR"), ("--error ci95", "Error bars: 95% CI"),
    ("--error none", "Error bars: None"), ("--error sd", "Error bars: SD"), ("--error sem", "Error bars: SEM"),
    ("--parametric parametric", "Test: Parametric"), ("--parametric auto", "Test: Auto"),
    ("Override with --parametric", "Override with the Test control"),
    ("--parametric", "the Test control"),
    ("--equal-var auto", "Variances: Auto"), ("--equal-var yes", "Variances: Equal"),
    ("--equal-var", "the Variances control"),
    ("--annotate letters", "Brackets: Letters"), ("--annotate all", "Brackets: All pairs"),
    ("--annotate adjacent", "Brackets: Adjacent"), ("--annotate", "the Brackets control"),
    ("--posthoc", "the Compare control"), ("--control", "Compare: vs a sample"),
    ("--unit replicate", "plates as the unit"), ("--unit plaque", "plaques as the unit"),
]


class _MsgLabel(QLabel):
    """A message line that takes no room while it is empty."""
    def setText(self, text):
        super().setText(text)
        self.setVisible(bool(text))


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
    """Guess the sample name from a plate CSV's filename: drop the Measure tab's
    'data-<channel>-' prefix (CT-R1 F17: every file used to be guessed as sample 'data-green'),
    then a trailing plate/rep/replicate token + number ('WT_plate2' → 'WT', 'T65I-3' → 'T65I')."""
    s = re.sub(r"^data-[A-Za-z]+-", "", str(stem))
    g = re.sub(r"[ _\-]*(plate|rep|replicate|r)?[ _\-]*\d+$", "", s, flags=re.I).strip(" _-")
    return g or s or str(stem)


class _AssignDialog(QDialog):
    """Map many per-plaque CSVs to samples — EACH CSV IS ONE REPLICATE PLATE. One row per file:
    pick its sample (reuse an existing name or type a new one), an optional 2nd factor, and the
    plate id (blank = plate1, plate2, … within the sample; the file name is kept as the plate's
    source). This is how you tell the tool which plate belongs to which sample, so replicates
    are real (no pseudoreplication)."""
    def __init__(self, parent, parsed, existing):
        super().__init__(parent)
        self.setWindowTitle("Assign CSVs to samples")
        self._parsed = parsed
        lay = QVBoxLayout(self)
        info = QLabel("Each CSV is one <b>replicate plate</b>. Assign each to a sample — reuse a name "
                      "to make plates replicates of the same sample, or type a new name. The 2nd "
                      "factor is optional (for control-comparison). Leave the plate id blank to "
                      "number the plates plate1, plate2, … within each sample.")
        info.setWordWrap(True); lay.addWidget(info)

        top = QHBoxLayout()
        self.all_sample = QLineEdit(); self.all_sample.setPlaceholderText("set every Sample to…")
        apply_btn = QPushButton("Apply to all"); apply_btn.clicked.connect(lambda _=False: self._apply_all())
        top.addWidget(QLabel("Quick:")); top.addWidget(self.all_sample); top.addWidget(apply_btn); top.addStretch()
        lay.addLayout(top)

        groups = []
        for s in existing:
            if s["group"] and s["group"] not in groups:
                groups.append(s["group"])
        self.table = QTableWidget(len(parsed), 5)
        self.table.setHorizontalHeaderLabels(["File", "N plaques", "Sample", "2nd factor",
                                              "Plate id (blank = plate1, 2, …)"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for c in (1, 2, 3, 4):
            self.table.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeToContents)
        for i, p in enumerate(parsed):
            f = QTableWidgetItem(p["stem"]); f.setFlags(Qt.ItemIsEnabled)
            f.setToolTip(p.get("path", p["stem"]))
            self.table.setItem(i, 0, f)
            n = QTableWidgetItem(str(p["n"])); n.setFlags(Qt.ItemIsEnabled); n.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(i, 1, n)
            cb = QComboBox(); cb.setEditable(True)
            for g in groups:
                cb.addItem(g)
            cb.setCurrentText(_sample_guess(os.path.splitext(p["label"])[0] if p.get("label") else p["stem"]))
            cb.setMinimumWidth(140)
            self.table.setCellWidget(i, 2, cb)
            self.table.setItem(i, 3, QTableWidgetItem(""))
            rep = QTableWidgetItem("")
            rep.setToolTip("File: %s — leave blank for plate1, plate2, … (the file name is kept as the "
                           "plate's source)." % p["stem"])
            self.table.setItem(i, 4, rep)
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
                        "diam": p["diam"], "area": p["area"], "left_out": p.get("left_out"),
                        "source": p.get("source") or os.path.basename(p.get("path") or p["stem"])})
        return out


# --------------------------------------------------------------------- the tab
class StudyTab(QWidget):
    METRICS = [("Diameter (mm)", "diam"), ("Area (mm²)", "area")]
    PALETTES_UI = [("Okabe–Ito (default)", "okabe"), ("Set2", "set2"), ("Tab10", "tab10"),
                   ("Warm", "warm"), ("Cool", "cool"), ("Grays", "grays")]
    _FIG_EXTS = (".png", ".svg", ".pdf", ".tif", ".tiff", ".eps")
    _EXT_FOR = {"PNG": ".png", "SVG": ".svg", "PDF": ".pdf", "TIFF": ".tiff", "EPS": ".eps"}

    def __init__(self, measure_tab=None):
        super().__init__()
        self.measure_tab = measure_tab
        self._samples = []        # list of {"group": str, "subgroup": str} — the containers, in x order
        self._plates = []         # list of {group, subgroup, replicate, diam[], area[], source}
        self._dirty = False       # CT-R1 F5/F25: unsaved changes to the compiled study
        self._ylabels = {}        # CT-R1 F21: Y label the user typed, per metric
        self.canvas = None
        self.toolbar = None
        self._fig_container = None
        self._last_fig = None
        self._last = None         # (kind, payload) cache for redraw + saving
        self._building = True     # guard so wiring customize controls doesn't trigger redraw
        self._cmp_ref = None      # CT-R2 F11: the Compare reference, the SAMPLE itself (not its name)
        self._stats_ok = _stats_available()

        intro = QLabel(
            "Compile your results, then analyze them without leaving the app. <b>Create a sample</b> and "
            "<b>add its plates into it</b> — three replicate plates of one sample sit together under it. "
            "Add the plate you just measured, or import saved per-plaque CSVs. Then <b>Analyze</b> for a "
            "publication-ready violin plot + the right statistics (plate = experimental unit), fully "
            "customizable, with the summary tables shown right here.")
        intro.setObjectName("ModeHelp"); intro.setWordWrap(True)

        # CT-R2 F18: this link opened the AGREEMENT guide (Bland-Altman, ICC). It now opens the
        # statistics engine's own section on how the Analyze test is chosen; the text promises
        # only what that section covers
        learn = QLabel('<a href="#stats" style="color:#0a5c43;font-weight:600;'
                       'text-decoration:none;">&#128218; New to these statistics? Read how the test is '
                       'chosen (plate = unit, t-test vs ANOVA, Welch) &rarr;</a>')
        learn.setTextFormat(Qt.RichText); learn.setOpenExternalLinks(False)
        learn.linkActivated.connect(lambda _=None: self._open_stats_guide())
        self.learn_lbl = learn

        lay = QVBoxLayout(self); lay.setContentsMargins(14, 12, 14, 12); lay.setSpacing(10)
        lay.addWidget(intro); lay.addWidget(learn)
        lay.addWidget(self._build_compile_card())
        lay.addWidget(self._build_analyse_card(), 1)
        self._building = False
        self._refresh_tree(dirty=False)

    # ---------------------------------------------------------------- actions
    def _bind(self, button, fn):
        """Connect a button to an action. clicked(bool) never reaches `fn` (CT-R1 F3: the
        Legend key button received False as its path), the old error is cleared first (F19) and
        any engine exit -- StatsError or a bare SystemExit -- becomes a message (F1)."""
        button.clicked.connect(lambda _=False: self._run_action(fn))

    def _run_action(self, fn, *a):
        self._clear_err()
        try:
            return fn(*a)
        except (Exception, SystemExit) as e:                      # noqa: BLE001
            if not isinstance(e, (ValueError, SystemExit)):    # a bug, not an engine refusal
                import traceback
                traceback.print_exc()
            self._warn("That did not work: %s" % _stats_message(e))
            return None

    def _clear_err(self):
        self.err.setText("")

    # ================================================================ COMPILE
    def _build_compile_card(self):
        card = QFrame(); card.setObjectName("Card"); _shadow(card)
        v = QVBoxLayout(card); v.setContentsMargins(14, 12, 14, 12); v.setSpacing(8)
        v.addWidget(self._heading("1 · Compile — build your samples"))

        self.new_sample_btn = QPushButton("＋  New sample"); self.new_sample_btn.setObjectName("Primary")
        self.new_sample_btn.setToolTip("Create a sample (a genotype/condition). Then add its plates into it.")
        self._bind(self.new_sample_btn, self._new_sample)
        self.add_cur_btn = QPushButton("Add current plate")
        self.add_cur_btn.setToolTip("Add the plate you just measured (Measure tab) as a replicate of the "
                                    "selected sample.")
        self._bind(self.add_cur_btn, self._add_current)
        self.add_csv_btn = QPushButton("Add CSV(s)…")
        self.add_csv_btn.setToolTip("Add saved per-plaque CSV(s) as replicate plates of the selected "
                                    "sample. Each file = one replicate; it needs a diameter-in-mm column.")
        self._bind(self.add_csv_btn, self._add_csvs)
        self.assign_btn = QPushButton("Import && assign…")   # CT-R2 F16: '&' alone is a mnemonic; self.assign_btn.setObjectName("Primary")
        self.assign_btn.setToolTip("Pick many plate CSVs at once and map each to a sample in one table "
                                   "(each CSV = one replicate plate). No sample needs to be selected first.")
        self._bind(self.assign_btn, self._import_assign)
        self.edit_btn = QPushButton("Rename / edit…")
        self.edit_btn.setToolTip("Rename the selected sample (or its 2nd factor), or the selected plate.")
        self._bind(self.edit_btn, self._edit_sample)
        self.remove_btn = QPushButton("Remove"); self._bind(self.remove_btn, self._remove_selected)
        # CT-R1 F25: samples can be reordered (their order is the figure's x order)
        self.up_btn = QToolButton(); self.up_btn.setText("▲"); self.up_btn.setToolTip("Move the selected sample up (left on the figure)")
        self.down_btn = QToolButton(); self.down_btn.setText("▼"); self.down_btn.setToolTip("Move the selected sample down (right on the figure)")
        self._bind(self.up_btn, lambda: self._move_sample(-1))
        self._bind(self.down_btn, lambda: self._move_sample(+1))
        v.addWidget(_flow([self.new_sample_btn, self.add_cur_btn, self.add_csv_btn, self.assign_btn,
                           self.edit_btn, self.remove_btn, self.up_btn, self.down_btn]))   # CT-R2 F16

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
        self.clear_btn = QPushButton("Clear all"); self._bind(self.clear_btn, self._clear_all)
        self.save_study_btn = QPushButton("Save study…"); self._bind(self.save_study_btn, self._save_study)
        self.load_study_btn = QPushButton("Load study…"); self._bind(self.load_study_btn, self._load_study)
        self.count_lbl.setWordWrap(True)
        v.addWidget(self.count_lbl)
        v.addWidget(_flow([self.clear_btn, self.save_study_btn, self.load_study_btn]))
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

        # analyze controls: metric + control + test + variances + compare-to + Analyze
        self.metric_sel = QComboBox()
        for lab, key in self.METRICS:
            self.metric_sel.addItem(lab, key)
        self.metric_sel.setToolTip("Which measurement to analyze (both are stored per plate).")
        self.metric_sel.currentIndexChanged.connect(self._on_metric_changed)
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
        self.param_sel.currentIndexChanged.connect(self._sync_controls)       # CT-R2 F12
        self.param_sel.currentIndexChanged.connect(self._reanalyse_if_ready)
        # CT-R1 new options: one control each, no dialogs
        self.var_cap = QLabel("Variances:"); self.var_cap.setObjectName("FieldLabel")
        self.var_sel = QComboBox()
        self.var_sel.addItem("Auto", "auto")
        self.var_sel.addItem("Equal (ANOVA + Tukey)", "yes")
        self.var_sel.addItem("Unequal (Welch)", "no")
        self.var_sel.setToolTip("3 or more samples: Auto lets Levene's test decide; Equal = one-way ANOVA + "
                                "Tukey; Unequal = Welch's ANOVA + Games-Howell. With 3 plates per sample "
                                "Levene's test cannot see a difference in spread.")
        self.var_sel.currentIndexChanged.connect(self._sync_controls)         # CT-R2 F12
        self.var_sel.currentIndexChanged.connect(self._reanalyse_if_ready)
        self.cmp_to_cap = QLabel("Compare:"); self.cmp_to_cap.setObjectName("FieldLabel")
        self.cmp_to_sel = QComboBox(); self.cmp_to_sel.setMinimumWidth(130)
        self.cmp_to_sel.addItem("All pairs", None)
        self.cmp_to_sel.setToolTip("All pairs (Tukey / Games-Howell / Dunn), or each sample vs one "
                                   "reference sample (Dunnett's test).")
        self.cmp_to_sel.currentIndexChanged.connect(self._on_cmp_changed)
        self.analyse_btn = QPushButton("  Analyze  "); self.analyse_btn.setObjectName("Primary")
        self._bind(self.analyse_btn, self._analyse)
        # CT-R2 F16: the row wraps in a narrow window (the Analyze button used to be off screen)
        v.addWidget(_flow([_pair(QLabel("Metric:"), self.metric_sel), _pair(self.ctrl_cap, self.control_sel),
                           _pair(QLabel("Test:"), self.param_sel), _pair(self.var_cap, self.var_sel),
                           _pair(self.cmp_to_cap, self.cmp_to_sel), self.analyse_btn], hspace=14))

        # CT-R1 F19: errors of the last action (cleared by every action) ...
        self.err = _MsgLabel(""); self.err.setWordWrap(True); self.err.setVisible(False)
        self.err.setStyleSheet("color:%s;font-weight:600" % style.LIGHT["danger"])
        v.addWidget(self.err)
        # ... and the statistics' own warnings (CT-R1 F9), which belong to the result on screen
        self.warn_lbl = _MsgLabel(""); self.warn_lbl.setWordWrap(True); self.warn_lbl.setVisible(False)
        self.warn_lbl.setStyleSheet("color:%s;font-weight:600" % style.LIGHT["warn"])
        v.addWidget(self.warn_lbl)

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
        self.savefig_btn = QPushButton("Save figure…"); self._bind(self.savefig_btn, self._save_fig)
        self.savesum_btn = QPushButton("Save summary CSV…"); self._bind(self.savesum_btn, self._save_summary)
        self.savedata_btn = QToolButton(); self.savedata_btn.setText("Save compiled data ▾")
        self.savedata_btn.setPopupMode(QToolButton.InstantPopup)
        dmenu = QMenu(self.savedata_btn)
        dmenu.addAction("Wide — one row per plaque", lambda: self._run_action(self._save_data_wide))
        dmenu.addAction("Long — group/replicate/metric/value (standalone-ready)",
                        lambda: self._run_action(self._save_data_long))
        self.savedata_btn.setMenu(dmenu)
        self.zip_btn = QPushButton("Export everything (ZIP)…"); self._bind(self.zip_btn, self._export_zip)
        self.zip_btn.setToolTip("Figure in every format + its legend key + summaries + pairwise + report + "
                                "provenance, the same bundle as the standalone app.")
        # CT-R1 F3: clicked(bool) used to arrive in _save_key as its path (False) -> TypeError
        self.key_btn = QPushButton("Legend key…"); self._bind(self.key_btn, self._save_key)
        self.key_btn.setToolTip("Save the figure's legend key: every sample/plate with its exact "
                                "colour and marker, in the figure's font and format.")
        v.addWidget(_flow([self.savefig_btn, self.key_btn, self.legend_cb, self.savesum_btn,
                           self.savedata_btn, self.zip_btn]))                          # CT-R2 F16
        # legend text starter: read-only, follows the figure on screen, one Copy button
        self.key_text = QLineEdit(); self.key_text.setReadOnly(True)
        self.key_text.setPlaceholderText("Analyze to get a sentence listing every sample with its colour.")
        self.key_copy_btn = QPushButton("Copy"); self._bind(self.key_copy_btn, self._copy_key_text)
        kt = QHBoxLayout()
        kcap = QLabel("Legend text starter"); kcap.setObjectName("FieldLabel")
        kt.addWidget(kcap); kt.addWidget(self.key_text, 1); kt.addWidget(self.key_copy_btn)
        v.addLayout(kt)
        self._fig_ext = ".png"        # the format last chosen in "Save figure…" (the key follows it)
        self._export_buttons = [self.savefig_btn, self.key_btn, self.key_copy_btn, self.savesum_btn,
                                self.savedata_btn, self.zip_btn]
        self._figure_buttons = [self.savefig_btn, self.key_btn, self.key_copy_btn, self.zip_btn]
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
        # CT-R1 F24: no second scroll area. The figure area is as tall as the canvas, so the tab's
        # own scroll bar scrolls the figure (it used to sit squeezed in a 365 px inner scroll box).
        self.fig_holder = QWidget()
        self.fig_layout = QVBoxLayout(self.fig_holder)
        self.fig_layout.setContentsMargins(4, 4, 4, 4); self.fig_layout.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.fig_placeholder = QLabel("The violin plot appears here after you click Analyze.")
        self.fig_placeholder.setObjectName("Placeholder"); self.fig_placeholder.setAlignment(Qt.AlignCenter)
        self.fig_placeholder.setMinimumHeight(360)
        self.fig_layout.addWidget(self.fig_placeholder)
        outer.addWidget(self.fig_holder, 1)
        # CT-R1 F12: what the marks are, under the figure (the same sentence ends the text starter)
        self.fig_caption = QLabel(""); self.fig_caption.setWordWrap(True)
        self.fig_caption.setObjectName("Placeholder")
        self.fig_caption.setTextInteractionFlags(Qt.TextSelectableByMouse)
        outer.addWidget(self.fig_caption)
        return w

    def _build_customize_panel(self):
        box = QFrame(); box.setObjectName("SummaryCard")
        g = QVBoxLayout(box); g.setContentsMargins(12, 8, 12, 8); g.setSpacing(4)
        pairs = []

        def add(r, c, label, widget):
            # CT-R2 F16: label/control pairs of one width in a flow, so the panel reads as a grid
            # in a wide window and wraps (2 or 1 per line) in a narrow one instead of scrolling
            cap = QLabel(label); cap.setObjectName("FieldLabel")
            pairs.append(_pair(cap, widget, label_w=74, widget_w=150))
            return cap

        # combos
        self.palette_sel = QComboBox()
        for lab, key in self.PALETTES_UI:
            self.palette_sel.addItem(lab, key)
        self.palette_custom = QLineEdit(); self.palette_custom.setPlaceholderText("or #hex,#hex,…")
        self.palette_custom.setMaximumWidth(150)
        self.palette_custom.setToolTip("Your own colours, comma-separated hex codes. It needs one colour per "
                                       "coloured item (sample, plate or 2nd-factor value).")
        self.fill_sel = QComboBox()
        for lab, key in [("Auto", "auto"), ("Neutral (grey)", "neutral"), ("Colored", "group")]:
            self.fill_sel.addItem(lab, key)
        self.fill_sel.setToolTip("Auto: grey violins when the plates carry the colours, coloured violins "
                                 "otherwise. The palette colours whatever is coloured.")
        self.center_sel = QComboBox()
        for lab, key in [("Mean", "mean"), ("Median", "median")]:
            self.center_sel.addItem(lab, key)
        self.error_sel = QComboBox()
        for lab, key in [("Auto", "auto"), ("SEM", "sem"), ("95% CI", "ci95"), ("SD", "sd"),
                         ("IQR", "iqr"), ("None", "none")]:
            self.error_sel.addItem(lab, key)
        self.annot_sel = QComboBox()
        for lab, key in [("Auto brackets", "auto"), ("All pairs", "all"), ("Adjacent", "adjacent"),
                         ("None", "none"), ("Letters", "letters")]:
            self.annot_sel.addItem(lab, key)
        self.annot_sel.setToolTip("Letters: a compact letter display (samples sharing a letter are not "
                                  "significantly different). Auto with more than 5 samples shows only the "
                                  "significant comparisons against the reference sample.")
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
        self.alpha.setToolTip("Violin opacity: higher = more solid (0.55 is the default look).")
        self.width_in = QDoubleSpinBox(); self.width_in.setRange(4, 16); self.width_in.setValue(8.4); self.width_in.setSingleStep(0.2); self.width_in.setDecimals(1)
        self.height_in = QDoubleSpinBox(); self.height_in.setRange(3, 12); self.height_in.setValue(5.4); self.height_in.setSingleStep(0.2); self.height_in.setDecimals(1)
        self.dpi_in = QSpinBox(); self.dpi_in.setRange(72, 600); self.dpi_in.setValue(300); self.dpi_in.setSingleStep(50)
        self.dpi_in.setToolTip("Resolution of every raster export (Save figure, legend key, ZIP), TIFF included.")
        self.seed_in = QSpinBox(); self.seed_in.setRange(0, 9999); self.seed_in.setValue(7)

        # checkboxes
        self.show_points = QCheckBox("raw plaques"); self.show_points.setChecked(True)
        self.show_n = QCheckBox("n labels"); self.show_n.setChecked(True)
        self.show_value = QCheckBox("center value"); self.show_value.setChecked(True)
        # "Place key on figure": the legend key drawn on the figure (outside its top-right corner).
        # It lives in the export bar beside "Legend key…" -- see _build_analyse_card.
        self.legend_cb = QCheckBox("Place key on figure"); self.legend_cb.setChecked(True)
        self.legend_cb.setToolTip("Draw the legend key on the figure itself (the same entries as the "
                                  "stand-alone key from “Legend key…”).")
        self.logy_cb = QCheckBox("log Y"); self.logy_cb.setChecked(False)
        # CT-R1 F15: values <= 0 cannot be drawn on a log axis -- the engine refuses unless asked
        self.logy_drop_cb = QCheckBox("hide ≤ 0"); self.logy_drop_cb.setChecked(False)
        self.logy_drop_cb.setToolTip("With log Y: leave values that are zero or negative off the figure "
                                     "(they stay in the statistics, and the figure says how many).")
        self.frame_cb = QCheckBox("full frame"); self.frame_cb.setChecked(False)

        # layout: 6 rows × 3 label/widget pairs
        add(0, 0, "Palette", self.palette_sel); add(0, 1, "Custom", self.palette_custom)
        self.fill_cap = add(0, 2, "Violin fill", self.fill_sel)
        add(1, 0, "Center", self.center_sel); add(1, 1, "Error bars", self.error_sel); add(1, 2, "Brackets", self.annot_sel)
        add(2, 0, "Title", self.title_in); add(2, 1, "Y label", self.ylabel_in); add(2, 2, "X label", self.xlabel_in)
        # CT-R1 F13: "Transparency" 1.0 was opaque -- it is an opacity
        add(3, 0, "Point size", self.point_size); add(3, 1, "Jitter", self.jitter); add(3, 2, "Opacity", self.alpha)
        add(4, 0, "Width (in)", self.width_in); add(4, 1, "Height (in)", self.height_in); add(4, 2, "Export DPI", self.dpi_in)
        add(5, 0, "Theme", self.theme_sel); add(5, 1, "Seed", self.seed_in)
        g.addWidget(_flow(pairs, hspace=16, vspace=4))
        # CT-R2 F4: what size the saved figure will really be (a key placed below makes it taller)
        self.size_lbl = QLabel(""); self.size_lbl.setObjectName("Placeholder"); self.size_lbl.setWordWrap(True)
        g.addWidget(self.size_lbl)
        g.addWidget(_flow([self.show_points, self.show_n, self.show_value, self.logy_cb,
                           self.logy_drop_cb, self.frame_cb], hspace=12))

        # wire every cosmetic control to a live redraw
        self.center_sel.currentIndexChanged.connect(self._sync_controls)
        self.show_points.toggled.connect(self._sync_controls)
        self.logy_cb.toggled.connect(self._sync_controls)
        for c in (self.palette_sel, self.fill_sel, self.center_sel, self.error_sel, self.annot_sel, self.theme_sel):
            c.currentIndexChanged.connect(self._on_cosmetic)
        self.ylabel_in.editingFinished.connect(self._remember_ylabel)
        for e in (self.palette_custom, self.title_in, self.ylabel_in, self.xlabel_in):
            e.editingFinished.connect(self._on_cosmetic)
        for sp in (self.point_size, self.jitter, self.alpha, self.width_in, self.height_in, self.dpi_in, self.seed_in):
            sp.valueChanged.connect(self._on_cosmetic)
        for cb in (self.show_points, self.show_n, self.show_value, self.legend_cb, self.logy_cb,
                   self.logy_drop_cb, self.frame_cb):
            cb.toggled.connect(self._on_cosmetic)
        self._sync_controls()
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
        v.addWidget(self._heading("Per sample — plate level (the statistical unit) and per plaque"))
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
        self.copy_btn = QPushButton("Copy report"); self._bind(self.copy_btn, self._copy_report)
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
        self._status("Sample '%s' created — now add its plates." % name, 5000)

    def _edit_sample(self):
        it = self.tree.currentItem()
        data = it.data(0, Qt.UserRole) if it is not None else None
        if data and data[0] == "plate":                     # CT-R1 F17: a plate can be renamed
            return self._rename_plate(data[1])
        idx = self._selected_sample_index()
        if idx is None:
            self._warn("Select a sample (or a plate) to edit."); return
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
        self._select_sample(idx)

    def _rename_plate(self, pid):
        p = next((x for x in self._plates if id(x) == pid), None)
        if p is None:
            return
        text, ok = QInputDialog.getText(self, "Rename plate",
                                        "Plate id (unique within sample '%s'):" % p["group"],
                                        QLineEdit.Normal, p["replicate"])
        if not ok:
            return
        new = (text or "").strip()
        if not new:
            self._warn("A plate needs an id."); return
        if any(q is not p and q["group"] == p["group"] and q.get("subgroup", "") == p.get("subgroup", "")
               and q["replicate"] == new for q in self._plates):
            self._warn("Sample '%s' already has a plate '%s'." % (p["group"], new)); return
        p["replicate"] = new
        self._refresh_tree()

    def _move_sample(self, step):
        idx = self._selected_sample_index()
        if idx is None:
            self._warn("Select a sample to move."); return
        j = idx + step
        if not 0 <= j < len(self._samples):
            return
        self._samples[idx], self._samples[j] = self._samples[j], self._samples[idx]
        self._refresh_tree()
        self._select_sample(j)

    def _target_sample_index(self):
        """Where new plates go: the selected sample (or the sample of a selected plate), else the
        only sample if there's exactly one, else None."""
        idx = self._selected_sample_index()
        if idx is not None:
            return idx
        if len(self._samples) == 1:
            return 0
        return None

    def _ask_unsized(self, name, part):
        """CT-R2 F8: the ONE question for a plate whose plaques are all left out of the sizes
        (both Add current plate and the CSV routes ask it), or for a file without plaque rows."""
        if part["left_out"]["n"]:
            text = ("All %d plaques of %s are flagged as not sizeable (%s). Add it as a plate "
                    "without sizes?\n\nA plate without sizes is listed under its sample but is not "
                    "counted in the statistics." % (part["left_out"]["n"], name,
                                                    part["left_out"]["why"] or "flagged"))
            title = "No sizeable plaques"
        else:
            text = "%s has no plaque rows. Add it as a plate with ZERO plaques?" % name
            title = "No plaques in the file"
        return QMessageBox.question(self, title, text, QMessageBox.Yes | QMessageBox.No,
                                    QMessageBox.No) == QMessageBox.Yes

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
        # CT-R3 F1: no mm scale = no millimetres. This added a plate of 0.0 mm diameters with no
        # word (the CSV route refuses the same file); now it is refused, every time it is clicked
        ed = getattr(mt, "editor", None)
        if ed is not None and not getattr(ed, "ppm", None):
            why = "the Dish size is 0" if getattr(ed, "plate", None) else "no dish was found"
            self._warn("Not added: this plate has no millimetre scale (%s): set the dish or use the "
                       "Ruler on the Measure tab, then add it." % why)
            return
        dc, ac = _diam_col(df), _area_col(df)
        if dc is None:
            self._warn("Couldn't find a diameter-in-mm column on the current measurement."); return
        keep, flags = _size_mask(df)                  # CT-R1 detection D10a
        left = _left_out_account(flags, keep)
        kdf = df[pd.Series(keep, index=df.index, dtype=bool)]
        diam = pd.to_numeric(kdf[dc], errors="coerce").dropna().tolist()
        area = pd.to_numeric(kdf[ac], errors="coerce").dropna().tolist() if ac else []
        src = os.path.basename(str(getattr(mt, "image_path", "") or "")) or "Measure tab"
        # CT-R1 F25: clicking twice used to add the same plate twice (pseudo-replicates).
        # CT-R2 F8: a plate without sizes is the same plate when its source and left-out count match.
        twin = next((p for p in self._plates if p.get("diam") == diam and (
            diam or (p.get("source") == src and p.get("left_out", 0) == left["n"]))), None)
        if twin is not None:
            q = QMessageBox.question(
                self, "Plate already added",
                "This measurement (%d plaques) is already in the study as plate '%s' of sample '%s'.\n\n"
                "Add it again as another plate? Only do this if it really is a different plate."
                % (len(diam), twin["replicate"], twin["group"]),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if q != QMessageBox.Yes:
                self._status("Not added: that plate is already in the study.", 5000)
                return
        elif not diam and not self._ask_unsized(src, {"left_out": left}):
            self._status("Not added: %s has no sizeable plaques." % src, 6000)
            return
        self._add_plate(idx, diam, area, source=src, left_out=left)
        self._refresh_tree(); self._select_sample(idx)
        s = self._samples[idx]
        note = _no_qc_note([src]) if flags is None else ""
        self._status("Added a plate to '%s' (%d plaques%s).%s" % (
            s["group"], len(diam), _left_out_text([left]), (" " + note) if note else ""), 10000)

    def _add_csvs(self):
        idx = self._target_sample_index()
        if idx is None:
            self._warn("Create or select a sample first, then add CSV(s) to it."); return
        paths, _ = QFileDialog.getOpenFileNames(self, "Add per-plaque CSV(s) as replicate plates", "",
                                                "CSV files (*.csv *.tsv *.txt);;All files (*.*)")
        if not paths:
            return
        problems, notes, no_qc, added = [], [], [], []
        for p in paths:
            parts = self._parse_csv(p, problems, notes, no_qc)
            for part in parts or []:
                # CT-R1 F17: plate ids are plate1..n within the sample; the file name is the source
                self._add_plate(idx, part["diam"], part["area"], source=part["source"],
                                left_out=part["left_out"])
                added.append(part)
        if added:
            self._refresh_tree(); self._select_sample(idx)
            msg = "Added %d replicate plate(s)%s." % (len(added), _left_out_text(p["left_out"] for p in added))
            extra = " ".join(notes + ([_no_qc_note(no_qc)] if no_qc else []))
            self._status(msg + ((" " + extra) if extra else ""), 12000)
        if problems:
            self._warn(" ".join(problems))

    def _parse_csv(self, path, problems=None, notes=None, no_qc=None):
        """Read a per-plaque CSV → a list of plates [{diam, area, left_out, source, stem, n}], or
        None (the reason is appended to `problems`, or shown). CT-R1 F6: the diameter must be a
        diameter-in-mm column (or the column the user names when asked); ';' tables and decimal
        commas are read; binary/JSON files, non-numbers and values <= 0 are refused; a file
        without plaques becomes a zero-plaque plate only after the user confirms.
        CT-R2 F3: a table whose IMAGE / plate / replicate column holds several values is one
        plate per value (never pooled), said in `notes`. CT-R2 F1: a file without a QC_FLAG column
        is named in `no_qc`. CT-R2 F8: a plate whose plaques are ALL flagged asks the one
        'plate without sizes' question."""
        name = os.path.basename(path)

        def fail(msg):
            if problems is None:
                self._warn(msg)
            else:
                problems.append(msg)
            return None

        try:
            df = _read_text_table(path)
        except (ValueError, OSError) as e:
            return fail("%s Skipped." % str(e).rstrip())          # CT-R2 F20: no '. —'
        keep, flags = _size_mask(df)                   # CT-R1 detection D10a
        if flags is None and no_qc is not None and len(df):
            no_qc.append(name)
        dc, ac = _diam_col(df), _area_col(df)
        if dc is None:
            # CT-R2 F20: an area column is never offered as the diameter
            numeric = [c for c in df.columns if _numbers(df[c])[1] == 0 and _numbers(df[c])[0].notna().any()
                       and not _NOT_MM_RE.search(str(c).lower())          # no µm / px / cm columns
                       and "area" not in str(c).lower() and c != _flag_col(df)]
            if not numeric:
                return fail("%s has no diameter-in-mm column (columns: %s). Skipped."
                            % (name, ", ".join(map(str, df.columns))))
            item, ok = QInputDialog.getItem(
                self, "Which column is the diameter?",
                "%s has no column named like 'diameter_mm'.\nWhich column holds the plaque DIAMETER "
                "in millimetres? (Cancel skips the file.)" % name, [str(c) for c in numeric], 0, False)
            if not ok or not item:
                return fail("%s skipped: no diameter-in-mm column chosen." % name)
            dc = item
        # CT-R3 F1: the app leaves the mm cells blank when a plate had no mm scale; such a file
        # (or such an image of Batch's all_plaques.csv) used to become a "plate without sizes"
        # or a zero-plaque plate instead of saying why. Checked per plate, below.
        no_mm = (df[dc].astype(str).str.strip().eq("") | df[dc].isna()).tolist()
        kept = df[pd.Series(keep, index=df.index, dtype=bool)]
        d, nbad = _numbers(kept[dc])
        if nbad:
            return fail("%s: %d cell(s) of '%s' are not numbers. Skipped." % (name, nbad, dc))
        if any(x <= 0 for x in d.dropna()):
            return fail("%s: %d diameter(s) are zero or negative, which is not a plaque diameter in mm. "
                        "Skipped." % (name, sum(1 for x in d.dropna() if x <= 0)))
        a = None
        if ac is not None:
            a, abad = _numbers(kept[ac])
            if abad:
                a = None
        pcol, word = _plate_split_col(df)
        if pcol is None:
            keys, labels = [None], [None]
        else:
            labels = list(dict.fromkeys(v for v in df[pcol].astype(str).str.strip() if v))
            keys = labels
        stem = os.path.splitext(name)[0]
        parts = []
        for key in keys:
            rows = [True] * len(df) if key is None else list(df[pcol].astype(str).str.strip() == key)
            if any(rows) and all(b for b, r in zip(no_mm, rows) if r):          # CT-R3 F1
                fail("%s: no millimetre sizes in this %s (it was measured without a scale). Set "
                     "the dish or use the Ruler on the Measure tab and save it again. Skipped."
                     % (name if key is None else "%s · %s" % (name, key),
                        "file" if key is None else word))
                continue
            sel = [r and k for r, k in zip(rows, keep)]
            sel_kept = pd.Series(sel, index=df.index)[pd.Series(keep, index=df.index, dtype=bool)]
            diam = d[sel_kept.values].dropna().tolist()
            area = a[sel_kept.values].dropna().tolist() if a is not None else []
            g_flags = None if flags is None else [f for f, r in zip(flags, rows) if r]
            g_keep = [k for k, r in zip(keep, rows) if r]
            part = {"diam": diam, "area": area, "left_out": _left_out_account(g_flags, g_keep),
                    "source": name if key is None else "%s · %s" % (name, key),
                    "stem": stem if key is None else "%s · %s" % (stem, key),
                    "path": path, "label": key}
            part["n"] = len(diam)
            if not diam and not self._ask_unsized(part["source"], part):
                fail("%s skipped: %s." % (part["source"], "no sizeable plaques" if part["left_out"]["n"]
                                          else "it has no plaques"))
                continue
            parts.append(part)
        if pcol is not None and notes is not None:
            notes.append("%s holds %d %ss: added as %d plate(s)%s." % (
                name, len(keys), word, len(parts),
                "" if len(parts) == len(keys) else " (%d skipped)" % (len(keys) - len(parts))))
        return parts or None

    def _import_assign(self):
        """Pick many plate CSVs and map each (one plate) to a sample in one dialog → real replicates."""
        paths, _ = QFileDialog.getOpenFileNames(self, "Import plate CSVs and assign to samples", "",
                                                "CSV files (*.csv *.tsv *.txt);;All files (*.*)")
        if not paths:
            return
        parsed, problems, notes, no_qc = [], [], [], []
        for p in paths:
            parsed.extend(self._parse_csv(p, problems, notes, no_qc) or [])
        if problems:
            self._warn(" ".join(problems))
        if not parsed:
            return
        dlg = _AssignDialog(self, parsed, self._samples)
        if dlg.exec() != QDialog.Accepted:
            return
        # CT-R2 F9: the left-out counts travel in each row; only the rows imported are counted
        self._apply_assignments(dlg.rows(), notes=notes, no_qc=no_qc)

    def _apply_assignments(self, rows, notes=None, no_qc=None):
        """rows: [{sample, subgroup, replicate, diam, area, source, left_out}] — each becomes ONE
        plate under its sample (created if new). The many-CSVs → real-replicates flow (each CSV,
        or each IMAGE of a multi-plate CSV, is a plate)."""
        added = []
        for r in rows:
            g = (r.get("sample") or "").strip()
            if not g:
                continue
            sub = (r.get("subgroup") or "").strip()
            si = next((i for i, s in enumerate(self._samples)
                       if s["group"] == g and s.get("subgroup", "") == sub), None)
            if si is None:
                self._samples.append({"group": g, "subgroup": sub}); si = len(self._samples) - 1
            self._add_plate(si, r["diam"], r.get("area") or [],
                            rep=(r.get("replicate") or "").strip() or None, source=r.get("source", ""),
                            left_out=r.get("left_out"))
            added.append(r)
        if added:
            self._refresh_tree()
            used = {str(r.get("source", "")).split(" · ")[0] for r in added}
            extra = " ".join((notes or []) + ([_no_qc_note([n for n in no_qc if n in used])]
                                              if no_qc and any(n in used for n in no_qc) else []))
            self._status("Imported %d plate(s) across %d sample(s)%s.%s" % (
                len(added), len(self._samples), _left_out_text(r.get("left_out") or {} for r in added),
                (" " + extra) if extra else ""), 12000)
        return len(added)

    def _next_auto_rep(self, group, subgroup=""):
        """A plate id not already used within this sample (group, subgroup). Per-sample uniqueness
        keeps the stats engine from ever pooling two plates into one mean, and survives Load study."""
        used = {p["replicate"] for p in self._plates
                if p["group"] == group and p.get("subgroup", "") == subgroup}
        i = 1
        while ("plate%d" % i) in used:
            i += 1
        return "plate%d" % i

    def _add_plate(self, s_idx, diam, area, rep=None, source="", left_out=None):
        """left_out: {'n', 'why'} -- the plaques of this plate left out of the sizes and why
        (CT-R2 F7); kept with the plate, shown in the tree / Report / ZIP, saved in the study."""
        s = self._samples[s_idx]
        g, sub = s["group"], s.get("subgroup", "")
        if not rep or any(p["group"] == g and p.get("subgroup", "") == sub and p["replicate"] == rep
                          for p in self._plates):
            rep = self._next_auto_rep(g, sub)        # blank or clashing id → next free one
        lo = left_out or {}
        self._plates.append({"group": g, "subgroup": sub, "replicate": rep,
                             "diam": list(diam), "area": list(area), "source": source or "",
                             "left_out": int(lo.get("n") or 0), "left_out_why": lo.get("why") or ""})

    def _plates_of(self, s):
        return [p for p in self._plates
                if p["group"] == s["group"] and p.get("subgroup", "") == s.get("subgroup", "")]

    def _plates_in_order(self):
        """Every plate, sample by sample in the samples' order (the figure's x order)."""
        out = []
        for s in self._samples:
            out.extend(self._plates_of(s))
        return out

    # ---------------------------------------------------------------- tree view
    def _refresh_tree(self, dirty=True):
        """Redraw the sample tree. Every caller changed the compiled study, so the study becomes
        unsaved (dirty) unless told otherwise (Load / Save / Clear)."""
        if dirty and not self._building:
            self._dirty = True
        self._invalidate_analysis()
        self.tree.blockSignals(True)
        self.tree.clear()
        total_plates, unsized = 0, []
        for si, s in enumerate(self._samples):
            plates = self._plates_of(s)
            # CT-R2 F8: ONE rule everywhere (tree, compiled line, PLATES chip, Summary): a plate
            # with at least one sized plaque counts; a plate without sizes is listed apart
            sized = [p for p in plates if p.get("diam")]
            total_plates += len(sized)
            unsized += ["%s/%s" % (s["group"], p["replicate"]) for p in plates if not p.get("diam")]
            n_un = len(plates) - len(sized)
            means = [float(np.mean(p["diam"])) for p in sized]
            roll = np.mean(means) if means else float("nan")
            top = QTreeWidgetItem([
                s["group"],
                s.get("subgroup", "") or "—",
                "%d plate(s)%s · %d plaques" % (len(sized), (" + %d without sizes" % n_un) if n_un else "",
                                                sum(len(p.get("diam") or []) for p in plates)),
                ("%.3f" % roll) if means else "—"])
            top.setData(0, Qt.UserRole, ("sample", si))
            f = top.font(0); f.setBold(True)
            for c in range(4):
                top.setFont(c, f)
            self.tree.addTopLevelItem(top)
            for p in plates:
                d = p.get("diam") or []
                lo = int(p.get("left_out") or 0)
                child = QTreeWidgetItem(["    " + p["replicate"], "",
                                         ("%d (+%d left out)" % (len(d), lo)) if lo else str(len(d)),
                                         ("%.3f" % np.mean(d)) if d else "—"])
                child.setData(0, Qt.UserRole, ("plate", id(p)))
                tip = ["Source: %s" % p["source"]] if p.get("source") else []
                tip.append(_plate_account(p))                   # CT-R2 F7
                for c in range(4):
                    child.setToolTip(c, "\n".join(tip))
                top.addChild(child)
            top.setExpanded(True)
        self.tree.blockSignals(False)
        n = len(self._samples)
        if n == 0:
            self.count_lbl.setText("No samples yet — click “New sample”, then add its plates.")
        else:
            self.count_lbl.setText("%d sample(s) · %d plate(s) compiled%s." % (
                n, total_plates, ("; %d plate(s) without sizes, not counted: %s" % (
                    len(unsized), ", ".join(unsized[:4]) + (", …" if len(unsized) > 4 else "")))
                if unsized else ""))
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
            self._refresh_tree(dirty=False)
            self._dirty = False
            self.warn_lbl.setText("")

    # ---------------------------------------------------------------- unsaved study on close
    def confirm_close(self):
        """CT-R1 F25: True when the app may close. An unsaved study asks first (MainWindow's
        closeEvent calls this). A hidden window (tests, teardown) never asks."""
        w = self.window()
        if not (self._dirty and self._samples) or w is None or not w.isVisible():
            return True
        q = QMessageBox.question(
            self, "Unsaved study",
            "The Analyze tab holds a study that is not saved (%d sample(s), %d plate(s)).\n\n"
            "Close anyway and lose it? Choose No, then Save study…, to keep it."
            % (len(self._samples), len(self._plates)),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return q == QMessageBox.Yes

    # ================================================================ PERSISTENCE
    def _tidy_frame(self):
        """One row per plaque, sample by sample in the samples' order (what is analysed)."""
        rows = []
        for pl in self._plates_in_order():
            diam = pl.get("diam") or []
            area = pl.get("area") or []
            for i in range(max(len(diam), len(area))):
                rows.append({"group": pl["group"], "subgroup": pl.get("subgroup", ""),
                             "replicate": pl["replicate"],
                             "diameter_mm": diam[i] if i < len(diam) else np.nan,
                             "area_mm2": area[i] if i < len(area) else np.nan,
                             "source": pl.get("source", "")})
        return pd.DataFrame(rows, columns=["group", "subgroup", "replicate", "diameter_mm",
                                           "area_mm2", "source"])

    def _study_frame(self):
        """The study file (CT-R1 F5): the per-plaque rows in sample order, plus one row with blank
        values for every plate without plaques and one row with a blank plate for every sample
        without plates, so Load study gets back exactly the samples, order and plates."""
        rows = []
        for s in self._samples:
            plates = self._plates_of(s)
            if not plates:
                rows.append({"group": s["group"], "subgroup": s.get("subgroup", ""), "replicate": "",
                             "diameter_mm": np.nan, "area_mm2": np.nan, "source": ""})
            for pl in plates:
                diam = pl.get("diam") or []
                area = pl.get("area") or []
                n = max(len(diam), len(area))
                for i in range(max(n, 1)):
                    rows.append({"group": pl["group"], "subgroup": pl.get("subgroup", ""),
                                 "replicate": pl["replicate"],
                                 "diameter_mm": diam[i] if i < len(diam) else np.nan,
                                 "area_mm2": area[i] if i < len(area) else np.nan,
                                 "source": pl.get("source", ""),
                                 # CT-R2 F7: the plate's left-out account, on its first row
                                 "left_out_plaques": (int(pl.get("left_out") or 0) or "") if i == 0 else "",
                                 "left_out_why": (pl.get("left_out_why") or "") if i == 0 else ""})
        return pd.DataFrame(rows, columns=self._STUDY_COLS)

    _STUDY_COLS = ["group", "subgroup", "replicate", "diameter_mm", "area_mm2", "source",
                   "left_out_plaques", "left_out_why"]

    def _long_frame(self):
        """Standalone-ready LONG format: one row per (plaque, metric)."""
        rows = []
        for pl in self._plates_in_order():
            for metric, key in (("diameter_mm", "diam"), ("area_mm2", "area")):
                for val in (pl.get(key) or []):
                    rows.append({"group": pl["group"], "subgroup": pl.get("subgroup", ""),
                                 "replicate": pl["replicate"], "metric": metric, "value": val})
        return pd.DataFrame(rows, columns=["group", "subgroup", "replicate", "metric", "value"])

    def _save_study(self):
        if not self._samples:
            self._warn("Nothing to save yet."); return
        path, _ = QFileDialog.getSaveFileName(self, "Save study", "plaque_study.csv", "CSV (*.csv)")
        if not path:
            return
        if not os.path.splitext(path)[1]:
            path += ".csv"
        _write_csv(self._study_frame(), path)
        self._dirty = False
        self._status("Study saved: %s" % path, 5000)

    def _load_study(self):
        if self._dirty and self._samples:                      # CT-R1 F5: ask before replacing
            q = QMessageBox.question(
                self, "Replace the current study?",
                "The current study (%d sample(s)) has changes that are not saved. Load another study "
                "and replace it?" % len(self._samples), QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if q != QMessageBox.Yes:
                return
        path, _ = QFileDialog.getOpenFileName(self, "Load study", "", "CSV (*.csv *.tsv *.txt);;All files (*.*)")
        if not path:
            return
        try:
            df = _read_text_table(path)
        except (ValueError, OSError) as e:
            self._warn("Could not read the study: %s" % e); return
        self._load_frame(df, os.path.basename(path))

    def _load_frame(self, df, source="study"):
        """Rebuild samples and plates from a study table: the tab's own Save study file (with its
        empty-plate / empty-sample rows), the Wide or Long compiled-data export, or any table with
        a group column and a diameter-in-mm (or area) column. Labels stay exactly as typed
        (CT-R1 F5: None / NA / 007 / 1.0 used to become nan / 7.0 / 1.0)."""
        src_df = df                      # keeps the file line numbers (attrs) for messages
        df = df.copy()
        df.columns = [str(c).strip().lower() for c in df.columns]
        if "group" not in df.columns:
            self._warn("The study file needs a 'group' column."); return
        for c in df.columns:
            if df[c].dtype == object or str(df[c].dtype) == "string":
                df[c] = df[c].fillna("").astype(str).str.strip()
        scol = "subgroup" if "subgroup" in df.columns else None
        rcol = "replicate" if "replicate" in df.columns else None
        long_mode = "metric" in df.columns and "value" in df.columns
        df = df.reset_index(drop=True)
        bad = []                       # CT-R2 F5: (row, column, cell, why) -- refused, never analysed
        if long_mode:
            # CT-R1 F25: the tab's own "Long" export loads too
            met = df["metric"].astype(str).str.strip().str.lower()
            is_d = met.map(lambda m: "diam" in m and not _NOT_MM_RE.search(m))
            is_a = met.map(lambda m: "area" in m and not _NOT_MM_RE.search(m))
            if not (is_d.any() or is_a.any()):
                self._warn("The long-format file has no diameter or area metric."); return
            size_rows = is_d | is_a        # other metrics (turbidity …) may be 0: not checked here
            vals, _n = _numbers(df["value"].where(size_rows, ""))
            bad += self._bad_sizes(df["value"], vals, size_rows, "value")
            df = df.assign(_d=vals.where(is_d), _a=vals.where(is_a))
            dcol, acol = "_d", "_a"
        else:
            dcol, acol = _diam_col(df), _area_col(df)
            if dcol is None and acol is None:
                self._warn("The study file needs a diameter_mm (or area_mm2) column."); return
            for c in (dcol, acol):
                if c is not None:
                    num, _n = _numbers(df[c])
                    bad += self._bad_sizes(df[c], num, None, c)
                    df[c] = num
        if bad:
            # the same rule as Add CSV(s): a size must be a positive number. Nothing is loaded,
            # so the current study stays as it was.
            where = ["%s: %s '%s' (%s)" % (_row_line(src_df, i), col, cell, why)
                     for i, col, cell, why in sorted(bad)[:8]]
            self._warn("Not loaded: %s has %d cell(s) that are not plaque sizes — %s%s. A diameter or "
                       "area must be a positive number (leave the cell empty for a plate without "
                       "plaques). Fix these cells and load the file again."
                       % (source, len(bad), "; ".join(where), "; …" if len(bad) > 8 else ""))
            return
        samples, plates, index = [], [], {}
        for _, r in df.iterrows():
            g = str(r["group"]).strip()
            if not g:
                continue
            sg = str(r[scol]).strip() if scol else ""
            rep = str(r[rcol]).strip() if rcol else "plate1"
            d = r[dcol] if dcol else np.nan
            a = r[acol] if acol else np.nan
            if not any(x["group"] == g and x["subgroup"] == sg for x in samples):
                samples.append({"group": g, "subgroup": sg})
            if rcol and not rep:
                if d == d or a == a:
                    rep = "plate1"                  # values with a blank plate id: one pooled plate
                else:
                    continue                         # an empty-sample placeholder row
            key = (g, sg, rep)
            if key not in index:
                index[key] = {"group": g, "subgroup": sg, "replicate": rep, "diam": [], "area": [],
                              "source": str(r["source"]).strip() if "source" in df.columns else "",
                              "left_out": 0, "left_out_why": ""}
                plates.append(index[key])
            # CT-R2 F7: the left-out account saved with the plate comes back with it
            lo = str(r["left_out_plaques"]).strip() if "left_out_plaques" in df.columns else ""
            if lo and not index[key]["left_out"]:
                try:
                    index[key]["left_out"] = int(float(lo))
                except ValueError:
                    pass
            why = str(r["left_out_why"]).strip() if "left_out_why" in df.columns else ""
            if why and not index[key]["left_out_why"]:
                index[key]["left_out_why"] = why
            if d == d:
                index[key]["diam"].append(float(d))
            if a == a:
                index[key]["area"].append(float(a))
        self._samples, self._plates = samples, plates
        self._refresh_tree(dirty=False)
        self._dirty = False
        self._status("Loaded %d sample(s) · %d plate(s) from %s"
                     % (len(self._samples), len(self._plates), source), 5000)

    @staticmethod
    def _bad_sizes(raw, num, mask, col):
        """CT-R2 F5: [(row, column, cell, why)] for the non-empty cells of a size column that are
        not a positive number (Load study used to drop text silently and analyse 0 and -1.0)."""
        out = []
        txt = raw.astype(str).str.strip()
        for i in range(len(raw)):
            if mask is not None and not bool(mask.iloc[i]):
                continue
            cell = txt.iloc[i]
            if not cell or pd.isna(raw.iloc[i]):
                continue
            v = num.iloc[i]
            if v != v:
                out.append((i, col, cell, "not a number"))
            elif v <= 0:
                out.append((i, col, cell, "zero or negative"))
        return out

    # ================================================================ ANALYSIS
    @staticmethod
    def _is_tagged(sub):
        # CT-R1 F2: a 2nd-factor tag is any non-blank text ('None', 'NA', 'nan' are tags)
        return bool(str(sub if sub is not None else "").strip())

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
        ps = _engine()
        o = dict(ps.DEFAULTS)
        # palette: custom hex wins, else named (the engine checks the colours and their number)
        custom = self.palette_custom.text().strip()
        cols = [c.strip() for c in re.split(r"[,;\s]+", custom) if c.strip()] if custom else []
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
        o["log_y_drop_nonpositive"] = self.logy_cb.isChecked() and self.logy_drop_cb.isChecked()
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
        # the reference sample of "Compare: vs X" (Dunnett) is also the figure's bracket reference
        grouped = any(self._is_tagged(p.get("subgroup", "")) for p in self._plates)
        o["control"] = None if grouped else self.cmp_to_sel.currentData()
        return o

    def _stat_choices(self):
        """The statistics options on screen -> engine arguments. ONE place, used by Analyze and
        by the ZIP, so the two can never disagree again (CT-R1 F2/F14)."""
        ctrl = self.cmp_to_sel.currentData()
        return {"parametric": self.param_sel.currentData(),
                "equal_var": self.var_sel.currentData(),
                "posthoc": "dunnett" if ctrl else "auto",
                "control": ctrl}

    def _on_cmp_changed(self, *_):
        """CT-R2 F11: remember WHICH sample is the reference, so a rename keeps it."""
        name = self.cmp_to_sel.currentData()
        self._cmp_ref = next((s for s in self._samples if s["group"] == name), None) if name else None
        self._sync_controls()
        self._reanalyse_if_ready()

    def _reanalyse_if_ready(self, *_):
        if not self._building and self._last is not None:
            self._run_action(self._analyse)

    def _on_metric_changed(self, *_):
        # CT-R1 F21: a typed Y label belongs to the metric it was typed for
        self.ylabel_in.blockSignals(True)
        self.ylabel_in.setText(self._ylabels.get(self.metric_sel.currentData(), ""))
        self.ylabel_in.blockSignals(False)
        self._reanalyse_if_ready()

    def _remember_ylabel(self):
        self._ylabels[self.metric_sel.currentData()] = self.ylabel_in.text().strip()

    def _on_cosmetic(self, *_):
        if not self._building and self._last is not None:
            self._clear_err()
            self._redraw()

    def _sync_controls(self, *_):
        """Offer only combinations that mean something (CT-R1 F13/F15/F16): around a median only
        IQR / 95 % CI / none; Jitter only with raw plaques; 'hide ≤ 0' only with log Y; in
        grouped mode the violins are always grey and brackets are always vs the control."""
        median = self.center_sel.currentData() == "median"
        m = self.error_sel.model()
        for i in range(self.error_sel.count()):
            if self.error_sel.itemData(i) in ("sem", "sd"):
                m.item(i).setEnabled(not median)
        if median and self.error_sel.currentData() in ("sem", "sd"):
            self.error_sel.blockSignals(True)
            self.error_sel.setCurrentIndex(self.error_sel.findData("iqr"))
            self.error_sel.blockSignals(False)
            if not self._building:
                self._status("Median: error bars switched to IQR (SD and SEM describe a mean).", 6000)
        self.error_sel.setToolTip("Around a median: IQR, a bootstrap 95 % CI of the median, or none." if median
                                  else "Around a mean: SEM, 95 % CI, SD, IQR or none (Auto = SEM).")
        self.jitter.setEnabled(self.show_points.isChecked())
        self.logy_drop_cb.setEnabled(self.logy_cb.isChecked())
        grouped = any(self._is_tagged(p.get("subgroup", "")) for p in self._plates)
        self.fill_sel.setEnabled(not grouped)
        self.fill_sel.setToolTip("Grouped mode: the violins are always grey; the palette colours the "
                                 "2nd-factor values." if grouped else
                                 "Auto: grey violins when the plates carry the colours, coloured violins "
                                 "otherwise. The palette colours whatever is coloured.")
        # CT-R2 F12: Dunnett's test assumes similar variances and is parametric. The choices that
        # cannot be combined with it are greyed (both ways), as Median greys SD and SEM
        if hasattr(self, "cmp_to_sel"):
            dunnett = (not grouped) and self.cmp_to_sel.currentData() is not None
            welch = self.var_sel.currentData() == "no"
            nonpar = self.param_sel.currentData() == "nonparametric"
            why_d = ("Not with Compare: vs a sample (Dunnett): Dunnett's test %s. Choose Compare: All "
                     "pairs first.")
            for combo, key, off, why in (
                    (self.var_sel, "no", dunnett, why_d % "assumes similar variances"),
                    (self.param_sel, "nonparametric", dunnett, why_d % "is parametric")):
                it = combo.model().item(combo.findData(key))
                it.setEnabled(not off)
                it.setToolTip(why if off else "")
            cm = self.cmp_to_sel.model()
            block = ("Variances: Unequal (Welch)" if welch else "Test: Non-parametric" if nonpar else "")
            for i in range(self.cmp_to_sel.count()):
                if self.cmp_to_sel.itemData(i) is not None:
                    cm.item(i).setEnabled(not block)
                    cm.item(i).setToolTip(
                        ("Dunnett's test cannot be combined with %s: it %s. Set %s back first."
                         % (block, "assumes similar variances" if welch else "is parametric",
                            "Variances to Auto or Equal" if welch else "Test to Auto or Parametric"))
                        if block else "")
        am = self.annot_sel.model()
        for i in range(self.annot_sel.count()):
            if self.annot_sel.itemData(i) in ("all", "adjacent", "letters"):
                am.item(i).setEnabled(not grouped)
        if grouped and self.annot_sel.currentData() in ("all", "adjacent", "letters"):
            self.annot_sel.blockSignals(True)
            self.annot_sel.setCurrentIndex(self.annot_sel.findData("auto"))
            self.annot_sel.blockSignals(False)

    def _analyse(self):
        self._clear_err()
        if len(self._plates) < 2:
            self._invalidate_analysis()
            self._warn("Add at least two plates (ideally ≥2 samples) before analyzing."); return
        metric_key = self.metric_sel.currentData()
        vcol = "diameter_mm" if metric_key == "diam" else "area_mm2"
        metric_name = "Diameter (mm)" if metric_key == "diam" else "Area (mm²)"
        tidy = self._tidy_frame()
        df = tidy.rename(columns={vcol: "value"})[["group", "subgroup", "replicate", "value"]].copy()
        # the rows left out are counted in the Report (as the engine's data notes do in the ZIP)
        miss = df[df["value"].isna()]
        self._data_note = ""
        if len(miss):
            plates = list(dict.fromkeys("%s/%s" % (g, r) for g, r in zip(miss["group"], miss["replicate"])))
            self._data_note = ("%d plaque row(s) have no %s value and are left out (plates: %s%s)."
                               % (len(miss), metric_name.split(" (")[0].lower(), ", ".join(plates[:8]),
                                  ", …" if len(plates) > 8 else ""))
        df = df.dropna(subset=["value"])
        self._plate_warns = self._unsized_warnings(metric_key)
        if df.empty:
            self._invalidate_analysis()
            self._warn("No %s values found — did you measure that metric?" % metric_name); return
        # decide the mode from the SAMPLE tags, not from the (metric-filtered) rows — so switching
        # metric can't silently flip grouped↔single just because some tagged plates lack that metric
        has_sub = any(self._is_tagged(p.get("subgroup", "")) for p in self._plates)
        try:
            ok = (self._analyse_grouped(df, metric_name, metric_key) if has_sub
                  else self._analyse_single(df.drop(columns=["subgroup"]), metric_name, metric_key))
        except (Exception, SystemExit) as e:                      # noqa: BLE001 -- CT-R1 F1
            ok = False
            msg = _stats_message(e)
        else:
            msg = None
        if not ok:
            keep = self.err.text()
            text = ("Analysis failed: %s" % msg) if msg else (keep or "Analysis failed.")
            if self._last is not None:
                # CT-R2 F12: a refusal never wipes a valid result of the SAME data (a data change
                # has already cleared it): the last good result stays, and the controls go back
                # to the choices it was computed with, so the screen and the ZIP agree with it
                self._restore_controls(self._last[1])
                self._warn(text + " The previous result stays on screen; the options were set back "
                           "to the ones it was computed with.")
                return
            # CT-R1 F19: nothing valid to keep: clear the results and disable every export
            self._invalidate_analysis()
            self._warn(text)
            return
        for b in self._export_buttons:
            b.setEnabled(True)
        if self._last_fig is None:                                # the figure itself failed
            for b in self._figure_buttons:
                b.setEnabled(False)

    def _restore_controls(self, pl):
        """Put Metric / Test / Variances / Compare / Control back to the choices of result `pl`."""
        sc = pl.get("stat_choices") or {}
        self._building = True
        try:
            for combo, val in ((self.metric_sel, pl.get("metric_key")), (self.param_sel, sc.get("parametric")),
                               (self.var_sel, sc.get("equal_var"))):
                i = combo.findData(val) if val is not None else -1
                if i >= 0:
                    combo.blockSignals(True); combo.setCurrentIndex(i); combo.blockSignals(False)
            if "control" in sc:
                i = self.cmp_to_sel.findData(sc["control"]) if sc["control"] else 0
                self.cmp_to_sel.blockSignals(True)
                self.cmp_to_sel.setCurrentIndex(max(i, 0))
                self.cmp_to_sel.blockSignals(False)
                name = self.cmp_to_sel.currentData()
                self._cmp_ref = next((s for s in self._samples if s["group"] == name), None) if name else None
            if pl.get("control") and self.control_sel.findText(pl["control"]) >= 0:
                self.control_sel.blockSignals(True)
                self.control_sel.setCurrentText(pl["control"])
                self.control_sel.blockSignals(False)
        finally:
            self._building = False
        self._sync_controls()

    @staticmethod
    def _effect_text(eff):
        """'Cohen's d = 8.20', 'η² = 0.85' or 'n/a' (CT-R1 F25: was 'cohens=8.20' / 'cohens=nan')."""
        names = {"cohens_d": "Cohen's d", "hedges_g": "Hedges' g", "eta_squared": "η²",
                 "epsilon_squared": "ε²"}
        ek = next(iter(eff or {}), None)
        if ek is None:
            return "n/a"
        v = eff[ek]
        try:
            v = float(v)
        except (TypeError, ValueError):
            return "n/a"
        if v != v or np.isinf(v):
            return "n/a"
        return "%s = %.2f" % (names.get(ek, ek.replace("_", " ")), v)

    def _analyse_single(self, df, metric_name, metric_key):
        ps = _engine()
        present = set(df["group"])
        order = self._ordered_groups(present) or list(dict.fromkeys(df["group"].tolist()))
        sc = self._stat_choices()
        omni, posthoc, unit, have_rep = ps.run_stats(
            df, order, "auto", sc["parametric"], equal_var=sc["equal_var"], posthoc=sc["posthoc"],
            control=sc["control"])
        summ = ps.group_summary(df, order, unit=unit)
        rep = ps.replicate_means(df)
        pairwise = pd.DataFrame(omni.get("pairwise") or [])
        empty = [s["group"] for s in self._samples if s["group"] not in present]
        if empty:          # a sample without plaques (of this metric) cannot be drawn or tested
            omni.setdefault("warnings", []).append(
                "%s %s no %s values, so %s left out of the figure and the test."
                % (", ".join(empty), "has" if len(empty) == 1 else "have", metric_name.split(" (")[0].lower(),
                   "it is" if len(empty) == 1 else "they are"))
        self._last = ("single", {"df": df, "order": order, "posthoc": posthoc, "omni": omni,
                                  "unit": unit, "have_rep": have_rep,
                                  "metric_name": metric_name, "metric_key": metric_key,
                                  "summary": summ, "replicates": rep, "pairwise": pairwise,
                                  "stat_choices": dict(sc), "data_note": self._data_note,
                                  "plate_warns": list(self._plate_warns)})
        self._redraw()

        n_plates = int(df.dropna(subset=["replicate"]).drop_duplicates(["group", "replicate"]).shape[0])
        self._chips["groups"].setText(str(len(order)))
        self._chips["plates"].setText(str(n_plates))         # CT-R1 F25: plates WITH plaques
        self._chips["unit"].setText("plate" if unit == "replicate" else "plaque")
        self._chips["test"].setText(str(omni.get("test", "—")))
        self._chips["p"].setText(ps.fmt_p(omni.get("p")))
        self._chips["effect"].setText(self._effect_text(omni.get("effect")))

        self._set_table(self.tbl_group, self._summary_display(summ))
        self._set_table(self.tbl_rep, self._replicate_display(rep))
        post = omni.get("posthoc") or omni.get("test") or ""
        if omni.get("control"):
            post = "%s, each sample vs %s" % (post, omni["control"])
        self.cmp_cap.setText("Pairwise comparisons (%s; on the %s)" % (post, ps._unit_word(unit)))
        self._set_table(self.tbl_cmp, self._pairwise_display(pairwise))

        warns = list(omni.get("warnings") or []) + list(self._plate_warns)
        self.warn_lbl.setText(self._words("\n".join("⚠ " + w for w in warns)))
        self._refresh_report()
        self._status("Analyzed %d samples (%s)." % (len(order), omni.get("test")), 5000)
        return True

    def _figure_text(self, fig=None):
        """The figure sentence (+ what the annotation means) of `fig` (default: the figure on
        screen) -- the ONE builder of the caption under the figure, the Report's 'Figure:' line
        and the ZIP report's Figure section (CT-R2 F6/F14). The key's note already ends with the
        annotation sentence; fig.annotation_note is added only when the note does not say it."""
        legend_key = _legend_key()
        fig = fig if fig is not None else self._last_fig
        if fig is None:
            return ""
        key = legend_key.from_figure(fig) or {}
        note = str(key.get("note") or "").strip()
        ann = str(getattr(fig, "annotation_note", "") or "").strip()

        def flat(t):
            return re.sub(r"\s+", " ", t.replace("`", "")).strip()
        if ann and flat(ann) not in flat(note):
            note = (note + " " + ann).strip()
        return note

    def _unsized_warnings(self, metric_key):
        """CT-R2 F8: every plate without a value of this metric, named (it is listed under its
        sample but not counted as a plate)."""
        out = []
        for p in self._plates_in_order():
            if p.get(metric_key):
                continue
            lo = int(p.get("left_out") or 0)
            what = ("no sized plaques (%d left out: %s)" % (lo, p.get("left_out_why") or "flagged")
                    if lo else "no plaques" if not (p.get("diam") or p.get("area")) else
                    "no %s values" % ("diameter" if metric_key == "diam" else "area"))
            out.append("%s/%s has %s, so it is not counted as a plate." % (p["group"], p["replicate"], what))
        return out

    def _account_lines(self):
        """CT-R2 F7: one line per plate with plaques left out of the sizes, for the Report and the
        ZIP report (the tree tooltip shows the same sentence)."""
        lines = []
        for p in self._plates_in_order():
            if int(p.get("left_out") or 0):
                lines.append("%s · %s" % (p["group"], _plate_account(p)))
        if not lines:
            return []
        n = sum(int(p.get("left_out") or 0) for p in self._plates)
        return (["Plaques left out of the sizes (%d in all; they count on their plate, but their "
                 "diameter is not this plate's edge definition):" % n] + ["  " + x for x in lines])

    def _set_report(self, lines):
        lines = list(lines)
        if getattr(self, "_data_note", ""):
            lines += ["", "Data: " + self._data_note]
        pw = [w for w in getattr(self, "_plate_warns", []) if not any(w in str(x) for x in lines)]
        if pw:
            lines += [""] + ["⚠ " + w for w in pw]
        acc = self._account_lines()
        if acc:
            lines += [""] + acc
        self.report.setPlainText(self._words("\n".join(lines)))

    def _words(self, text):
        """_ui_words with the Compare reference of the result on screen."""
        ref = None
        if self._last is not None and self._last[0] == "single":
            ref = (self._last[1].get("stat_choices") or {}).get("control")
        return _ui_words(text, ref)

    def _refresh_report(self):
        """CT-R2 F6: the Report is rebuilt from the result AND the current options on every
        redraw, so after a Center / Error bars / Brackets change it says what the figure shows."""
        if self._last is None:
            return
        kind, pl = self._last
        self._data_note = pl.get("data_note", "")
        self._plate_warns = list(pl.get("plate_warns") or [])
        lines = (self._report_lines_single(pl) if kind == "single" else self._report_lines_grouped(pl))
        self._set_report(lines)

    def _report_lines_single(self, pl):
        ps = _engine()
        metric_name, summ, omni = pl["metric_name"], pl["summary"], pl["omni"]
        unit, have_rep = pl["unit"], pl["have_rep"]
        o = self._opts(pl["metric_key"])
        try:
            centers = ps.center_table(pl["df"], pl["order"], o)
        except (Exception, SystemExit):                            # noqa: BLE001
            centers = None
        L = [ps.paste_sentence(metric_name, summ, omni, unit, have_rep, o, centers=centers), ""]
        L.append("Test choice: %s, followed by %s. %s %s" % (
            omni.get("test"), omni.get("posthoc") or "no post-hoc test",
            omni.get("choice_note") or "", omni.get("variance_rule") or ""))
        ft = self._figure_text()
        if ft:
            L += ["", "Figure: " + ft]
        L += ["", ps.power_sentence(omni.get("power"), unit).replace("**", "")]
        icc = omni.get("icc")
        if icc and icc.get("icc") == icc.get("icc"):
            L.append("Plate-to-plate variation: %.0f %% of the variance within a sample lies between "
                     "plates (ICC = %.2f; %d plates, %d plaques)."
                     % (100 * icc["icc"], icc["icc"], icc["n_plates"], icc["n_plaques"]))
        ws, ns = list(omni.get("warnings") or []), list(omni.get("notes") or [])
        if ws or ns:
            L.append("")
            L += ["⚠ " + w for w in ws]
            L += ["Note: " + n for n in ns]
        return L

    def _report_lines_grouped(self, pl):
        ps = _engine()
        comp, unit, control = pl["comparisons"], pl["unit"], pl["control"]
        L = [ps.paste_sentence(pl["metric_name"], comp=comp, unit=unit, control=control,
                               opts=self._opts(pl["metric_key"])), ""]
        L.append("p-values are Holm-adjusted within each sample (raw p in the p_raw column); each "
                 "2nd-factor value is compared with the control '%s' by a %s on the %s."
                 % (control, str(comp["test"].iloc[0]) if len(comp) else "test", ps._unit_word(unit)))
        ft = self._figure_text()
        if ft:
            L += ["", "Figure: " + ft]
        warns, notes = pl.get("warns") or [], (pl.get("info") or {}).get("notes") or []
        if warns or notes:
            L.append("")
            L += ["⚠ " + w for w in warns]
            L += ["Note: " + n for n in notes]
        return L

    # ---- display copies of the result tables (the raw numbers stay in self._last for the CSVs)
    @staticmethod
    def _summary_display(summ):
        """CT-R1 F12: the plate-level numbers (what the test and the bar use) beside the per-plaque
        ones -- they used to be three different 'means' with nothing saying which is which."""
        if summ is None or not len(summ):
            return pd.DataFrame()
        per_plate = "unit" in summ.columns and (summ["unit"] == "plate").any()
        out = pd.DataFrame({"sample": summ["group"].astype(str)})
        if per_plate:
            out["N plates"] = summ["n_units"].astype(int)
            out["plate mean"] = summ["unit_mean"]
            out["plate SD"] = summ["unit_sd"]
            out["plate SEM"] = summ["unit_sem"]
        out["n plaques"] = summ["n"].astype(int)
        out["plaque mean"] = summ["mean"]
        out["plaque SD"] = summ["sd"]
        out["plaque SEM"] = summ["sem"]
        out["median"] = summ["median"]
        out["IQR"] = summ["iqr"]
        return _round_df(out)

    @staticmethod
    def _replicate_display(rep):
        if rep is None or not len(rep):
            return pd.DataFrame()
        cols = [c for c in ("group", "subgroup", "replicate") if c in rep.columns]
        out = rep[cols].copy().rename(columns={"group": "sample", "subgroup": "2nd factor",
                                               "replicate": "plate"})
        out["plate mean"] = rep["value"].values
        out["n plaques"] = rep["n_plaques"].astype(int).values
        return _round_df(out)

    @staticmethod
    def _pairwise_display(pw):
        """p via the engine's fmt_p; a comparison that could not be run reads n/a (CT-R1 F9)."""
        ps = _engine()
        if pw is None or not len(pw):
            return pd.DataFrame()
        out = pd.DataFrame({"sample A": pw["group_a"].astype(str), "sample B": pw["group_b"].astype(str),
                            "mean A": pw["mean_a"], "mean B": pw["mean_b"], "difference": pw["mean_diff"]})
        if "diff_ci95_lo" in pw.columns:
            out["95% CI"] = ["[%.3g, %.3g]" % (lo, hi) if lo == lo and hi == hi else "n/a"
                             for lo, hi in zip(pw["diff_ci95_lo"], pw["diff_ci95_hi"])]
        if "hedges_g" in pw.columns:
            out["Hedges' g"] = pw["hedges_g"]
        out["p (adjusted)"] = [ps.fmt_p(p) for p in pw["p_adj"]]
        out["signif"] = pw["signif"].astype(str)
        return _round_df(out)

    def _analyse_grouped(self, df, metric_name, metric_key):
        ps = _engine()
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
        summ, comp, unit, info = ps.grouped_stats(df, group_order, sub_order, control, parametric,
                                                  return_info=True)
        pm = ps._plate_means_gs(df)
        warns = list(info.get("warnings") or []) + list(self._plate_warns)
        if excluded:
            warns.append("%d plate(s) without a 2nd-factor tag were EXCLUDED (%d analyzed). Clear all "
                         "2nd-factor tags to compare every plate as single-factor samples."
                         % (excluded, analyzed))
        self._last = ("grouped", {"df": df, "group_order": group_order, "sub_order": sub_order,
                                  "control": control, "comparisons": comp, "unit": unit,
                                  "metric_name": metric_name, "metric_key": metric_key,
                                  "summary": summ, "replicates": pm, "info": info, "warns": warns,
                                  "stat_choices": {"parametric": parametric},
                                  "data_note": self._data_note, "plate_warns": list(self._plate_warns)})
        self._redraw()

        self._chips["groups"].setText("%d×%d" % (len(group_order), len(sub_order)))
        self._chips["plates"].setText(str(analyzed))
        self._chips["unit"].setText("plate" if unit == "replicate" else "plaque")
        self._chips["test"].setText(str(comp["test"].iloc[0]) if len(comp) else "—")
        self._chips["p"].setText("per row" if len(comp) else "—")
        self._chips["effect"].setText("vs %s" % control)

        self._set_table(self.tbl_group, _round_df(summ))
        self._set_table(self.tbl_rep, self._replicate_display(pm))
        self.cmp_cap.setText("Control comparisons (vs %s; Holm-adjusted within each sample)" % control)
        disp = comp.copy()
        if len(disp):
            disp["p"] = [ps.fmt_p(p) for p in disp["p"]]
            if "p_raw" in disp.columns:
                disp["p_raw"] = [ps.fmt_p(p) for p in disp["p_raw"]]
        self._set_table(self.tbl_cmp, _round_df(disp))

        self.warn_lbl.setText(self._words("\n".join("⚠ " + w for w in warns)))
        self._refresh_report()
        self._status("Grouped comparison vs '%s' across %d sample(s)." % (control, len(group_order)), 5000)
        return True

    # ---------------------------------------------------------------- figure
    def _build_fig(self, opts):
        ps = _engine()
        kind, pl = self._last
        if kind == "single":
            return ps.plot_violin(pl["df"], pl["order"], opts, pl["metric_name"], pl["posthoc"])
        o = dict(opts); o["_sublabel"] = "2nd factor"
        return ps.plot_grouped(pl["df"], pl["group_order"], pl["sub_order"], pl["control"], o,
                               pl["metric_name"], pl["comparisons"])

    def _render(self, opts):
        """A fresh figure from the current state; a failure closes any half-built figure and
        re-raises (StatsError / SystemExit included)."""
        import matplotlib.pyplot as plt
        before = set(plt.get_fignums())
        try:
            return self._build_fig(opts)
        except BaseException:
            for n in set(plt.get_fignums()) - before:
                plt.close(n)
            raise

    def _redraw(self):
        if self._last is None:
            return
        opts = self._opts(self._last[1]["metric_key"])
        try:
            fig = self._render(opts)
            # CT-R2 F4/F19: the size the figure really has (a key below makes it taller), taken
            # BEFORE a canvas is attached (a Qt canvas resizes its figure)
            self._fig_size = tuple(float(x) for x in fig.get_size_inches())
            self.size_lbl.setText(self._size_note(self._fig_size, opts, "Saved figures will be"))
        except (Exception, SystemExit) as e:                      # noqa: BLE001 -- CT-R1 F1/F19
            # the old figure no longer matches the controls: take it off screen, keep the results
            self._clear_fig_area(restore_placeholder=True)
            self.fig_placeholder.setText("The figure cannot be drawn with these settings — see the "
                                         "message above.")
            self.fig_caption.setText("")
            self.key_text.clear()
            for b in self._figure_buttons:
                b.setEnabled(False)
            self._warn("Could not draw: %s" % _stats_message(e))
            self._refresh_report()
            return
        self._show_fig(fig)
        self._refresh_report()                     # CT-R2 F6: the Report follows the figure
        if self._last is not None and self.savesum_btn.isEnabled():
            for b in self._figure_buttons:
                b.setEnabled(True)

    @staticmethod
    def _size_note(size, opts, lead="Saved at"):
        """'Saved at 6.0 × 7.5 in: the key was placed below, so the figure is taller than the 5.4 in
        asked for.' (CT-R2 F4: the status and the ZIP used to report the size asked for)."""
        w, h = size
        txt = "%s %.1f × %.1f in" % (lead, w, h)
        aw, ah = float(opts["width"]), float(opts["height"])
        if abs(h - ah) > 0.05 and abs(w - aw) <= 0.05:
            return txt + (": the key was placed below, so the figure is %s than the %.1f in asked for."
                          % ("taller" if h > ah else "shorter", ah))
        if abs(h - ah) > 0.05 or abs(w - aw) > 0.05:
            return txt + (": the figure grew to fit its key and labels (%.1f × %.1f in asked for)."
                          % (aw, ah))
        return txt + "."

    def _preview_scale(self, w_in):
        """CT-R2 F19/F16: the preview is the figure at its size in inches, scaled AS A WHOLE so it
        fits the panel (1.0 = 96 px per inch). Text keeps its proportion to the plot."""
        if not self.isVisible():
            return 1.0
        sa = self._scroll_area()
        if sa is None:
            return 1.0
        from PySide6.QtCore import QPoint
        left = self.fig_holder.mapTo(self, QPoint(0, 0)).x()
        m = self.fig_layout.contentsMargins()
        avail = sa.viewport().width() - 2 * left - m.left() - m.right() - 4
        return max(0.25, min(1.0, avail / (w_in * 96.0)))

    def _scroll_area(self):
        """The main window's scroll area that holds this tab (found once). Looked up from the
        window, not by walking parentWidget(): that walk made PySide drop the wrappers of
        unrelated combo-box models."""
        sa = getattr(self, "_sa", None)
        if sa is None:
            from PySide6.QtWidgets import QScrollArea
            w = self.window()
            sa = next((a for a in (w.findChildren(QScrollArea) if w is not None else [])
                       if a.widget() is self), None)
            self._sa = sa
        return sa

    def _fit_canvas(self):
        """Size the canvas to the figure's inches at the preview scale (no re-render)."""
        if self.canvas is None or self._last_fig is None:
            return
        fig = self._last_fig
        w_in, h_in = getattr(self, "_fig_size", None) or fig.get_size_inches()
        dpi = 96.0 * self._preview_scale(w_in)
        if abs(getattr(fig, "_original_dpi", fig.dpi) - dpi) > 0.5 or self.canvas.width() != int(round(w_in * dpi)):
            fig._original_dpi = dpi
            fig._set_dpi(dpi * self.canvas.device_pixel_ratio, forward=False)
            self.canvas.setFixedSize(int(round(w_in * dpi)), int(round(h_in * dpi)))
            m = self.fig_layout.contentsMargins()
            self.fig_holder.setMinimumHeight(self.canvas.height() + self.toolbar.sizeHint().height() + 2
                                             + m.top() + m.bottom())
            self.canvas.draw_idle()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.canvas is not None and not getattr(self, "_fitting", False):
            from PySide6.QtCore import QTimer
            self._fitting = True

            def fit():
                try:
                    self._fit_canvas()
                finally:
                    self._fitting = False
            QTimer.singleShot(0, fit)

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
        self.fig_holder.setMinimumHeight(0)
        if restore_placeholder:
            self.fig_placeholder = QLabel("The violin plot appears here after you click Analyze.")
            self.fig_placeholder.setObjectName("Placeholder"); self.fig_placeholder.setAlignment(Qt.AlignCenter)
            self.fig_placeholder.setMinimumHeight(360)
            self.fig_placeholder.setWordWrap(True)
            self.fig_layout.addWidget(self.fig_placeholder)

    def _show_fig(self, fig):
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
        from matplotlib.backends.backend_qtagg import NavigationToolbar2QT
        self._clear_fig_area()
        # CT-R2 F19: the preview IS the figure at its size in inches: the figure's dpi is the
        # preview scale (96 px per inch, less when the panel is narrower), set BEFORE the canvas
        # exists, and the canvas is pinned to inches x dpi. (The canvas used to be pinned at 96 px
        # per inch while the figure kept 100 dpi, so the preview was an 8.06 in figure.)
        w_in, h_in = getattr(self, "_fig_size", None) or tuple(fig.get_size_inches())
        dpi = 96.0 * self._preview_scale(w_in)
        fig.set_dpi(dpi)
        px_w, px_h = int(round(w_in * dpi)), int(round(h_in * dpi))
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
        # CT-R1 F24: the figure area is at least as tall as the canvas (+ toolbar), so the page
        # scrolls with ONE scroll bar instead of squeezing the figure into a small inner box
        m = self.fig_layout.contentsMargins()
        self.fig_holder.setMinimumHeight(px_h + toolbar.sizeHint().height() + cl.spacing()
                                         + m.top() + m.bottom())
        canvas.draw()
        self._refresh_key_text(fig)
        self.fig_caption.setText(self._words(self._figure_text()))

    def _refresh_key_text(self, fig=None):
        """The text starter always comes from the figure on screen (never a stored copy)."""
        legend_key = _legend_key()
        key = legend_key.from_figure(fig) if fig is not None else None
        self.key_text.setText(legend_key.text_starter(key) if key else "")
        self.key_text.setCursorPosition(0)

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
        for name in ("report", "key_text"):
            if hasattr(self, name):
                getattr(self, name).clear()
        for name in ("warn_lbl", "fig_caption", "size_lbl"):
            if hasattr(self, name):
                getattr(self, name).setText("")
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
        # "Compare: all pairs / vs <sample>" follows the current sample names; the reference is
        # the sample itself, so renaming it keeps it (CT-R2 F11: it used to fall back to All pairs)
        ref = self._cmp_ref
        cur_ref = ref["group"] if ref is not None and any(s is ref for s in self._samples) else None
        if cur_ref is None:
            self._cmp_ref = None
        self.cmp_to_sel.blockSignals(True)
        self.cmp_to_sel.clear()
        self.cmp_to_sel.addItem("All pairs", None)
        for g in groups:
            self.cmp_to_sel.addItem("vs %s (Dunnett)" % g, g)
        i = self.cmp_to_sel.findData(cur_ref) if cur_ref is not None else 0
        self.cmp_to_sel.setCurrentIndex(i if i >= 0 else 0)
        self.cmp_to_sel.blockSignals(False)
        for w in (self.var_cap, self.var_sel, self.cmp_to_cap, self.cmp_to_sel):
            w.setVisible(not has_sub)
        if hasattr(self, "annot_sel"):
            self._sync_controls()
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
    _FIG_FILTERS = ("PNG image (*.png);;SVG — vector, editable (*.svg);;PDF — vector (*.pdf);;"
                    "TIFF — journal raster (*.tiff);;EPS — vector (*.eps)")

    def _with_ext(self, path, sel):
        """CT-R1 F20: a typed figure extension wins over the filter, and a name with dots
        ('fig_0.5MOI') keeps them -- the filter's extension is appended, never substituted."""
        ext = os.path.splitext(path)[1].lower()
        if ext in self._FIG_EXTS:
            return path
        want = next((e for k, e in self._EXT_FOR.items() if (sel or "").startswith(k)), ".png")
        return path + want

    def _save_figure_file(self, fig, path, dpi):
        """One rule for every figure file (Save figure and the ZIP): the chosen size in inches
        exactly (no tight crop) at the Export DPI (CT-R1 F20)."""
        import matplotlib
        ext = os.path.splitext(path)[1].lower()
        kw = {"dpi": int(dpi), "facecolor": "white"}
        if ext in (".tif", ".tiff"):
            kw["pil_kwargs"] = {"compression": "tiff_lzw"}
        with matplotlib.rc_context({"svg.fonttype": "none", "pdf.fonttype": 42, "ps.fonttype": 42}):
            fig.savefig(path, **kw)

    def _save_fig(self):
        if self._last is None:
            return
        path, sel = QFileDialog.getSaveFileName(self, "Save figure", "plaque_figure.png", self._FIG_FILTERS)
        if not path:
            return
        path = self._with_ext(path, sel)
        ext = os.path.splitext(path)[1].lower()
        self._fig_ext = ext or ".png"
        opts = self._opts(self._last[1]["metric_key"])
        dpi = int(opts["dpi"])
        import matplotlib.pyplot as plt
        fig = None
        try:
            fig = self._render(opts)       # a FRESH figure at exactly the configured size
            size = tuple(float(x) for x in fig.get_size_inches())
            self._save_figure_file(fig, path, dpi)
        except (Exception, SystemExit) as e:                      # noqa: BLE001
            self._warn("Could not save figure: %s" % _stats_message(e)); return
        finally:
            if fig is not None:
                plt.close(fig)                    # always release the export figure
        # CT-R2 F4: the size the file really has, and why it differs from the one asked for
        msg = "Figure saved (%s, %d dpi): %s — %s" % (ext.lstrip("."), dpi, path,
                                                     self._size_note(size, opts))
        if ext == ".eps":
            msg += " — EPS cannot store transparency: the violins are drawn opaque (use PDF or SVG to keep it)."
        self._status(msg, 8000)

    def _save_key(self, path=None):
        """Save the legend key of the CURRENT figure (re-drawn from the current samples, names,
        palette and selection), in the figure's format -- the one last used in Save figure."""
        if self._last is None:
            return None
        legend_key = _legend_key()
        if path is None:
            first = next((k for k, e in self._EXT_FOR.items() if e == self._fig_ext), "PNG")
            filters = self._FIG_FILTERS.split(";;")
            sel0 = next((f for f in filters if f.startswith(first)), filters[0])
            path, sel = QFileDialog.getSaveFileName(self, "Save legend key",
                                                    "plaque_figure_legend_key" + self._fig_ext,
                                                    self._FIG_FILTERS, sel0)
            if not path:
                return None
            path = self._with_ext(path, sel)
        opts = self._opts(self._last[1]["metric_key"])
        dpi = int(opts["dpi"])
        import matplotlib.pyplot as plt
        fig = None
        try:
            fig = self._render(opts)
            key = legend_key.from_figure(fig)
            if not key or not key.get("entries"):
                self._warn("This figure has no sample or plate colours to key."); return None
            legend_key.save_key(key, path, dpi=dpi)
        except (Exception, SystemExit) as e:                      # noqa: BLE001
            self._warn("Could not save the legend key: %s" % _stats_message(e)); return None
        finally:
            if fig is not None:
                plt.close(fig)
        self._status("Legend key saved: %s" % path, 6000)
        return path

    def _copy_key_text(self):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.key_text.text())
        self._status("Legend text copied to the clipboard.", 3000)

    def _save_summary(self):
        if self._last is None:
            return
        kind, pl = self._last
        path, _ = QFileDialog.getSaveFileName(self, "Save summary", "plaque_summary.csv", "CSV (*.csv)")
        if not path:
            return
        if not os.path.splitext(path)[1]:
            path += ".csv"
        pl["summary"].to_csv(path, index=False)
        extra = "comparisons" if kind == "grouped" else "pairwise"
        if pl.get(extra) is not None and len(pl[extra]):
            pl[extra].to_csv(os.path.splitext(path)[0] + "_" + extra + ".csv", index=False)
        self._status("Summary (+ %s) saved next to it." % extra, 5000)

    def _save_data_wide(self):
        if not self._plates:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save compiled data (wide)", "plaque_compiled_wide.csv", "CSV (*.csv)")
        if path:
            _write_csv(self._tidy_frame(), path)
            self._status("Wide per-plaque data saved: %s" % path, 5000)

    def _save_data_long(self):
        if not self._plates:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save compiled data (long, standalone-ready)",
                                              "plaque_compiled_long.csv", "CSV (*.csv)")
        if path:
            _write_csv(self._long_frame(), path)
            self._status("Long-format data saved (drops into the standalone app): %s" % path, 6000)

    def _export_zip(self):
        if self._last is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export everything (ZIP)", "plaque_analysis.zip", "ZIP (*.zip)")
        if not path:
            return
        if not path.lower().endswith(".zip"):
            path += ".zip"
        try:
            self._write_everything(path)
        except (Exception, SystemExit) as e:                      # noqa: BLE001 -- CT-R1 F1
            self._warn("Export failed: %s" % _stats_message(e)); return
        self._status("Exported everything: %s" % path, 6000)

    def _write_everything(self, path):
        """Build the full standalone-parity bundle at `path` (figure in every format + its legend
        key + summaries + pairwise + report.md + run_config.json + table images + compiled data).
        The engine gets the IN-MEMORY table and the screen's own order, 2nd-factor order, key
        title, control and test options (CT-R1 F1/F2/F14): no CSV round trip that re-reads the
        labels, so the bundle's samples, tags and statistics are the screen's."""
        import shutil
        from datetime import datetime
        import matplotlib.pyplot as plt
        ps = _engine()
        kind, pl = self._last
        metric_key = pl["metric_key"]
        vcol = "diameter_mm" if metric_key == "diam" else "area_mm2"
        opts = self._opts(metric_key)
        formats = ["png", "svg", "pdf", "tiff"]
        tmp = tempfile.mkdtemp(prefix="plaque_zip_")
        try:
            out = os.path.join(tmp, "out"); os.makedirs(out, exist_ok=True)
            tidy = self._tidy_frame()
            cols = ["group", "subgroup", "replicate", vcol] if kind == "grouped" else ["group", "replicate", vcol]
            args = dict(opts)
            args.update({"data": tidy[cols].copy(), "group": "group", "value": vcol,
                         "replicate": "replicate", "metric": None, "unit": "auto",
                         # CT-R2 F12: the statistics choices of the result ON SCREEN (a refused
                         # change keeps the last good result, so the live controls may differ)
                         "parametric": (pl.get("stat_choices") or {}).get(
                             "parametric", self.param_sel.currentData()),
                         "formats": formats, "dpi": int(opts["dpi"]),
                         "stats_table": True, "out": out, "legend_key": True,
                         "order": pl["group_order"] if kind == "grouped" else pl["order"],
                         "_stamp": datetime.now().strftime("%Y-%m-%d %H:%M")})
            if kind == "grouped":
                args.update({"subgroup": "subgroup", "control": pl["control"],
                             "sub_order": list(pl["sub_order"]), "_sublabel": "2nd factor",
                             "posthoc": "auto"})
            else:
                sc = pl.get("stat_choices") or self._stat_choices()
                args.update({"subgroup": None, "equal_var": sc["equal_var"], "posthoc": sc["posthoc"],
                             "control": sc["control"]})
            res = ps.run(args)
            # the figure files: the screen's own figure, at the chosen size and Export DPI (F20)
            base = os.path.join(out, ("grouped_%s" if kind == "grouped" else "violin_%s") % ps._safe(res["metric"]))
            fig = self._render(opts)
            try:
                zip_size = [round(float(x), 3) for x in fig.get_size_inches()]
                for fmt in formats:
                    self._save_figure_file(fig, "%s.%s" % (base, fmt), opts["dpi"])
                fig_text = self._figure_text(fig)
            finally:
                plt.close(fig)
            # provenance: no temp paths; the Toolkit's version (CT-R1 F25)
            for f in os.listdir(out):
                if f.startswith("run_config_") and f.endswith(".json"):
                    fp = os.path.join(out, f)
                    with open(fp, encoding="utf-8") as fh:
                        cfg = json.load(fh)
                    cfg["out"] = os.path.basename(path)
                    cfg["data"] = "Analyze tab study (in-memory, %d plaque rows)" % len(tidy)
                    cfg["source"] = "Plaque Toolkit — Analyze tab"
                    cfg["toolkit_version"] = (cfg.get("versions") or {}).get("toolkit")
                    cfg["figure_size_in"] = zip_size                       # CT-R2 F4: as saved
                    cfg["figure_size_asked_in"] = [opts["width"], opts["height"]]
                    cfg["figure_size_note"] = self._size_note(zip_size, opts)
                    with open(fp, "w", encoding="utf-8") as fh:
                        json.dump(cfg, fh, indent=2, default=str)
            # CT-R2 F7/F8: the plates' left-out account and the plates without sizes
            extra = (["- ⚠️ %s" % w for w in pl.get("plate_warns") or []]
                     + ["- %s" % x.strip() for x in self._account_lines()])
            for f in os.listdir(out):
                if f.startswith("report_") and f.endswith(".md"):
                    fp = os.path.join(out, f)
                    with open(fp, encoding="utf-8") as fh:
                        md = fh.read()
                    # CT-R2 F6/F14: the Figure section is the tab's own figure text (the caption)
                    md = re.sub(r"(\n## Figure\n\n?)(.*?)(\n(?=## )|\Z)",
                                lambda m: m.group(1) + fig_text + "\n" + m.group(3), md, count=1,
                                flags=re.S)
                    if extra:
                        md = md.rstrip("\n") + "\n\n## Plates and plaques left out\n\n" + "\n".join(extra) + "\n"
                    # CT-R2 F13: the tab's control names, not command-line flags
                    with open(fp, "w", encoding="utf-8") as fh:
                        fh.write(self._words(md))
            # also drop the standalone-ready long + wide CSVs and the study file in the bundle
            _write_csv(self._long_frame(), os.path.join(out, "compiled_long.csv"))
            _write_csv(tidy, os.path.join(out, "compiled_wide.csv"))
            _write_csv(self._study_frame(), os.path.join(out, "study.csv"))
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
        self._status("Report copied to the clipboard.", 3000)

    # ================================================================ misc
    @staticmethod
    def _pfmt(p):
        try:
            fmt_p = _engine().fmt_p
            return fmt_p(p)
        except Exception:                                          # noqa: BLE001 -- Light build
            try:
                p = float(p)
            except (TypeError, ValueError):
                return "n/a"
            if p != p:
                return "n/a"
            return "< 0.001" if p < 1e-3 else "%.3f" % p

    def _status(self, msg, ms=5000):
        try:
            self.window().statusBar().showMessage(msg, ms)
        except Exception:                                          # noqa: BLE001 -- no main window
            pass

    def _warn(self, msg):
        self.err.setText(msg)
        self._status(msg, 6000)

    # where the Analyze statistics are explained, first one found wins: the statistics engine's
    # README section 4 (source checkout), else the User guide's paper section (the frozen app ships
    # docs/ only -- see the report: plaque_stats/README.md is not in the build's datas)
    _STATS_GUIDE = (("plaque_stats/README.md", "4-the-statistics-and-why-platelevel"),
                    ("USER_GUIDE.md", "11-using-it-in-a-paper"))

    def _open_stats_guide(self):
        """CT-R2 F18: open the guide to the Analyze statistics, scrolled to its section."""
        from app.ui import DocViewer, _DOC_VIEWERS, _resolve_doc
        name, frag = self._STATS_GUIDE[-1]
        for n, f in self._STATS_GUIDE:
            if _resolve_doc(n)[0]:
                name, frag = n, f
                break
        v = DocViewer(_resolve_doc(name)[0] or name, self.window())
        _DOC_VIEWERS.append(v)
        v.finished.connect(lambda _=0, vv=v: (vv in _DOC_VIEWERS) and _DOC_VIEWERS.remove(vv))
        v.show(); v.raise_()
        v.scroll_to(frag)
        self._guide_viewer = v
        return v

    def _open_doc(self, name):
        try:
            from app.ui import _open_doc
            _open_doc(name, self)
        except Exception:
            pass
