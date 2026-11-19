"""Unified Plaque Toolkit desktop app (PySide6). Two workflows in one window:
   • Measure — open an image, auto-detect, edit by hand, save size + turbidity.
   • Compare — batch a folder of phages, get optical-density turbidity + titer + figures.
The validated engine is reached only through app.engine_api."""
import os
import sys
import tempfile

import matplotlib
matplotlib.use("QtAgg")   # set before any pyplot/canvas use (frozen-app safe)

import pandas as pd
from PySide6.QtCore import Qt, QThreadPool, QTimer, QItemSelectionModel, QRect, QPoint, QSize
from PySide6.QtGui import (QPixmap, QIcon, QKeySequence, QShortcut, QAction, QDesktopServices,
                           QFont, QActionGroup)
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QFileDialog, QDoubleSpinBox, QCheckBox, QTableView, QSplitter,
    QLineEdit, QGroupBox, QScrollArea, QMessageBox, QSplashScreen, QComboBox,
    QFrame, QProgressBar, QStyle, QMenu, QAbstractItemView, QPlainTextEdit,
    QDialog, QTextBrowser, QLayout, QSizePolicy)

from app import __version__, engine_api, style, batch_measure, validate
from app.study_tab import StudyTab
from app.workers import Worker
from app.widgets import PandasTableModel, NumericSortProxy, CopyableTableView
from app.plaque_canvas import PlaqueCanvas

IMG_FILTER = "Images (*.tif *.tiff *.jpg *.jpeg *.png *.heic *.heif)"
IMG_EXTS = (".tif", ".tiff", ".jpg", ".jpeg", ".png", ".heic", ".heif")


