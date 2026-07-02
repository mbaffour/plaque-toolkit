"""Native-Qt interactive plaque editor (QGraphicsView).

Reliable mouse handling, smooth wheel/button zoom + drag-pan, a rubber-band
"detect in this area" tool, click-to-toggle and box select/deselect, click-to-add /
click-to-erase, a draggable + length-selectable scale bar, and exports (per-plaque
CSV, annotated figure, ground-truth labels) so hand-corrected plates can drive
validation and training.

Public surface kept compatible with the old EditorWidget so app/ui.py needs only
a one-line swap:
    .plaques                        -> the live list of plaque dicts (same schema)
    .save()                         -> write annotated image + CSV (engine save)
    .export_groundtruth(path=None)  -> write per-plaque labels (x, y, r, mm, source)

Plaque dict schema (unchanged from plaque_gui), plus a private "_uid" the editor
adds for stable selection across edits (ignored by the engine/save/table code):
    {source: auto|manual|region|watershed, kind: contour|circle,
     center: (x,y), area_pxl: float, contour|radius: ...}
"""
import os
import math
import json

import numpy as np
import cv2
import pandas as pd

from PySide6.QtCore import Qt, QRectF, QPointF, QRect, QSize, QPoint
from PySide6.QtGui import QImage, QPixmap, QPen, QBrush, QColor, QPainter, QPolygonF, QFont
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLayout, QSizePolicy, QGraphicsView,
    QGraphicsScene, QGraphicsItem, QGraphicsEllipseItem, QGraphicsRectItem, QGraphicsPolygonItem,
    QGraphicsLineItem, QGraphicsSimpleTextItem, QPushButton, QButtonGroup, QLabel,
    QComboBox, QMenu, QFileDialog, QMessageBox, QInputDialog, QColorDialog)


class FlowLayout(QLayout):
    """A layout that lays widgets left-to-right and wraps to a new line when out of width,
    so the toolbar is never clipped (every button stays visible at any panel width)."""

    def __init__(self, parent=None, margin=0, hspace=6, vspace=6):
        super().__init__(parent)
        self._items = []
        self._hspace = hspace
        self._vspace = vspace
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
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for it in self._items:
            s = s.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return s + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do(self, rect, test):
        x, y, line_h = rect.x(), rect.y(), 0
        for it in self._items:
            w, h = it.sizeHint().width(), it.sizeHint().height()
            nx = x + w + self._hspace
            if nx - self._hspace > rect.right() and line_h > 0:
                x = rect.x(); y = y + line_h + self._vspace; nx = x + w + self._hspace; line_h = 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), it.sizeHint()))
            x = nx; line_h = max(line_h, h)
        return y + line_h - rect.y()

import plaque_gui as pgui
from app import engine_api

TOOL_SELECT = "select"
TOOL_ADD = "add"
TOOL_REGION = "region"
TOOL_ERASE = "erase"
TOOL_DISH = "dish"
TOOL_SCALE = "scale"


def _circle_from_3(p1, p2, p3):
    """Circle (cx, cy, r) through 3 points, or None if they are collinear."""
    (x1, y1), (x2, y2), (x3, y3) = p1, p2, p3
    d = 2.0 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
    if abs(d) < 1e-6:
        return None
    s1 = x1 * x1 + y1 * y1
    s2 = x2 * x2 + y2 * y2
    s3 = x3 * x3 + y3 * y3
    ux = (s1 * (y2 - y3) + s2 * (y3 - y1) + s3 * (y1 - y2)) / d
    uy = (s1 * (x3 - x2) + s2 * (x1 - x3) + s3 * (x2 - x1)) / d
    return ux, uy, math.hypot(x1 - ux, y1 - uy)

_COL = {"auto": QColor(40, 220, 70), "manual": QColor(30, 170, 255),
        "region": QColor(255, 170, 0), "watershed": QColor(180, 120, 255)}
_DEFAULT_COL = QColor(40, 220, 70)
_SEL = QColor(255, 45, 45)
_SEL_FILL = QColor(255, 45, 45, 70)
_SCALE_OPTIONS = [("Auto", None), ("0.5 mm", 0.5), ("1 mm", 1.0), ("2 mm", 2.0),
                  ("5 mm", 5.0), ("10 mm", 10.0), ("20 mm", 20.0), ("50 mm", 50.0),
                  ("100 mm", 100.0), ("Custom…", "custom")]


def _rgb_to_pixmap(rgb):
    rgb = np.ascontiguousarray(rgb)
    h, w = rgb.shape[:2]
    img = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888)
    return QPixmap.fromImage(img.copy())


def _pt(e):
    try:
        return e.position().toPoint()
    except AttributeError:
        return e.pos()


