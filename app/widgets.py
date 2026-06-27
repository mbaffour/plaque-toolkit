"""Small shared Qt widgets."""
import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QSortFilterProxyModel, Qt


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
        if role == Qt.TextAlignmentRole:
            try:
                float(val)
                return int(Qt.AlignRight | Qt.AlignVCenter)
            except (TypeError, ValueError):
                return int(Qt.AlignLeft | Qt.AlignVCenter)
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return str(self._df.columns[section])
        return str(section + 1)


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