class FlowLayout(QLayout):
    """Lays widgets left-to-right and wraps to the next line when it runs out of width — so a
    wide toolbar reflows to fit narrow windows instead of overflowing / needing a scrollbar."""

    def __init__(self, parent=None, margin=0, hspacing=8, vspacing=6):
        super().__init__(parent)
        self._items = []
        self._hspace = hspacing
        self._vspace = vspacing
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._layout(rect, test_only=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for it in self._items:
            s = s.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return s + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _layout(self, rect, test_only):
        m = self.contentsMargins()
        x = rect.x() + m.left()
        y = rect.y() + m.top()
        line_h = 0
        right = rect.right() - m.right()
        for it in self._items:
            sz = it.sizeHint()
            nx = x + sz.width()
            if nx - 1 > right and line_h > 0:          # wrap to next line
                x = rect.x() + m.left()
                y = y + line_h + self._vspace
                nx = x + sz.width()
                line_h = 0
            if not test_only:
                it.setGeometry(QRect(QPoint(x, y), sz))
            x = nx + self._hspace
            line_h = max(line_h, sz.height())
        return y + line_h - rect.y() + m.bottom()

class _FitVBox(QVBoxLayout):
    """A QVBoxLayout that does not ADVERTISE height-for-width to its parent scroll area.

    The Measure tab contains wrapping toolbars (FlowLayout), which makes an ordinary box
    layout report hasHeightForWidth(). A QScrollArea with widgetResizable then sizes the tab
    to heightForWidth(width) -- its PREFERRED height (971 px here) -- in every window, so the
    canvas and the feedback line ended up below the fold (CT-R1 F11). Internally the box still
    gives each wrapping toolbar the height it needs for the current width; only the report to
    the scroll area changes, so the tab is fitted to the viewport and the canvas takes the
    height that is left. MeasureTab.resizeEvent publishes the true minimum height."""

    def hasHeightForWidth(self):
        return False

    def heightForWidth(self, w):
        return -1


# Engine/mode catalogue: label -> (kwargs/flag, helper text).
MODES = [
    ("Published (validated)", "published",
     "The peer-reviewed Trofimova & Jaschke (2021) algorithm, unchanged. "
     "Cite this mode for published results.  (~a few seconds)"),
    ("Current (corrected)", "current",
     "The maintained engine with bug-fixes and improved dish/calibration handling. "
     "Recommended default for routine measuring.  (~a few seconds)"),
    ("Sensitive (tiny plaques)", "sensitive",
     "Lowers the size gates to catch sub-0.4 mm plaques. Detects many more, but adds "
     "false positives — verify by eye. In-house, not independently validated.  (~a few seconds)"),
    ("Precise (PST + PlaqSeg)", "precise",
     "Best accuracy: fuses the classic detector with a PlaqSeg deep-learning model. In-house "
     "(not independently/peer-reviewed); locally validated (~0.95 precision on our test plates) — "
     "validate on yours before publishing.  (~1 min on first run, then faster)"),
]

# Playful, on-brand progress messages ("Frankenstein's Plaque Lab") cycled while detecting.
_BUSY_PRECISE = [
    "⚡ Waking the monster… (first run ~1 min)",
    "🧵 Stitching PST + PlaqSeg together…",
    "🔬 Hunting every clearing…",
    "📏 Measuring the plaques…",
    "🧟 Almost alive…",
]
_BUSY_STD = [
    "🔬 Scanning the plate…",
    "🕳️ Finding clearings…",
    "📏 Measuring the plaques…",
]


def _shadow(widget, blur=18, dy=2, alpha=40):
    """Soft drop shadow for cards (purely cosmetic)."""
    try:
        from PySide6.QtWidgets import QGraphicsDropShadowEffect
        from PySide6.QtGui import QColor
        eff = QGraphicsDropShadowEffect(widget)
        eff.setBlurRadius(blur)
        eff.setXOffset(0)
        eff.setYOffset(dy)
        eff.setColor(QColor(0, 0, 0, alpha))
        widget.setGraphicsEffect(eff)
    except Exception:
        pass


def _icon(sp):
    """Standard Qt pixmap icon by enum (keeps us dependency-free for glyphs)."""
    app = QApplication.instance()
    if app is None:
        return QIcon()
    return app.style().standardIcon(sp)


# --------------------------------------------------------------------------- #
class MeasureTab(QWidget):
    _SEL_HINT = ("Tip: click a plaque on the image to highlight its row here (and vice-versa). "
                 "Select rows and press Ctrl+C to copy them for Excel.")

    def __init__(self, pool):
        super().__init__()
        self.pool = pool
        self.det = None
        self.image_path = None
        self.editor = None
        self.busy = False
        self._syncing = False          # guards the two-way canvas<->table selection link
        self.setAcceptDrops(True)
        # rotating, on-brand progress messages while a detection runs
        self._busy_timer = QTimer(self); self._busy_timer.setInterval(2200)
        self._busy_timer.timeout.connect(self._tick_busy)
        self._busy_msgs = []; self._busy_i = 0

        # ---- parameters row ------------------------------------------------ #
        self.plate = QDoubleSpinBox(); self.plate.setRange(0, 500); self.plate.setValue(100)
        self.plate.setSuffix(" mm"); self.plate.setDecimals(1)
        self.plate.setToolTip("Diameter of the Petri dish, in millimetres. Used to convert "
                              "pixels to mm via the detected dish. Set to 0 to report pixels only.\n"
                              "Tip: measure the AGAR base (often ~85 mm), not the printed lid size.")
        self.plate_85 = QPushButton("85 mm")
        self.plate_85.setToolTip("Quick-set 85 mm — a common agar-base diameter.")
        self.plate_85.clicked.connect(lambda: self._quick_dish(85))
        self.plate_100 = QPushButton("100 mm")
        self.plate_100.setToolTip("Quick-set 100 mm — the nominal lid diameter.")
        self.plate_100.clicked.connect(lambda: self._quick_dish(100))
        # changing the dish size (typing OR the 85/100 buttons) live-re-scales the current image
        self.plate.valueChanged.connect(self._on_dish_value_changed)

        # image orientation — rotate / flip the plate (e.g. to match your Fiji hand-labelling)
        self._cur_img = None       # current (oriented) BGR array
        self._detect_src = None    # path detection runs on (an oriented temp; None => image_path)
        self._orient_ops = []      # rotate/flip steps applied to the image on screen (metadata)
        # CT-R1 F15: what a running detection was asked to open. image_path / _detect_src /
        # _cur_img / _orient_ops only change when that detection SUCCEEDS (on_detected), so a
        # failed open leaves the tab pointing at the image that is still on screen.
        self._pending = None
        self._det_settings = None  # (engine key, watershed) the result on screen was made with
        self._dish_msg = None      # why a Dish action could not rescale (shown under the card)
        self.orient_btn = QPushButton("Orient ▾")
        self.orient_btn.setToolTip("Rotate or flip the plate to match your reference orientation "
                                   "(e.g. your Fiji hand-labelling). Re-runs detection on the new view.")
        _om = QMenu(self.orient_btn)
        _om.addAction("Rotate 90° left", lambda: self._orient("ccw"))
        _om.addAction("Rotate 90° right", lambda: self._orient("cw"))
        _om.addSeparator()
        _om.addAction("Flip left–right", lambda: self._orient("fliph"))
        _om.addAction("Flip top–bottom", lambda: self._orient("flipv"))
        self.orient_btn.setMenu(_om)
        self.orient_btn.setEnabled(False)
        self._orient_btns = (self.orient_btn,)

        self.mode = QComboBox()
        for label, _key, _help in MODES:
            self.mode.addItem(label)
        try:
            _precise_ok = engine_api.precise_available()[0]
        except Exception:
            _precise_ok = False
        # default to the most precise engine when it's available, else Current (corrected)
        self._def_mode = 3 if _precise_ok else 1
        self.mode.setCurrentIndex(self._def_mode)
        # flag the recommended engine right in the dropdown (label stays clean for status text)
        self.mode.setItemText(self._def_mode, MODES[self._def_mode][0] + "   ★ recommended")
        if not _precise_ok:
            # CT-R1 F15: say so in the list, instead of only after the user has picked it
            self.mode.setItemText(3, MODES[3][0] + "   (not installed)")
            self.mode.setItemData(3, "The Precise engine needs PyTorch + the PlaqSeg model, which "
                                     "are not installed on this computer.", Qt.ToolTipRole)
        self.mode.setToolTip("Detection engine / mode. Hover an option or read the line below.")
        self.mode.currentIndexChanged.connect(self._mode_changed)

        self.watershed = QCheckBox("Split touching plaques")
        self.watershed.setToolTip("Watershed segmentation to separate plaques whose edges touch. "
                                  "Helpful on crowded plates; ignored under Published mode.")
        self.watershed.stateChanged.connect(lambda _=0: self._update_stale())

        self.exclude_overlaps = QCheckBox("Exclude overlaps from stats")
        self.exclude_overlaps.setToolTip("Leave overlapping/touching plaques (OVERLAP=yes, shown "
                                         "dashed-pink) OUT of the median/mean diameter — their size "
                                         "is unreliable. They stay visible and in the CSV, just not "
                                         "in the summary numbers.")
        self.exclude_overlaps.stateChanged.connect(lambda _=0: self.refresh_table())

        self.open_btn = QPushButton(" Open image…"); self.open_btn.setObjectName("Primary")
        self.open_btn.setIcon(_icon(QStyle.SP_DirOpenIcon))
        self.open_btn.clicked.connect(self.open_image)
        self.open_btn.setToolTip("Open a plaque image (Ctrl+O). TIFF, JPEG, PNG and iPhone HEIC "
                                 "are supported. You can also drag-and-drop an image here.")

        self.redetect_btn = QPushButton(" Re-detect")
        self.redetect_btn.setIcon(_icon(QStyle.SP_BrowserReload))
        self.redetect_btn.clicked.connect(self.redetect)
        self.redetect_btn.setEnabled(False)
        self.redetect_btn.setToolTip("Re-run detection on the current image with the options above "
                                     "(replaces the current detections).")

        self.save_btn = QPushButton(" Save results")
        self.save_btn.setIcon(_icon(QStyle.SP_DialogSaveButton))
        self.save_btn.clicked.connect(self.save)
        self.save_btn.setEnabled(False)
        self.save_btn.setToolTip("Write the measurement table, overlay and turbidity to an 'out' "
                                 "folder next to the image (Ctrl+S).")

        params_box = QGroupBox("Parameters")
        # FlowLayout so the toolbar WRAPS onto more rows on narrow windows instead of overflowing
        pl = FlowLayout(params_box, margin=4, hspacing=10, vspacing=6)
        pl.addWidget(QLabel("Dish")); pl.addWidget(self.plate)
        pl.addWidget(self.plate_85); pl.addWidget(self.plate_100)
        pl.addWidget(QLabel("Engine")); pl.addWidget(self.mode)
        pl.addWidget(self.watershed); pl.addWidget(self.exclude_overlaps)
        pl.addWidget(self.orient_btn)
        pl.addWidget(self.open_btn); pl.addWidget(self.redetect_btn); pl.addWidget(self.save_btn)

        # mode helper + progress strip
        self.mode_help = QLabel(MODES[self._def_mode][2]); self.mode_help.setObjectName("ModeHelp")
        self.mode_help.setWordWrap(True)
        self.progress = QProgressBar(); self.progress.setRange(0, 0)   # indeterminate
        self.progress.setVisible(False); self.progress.setMaximumWidth(220)
        self.busy_label = QLabel(""); self.busy_label.setObjectName("ModeHelp")
        # CT-R1 F25: Engine / Split-touching changed but the result on screen is the old one
        self.stale_label = QLabel(""); self.stale_label.setVisible(False)
        self.stale_label.setStyleSheet(f"font-weight:700; color:{style.LIGHT['warn']};")
        strip = QHBoxLayout(); strip.setContentsMargins(2, 0, 2, 0)
        strip.addWidget(self.mode_help, 1)
        strip.addWidget(self.stale_label)
        strip.addWidget(self.busy_label); strip.addWidget(self.progress)

        # ---- canvas (left) ------------------------------------------------- #
        self.canvas_holder = QFrame(); self.canvas_holder.setObjectName("Card")
        self.canvas_layout = QVBoxLayout(self.canvas_holder)
        self.canvas_layout.setContentsMargins(6, 6, 6, 6)
        # loaded-photo info strip (name · dimensions · camera · date · size) — filled on load
        self.img_info = QLabel(""); self.img_info.setVisible(False)
        self.img_info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.img_info.setStyleSheet("font-family:Consolas,monospace;font-size:12px;color:#33413c;"
                                    "background:#eef4f1;border:1px solid #d7e2dc;border-radius:7px;padding:4px 9px;")
        self.canvas_layout.addWidget(self.img_info)
        self.placeholder = QLabel(
            "🧫\n\n"
            "Drag a plaque photo here\n"
            "— or click  “Open image…”  above —\n\n"
            "TIFF · JPEG · PNG · iPhone HEIC\n\n"
            "Then set your dish size and pick an engine. Numbering runs 1→N from the top.")
        self.placeholder.setObjectName("Placeholder")
        self.placeholder.setAlignment(Qt.AlignCenter)
        self.placeholder.setWordWrap(True)   # don't force the canvas panel wide on a small screen
        self.placeholder.setMinimumHeight(360)
        self.placeholder.setStyleSheet(
            "border:2px dashed #c2c9d6; border-radius:14px; color:#6b7484; "
            "font-size:15px; background:#fbfcfe;")
        self.canvas_layout.addWidget(self.placeholder)

        # ---- right panel: summary card + table ----------------------------- #
        self.summary_card = self._build_summary_card()

        self.table = CopyableTableView()
        self.table.setMinimumWidth(150)   # let the right panel shrink; the table scrolls its columns
        self.model = PandasTableModel()
        self.proxy = NumericSortProxy(); self.proxy.setSourceModel(self.model)
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(0, Qt.AscendingOrder)   # INDEX ascending -> #1 (topmost) at the top
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setHighlightSections(False)
        self.table.setAccessibleName("Per-plaque measurements table")
        self.table.setAccessibleDescription(
            "One row per plaque: number, diameter, area, mean gray and turbidity. "
            "Click a row to highlight that plaque on the image. Press Ctrl+C to copy "
            "selected rows for Excel.")
        # keep the image and the table linked both ways
        self.table.selectionModel().selectionChanged.connect(self._on_table_selection)
        self.table.copied.connect(
            lambda n: self.window().statusBar().showMessage(
                f"Copied {n} row(s) to the clipboard — paste into Excel (Ctrl+V).", 4000))

        table_card = QFrame(); table_card.setObjectName("Card")
        tcl = QVBoxLayout(table_card); tcl.setContentsMargins(12, 10, 12, 12)
        caprow = QHBoxLayout(); caprow.setContentsMargins(0, 0, 0, 0)
        cap = QLabel("Per-plaque measurements"); cap.setObjectName("SummaryHeading")
        self.copy_btn = QPushButton("Copy")
        self.copy_btn.setToolTip("Copy the selected rows (or the whole table if none are "
                                 "selected) as tab-separated text — paste straight into Excel. "
                                 "Shortcut: Ctrl+C while the table is focused.")
        self.copy_btn.setAccessibleName("Copy measurements to clipboard")
        self.copy_btn.clicked.connect(lambda: self.table.copy_selection(all_rows=False, headers=True))
        self.fiji_btn = QPushButton("Compare vs Fiji…")
        self.fiji_btn.setToolTip("Pair your Fiji measurements to these plaques by location and "
                                 "show the per-plaque differences — the same plaque in both tools, "
                                 "regardless of numbering. (Export the Fiji bundle first if you "
                                 "haven't: Export ▾ → Fiji registration bundle.)")
        self.fiji_btn.setAccessibleName("Compare against Fiji results")
        self.fiji_btn.clicked.connect(self._open_fiji_compare)
        caprow.addWidget(cap); caprow.addStretch()
        caprow.addWidget(self.fiji_btn); caprow.addWidget(self.copy_btn)
        self.sel_readout = QLabel(self._SEL_HINT); self.sel_readout.setObjectName("ModeHelp")
        self.sel_readout.setWordWrap(True)
        tcl.addLayout(caprow); tcl.addWidget(self.table); tcl.addWidget(self.sel_readout)

        right = QWidget(); rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0); rl.setSpacing(12)
        rl.addWidget(self.summary_card)
        rl.addWidget(table_card, 1)

        split = QSplitter()
        split.addWidget(self.canvas_holder); split.addWidget(right)
        split.setSizes([720, 470]); split.setChildrenCollapsible(False)

        # CT-R1 F11: _FitVBox, not QVBoxLayout -- see its docstring (the tab was laid out
        # 971 px tall in every window, with the canvas and its feedback line below the fold).
        lay = _FitVBox(self); lay.setContentsMargins(14, 12, 14, 12); lay.setSpacing(10)
        lay.addWidget(params_box)
        lay.addLayout(strip)
        self._params_box, self._right, self._strip = params_box, right, strip
        lay.addWidget(split, 1)
        self._split = split
        split.splitterMoved.connect(lambda *_a: self._sync_min_height())

        self._apply_a11y()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # The tab's real minimum height depends on its width (the toolbars wrap). Publish it,
        # so the outer scroll area scrolls only when the window is too small for that minimum
        # and otherwise hands the canvas all the height that is left (CT-R1 F11).
        self._sync_min_height()

    def _sync_min_height(self):
        """Publish the tab's real minimum height for its CURRENT width: the wrapped parameter
        row + the help strip + the taller of the canvas card (editor toolbar rows, feedback
        line, a usable image, legend row) and the right panel. Summed by hand: _FitVBox hides
        height-for-width from the scroll area on purpose, so the layout cannot be asked."""
        lay = self.layout()
        if lay is None or self.width() <= 0:
            return

        def h4w(widget_or_layout, w):
            if widget_or_layout.hasHeightForWidth() and w > 0:
                return max(widget_or_layout.heightForWidth(w), 0)
            ms = widget_or_layout.minimumSizeHint() if hasattr(widget_or_layout, "minimumSizeHint") \
                else widget_or_layout.minimumSize()
            return max(ms.height(), 0)

        m = lay.contentsMargins()
        inner = self.width() - m.left() - m.right()
        ch = self.canvas_holder
        cl = ch.layout()
        cw = ch.width() if ch.width() > 0 else int(inner * 0.6)
        canvas_need = (cl.minimumHeightForWidth(cw) if cl.hasHeightForWidth()
                       else cl.minimumSize().height())
        need = (m.top() + m.bottom() + 2 * lay.spacing()
                + h4w(self._params_box, inner) + h4w(self._strip, inner)
                + max(canvas_need, self._right.minimumSizeHint().height()))
        if need > 0 and need != self.minimumHeight():
            self.setMinimumHeight(need)

    # -- accessibility ------------------------------------------------------ #
    def _apply_a11y(self):
        """Screen-reader names/descriptions on the main controls and an explicit tab order
        so the tab stops flow left-to-right through the parameters, then into the table."""
        named = [
            (self.plate, "Dish diameter", "Petri-dish diameter in millimetres, used to convert pixels to mm."),
            (self.plate_85, "Set dish to 85 mm", "Quick-set the agar-base diameter to 85 mm."),
            (self.plate_100, "Set dish to 100 mm", "Quick-set the lid diameter to 100 mm."),
            (self.mode, "Detection engine", "Choose the plaque-detection engine."),
            (self.watershed, "Split touching plaques", "Separate plaques whose edges touch."),
            (self.exclude_overlaps, "Exclude overlapping plaques from statistics",
             "Leave overlapping plaques out of the median and mean diameter."),
            (self.orient_btn, "Orient image", "Rotate or flip the plate to match a reference orientation."),
            (self.open_btn, "Open image", "Open a plaque photo (Ctrl+O)."),
            (self.redetect_btn, "Re-detect", "Re-run detection with the current options."),
            (self.save_btn, "Save results", "Write the measurement table, overlay and turbidity (Ctrl+S)."),
        ]
        for w, name, desc in named:
            w.setAccessibleName(name)
            w.setAccessibleDescription(desc)
        order = [self.plate, self.plate_85, self.plate_100, self.mode, self.watershed,
                 self.orient_btn, self.open_btn, self.redetect_btn, self.save_btn,
                 self.table, self.fiji_btn, self.copy_btn]
        for a, b in zip(order, order[1:]):
            self.setTabOrder(a, b)

    # -- summary card ------------------------------------------------------- #
    def _build_summary_card(self):
        card = QFrame(); card.setObjectName("SummaryCard")
        _shadow(card)
        grid = QGridLayout(card); grid.setContentsMargins(16, 12, 16, 12)
        grid.setHorizontalSpacing(26); grid.setVerticalSpacing(2)

        def metric(col, key, label):
            cap = QLabel(label); cap.setObjectName("SummaryHeading")
            val = QLabel("—")
            val.setStyleSheet("font-size:20px; font-weight:700;")
            grid.addWidget(cap, 0, col)
            grid.addWidget(val, 1, col)
            self._metrics[key] = val
            self._metric_caps[key] = cap

        self._metrics = {}
        self._metric_caps = {}
        metric(0, "count", "PLAQUES")
        metric(1, "median", "MEDIAN Ø (mm)")
        metric(2, "mean", "MEAN Ø (mm)")
        metric(3, "cal", "CALIBRATION")
        self.flag_label = QLabel("")
        self.flag_label.setWordWrap(True)
        self.flag_label.setStyleSheet("font-size:12px; font-weight:600;")
        grid.addWidget(self.flag_label, 2, 0, 1, 4)
        return card

    def _set_summary(self, n=None, median=None, mean=None, cal=None, flag=None, mode=None, unit="mm"):
        """`unit` = "mm", or "px" when there is no mm scale: the card then shows PIXEL
        diameters under headings that say so, instead of 0.00 "mm" (CT-R1 F14)."""
        self._metrics["count"].setText("—" if n is None else str(n))
        self._metric_caps["median"].setText("MEDIAN Ø (%s)" % unit)
        self._metric_caps["mean"].setText("MEAN Ø (%s)" % unit)
        fmt = "%.2f" if unit == "mm" else "%.1f"
        self._metrics["median"].setText("—" if median is None else fmt % median)
        self._metrics["mean"].setText("—" if mean is None else fmt % mean)
        cal_lbl = self._metrics["cal"]
        if cal:
            cal_lbl.setText(f"{cal:.4f} mm/px  ✓")
            cal_lbl.setStyleSheet(f"font-size:17px; font-weight:700; color:{style.LIGHT['ok']};")
            cal_lbl.setToolTip("Scale is set — sizes below are in millimetres.")
        else:
            cal_lbl.setText("Not set")
            cal_lbl.setStyleSheet(f"font-size:17px; font-weight:700; color:{style.LIGHT['warn']};")
            cal_lbl.setToolTip("No mm scale yet — sizes are in pixels only. In the editor use "
                               "“Set plate” (click 3 points on the agar rim, then type its diameter), "
                               "or set the Dish size before detecting.")
        if flag:
            self.flag_label.setText(flag)
            self.flag_label.setStyleSheet(
                f"font-size:12px; font-weight:600; color:{style.LIGHT['warn']};")
            self.flag_label.setVisible(True)
        else:
            self.flag_label.setVisible(False)

    # -- mode handling ------------------------------------------------------ #
    def _mode_key(self):
        return MODES[self.mode.currentIndex()][1]

    def _mode_changed(self, idx):
        self.mode_help.setText(MODES[idx][2])
        key = MODES[idx][1]
        if key == "published" and self.watershed.isChecked():
            # CT-R1 F25: the box was greyed out but stayed ticked, as if it still applied
            self.watershed.setChecked(False)
        self.watershed.setEnabled(key not in ("published",))
        self._update_stale()

    def _engine_key_of(self, det):
        """The engine that PRODUCED a result, from its own flags (not the dropdown, which the
        user may have changed since)."""
        if det.get("precise"):
            return "precise"
        if det.get("published"):
            return "published"
        return "sensitive" if det.get("sensitive") else "current"

    def _engine_label_of(self, det):
        key = self._engine_key_of(det)
        return next(label for label, k, _h in MODES if k == key)

    def _update_stale(self):
        """Show 'settings changed: press Re-detect' while the Engine / Split-touching controls
        no longer describe the result on screen (CT-R1 F25: nothing marked it as stale)."""
        stale = False
        if self.det is not None and self.editor is not None and self._det_settings is not None:
            key, ws = self._det_settings
            now_key = self._mode_key()
            now_ws = self.watershed.isChecked() and now_key not in ("published", "precise")
            stale = (now_key != key) or (bool(now_ws) != bool(ws))
        if stale:
            self.stale_label.setText("⚠ settings changed: press Re-detect  (on screen: %s)"
                                     % self._engine_label_of(self.det))
        self.stale_label.setVisible(stale)

    def _dish_note(self, text=None):
        """A one-line explanation under the summary numbers for a Dish action that could not
        do anything (CT-R1 F14: the 85 / 100 buttons did nothing, silently)."""
        self._dish_msg = text
        self.refresh_table()            # (this resets the status bar, so the note goes after it)
        if text:
            self.window().statusBar().showMessage(text, 8000)

    def _quick_dish(self, mm):
        """The 85 / 100 buttons: set the Dish box and, if that cannot rescale the plate on
        screen, say why."""
        same = abs(self.plate.value() - mm) < 1e-9
        self.plate.setValue(mm)
        if same and self.editor is not None and not self.busy:
            self._on_dish_value_changed(mm)      # the box did not change, so nothing fired

    def _on_dish_value_changed(self, val):
        """Live-recalibrate the current image when the dish size changes (typing or the 85/100
        quick-picks): re-scales the already-detected dish, so all mm sizes + the calibration
        update immediately. Before an image is loaded it's a no-op (the value applies at detect)."""
        if self.busy or self.editor is None:
            return
        if self.editor.set_plate_mm(val):
            self._dish_note(None)
        else:
            self._dish_note("No dish outline was found on this image, so the Dish size has nothing "
                            "to rescale. Use “Set plate” (click 3 points on the rim) or the "
                            "“Ruler” to calibrate.")

    def _on_calibration_changed(self, plate_mm):
        """Set plate / Ruler / an undo of either changed the scale in the editor: show the dish
        size it now stands for in the Dish box. Signals blocked, so this does not come back
        as a rescale (CT-R1 F20: the box kept saying 90 after Set plate 85)."""
        if plate_mm is None or plate_mm <= 0:
            return
        self.plate.blockSignals(True)
        try:
            self.plate.setValue(float(plate_mm))
        finally:
            self.plate.blockSignals(False)

    def _confirm_discard(self, action):
        """Ask ONCE before an action that throws away unsaved hand edits (CT-R1 F8: Orient and
        Re-detect discarded erased plaques, drawn shapes and a hand calibration without a
        word). True = go ahead."""
        ed = self.editor
        if ed is None or not getattr(ed, "dirty", False):
            return True
        ans = QMessageBox.question(
            self, "Unsaved edits",
            "You have unsaved edits on this plate (plaques added or removed, a hand "
            "calibration or a scale-bar change).\n\n%s replaces them with a fresh detection. "
            "Save results or Export all first if you want to keep them.\n\n"
            "Discard the edits and continue?" % action,
            QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Cancel)
        # Yes is accepted too: scripted callers that answer every question with Yes mean "go on"
        return ans in (QMessageBox.Discard, QMessageBox.Yes)

    # -- drag and drop ------------------------------------------------------ #
    def dragEnterEvent(self, e):
        md = e.mimeData()
        if md.hasUrls():
            for u in md.urls():
                if u.toLocalFile().lower().endswith(IMG_EXTS):
                    e.acceptProposedAction(); return
        e.ignore()

    def dropEvent(self, e):
        if self.busy:
            e.ignore(); return
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if p.lower().endswith(IMG_EXTS):
                if not self._confirm_discard("Opening another image"):
                    e.ignore(); return
                self._detect(self._new_image_request(p))   # loads/replaces the current image
                e.acceptProposedAction()
                return
        e.ignore()

    # -- actions ------------------------------------------------------------ #
    @staticmethod
    def _new_image_request(path):
        """A detection request for a freshly opened file (identity orientation)."""
        return {"image_path": path, "detect_src": None, "cur_img": None, "orient_ops": []}

    def open_image(self):
        if self.busy:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Select a plaque image", "", IMG_FILTER)
        if not path:
            return
        if not self._confirm_discard("Opening another image"):
            return
        self._detect(self._new_image_request(path))

    def redetect(self):
        if self.image_path and not self.busy:
            if not self._confirm_discard("Re-detect"):
                return
            self._detect()

    def _orient(self, op):
        """Rotate/flip the loaded plate and re-detect on the new orientation, so the image,
        coordinates and any exported labels all match (e.g. your Fiji hand-labelling). Outputs
        stay named/saved next to the original image."""
        if self.busy or self.image_path is None:
            return
        if not self._confirm_discard("Rotating or flipping the plate"):
            return
        try:
            cur = self._cur_img
            if cur is None:
                cur = engine_api.read_image(self.image_path)
            cur = engine_api.rotate_flip(cur, op)
            stem = os.path.splitext(os.path.basename(self.image_path))[0]
            # Keep the oriented copy next to the outputs, not in the temp folder, and open
            # the editor ON that copy: exported labels then point at an image that exists
            # in the same orientation, so Validate scores them correctly. (Labels written
            # against the un-rotated original scored 0 % recall; AUDIT-2026-10.md, PT-34.)
            out_dir = os.path.join(os.path.dirname(self.image_path), "out")
            os.makedirs(out_dir, exist_ok=True)
            tmp = os.path.join(out_dir, stem + "_oriented.png")
            engine_api.write_image(tmp, cur)
        except Exception as e:
            QMessageBox.warning(self, "Orientation failed", str(e))
            return
        self._detect({"image_path": self.image_path, "detect_src": tmp, "cur_img": cur,
                      "orient_ops": list(self._orient_ops) + [op]})

    def _set_busy(self, on, message=""):
        self.busy = on
        self.progress.setVisible(on)
        self.busy_label.setText(message if on else "")
        if not on:
            self._busy_timer.stop()
        for w in (self.open_btn, self.redetect_btn, self.save_btn, self.mode, self.plate,
                  self.watershed, self.exclude_overlaps, self.plate_85, self.plate_100) + self._orient_btns:
            w.setEnabled(not on)
        if not on:
            self.save_btn.setEnabled(self.editor is not None)
            self.redetect_btn.setEnabled(self.image_path is not None)
            for _b in self._orient_btns:
                _b.setEnabled(self.image_path is not None)
            self._mode_changed(self.mode.currentIndex())

    def _start_busy(self, msgs):
        """Enter the busy state and cycle on-brand progress messages."""
        self._busy_msgs = list(msgs); self._busy_i = 0
        self._set_busy(True, self._busy_msgs[0])
        try:
            self.placeholder.setText(self._busy_msgs[0])
        except (RuntimeError, AttributeError):
            pass
        self._busy_timer.start()

    def _tick_busy(self):
        if not self.busy or not self._busy_msgs:
            return
        self._busy_i = (self._busy_i + 1) % len(self._busy_msgs)
        msg = self._busy_msgs[self._busy_i]
        self.busy_label.setText(msg)
        try:
            if self.placeholder is not None and self.placeholder.parent() is not None:
                self.placeholder.setText(msg)
        except (RuntimeError, AttributeError):
            pass

    def _detect(self, req=None):
        """Run a detection. `req` says WHAT to open ({image_path, detect_src, cur_img,
        orient_ops}); None = the image already on the tab, as it is. Nothing on the tab changes
        until the detection succeeds (on_detected commits the request; CT-R1 F15)."""
        if req is None:
            req = {"image_path": self.image_path, "detect_src": self._detect_src,
                   "cur_img": self._cur_img, "orient_ops": list(self._orient_ops)}
        key = self._mode_key()
        src = req["detect_src"] or req["image_path"]
        req["settings"] = {"key": key, "plate_mm": self.plate.value(),
                           "watershed": bool(self.watershed.isChecked()) and key not in ("published", "precise")}
        if key == "precise":
            self._detect_precise(req, src)
            return
        self._pending = req
        self._start_busy(_BUSY_STD)
        self.window().statusBar().showMessage(f"Detecting ({MODES[self.mode.currentIndex()][0]})…")
        kw = dict(plate_mm=self.plate.value(), watershed=self.watershed.isChecked())
        if key == "published":
            kw["published"] = True
        elif key == "sensitive":
            kw["small"] = True; kw["sensitive"] = True
        else:  # current
            kw["small"] = True
        w = Worker(engine_api.detect_single, src, **kw)
        w.signals.finished.connect(self.on_detected)
        w.signals.error.connect(self.on_error)
        self.pool.start(w)

    def _detect_precise(self, req, src):
        ok, reason = engine_api.precise_available()
        if not ok:
            QMessageBox.information(
                self, "Precise engine unavailable",
                "Precise mode needs a second environment (PlaqSeg / PyTorch) and the model "
                "weights, which are not installed on this machine:\n\n" + reason +
                "\n\nFalling back is easy — pick Published, Current or Sensitive above.")
            self.window().statusBar().showMessage(self._not_opened_message(
                req, "Precise is not installed — pick another engine"))
            return
        self._pending = req
        self._start_busy(_BUSY_PRECISE)
        self.window().statusBar().showMessage("Precise pipeline running (this can take a minute)…")
        w = Worker(engine_api.detect_precise, src, plate_mm=self.plate.value())
        w.signals.finished.connect(self.on_precise_detected)
        w.signals.error.connect(self.on_precise_error)
        self.pool.start(w)

    def _not_opened_message(self, req, why):
        """Status text for a detection that did not happen / failed: say which image is still
        the one on screen when the request was for a different file."""
        new = (req or {}).get("image_path")
        if self.editor is not None and self.image_path and new and new != self.image_path:
            return "%s. %s was NOT opened; still showing %s." % (
                why, os.path.basename(new), os.path.basename(self.image_path))
        return why + "."

    def _commit_request(self, det):
        """A detection succeeded: NOW the tab points at what it opened, and the result is
        stamped with what produced it (watershed, requested dish mm, the source file and any
        rotate/flip steps) so every export can say so without reading the widgets later."""
        req, self._pending = self._pending, None
        if req is None:                 # a result handed in directly (self-test, tests)
            return
        self.image_path = req["image_path"]
        self._detect_src = req["detect_src"]
        self._cur_img = req["cur_img"]
        self._orient_ops = list(req["orient_ops"])
        s = req.get("settings") or {}
        self._det_settings = (s.get("key"), bool(s.get("watershed")))
        det.setdefault("watershed", bool(s.get("watershed")))
        det.setdefault("plate_mm_requested", s.get("plate_mm"))
        det["source_image"] = self.image_path
        det["orientation"] = list(self._orient_ops)

    def _mount_editor(self):
        if self.editor is not None:
            self.editor.setParent(None)
        else:
            self.placeholder.setParent(None)
        self.editor = PlaqueCanvas(self.det, self._detect_src or self.image_path,
                                   os.path.join(os.path.dirname(self.image_path), "out"),
                                   on_change=self.refresh_table,
                                   face=style.LIGHT["surface"])
        self.editor.selection_changed.connect(self._on_canvas_selection)
        self.editor.calibration_changed.connect(self._on_calibration_changed)
        self.editor.dirty_changed.connect(lambda _on=True: self._show_status())
        self.canvas_layout.addWidget(self.editor, 1)
        QTimer.singleShot(0, self._sync_min_height)     # once the editor has its width

    def _status_text(self):
        """'19 detected + 14 detect-area · Published (validated) (edited)': what is on screen,
        by how it got there, the engine that PRODUCED it, and whether it has unsaved edits
        (CT-R1 F20: a Published result with 14 detect-area plaques still read 'Published')."""
        if self.editor is None or self.det is None:
            return ""
        c = self.editor.counts()
        parts = ["%d detected" % c["detected"]]
        if c["detect_area"]:
            parts.append("%d detect-area" % c["detect_area"])
        if c["by_hand"]:
            parts.append("%d added by hand" % c["by_hand"])
        # short engine name ("Published", not "Published (validated)") so "(edited)" reads clearly;
        # edited = differs from the detection result, or hand edits not yet saved
        eng = self._engine_label_of(self.det).split(" (")[0]
        edited = self.editor.edited or self.editor.dirty
        return "%s · %s%s" % (" + ".join(parts), eng, " (edited)" if edited else "")

    def _show_status(self):
        txt = self._status_text()
        if txt:
            self.window().statusBar().showMessage(txt)

    def on_detected(self, det):
        self._commit_request(det)
        self.det = det
        self._dish_msg = None
        try:
            self._mount_editor()
        finally:
            self._set_busy(False)      # an editor error must not leave the tab locked
        self.refresh_table()
        self._set_image_info()
        self._update_stale()

    def on_precise_detected(self, det):
        self._commit_request(det)
        self.det = det
        self._dish_msg = None
        try:
            self._mount_editor()
        finally:
            self._set_busy(False)
        # plaques are now the editable Precise detections -> normal table path
        self.refresh_table()
        self._set_image_info()
        self._update_stale()

    def _set_image_info(self):
        """Show the loaded photo's name + pixel size + camera/date + file size above the canvas."""
        if not self.image_path:
            self.img_info.setVisible(False)
            return
        parts = [os.path.basename(self.image_path)]
        try:
            ob = self.det.get("orig_bgr") if self.det else None
            if ob is not None:
                h, w = ob.shape[:2]
                parts.append("%d×%d px" % (w, h))
        except Exception:
            pass
        try:
            from PIL import Image
            ex = Image.open(self.image_path).getexif()
            model = ex.get(272)                      # camera model
            dt = ex.get(36867) or ex.get(306)        # DateTimeOriginal / DateTime
            if model:
                parts.append(str(model).strip())
            if dt:
                parts.append(str(dt).split()[0].replace(":", "-"))   # date only
        except Exception:
            pass
        try:
            parts.append("%.1f MB" % (os.path.getsize(self.image_path) / 1e6))
        except Exception:
            pass
        self.img_info.setText("📷  " + "   ·   ".join(parts))
        self.img_info.setToolTip(os.path.abspath(self.image_path))
        self.img_info.setVisible(True)

    def refresh_table(self, precise=None):
        if self.det is None or self.editor is None:
            return
        det = self.det
        flag = None
        plate = det.get("plate")
        if plate and plate.get("axis_ratio") and plate["axis_ratio"] > 1.03:
            flag = (f"⚠ Dish looks tilted (axis ratio {plate['axis_ratio']:.2f}). "
                    "mm calibration may be biased — re-shoot square-on for best accuracy.")

        if isinstance(precise, dict) and precise.get("precise"):
            summ = precise.get("precise_summary", {})
            df = precise.get("precise_df")
            self._set_table_df(df)
            n = int(summ.get("n_final", len(df)))
            median = summ.get("median_diam_mm")
            mean = summ.get("mean_diam_mm")
            cal = det.get("pxl_per_mm")
            if summ.get("uncertainty_flag"):
                extra = "⚠ Detectors disagree on count — verify by eye."
                flag = (flag + "  " + extra) if flag else extra
            self._set_summary(n=n, median=median, mean=mean, cal=cal, flag=flag)
            return

        summ = det.get("precise_summary") or {}
        if summ.get("uncertainty_flag"):
            extra = "⚠ Detectors disagree on count — verify by eye."
            flag = (flag + "  " + extra) if flag else extra
        # The table comes from the EDITOR (its plaques, its current plate and calibration, the
        # result's own engine flag) -- the same call every export makes, so the screen and the
        # files cannot disagree (CT-R1 F7).
        full = self.editor.table(with_reason=True)
        reasons = [str(r) if r else "" for r in full["QC_REASON"].tolist()]
        df = full.drop(columns=["QC_REASON"])
        cal = self.editor.ppm
        self._set_table_df(df, reasons=reasons, calibrated=bool(cal))
        n = len(df)
        stats_df = df
        if self.exclude_overlaps.isChecked() and "OVERLAP" in df.columns:
            stats_df = df[df["OVERLAP"] != "yes"]
        n_excl = n - len(stats_df)
        if n_excl:
            ov_msg = f"↔ {n_excl} overlapping plaque(s) excluded from the stats."
            flag = (flag + "  " + ov_msg) if flag else ov_msg
        if not cal:
            # CT-R1 F14: no mm scale. The card switches to pixel diameters and says why, in
            # place of "0.00 mm" that looked like a measurement.
            if self.editor.plate and self.plate.value() <= 0:
                why = ("⚠ Dish size is 0: sizes are in pixels. Type the dish diameter in the Dish "
                       "box, or use Set plate or the Ruler to calibrate.")
            else:
                why = ("⚠ No dish found: sizes are in pixels. Use Set plate or the Ruler to "
                       "calibrate.")
            if self._dish_msg:      # the user just tried the Dish box / 85 / 100 buttons
                why += "  The Dish size has no dish outline to rescale on this image."
            flag = (why + "  " + flag) if flag else why
        elif self._dish_msg:
            flag = (flag + "  " + self._dish_msg) if flag else self._dish_msg
        dm =pd.to_numeric(stats_df["DIAMETER_MM" if cal else "DIAMETER_PXL"], errors="coerce").dropna()
        self._set_summary(
            n=n,
            median=(dm.median() if len(dm) else None),
            mean=(dm.mean() if len(dm) else None),
            cal=cal, flag=flag, unit=("mm" if cal else "px"))
        self._show_status()

    # -- canvas <-> table selection link ------------------------------------ #
    _MM_COLUMNS = ("AREA_MM2", "DIAMETER_MM")

    def _set_table_df(self, df, reasons=None, calibrated=True):
        """Refresh the table without letting the model-reset wipe the canvas selection,
        then re-mirror the canvas selection into the fresh rows.

        Display only (the model keeps the measure_table frame as it is, in CSV column order):
        mm cells read "—" when there is no mm scale (CT-R1 F14); a flagged row is tinted, its
        QC_FLAG cell explains itself on hover, and the QC_FLAG column is SHOWN second, where it
        can be seen without scrolling (F24)."""
        self._syncing = True
        try:
            has_qc = df is not None and "QC_FLAG" in df.columns
            self.model.set_dataframe(
                df, dash_columns=(() if calibrated else self._MM_COLUMNS),
                cell_tooltips=({"QC_FLAG": reasons} if (has_qc and reasons is not None) else None),
                flag_column=("QC_FLAG" if has_qc else None))
            if has_qc:
                hdr = self.table.horizontalHeader()
                vis = hdr.visualIndex(list(df.columns).index("QC_FLAG"))
                if vis != 1 and hdr.count() > 1:
                    hdr.moveSection(vis, 1)
        finally:
            self._syncing = False
        if self.editor is not None:
            self._apply_canvas_selection_to_table(self.editor.selected_uids())

    def _on_canvas_selection(self, uids):
        """A plaque was (de)selected on the image → mirror it onto the table rows."""
        if self._syncing:
            return
        self._apply_canvas_selection_to_table(list(uids or []))

    def _on_table_selection(self, *args):
        """Row(s) selected in the table → highlight the matching plaque(s) on the image."""
        if self._syncing or self.editor is None:
            return
        sm = self.table.selectionModel()
        rows = sorted({self.proxy.mapToSource(ix).row() for ix in sm.selectedIndexes()})
        plaques = self.editor.plaques
        uids = [plaques[r].get("_uid") for r in rows if 0 <= r < len(plaques)]
        self._syncing = True
        try:
            self.editor.select_uids(uids)
        finally:
            self._syncing = False
        self._update_selected_readout(uids)

    def _apply_canvas_selection_to_table(self, uids):
        sm = self.table.selectionModel()
        if sm is None or self.editor is None:
            return
        uidset = set(u for u in (uids or []) if u is not None)
        self._syncing = True
        try:
            sm.clearSelection()
            first = None
            if uidset:
                for i, p in enumerate(self.editor.plaques):
                    if p.get("_uid") in uidset:
                        prox = self.proxy.mapFromSource(self.model.index(i, 0))
                        sm.select(prox, QItemSelectionModel.Select | QItemSelectionModel.Rows)
                        if first is None:
                            first = prox
                if first is not None:
                    self.table.scrollTo(first, QAbstractItemView.EnsureVisible)
        finally:
            self._syncing = False
        self._update_selected_readout(list(uidset))

    def _update_selected_readout(self, uids):
        uids = [u for u in (uids or []) if u is not None]
        if not uids:
            self.sel_readout.setText(self._SEL_HINT); return
        if len(uids) == 1 and self.editor is not None:
            try:
                i = next(k for k, p in enumerate(self.editor.plaques) if p.get("_uid") == uids[0])
                row = self.model.dataframe().iloc[i]
                turb = row["TURBIDITY_REL"]
                turb = "—" if turb in ("", None) else turb
                if self.editor.ppm:
                    size = f"Ø {row['DIAMETER_MM']} mm  ·  area {row['AREA_MM2']} mm²"
                else:               # no mm scale: pixels, not "0.0 mm" (CT-R1 F14)
                    size = f"Ø {row['DIAMETER_PXL']} px  ·  area {row['AREA_PXL']} px²"
                self.sel_readout.setText(
                    f"Selected  #{row['INDEX']}  ·  {size}"
                    f"  ·  gray {row['MEAN_GRAY']}  ·  turbidity {turb}  —  Ctrl+C to copy this row")
                return
            except (StopIteration, IndexError, KeyError):
                pass
        self.sel_readout.setText(f"{len(uids)} plaques selected — Ctrl+C to copy their rows")

    def _open_fiji_compare(self):
        if self.editor is None:
            QMessageBox.information(self, "Open an image first",
                                   "Detect plaques first, then compare them against your Fiji results.")
            return
        from app import fiji_export, fiji_dialog
        app_df = fiji_export.app_match_frame(self.editor.plaques, self.editor.orig_bgr,
                                             self.editor.plate, self.editor.ppm,
                                             published=self.editor._pub())
        dlg = fiji_dialog.FijiCompareDialog(app_df, calibrated=bool(self.editor.ppm), parent=self)
        dlg.exec()

    def save(self):
        if self.editor is None:
            return
        try:
            self.editor.save()
            # the folder the editor actually wrote to (it belongs to the image ON SCREEN; the
            # tab used to rebuild the path from a file name that could be another image, F15)
            out_dir = self.editor.out_dir
            self.editor._update_hint("✓ saved the results (CSV, annotated image, legend key) → 'out' folder")
            self.window().statusBar().showMessage(f"Saved to {out_dir}")
            QMessageBox.information(self, "Saved", f"Results written to:\n{out_dir}")
        except Exception as e:
            QMessageBox.critical(self, "Save failed", str(e))

    def _set_placeholder(self, text):
        try:
            if self.editor is None:
                self.placeholder.setText(text)
        except (RuntimeError, AttributeError):
            pass

    def on_error(self, msg):
        req, self._pending = self._pending, None     # nothing was opened: the tab is unchanged
        self._set_busy(False)
        self._set_placeholder("Detection failed. Try another image or mode.")
        self.window().statusBar().showMessage(self._not_opened_message(req, "Detection failed"))
        QMessageBox.critical(self, "Detection failed", msg[:1000])

    def on_precise_error(self, msg):
        req, self._pending = self._pending, None
        self._set_busy(False)
        self._set_placeholder("Precise detection unavailable.")
        self.window().statusBar().showMessage(self._not_opened_message(
            req, "Precise unavailable — pick another engine"))
        QMessageBox.information(self, "Precise engine unavailable", msg[:1200])