class _View(QGraphicsView):
    """Image view. Wheel / +/- = zoom-at-cursor (clamped). In Select tool: drag = pan,
    click = toggle one plaque, Shift+drag = box-select, Ctrl+drag = box-deselect. Middle-drag
    pans in any tool. Right-click always erases. The scale bar can be grabbed and dragged."""

    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.setRenderHint(QPainter.Antialiasing)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setBackgroundBrush(QColor("#0e1216"))
        self._panning = False
        self._pan_last = None
        self._press_pos = None
        self._press_scene = None
        self._moved = False
        self._temp = None          # transient circle/rect item during a drag
        self._box_mode = None      # None | "select" | "deselect" while Shift/Ctrl-dragging
        self._sb_drag = False      # dragging the scale bar
        self._sb_last = None

    def wheelEvent(self, e):
        self.zoom_by(1.2 if e.angleDelta().y() > 0 else 1.0 / 1.2)

    def zoom_by(self, f):
        self.owner._auto_fit = False
        cur = self.transform().m11()
        fit = getattr(self.owner, "_fit_scale", cur) or cur
        lo, hi = fit * 0.8, fit * 40.0
        target = cur * f
        if target < lo:
            f = lo / cur
        elif target > hi:
            f = hi / cur
        if abs(f - 1.0) > 1e-3:
            self.scale(f, f)

    def mousePressEvent(self, e):
        pos = _pt(e)
        self._press_pos = pos
        self._press_scene = self.mapToScene(pos)
        self._moved = False
        if e.button() == Qt.MiddleButton:
            self._panning = True; self._pan_last = pos
            self.setCursor(Qt.ClosedHandCursor); return
        if e.button() == Qt.RightButton:
            self.owner._erase_at(self._press_scene); return
        if e.button() != Qt.LeftButton:
            return super().mousePressEvent(e)
        # grab the scale bar from any tool
        if self.owner._sb_hit(self._press_scene):
            self._sb_drag = True; self._sb_last = self._press_scene
            self.setCursor(Qt.SizeAllCursor); return
        tool = self.owner.tool
        if tool == TOOL_SELECT:
            mods = e.modifiers()
            if mods & (Qt.ShiftModifier | Qt.ControlModifier):
                self._box_mode = "deselect" if (mods & Qt.ControlModifier) else "select"
                self._temp = QGraphicsRectItem(); self._temp.setPen(self._dash())
                self.scene().addItem(self._temp)
                self._temp.setRect(QRectF(self._press_scene, self._press_scene)); return
            self._panning = True; self._pan_last = pos
            self.setCursor(Qt.ClosedHandCursor); return
        if tool == TOOL_ERASE:
            self.owner._erase_at(self._press_scene); return
        if tool == TOOL_ADD:
            self._temp = QGraphicsEllipseItem(); self._temp.setPen(self._dash())
            self.scene().addItem(self._temp)
            self._size_circle(self._press_scene, self._press_scene); return
        if tool == TOOL_REGION:
            self._temp = QGraphicsRectItem(); self._temp.setPen(self._dash())
            self.scene().addItem(self._temp)
            self._temp.setRect(QRectF(self._press_scene, self._press_scene)); return
        if tool == TOOL_DISH:
            self.owner._dish_click(self._press_scene); return
        if tool == TOOL_SCALE:
            self.owner._scale_click(self._press_scene); return

    def mouseMoveEvent(self, e):
        pos = _pt(e)
        if self._sb_drag:
            scene = self.mapToScene(pos)
            self.owner._move_scalebar(scene.x() - self._sb_last.x(), scene.y() - self._sb_last.y())
            self._sb_last = scene; return
        if self._panning:
            d = pos - self._pan_last; self._pan_last = pos
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - d.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - d.y())
            if (pos - self._press_pos).manhattanLength() > 3:
                self._moved = True
            self.owner._auto_fit = False
            return
        if self._temp is not None:
            scene = self.mapToScene(pos)
            if self.owner.tool == TOOL_ADD and self._box_mode is None:
                self._size_circle(self._press_scene, scene)
            else:
                self._temp.setRect(QRectF(self._press_scene, scene).normalized())
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._sb_drag and e.button() == Qt.LeftButton:
            self._sb_drag = False; self.setCursor(Qt.ArrowCursor); return
        if self._panning and e.button() in (Qt.LeftButton, Qt.MiddleButton):
            self._panning = False; self.setCursor(Qt.ArrowCursor)
            if e.button() == Qt.LeftButton and not self._moved and self.owner.tool == TOOL_SELECT:
                self.owner._toggle_select_at(self.mapToScene(_pt(e)))
            return
        if e.button() != Qt.LeftButton:
            return super().mouseReleaseEvent(e)
        if self._temp is not None:
            scene = self.mapToScene(_pt(e)); start = self._press_scene
            self.scene().removeItem(self._temp); self._temp = None
            if self._box_mode is not None:
                rect = QRectF(start, scene).normalized()
                self.owner._box_select(rect, self._box_mode)
                self._box_mode = None
            elif self.owner.tool == TOOL_ADD:
                r = math.hypot(scene.x() - start.x(), scene.y() - start.y())
                if r < 3:
                    self.owner._add_point(start)
                else:
                    self.owner._add_circle(start, r)
            elif self.owner.tool == TOOL_REGION:
                x0 = min(start.x(), scene.x()); y0 = min(start.y(), scene.y())
                w = abs(scene.x() - start.x()); h = abs(scene.y() - start.y())
                if w >= 5 and h >= 5:
                    self.owner._detect_region((x0, y0, w, h))
            return
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key_Delete, Qt.Key_Backspace):
            self.owner._remove_selected()
        elif k == Qt.Key_U:
            self.owner._undo_last()
        elif k == Qt.Key_A and (e.modifiers() & Qt.ControlModifier):
            self.owner._select_all()
        elif k in (Qt.Key_Plus, Qt.Key_Equal):
            self.zoom_by(1.25)
        elif k in (Qt.Key_Minus, Qt.Key_Underscore):
            self.zoom_by(1.0 / 1.25)
        elif k in (Qt.Key_0, Qt.Key_Home):
            self.owner._reset_view()
        elif k == Qt.Key_Escape:
            self.owner._clear_selection()
        else:
            super().keyPressEvent(e)

    def _size_circle(self, c, edge):
        r = math.hypot(edge.x() - c.x(), edge.y() - c.y())
        self._temp.setRect(c.x() - r, c.y() - r, 2 * r, 2 * r)

    @staticmethod
    def _dash():
        pen = QPen(QColor(255, 230, 0), 1.5, Qt.DashLine); pen.setCosmetic(True)
        return pen


