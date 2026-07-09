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
from PySide6.QtCore import Qt, QThreadPool, QTimer, QItemSelectionModel
from PySide6.QtGui import (QPixmap, QIcon, QKeySequence, QShortcut, QAction, QDesktopServices,
                           QFont, QActionGroup)
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QFileDialog, QDoubleSpinBox, QCheckBox, QTableView, QSplitter,
    QLineEdit, QGroupBox, QScrollArea, QMessageBox, QSplashScreen, QComboBox,
    QFrame, QProgressBar, QStyle, QMenu, QAbstractItemView, QPlainTextEdit)

from app import __version__, engine_api, style, batch_measure, validate
from app.workers import Worker
from app.widgets import PandasTableModel, NumericSortProxy, CopyableTableView
from app.plaque_canvas import PlaqueCanvas

IMG_FILTER = "Images (*.tif *.tiff *.jpg *.jpeg *.png *.heic *.heif)"
IMG_EXTS = (".tif", ".tiff", ".jpg", ".jpeg", ".png", ".heic", ".heif")

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
        self.plate_85.clicked.connect(lambda: self.plate.setValue(85))
        self.plate_100 = QPushButton("100 mm")
        self.plate_100.setToolTip("Quick-set 100 mm — the nominal lid diameter.")
        self.plate_100.clicked.connect(lambda: self.plate.setValue(100))
        # changing the dish size (typing OR the 85/100 buttons) live-re-scales the current image
        self.plate.valueChanged.connect(self._on_dish_value_changed)

        # image orientation — rotate / flip the plate (e.g. to match your Fiji hand-labelling)
        self._cur_img = None       # current (oriented) BGR array
        self._detect_src = None    # path detection runs on (an oriented temp; None => image_path)
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
        self.mode.setToolTip("Detection engine / mode. Hover an option or read the line below.")
        self.mode.currentIndexChanged.connect(self._mode_changed)

        self.watershed = QCheckBox("Split touching plaques")
        self.watershed.setToolTip("Watershed segmentation to separate plaques whose edges touch. "
                                  "Helpful on crowded plates; ignored under Published mode.")

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
        pl = QHBoxLayout(params_box); pl.setSpacing(10)
        pl.addWidget(QLabel("Dish")); pl.addWidget(self.plate)
        pl.addWidget(self.plate_85); pl.addWidget(self.plate_100)
        sep = QFrame(); sep.setFrameShape(QFrame.VLine); sep.setStyleSheet("color:#d6dbe5")
        pl.addSpacing(4); pl.addWidget(sep); pl.addSpacing(4)
        pl.addWidget(QLabel("Engine")); pl.addWidget(self.mode)
        pl.addWidget(self.watershed); pl.addWidget(self.exclude_overlaps)
        sep2 = QFrame(); sep2.setFrameShape(QFrame.VLine); sep2.setStyleSheet("color:#d6dbe5")
        pl.addSpacing(4); pl.addWidget(sep2); pl.addSpacing(4)
        pl.addWidget(self.orient_btn)
        pl.addStretch()
        pl.addWidget(self.open_btn); pl.addWidget(self.redetect_btn); pl.addWidget(self.save_btn)

        # mode helper + progress strip
        self.mode_help = QLabel(MODES[self._def_mode][2]); self.mode_help.setObjectName("ModeHelp")
        self.mode_help.setWordWrap(True)
        self.progress = QProgressBar(); self.progress.setRange(0, 0)   # indeterminate
        self.progress.setVisible(False); self.progress.setMaximumWidth(220)
        self.busy_label = QLabel(""); self.busy_label.setObjectName("ModeHelp")
        strip = QHBoxLayout(); strip.setContentsMargins(2, 0, 2, 0)
        strip.addWidget(self.mode_help, 1)
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
        self.placeholder.setMinimumHeight(360)
        self.placeholder.setStyleSheet(
            "border:2px dashed #c2c9d6; border-radius:14px; color:#6b7484; "
            "font-size:15px; background:#fbfcfe;")
        self.canvas_layout.addWidget(self.placeholder)

        # ---- right panel: summary card + table ----------------------------- #
        self.summary_card = self._build_summary_card()

        self.table = CopyableTableView()
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

        lay = QVBoxLayout(self); lay.setContentsMargins(14, 12, 14, 12); lay.setSpacing(10)
        lay.addWidget(params_box)
        lay.addLayout(strip)
        lay.addWidget(split, 1)

        self._apply_a11y()

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

        self._metrics = {}
        metric(0, "count", "PLAQUES")
        metric(1, "median", "MEDIAN Ø (mm)")
        metric(2, "mean", "MEAN Ø (mm)")
        metric(3, "cal", "CALIBRATION")
        self.flag_label = QLabel("")
        self.flag_label.setWordWrap(True)
        self.flag_label.setStyleSheet("font-size:12px; font-weight:600;")
        grid.addWidget(self.flag_label, 2, 0, 1, 4)
        return card

    def _set_summary(self, n=None, median=None, mean=None, cal=None, flag=None, mode=None):
        self._metrics["count"].setText("—" if n is None else str(n))
        self._metrics["median"].setText("—" if median is None else f"{median:.2f}")
        self._metrics["mean"].setText("—" if mean is None else f"{mean:.2f}")
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
        self.watershed.setEnabled(key not in ("published",))

    def _on_dish_value_changed(self, val):
        """Live-recalibrate the current image when the dish size changes (typing or the 85/100
        quick-picks): re-scales the already-detected dish, so all mm sizes + the calibration
        update immediately. Before an image is loaded it's a no-op (the value applies at detect)."""
        if self.busy or self.editor is None:
            return
        self.editor.set_plate_mm(val)

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
                self.image_path = p
                self._cur_img = None; self._detect_src = None
                self._detect()               # loads/replaces the current image
                e.acceptProposedAction()
                return
        e.ignore()

    # -- actions ------------------------------------------------------------ #
    def open_image(self):
        if self.busy:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Select a plaque image", "", IMG_FILTER)
        if not path:
            return
        self.image_path = path
        self._cur_img = None; self._detect_src = None   # fresh image → identity orientation
        self._detect()

    def redetect(self):
        if self.image_path and not self.busy:
            self._detect()

    def _orient(self, op):
        """Rotate/flip the loaded plate and re-detect on the new orientation, so the image,
        coordinates and any exported labels all match (e.g. your Fiji hand-labelling). Outputs
        stay named/saved next to the original image."""
        if self.busy or self.image_path is None:
            return
        if self.editor is not None and any(p.get("source") == "manual" for p in self.editor.plaques):
            if QMessageBox.question(
                    self, "Re-orient plate",
                    "Rotating/flipping re-runs detection and discards your manual edits.\n"
                    "Best to orient the plate first, then label. Continue?",
                    QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
                return
        try:
            if self._cur_img is None:
                self._cur_img = engine_api.read_image(self.image_path)
            self._cur_img = engine_api.rotate_flip(self._cur_img, op)
            stem = os.path.splitext(os.path.basename(self.image_path))[0]
            tmp = os.path.join(tempfile.gettempdir(), "plaquetk_oriented_" + stem + ".png")
            engine_api.write_image(tmp, self._cur_img)
            self._detect_src = tmp
        except Exception as e:
            QMessageBox.warning(self, "Orientation failed", str(e))
            return
        self._detect()

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

    def _detect(self):
        key = self._mode_key()
        name = os.path.basename(self.image_path)
        if key == "precise":
            self._detect_precise(name)
            return
        self._start_busy(_BUSY_STD)
        self.window().statusBar().showMessage(f"Detecting ({MODES[self.mode.currentIndex()][0]})…")
        kw = dict(plate_mm=self.plate.value(), watershed=self.watershed.isChecked())
        if key == "published":
            kw["published"] = True
        elif key == "sensitive":
            kw["small"] = True; kw["sensitive"] = True
        else:  # current
            kw["small"] = True
        w = Worker(engine_api.detect_single, self._detect_src or self.image_path, **kw)
        w.signals.finished.connect(self.on_detected)
        w.signals.error.connect(self.on_error)
        self.pool.start(w)

    def _detect_precise(self, name):
        ok, reason = engine_api.precise_available()
        if not ok:
            QMessageBox.information(
                self, "Precise engine unavailable",
                "Precise mode needs a second environment (PlaqSeg / PyTorch) and the model "
                "weights, which are not installed on this machine:\n\n" + reason +
                "\n\nFalling back is easy — pick Published, Current or Sensitive above.")
            self.window().statusBar().showMessage("Precise unavailable — pick another mode.")
            return
        self._start_busy(_BUSY_PRECISE)
        self.window().statusBar().showMessage("Precise pipeline running (this can take a minute)…")
        w = Worker(engine_api.detect_precise, self._detect_src or self.image_path,
                   plate_mm=self.plate.value())
        w.signals.finished.connect(self.on_precise_detected)
        w.signals.error.connect(self.on_precise_error)
        self.pool.start(w)

    def _mount_editor(self):
        if self.editor is not None:
            self.editor.setParent(None)
        else:
            self.placeholder.setParent(None)
        self.editor = PlaqueCanvas(self.det, self.image_path,
                                   os.path.join(os.path.dirname(self.image_path), "out"),
                                   on_change=self.refresh_table,
                                   face=style.LIGHT["surface"])
        self.editor.selection_changed.connect(self._on_canvas_selection)
        self.canvas_layout.addWidget(self.editor)

    def on_detected(self, det):
        self.det = det
        self._mount_editor()
        self._set_busy(False)
        self.refresh_table()
        self._set_image_info()
        label = MODES[self.mode.currentIndex()][0]
        self.window().statusBar().showMessage(f"{det['n_plaques']} plaques detected · {label}")

    def on_precise_detected(self, det):
        self.det = det
        self._mount_editor()
        self._set_busy(False)
        # plaques are now the editable Precise detections -> normal table path
        self.refresh_table()
        self._set_image_info()
        n = det["n_plaques"]
        self.window().statusBar().showMessage(f"{n} plaques (Precise · PST+PlaqSeg)")

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
        df = engine_api.measure_table(self.editor.plaques, det["orig_bgr"],
                                      det["pxl_per_mm"], det["lawn_gray"])
        self._set_table_df(df)
        n = len(df)
        stats_df = df
        if self.exclude_overlaps.isChecked() and "OVERLAP" in df.columns:
            stats_df = df[df["OVERLAP"] != "yes"]
        n_excl = n - len(stats_df)
        if n_excl:
            ov_msg = f"↔ {n_excl} overlapping plaque(s) excluded from the stats."
            flag = (flag + "  " + ov_msg) if flag else ov_msg
        dm = pd.to_numeric(stats_df["DIAMETER_MM"], errors="coerce").dropna()
        cal = det["pxl_per_mm"]
        self._set_summary(
            n=n,
            median=(dm.median() if len(dm) else None),
            mean=(dm.mean() if len(dm) else None),
            cal=cal, flag=flag)

    # -- canvas <-> table selection link ------------------------------------ #
    def _set_table_df(self, df):
        """Refresh the table without letting the model-reset wipe the canvas selection,
        then re-mirror the canvas selection into the fresh rows."""
        self._syncing = True
        try:
            self.model.set_dataframe(df)
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
                self.sel_readout.setText(
                    f"Selected  #{row['INDEX']}  ·  Ø {row['DIAMETER_MM']} mm  ·  area {row['AREA_MM2']} mm²"
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
                                             self.editor.plate, self.editor.ppm)
        dlg = fiji_dialog.FijiCompareDialog(app_df, calibrated=bool(self.editor.ppm), parent=self)
        dlg.exec()

    def save(self):
        if self.editor is None:
            return
        try:
            self.editor.save()
            out_dir = os.path.join(os.path.dirname(self.image_path), "out")
            self.window().statusBar().showMessage(f"Saved to {out_dir}")
            QMessageBox.information(self, "Saved", f"Results written to:\n{out_dir}")
        except Exception as e:
            QMessageBox.critical(self, "Save failed", str(e))

    def on_error(self, msg):
        self._set_busy(False)
        self.placeholder.setText("Detection failed. Try another image or mode.")
        self.window().statusBar().showMessage("Detection failed.")
        QMessageBox.critical(self, "Detection failed", msg[:1000])

    def on_precise_error(self, msg):
        self._set_busy(False)
        self.placeholder.setText("Precise detection unavailable.")
        self.window().statusBar().showMessage("Precise unavailable — pick another mode.")
        QMessageBox.information(self, "Precise engine unavailable", msg[:1200])


# --------------------------------------------------------------------------- #
class CompareTab(QWidget):
    def __init__(self, pool):
        super().__init__()
        self.pool = pool

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
        self.volume = QLineEdit(); self.volume.setPlaceholderText("plated volume µL")

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
        self.progress = QProgressBar(); self.progress.setRange(0, 0); self.progress.setVisible(False)
        self.progress.setMaximumWidth(220)
        runrow = QHBoxLayout(); runrow.addWidget(self.run_btn); runrow.addStretch()
        runrow.addWidget(self.progress)

        self.qc = QLabel("—"); self.qc.setWordWrap(True); self.qc.setObjectName("ModeHelp")
        self.table = CopyableTableView(); self.model = PandasTableModel()
        self.proxy = NumericSortProxy(); self.proxy.setSourceModel(self.model)
        self.table.setModel(self.proxy); self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)

        self.figs = QWidget(); self.figs_layout = QVBoxLayout(self.figs)
        self.figs_placeholder = QLabel(
            "Comparison figures will appear here after a run\n"
            "(per-phage bars, diameter histograms).")
        self.figs_placeholder.setObjectName("Placeholder")
        self.figs_placeholder.setAlignment(Qt.AlignCenter)
        self.figs_layout.addWidget(self.figs_placeholder)
        self.figs_layout.addStretch()
        figscroll = QScrollArea(); figscroll.setWidgetResizable(True); figscroll.setWidget(self.figs)
        figscroll.setFrameShape(QFrame.NoFrame)

        left = QFrame(); left.setObjectName("Card")
        ll = QVBoxLayout(left); ll.setContentsMargins(12, 10, 12, 12)
        cap = QLabel("Per-phage summary"); cap.setObjectName("SummaryHeading")
        ll.addWidget(cap); ll.addWidget(self.table); ll.addWidget(self.qc)
        right = QFrame(); right.setObjectName("Card")
        rl = QVBoxLayout(right); rl.setContentsMargins(8, 8, 8, 8)
        rl.addWidget(figscroll)

        results = QSplitter()
        results.addWidget(left); results.addWidget(right)
        results.setSizes([520, 560]); results.setChildrenCollapsible(False)

        inputs_box = QGroupBox("Inputs")
        ib = QVBoxLayout(inputs_box)
        for r in (self.folder, self.blank, self.flat):
            ib.addLayout(r["row"])

        lay = QVBoxLayout(self); lay.setContentsMargins(14, 12, 14, 12); lay.setSpacing(10)
        lay.addWidget(inputs_box)
        lay.addWidget(opts_box)
        lay.addLayout(runrow)
        lay.addWidget(results, 1)

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

    def run(self):
        directory = self.folder["edit"].text().strip()
        if not directory or not os.path.isdir(directory):
            QMessageBox.warning(self, "Pick a folder", "Choose a folder of phage plate images.")
            return
        out_dir = os.path.join(directory, "out_turbidity")
        kw = dict(plate_mm=self.plate.value(), small=self.small.isChecked(),
                  blank=self.blank["edit"].text().strip() or None,
                  flat=self.flat["edit"].text().strip() or None,
                  core=self.core.value(), group_by_prefix=self.group.isChecked(),
                  watershed=self.watershed.isChecked(), out_dir=out_dir)
        try:
            if self.dilution.text().strip():
                kw["dilution"] = float(self.dilution.text())
            if self.volume.text().strip():
                kw["volume_ul"] = float(self.volume.text())
        except ValueError:
            QMessageBox.warning(self, "Titer", "Dilution and volume must be numbers."); return
        self.run_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.window().statusBar().showMessage("Running batch comparison…")
        w = Worker(engine_api.run_compare, directory, **kw)
        w.signals.finished.connect(self.on_done)
        w.signals.error.connect(self.on_error)
        self.pool.start(w)

    def on_done(self, res):
        self.run_btn.setEnabled(True)
        self.progress.setVisible(False)
        out_dir = res["out_dir"]
        per = os.path.join(out_dir, "per_phage.csv")
        if os.path.exists(per):
            self.model.set_dataframe(pd.read_csv(per))
        qcp = os.path.join(out_dir, "qc.csv")
        if os.path.exists(qcp):
            q = pd.read_csv(qcp)
            bad = []
            if "POLARITY_OK" in q: bad += list(q.loc[q["POLARITY_OK"] == False, "PLATE"].astype(str))
            nod = list(q.loc[~q["DISH_FOUND"], "PLATE"].astype(str)) if "DISH_FOUND" in q else []
            note = f"{len(q)} plates analysed."
            if nod: note += f"  ⚠ no dish: {', '.join(nod)}"
            if bad: note += f"  ⚠ polarity fail (check imaging): {', '.join(bad)}"
            if not (nod or bad): note += "  ✓ QC passed (dish + polarity)."
            self.qc.setText(note)
        while self.figs_layout.count():
            item = self.figs_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        import glob
        for png in sorted(glob.glob(os.path.join(out_dir, "compare_*.png"))) + \
                   sorted(glob.glob(os.path.join(out_dir, "hist_*.png"))):
            lbl = QLabel(); pm = QPixmap(png)
            if not pm.isNull():
                lbl.setPixmap(pm.scaledToWidth(520, Qt.SmoothTransformation))
            self.figs_layout.addWidget(lbl)
        self.figs_layout.addStretch()
        self.window().statusBar().showMessage(f"Done → {out_dir}")

    def on_error(self, msg):
        self.run_btn.setEnabled(True)
        self.progress.setVisible(False)
        self.window().statusBar().showMessage("Batch failed.")
        QMessageBox.critical(self, "Batch failed", msg[:1000])


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

            "<p><b>The tabs</b></p><ul>"
            "<li><b>Measure</b> — open one image, auto-detect, correct by hand, read size + turbidity, export.</li>"
            "<li><b>Batch</b> — a whole folder → one CSV per plate + an all-plaques CSV + annotated images. "
            "(Drop a folder onto the tab.)</li>"
            "<li><b>Compare turbidity</b> — a folder of phages → optical density, clarity class, titer/PFU, "
            "per-phage stats + figures.</li>"
            "<li><b>Validate</b> — score the engines against your own hand-corrected labels "
            "(precision / recall / F1 + size agreement).</li></ul>"

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

            "<p style='color:#6b7484'>Full guides live in the <b>Help</b> menu (User guide, interactive guide, "
            "validation, how it was built).</p>")
        body.setObjectName("AboutBody"); body.setWordWrap(True); body.setOpenExternalLinks(True)
        body.setTextInteractionFlags(Qt.TextBrowserInteraction)
        lay.addWidget(body)

        holder = QWidget(); hl = QVBoxLayout(holder); hl.setContentsMargins(0, 0, 0, 0)
        hl.addWidget(card, 0, Qt.AlignHCenter | Qt.AlignTop); hl.addStretch()
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(holder)
        outer.addWidget(scroll)