# --------------------------------------------------------------------------- #
#  Summary tables shared by the Batch and Compare tabs (CT-R1 F18, F23)
# --------------------------------------------------------------------------- #
from PySide6.QtGui import QFontMetrics  # noqa: E402
from PySide6.QtWidgets import QBoxLayout  # noqa: E402  (only the Compare tab needs it)


def _is_blank(val):
    """True for the values a summary table shows as an empty cell (None / NaN / pd.NA / '')."""
    if val is None:
        return True
    if isinstance(val, str):
        return val.strip() == "" or val.strip().lower() in ("nan", "none", "<na>")
    try:
        return bool(pd.isna(val))
    except (TypeError, ValueError):
        return False


def _fmt_cell(val, kind=None):
    """Display text of one summary-table cell. The CSV on disk keeps full precision; the
    table shows whole counts, 4 significant digits, yes/no for flags and an EMPTY cell (not
    'nan') where there is no value."""
    if _is_blank(val):
        return ""
    if isinstance(val, bool) or type(val).__name__ in ("bool_", "bool"):
        return "yes" if bool(val) else "no"
    if isinstance(val, str):
        return val
    try:
        f = float(val)
    except (TypeError, ValueError):
        return str(val)
    if kind == "count" or (float(f).is_integer() and abs(f) < 1e6 and kind is None
                           and not isinstance(val, float)):
        return str(int(round(f)))
    if kind == "sci":
        return "%.3g" % f if abs(f) < 1e4 else "%.2e" % f
    return "%.4g" % f


class SummaryTableModel(PandasTableModel):
    """PandasTableModel for the per-plate / per-phage summaries: short human header labels
    with the CSV column name + meaning as tooltip, rounded numbers, blanks instead of 'nan'.
    Qt.UserRole still returns the raw value, so sorting is by the real number."""

    def __init__(self, columns=None):
        super().__init__()
        self._meta = dict(columns or {})        # CSV column -> (label, tooltip, kind)

    def _col(self, section):
        return str(self._df.columns[section])

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        col = self._col(index.column())
        val = self._df.iloc[index.row(), index.column()]
        if role == Qt.DisplayRole:
            return _fmt_cell(val, self._meta.get(col, ("", "", None))[2])
        if role == Qt.UserRole:
            return val
        if role == Qt.ToolTipRole:
            if isinstance(val, str) and len(val) > 30:
                return val                       # long text (an error) is readable on hover
            return self._meta.get(col, (col, None, None))[1]
        if role == Qt.TextAlignmentRole:
            numeric = not isinstance(val, (str, bool)) and type(val).__name__ != "bool_"
            return int((Qt.AlignRight if numeric else Qt.AlignLeft) | Qt.AlignVCenter)
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and section < len(self._df.columns):
            col = self._col(section)
            label, tip, _kind = self._meta.get(col, (col, None, None))
            if role == Qt.DisplayRole:
                return label
            if role == Qt.ToolTipRole:
                return ("%s\n(CSV column: %s)" % (tip, col)) if tip else "CSV column: %s" % col
            return None
        return super().headerData(section, orientation, role)


class NaturalSortProxy(NumericSortProxy):
    """Sorts numbers by value, text in natural order (Plate_2 before Plate_10), and keeps
    empty cells together after everything else."""

    @staticmethod
    def _key(val):
        if _is_blank(val):
            return (2, 0.0, [])
        if isinstance(val, str):
            return (1, 0.0, batch_measure.natural_key(val))
        try:
            return (0, float(val), [])
        except (TypeError, ValueError):
            return (1, 0.0, batch_measure.natural_key(str(val)))

    def lessThan(self, left, right):
        return (self._key(self.sourceModel().data(left, Qt.UserRole))
                < self._key(self.sourceModel().data(right, Qt.UserRole)))


def _visible_columns(df):
    """`df` without the columns that are blank in every row (half of per_phage.csv is empty
    when there is no blank image, and the table showed them all as 'nan'; CT-R1 F23)."""
    if df is None or not len(df.columns):
        return df
    keep = [c for c in df.columns if len(df) == 0 or not all(_is_blank(v) for v in df[c].tolist())]
    return df[keep]


def _summary_table(columns):
    """(view, model, proxy) for a read-only summary table, sortable, sized to its contents."""
    view = CopyableTableView(); model = SummaryTableModel(columns)
    proxy = NaturalSortProxy(); proxy.setSourceModel(model)
    view.setModel(proxy); view.setSortingEnabled(True)
    view.setAlternatingRowColors(True)
    view.verticalHeader().setVisible(False)
    view.horizontalHeader().setStretchLastSection(True)
    view.setEditTriggers(QAbstractItemView.NoEditTriggers)
    # the sorted column needs room for its arrow: re-fit when the user sorts by another one
    view.horizontalHeader().sortIndicatorChanged.connect(lambda *_: _fit_columns(view))
    return view, model, proxy


def _fit_columns(view, max_width=420):
    """Size every column to its contents AND its full header text; cap very long text.
    Qt's own resizeColumnsToContents reserves room for a sort arrow on EVERY column (~40 px
    each), which pushed the last columns of the summaries off the card; only the column that
    is sorted needs it."""
    hdr, model = view.horizontalHeader(), view.model()
    if model is None:
        return
    bold = QFont(hdr.font()); bold.setBold(True)       # the stylesheet draws headers semi-bold
    fm_head, fm_cell = QFontMetrics(bold), view.fontMetrics()
    sorted_col = hdr.sortIndicatorSection() if hdr.isSortIndicatorShown() else -1
    hdr.setStretchLastSection(False)
    for c in range(model.columnCount()):
        head = str(model.headerData(c, Qt.Horizontal, Qt.DisplayRole) or "")
        w = fm_head.horizontalAdvance(head) + 26 + (22 if c == sorted_col else 0)
        for r in range(min(model.rowCount(), 500)):
            w = max(w, fm_cell.horizontalAdvance(str(model.data(model.index(r, c), Qt.DisplayRole) or "")) + 22)
        hdr.resizeSection(c, min(w, max_width))
    # the last column takes whatever width is left, but only when it holds text: a stretched
    # numeric column puts its right-aligned numbers at the far edge of the card, far from
    # their header (seen in the Batch and per-phage tables)
    last = model.columnCount() - 1
    cells = [str(model.data(model.index(r, last), Qt.DisplayRole) or "") for r in range(min(model.rowCount(), 50))]
    def _num(t):
        try:
            float(t); return True
        except ValueError:
            return False
    hdr.setStretchLastSection(not any(_num(t) for t in cells if t))


def _read_csv_or_empty(path):
    """A CSV as a DataFrame; an absent or zero-byte file is an empty frame, never an exception
    on the GUI thread (qc.csv is one byte when every image of a run failed)."""
    try:
        return pd.read_csv(path)
    except (OSError, ValueError, pd.errors.EmptyDataError):
        return pd.DataFrame()


def _truthy(v):
    return str(v).strip().lower() in ("true", "1", "yes")


_STAT = {"PLAQUE_MEAN": ("pooled", "mean over every plaque of the phage, pooled across its "
                                   "plates (plaques are not independent replicates)"),
         "PLATE_MEAN": ("plate mean", "mean of the per-plate means: the plate is the replicate, "
                                      "so compare phages with this one"),
         "PLATE_SD": ("plate SD", "standard deviation between the per-plate means (blank with "
                                  "one plate)")}
_QUANTITY = {"TRANSMITTANCE": ("Transm.", "transmittance = light through the plaque relative to "
                                          "the blank agar (with a blank image) or to the lawn (without)"),
             "OD": ("OD", "optical density of the plaque against the blank agar"),
             "TURBIDITY": ("Turbidity", "plaque OD / lawn OD: 0 = as clear as agar, 1 = as opaque "
                                        "as the lawn")}
PHAGE_COLUMNS = {"PHAGE": ("Phage", "Phage / sample label (from the file name).", None),
                 "N_PLATES": ("Plates", "Number of plates of this phage that had plaques.", "count"),
                 "N_PLAQUES": ("Plaques", "Number of plaques measured, all plates together.", "count")}
for _q, (_qlab, _qtip) in _QUANTITY.items():
    for _s, (_slab, _stip) in _STAT.items():
        PHAGE_COLUMNS["%s_%s" % (_q, _s)] = ("%s %s" % (_qlab, _slab),
                                             "%s — %s.\n%s." % (_q.capitalize(), _stip,
                                                                _qtip[0].upper() + _qtip[1:]), None)