class PlaqueCanvas(QWidget):
    """Interactive editor widget. Drop-in for the old EditorWidget."""

    def __init__(self, det, image_path, out_dir, on_change=None, parent=None, face="#ffffff"):
        super().__init__(parent)
        self.det = det
        self.image_path = image_path
        self.out_dir = out_dir
        self._on_change = on_change
        self.ppm = det.get("pxl_per_mm")
        self.orig_bgr = det["orig_bgr"]
        self.proc_gray = det.get("proc_gray")
        self.candidates = det.get("candidates") or []
        self.lawn_gray = det.get("lawn_gray")
        self.plate = det.get("plate")
        # dish diameter in mm (invariant of which dish was detected: ppm = plate_mm / dish_px,
        # so ppm*dish_px recovers the value the user entered). Enables manual re-calibration.
        self.plate_mm = ((self.ppm * self.plate["diam_px"])
                         if (self.ppm and self.plate and self.plate.get("diam_px")) else 100.0)
        self._dish_pts = []          # rim points collected by the "Set dish" tool
        self._dish_markers = []      # their on-screen dots
        self._plate_items = []       # the drawn dish circle + label (so we can redraw)
        self._scale_pts = []         # two points for the "Calibrate from ruler" tool
        self._scale_markers = []     # their on-screen dots/line
        self._uid = 0
        self._plaques = []
        for p in det.get("plaques", []):
            q = dict(p); q["_uid"] = self._next_uid(); self._plaques.append(q)
        self._reorder()          # number 1..N top-to-bottom from the very first render
        self.tool = TOOL_SELECT
        self.selected = set()
        self._undo = []
        self._overlay = []
        self._auto_fit = True
        self._fit_scale = None
        # scale bar state
        self._scalebar_mm = None        # None = auto length
        self._scalebar_anchor = None    # (x,y) image px of the bar's left end; None = auto
        self._scalebar_rgb = (255, 255, 255)   # bar/label colour (RGB)
        self._sb_items = []
        self._sb_geom = None            # (x0, y0, len_px) of the current bar, for hit-test/export

        self.scene = QGraphicsScene(self)
        pm = _rgb_to_pixmap(det["display_rgb"])
        self.scene.addPixmap(pm)
        self.scene.setSceneRect(QRectF(pm.rect()))
        self.view = _View(self); self.view.setScene(self.scene)

        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(6)
        lay.addWidget(self._build_toolbar())
        lay.addWidget(self.view, 1)
        self.hint = QLabel(); self.hint.setObjectName("ModeHelp"); self.hint.setWordWrap(True)
        lay.addWidget(self.hint)

        self._draw_plate()
        self._draw_scalebar()
        self._render()
        self._update_hint()

    def _next_uid(self):
        self._uid += 1
        return self._uid

    # ---- public surface ---------------------------------------------------- #
    @property
    def plaques(self):
        return self._plaques

    def save(self):
        return pgui.save_results(self._plaques, self.orig_bgr, self.image_path, self.out_dir,
                                 self.ppm, self.lawn_gray, plate=self.plate,
                                 scalebar_mm=self._scalebar_mm, scalebar_anchor=self._scalebar_anchor,
                                 scalebar_color=self._sb_bgr())

    # ---- toolbar ----------------------------------------------------------- #
    def _build_toolbar(self):
        bar = QWidget()
        pol = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        pol.setHeightForWidth(True); bar.setSizePolicy(pol)
        bar.setStyleSheet(
            "QPushButton{padding:5px 10px;border:1px solid #c7ccd6;border-radius:6px;"
            "background:#f6f7f9;color:#1f2430;} QPushButton:hover{background:#eceff4;} "
            "QPushButton:checked{background:#2563eb;color:#ffffff;border:1px solid #1d4ed8;font-weight:600;} "
            # bright, bold, larger Export so it stands out as the main download action
            "QPushButton#Primary{background:#16a34a;color:#ffffff;border:1px solid #0f8a3d;"
            "font-weight:800;padding:6px 18px;font-size:13px;} "
            "QPushButton#Primary:hover{background:#19c258;} "
            "QPushButton#Primary::menu-indicator{width:0px;} QComboBox{padding:3px 6px;}")
        flow = FlowLayout(bar, margin=0, hspace=6, vspace=6)
        self._btns = {}
        group = QButtonGroup(self); group.setExclusive(True)

        def toolbtn(key, text, tip):
            b = QPushButton(text); b.setCheckable(True); b.setToolTip(tip)
            b.clicked.connect(lambda _=False, k=key: self._set_tool(k))
            group.addButton(b); self._btns[key] = b; flow.addWidget(b); return b

        toolbtn(TOOL_SELECT, "Select / pan",
                "Click a plaque to select/deselect it (turns red). Drag to pan, wheel to zoom. "
                "Shift+drag = box-select, Ctrl+drag = box-deselect.")
        toolbtn(TOOL_ADD, "Add",
                "Click a plaque the program missed to auto-trace it, or drag to draw a circle.")
        toolbtn(TOOL_REGION, "Detect area",
                "Drag a tight box; the detector re-scans inside it and adds plaques it finds.")
        toolbtn(TOOL_ERASE, "Erase",
                "Click a detection to remove it (or right-click anything, in any tool).")
        toolbtn(TOOL_DISH, "Set plate",
                "Calibrate: click 3 points on the real plate/agar rim, then type its diameter in mm "
                "(e.g. 85 for your agar area). The mm scale is set from your circle — fixes wrong "
                "auto-detection and gives true sizes.")

        def actbtn(text, slot, tip):
            b = QPushButton(text); b.setToolTip(tip); b.clicked.connect(slot)
            flow.addWidget(b); return b

        actbtn("Select all", self._select_all, "Select every plaque (Ctrl+A).")
        actbtn("Deselect all", self._clear_selection, "Clear the selection (Esc).")
        self.rm_btn = actbtn("Remove selected", self._remove_selected,
                             "Delete every selected (red) plaque. Shortcut: Delete.")
        actbtn("Undo", self._undo_last, "Undo the last change (u).")

        zout = QPushButton("–"); zout.setFixedWidth(34); zout.setToolTip("Zoom out (– / wheel)")
        zout.clicked.connect(lambda: self.view.zoom_by(1.0 / 1.25)); flow.addWidget(zout)
        zfit = QPushButton("Fit"); zfit.setToolTip("Zoom to fit the whole plate (0).")
        zfit.clicked.connect(self._reset_view); flow.addWidget(zfit)
        zin = QPushButton("+"); zin.setFixedWidth(34); zin.setToolTip("Zoom in (+ / wheel)")
        zin.clicked.connect(lambda: self.view.zoom_by(1.25)); flow.addWidget(zin)

        flow.addWidget(QLabel(" Scale bar:"))
        self.scale_combo = QComboBox()
        for label, val in _SCALE_OPTIONS:
            self.scale_combo.addItem(label, val)
        self.scale_combo.setToolTip("Scale-bar length. 'Auto' picks a nice round value; or pick "
                                    "a fixed length. Drag the bar on the image to reposition it.")
        self.scale_combo.currentIndexChanged.connect(self._scale_changed)
        flow.addWidget(self.scale_combo)
        col_btn = QPushButton("Colour"); col_btn.setToolTip("Pick the scale-bar colour.")
        col_btn.clicked.connect(self._pick_scalebar_color); flow.addWidget(col_btn)

        exp = QPushButton("⬇  Export all"); exp.setObjectName("Primary")
        exp.setToolTip("One click: save the data table (CSV) + the annotated figure to the "
                       "'out' folder next to your image, then open that folder.")
        exp.clicked.connect(self.export_all)
        flow.addWidget(exp)

        more = QPushButton("More ▾")
        more.setToolTip("More export options — individual files.")
        menu = QMenu(more)
        menu.addAction("Everything (CSV + annotated figure)", self.export_all)
        menu.addSeparator()
        menu.addAction("Data table (CSV)…", self.export_csv)
        menu.addAction("Annotated figure (PNG)…", self.export_figure)
        menu.addAction("Input vs annotated (side-by-side)…", self.export_comparison)
        menu.addAction("Original input image…", self.export_input)
        menu.addAction("Cropped plate for Fiji (calibrated TIFF)…", self.export_plate_crop)
        menu.addAction("Ground-truth labels…", self.export_groundtruth)
        more.setMenu(menu)
        flow.addWidget(more)

        self._btns[TOOL_SELECT].setChecked(True)
        return bar

    def _clear_calib_markers(self):
        for mk in list(self._dish_markers) + list(self._scale_markers):
            try:
                self.scene.removeItem(mk)
            except Exception:
                pass
        self._dish_pts = []; self._dish_markers = []
        self._scale_pts = []; self._scale_markers = []

    def _set_tool(self, key):
        self.tool = key
        # leaving a calibration tool: discard any half-collected points/markers
        if key not in (TOOL_DISH, TOOL_SCALE):
            self._clear_calib_markers()
        if key in self._btns:
            self._btns[key].setChecked(True)
        if key == TOOL_DISH:
            self._update_hint("Set dish: click 3 points around the dish rim; the mm scale "
                              "re-calibrates to your circle.")
        elif key == TOOL_SCALE:
            self._update_hint("Set scale: click TWO points a known distance apart (e.g. two ruler "
                              "marks); you'll type the real mm and the scale is set directly.")
        else:
            self._update_hint()

    def _scale_changed(self, _idx):
        val = self.scale_combo.currentData()
        if val == "custom":
            cur = self._scalebar_mm if isinstance(self._scalebar_mm, (int, float)) and self._scalebar_mm else 5.0
            num, ok = QInputDialog.getDouble(self, "Custom scale bar", "Scale-bar length (mm):",
                                             float(cur), 0.01, 1000.0, 2)
            if not ok:
                self.scale_combo.blockSignals(True); self.scale_combo.setCurrentIndex(0)
                self.scale_combo.blockSignals(False)
                self._scalebar_mm = None; self._draw_scalebar(); return
            self._scalebar_mm = float(num)
        else:
            self._scalebar_mm = val
        self._draw_scalebar()
        self._update_hint("scale bar = %s" % (("%g mm" % self._scalebar_mm) if self._scalebar_mm else "auto"))

    def _pick_scalebar_color(self):
        c = QColorDialog.getColor(QColor(*self._scalebar_rgb), self, "Scale-bar colour")
        if c.isValid():
            self._scalebar_rgb = (c.red(), c.green(), c.blue())
            self._draw_scalebar()
            self._update_hint("scale-bar colour updated")

    def _sb_bgr(self):
        r, g, b = self._scalebar_rgb
        return (b, g, r)

    # ---- overlays ---------------------------------------------------------- #
    def _draw_plate(self):
        # remove any previously drawn dish circle/label so a re-calibration redraws cleanly
        for it in getattr(self, "_plate_items", []):
            try:
                self.scene.removeItem(it)
            except Exception:
                pass
        self._plate_items = []
        if not self.plate:
            return
        cx, cy = self.plate["center"]; r = self.plate["radius"]
        pen = QPen(QColor(255, 165, 0), 1.4, Qt.DashLine); pen.setCosmetic(True)
        item = QGraphicsEllipseItem(cx - r, cy - r, 2 * r, 2 * r)
        item.setPen(pen); item.setZValue(5)
        self.scene.addItem(item); self._plate_items.append(item)
        diam = self.plate.get("diam_px") or (2 * r)
        tag = "dish Ø=%.0f px" % diam
        ar = self.plate.get("axis_ratio")
        if ar:
            tag += "  ·  axis %.2f%s" % (ar, "  (tilted!)" if ar > 1.03 else "")
        if self.ppm:
            tag += "  ·  %.4f mm/px" % self.ppm
        t = QGraphicsSimpleTextItem(tag); t.setBrush(QColor(255, 170, 0))
        f = QFont(); f.setPointSize(8); f.setBold(True); t.setFont(f)
        t.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        t.setPos(cx - r, cy - r); t.setZValue(6); self.scene.addItem(t); self._plate_items.append(t)

    # ---- manual dish / re-calibration -------------------------------------- #
    def _dish_click(self, scene_pt):
        """Collect a rim point; after the 3rd, fit a circle and re-calibrate."""
        self._dish_pts.append((scene_pt.x(), scene_pt.y()))
        m = QGraphicsEllipseItem(scene_pt.x() - 7, scene_pt.y() - 7, 14, 14)
        mp = QPen(QColor(0, 200, 255)); mp.setCosmetic(True); mp.setWidth(2)
        m.setPen(mp); m.setZValue(9); self.scene.addItem(m); self._dish_markers.append(m)
        need = 3 - len(self._dish_pts)
        if need > 0:
            self._update_hint("Set dish: click %d more point(s) on the dish rim." % need)
            return
        res = _circle_from_3(*self._dish_pts[:3])
        for mk in self._dish_markers:
            try:
                self.scene.removeItem(mk)
            except Exception:
                pass
        self._dish_markers = []; self._dish_pts = []
        if res is None:
            self._update_hint("Those 3 points line up — click 3 spread-out rim points instead.")
            return
        cx, cy, r = res
        mm, ok = QInputDialog.getDouble(
            self, "Plate diameter",
            "Diameter of the rim you just drew (mm)\n(e.g. your agar / plaque area ≈ 85 mm):",
            float(self.plate_mm or 90.0), 0.1, 1000.0, 2)
        if not ok or mm <= 0:
            self._update_hint("dish calibration cancelled")
            return
        self._apply_dish(cx, cy, r, diam_mm=mm)

    def _scale_click(self, scene_pt):
        """Collect two points a known distance apart, then set mm/px directly from the ruler."""
        self._scale_pts.append((scene_pt.x(), scene_pt.y()))
        m = QGraphicsEllipseItem(scene_pt.x() - 7, scene_pt.y() - 7, 14, 14)
        mp = QPen(QColor(0, 220, 120)); mp.setCosmetic(True); mp.setWidth(2)
        m.setPen(mp); m.setZValue(9); self.scene.addItem(m); self._scale_markers.append(m)
        if len(self._scale_pts) < 2:
            self._update_hint("Set scale: click the SECOND point a known distance away (a ruler mark).")
            return
        (x0, y0), (x1, y1) = self._scale_pts[:2]
        ln = QGraphicsLineItem(x0, y0, x1, y1)
        lp = QPen(QColor(0, 220, 120)); lp.setCosmetic(True); lp.setWidth(2)
        ln.setPen(lp); ln.setZValue(9); self.scene.addItem(ln); self._scale_markers.append(ln)
        px = math.hypot(x1 - x0, y1 - y0)
        self._scale_pts = []
        if px < 2:
            self._clear_calib_markers()
            self._update_hint("Those two points are basically the same — try again.")
            return
        mm, ok = QInputDialog.getDouble(self, "Calibrate from ruler",
                                        "Real distance between the two points (mm):",
                                        10.0, 0.001, 1000.0, 3)
        self._clear_calib_markers()
        if not ok or mm <= 0:
            self._update_hint("scale calibration cancelled"); return
        self._apply_ruler_scale(mm / px)

    def _apply_ruler_scale(self, ppm):
        """Set mm/px directly from a ruler measurement (independent of dish detection)."""
        self.ppm = float(ppm)
        try:
            self.det["pxl_per_mm"] = self.ppm
        except Exception:
            pass
        # keep plate_mm consistent so the Set-dish tool still works afterward
        if self.plate and self.plate.get("diam_px"):
            self.plate_mm = self.ppm * self.plate["diam_px"]
        self._draw_scalebar()
        self._update_hint("scale set from ruler: %.4f mm/px  (%.2f px/mm)"
                          % (self.ppm, (1.0 / self.ppm) if self.ppm else 0.0))
        if self._on_change:
            self._on_change()

    def _apply_dish(self, cx, cy, r, diam_mm=None):
        """Set the dish to a manual circle and recompute mm/px. diam_mm = the real
        diameter (mm) of the rim just drawn; when given it becomes the working plate size."""
        diam = 2.0 * r
        self.plate = {"center": (cx, cy), "radius": r, "diam_px": diam, "axis_ratio": 1.0}
        if diam_mm and diam_mm > 0:
            self.plate_mm = float(diam_mm)
        if self.plate_mm and diam > 0:
            self.ppm = float(self.plate_mm) / diam
        # propagate to the shared detection dict so the table + summary card recompute
        try:
            self.det["plate"] = self.plate
            self.det["pxl_per_mm"] = self.ppm
        except Exception:
            pass
        self._draw_plate(); self._draw_scalebar()
        self._update_hint("dish set manually: Ø=%.0f px · %.4f mm/px (calibration updated)"
                          % (diam, self.ppm or 0.0))
        if self._on_change:
            self._on_change()

    def _scalebar_mm_used(self):
        """The mm length the bar will draw at (resolves 'Auto' to the nice value)."""
        if not self.ppm:
            return None
        if self._scalebar_mm:
            return self._scalebar_mm
        H, W = self.orig_bgr.shape[:2]
        target_mm = 0.18 * W * self.ppm
        return min([0.5, 1, 2, 5, 10, 20, 50, 100], key=lambda v: abs(v - target_mm))

    def _draw_scalebar(self):
        """(Re)draw the scale bar at the current anchor + length. Stores geometry so it can
        be hit-tested for dragging and so the export reproduces it exactly."""
        for it in self._sb_items:
            try:
                self.scene.removeItem(it)
            except Exception:
                pass
        self._sb_items = []
        mm = self._scalebar_mm_used()
        if not mm:
            self._sb_geom = None
            return
        lpx = mm / self.ppm
        if self._scalebar_anchor is None:
            H, W = self.orig_bgr.shape[:2]
            if self.plate and self.plate.get("center") is not None and self.plate.get("radius"):
                cx, cy = self.plate["center"]; r = float(self.plate["radius"])
                self._scalebar_anchor = (cx - lpx / 2.0, cy + 0.80 * r)
            else:
                self._scalebar_anchor = (0.04 * W, H - 0.06 * H)
        x0, y0 = self._scalebar_anchor
        back = QGraphicsLineItem(x0, y0, x0 + lpx, y0)
        pb = QPen(QColor(0, 0, 0)); pb.setCosmetic(True); pb.setWidth(6); back.setPen(pb)
        back.setZValue(20); self.scene.addItem(back); self._sb_items.append(back)
        bar = QGraphicsLineItem(x0, y0, x0 + lpx, y0)
        pp = QPen(QColor(*self._scalebar_rgb)); pp.setCosmetic(True); pp.setWidth(3); bar.setPen(pp)
        bar.setZValue(21); self.scene.addItem(bar); self._sb_items.append(bar)
        t = QGraphicsSimpleTextItem("%g mm" % mm); t.setBrush(QColor(*self._scalebar_rgb))
        f = QFont(); f.setPointSize(9); f.setBold(True); t.setFont(f)
        t.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        t.setPos(x0, y0 - 0.045 * self.orig_bgr.shape[0]); t.setZValue(22)
        self.scene.addItem(t); self._sb_items.append(t)
        self._sb_geom = (x0, y0, lpx)

    def _sb_hit(self, scene_pt):
        """True if scene_pt is on/near the scale bar (so a drag moves it instead of editing)."""
        if not self._sb_geom:
            return False
        x0, y0, lpx = self._sb_geom
        H = self.orig_bgr.shape[0]
        m = 0.02 * self.orig_bgr.shape[1]
        return (x0 - m <= scene_pt.x() <= x0 + lpx + m) and (y0 - 0.07 * H <= scene_pt.y() <= y0 + m)

    def _move_scalebar(self, dx, dy):
        if self._scalebar_anchor is None:
            return
        H, W = self.orig_bgr.shape[:2]
        x0 = min(max(self._scalebar_anchor[0] + dx, 0), W)
        y0 = min(max(self._scalebar_anchor[1] + dy, 0), H)
        self._scalebar_anchor = (x0, y0)
        self._draw_scalebar()

    def _clear_overlay(self):
        for it in self._overlay:
            try:
                self.scene.removeItem(it)
            except Exception:
                pass
        self._overlay = []

    def _render(self):
        self._clear_overlay()
        for i, p in enumerate(self._plaques):
            sel = p.get("_uid") in self.selected
            col = _SEL if sel else _COL.get(p.get("source", "auto"), _DEFAULT_COL)
            pen = QPen(col, 2.4 if sel else 1.4); pen.setCosmetic(True)
            if p["kind"] == "circle":
                r = float(p.get("radius", math.sqrt(max(p["area_pxl"], 1) / math.pi)))
                cx, cy = p["center"]
                item = QGraphicsEllipseItem(cx - r, cy - r, 2 * r, 2 * r)
            else:
                pts = np.asarray(p["contour"], dtype=np.int32).reshape(-1, 2)
                item = QGraphicsPolygonItem(QPolygonF([QPointF(float(x), float(y)) for x, y in pts]))
            item.setPen(pen)
            if sel:
                item.setBrush(QBrush(_SEL_FILL))
            item.setZValue(10)
            self.scene.addItem(item); self._overlay.append(item)
            t = QGraphicsSimpleTextItem(str(i + 1))
            # white glyph with a thin dark outline: readable on any background and
            # colour-blind-safe (was pure yellow, which washed out on pale plates)
            t.setBrush(QColor(255, 255, 255))
            _num_pen = QPen(QColor(0, 0, 0)); _num_pen.setWidthF(0.6); _num_pen.setCosmetic(True)
            t.setPen(_num_pen)
            f = QFont(); f.setPointSize(8); f.setBold(True); t.setFont(f)
            t.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
            t.setPos(p["center"][0], p["center"][1]); t.setZValue(11)
            self.scene.addItem(t); self._overlay.append(t)

    def _update_hint(self, msg=None):
        cal = (f"{self.ppm:.4f} mm/px" if self.ppm else "pixels only")
        nsel = len(self.selected)
        base = (f"{len(self._plaques)} plaques"
                + (f" · {nsel} selected" if nsel else "")
                + f" · {cal}   —   wheel/＋－ zoom · drag = pan · click = select · "
                "Shift/Ctrl+drag = box select/deselect · drag scale bar to move it")
        self.hint.setText((msg + "   ·   " + base) if msg else base)

    # ---- geometry helpers -------------------------------------------------- #
    def _find(self, sx, sy):
        best, ba = None, None
        for i, p in enumerate(self._plaques):
            if p["kind"] == "circle":
                r = float(p.get("radius", math.sqrt(max(p["area_pxl"], 1) / math.pi)))
                inside = math.hypot(sx - p["center"][0], sy - p["center"][1]) <= r
            else:
                inside = cv2.pointPolygonTest(np.asarray(p["contour"], dtype=np.int32),
                                              (float(sx), float(sy)), False) >= 0
            if inside and (ba is None or p["area_pxl"] < ba):
                best, ba = i, p["area_pxl"]
        if best is not None:
            return best
        near, nd = None, 18.0
        for i, p in enumerate(self._plaques):
            d = math.hypot(sx - p["center"][0], sy - p["center"][1])
            if d < nd:
                near, nd = i, d
        return near

    def _inside_existing(self, sx, sy):
        for p in self._plaques:
            if math.hypot(sx - p["center"][0], sy - p["center"][1]) < 6:
                return True
            if p["kind"] == "circle":
                r = float(p.get("radius", math.sqrt(max(p["area_pxl"], 1) / math.pi)))
                if math.hypot(sx - p["center"][0], sy - p["center"][1]) <= r:
                    return True
            elif cv2.pointPolygonTest(np.asarray(p["contour"], dtype=np.int32),
                                      (float(sx), float(sy)), False) >= 0:
                return True
        return False

    # ---- selection --------------------------------------------------------- #
    def _toggle_select_at(self, scene_pt):
        idx = self._find(scene_pt.x(), scene_pt.y())
        if idx is None:
            self._clear_selection(); return
        uid = self._plaques[idx].get("_uid")
        (self.selected.discard if uid in self.selected else self.selected.add)(uid)
        self._render(); self._update_hint()

    def _box_select(self, rect, mode):
        n = 0
        for p in self._plaques:
            if rect.contains(QPointF(p["center"][0], p["center"][1])):
                uid = p.get("_uid")
                if mode == "select" and uid not in self.selected:
                    self.selected.add(uid); n += 1
                elif mode == "deselect" and uid in self.selected:
                    self.selected.discard(uid); n += 1
        self._render()
        self._update_hint("%s %d plaque(s) in the box" % ("selected" if mode == "select" else "deselected", n))

    def _select_all(self):
        self.selected = set(p.get("_uid") for p in self._plaques)
        self._render(); self._update_hint("selected all %d" % len(self.selected))

    def _clear_selection(self):
        if self.selected:
            self.selected.clear(); self._render()
        self._update_hint("selection cleared")

    def _remove_selected(self):
        if not self.selected:
            self._update_hint("nothing selected — click plaques (they turn red) first")
            return
        self._push_undo()
        n = len(self.selected)
        self._plaques = [p for p in self._plaques if p.get("_uid") not in self.selected]
        self.selected.clear()
        self._changed(f"removed {n} selected plaque(s)")

    # ---- edit operations --------------------------------------------------- #
    def _push_undo(self):
        self._undo.append(([dict(p) for p in self._plaques], set(self.selected)))
        if len(self._undo) > 80:
            self._undo.pop(0)

    def _reorder(self):
        # Number plaques 1..N top-to-bottom, then left-to-right, so the on-canvas
        # labels, the results table INDEX, the CSV, the annotated figure and the
        # ground-truth export all read in the same human-obvious order with #1 at
        # the top of the image. Selection is by _uid, so it survives reordering.
        self._plaques.sort(key=lambda p: (p["center"][1], p["center"][0]))

    def _changed(self, msg=None):
        self._reorder()
        self._render(); self._update_hint(msg)
        if self._on_change:
            self._on_change()

    def _erase_at(self, scene_pt):
        idx = self._find(scene_pt.x(), scene_pt.y())
        if idx is None:
            self._update_hint("nothing to erase there"); return
        self._push_undo()
        removed = self._plaques.pop(idx)
        self.selected.discard(removed.get("_uid"))
        self._changed(f"erased a {removed.get('source', 'auto')} plaque")

    def _add_point(self, scene_pt):
        res = pgui.trace_at(self.candidates, self.proc_gray, scene_pt.x(), scene_pt.y())
        if res is None:
            self._update_hint("couldn't auto-trace there — drag to draw a circle instead"); return
        hull, area, center = res
        self._push_undo()
        self._plaques.append({"source": "manual", "kind": "contour", "_uid": self._next_uid(),
                              "contour": hull, "area_pxl": float(area), "center": center})
        self._changed("added a traced plaque")

    def _add_circle(self, center, r):
        self._push_undo()
        self._plaques.append({"source": "manual", "kind": "circle", "_uid": self._next_uid(),
                              "center": (center.x(), center.y()), "radius": float(r),
                              "area_pxl": float(math.pi * r * r)})
        self._changed("added a circle")

    def _detect_region(self, roi):
        try:
            found = engine_api.detect_region(self.orig_bgr, roi, sensitive=True, small=True)
        except Exception as e:
            self._update_hint("area detect failed: %s" % e); return
        fresh = [p for p in found if not self._inside_existing(*p["center"])]
        if not fresh:
            self._update_hint("no new plaques found in that area"); return
        self._push_undo()
        for p in fresh:
            p["_uid"] = self._next_uid(); self._plaques.append(p)
        self._changed("added %d plaque(s) from the selected area" % len(fresh))

    def _undo_last(self):
        if not self._undo:
            self._update_hint("nothing to undo"); return
        pls, sel = self._undo.pop()
        self._plaques = pls; self.selected = sel
        self._changed("undid last change")

    # ---- view fit / zoom --------------------------------------------------- #
    def _fit_to_scene(self):
        self.view.resetTransform()
        self.view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
        self._fit_scale = self.view.transform().m11()

    def _reset_view(self):
        self._auto_fit = True
        self._fit_to_scene()

    def showEvent(self, e):
        super().showEvent(e)
        self._fit_to_scene()

    # ---- exports ----------------------------------------------------------- #
    def _ask_path(self, title, default_name, flt):
        os.makedirs(self.out_dir, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(self, title, os.path.join(self.out_dir, default_name), flt)
        return path or None

    def _info(self, title, text):
        try:
            inst = QApplication.instance()
            if inst is not None and inst.platformName() != "offscreen":
                QMessageBox.information(self, title, text)
        except Exception:
            pass

    def _open_folder(self, path):
        """Reveal the output folder in the OS file manager (skipped when headless)."""
        try:
            inst = QApplication.instance()
            if inst is not None and inst.platformName() == "offscreen":
                return
            import sys
            if sys.platform.startswith("win"):
                os.startfile(path)                       # noqa: Windows-only
            elif sys.platform == "darwin":
                import subprocess; subprocess.Popen(["open", path])
            else:
                import subprocess; subprocess.Popen(["xdg-open", path])
        except Exception:
            pass

    def export_all(self):
        """One click: write the CSV table + annotated figure to the out folder and open it."""
        name = os.path.splitext(os.path.basename(self.image_path))[0]
        os.makedirs(self.out_dir, exist_ok=True)
        csv_path = os.path.join(self.out_dir, f"data_{name}.csv")
        df = engine_api.measure_table(self._plaques, self.orig_bgr, self.ppm, self.lawn_gray)
        df.to_csv(csv_path, index=False)
        fig_path = os.path.join(self.out_dir, f"figure_{name}.png")
        pgui.save_figure(self._plaques, self.orig_bgr, fig_path, self.ppm, plate=self.plate,
                         scalebar_mm=self._scalebar_mm, scalebar_anchor=self._scalebar_anchor,
                         scalebar_color=self._sb_bgr())
        self._update_hint("✓ exported %d rows + annotated figure → 'out' folder" % len(df))
        self._open_folder(self.out_dir)
        return self.out_dir

    def export_csv(self, path=None):
        """Export the per-plaque measurement table (the same rows shown on the right) to CSV."""
        name = os.path.splitext(os.path.basename(self.image_path))[0]
        if path is None:
            path = self._ask_path("Export data table (CSV)", f"data_{name}.csv", "CSV (*.csv)")
            if not path:
                return None
        df = engine_api.measure_table(self._plaques, self.orig_bgr, self.ppm, self.lawn_gray)
        df.to_csv(path, index=False)
        self._update_hint("saved %d rows → %s" % (len(df), os.path.basename(path)))
        self._info("CSV saved", "Saved %d plaque rows to:\n\n%s" % (len(df), path))
        return path

    def export_figure(self, path=None):
        """Download the annotated image (outlines + numbers + scale bar) as a figure."""
        name = os.path.splitext(os.path.basename(self.image_path))[0]
        if path is None:
            path = self._ask_path("Download annotated figure", f"figure_{name}.png",
                                  "Image (*.png *.tif *.tiff *.jpg)")
            if not path:
                return None
        out = pgui.save_figure(self._plaques, self.orig_bgr, path, self.ppm, plate=self.plate,
                               scalebar_mm=self._scalebar_mm, scalebar_anchor=self._scalebar_anchor,
                               scalebar_color=self._sb_bgr())
        self._update_hint("saved figure → %s" % os.path.basename(out))
        self._info("Figure saved", "Annotated figure (with scale bar) saved to:\n\n%s" % out)
        return out

    def export_comparison(self, path=None):
        """Download a side-by-side 'input vs annotated output' figure."""
        name = os.path.splitext(os.path.basename(self.image_path))[0]
        if path is None:
            path = self._ask_path("Download input vs annotated (side-by-side)",
                                  f"compare_{name}.png", "Image (*.png *.tif *.tiff *.jpg)")
            if not path:
                return None
        out = pgui.save_comparison(self._plaques, self.orig_bgr, path, self.ppm, plate=self.plate,
                                   scalebar_mm=self._scalebar_mm, scalebar_anchor=self._scalebar_anchor,
                                   scalebar_color=self._sb_bgr())
        self._update_hint("saved side-by-side → %s" % os.path.basename(out))
        self._info("Saved", "Input-vs-annotated figure saved to:\n\n%s" % out)
        return out

    def export_input(self, path=None):
        """Download the original input image (decoded; HEIC is written as PNG)."""
        name = os.path.splitext(os.path.basename(self.image_path))[0]
        if path is None:
            path = self._ask_path("Download the original input image",
                                  f"input_{name}.png", "Image (*.png *.tif *.tiff *.jpg)")
            if not path:
                return None
        out = pgui.save_image(self.orig_bgr, path)
        self._update_hint("saved input image → %s" % os.path.basename(out))
        self._info("Saved", "Original input image saved to:\n\n%s" % out)
        return out

    def export_plate_crop(self, path=None):
        """Crop the dish region and save a Fiji/ImageJ-calibrated TIFF (mm scale baked in).

        The TIFF opens in Fiji already scaled in millimetres, so cropping a plaque
        there keeps the scale and Analyze > Tools > Scale Bar draws a correct mm bar.
        """
        import plate_crop
        name = os.path.splitext(os.path.basename(self.image_path))[0]
        if path is None:
            path = self._ask_path("Save cropped plate for Fiji (calibrated TIFF)",
                                  f"{name}_plate.tif", "TIFF image (*.tif *.tiff)")
            if not path:
                return None
        info = plate_crop.save_plate_crop(self.orig_bgr, self.plate, self.ppm, path)
        w, h = info["crop_px"]
        if info["mm_per_px"]:
            cal = ("Calibrated: 1 px = %.5f mm (%.2f px/mm).\nFiji opens it already in mm — "
                   "crop a plaque and the scale follows.\n\n" % (info["mm_per_px"], info["px_per_mm"]))
        else:
            cal = ("No dish was detected, so the crop is NOT calibrated — set the scale "
                   "in Fiji from a known reference.\n\n")
        self._update_hint("saved calibrated plate crop → %s" % os.path.basename(info["tiff"]))
        self._info("Plate crop saved",
                   "Cropped plate (%d × %d px) saved to:\n\n%s\n\n%sA sidecar '%s' explains "
                   "the scale and the Fiji steps."
                   % (w, h, info["tiff"], cal, os.path.basename(info["readme"]) if info["readme"] else ""))
        return info["tiff"]

    def export_groundtruth(self, path=None):
        """Write the corrected plaque set as a reusable labels file (JSON + sibling CSV)."""
        name = os.path.splitext(os.path.basename(self.image_path))[0]
        if path is None:
            path = self._ask_path("Save ground-truth labels", f"labels_{name}.json", "Label file (*.json)")
            if not path:
                return None
        recs = []
        for i, p in enumerate(self._plaques, start=1):
            cx, cy = p["center"]
            r_px = math.sqrt(max(p["area_pxl"], 1e-9) / math.pi)
            _dp, _amm, dia_mm = pgui.measure(p["area_pxl"], self.ppm)
            recs.append({"index": i, "x_px": round(float(cx), 1), "y_px": round(float(cy), 1),
                         "r_px": round(float(r_px), 1), "area_px": round(float(p["area_pxl"]), 1),
                         "diam_mm": (round(float(dia_mm), 3) if self.ppm else None),
                         "source": p.get("source", "auto"), "kind": p["kind"]})
        meta = {"image": os.path.basename(self.image_path),
                "image_path": os.path.abspath(self.image_path),
                "mm_per_px": self.ppm, "n_plaques": len(recs),
                "n_manual": sum(1 for r in recs if r["source"] != "auto"),
                "dish_diam_px": (self.plate or {}).get("diam_px"),
                "dish_center_px": (self.plate or {}).get("center"),
                "schema": "plaque-groundtruth-v1"}
        with open(path, "w") as fh:
            json.dump({"meta": meta, "plaques": recs}, fh, indent=2)
        csv_path = os.path.splitext(path)[0] + ".csv"
        pd.DataFrame(recs).to_csv(csv_path, index=False)
        self._update_hint("saved %d labels → %s" % (len(recs), os.path.basename(path)))
        self._info("Ground truth saved",
                   "Saved %d plaque labels (%d hand-edited):\n\n%s\n%s\n\n"
                   "Use these as the gold standard to score the engines (precision / recall) "
                   "and to retrain the classifier." % (len(recs), meta["n_manual"], path, csv_path))
        return path
