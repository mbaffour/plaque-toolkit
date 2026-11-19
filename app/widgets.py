"""Small shared Qt widgets."""
import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QKeySequence, QBrush, QColor
from PySide6.QtWidgets import QTableView, QMenu, QApplication

# Hover help for the per-plaque result columns (shown on the table headers).
COLUMN_TOOLTIPS = {
    "INDEX": "Plaque number — 1 is the topmost plaque in the image, counting downward.",
    "AREA_PXL": "Plaque area in pixels (convex hull, halo-inclusive).",
    "DIAMETER_PXL": "Area-equivalent diameter in pixels: d = 2·√(area/π).",
    "AREA_MM2": "Plaque area in mm² (requires calibration).",
    "DIAMETER_MM": "Area-equivalent diameter in mm — halo-inclusive (requires calibration).",
    "MEAN_GRAY": "Mean brightness inside the plaque (0–255). Lower = clearer / darker.",
    # CT-R1 F16: the tooltip gave a formula (plaque ÷ lawn) the engine does not use
    "TURBIDITY_REL": "Relative turbidity within THIS plate: 1 − |plaque − lawn| ÷ the largest "
                     "such difference on the plate (mean gray values). 0 = the clearest plaque "
                     "on this plate, 1 = the same as the lawn. Not comparable between plates.",
    "CIRCULARITY": "Shape roundness 4·π·area / perimeter² (0–1). 1 = perfect circle; "
                   "lower = irregular / comet / elongated. Circles you draw score 1.",
    "OVERLAP": "yes = this plaque touches/overlaps another, so its size is unreliable. "
               "Tick 'Exclude overlapping plaques' to drop these from the stats.",
    "SOURCE": "How the plaque was found: auto (detector), small (detector, found only at the small "
              "scale of the Auto plaque size), manual (you added it), "
              "freehand (you drew the outline), region (the Detect-area tool), or watershed "
              "(split from a touching pair).",
    # CT-R1 F24: the one column with no explanation
    "QC_FLAG": "Rows that deserve a second look (OK = none). Several can apply, joined with |.\n"
               "EDGE — touches the image border or the dish rim, so part of it may be cut off.\n"
               "LARGE? — area more than 2.5× the plate's median, with a normal round shape.\n"
               "MERGED? — far from round (circularity below 0.6): likely two plaques counted as one.\n"
               "TINY — at or below the standard size gate; found only by the small / sensitive gates.\n"
               "OVERLAP — its disk overlaps another plaque's, so both sizes are unreliable.\n"
               "LOW_CONF — the Precise classifier scored it below 0.6.\n"
               "Hover a flagged cell for the reason. A flag never changes a measurement.",
}
# what an uncalibrated mm value is shown as (the number itself stays in the data)
NO_VALUE = "—"
# translucent amber: a row whose QC_FLAG is not OK. Translucent so it reads on the light AND
# the dark theme (an opaque pale fill under the dark theme's light text was unreadable).
_FLAG_TINT = QColor(255, 176, 32, 70)


class PandasTableModel(QAbstractTableModel):
    """Read-only Qt table model backed by a pandas DataFrame.

    Numbers are right-aligned and a Qt.UserRole exposes the raw (typed) value so a
    proxy can sort numerically rather than lexically."""

    def __init__(self, df=None):
        super().__init__()
        self._df = df if df is not None else pd.DataFrame()
        self._dash_cols = frozenset()
        self._cell_tips = {}
        self._flag_col = None

    def set_dataframe(self, df, dash_columns=(), cell_tooltips=None, flag_column=None):
        """Show `df`. Display-only extras (the DataFrame itself is never altered, so
        dataframe(), sorting and every consumer keep the real values):

        dash_columns   columns whose cells are SHOWN as "—" (mm values with no mm scale;
                       CT-R1 F14 -- they used to read 0.0, like real zeros)
        cell_tooltips  {column: [tooltip per row]} overriding the column's tooltip where set
        flag_column    a column whose non-empty, non-"OK" value tints the whole row (F24)
        """
        self.beginResetModel()
        self._df = df.reset_index(drop=True) if df is not None else pd.DataFrame()
        self._dash_cols = frozenset(dash_columns or ())
        self._cell_tips = dict(cell_tooltips or {})
        self._flag_col = flag_column if (flag_column in self._df.columns) else None
        self.endResetModel()

    def dataframe(self):
        """The backing DataFrame (row i corresponds to the i-th plaque / INDEX i+1)."""
        return self._df

    def rowCount(self, parent=None):
        return len(self._df)

    def columnCount(self, parent=None):
        return len(self._df.columns)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        val = self._df.iloc[index.row(), index.column()]
        col = str(self._df.columns[index.column()])
        if role == Qt.DisplayRole:
            if col in self._dash_cols:
                return NO_VALUE
            return "" if val is None else str(val)
        if role == Qt.UserRole:
            # raw value for numeric-aware sorting
            return val
        if role == Qt.ToolTipRole:
            # hovering any cell explains its column (a11y: values gain context, not just headers)
            try:
                tips = self._cell_tips.get(col)
                if tips is not None and tips[index.row()]:
                    return str(tips[index.row()])
                return COLUMN_TOOLTIPS.get(col)
            except (IndexError, TypeError):
                return None
        if role == Qt.BackgroundRole and self._flag_col is not None:
            flag = str(self._df.iloc[index.row()][self._flag_col])
            return None if flag in ("", "OK", "nan", "None") else QBrush(_FLAG_TINT)
        if role == Qt.TextAlignmentRole:
            try:
                float(val)
                return int(Qt.AlignRight | Qt.AlignVCenter)
            except (TypeError, ValueError):
                return int(Qt.AlignLeft | Qt.AlignVCenter)
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal:
            if section >= len(self._df.columns):
                return None
            col = str(self._df.columns[section])
            if role == Qt.DisplayRole:
                return col
            if role == Qt.ToolTipRole:
                return COLUMN_TOOLTIPS.get(col)
            return None
        if role == Qt.DisplayRole:
            return str(section + 1)
        return None