PLATE_COLUMNS = {
    "PLATE": ("Plate", "Plate label (the image file name).", None),
    "PHAGE": ("Phage", "Phage / sample this plate belongs to.", None),
    "N_PLAQUES": ("Plaques", "Number of plaques counted on this plate.", "count"),
    "PFU_PER_ML": ("PFU/mL", "Titer = plaques × dilution factor ÷ plated volume (mL).", "sci"),
    "PFU_PER_ML_CI95_LO": ("95 % low", "Lower end of the 95 % interval of the titer (exact "
                                       "Poisson limits on the plaque count).", "sci"),
    "PFU_PER_ML_CI95_HI": ("95 % high", "Upper end of the 95 % interval of the titer (exact "
                                        "Poisson limits on the plaque count).", "sci"),
    "COUNTABLE_30_300": ("Countable (30–300)", "yes when the plate has 30 to 300 plaques, the "
                                               "conventional range for a reliable titer; no "
                                               "when it has fewer or more.", None),
    "OD_REFERENCE": ("OD reference", "absolute = measured against the blank-agar image; "
                                     "lawn-relative = no blank (or no dish found), so only "
                                     "transmittance relative to the lawn is reported.", None),
}

BATCH_COLUMNS = {
    "image": ("Image", "Image file name.", None),
    "n_plaques": ("Plaques", "Number of plaques measured on the plate.", "count"),
    "mm_per_px": ("mm/pixel", "Calibration: millimetres per image pixel (from the dish "
                              "diameter). Empty when no dish was found.", None),
    "median_diam_mm": ("Median (mm)", "Median plaque diameter on the plate, in mm.", None),
    "mean_diam_mm": ("Mean (mm)", "Mean plaque diameter on the plate, in mm.", None),
    "axis_ratio": ("Axis ratio", "Long / short axis of the detected dish. Above 1.03 the "
                                 "photo was taken at an angle and sizes may be biased.", None),
    "tilt_flag": ("Tilted?", "yes when the dish axis ratio is above 1.03 (photo taken at an "
                             "angle).", None),
    "n_edge": ("Edge", "Plaques touching the dish rim or the image border (QC flag EDGE). "
                       "Open the plate in Measure to check them.", "count"),
    "n_overlap": ("Overlap", "Plaques touching another plaque (QC flag OVERLAP): their sizes "
                             "are unreliable.", "count"),
    "n_merged": ("Merged?", "Plaques that look like two counted as one (QC flag MERGED?: far "
                            "larger than the plate median, or far from round).", "count"),
    "error": ("Problem", "Why this image could not be measured.", None),
}


def compare_qc_note(q, failed=(), titer=False):
    """The Compare tab's QC sentence(s), from qc.csv rows `q` (CT-R1 F5). Polarity is a
    pass/fail only for plates measured against a blank (ABSOLUTE_OD): without one the engine
    does not assess it, and the tab must not call it a failure. Plates with no plaques are
    named, because they are absent from the per-phage table."""
    failed = [str(f) for f in failed]
    n = len(q)
    parts = ["%d plate%s analysed." % (n, "" if n == 1 else "s")]
    if failed:
        parts.append("⚠ %d image%s could not be read (see errors.csv): %s."
                     % (len(failed), "" if len(failed) == 1 else "s", ", ".join(failed)))
    if n == 0:
        return "  ".join(parts)
    plates = q["PLATE"].astype(str).tolist()
    absolute = [_truthy(v) for v in q["ABSOLUTE_OD"]] if "ABSOLUTE_OD" in q else [False] * n
    pol_ok = [_truthy(v) for v in q["POLARITY_OK"]] if "POLARITY_OK" in q else [True] * n
    dish = [_truthy(v) for v in q["DISH_FOUND"]] if "DISH_FOUND" in q else [True] * n
    counts = pd.to_numeric(q["N_PLAQUES"], errors="coerce").fillna(0).tolist() if "N_PLAQUES" in q else [1] * n
    cv = pd.to_numeric(q["ILLUM_CV"], errors="coerce").tolist() if "ILLUM_CV" in q else [float("nan")] * n
    nod = [p for p, d in zip(plates, dish) if not d]
    zero = [p for p, c in zip(plates, counts) if c == 0]
    bad = [p for p, a, ok in zip(plates, absolute, pol_ok) if a and not ok]
    rel = [p for p, a in zip(plates, absolute) if not a]
    uneven = [p for p, v in zip(plates, cv) if v == v and v > 0.15]
    if nod:
        parts.append("⚠ no dish found (sizes and turbidity unreliable): %s." % ", ".join(nod))
    if zero:
        parts.append("0 plaques: %s." % ", ".join(zero))
    if bad:
        parts.append("⚠ polarity fail (plaques darker than the lawn; check that the plates were "
                     "back-lit): %s." % ", ".join(bad))
    if uneven:
        parts.append("⚠ uneven illumination (add a flat-field image): %s." % ", ".join(uneven))
    if len(rel) == n:
        parts.append("Lawn-relative only (no blank): polarity not assessed.")
    elif rel:
        parts.append("Lawn-relative only (the blank could not be applied): polarity not assessed "
                     "for %s." % ", ".join(rel))
    if not (nod or bad or uneven or failed):
        parts.append("✓ QC passed (dish found%s)." % (", polarity" if len(rel) < n else ""))
    if not titer:
        parts.append("No titer: fill in both Titer boxes (dilution factor and plated volume) "
                     "to get PFU/mL.")
    return "  ".join(parts)


def parse_number(text):
    """A number typed into a Titer box: 1e6, 1000000, 2.5 or 10^6. Returns a float, or None
    when the text is not ONE unambiguous number ('1,000,000' is refused: a comma is a decimal
    mark in half the world, and a wrong guess is a titer wrong by orders of magnitude)."""
    import re
    t = str(text).strip().replace(" ", "")
    m = re.fullmatch(r"(\d+(?:\.\d+)?)?(?:[x×*])?10\^(-?\d+)", t)
    try:
        v = (float(m.group(1) or 1) * 10.0 ** int(m.group(2))) if m else float(t)
    except (ValueError, OverflowError):
        return None
    return v if v == v and abs(v) != float("inf") else None


# --------------------------------------------------------------------------- #
class CompareTab(QWidget):
    _FIG_MAX_W = 640           # figures are scaled to the panel width, never above this

    def __init__(self, pool):
        super().__init__()
        self.pool = pool
        self.last_out = None       # output folder of the last finished run
        self._last_df = None       # its plaque table (re-drawn when the key switch changes)
        self._figures = []         # records of the figures the last run wrote (and nothing else)
        self._fig_labels = []      # (QLabel, full-size QPixmap) of the figures on screen

        self.folder = self._pathrow("Plate folder (filename = phage)", browse_dir=True,
                                     tip="A folder of plate images; the file name is used as the "
                                         "phage label.")
        self.blank = self._pathrow("Blank-agar image (optional)", file=True,
                                   tip="An image of blank agar with no lawn — enables absolute "
                                       "optical-density (OD) readings.")
        self.flat = self._pathrow("Flat-field image (optional)", file=True,
                                  tip="An even-illumination reference image to correct uneven "
                                      "lighting across the plate.")

        self.plate = QDoubleSpinBox(); self.plate.setRange(0, 500); self.plate.setValue(100)
        self.plate.setSuffix(" mm")
        self.small = QCheckBox("Small plaques")
        self.watershed = QCheckBox("Watershed")
        self.group = QCheckBox("Group replicates by name prefix"); self.group.setChecked(True)
        self.core = QDoubleSpinBox(); self.core.setRange(0.2, 1.0); self.core.setValue(1.0)
        self.core.setSingleStep(0.1)
        self.dilution = QLineEdit(); self.dilution.setPlaceholderText("dilution factor (e.g. 1e6)")
        self.dilution.setToolTip("For PFU/mL: the RECIPROCAL of the dilution that was plated — "
                                 "type 1e6 (or 1000000) for a 10⁻⁶ dilution. Fill in both Titer "
                                 "boxes, or leave both empty.")
        self.volume = QLineEdit(); self.volume.setPlaceholderText("plated volume µL")
        self.volume.setToolTip("For PFU/mL: the volume of diluted lysate plated, in microlitres "
                               "(e.g. 100). Fill in both Titer boxes, or leave both empty.")

        opts_box = QGroupBox("Options")
        opts = QGridLayout(opts_box); opts.setHorizontalSpacing(14); opts.setVerticalSpacing(8)
        opts.addWidget(QLabel("Dish"), 0, 0); opts.addWidget(self.plate, 0, 1)
        opts.addWidget(self.small, 0, 2); opts.addWidget(self.watershed, 0, 3)
        opts.addWidget(self.group, 1, 0, 1, 2)
        opts.addWidget(QLabel("Core fraction"), 1, 2); opts.addWidget(self.core, 1, 3)
        opts.addWidget(QLabel("Titer"), 2, 0)
        opts.addWidget(self.dilution, 2, 1); opts.addWidget(self.volume, 2, 2)

        self.run_btn = QPushButton(" Run comparison"); self.run_btn.setObjectName("Primary")
        self.run_btn.setIcon(_icon(QStyle.SP_MediaPlay))
        self.run_btn.clicked.connect(self.run)
        self.open_btn = QPushButton(" Open output folder"); self.open_btn.setEnabled(False)
        self.open_btn.setIcon(_icon(QStyle.SP_DirOpenIcon)); self.open_btn.clicked.connect(self._open_out)
        self.open_btn.setToolTip("Open the folder with the CSVs, the figures (PNG, SVG, PDF) and "
                                 "their legend keys (enabled after a run).")
        self.progress = QProgressBar(); self.progress.setRange(0, 0); self.progress.setVisible(False)
        self.progress.setMaximumWidth(220)
        runrow = QHBoxLayout(); runrow.addWidget(self.run_btn); runrow.addWidget(self.open_btn)
        runrow.addStretch(); runrow.addWidget(self.progress)

        self.qc = QLabel("—"); self.qc.setWordWrap(True); self.qc.setObjectName("ModeHelp")
        # per-phage summary (per_phage.csv) and per-plate counts + titer (qc.csv)
        self.table, self.model, self.proxy = _summary_table(PHAGE_COLUMNS)
        self.plate_table, self.plate_model, self.plate_proxy = _summary_table(PLATE_COLUMNS)

        # the figure panel: Legend key… | Place key on figure, then the figures of THIS run
        self.key_btn = QPushButton("Legend key…"); self.key_btn.setEnabled(False)
        self.key_btn.clicked.connect(self._save_keys)
        self.key_btn.setToolTip("Save the legend key of every figure shown here: each phage with "
                                "its exact colour, plus what the box-plot marks mean — as PNG, "
                                "SVG and PDF, with the legend text. (The same files are already "
                                "beside the figures in the output folder.)")
        self.key_cb = QCheckBox("Place key on figure"); self.key_cb.setChecked(True)
        self.key_cb.setToolTip("Draw the legend key on the figures themselves (the same entries "
                               "as the stand-alone key from “Legend key…”). Untick for figures "
                               "without a key; the shown figures are re-drawn at once.")
        self.key_cb.toggled.connect(self._rerender)
        keyrow = QHBoxLayout(); keyrow.setContentsMargins(4, 0, 4, 0)
        keyrow.addWidget(self.key_btn); keyrow.addWidget(self.key_cb); keyrow.addStretch()

        self.figs = QWidget(); self.figs_layout = QVBoxLayout(self.figs)
        self.figs_placeholder = None
        self.figscroll = QScrollArea(); self.figscroll.setWidgetResizable(True)
        self.figscroll.setWidget(self.figs)
        self.figscroll.setFrameShape(QFrame.NoFrame)
        # figures are scaled to the panel width (see _rescale_figures): only ever scroll down
        self.figscroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.figscroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self._show_placeholder("Comparison figures will appear here after a run\n"
                               "(box plots and histograms per phage).")

        left = QFrame(); left.setObjectName("Card")
        ll = QVBoxLayout(left); ll.setContentsMargins(12, 10, 12, 12)
        cap = QLabel("Per-phage summary"); cap.setObjectName("SummaryHeading")
        cap2 = QLabel("Per-plate counts and titer"); cap2.setObjectName("SummaryHeading")
        ll.addWidget(cap); ll.addWidget(self.table, 2)
        ll.addWidget(cap2); ll.addWidget(self.plate_table, 3)
        ll.addWidget(self.qc)
        right = QFrame(); right.setObjectName("Card")
        rl = QVBoxLayout(right); rl.setContentsMargins(8, 8, 8, 8)
        rl.addLayout(keyrow)
        rl.addWidget(self.figscroll, 1)

        self.results = QSplitter()
        self.results.addWidget(left); self.results.addWidget(right)
        self.results.setSizes([730, 500]); self.results.setChildrenCollapsible(False)
        self.results.splitterMoved.connect(lambda *_: self._rescale_figures())

        inputs_box = QGroupBox("Inputs")
        ib = QVBoxLayout(inputs_box)
        for r in (self.folder, self.blank, self.flat):
            ib.addLayout(r["row"])

        # Inputs above Options in a narrow window (as before); side by side once the window
        # is wide enough, which gives the results ~150 px more height (CT-R1 F23: at
        # 1320x880 the tables and figures had 290 px). See resizeEvent.
        self._top = QBoxLayout(QBoxLayout.TopToBottom); self._top.setSpacing(10)
        self._top.addWidget(inputs_box, 3); self._top.addWidget(opts_box, 2)

        lay = QVBoxLayout(self); lay.setContentsMargins(14, 12, 14, 12); lay.setSpacing(10)
        lay.addLayout(self._top)
        lay.addLayout(runrow)
        lay.addWidget(self.results, 1)

    # -- layout ------------------------------------------------------------- #
    def sizeHint(self):
        # MainWindow pins a tab's sizeHint as its minimum size. The two tables and the figure
        # panel can all shrink and scroll inside themselves, so do not let their roomy
        # default hints force a page scrollbar at the default window size.
        s = super().sizeHint()
        return QSize(s.width(), max(self.minimumSizeHint().height(), min(s.height(), 640)))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        want = QBoxLayout.LeftToRight if self.width() >= 1180 else QBoxLayout.TopToBottom
        if self._top.direction() != want:
            self._top.setDirection(want)
        self._rescale_figures()

    def _pathrow(self, label, file=False, browse_dir=False, tip=""):
        edit = QLineEdit(); edit.setToolTip(tip)
        btn = QPushButton("Browse…"); btn.setToolTip(tip)
        lab = QLabel(label); lab.setMinimumWidth(220)
        def pick():
            if file:
                p, _ = QFileDialog.getOpenFileName(self, label, "", IMG_FILTER)
            else:
                p = QFileDialog.getExistingDirectory(self, label)
            if p:
                edit.setText(p)
        btn.clicked.connect(pick)
        row = QHBoxLayout(); row.addWidget(lab); row.addWidget(edit, 1); row.addWidget(btn)
        return {"row": row, "edit": edit}

    # -- run ---------------------------------------------------------------- #
    def _check_inputs(self):
        """Everything the engine would refuse, checked BEFORE the worker starts, each with a
        message that says what is wrong and what to do (CT-R1 F2, F3). Returns the keyword
        arguments for engine_api.run_compare, or None after showing a warning."""
        def stop(title, text):
            QMessageBox.warning(self, title, text)
            return None

        directory = self.folder["edit"].text().strip()
        if not directory or not os.path.isdir(directory):
            return stop("Pick a folder", "Choose a folder of phage plate images.")
        if not engine_api.compare_images(directory):
            return stop("No images found",
                        "No images found in %s.\n\nThe folder must hold the plate photos "
                        "(.tif, .jpg, .png or .heic), one plate per file; the file name is "
                        "used as the phage label." % directory)
        kw = dict(plate_mm=self.plate.value(), small=self.small.isChecked(),
                  core=self.core.value(), group_by_prefix=self.group.isChecked(),
                  watershed=self.watershed.isChecked(),
                  out_dir=os.path.join(directory, "out_turbidity"),
                  key_on_figure=self.key_cb.isChecked())
        for name, row, what in (("blank", self.blank, "Blank-agar image"),
                                ("flat", self.flat, "Flat-field image")):
            path = row["edit"].text().strip()
            if path and not os.path.isfile(path):
                return stop("%s not found" % what,
                            "%s not found:\n%s\n\nPick the file again with Browse…, or clear "
                            "the box to run without it." % (what, path))
            kw[name] = path or None
        dil_t, vol_t = self.dilution.text().strip(), self.volume.text().strip()
        if bool(dil_t) != bool(vol_t):
            return stop("Titer needs both values",
                        "PFU/mL needs both Titer boxes: the dilution factor (e.g. 1e6) AND the "
                        "plated volume in µL (e.g. 100).\n\nFill in the %s, or clear both boxes "
                        "to run without a titer."
                        % ("plated volume" if dil_t else "dilution factor"))
        if dil_t:
            dil, vol = parse_number(dil_t), parse_number(vol_t)
            if dil is None or dil < 1:
                return stop("Dilution factor",
                            "The dilution factor must be a number of 1 or more: it is the "
                            "RECIPROCAL of the dilution that was plated, e.g. 1e6 (or 1000000) "
                            "for a 10⁻⁶ dilution.\n\nYou typed “%s”." % dil_t)
            if vol is None or vol <= 0:
                return stop("Plated volume",
                            "The plated volume must be a number greater than 0, in microlitres "
                            "(e.g. 100 for 0.1 mL).\n\nYou typed “%s”." % vol_t)
            kw["dilution"], kw["volume_ul"] = dil, vol
        return directory, kw

    def run(self):
        checked = self._check_inputs()
        if checked is None:
            return
        directory, kw = checked
        self._set_busy(True)
        self.window().statusBar().showMessage("Running turbidity comparison…")
        w = Worker(engine_api.run_compare, directory, **kw)
        w.signals.finished.connect(self.on_done)
        w.signals.error.connect(self.on_error)
        self.pool.start(w)

    def _set_busy(self, on):
        self.run_btn.setEnabled(not on)
        self.key_cb.setEnabled(not on)
        self.key_btn.setEnabled(not on and bool(self._figures))
        self.progress.setVisible(on)

    def on_done(self, res):
        out_dir = res["out_dir"]
        self.last_out = out_dir
        self._last_df = res.get("df")
        self._figures = list(res.get("figures") or [])
        self._set_busy(False)
        self.open_btn.setEnabled(True)
        self._load_tables(out_dir)
        self._show_figures()
        self.window().statusBar().showMessage(f"Done → {out_dir}")

    def on_error(self, msg):
        self._set_busy(False)
        self.window().statusBar().showMessage("Comparison failed.")
        QMessageBox.critical(self, "Comparison failed",
                             "The comparison could not run:\n\n" + str(msg)[:1000])

    # -- tables ------------------------------------------------------------- #
    def _load_tables(self, out_dir):
        per = _read_csv_or_empty(os.path.join(out_dir, "per_phage.csv"))
        self.model.set_dataframe(_visible_columns(per))
        self.table.sortByColumn(0, Qt.AscendingOrder)       # ascending by phage
        _fit_columns(self.table)

        q = _read_csv_or_empty(os.path.join(out_dir, "qc.csv"))
        titer = "PFU_PER_ML" in q.columns
        self.plate_model.set_dataframe(_visible_columns(self._plate_frame(q)))
        self.plate_table.sortByColumn(0, Qt.AscendingOrder)
        _fit_columns(self.plate_table)

        failed = []
        try:                                   # errors.csv is only current when this run failed some
            import json
            with open(os.path.join(out_dir, "run_metadata.json"), encoding="utf-8") as fh:
                n_failed = int(json.load(fh).get("n_failed") or 0)
            if n_failed:
                err = _read_csv_or_empty(os.path.join(out_dir, "errors.csv"))
                failed = err["PLATE"].astype(str).tolist() if "PLATE" in err else ["%d" % n_failed]
        except (OSError, ValueError):
            pass
        self.qc.setText(compare_qc_note(q, failed=failed, titer=titer))

    @staticmethod
    def _plate_frame(q):
        """qc.csv -> the per-plate table: plate, phage, count, PFU/mL with its 95 % interval,
        countable (30-300), and whether OD is absolute or lawn-relative (CT-R1 F3). A phage
        whose plates all have 0 plaques has no row in per_phage.csv but has one here."""
        cols = ["PLATE", "PHAGE", "N_PLAQUES", "PFU_PER_ML", "PFU_PER_ML_CI95_LO",
                "PFU_PER_ML_CI95_HI", "COUNTABLE_30_300", "OD_REFERENCE"]
        if q is None or not len(q) or "PLATE" not in q.columns:
            return pd.DataFrame(columns=cols[:3] + cols[6:])
        out = pd.DataFrame({"PLATE": q["PLATE"].astype(str)})
        out["PHAGE"] = q["PHAGE"].astype(str) if "PHAGE" in q else ""
        counts = pd.to_numeric(q["N_PLAQUES"], errors="coerce") if "N_PLAQUES" in q else pd.Series([float("nan")] * len(q))
        out["N_PLAQUES"] = pd.array([None if c != c else int(c) for c in counts], dtype="Int64")
        for c in ("PFU_PER_ML", "PFU_PER_ML_CI95_LO", "PFU_PER_ML_CI95_HI"):
            if c in q:
                out[c] = pd.to_numeric(q[c], errors="coerce")
        out["COUNTABLE_30_300"] = ["" if c != c else ("yes" if 30 <= c <= 300 else "no") for c in counts]
        if "ABSOLUTE_OD" in q:
            out["OD_REFERENCE"] = ["absolute (blank)" if _truthy(v) else "lawn-relative"
                                   for v in q["ABSOLUTE_OD"]]
        return out

    # -- figures ------------------------------------------------------------ #
    def _clear_figures(self):
        self._fig_labels = []
        self.figs_placeholder = None
        while self.figs_layout.count():
            item = self.figs_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)

    def _show_placeholder(self, text):
        self._clear_figures()
        self.figs_placeholder = QLabel(text)
        self.figs_placeholder.setObjectName("Placeholder")
        self.figs_placeholder.setAlignment(Qt.AlignCenter)
        self.figs_placeholder.setWordWrap(True)
        self.figs_layout.addWidget(self.figs_placeholder)
        self.figs_layout.addStretch()

    def _show_figures(self):
        """Show exactly the figures the last run wrote (`self._figures`), each with its legend
        text starter. Nothing is read from the folder by name pattern, so an earlier run's
        files can never appear (CT-R1 F4)."""
        self.key_btn.setEnabled(bool(self._figures))
        if not self._figures:
            self._show_placeholder("No figures: this run found no plaques to plot.")
            return
        self._clear_figures()
        for f in self._figures:
            pm = QPixmap(f["png"])
            if pm.isNull():
                continue
            lbl = QLabel(); lbl.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
            lbl.setToolTip("%s\nSaved as %s" % (f.get("title", ""), ", ".join(
                os.path.basename(p) for p in f.get("files", []))))
            self.figs_layout.addWidget(lbl)
            self._fig_labels.append((lbl, pm))
            self._add_key_text_row(f)
        self.figs_layout.addStretch()
        self._rescale_figures()
        QTimer.singleShot(0, self._rescale_figures)      # again once the panel has its final width

    def _rescale_figures(self):
        if not self._fig_labels:
            return
        m = self.figs_layout.contentsMargins()
        width = max(320, min(self._FIG_MAX_W,
                             self.figscroll.viewport().width() - m.left() - m.right() - 4))
        for lbl, pm in self._fig_labels:
            lbl.setPixmap(pm.scaledToWidth(min(width, pm.width()), Qt.SmoothTransformation))

    def _add_key_text_row(self, fig):
        """Under each figure: its legend text starter (from the key the figure was drawn with
        in THIS run) and a Copy button."""
        sentence = fig.get("legend_text") or ""
        if not sentence:
            return
        box = QLineEdit(sentence); box.setReadOnly(True); box.setCursorPosition(0)
        box.setObjectName("LegendText")
        box.setToolTip("Legend text starter for this figure — paste it into the figure legend "
                       "and edit. Its key image is saved beside the figure: %s"
                       % ", ".join(os.path.basename(p) for p in fig.get("key_files", [])
                                   if not p.endswith(".txt")))
        copy = QPushButton("Copy")
        copy.clicked.connect(lambda _=False, b=box: QApplication.clipboard().setText(b.text()))
        cap = QLabel("Legend text starter"); cap.setObjectName("FieldLabel")
        row = QWidget(); rl = QHBoxLayout(row); rl.setContentsMargins(0, 0, 0, 8)
        rl.addWidget(cap); rl.addWidget(box, 1); rl.addWidget(copy)
        self.figs_layout.addWidget(row)

    def _rerender(self, _checked=None):
        """"Place key on figure" changed: re-draw the shown figures with / without the key
        (same data, same colours; the stand-alone key files are rewritten with them)."""
        if self._last_df is None or not self.last_out or not self._figures:
            return                                   # nothing on screen yet: applies to the next run
        self._set_busy(True)
        self.window().statusBar().showMessage("Re-drawing the figures…")
        w = Worker(engine_api.render_compare_figures, self._last_df, self.last_out,
                   key_on_figure=self.key_cb.isChecked())
        w.signals.finished.connect(self._rerendered)
        w.signals.error.connect(self.on_error)
        self.pool.start(w)

    def _rerendered(self, res):
        self._figures = list(res.get("figures") or [])
        self._set_busy(False)
        self._show_figures()
        self.window().statusBar().showMessage(
            "Figures re-drawn %s the legend key → %s"
            % ("with" if self.key_cb.isChecked() else "without", res["out_dir"]))

    def _save_keys(self):
        """One click: the legend keys of the figures on screen, into a folder the user picks."""
        if not self._figures:
            return
        dest = QFileDialog.getExistingDirectory(
            self, "Save the legend keys of the shown figures to…", self.last_out or "")
        if not dest:
            return
        try:
            paths = engine_api.save_compare_keys(self._figures, dest)
        except Exception as e:                       # noqa: BLE001 -- report, never crash
            QMessageBox.warning(self, "Legend key",
                                "Could not save the legend keys to %s:\n%s" % (dest, e))
            return
        n = len([f for f in self._figures if f.get("key")])
        self.window().statusBar().showMessage(
            "Legend keys of %d figure%s saved (%d files) → %s"
            % (n, "" if n == 1 else "s", len(paths), dest), 8000)

    def _open_out(self):
        if self.last_out and os.path.isdir(self.last_out):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.last_out))