def _open_doc(name):
    """Open a docs/ file with the system default viewer (works from source and frozen)."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if getattr(sys, "frozen", False):
        root = getattr(sys, "_MEIPASS", root)
    path = os.path.join(root, "docs", name)
    if not os.path.exists(path):
        path = os.path.join(root, name)
    if os.path.exists(path):
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))
    else:
        QMessageBox.information(None, "Document not found",
                                f"Could not find {name}. It ships in the docs/ folder.")


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
        self.watershed.setToolTip("Watershed segmentation to separate plaques whose edges touch.")
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

        self.table = CopyableTableView(); self.model = PandasTableModel()
        self.proxy = NumericSortProxy(); self.proxy.setSourceModel(self.model)
        self.table.setModel(self.proxy); self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True); self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)

        inputs = QGroupBox("Batch inputs")
        gl = QGridLayout(inputs); gl.setHorizontalSpacing(10); gl.setVerticalSpacing(8)
        gl.addWidget(QLabel("Folder"), 0, 0); gl.addWidget(self.folder, 0, 1); gl.addWidget(browse, 0, 2)
        gl.addWidget(QLabel("Dish"), 1, 0); gl.addWidget(self.plate, 1, 1)
        opt = QHBoxLayout(); opt.addWidget(QLabel("Engine")); opt.addWidget(self.mode)
        opt.addWidget(self.watershed); opt.addStretch()
        gl.addLayout(opt, 2, 1)
        gl.addWidget(self.crops, 3, 1)

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

    def _run(self):
        folder = self.folder.text().strip()
        if not folder or not os.path.isdir(folder):
            QMessageBox.warning(self, "Pick a folder", "Choose a folder of plate images."); return
        key = MODES[self.mode.currentIndex()][1]
        if key == "precise" and not engine_api.precise_available()[0]:
            QMessageBox.information(self, "Precise unavailable",
                                    "Precise isn't available here; pick another engine."); return
        if key == "precise":
            QMessageBox.information(self, "Heads-up",
                                    "Precise runs the deep model on every image (~1 min each). "
                                    "For a large folder, Current is far faster.")
        self._set_busy(True); self.window().statusBar().showMessage("Batch running…")
        w = Worker(batch_measure.batch_measure, folder, plate_mm=self.plate.value(), mode=key,
                   watershed=self.watershed.isChecked(), crops=self.crops.isChecked())
        w.kwargs["progress"] = w.signals.progress.emit
        w.signals.progress.connect(self.status.setText)
        w.signals.finished.connect(self._done); w.signals.error.connect(self._err)
        self.pool.start(w)

    def _set_busy(self, on):
        self.progress.setVisible(on)
        for x in (self.run_btn, self.mode, self.plate, self.watershed, self.crops):
            x.setEnabled(not on)

    def _done(self, res):
        self._set_busy(False)
        self.model.set_dataframe(res["summary_df"])
        self.last_out = res["out_dir"]; self.open_btn.setEnabled(True)
        msg = f"{res['n_images']} images → {res['out_dir']}"
        if res.get("errors"):
            msg += f"   ⚠ {len(res['errors'])} failed"
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

        self.run_btn = QPushButton(" Run validation"); self.run_btn.setObjectName("Primary")
        self.run_btn.setIcon(_icon(QStyle.SP_DialogApplyButton)); self.run_btn.clicked.connect(self._run)
        guide = QPushButton(" Validation guide"); guide.setIcon(_icon(QStyle.SP_FileDialogInfoView))
        guide.clicked.connect(lambda: _open_doc("VALIDATION_GUIDE.md"))
        self.progress = QProgressBar(); self.progress.setRange(0, 0); self.progress.setVisible(False)
        self.progress.setMaximumWidth(220)
        self.status = QLabel("First build ground truth: in Measure, correct a few plates by hand, then "
                             "Export → Ground-truth labels. Point here at that folder and score the engines.")
        self.status.setObjectName("ModeHelp"); self.status.setWordWrap(True)

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
        lay.addWidget(inputs); lay.addLayout(runrow); lay.addWidget(self.status); lay.addWidget(split, 1)

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
        for x in (self.run_btn,) + tuple(self.mode_checks.values()):
            x.setEnabled(not on)

    def _done(self, res):
        self._set_busy(False)
        self.mode_model.set_dataframe(res["per_mode_df"])
        self.plate_model.set_dataframe(res["per_plate_df"])
        n = len(res["per_plate_df"])
        self.status.setText(f"Scored {n} (plate × engine) results. Higher F1 = closer to your gold "
                            "standard. See the Validation guide (Help menu) for how to report this.")
        self.window().statusBar().showMessage("Validation done.")

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
        inrow = QHBoxLayout(); inrow.addLayout(tb); inrow.addLayout(fb)

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
        self.savecsv_btn = QPushButton("Save paired CSV…"); self.savecsv_btn.clicked.connect(self._save_csv)
        for b in (self.copy_btn, self.savefig_btn, self.savecsv_btn):
            b.setEnabled(False)
        rrow = QHBoxLayout(); rrow.addWidget(self.copy_btn); rrow.addWidget(self.savefig_btn)
        rrow.addWidget(self.savecsv_btn); rrow.addStretch()

        lay = QVBoxLayout(self); lay.setContentsMargins(14, 12, 14, 12); lay.setSpacing(10)
        lay.addWidget(intro); lay.addWidget(learn); lay.addLayout(inrow); lay.addLayout(optrow); lay.addWidget(self.err)
        lay.addWidget(self.stats_card); lay.addWidget(self.fig_holder, 1)
        lay.addWidget(rep_cap); lay.addWidget(self.report); lay.addLayout(rrow)

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
        tool = agreement.parse_column(self.tool_in.toPlainText())
        fiji = agreement.parse_column(self.fiji_in.toPlainText())
        if len(tool) < 3 or len(fiji) < 3:
            self.err.setText("Enter at least 3 paired values in each box."); return
        if len(tool) != len(fiji):
            self.err.setText("Unequal counts: %d Toolkit vs %d Fiji — using the first %d pairs; "
                             "check the rows line up (same plaque per line)."
                             % (len(tool), len(fiji), min(len(tool), len(fiji))))
        unit, what = "mm", "diameters"
        if self.unit.currentData() == "area":
            tool, fiji = agreement.area_to_diam(tool), agreement.area_to_diam(fiji)
            what = "diameters (area-equivalent)"
        try:
            s = agreement.compute(tool, fiji)
        except Exception as e:
            self.err.setText(str(e)); return
        self._last = (s, unit, what)
        m = self._metrics
        m["n"].setText(str(s["n"]))
        m["bias"].setText("%+.3f" % s["bias"])
        m["loa"].setText("%+.2f…%+.2f" % (s["loa_lo"], s["loa_hi"]))
        m["icc"].setText("%.3f" % s["icc"] if s["icc"] == s["icc"] else "—")
        m["r"].setText("%.3f" % s["r"] if s["r"] == s["r"] else "—")
        m["slope"].setText("%.3f" % s["slope"] if s["slope"] == s["slope"] else "—")
        self._draw(s, unit)
        self.report.setPlainText(agreement.report_sentence(s, unit, what))
        for b in (self.copy_btn, self.savefig_btn, self.savecsv_btn):
            b.setEnabled(True)
        self.window().statusBar().showMessage("Agreement computed on %d plaque pairs." % s["n"], 4000)

    def _draw(self, s, unit):
        from app import agreement
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
        fig = agreement.make_figure(s, unit)
        new = FigureCanvas(fig)
        if self.canvas is not None:
            self.fig_layout.removeWidget(self.canvas); self.canvas.setParent(None)
        elif self.fig_placeholder is not None:
            self.fig_layout.removeWidget(self.fig_placeholder); self.fig_placeholder.setParent(None)
            self.fig_placeholder = None
        self.canvas = new; self.fig_layout.addWidget(self.canvas); self.canvas.draw()

    def _example(self):
        self.tool_in.setPlainText(self._EX_TOOL); self.fiji_in.setPlaceholderText("")
        self.fiji_in.setPlainText(self._EX_FIJI)
        self.unit.setCurrentIndex(0); self._compute()

    def _clear(self):
        self.tool_in.clear(); self.fiji_in.clear(); self.report.clear(); self.err.setText("")
        for v in self._metrics.values():
            v.setText("—")
        for b in (self.copy_btn, self.savefig_btn, self.savecsv_btn):
            b.setEnabled(False)

    def _copy(self):
        QApplication.clipboard().setText(self.report.toPlainText())
        self.window().statusBar().showMessage("Report copied to the clipboard.", 3000)

    def _save_fig(self):
        if not self._last:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save figure", "PlaqueToolkit_vs_Fiji.png",
                                              "PNG image (*.png);;PDF (*.pdf)")
        if path:
            from app import agreement
            agreement.make_figure(self._last[0], self._last[1]).savefig(path, dpi=200, bbox_inches="tight")
            self.window().statusBar().showMessage("Figure saved: %s" % path, 4000)

    def _save_csv(self):
        if not self._last:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save paired data", "app_vs_fiji_pairs.csv", "CSV (*.csv)")
        if path:
            s = self._last[0]
            df = pd.DataFrame({"toolkit": s["tool"], "fiji": s["fiji"], "difference": s["diff"]})
            df.to_csv(path, index=False)
            self.window().statusBar().showMessage("Saved %d pairs: %s" % (s["n"], path), 4000)


# --------------------------------------------------------------------------- #
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Plaque Toolkit {__version__}")
        _icon_path = engine_api.resource_path("icon.png")
        if os.path.exists(_icon_path):
            self.setWindowIcon(QIcon(_icon_path))
        self.resize(1240, 800)
        self.pool = QThreadPool(); self.pool.setMaxThreadCount(1)  # engine flags are global

        root = QWidget(); root.setObjectName("AppRoot")
        rlay = QVBoxLayout(root); rlay.setContentsMargins(0, 0, 0, 0); rlay.setSpacing(0)
        rlay.addWidget(self._build_header())

        self.tabs = QTabWidget()
        self.measure_tab = MeasureTab(self.pool)
        self.tabs.addTab(self.measure_tab, "  Measure  ")
        self.tabs.addTab(BatchTab(self.pool), "  Batch  ")
        self.tabs.addTab(CompareTab(self.pool), "  Compare turbidity  ")
        self.tabs.addTab(ValidateTab(self.pool), "  Validate  ")
        self.tabs.addTab(AgreementTab(), "  Fiji agreement  ")
        self.about_tab = AboutTab()
        self.tabs.addTab(self.about_tab, "  About  ")
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
                           ("Publication notes", "PUBLICATION.md")):
            a = QAction(label, self)
            a.triggered.connect(lambda _=False, d=doc: _open_doc(d))
            m.addAction(a)
        m.addSeparator()
        about = QAction("About Plaque Toolkit", self)
        about.triggered.connect(lambda: self.tabs.setCurrentWidget(self.about_tab))
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
    print("UITEST", "OK" if ok else "FAIL", "| rows", measure.model.rowCount(),
          "| precise_available", avail[0], "| fiji", fiji_ok)
    return 0 if ok else 1
