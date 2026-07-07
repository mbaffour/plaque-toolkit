"""Small shared Qt widgets."""
import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QTableView, QMenu, QApplication

# Hover help for the per-plaque result columns (shown on the table headers).
COLUMN_TOOLTIPS = {
    "INDEX": "Plaque number — 1 is the topmost plaque in the image, counting downward.",
    "AREA_PXL": "Plaque area in pixels (convex hull, halo-inclusive).",
    "DIAMETER_PXL": "Area-equivalent diameter in pixels: d = 2·√(area/π).",
    "AREA_MM2": "Plaque area in mm² (requires calibration).",
    "DIAMETER_MM": "Area-equivalent diameter in mm — halo-inclusive (requires calibration).",
    "MEAN_GRAY": "Mean brightness inside the plaque (0–255). Lower = clearer / darker.",
    "TURBIDITY_REL": "Relative turbidity: plaque brightness ÷ surrounding lawn. "
                     "~1 = as opaque as the lawn (turbid); lower = clearer.",
    "CIRCULARITY": "Shape roundness 4·π·area / perimeter² (0–1). 1 = perfect circle; "
                   "lower = irregular / comet / elongated. Circles you draw score 1.",
    "OVERLAP": "yes = this plaque touches/overlaps another, so its size is unreliable. "
               "Tick 'Exclude overlapping plaques' to drop these from the stats.",
    "SOURCE": "How the plaque was found: auto (detector), manual (you added it), "
              "freehand (you drew the outline), or watershed (split from a touching pair).",
}


class PandasTableModel(QAbstractTableModel):
    """Read-only Qt table model backed by a pandas DataFrame.

    Numbers are right-aligned and a Qt.UserRole exposes the raw (typed) value so a
    proxy can sort numerically rather than lexically."""

    def __init__(self, df=None):
        super().__init__()
        self._df = df if df is not None else pd.DataFrame()

    def set_dataframe(self, df):
        self.beginResetModel()
        self._df = df.reset_index(drop=True) if df is not None else pd.DataFrame()
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
        if role == Qt.DisplayRole:
            return "" if val is None else str(val)
        if role == Qt.UserRole:
            # raw value for numeric-aware sorting
            return val
        if role == Qt.ToolTipRole:
            # hovering any cell explains its column (a11y: values gain context, not just headers)
            try:
                return COLUMN_TOOLTIPS.get(str(self._df.columns[index.column()]))
            except (IndexError, TypeError):
                return None
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