# --------------------------------------------------------------------------- #
class AboutTab(QWidget):
    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self); outer.setContentsMargins(24, 22, 24, 22)
        card = QFrame(); card.setObjectName("Card")
        _shadow(card)
        card.setMaximumWidth(760)
        lay = QVBoxLayout(card); lay.setContentsMargins(28, 24, 28, 24); lay.setSpacing(8)

        head = QHBoxLayout()
        ic = QLabel()
        icon_path = engine_api.resource_path("icon.png")
        if os.path.exists(icon_path):
            pm = QPixmap(icon_path)
            if not pm.isNull():
                ic.setPixmap(pm.scaled(56, 56, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        title_box = QVBoxLayout(); title_box.setSpacing(0)
        t = QLabel("Plaque Toolkit"); t.setStyleSheet("font-size:22px; font-weight:700;")
        nick = QLabel("“Frankenstein’s Plaque Lab”")
        nick.setStyleSheet("font-style:italic; color:#6b7484; font-size:13px;")
        v = QLabel(f"version {__version__}"); v.setObjectName("ModeHelp")
        title_box.addWidget(t); title_box.addWidget(nick); title_box.addWidget(v)
        head.addWidget(ic); head.addSpacing(12); head.addLayout(title_box); head.addStretch()
        lay.addLayout(head)

        body = QLabel(
            "<p>A desktop app for measuring bacteriophage <b>plaque size</b> and <b>turbidity</b> "
            "from Petri-dish photos, built on the peer-reviewed <b>Plaque Size Tool</b>. Nicknamed "
            "<b>“Frankenstein’s Plaque Lab”</b> because it stitches several tools into one — the PST "
            "detector, a PlaqSeg deep-learning model, a manual-correction editor, and mm calibration. "
            "Plaques are numbered <b>1→N from the top</b>.</p>"

            # CT-R1 DA-F23: the real seven tabs, one accurate line each
            "<p><b>The tabs</b></p><ul>"
            "<li><b>Measure</b> — open one plate photo, auto-detect, correct by hand, read size + "
            "turbidity, export (CSV, annotated figure, Fiji bundle, ground-truth labels).</li>"
            "<li><b>Batch</b> — a whole folder of plates → one CSV per plate + an all-plaques CSV + "
            "annotated images. (Drop a folder onto the tab.)</li>"
            "<li><b>Compare turbidity</b> — a folder of phages → optical density, clarity class, "
            "titer/PFU, per-phage statistics + figures.</li>"
            "<li><b>Analyze</b> — group plates into samples, then a violin SuperPlot with the right "
            "statistics (the plate is the experimental unit), summary tables and a ZIP export.</li>"
            "<li><b>Validate</b> — score the engines against your own hand-corrected labels "
            "(precision / recall / F1 + size agreement), with a CSV and a sentence to paste.</li>"
            "<li><b>Fiji agreement</b> — paste paired Toolkit and Fiji/ImageJ sizes → Bland–Altman, "
            "ICC, r, a method-comparison figure and a sentence for your paper.</li>"
            "<li><b>About</b> — this page.</li></ul>"

            "<p><b>Legend key</b> — every figure (Analyze, Compare turbidity, Fiji agreement) "
            "has a <b>Legend key…</b> button that saves a small image listing each sample, point "
            "and line style with its exact colour, in the figure’s format; a <b>legend text starter</b> "
            "sentence to paste into your figure legend (with Copy); and a <b>Place key on figure</b> "
            "switch that draws the same key on the figure itself.</p>"

            "<p><b>Detection engines</b> (Measure dropdown)</p><ul>"
            "<li><b>Published (validated)</b> — the exact Trofimova &amp; Jaschke 2021 algorithm. "
            "<i>The only citable mode.</i></li>"
            "<li><b>Current (corrected)</b> — same algorithm + bug-fixes + better dish calibration. "
            "Good routine default.</li>"
            "<li><b>Sensitive</b> — lowers the size gates to catch tiny plaques; more false positives "
            "(verify by eye).</li>"
            "<li><b>Precise (PST + PlaqSeg)</b> — fuses the classic detector with a deep-learning model; "
            "best on dense plates. ~1 min on first run. In-house (not independently/peer-reviewed); "
            "<b>locally validated</b> (~0.95 precision on our test plates) — report your own validation "
            "for publication.</li></ul>"

            "<p><b>Editor tools &amp; buttons</b> (once an image is open)</p><ul>"
            "<li><b>Add</b> — click a plaque to auto-trace it, or drag to draw a circle.</li>"
            "<li><b>Detect area</b> — rubber-band a region to re-scan just there.</li>"
            "<li><b>Erase</b> (or right-click) — remove a false positive.</li>"
            "<li><b>Set plate</b> — click 3 points on the real agar rim, type its diameter (mm) → recalibrates.</li>"
            "<li><b>Select / Remove selected / Undo</b> — click or box-select plaques; delete; step back.</li>"
            "<li><b>Scale bar</b> — pick a length + colour; drag it to reposition.</li>"
            "<li><b>⬇ Export all</b> — one click writes the CSV + annotated figure to an <code>out/</code> folder "
            "and opens it. <b>More ▾</b> has the individual exports (CSV, side-by-side, Fiji-calibrated crop, "
            "ground-truth labels).</li></ul>"

            "<p><b>Calibration (getting mm right)</b> — set <b>Dish</b> to the diameter of the circle the tool "
            "traces. The vendor’s “90 / 100 mm” is the <b>lid</b>; your plaques sit on the smaller <b>agar</b> "
            "base (often ~85 mm) — use that. The <b>85 / 100</b> quick-picks (and typing a value) now "
            "<b>re-scale the current image live</b>. A ruler laid in the agar plane is the most direct check. "
            "Until a scale is set, sizes are in pixels only.</p>"

            "<p><b>Turbidity</b> — a plaque’s <i>clarity</i>: clear ≈ fully lytic, turbid/cloudy ≈ temperate or "
            "regrowth. Reported per-plaque (<code>TURBIDITY_REL</code>) and across phages (Compare tab). From "
            "top-lit phone photos it is <i>apparent</i> OD (screening-grade) — for absolute OD use a backlit / "
            "transilluminator setup with RAW images.</p>"

            "<p><b>Citation.</b> The validated detection algorithm is from Trofimova&nbsp;&amp;&nbsp;Jaschke, "
            "<i>Virology</i> (2021). Cite that paper and use <b>Published (validated)</b> mode for published "
            "measurements.</p>"

            "<p style='color:#b45309'><b>Honest note.</b> The <b>Sensitive</b> and <b>Precise</b> modes are "
            "in-house extensions — <i>not</i> independently / peer-reviewed. <b>Precise</b> is "
            "<i>locally</i> validated (high precision on our test plates), which is not the same as an "
            "independent stamp: still verify by eye and report your own validation before publishing. "
            "For citable numbers use <b>Published (validated)</b>.</p>"

            "<p style='color:#6b7484'>Full guides live in the <b>Help</b> menu (User guide; How-to, use "
            "cases &amp; verification; Understanding the agreement statistics; How to validate this "
            "program; How it was built; and more).</p>")
        body.setObjectName("AboutBody"); body.setWordWrap(True); body.setOpenExternalLinks(True)
        body.setTextInteractionFlags(Qt.TextBrowserInteraction)
        lay.addWidget(body)

        holder = QWidget(); hl = QVBoxLayout(holder); hl.setContentsMargins(0, 0, 0, 0)
        hl.addWidget(card, 0, Qt.AlignHCenter | Qt.AlignTop); hl.addStretch()
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(holder)
        outer.addWidget(scroll)


def _scrollable(w, grow=True):
    """Wrap a tab in a scroll area so nothing is ever hidden. With grow=True we pin the tab's
    PREFERRED size as its minimum, so when the window is smaller than the content the scroll area
    shows real scrollbars (both directions) instead of squashing it — right for form tabs. With
    grow=False (canvas/splitter tabs like Measure) we let the content compress naturally (the
    splitter shrinks, the table scrolls internally) and only scroll below its true minimum."""
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.NoFrame)
    sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    sa.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    if grow:
        hint = w.sizeHint()
        if hint.width() > 0 and hint.height() > 0:
            w.setMinimumSize(hint)
    sa.setWidget(w)
    return sa


def _resolve_doc(name):
    """Return (abs_path_or_None, docs_dir) for a docs/ file (works from source and frozen)."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if getattr(sys, "frozen", False):
        root = getattr(sys, "_MEIPASS", root)
    docs_dir = os.path.join(root, "docs")
    path = os.path.join(docs_dir, name)
    if not os.path.exists(path):
        alt = os.path.join(root, name)
        path = alt if os.path.exists(alt) else None
    return path, docs_dir


_DOC_VIEWERS = []   # hold references so non-modal viewers aren't garbage-collected


class DocViewer(QDialog):
    """In-app documentation viewer: renders Markdown natively and HTML best-effort INSIDE
    the tool (no external editor), with a button to open the full-fidelity page in a browser."""

    def __init__(self, name, parent=None):
        super().__init__(parent)
        self._path, docs_dir = _resolve_doc(name)
        self._interactive = _is_interactive_html(self._path)
        self._is_md = False
        self._anchors = {}
        shown = os.path.basename(name) if os.path.isabs(name) else name
        self.setWindowTitle("Plaque Toolkit — help — %s" % shown)
        _av = QApplication.primaryScreen().availableGeometry()   # never open bigger than the screen
        self.resize(min(960, _av.width() - 60), min(800, _av.height() - 100))
        self.setObjectName("AppRoot")
        self.setAttribute(Qt.WA_DeleteOnClose, True)   # destroy on close; _DOC_VIEWERS holds it while open

        self.browser = QTextBrowser()
        self.browser.setOpenLinks(False)               # we handle links ourselves (ask before a browser)
        self.browser.anchorClicked.connect(self._on_anchor)
        self.browser.setSearchPaths([docs_dir])        # resolve relative images/links
        self.browser.setStyleSheet(
            "QTextBrowser{background:#ffffff;color:#1f2430;border:1px solid #dde6e2;"
            "border-radius:8px;padding:14px 20px;font-size:15px;}")

        is_html = name.lower().endswith((".html", ".htm"))
        text = None
        if self._path and os.path.exists(self._path):
            try:
                with open(self._path, "r", encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except OSError as e:
                self.browser.setPlainText("Could not read %s:\n%s" % (name, e))
        if text is not None:
            if is_html:
                self.browser.setHtml(text)
            else:
                self.browser.setMarkdown(text)
                self._is_md = True
                self._index_headings()
        elif self._path is None:
            self.browser.setPlainText("Could not find %s. It ships in the docs/ folder." % name)

        cap = QLabel(shown); cap.setObjectName("SummaryHeading")
        top = QHBoxLayout(); top.addWidget(cap); top.addStretch()
        self.ext_btn = QPushButton("Open in web browser")
        self.ext_btn.setToolTip("Open this page in your default web browser (full CSS layout, "
                                "figures and any interactive parts).")
        self.ext_btn.clicked.connect(self._open_external)
        self.ext_btn.setEnabled(bool(self._path))
        top.addWidget(self.ext_btn)
        close = QPushButton("Close"); close.clicked.connect(self.close)
        top.addWidget(close)

        lay = QVBoxLayout(self); lay.setContentsMargins(12, 12, 12, 12); lay.setSpacing(10)
        lay.addLayout(top)
        if self._interactive:
            banner = QLabel("⚠  This page is interactive (calculator / input boxes). Those "
                            "controls won’t work here — click “Open in web browser” "
                            "above for the working version.")
            banner.setWordWrap(True)
            banner.setStyleSheet("background:#fdf5e9;color:#7a4a08;border:1px solid #f0c987;"
                                 "border-radius:8px;padding:8px 12px;")
            lay.addWidget(banner)
        elif is_html:
            hint = QLabel("Tip: click “Open in web browser” above for the full-fidelity "
                          "layout & figures.")
            hint.setStyleSheet("color:#5b6a65;font-size:12px;padding:0 2px")
            lay.addWidget(hint)
        lay.addWidget(self.browser, 1)

    def _open_external(self):
        if self._path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._path))

    # CT-R1 DA-F23: setMarkdown() gives headings no anchors, so a table-of-contents link did
    # nothing; and links to other documents were ignored. Headings are indexed by their
    # GitHub-style slug (plus a punctuation-free form, and a prefix match for shortened links).
    @staticmethod
    def _slug(text):
        import re
        t = re.sub(r"[^\w\- ]", "", str(text).strip().lower(), flags=re.UNICODE)
        return t.replace(" ", "-")

    @staticmethod
    def _loose(text):
        import re
        return re.sub(r"[^0-9a-z]", "", str(text).lower())

    def _index_headings(self):
        self._anchors = {}
        block = self.browser.document().begin()
        while block.isValid():
            if block.blockFormat().headingLevel() > 0:
                slug = self._slug(block.text())
                key, k = slug, 1
                while key in self._anchors:          # GitHub numbers duplicate headings
                    key = "%s-%d" % (slug, k); k += 1
                self._anchors[key] = block.position()
            block = block.next()

    def _find_anchor(self, fragment):
        """Document position of the heading a #fragment points at, or None."""
        from urllib.parse import unquote
        frag = unquote(fragment).lower()
        if frag in self._anchors:
            return self._anchors[frag]
        loose = self._loose(frag)
        for slug, pos in self._anchors.items():
            if self._loose(slug) == loose:
                return pos
        for slug, pos in self._anchors.items():
            if loose and self._loose(slug).startswith(loose):
                return pos
        return None

    def scroll_to(self, fragment):
        """Scroll so the heading (Markdown) or named anchor (HTML) is at the top. True if found."""
        if not fragment:
            return False
        if self._is_md:
            pos = self._find_anchor(fragment)
            if pos is None:
                return False
            from PySide6.QtGui import QTextCursor
            block = self.browser.document().findBlock(pos)
            cur = QTextCursor(block)
            self.browser.setTextCursor(cur)
            y = self.browser.document().documentLayout().blockBoundingRect(block).top()
            self.browser.verticalScrollBar().setValue(int(y))
            return True
        self.browser.scrollToAnchor(fragment)
        return True

    def _open_linked_doc(self, url):
        """A relative link to another .md/.html document opens it in a new viewer."""
        base = os.path.dirname(self._path) if self._path else _resolve_doc("")[1]
        target = os.path.normpath(os.path.join(base, url.path()))
        if not os.path.exists(target):
            QMessageBox.information(self, "Document not found",
                                    "This link points to %s, which is not shipped with the app."
                                    % url.path())
            return None
        v = DocViewer(target, self.parent() or self)
        _DOC_VIEWERS.append(v)
        v.finished.connect(lambda _=0, vv=v: (vv in _DOC_VIEWERS) and _DOC_VIEWERS.remove(vv))
        v.show(); v.raise_(); v.activateWindow()
        if url.fragment():
            v.scroll_to(url.fragment())
        return v

    def _on_anchor(self, url):
        """Internal #anchors scroll within the doc; links to other .md/.html documents open in
        the viewer; an external http(s) link ASKS before opening a web browser."""
        if url.scheme() in ("http", "https"):
            ret = QMessageBox.question(
                self, "Open link in web browser?",
                "Open this link in your web browser?\n\n%s" % url.toString(),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ret == QMessageBox.Yes:
                QDesktopServices.openUrl(url)
        elif url.scheme() in ("", "file") and url.path().lower().endswith((".md", ".html", ".htm")):
            self._open_linked_doc(url)
        elif url.fragment():
            self.scroll_to(url.fragment())


def _is_interactive_html(path):
    """True for HTML pages that need a real browser (JavaScript/forms) — e.g. the Fiji
    validation calculator. QTextBrowser runs no JS, so these get a 'use a browser' banner."""
    if not (path and path.lower().endswith((".html", ".htm"))):
        return False
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            return "<script" in fh.read().lower()
    except OSError:
        return False


def _open_doc(name, parent=None):
    """Open a docs/ file IN-APP (rendered inside the tool). Interactive HTML still renders in the
    viewer, which shows a notice + an 'Open in web browser' button — nothing opens a browser
    without an explicit click. Signature kept for existing callers."""
    v = DocViewer(name, parent or QApplication.activeWindow())
    _DOC_VIEWERS.append(v)
    v.finished.connect(lambda _=0, vv=v: (vv in _DOC_VIEWERS) and _DOC_VIEWERS.remove(vv))
    v.show(); v.raise_(); v.activateWindow()


# --------------------------------------------------------------------------- #
class BatchTab(QWidget):
    """Run detection over a whole folder of plates → per-plate CSV + annotated images + summary."""

    def __init__(self, pool):
        super().__init__()
        self.pool = pool
        self.last_out = None
        self.setAcceptDrops(True)   # drop a folder anywhere on this tab to set it (see dropEvent)

        self.folder = QLineEdit(); self.folder.setPlaceholderText("Folder of plate images… (or drop one here)")
        self.folder.setToolTip("Folder with one plate photo per file. Tip: drag a folder onto this tab to set it.")
        browse = QPushButton("Browse…"); browse.clicked.connect(self._pick)
        browse.setToolTip("Choose the folder of plate images.")
        self.plate = QDoubleSpinBox(); self.plate.setRange(0, 500); self.plate.setValue(100)
        self.plate.setSuffix(" mm")
        self.plate.setToolTip("Dish diameter (mm) applied to every plate. Use the agar diameter (~85 mm), "
                              "not the lid. 0 = report pixels only.")
        self.mode = QComboBox()
        for label, _k, _h in MODES:
            self.mode.addItem(label)
        self.mode.setCurrentIndex(1)   # Current — fast; Precise over a whole folder is very slow
        self.mode.setToolTip("Detection engine for the batch. Current is a good fast default; "
                             "Precise is very slow over a whole folder.")
        self.watershed = QCheckBox("Split touching plaques")
        self.small = QCheckBox("Small plaques (engine -small gates)")
        # CT-R1 F18: each box is only enabled for the engines that use it, and shows what the
        # run will really do. The user's own choices are remembered here so switching engine
        # and back does not lose them.
        self._busy = False
        self._ws_choice = False            # "Split touching plaques" for Current / Sensitive
        self._small_choice = False         # "Small plaques" for Published
        self.watershed.toggled.connect(self._option_toggled)
        self.small.toggled.connect(self._option_toggled)
        self.mode.currentIndexChanged.connect(self._sync_options)
        self.crops = QCheckBox("Also export Fiji-calibrated plate crops")
        self.crops.setToolTip("For each image, also write a cropped-plate TIFF with the mm scale "
                              "baked in (plus a .fiji.txt). Opens in Fiji already scaled in mm, so "
                              "cropping a plaque keeps the scale for a scale bar.")

        self.run_btn = QPushButton(" Run batch"); self.run_btn.setObjectName("Primary")
        self.run_btn.setIcon(_icon(QStyle.SP_MediaPlay)); self.run_btn.clicked.connect(self._run)
        self.run_btn.setToolTip("Measure every image in the folder → per_plate.csv + all_plaques.csv "
                                "+ an annotated image for each.")
        self.open_btn = QPushButton(" Open output folder"); self.open_btn.setEnabled(False)
        self.open_btn.setIcon(_icon(QStyle.SP_DirOpenIcon)); self.open_btn.clicked.connect(self._open_out)
        self.open_btn.setToolTip("Open the folder with the batch results (enabled after a run).")
        self.progress = QProgressBar(); self.progress.setRange(0, 0); self.progress.setVisible(False)
        self.progress.setMaximumWidth(220)
        self.status = QLabel("Pick a folder of plate photos (one plate per image). Writes a per-plate "
                             "CSV, an all-plaques CSV and an annotated image for each.")
        self.status.setObjectName("ModeHelp"); self.status.setWordWrap(True)

        # whole counts, blanks instead of "nan", 4 significant digits, full header labels,
        # natural image order (CT-R1 F18) -- see SummaryTableModel
        self.table, self.model, self.proxy = _summary_table(BATCH_COLUMNS)
        self._sync_options()

        inputs = QGroupBox("Batch inputs")
        gl = QGridLayout(inputs); gl.setHorizontalSpacing(10); gl.setVerticalSpacing(8)
        gl.addWidget(QLabel("Folder"), 0, 0); gl.addWidget(self.folder, 0, 1); gl.addWidget(browse, 0, 2)
        gl.addWidget(QLabel("Dish"), 1, 0); gl.addWidget(self.plate, 1, 1)
        opt = QHBoxLayout(); opt.addWidget(QLabel("Engine")); opt.addWidget(self.mode)
        opt.addWidget(self.watershed); opt.addStretch()
        gl.addLayout(opt, 2, 1)
        gl.addWidget(self.crops, 3, 1)
        gl.addWidget(self.small, 4, 1)

        runrow = QHBoxLayout(); runrow.addWidget(self.run_btn); runrow.addWidget(self.open_btn)
        runrow.addStretch(); runrow.addWidget(self.progress)

        card = QFrame(); card.setObjectName("Card"); cl = QVBoxLayout(card); cl.setContentsMargins(12, 10, 12, 12)
        cap = QLabel("Per-plate summary"); cap.setObjectName("SummaryHeading")
        cl.addWidget(cap); cl.addWidget(self.table)

        lay = QVBoxLayout(self); lay.setContentsMargins(14, 12, 14, 12); lay.setSpacing(10)
        lay.addWidget(inputs); lay.addLayout(runrow); lay.addWidget(self.status); lay.addWidget(card, 1)

    # -- drag and drop: drop a folder anywhere on the tab to set the batch folder -- #
    def dragEnterEvent(self, e):
        md = e.mimeData()
        if md.hasUrls():
            for u in md.urls():
                if os.path.isdir(u.toLocalFile()):
                    e.acceptProposedAction(); return
        e.ignore()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if os.path.isdir(p):
                self.folder.setText(p)
                self.status.setText(f"Folder set: {p}   —   click “Run batch”.")
                e.acceptProposedAction()
                return
        e.ignore()

    def _pick(self):
        p = QFileDialog.getExistingDirectory(self, "Folder of plate images")
        if p:
            self.folder.setText(p)

    # -- options that depend on the engine (CT-R1 F18) ----------------------- #
    def _mode_key(self):
        return MODES[self.mode.currentIndex()][1]

    def _applied_options(self):
        """(watershed, small) as the run will really use them for the chosen engine."""
        key = self._mode_key()
        return (self._ws_choice and key in ("current", "sensitive"),
                self._small_choice if key == "published" else True)

    def _option_toggled(self, _checked=None):
        key = self._mode_key()
        if self.sender() is self.watershed and key in ("current", "sensitive"):
            self._ws_choice = self.watershed.isChecked()
        elif self.sender() is self.small and key == "published":
            self._small_choice = self.small.isChecked()
        self._sync_options()                 # a box that does not apply snaps back to the truth

    def _sync_options(self, *_):
        key = self._mode_key()
        ws_applies = key in ("current", "sensitive")
        small_is_choice = key == "published"
        ws, small = self._applied_options()
        for box, val in ((self.watershed, ws), (self.small, small)):
            box.blockSignals(True); box.setChecked(bool(val)); box.blockSignals(False)
        self.watershed.setEnabled(ws_applies and not self._busy)
        self.small.setEnabled(small_is_choice and not self._busy)
        # say it in the label too: a disabled box alone is easy to miss
        self.watershed.setText("Split touching plaques" if ws_applies
                               else "Split touching plaques (not used by this engine)")
        self.small.setText("Small plaques (engine -small gates)" if small_is_choice
                           else "Small plaques (always on with this engine)")
        self.watershed.setToolTip(
            "Watershed segmentation to separate plaques whose edges touch."
            if ws_applies else
            "Not available with this engine: Published never splits plaques (it is the "
            "unchanged published algorithm) and Precise does not use this option. Choose "
            "Current or Sensitive to use it.")
        self.small.setToolTip(
            "Lower the engine's size gates for plaques under ~2.5 mm. Published runs WITHOUT "
            "this unless ticked, matching the Measure tab and the command line."
            if small_is_choice else
            "Always on with this engine: Current, Sensitive and Precise always use the small "
            "gates in the app, so there is nothing to choose. Only Published can run without "
            "them.")

    def _run(self):
        folder = self.folder.text().strip()
        if not folder or not os.path.isdir(folder):
            QMessageBox.warning(self, "Pick a folder", "Choose a folder of plate images."); return
        if not batch_measure.find_images(folder):
            # an empty folder used to "succeed": "0 images → out_batch" and two empty CSVs
            msg = "No images found in %s" % folder
            self.status.setText(msg + " — nothing was measured.")
            self.window().statusBar().showMessage(msg)
            QMessageBox.warning(self, "No images found",
                                msg + ".\n\nThe folder must hold the plate photos themselves "
                                "(.tif, .jpg, .png or .heic), one plate per file; sub-folders "
                                "are not searched.")
            return
        key = self._mode_key()
        watershed, small = self._applied_options()
        if key == "precise" and not engine_api.precise_available()[0]:
            QMessageBox.information(self, "Precise unavailable",
                                    "Precise isn't available here; pick another engine."); return
        if key == "precise":
            QMessageBox.information(self, "Heads-up",
                                    "Precise runs the deep model on every image (~1 min each). "
                                    "For a large folder, Current is far faster.")
        self._set_busy(True); self.window().statusBar().showMessage("Batch running…")
        # only what applies to this engine is passed on (and so recorded in run_metadata.json)
        w = Worker(batch_measure.batch_measure, folder, plate_mm=self.plate.value(), mode=key,
                   watershed=watershed, crops=self.crops.isChecked(),
                   small=(small if key == "published" else False))
        w.kwargs["progress"] = w.signals.progress.emit
        w.signals.progress.connect(self.status.setText)
        w.signals.finished.connect(self._done); w.signals.error.connect(self._err)
        self.pool.start(w)

    def _set_busy(self, on):
        self._busy = bool(on)
        self.progress.setVisible(on)
        for x in (self.run_btn, self.mode, self.plate, self.crops):
            x.setEnabled(not on)
        self._sync_options()                 # the two engine-dependent boxes

    def _done(self, res):
        self._set_busy(False)
        df = res["summary_df"]
        if "error" in df.columns:
            # The Image column already names the file: show the reason alone, so it is
            # readable in the column (per_plate.csv keeps "file: reason  [path]").
            why = {e.get("image"): e.get("reason") for e in (res.get("errors") or [])}
            df = df.copy()
            df["error"] = [why.get(i) or e for i, e in zip(df["image"], df["error"])]
        self.model.set_dataframe(df)
        self.table.sortByColumn(0, Qt.AscendingOrder)     # by image name, natural order
        _fit_columns(self.table)
        self.last_out = res["out_dir"]; self.open_btn.setEnabled(True)
        n, bad = int(res["n_images"]), len(res.get("errors") or [])
        if n == 0:
            msg = "No images found in %s — nothing was measured." % self.folder.text().strip()
        else:
            msg = "%d image%s measured → %s" % (n - bad, "" if n - bad == 1 else "s", res["out_dir"])
            if bad:
                msg += ("   ⚠ %d could not be measured (see the Problem column)" % bad)
        self.status.setText(msg); self.window().statusBar().showMessage(msg)

    def _err(self, m):
        self._set_busy(False)
        QMessageBox.critical(self, "Batch failed", m[:1200])
        self.window().statusBar().showMessage("Batch failed.")

    def _open_out(self):
        if self.last_out and os.path.isdir(self.last_out):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.last_out))