class NumericSortProxy(QSortFilterProxyModel):
    """Sort proxy that orders numeric columns by value, not string order."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSortRole(Qt.UserRole)

    def lessThan(self, left, right):
        lv = self.sourceModel().data(left, Qt.UserRole)
        rv = self.sourceModel().data(right, Qt.UserRole)
        try:
            return float(lv) < float(rv)
        except (TypeError, ValueError):
            return str(lv) < str(rv)


class CopyableTableView(QTableView):
    """QTableView with Excel-friendly clipboard support.

    • Ctrl+C copies the selected rows as TSV (tab-separated, with a header row) so it
      pastes straight into Excel/Sheets with columns split. If nothing is selected it
      copies the whole table.
    • Right-click offers Copy selected / Copy whole table / Select all.
    Rows are emitted in the currently-visible (sorted) order, using the same rounded
    display strings shown on screen and in the CSV export."""

    copied = Signal(int)   # number of data rows placed on the clipboard

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)

    # -- build the clipboard payload ---------------------------------------- #
    def _selected_rows(self):
        sm = self.selectionModel()
        if sm is None:
            return []
        return sorted({ix.row() for ix in sm.selectedIndexes()})

    def selection_tsv(self, all_rows=False, headers=True):
        """Return the selected rows (or all rows) as an Excel-ready TSV string plus the
        data-row count: (text, n_rows). Rows follow the current visible/sorted order."""
        model = self.model()
        if model is None:
            return "", 0
        ncols = model.columnCount()
        rows = list(range(model.rowCount())) if all_rows else self._selected_rows()
        if not rows:                                   # nothing highlighted → copy everything
            rows = list(range(model.rowCount()))
        lines = []
        if headers:
            lines.append("\t".join(
                str(model.headerData(c, Qt.Horizontal, Qt.DisplayRole) or "")
                for c in range(ncols)))
        for r in rows:
            lines.append("\t".join(
                str(model.data(model.index(r, c), Qt.DisplayRole) or "")
                for c in range(ncols)))
        return "\r\n".join(lines), len(rows)

    def copy_selection(self, all_rows=False, headers=True):
        text, n = self.selection_tsv(all_rows=all_rows, headers=headers)
        QApplication.clipboard().setText(text)
        self.copied.emit(n)
        return n

    # -- interaction -------------------------------------------------------- #
    def keyPressEvent(self, e):
        if e.matches(QKeySequence.Copy):
            self.copy_selection(all_rows=False, headers=True)
            e.accept(); return
        super().keyPressEvent(e)

    def _context_menu(self, pos):
        model = self.model()
        if model is None:
            return
        m = QMenu(self)
        n_sel = len(self._selected_rows())
        a_sel = m.addAction(f"Copy {n_sel or 'selected'} row(s) with headers"
                            if n_sel else "Copy selected rows")
        a_sel.setEnabled(n_sel > 0)
        a_sel.triggered.connect(lambda: self.copy_selection(all_rows=False, headers=True))
        a_all = m.addAction("Copy whole table (for Excel)")
        a_all.triggered.connect(lambda: self.copy_selection(all_rows=True, headers=True))
        m.addSeparator()
        a_pick = m.addAction("Select all")
        a_pick.triggered.connect(self.selectAll)
        m.exec(self.viewport().mapToGlobal(pos))