# --------------------------------------------------------------------------- #
class ValidateTab(QWidget):
    """Score the engines against your hand-corrected ground-truth labels (precision/recall/F1)."""

    def __init__(self, pool):
        super().__init__()
        self.pool = pool

        self.labels = QLineEdit()
        self.labels.setPlaceholderText("Folder with labels_*.json (from Measure → Export → Ground-truth labels)…")
        browse = QPushButton("Browse…"); browse.clicked.connect(self._pick)

        self.mode_checks = {}
        modes_box = QHBoxLayout()
        for key, default in (("published", False), ("current", True), ("sensitive", False), ("precise", True)):
            label = next(l for l, k, _ in MODES if k == key)
            cb = QCheckBox(label); cb.setChecked(default); self.mode_checks[key] = cb; modes_box.addWidget(cb)
        modes_box.addStretch()
        # CT-R1 DA-F22: an engine that cannot run here is unticked and disabled, with the reason
        self._unavailable = set()
        ok, why = engine_api.precise_available()
        if not ok:
            cb = self.mode_checks["precise"]
            cb.setChecked(False); cb.setEnabled(False)
            cb.setToolTip("Precise is not available on this computer: %s" % why)
            self._unavailable.add("precise")

        self.run_btn = QPushButton(" Run validation"); self.run_btn.setObjectName("Primary")
        self.run_btn.setIcon(_icon(QStyle.SP_DialogApplyButton)); self.run_btn.clicked.connect(self._run)
        guide = QPushButton(" Validation guide"); guide.setIcon(_icon(QStyle.SP_FileDialogInfoView))
        guide.clicked.connect(lambda: _open_doc("VALIDATION_GUIDE.md"))
        self.progress = QProgressBar(); self.progress.setRange(0, 0); self.progress.setVisible(False)
        self.progress.setMaximumWidth(220)
        self.status = QLabel("First build ground truth: in Measure, correct a few plates by hand, then "
                             "Export → Ground-truth labels. Point here at that folder and score the engines.")
        self.status.setObjectName("ModeHelp"); self.status.setWordWrap(True)
        self._res = None
        self.save_btn = QPushButton("Save results (CSV)…"); self.save_btn.clicked.connect(self._save)
        self.save_btn.setToolTip("Write the per-engine and per-plate tables as two CSV files.")
        self.sentence = QLineEdit(); self.sentence.setReadOnly(True)
        self.sentence.setPlaceholderText("Run validation to get a sentence for your Methods/Results.")
        self.sent_copy = QPushButton("Copy"); self.sent_copy.clicked.connect(self._copy_sentence)
        for b in (self.save_btn, self.sent_copy):
            b.setEnabled(False)

        self.mode_table = CopyableTableView(); self.mode_model = PandasTableModel()
        self.mode_table.setModel(self.mode_model); self.mode_table.setAlternatingRowColors(True)
        self.mode_table.verticalHeader().setVisible(False); self.mode_table.horizontalHeader().setStretchLastSection(True)
        self.plate_table = CopyableTableView(); self.plate_model = PandasTableModel()
        self.pproxy = NumericSortProxy(); self.pproxy.setSourceModel(self.plate_model)
        self.plate_table.setModel(self.pproxy); self.plate_table.setSortingEnabled(True)
        self.plate_table.setAlternatingRowColors(True); self.plate_table.verticalHeader().setVisible(False)
        self.plate_table.horizontalHeader().setStretchLastSection(True)

        inputs = QGroupBox("Validation inputs")
        gl = QGridLayout(inputs); gl.setHorizontalSpacing(10); gl.setVerticalSpacing(8)
        gl.addWidget(QLabel("Labels folder"), 0, 0); gl.addWidget(self.labels, 0, 1); gl.addWidget(browse, 0, 2)
        gl.addWidget(QLabel("Engines"), 1, 0); gl.addLayout(modes_box, 1, 1)

        runrow = QHBoxLayout(); runrow.addWidget(self.run_btn); runrow.addWidget(guide)
        runrow.addStretch(); runrow.addWidget(self.progress)

        def cap(t):
            l = QLabel(t); l.setObjectName("SummaryHeading"); return l
        mcard = QFrame(); mcard.setObjectName("Card"); ml = QVBoxLayout(mcard); ml.setContentsMargins(12, 10, 12, 12)
        ml.addWidget(cap("Per-engine score — precision / recall / F1 vs your gold standard")); ml.addWidget(self.mode_table)
        pcard = QFrame(); pcard.setObjectName("Card"); pl = QVBoxLayout(pcard); pl.setContentsMargins(12, 10, 12, 12)
        pl.addWidget(cap("Per-plate detail")); pl.addWidget(self.plate_table)
        split = QSplitter(Qt.Vertical); split.addWidget(mcard); split.addWidget(pcard); split.setSizes([200, 360])
        split.setChildrenCollapsible(False)

        lay = QVBoxLayout(self); lay.setContentsMargins(14, 12, 14, 12); lay.setSpacing(10)
        srow = QHBoxLayout()
        scap = QLabel("Paste-ready sentence"); scap.setObjectName("FieldLabel")
        srow.addWidget(scap); srow.addWidget(self.sentence, 1); srow.addWidget(self.sent_copy)
        srow.addWidget(self.save_btn)
        lay.addWidget(inputs); lay.addLayout(runrow); lay.addWidget(self.status); lay.addLayout(srow)
        lay.addWidget(split, 1)

    def _pick(self):
        p = QFileDialog.getExistingDirectory(self, "Folder of ground-truth labels")
        if p:
            self.labels.setText(p)

    def _run(self):
        d = self.labels.text().strip()
        if not d or not os.path.exists(d):
            QMessageBox.warning(self, "Pick labels", "Choose the folder with your labels_*.json files."); return
        modes = tuple(k for k, cb in self.mode_checks.items() if cb.isChecked())
        if not modes:
            QMessageBox.warning(self, "Pick engines", "Tick at least one engine to score."); return
        files, skipped = validate.collect_label_files(d)
        if not files:
            QMessageBox.warning(self, "No label files",
                                "No plaque label files were found in this folder%s. Make them in "
                                "Measure: correct a plate by hand, then Export → Ground-truth labels."
                                % (" (%d other JSON file%s skipped)" % (len(skipped), "" if len(skipped) == 1 else "s")
                                   if skipped else ""))
            return
        if "precise" in modes and not engine_api.precise_available()[0]:
            QMessageBox.information(self, "Precise unavailable", "Precise isn't available here; untick it."); return
        self._set_busy(True); self.window().statusBar().showMessage("Validating…")
        w = Worker(validate.validate, d, modes=modes)
        w.kwargs["progress"] = w.signals.progress.emit
        w.signals.progress.connect(self.status.setText)
        w.signals.finished.connect(self._done); w.signals.error.connect(self._err)
        self.pool.start(w)

    def _set_busy(self, on):
        self.progress.setVisible(on)
        for x in (self.run_btn,) + tuple(cb for k, cb in self.mode_checks.items()
                                         if k not in self._unavailable):
            x.setEnabled(not on)

    def _done(self, res):
        self._set_busy(False)
        self._res = res
        self.mode_model.set_dataframe(res["per_mode_df"])
        self.plate_model.set_dataframe(res["per_plate_df"])
        self.status.setText(validate.summary_status(res) + " Higher F1 = closer to your gold "
                            "standard; see the Validation guide (Help menu) for how to report it.")
        names = {k: l for l, k, _h in MODES}
        self.sentence.setText(validate.report_sentence(res, names, __version__))
        self.save_btn.setEnabled(res["n_label_files"] > 0)
        self.sent_copy.setEnabled(bool(self.sentence.text()))
        self.window().statusBar().showMessage("Validation done.")

    def _copy_sentence(self):
        QApplication.clipboard().setText(self.sentence.text())
        self.window().statusBar().showMessage("Sentence copied to the clipboard.", 3000)

    def _save(self, path=None):
        """Per-engine + per-plate tables, as <name>_per_engine.csv and <name>_per_plate.csv."""
        if not self._res:
            return None
        if path is None:
            path, _ = QFileDialog.getSaveFileName(self, "Save validation results",
                                                  "validation_results.csv", "CSV (*.csv)")
        if not path:
            return None
        base = path[:-4] if path.lower().endswith(".csv") else path
        out = (base + "_per_engine.csv", base + "_per_plate.csv")
        try:
            self._res["per_mode_df"].to_csv(out[0], index=False, float_format="%.6g")
            self._res["per_plate_df"].to_csv(out[1], index=False, float_format="%.6g")
        except OSError as e:
            QMessageBox.warning(self, "Could not save", "Saving the results failed:\n%s" % e)
            return None
        self.window().statusBar().showMessage("Saved %s and %s" % out, 6000)
        return out

    def _err(self, m):
        self._set_busy(False)
        QMessageBox.critical(self, "Validation failed", m[:1500])
        self.window().statusBar().showMessage("Validation failed.")


# --------------------------------------------------------------------------- #
class AgreementTab(QWidget):
    """Validate the tool's sizes against a reference (Fiji/ImageJ): paste the two paired
    columns → Bland–Altman (bias + 95% limits of agreement) + ICC + r + a report sentence
    + a method-comparison figure. Pure size-agreement stats, no image needed."""

    # a clean paired DIAMETER example (both mm) so the demo shows a realistic good result
    _EX_TOOL = "1.24\n0.98\n1.51\n0.62\n1.80\n1.11\n0.75\n1.35\n2.02\n0.90\n1.44\n1.19\n0.68\n1.60\n1.05"
    _EX_FIJI = "1.27\n0.96\n1.55\n0.60\n1.84\n1.09\n0.79\n1.38\n2.05\n0.93\n1.41\n1.22\n0.71\n1.57\n1.02"

    def __init__(self):
        super().__init__()
        self._last = None
        self.canvas = None

        intro = QLabel(
            "Validate plaque size against Fiji/ImageJ. Paste the two paired columns — one value "
            "per line, the SAME plaque on each line. It computes Bland–Altman (bias + 95% limits "
            "of agreement), ICC and r, draws the figure, and writes the sentence for your paper.")
        intro.setObjectName("ModeHelp"); intro.setWordWrap(True)

        learn = QLabel('<a href="STATS_EXPLAINED.html" style="color:#0a5c43;font-weight:600;'
                       'text-decoration:none;">&#128218; New to these numbers? Read '
                       '&ldquo;Understanding the agreement statistics&rdquo; &rarr;</a>')
        learn.setTextFormat(Qt.RichText); learn.setOpenExternalLinks(False)
        learn.setToolTip("Opens a plain-language guide that explains bias, limits of agreement, "
                         "ICC and r — with the maths worked out on real numbers.")
        learn.linkActivated.connect(lambda _=None: _open_doc("STATS_EXPLAINED.html"))

        _ta_css = ("QPlainTextEdit{background:#ffffff;color:#1f2430;border:1px solid #c7ccd6;"
                   "border-radius:8px;font-family:Consolas,monospace;font-size:13px;padding:6px;}")
        self.tool_in = QPlainTextEdit(); self.tool_in.setPlaceholderText("1.24\n0.98\n1.51\n…")
        self.fiji_in = QPlainTextEdit(); self.fiji_in.setPlaceholderText("1.23\n0.79\n1.86\n…")
        for w in (self.tool_in, self.fiji_in):
            w.setMaximumHeight(150); w.setStyleSheet(_ta_css)
        tcap = QLabel("Plaque Toolkit values"); fcap = QLabel("Fiji / ImageJ values")
        for c in (tcap, fcap):
            c.setObjectName("SummaryHeading")
        tb = QVBoxLayout(); tb.addWidget(tcap); tb.addWidget(self.tool_in)
        fb = QVBoxLayout(); fb.addWidget(fcap); fb.addWidget(self.fiji_in)
        # CT-R1 DA-F7: show what was actually read (the pairs + what was skipped / chosen), so a
        # header digit or a row-number column can never shift the pairs unseen.
        from PySide6.QtWidgets import QTableWidget
        pcap = QLabel("Parsed pairs (preview)"); pcap.setObjectName("SummaryHeading")
        self.parse_notes = QLabel("Compute to see the pairs as read."); self.parse_notes.setWordWrap(True)
        self.parse_notes.setObjectName("ModeHelp")
        self.preview = QTableWidget(0, 2)
        self.preview.setHorizontalHeaderLabels(["Toolkit", "Fiji"])
        self.preview.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.preview.setMaximumHeight(150); self.preview.setMinimumWidth(220)
        self.preview.horizontalHeader().setStretchLastSection(True)
        self.preview.verticalHeader().setDefaultSectionSize(20)
        self.preview.setAccessibleName("Parsed pairs preview")
        pb = QVBoxLayout(); pb.addWidget(pcap); pb.addWidget(self.parse_notes); pb.addWidget(self.preview)
        inrow = QHBoxLayout(); inrow.addLayout(tb, 2); inrow.addLayout(fb, 2); inrow.addLayout(pb, 2)

        self.unit = QComboBox()
        self.unit.addItem("Diameter (mm)", "mm")
        self.unit.addItem("Area (mm²) — convert to diameter", "area")
        self.unit.setToolTip("What did you paste? Fiji's default is Area (mm²); choosing it converts "
                             "both columns to the area-equivalent diameter, matching the tool.")
        self.compute_btn = QPushButton("  Compute agreement  "); self.compute_btn.setObjectName("Primary")
        self.compute_btn.clicked.connect(self._compute)
        self.example_btn = QPushButton("Load example"); self.example_btn.clicked.connect(self._example)
        self.clear_btn = QPushButton("Clear"); self.clear_btn.clicked.connect(self._clear)
        optrow = QHBoxLayout()
        optrow.addWidget(QLabel("Values are:")); optrow.addWidget(self.unit); optrow.addStretch()
        optrow.addWidget(self.example_btn); optrow.addWidget(self.clear_btn); optrow.addWidget(self.compute_btn)

        self.err = QLabel(""); self.err.setWordWrap(True)
        self.err.setStyleSheet("color:%s;font-weight:600" % style.LIGHT["warn"])

        self._metrics = {}
        self.stats_card = self._build_stats_card()

        self.fig_holder = QFrame(); self.fig_holder.setObjectName("Card")
        self.fig_layout = QVBoxLayout(self.fig_holder); self.fig_layout.setContentsMargins(6, 6, 6, 6)
        self.fig_placeholder = QLabel("The method-comparison + Bland–Altman plot appears here.")
        self.fig_placeholder.setObjectName("Placeholder"); self.fig_placeholder.setAlignment(Qt.AlignCenter)
        self.fig_placeholder.setMinimumHeight(300); self.fig_layout.addWidget(self.fig_placeholder)

        rep_cap = QLabel("Report — paste into your Methods/Results"); rep_cap.setObjectName("SummaryHeading")
        self.report = QPlainTextEdit(); self.report.setReadOnly(True); self.report.setMaximumHeight(96)
        self.report.setStyleSheet("QPlainTextEdit{background:#ffffff;color:#1f2430;"
                                  "border:1px solid #c7ccd6;border-radius:8px;padding:8px;}")
        self.copy_btn = QPushButton("Copy report"); self.copy_btn.clicked.connect(self._copy)
        self.savefig_btn = QPushButton("Save figure…"); self.savefig_btn.clicked.connect(self._save_fig)
        self.savefig_btn.setToolTip("Save the figure as PNG/TIFF (high-res raster) or SVG/PDF/EPS "
                                    "(vector — open and edit in Illustrator, Inkscape or PowerPoint).")
        self.savecsv_btn = QPushButton("Save paired CSV…"); self.savecsv_btn.clicked.connect(self._save_csv)
        # CT-R1 DA-F4: the figure rule -- legend key (same formats as the figure), a legend text
        # starter with Copy, and one "place on figure" switch; all read from the CURRENT figure.
        self.key_btn = QPushButton("Legend key…"); self.key_btn.clicked.connect(self._save_key)
        self.key_btn.setToolTip("Save the figure's legend key: every point and line style with its "
                                "exact colour, in the figure's font and format.")
        self.key_cb = QCheckBox("Place key on figure"); self.key_cb.setChecked(True)
        self.key_cb.setToolTip("Draw the legend key below the two panels (the same entries as the "
                               "stand-alone key from “Legend key…”).")
        self.key_cb.toggled.connect(self._redraw)
        self.key_text = QLineEdit(); self.key_text.setReadOnly(True)
        self.key_text.setPlaceholderText("Compute to get a sentence listing every point and line style.")
        self.key_copy_btn = QPushButton("Copy"); self.key_copy_btn.clicked.connect(self._copy_key_text)
        self._fig_ext = ".png"        # the format last chosen in "Save figure…" (the key follows it)
        for b in self._result_buttons():
            b.setEnabled(False)
        rrow = QHBoxLayout(); rrow.addWidget(self.copy_btn); rrow.addWidget(self.savefig_btn)
        rrow.addWidget(self.key_btn); rrow.addWidget(self.key_cb)
        rrow.addWidget(self.savecsv_btn); rrow.addStretch()
        krow = QHBoxLayout()
        kcap = QLabel("Legend text starter"); kcap.setObjectName("FieldLabel")
        krow.addWidget(kcap); krow.addWidget(self.key_text, 1); krow.addWidget(self.key_copy_btn)

        lay = QVBoxLayout(self); lay.setContentsMargins(14, 12, 14, 12); lay.setSpacing(10)
        lay.addWidget(intro); lay.addWidget(learn); lay.addLayout(inrow); lay.addLayout(optrow); lay.addWidget(self.err)
        lay.addWidget(self.stats_card); lay.addWidget(self.fig_holder, 1)
        lay.addWidget(rep_cap); lay.addWidget(self.report); lay.addLayout(rrow); lay.addLayout(krow)

    def _build_stats_card(self):
        card = QFrame(); card.setObjectName("SummaryCard"); _shadow(card)
        grid = QGridLayout(card); grid.setContentsMargins(16, 12, 16, 12)
        grid.setHorizontalSpacing(22); grid.setVerticalSpacing(2)
        for col, key, label in [(0, "n", "n PAIRS"), (1, "bias", "MEAN BIAS"),
                                (2, "loa", "95% LIMITS"), (3, "icc", "ICC"),
                                (4, "r", "PEARSON r"), (5, "slope", "SLOPE")]:
            cap = QLabel(label); cap.setObjectName("SummaryHeading")
            val = QLabel("—"); val.setStyleSheet("font-size:19px;font-weight:700;")
            grid.addWidget(cap, 0, col); grid.addWidget(val, 1, col)
            self._metrics[key] = val
        return card

    def _compute(self):
        from app import agreement
        self.err.setText("")
        parsed = {}
        for key, box, name in (("tool", self.tool_in, "Plaque Toolkit"), ("fiji", self.fiji_in, "Fiji / ImageJ")):
            try:
                parsed[key] = agreement.parse_values(box.toPlainText())
            except ValueError as e:
                self._fail("%s box: %s" % (name, e)); return
        (tool, tnotes), (fiji, fnotes) = parsed["tool"], parsed["fiji"]
        self._show_preview(tool, fiji, tnotes, fnotes)
        if len(tool) < 3 or len(fiji) < 3:
            self._fail("Enter at least 3 paired values in each box (read %d Toolkit, %d Fiji)."
                       % (len(tool), len(fiji))); return
        if len(tool) != len(fiji):
            # CT-R1 DA-F7: refuse instead of silently pairing the first min(n) lines
            self._fail("The two boxes hold different numbers of values: %d Plaque Toolkit vs %d "
                       "Fiji / ImageJ. Each line must be the same plaque in both boxes; fix the "
                       "lists (see the preview) and compute again." % (len(tool), len(fiji)))
            return
        unit, what = "mm", "plaque diameters"
        if self.unit.currentData() == "area":
            tool, fiji = agreement.area_to_diam(tool), agreement.area_to_diam(fiji)
            what = "plaque diameters (area-equivalent)"
        try:
            # CT-R1 SM-F16/F17: the same statistics + sentence as the CLI and the web app
            s = agreement.full_stats(tool, fiji)
        except Exception as e:
            self._fail("Cannot compute agreement: %s" % e); return
        self._last = (s, unit, what)
        m = self._metrics
        m["n"].setText(str(s["n"]))
        m["bias"].setText("%+.3f" % s["bias"])
        m["loa"].setText("%+.3f…%+.3f" % (s["loa_lo"], s["loa_hi"]))
        m["loa"].setToolTip("bias ± 1.96 SD" if s["loa_method"] == "1.96 SD" else
                            "n < 20: 95%% prediction limits, bias ± t·SD·√(1+1/n) = ± %.2f SD"
                            % s["loa_mult"])
        m["icc"].setText("%.3f" % s["icc"] if s["icc"] == s["icc"] else "—")
        m["r"].setText("%.3f" % s["r"] if s["r"] == s["r"] else "—")
        m["slope"].setText("%.3f" % s["slope"] if s["slope"] == s["slope"] else "—")
        self._draw(s, unit)
        self.report.setPlainText(agreement.report_sentence(s, unit, what))
        self.report.setToolTip("ICC(A,1) 95% CI: McGraw & Wong (1996) exact F interval; "
                               "limits-of-agreement CI: Bland & Altman (1999).")
        for b in self._result_buttons():
            b.setEnabled(True)
        self.window().statusBar().showMessage("Agreement computed on %d plaque pairs." % s["n"], 4000)

    def _make_fig(self):
        """The CURRENT figure (current pairs + the 'Place key on figure' switch)."""
        from app import agreement
        s, unit, _what = self._last
        return agreement.make_figure(s, unit, show_key=self.key_cb.isChecked())

    def _draw(self, s, unit):
        from app.agreement import _lk as legend_key
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
        fig = self._make_fig()
        new = FigureCanvas(fig)
        # pin to the figure's native pixel size so the scroll area can't stretch/distort it
        w_in, h_in = fig.get_size_inches()
        new.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        new.setFixedSize(int(round(w_in * 96)), int(round(h_in * 96)))
        if self.canvas is not None:
            self.fig_layout.removeWidget(self.canvas); self.canvas.setParent(None)
        elif self.fig_placeholder is not None:
            self.fig_layout.removeWidget(self.fig_placeholder); self.fig_placeholder.setParent(None)
            self.fig_placeholder = None
        self.canvas = new
        self.fig_layout.addWidget(self.canvas, 0, Qt.AlignHCenter | Qt.AlignTop)
        # the card must hold the whole canvas: the scroll wrapper pinned this tab's minimum size
        # to its first size hint (300 px placeholder), which clipped the figure's lower half
        self.fig_holder.setMinimumHeight(self.canvas.height() + 14)
        self.setMinimumHeight(max(self.minimumHeight(), self.sizeHint().height()))
        self.canvas.draw()
        key = legend_key.from_figure(fig)
        self.key_text.setText(legend_key.text_starter(key) if key else "")

    def _redraw(self, *_):
        if self._last is not None:
            self._draw(self._last[0], self._last[1])

    _PREVIEW_ROWS = 200

    def _show_preview(self, tool, fiji, tnotes, fnotes):
        """Fill the read-only preview with the pairs as parsed (first 200) + the parse notes."""
        from PySide6.QtWidgets import QTableWidgetItem
        n = max(len(tool), len(fiji))
        shown = min(n, self._PREVIEW_ROWS)
        self.preview.setRowCount(shown)
        for i in range(shown):
            for j, seq in enumerate((tool, fiji)):
                it = QTableWidgetItem("%g" % seq[i] if i < len(seq) else "")
                it.setTextAlignment(int(Qt.AlignRight | Qt.AlignVCenter))
                self.preview.setItem(i, j, it)
        notes = ["Toolkit: " + " ".join(tnotes)] if tnotes else []
        notes += ["Fiji: " + " ".join(fnotes)] if fnotes else []
        head = "Read %d Toolkit and %d Fiji values." % (len(tool), len(fiji))
        if n > shown:
            head += " Showing the first %d rows." % shown
        self.parse_notes.setText(" ".join([head] + notes))

    def _reset_results(self):
        """CT-R1 DA-F19: no stale result may survive a failed compute or Clear -- remove the
        figure, chips, report and key text, and disable every save/copy button."""
        self._last = None
        if self.canvas is not None:
            self.fig_layout.removeWidget(self.canvas); self.canvas.setParent(None)
            self.canvas = None
        if self.fig_placeholder is None:
            self.fig_placeholder = QLabel("The method-comparison + Bland–Altman plot appears here.")
            self.fig_placeholder.setObjectName("Placeholder"); self.fig_placeholder.setAlignment(Qt.AlignCenter)
            self.fig_placeholder.setMinimumHeight(300); self.fig_layout.addWidget(self.fig_placeholder)
        for v in self._metrics.values():
            v.setText("—")
        self.report.clear()
        if hasattr(self, "key_text"):
            self.key_text.clear()
        for b in self._result_buttons():
            b.setEnabled(False)

    def _result_buttons(self):
        return [b for b in (self.copy_btn, self.savefig_btn, self.savecsv_btn,
                            getattr(self, "key_btn", None), getattr(self, "key_copy_btn", None)) if b]

    def _fail(self, msg):
        self._reset_results()
        self.err.setText(msg)

    def _example(self):
        self.tool_in.setPlainText(self._EX_TOOL); self.fiji_in.setPlaceholderText("")
        self.fiji_in.setPlainText(self._EX_FIJI)
        self.unit.setCurrentIndex(0); self._compute()

    def _clear(self):
        self.tool_in.clear(); self.fiji_in.clear(); self.err.setText("")
        self._reset_results()
        self.preview.setRowCount(0); self.parse_notes.setText("Compute to see the pairs as read.")

    def _copy(self):
        QApplication.clipboard().setText(self.report.toPlainText())
        self.window().statusBar().showMessage("Report copied to the clipboard.", 3000)

    _FIG_FILTERS = ("PNG image — 300 dpi (*.png);;"
                    "SVG — vector, editable in Illustrator/Inkscape (*.svg);;"
                    "PDF — vector, editable (*.pdf);;"
                    "TIFF — 600 dpi for journals (*.tiff);;"
                    "EPS — vector (*.eps)")
    _EXT_FOR = {"PNG": ".png", "SVG": ".svg", "PDF": ".pdf", "TIFF": ".tiff", "EPS": ".eps"}

    def _ask_path(self, title, default_stem):
        """Save dialog in the figure formats; the typed extension wins over the filter and
        dotted names keep their dots (CT-R1 DA-F20)."""
        from app import agreement
        first = next((k for k, e in self._EXT_FOR.items() if e == self._fig_ext), "PNG")
        filters = self._FIG_FILTERS.split(";;")
        sel0 = next((f for f in filters if f.startswith(first)), filters[0])
        path, sel = QFileDialog.getSaveFileName(self, title, default_stem + self._fig_ext,
                                                self._FIG_FILTERS, sel0)
        if not path:
            return None
        want = next((e for k, e in self._EXT_FOR.items() if (sel or "").startswith(k)), ".png")
        return agreement.resolve_save_path(path, want)

    @staticmethod
    def _dpi_for(ext):
        return 600 if ext in (".tif", ".tiff") else 300

    def _save_fig(self, path=None):
        if not self._last:
            return None
        from app import agreement
        path = path or self._ask_path("Save figure", "PlaqueToolkit_vs_Fiji")
        if not path:
            return None
        ext = os.path.splitext(path)[1].lower()
        dpi = self._dpi_for(ext)
        try:
            agreement.save_figure(self._make_fig(), path, dpi=dpi)
        except Exception as e:
            QMessageBox.warning(self, "Could not save figure", "Saving %s failed:\n%s" % (ext, e))
            return None
        self._fig_ext = ".tiff" if ext == ".tif" else ext
        vec = ext in (".svg", ".pdf", ".eps")
        self.window().statusBar().showMessage(
            "Figure saved (%s%s): %s" % (ext.lstrip("."),
                                         ", vector/editable" if vec else ", %d dpi" % dpi, path), 6000)
        return path

    def _save_key(self, path=None):
        """Save the legend key of the CURRENT figure, in the figure's format."""
        if not self._last:
            return None
        from app.agreement import _lk as legend_key
        path = path or self._ask_path("Save legend key", "PlaqueToolkit_vs_Fiji_legend_key")
        if not path:
            return None
        ext = os.path.splitext(path)[1].lower()
        try:
            key = legend_key.from_figure(self._make_fig())
            legend_key.save_key(key, path, dpi=self._dpi_for(ext))
        except Exception as e:
            QMessageBox.warning(self, "Could not save the legend key", "Saving %s failed:\n%s" % (ext, e))
            return None
        self.window().statusBar().showMessage("Legend key saved: %s" % path, 6000)
        return path

    def _copy_key_text(self):
        QApplication.clipboard().setText(self.key_text.text())
        self.window().statusBar().showMessage("Legend text copied to the clipboard.", 3000)

    def _save_csv(self, path=None):
        if not self._last:
            return None
        if path is None:
            path, _ = QFileDialog.getSaveFileName(self, "Save paired data", "app_vs_fiji_pairs.csv",
                                                  "CSV (*.csv)")
        if not path:
            return None
        from app import agreement
        # CT-R1 DA-F20: add .csv only when the name has no data extension (pairs_0.5x ->
        # pairs_0.5x.csv), and write 6 significant digits (not -0.030000000000000027)
        path = agreement.resolve_save_path(path, ".csv", known=(".csv", ".tsv", ".txt"))
        s = self._last[0]
        df = pd.DataFrame({"toolkit": s["tool"], "fiji": s["fiji"], "difference": s["diff"]})
        df.to_csv(path, index=False, float_format="%.6g",
                  sep="\t" if path.lower().endswith(".tsv") else ",")
        self.window().statusBar().showMessage("Saved %d pairs: %s" % (s["n"], path), 4000)
        return path


WORKER_STACK_BYTES = 16 * 1024 * 1024      # stack of the app's worker threads (CT-R1 F1)


# --------------------------------------------------------------------------- #
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Plaque Toolkit {__version__}")
        _icon_path = engine_api.resource_path("icon.png")
        if os.path.exists(_icon_path):
            self.setWindowIcon(QIcon(_icon_path))
        _av = QApplication.primaryScreen().availableGeometry()   # never open bigger than the screen
        self.resize(min(1320, _av.width() - 40), min(880, _av.height() - 60))
        self.setMinimumSize(min(760, _av.width() - 20), min(520, _av.height() - 40))
        self.pool = QThreadPool(); self.pool.setMaxThreadCount(1)  # engine flags are global
        # CT-R1 F1: macOS gives every secondary thread a 512 KB stack (the main thread has
        # 8 MB) and Qt's pool threads take that default. numpy/OpenBLAS (LAPACK inverts a
        # matrix on the stack) under matplotlib's layout code overflows it, so the Compare
        # tab died with "Bus error" on any folder that had plaques to plot. 16 MB is twice
        # the main thread's stack and is only reserved, not committed.
        self.pool.setStackSize(WORKER_STACK_BYTES)

        root = QWidget(); root.setObjectName("AppRoot")
        rlay = QVBoxLayout(root); rlay.setContentsMargins(0, 0, 0, 0); rlay.setSpacing(0)
        rlay.addWidget(self._build_header())

        self.tabs = QTabWidget()
        # every tab is wrapped in a scroll area so its content is always reachable, both
        # vertically and horizontally, on screens smaller than the content (see _scrollable).
        self.measure_tab = MeasureTab(self.pool)
        self.tabs.addTab(_scrollable(self.measure_tab, grow=False), "  Measure  ")
        self.tabs.addTab(_scrollable(BatchTab(self.pool)), "  Batch  ")
        self.tabs.addTab(_scrollable(CompareTab(self.pool)), "  Compare turbidity  ")
        self.study_tab = StudyTab(self.measure_tab)
        # grow=False so the scroll area does NOT stretch the tab (its figure pins its own size)
        self.tabs.addTab(_scrollable(self.study_tab, grow=False), "  Analyze  ")
        self.tabs.addTab(_scrollable(ValidateTab(self.pool)), "  Validate  ")
        self.tabs.addTab(_scrollable(AgreementTab()), "  Fiji agreement  ")
        self.about_tab = AboutTab()
        self._about_scroll = _scrollable(self.about_tab)
        self.tabs.addTab(self._about_scroll, "  About  ")
        rlay.addWidget(self.tabs, 1)
        self.setCentralWidget(root)
        self._build_menu()

        self.statusBar().showMessage(
            f"Ready  ·  numpy {engine_api.numpy_version()}  ·  engine: validated Plaque Size Tool")

        # keyboard shortcuts
        QShortcut(QKeySequence.Open, self, activated=self._shortcut_open)
        QShortcut(QKeySequence.Save, self, activated=self._shortcut_save)

    def _build_menu(self):
        # View — accessibility: enlarge the whole UI's text in one place
        view = self.menuBar().addMenu("&View")
        ts = view.addMenu("Text size")
        grp = QActionGroup(self); grp.setExclusive(True)
        for label, sc in (("Normal", 1.0), ("Large (120%)", 1.2), ("Larger (140%)", 1.4)):
            a = QAction(label, self, checkable=True)
            a.setChecked(abs(sc - 1.0) < 1e-3)
            a.triggered.connect(lambda _=False, s=sc: self._set_text_scale(s))
            grp.addAction(a); ts.addAction(a)

        m = self.menuBar().addMenu("&Help")
        for label, doc in (("How-to, use cases & verification", "HOWTO_AND_VERIFICATION.html"),
                           ("Understanding the agreement statistics", "STATS_EXPLAINED.html"),
                           ("Validate vs Fiji for a paper (calculator)", "FIJI_VALIDATION_PROTOCOL.html"),
                           ("Tool atlas (screenshots)", "TOOL_ATLAS.html"),
                           ("Measuring in Fiji (tutorial)", "FIJI_TUTORIAL.html"),
                           ("User guide", "USER_GUIDE.md"),
                           ("How to validate this program", "VALIDATION_GUIDE.md"),
                           ("How it was built", "HOW_IT_WAS_BUILT.md"),
                           ("Engine reference", "ENGINES.md"),
                           ("Publication notes", "PUBLICATION.md"),
                           ("Credits & lineage", "CREDITS_AND_LINEAGE.md"),
                           ("Licensing", "LICENSING.md")):
            a = QAction(label, self)
            a.triggered.connect(lambda _=False, d=doc: _open_doc(d))
            m.addAction(a)
        m.addSeparator()
        about = QAction("About Plaque Toolkit", self)
        about.triggered.connect(lambda: self.tabs.setCurrentWidget(self._about_scroll))
        m.addAction(about)

    def _set_text_scale(self, scale):
        """Re-apply the app stylesheet at a larger font scale (accessibility)."""
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(style.get_stylesheet("light", scale))
        self.statusBar().showMessage(f"Text size set to {int(round(scale * 100))}%", 3000)

    def _build_header(self):
        bar = QFrame(); bar.setObjectName("HeaderBar"); bar.setFixedHeight(64)
        hl = QHBoxLayout(bar); hl.setContentsMargins(18, 8, 18, 8)
        ic = QLabel()
        icon_path = engine_api.resource_path("icon.png")
        if os.path.exists(icon_path):
            pm = QPixmap(icon_path)
            if not pm.isNull():
                ic.setPixmap(pm.scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        tbox = QVBoxLayout(); tbox.setSpacing(0)
        title = QLabel("Plaque Toolkit"); title.setObjectName("HeaderTitle")
        sub = QLabel("“Frankenstein’s Plaque Lab” · measure plaque size & turbidity")
        sub.setObjectName("HeaderSubtitle")
        tbox.addWidget(title); tbox.addWidget(sub)
        hl.addWidget(ic); hl.addSpacing(12); hl.addLayout(tbox); hl.addStretch()
        return bar

    def _shortcut_open(self):
        if self.tabs.currentIndex() == 0:
            self.measure_tab.open_image()

    def _shortcut_save(self):
        if self.tabs.currentIndex() == 0:
            self.measure_tab.save()


def launch():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Plaque Toolkit")
    app.setStyleSheet(style.get_stylesheet("light"))
    # warm the Precise models (YOLO + classifier) in the background so the first Precise
    # run doesn't pay the cold load — runs only for the real GUI, not headless self-tests
    import threading
    threading.Thread(target=engine_api.warmup_precise, daemon=True).start()
    icon_path = engine_api.resource_path("icon.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    splash = None
    splash_path = engine_api.resource_path("splash.png")
    if os.path.exists(splash_path):
        pm = QPixmap(splash_path)
        if not pm.isNull():
            splash = QSplashScreen(pm)
            splash.show()
            # tell the user WHY the first launch is slow, so a ~30 s cold start doesn't read as a hang
            from PySide6.QtGui import QColor
            splash.showMessage("Loading the toolkit…  the first launch warms the Precise engine "
                               "(~20–40 s); later launches are fast.",
                               Qt.AlignBottom | Qt.AlignHCenter, QColor("#ffffff"))
            app.processEvents()
    win = MainWindow()
    if splash is not None:
        splash.finish(win)
    win.show()
    return app.exec()


def uitest():
    """Headless construct-the-GUI + detect self-test (exit code 0 = OK). Works windowed
    via QT_QPA_PLATFORM=offscreen, so it validates the FROZEN app without a display."""
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(style.get_stylesheet("light"))
    win = MainWindow()
    measure = win.measure_tab
    sample = engine_api.resource_path("sample.tif")
    det = engine_api.detect_single(sample, plate_mm=100)
    measure.image_path = sample
    measure.on_detected(det)
    ok = det["n_plaques"] > 0 and measure.model.rowCount() == det["n_plaques"]
    # exercise the precise availability path (must not crash, returns a (bool, reason))
    avail = engine_api.precise_available()
    ok = ok and isinstance(avail, tuple) and isinstance(avail[0], bool)
    # exercise the Fiji correspondence modules so the frozen build is gated on them too
    fiji_ok = False
    try:
        import tempfile
        from app import fiji_export, fiji_match, imagej_roi, fiji_dialog  # noqa: F401
        amf = fiji_export.app_match_frame(measure.editor.plaques, measure.editor.orig_bgr,
                                          measure.editor.plate, measure.editor.ppm)
        binfo = fiji_export.save_bundle(measure.editor.plaques, measure.editor.orig_bgr,
                                        measure.editor.plate, measure.editor.ppm,
                                        measure.editor.lawn_gray,
                                        os.path.join(tempfile.gettempdir(), "uitest_fiji"), "uitest")
        fiji_ok = (len(amf) == det["n_plaques"] and binfo["n"] == det["n_plaques"]
                   and len(imagej_roi.oval_roi(0, 0, 4, 4)) == 64
                   and os.path.exists(binfo["roiset"]))
    except Exception as e:      # pragma: no cover
        print("UITEST fiji-check error:", e)
    ok = ok and fiji_ok

    # exercise the Analyze tab end-to-end: sample containers → both modes → customize/redraw →
    # summary + comparison tables populate → export-everything ZIP → invalidation + auto-rep regressions
    study_ok = False
    try:
        import tempfile as _tmp, zipfile as _zip
        st = win.study_tab
        rng = __import__("numpy").random.default_rng(0)

        def _add_sample(group, sub, mus):
            st._samples.append({"group": group, "subgroup": sub})
            si = len(st._samples) - 1
            for mu in mus:
                d = (mu + rng.normal(0, 0.05, 40)).round(3).tolist()
                st._add_plate(si, d, [x * x for x in d])

        # single-factor: two samples, 3 replicate plates each
        _add_sample("WT", "", [0.86, 0.90, 0.94])
        _add_sample("mut", "", [1.16, 1.20, 1.24])
        st._refresh_tree(); st.metric_sel.setCurrentIndex(0)
        st._analyse()
        single_ok = (st._last is not None and st._last[0] == "single" and st._last_fig is not None
                     and st.tbl_group.model().rowCount() >= 2 and st.tbl_cmp.model().rowCount() >= 1)
        # customize + live redraw must not crash and must keep a figure
        st.palette_sel.setCurrentIndex(1); st.center_sel.setCurrentIndex(1)  # Set2 + median
        st.error_sel.setCurrentIndex(2); st.alpha.setValue(0.8); st._redraw()
        redraw_ok = st._last_fig is not None
        # export everything → non-empty ZIP with report + run_config + a figure
        zpath = os.path.join(_tmp.gettempdir(), "uitest_analyze.zip")
        st._write_everything(zpath)
        names = _zip.ZipFile(zpath).namelist()
        zip_ok = (os.path.getsize(zpath) > 0
                  and any(n.startswith("report_") and n.endswith(".md") for n in names)
                  and any(n.startswith("run_config_") for n in names)
                  and any(n.endswith(".png") for n in names))

        # grouped control-comparison: samples that share a name but differ by 2nd factor
        st._samples = []; st._plates = []
        _add_sample("WT", "ctrl", [1.0, 1.02, 0.98])
        _add_sample("WT", "treat", [0.80, 0.82, 0.78])
        _add_sample("mut", "ctrl", [1.0, 1.01, 0.99])
        _add_sample("mut", "treat", [0.95, 0.97, 0.93])
        st._refresh_tree(); st.control_sel.setCurrentText("ctrl")
        st._analyse()
        grouped_ok = (st._last is not None and st._last[0] == "grouped" and st._last_fig is not None
                      and st.tbl_cmp.model().rowCount() >= 1)
        # regression: mutating the samples invalidates a prior analysis (no stale figure/exports)
        st._refresh_tree()
        inval_ok = st._last is None and st._last_fig is None and not st.savefig_btn.isEnabled()
        # regression: auto replicate ids stay unique within a sample even after a Load-study restore
        st._samples = [{"group": "WT", "subgroup": ""}]
        st._plates = [{"group": "WT", "subgroup": "", "replicate": "plate%d" % i,
                       "diam": [0.4, 0.5], "area": []} for i in (1, 2, 3)]
        st._add_plate(0, [0.4, 0.5], [])
        rep_ok = st._plates[-1]["replicate"] == "plate4"
        study_ok = bool(single_ok and redraw_ok and zip_ok and grouped_ok and inval_ok and rep_ok)
    except Exception as e:      # pragma: no cover
        import traceback; print("UITEST study-check error:", e); traceback.print_exc()
    ok = ok and study_ok

    print("UITEST", "OK" if ok else "FAIL", "| rows", measure.model.rowCount(),
          "| precise_available", avail[0], "| fiji", fiji_ok, "| study", study_ok)
    return 0 if ok else 1
