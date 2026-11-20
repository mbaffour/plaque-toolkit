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

What is drawn here is drawn from plaque_gui's figure style (PLAQUE_CLASSES, label_text,
layout_labels, scalebar.bar_geometry, plate_key): the same functions draw every exported
plate image, so the canvas and the files agree (click-through round 1, F9/F12/F19).
"""
import os
import math
import json

import numpy as np
import cv2
import pandas as pd

from PySide6.QtCore import Qt, QRectF, QPointF, QRect, QSize, QPoint, Signal
from PySide6.QtGui import (QImage, QPixmap, QPen, QBrush, QColor, QPainter, QPolygonF, QFont,
                           QTransform, QKeySequence, QShortcut, QFontDatabase)
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLayout, QSizePolicy, QGraphicsView,
    QGraphicsScene, QGraphicsItem, QGraphicsEllipseItem, QGraphicsRectItem, QGraphicsPolygonItem,
    QGraphicsLineItem, QGraphicsSimpleTextItem, QGraphicsPathItem, QGraphicsPixmapItem, QPushButton,
    QButtonGroup, QLabel, QComboBox, QSpinBox, QMenu, QFileDialog, QMessageBox, QInputDialog,
    QColorDialog, QLineEdit, QCheckBox, QScrollArea)


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
import scalebar as sbmod
from app import engine_api

TOOL_SELECT = "select"
TOOL_ADD = "add"
TOOL_FREEHAND = "freehand"
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


def clipped_circle_contour(cx, cy, r, shape):
    """The part of a circle that lies INSIDE the image, as an int32 contour (N, 1, 2).

    A circle drawn across the image edge used to keep its full pi*r^2 although part of it is
    not on the photo (CT-R1 F16). Clamping each outline point to the image is exact for a
    disk whose centre is inside the image: the disk is convex, so every point pushed back
    onto an edge (or a corner) lands on the boundary of disk-and-image."""
    H, W = int(shape[0]), int(shape[1])
    n = int(max(72, min(720, 2 * math.pi * r / 2.0)))
    a = np.linspace(0.0, 2 * math.pi, n, endpoint=False)
    pts = np.column_stack([np.clip(cx + r * np.cos(a), 0, W - 1), np.clip(cy + r * np.sin(a), 0, H - 1)])
    pts = np.round(pts).astype(np.int32)
    keep = np.ones(len(pts), dtype=bool)
    keep[1:] = np.any(pts[1:] != pts[:-1], axis=1)          # drop repeats made by the clamp
    return pts[keep].reshape(-1, 1, 2)


def outline_crosses_itself(arr):
    """True when a hand-drawn outline is a figure-eight (or worse) rather than one loop.

    The signed (shoelace) area of a figure-eight is the DIFFERENCE of its lobes while the
    region it encloses is their sum, so the two disagree badly; for one loop -- including the
    usual small overshoot where the pen passes its own start -- they agree. Compared against
    the filled region minus half its boundary (Pick's theorem), which equals the polygon area
    for a simple outline (CT-R1 F16: a figure-eight was stored with an area of 20 px)."""
    pts = np.asarray(arr, dtype=np.int32).reshape(-1, 2)
    if len(pts) < 4:
        return False
    signed = abs(float(cv2.contourArea(pts.reshape(-1, 1, 2))))
    x0, y0 = pts.min(axis=0)
    x1, y1 = pts.max(axis=0)
    mask = np.zeros((int(y1 - y0) + 3, int(x1 - x0) + 3), np.uint8)
    cv2.fillPoly(mask, [(pts - [x0 - 1, y0 - 1]).astype(np.int32).reshape(-1, 1, 2)], 255)
    filled = float(cv2.countNonZero(mask))
    per = float(cv2.arcLength(pts.reshape(-1, 1, 2), True))
    return signed < 0.7 * max(filled - per / 2.0, 1.0)


_OVERLAP_COL = QColor(*pgui.PLAQUE_CLASSES["overlap"][1])   # kept for callers; see PLAQUE_CLASSES
_SEL = QColor(255, 45, 45)
_SEL_FILL = QColor(255, 45, 45, 70)
_SCALE_OPTIONS = [("Auto", None), ("0.5 mm", 0.5), ("1 mm", 1.0), ("2 mm", 2.0),
                  ("5 mm", 5.0), ("10 mm", 10.0), ("20 mm", 20.0), ("50 mm", 50.0),
                  ("100 mm", 100.0), ("Custom…", "custom")]
_BTN_QSS = (
    "QPushButton{padding:5px 10px;border:1px solid #c7ccd6;border-radius:6px;"
    "background:#f6f7f9;color:#1f2430;} QPushButton:hover{background:#eceff4;} "
    "QPushButton:checked{background:#2563eb;color:#ffffff;border:1px solid #1d4ed8;font-weight:600;} "
    # bright, bold, larger Export so it stands out as the main download action
    "QPushButton#Primary{background:#16a34a;color:#ffffff;border:1px solid #0f8a3d;"
    "font-weight:800;padding:6px 18px;font-size:13px;} "
    "QPushButton#Primary:hover{background:#19c258;} "
    "QPushButton#Primary::menu-indicator{width:0px;} QComboBox{padding:3px 6px;}")
_HELP = ("Wheel or + / − = zoom (when the page scrolls, the wheel scrolls it: click the image "
         "first or hold Ctrl to zoom) · drag = pan · click = select · Shift/Ctrl+drag = box select / "
         "deselect · right-click = erase · Ctrl+Z / Ctrl+Shift+Z = undo / redo · drag the scale "
         "bar (Select / pan tool) to move it.")

_CANVAS_FAMILY = []


def _canvas_font(pt, bold=True):
    """The canvas labels in the figure's own font (DejaVu Sans, as the exported image and the
    legend key) when it can be loaded into Qt; else the application font."""
    if not _CANVAS_FAMILY:
        fam = None
        try:
            path = pgui.figure_font_path(bold=True)
            if path:
                fid = QFontDatabase.addApplicationFont(path)
                fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
                fam = fams[0] if fams else None
        except Exception:                               # noqa: BLE001
            fam = None
        _CANVAS_FAMILY.append(fam)
    f = QFont(_CANVAS_FAMILY[0]) if _CANVAS_FAMILY[0] else QFont()
    f.setPointSize(pt); f.setBold(bold)
    return f


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
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setBackgroundBrush(QColor("#0e1216"))
        # QGraphicsView grabs drops by default, which blocked drag-and-drop once an image was
        # loaded (the editor covers the tab). Refuse drops here so they fall through to the tab.
        self.setAcceptDrops(False)
        self.viewport().setAcceptDrops(False)
        self._panning = False
        self._pan_last = None
        self._press_pos = None
        self._press_scene = None
        self._moved = False
        self._temp = None          # transient circle/rect item during a drag
        self._box_mode = None      # None | "select" | "deselect" while Shift/Ctrl-dragging
        self._sb_drag = False      # dragging the scale bar
        self._sb_last = None
        self._fitting = False

    def _page(self):
        """The scroll area the editor's tab sits in (None outside the app)."""
        w = self.parentWidget()
        while w is not None:
            if isinstance(w, QScrollArea):
                return w
            w = w.parentWidget()
        return None

    def _page_scrolls(self):
        """True when the page around the editor (the tab's scroll area) can scroll."""
        page = self._page()
        return page is not None and page.verticalScrollBar().maximum() > 0

    def wheelEvent(self, e):
        # CT-R2 N10: on a page that scrolls (a small window) the wheel over the image scrolls
        # the PAGE, so the rows below the image stay reachable; it zooms when Ctrl is held, when
        # the image has the focus (click it first), or when the page does not scroll.
        if (e.modifiers() & Qt.ControlModifier) or self.hasFocus() or not self._page_scrolls():
            self.zoom_by(1.2 if e.angleDelta().y() > 0 else 1.0 / 1.2)
        else:
            # handed to the page's scroll bar explicitly (Qt does not pass a synthesized wheel
            # event on to the parent, and this way every wheel event behaves the same)
            QApplication.sendEvent(self._page().verticalScrollBar(), e.clone())
        e.accept()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # CT-R1 F10: the plate was fitted once, in showEvent, before the layout had given the
        # view its size, and never again. Fit on every resize until the user zooms or pans.
        if self.owner._auto_fit and not self._fitting:
            self._fitting = True                # fitInView can toggle scroll bars -> resize
            try:
                self.owner._fit_to_scene()
            finally:
                self._fitting = False

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
        # the scale bar is grabbed by the Select / pan tool only: a Detect-area box or a circle
        # started on it used to move the bar and mark the plate edited (CT-R2 N12)
        if self.owner.tool == TOOL_SELECT and self.owner._sb_hit(self._press_scene):
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
        if tool == TOOL_FREEHAND:
            self._free_pts = [self._press_scene]
            self._free_item = QGraphicsPolygonItem(); self._free_item.setPen(self._dash())
            self.scene().addItem(self._free_item); return
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
                self.owner._auto_fit = False        # a real pan (not a click) ends auto-fit
            return
        if getattr(self, "_free_item", None) is not None:
            scene = self.mapToScene(pos)
            self._free_pts.append(scene)
            self._free_item.setPolygon(QPolygonF(self._free_pts))
            self._moved = True
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
        if getattr(self, "_free_item", None) is not None and e.button() == Qt.LeftButton:
            self.scene().removeItem(self._free_item); self._free_item = None
            pts = self._free_pts; self._free_pts = []
            self.owner._add_freehand(pts); return
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
        ctrl = bool(e.modifiers() & Qt.ControlModifier)
        shift = bool(e.modifiers() & Qt.ShiftModifier)
        if k in (Qt.Key_Delete, Qt.Key_Backspace):
            self.owner._remove_selected()
        elif ctrl and k == Qt.Key_Z:                 # CT-R1 F25: Ctrl+Z did nothing
            (self.owner._redo_last if shift else self.owner._undo_last)()
        elif ctrl and k == Qt.Key_Y:
            self.owner._redo_last()
        elif k == Qt.Key_U:
            self.owner._undo_last()
        elif k == Qt.Key_A and ctrl:
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

    # emitted whenever the on-canvas selection changes; payload is the list of selected
    # plaque _uid values (in top-down plaque order). Lets the results table mirror the
    # canvas selection (and vice-versa) so a plaque and its row stay linked.
    selection_changed = Signal(object)
    # the dish diameter (mm) the calibration now stands for, after Set plate / the ruler /
    # an undo of either -- so the tab's Dish box can follow (None = no dish to express it by)
    calibration_changed = Signal(object)
    # emitted once, when the first unsaved hand edit is made on this plate
    dirty_changed = Signal(bool)

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
        # None when there is no dish to express the calibration by.
        self.plate_mm = ((self.ppm * self.plate["diam_px"])
                         if (self.ppm and self.plate and self.plate.get("diam_px")) else None)
        # where the mm scale came from: "dish" (auto), "embedded scale", "none", or -- by hand --
        # "set plate" / "ruler". The by-hand values make the result "edited" (CT-R1 F6).
        self._calib_source = ("dish" if (self.ppm and self.plate) else
                              ("embedded scale" if self.ppm else "none"))
        self._dish_pts = []          # rim points collected by the "Set dish" tool
        self._dish_markers = []      # their on-screen dots
        self._plate_items = []       # the drawn dish circle + label (so we can redraw)
        self._scale_pts = []         # two points for the "Calibrate from ruler" tool
        self._scale_markers = []     # their on-screen dots/line
        self._uid = 0
        self._plaques = []
        for p in det.get("plaques", []):
            q = dict(p); q["_uid"] = self._next_uid(); self._plaques.append(q)
        self._det_uids = set(p["_uid"] for p in self._plaques)   # the detection result, for "edited"
        self._reorder()          # number 1..N top-to-bottom from the very first render
        self._retag()
        self.tool = TOOL_SELECT
        self.selected = set()
        self._undo = []
        self._redo = []
        self._dish_step_open = False    # consecutive Dish-box changes merge into one undo step
        # CT-R1 F8: set by any edit that Open / Re-detect / Orient would throw away (a plaque
        # edit, a hand calibration, a scale-bar change). Never cleared: a new detection makes
        # a new editor.
        self.dirty = False
        self._overlay = []
        self._auto_fit = True
        self._fit_scale = None
        # figure style shared with the export (CT-R1 F9/F12)
        self.label_mode = "numbers"     # one of pgui.LABEL_MODES
        self.key_on_figure = False
        self._layout_cache = None
        self._key_item = None
        self._key_rect = None
        self._key_cache = None
        # scale bar state
        self._scalebar_mm = None        # None = auto length
        self._scalebar_anchor = None    # (x,y) image px of the bar's left end; None = auto
        self._scalebar_rgb = (255, 255, 255)   # bar/label colour (RGB)
        self._sb_items = []
        self._sb_g = None               # scalebar.bar_geometry of the current bar
        self._sb_geom = None            # (x0, y0, len_px) of the current bar (legacy readers)

        self.scene = QGraphicsScene(self)
        pm = _rgb_to_pixmap(det["display_rgb"])
        self.scene.addPixmap(pm)
        self.scene.setSceneRect(QRectF(pm.rect()))
        self.view = _View(self); self.view.setScene(self.scene)
        self.view.setMinimumHeight(170)

        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(6)
        lay.addWidget(self._build_toolbar())
        # CT-R1 F11: every tool reports here, so it sits ABOVE the image (it used to be the
        # last widget, below the fold). Fixed height: a longer message must not resize the view.
        self.hint = QLabel(); self.hint.setObjectName("ModeHelp"); self.hint.setWordWrap(True)
        self.hint.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.hint.setFixedHeight(self.hint.fontMetrics().lineSpacing() * 2 + 4)
        self.hint.setToolTip(_HELP)
        lay.addWidget(self.hint)
        lay.addWidget(self.view, 1)
        lay.addWidget(self._build_key_row())

        # undo / redo from anywhere in the editor (a toolbar click moves the focus off the image)
        for seq, slot in ((QKeySequence.Undo, self._undo_last), (QKeySequence.Redo, self._redo_last)):
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(slot)

        self._draw_plate()
        self._draw_scalebar()
        self._refresh_key()
        self._render()
        self._update_hint()

    def _next_uid(self):
        self._uid += 1
        return self._uid

    # ---- public surface ---------------------------------------------------- #
    @property
    def plaques(self):
        return self._plaques

    def selected_uids(self):
        """Selected plaque _uid values, in top-down plaque order."""
        return [p.get("_uid") for p in self._plaques if p.get("_uid") in self.selected]

    def get_selected_plaques(self):
        """Plaque dicts currently selected on the canvas (top-down order)."""
        return [p for p in self._plaques if p.get("_uid") in self.selected]

    def select_uids(self, uids):
        """Set the canvas selection to the given _uid values and redraw. Does NOT re-emit
        selection_changed — used by the table→canvas sync to avoid a feedback loop."""
        self.selected = set(u for u in (uids or []) if u is not None)
        self._render(); self._update_hint()

    def _emit_selection(self):
        self.selection_changed.emit(self.selected_uids())

    def _det_flag(self, key):
        d = getattr(self, "det", None)
        return d.get(key) if isinstance(d, dict) else None

    # ---- the ONE description of this result that every export is built from -- #
    @property
    def edited(self):
        """True when the plaque set differs from the detection result (anything added or
        removed) or the mm scale was set by hand. This is what run_metadata.json records."""
        return (set(p.get("_uid") for p in self._plaques) != self._det_uids
                or self._calib_source in ("set plate", "ruler"))

    def edit_summary(self):
        cur = set(p.get("_uid") for p in self._plaques)
        return {"n_added": len(cur - self._det_uids), "n_removed": len(self._det_uids - cur),
                "calibration": self._calib_source}

    def counts(self):
        """How the plaques on screen came about: {'detected', 'detect_area', 'by_hand'}."""
        cls = [pgui.plaque_class(p) for p in self._plaques]
        return {"detected": sum(c in ("auto", "watershed", "nosize") for c in cls),
                "detect_area": sum(c == "region" for c in cls),
                "by_hand": sum(c == "manual" for c in cls)}

    def export_state(self):
        """Engine flags, dish size and edit state of THIS result, read from the detection
        result's own flags and the editor's current calibration -- never from the engine
        module's globals, which the Batch / Compare tabs and the next detection overwrite
        (CT-R1 F6/F7: Save recorded "Current" for a Sensitive result after a Batch run, and
        the Data-table CSV sized two plaques by another engine's rule)."""
        d = self.det if isinstance(self.det, dict) else {}
        pub = bool(d.get("published"))
        dish_mm = ((self.ppm * self.plate["diam_px"])
                   if (self.ppm and self.plate and self.plate.get("diam_px")) else None)
        return {"published": pub, "precise": bool(d.get("precise")),
                "sensitive": bool(d.get("sensitive")) and not pub, "small": bool(d.get("small")),
                "watershed": bool(d.get("watershed")) and not pub,
                "plate_mm": (round(float(dish_mm), 3) if dish_mm else None),
                "edited": self.edited, "edits": self.edit_summary(),
                "source_image": d.get("source_image") or self.image_path,
                "orientation": list(d.get("orientation") or []),
                # plaque-size scale and dish provenance (CT-R1 detection D1-D4)
                "scale": d.get("scale"),
                "detection": dict({k: d[k] for k in ("scale", "dish_source", "dish_reason",
                                                     "n_outside_dish", "dish_warnings")
                                   if k in d},
                                  # CT-R2 N5: the plaques NOW on the plate, by SOURCE value
                                  **({"sources": pgui.source_counts_now(self._plaques)}
                                     if d.get("sources") is not None else {}))}

    def _pub(self):
        """The result's own Published flag (None only for a result that carries none)."""
        return self._det_flag("published")

    def table(self, with_reason=False):
        """The per-plaque table of what is on screen. The table widget, Save results' numbers,
        Export all and More > Data table (CSV) all come from here."""
        return engine_api.measure_table(self._plaques, self.orig_bgr, self.ppm, self.lawn_gray,
                                        published=self._pub(), plate=self.plate,
                                        with_reason=with_reason)

    def _figure_kwargs(self):
        """How the plate figure is drawn right now -- the canvas and every exported image."""
        return dict(plate=self.plate, scalebar_mm=self._scalebar_mm,
                    scalebar_anchor=self._scalebar_anchor, scalebar_color=self._sb_bgr(),
                    published=self._pub(), precise=bool(self._det_flag("precise")),
                    key=bool(self.key_on_figure))

    def save(self):
        st = self.export_state()
        res = pgui.save_results(
            self._plaques, self.orig_bgr, self.image_path, self.out_dir, self.ppm, self.lawn_gray,
            labels=self.label_mode, write_key=True,
            sensitive=st["sensitive"], small=st["small"], watershed=st["watershed"],
            plate_mm=st["plate_mm"], edited=st["edited"], edits=st["edits"],
            source_image=st["source_image"], orientation=st["orientation"],
            detection=st["detection"], **self._figure_kwargs())
        self.mark_saved()
        return res

    # ---- toolbar ----------------------------------------------------------- #
    def _build_toolbar(self):
        bar = QWidget()
        pol = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        pol.setHeightForWidth(True); bar.setSizePolicy(pol)
        bar.setStyleSheet(_BTN_QSS)
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
        toolbtn(TOOL_FREEHAND, "Draw shape",
                "Freehand-trace any outline: press and drag all the way around an irregular "
                "plaque, then release. For comet/blob shapes the auto-trace can't follow.")
        toolbtn(TOOL_REGION, "Detect area",
                "Drag a tight box; the detector re-scans inside it with the SAME engine that made "
                "the result on screen and adds the plaques it finds (orange, 'detect-area').")
        toolbtn(TOOL_ERASE, "Erase",
                "Click a detection to remove it (or right-click anything, in any tool).")
        toolbtn(TOOL_DISH, "Set plate",
                "Calibrate: click 3 points on the real plate/agar rim, then type its diameter in mm "
                "(e.g. 85 for your agar area). The mm scale is set from your circle — fixes wrong "
                "auto-detection and gives true sizes.")
        toolbtn(TOOL_SCALE, "Ruler",
                "Calibrate from a known distance: click TWO points (e.g. two ruler marks, or the "
                "two sides of the dish), then type the real distance in mm. Use it when no dish "
                "was found or the photo shows a ruler.")

        flow.addWidget(QLabel(" Trace tol:"))
        self.trace_tol = QSpinBox(); self.trace_tol.setRange(1, 100); self.trace_tol.setValue(20)
        self.trace_tol.setFixedWidth(58)
        self.trace_tol.setToolTip("Auto-trace sensitivity for the Add tool (flood-fill tolerance). "
                                  "Higher grabs fainter / larger boundaries; lower stays tighter. "
                                  "Default 20.")
        flow.addWidget(self.trace_tol)

        def actbtn(text, slot, tip):
            b = QPushButton(text); b.setToolTip(tip); b.clicked.connect(slot)
            flow.addWidget(b); return b

        actbtn("Select all", self._select_all, "Select every plaque (Ctrl+A).")
        actbtn("Deselect all", self._clear_selection, "Clear the selection (Esc).")
        self.rm_btn = actbtn("Remove selected", self._remove_selected,
                             "Delete every selected (red) plaque. Shortcut: Delete.")
        self.undo_btn = actbtn("Undo", self._undo_last,
                               "Undo the last change — plaque edits and Set plate / Ruler "
                               "calibrations (Ctrl+Z, or u).")
        self.redo_btn = actbtn("Redo", self._redo_last, "Redo what you just undid (Ctrl+Shift+Z).")

        zout = QPushButton("–"); zout.setFixedWidth(34); zout.setToolTip("Zoom out (– / wheel)")
        zout.clicked.connect(lambda: self.view.zoom_by(1.0 / 1.25)); flow.addWidget(zout)
        zfit = QPushButton("Fit"); zfit.setToolTip("Zoom to fit the whole plate (0).")
        zfit.clicked.connect(self._reset_view); flow.addWidget(zfit)
        zin = QPushButton("+"); zin.setFixedWidth(34); zin.setToolTip("Zoom in (+ / wheel)")
        zin.clicked.connect(lambda: self.view.zoom_by(1.25)); flow.addWidget(zin)

        flow.addWidget(QLabel(" Labels:"))
        self.label_combo = QComboBox()
        for mode in pgui.LABEL_MODES:
            self.label_combo.addItem(mode, mode)
        self.label_combo.setToolTip("What is written beside each plaque, here AND in every exported "
                                    "image: its number, its number and diameter, or nothing.")
        self.label_combo.currentIndexChanged.connect(self._label_mode_changed)
        flow.addWidget(self.label_combo)

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
        exp.setToolTip("One click: save the data table (CSV), the annotated figure and its legend "
                       "key to the 'out' folder next to your image, then open that folder.")
        exp.clicked.connect(self.export_all)
        flow.addWidget(exp)

        more = QPushButton("More ▾")
        more.setToolTip("More export options — individual files.")
        menu = QMenu(more)
        menu.addAction("Everything (CSV + annotated figure + legend key)", self.export_all)
        menu.addSeparator()
        menu.addAction("Data table (CSV)…", self.export_csv)
        menu.addAction("Annotated figure (PNG / TIFF / JPEG / PDF / SVG)…", self.export_figure)
        menu.addAction("Legend key…", self.export_legend_key)
        menu.addAction("Input vs annotated (side-by-side)…", self.export_comparison)
        menu.addAction("Original input image…", self.export_input)
        menu.addAction("Cropped plate for Fiji (calibrated TIFF)…", self.export_plate_crop)
        menu.addAction("Fiji registration bundle (crop + ROIs + map)…", self.export_fiji_bundle)
        menu.addAction("Ground-truth labels…", self.export_groundtruth)
        more.setMenu(menu)
        self.more_menu = menu
        flow.addWidget(more)

        self._btns[TOOL_SELECT].setChecked(True)
        return bar

    def _build_key_row(self):
        """The legend key of the plate figure (the standing figure rule): one text box with the
        legend text starter, Copy, the 'Place key on figure' switch and the key export."""
        row = QWidget(); row.setStyleSheet(_BTN_QSS)
        rl = QHBoxLayout(row); rl.setContentsMargins(0, 0, 0, 0); rl.setSpacing(6)
        cap = QLabel("Legend text"); cap.setObjectName("FieldLabel")
        self.key_text = QLineEdit(); self.key_text.setReadOnly(True)
        self.key_text.setPlaceholderText("no plaques on this plate")
        self.key_text.setToolTip("Legend text starter: every outline colour on THIS plate in words. "
                                 "Copy it into your figure legend and edit it.")
        self.key_copy_btn = QPushButton("Copy")
        self.key_copy_btn.setToolTip("Copy the legend text to the clipboard.")
        self.key_copy_btn.clicked.connect(self._copy_key_text)
        self.key_cb = QCheckBox("Place key on figure")
        self.key_cb.setToolTip("Draw the legend key on the plate itself (top-right corner), here "
                               "and in every exported image. It is the same key as “Legend key…”.")
        self.key_cb.toggled.connect(self._key_toggled)
        self.key_text.setMinimumWidth(40)
        # the key itself is saved from More ▾ > "Legend key…" (and by Export all); a second
        # button here made the row too wide for a small window
        rl.addWidget(cap); rl.addWidget(self.key_text, 1); rl.addWidget(self.key_copy_btn)
        rl.addWidget(self.key_cb)
        return row

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
            self._update_hint("Set plate: click 3 points around the dish rim; the mm scale "
                              "re-calibrates to your circle.")
        elif key == TOOL_SCALE:
            self._update_hint("Ruler: click TWO points a known distance apart (e.g. two ruler "
                              "marks); you'll type the real mm and the scale is set directly.")
        elif key == TOOL_FREEHAND:
            self._update_hint("Draw shape: press and drag all the way around an irregular plaque, "
                              "then release to store the outline (measured by its true area).")
        else:
            self._update_hint()

    def _mark_dirty(self):
        if not self.dirty:
            self.dirty = True
            self.dirty_changed.emit(True)
        self._update_hint_base()

    def mark_saved(self):
        """The edits on screen are now in a file (Save results / Export all): Open, Re-detect
        and Orient no longer need to ask. `edited` (what run_metadata.json records) is not
        affected -- the result still differs from the detection."""
        if self.dirty:
            self.dirty = False
            self.dirty_changed.emit(False)
        self._update_hint_base()

    def _update_hint_base(self):
        # keep the current message, refresh only the state part (" · unsaved edits")
        try:
            msg = self._hint_msg
        except AttributeError:
            msg = None
        if hasattr(self, "hint"):
            self._update_hint(msg)

    def _label_mode_changed(self, _idx=0):
        self.label_mode = self.label_combo.currentData() or "numbers"
        self._layout_cache = None
        self._render()
        self._update_hint("labels: %s (on screen and in exported images)" % self.label_mode)

    def set_label_mode(self, mode):
        """Programmatic twin of the Labels box."""
        i = self.label_combo.findData(mode)
        if i >= 0:
            self.label_combo.setCurrentIndex(i)

    def _scale_changed(self, _idx):
        val = self.scale_combo.currentData()
        if val == "custom":
            cur = self._scalebar_mm if isinstance(self._scalebar_mm, (int, float)) and self._scalebar_mm else 5.0
            num, ok = QInputDialog.getDouble(self, "Custom scale bar", "Scale-bar length (mm):",
                                             float(cur), 0.01, 1000.0, 2)
            if not ok:
                self.scale_combo.blockSignals(True); self.scale_combo.setCurrentIndex(0)
                self.scale_combo.blockSignals(False)
                self._scalebar_mm = None; self._draw_scalebar(); self._render(); return
            self._scalebar_mm = float(num)
        else:
            self._scalebar_mm = val
        self._mark_dirty()
        self._draw_scalebar(); self._render()
        g = self._sb_g
        if g and g["shortened"] and self._scalebar_mm:
            self._update_hint("a %g mm bar does not fit on this image: showing %s (also in exports)"
                              % (self._scalebar_mm, g["label"]))
        elif not self.ppm and self._scalebar_mm:
            self._update_hint("no mm scale on this plate yet, so the bar is in pixels — "
                              "use Set plate or the Ruler first")
        else:
            self._update_hint("scale bar = %s" % (("%g mm" % self._scalebar_mm) if self._scalebar_mm else "auto"))

    def _pick_scalebar_color(self):
        c = QColorDialog.getColor(QColor(*self._scalebar_rgb), self, "Scale-bar colour")
        if c.isValid():
            self._scalebar_rgb = (c.red(), c.green(), c.blue())
            self._mark_dirty()
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
        # CT-R1 F25: the dish label ("dish Ø=1177 px · axis 1.01 · 0.0764 mm/px") was drawn on
        # the image and ran along the dashed rim, reading as struck through. A plate that fills
        # the photo leaves no free spot inside it, so the same facts are now in the line above
        # the image (_dish_tag, shown by _update_hint) and nothing is written over the dish.

    def _dish_tag(self):
        """'dish Ø 1177 px · axis 1.01' for the feedback line (empty when no dish is known)."""
        if not self.plate:
            return ""
        diam = self.plate.get("diam_px") or (2 * self.plate["radius"])
        tag = "dish Ø %.0f px" % diam
        ar = self.plate.get("axis_ratio")
        if ar:
            tag += " · axis %.2f%s" % (ar, " (tilted!)" if ar > 1.03 else "")
        return tag

    # ---- manual dish / re-calibration -------------------------------------- #
    def _dish_click(self, scene_pt):
        """Collect a rim point; after the 3rd, fit a circle and re-calibrate."""
        self._dish_pts.append((scene_pt.x(), scene_pt.y()))
        m = QGraphicsEllipseItem(scene_pt.x() - 7, scene_pt.y() - 7, 14, 14)
        mp = QPen(QColor(0, 200, 255)); mp.setCosmetic(True); mp.setWidth(2)
        m.setPen(mp); m.setZValue(9); self.scene.addItem(m); self._dish_markers.append(m)
        need = 3 - len(self._dish_pts)
        if need > 0:
            self._update_hint("Set plate: click %d more point(s) on the dish rim." % need)
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
            float(self.plate_mm or self._det_flag("plate_mm_requested") or 90.0), 0.1, 1000.0, 2)
        if not ok or mm <= 0:
            self._update_hint("plate calibration cancelled")
            return
        self._apply_dish(cx, cy, r, diam_mm=mm)

    def _scale_click(self, scene_pt):
        """Collect two points a known distance apart, then set mm/px directly from the ruler."""
        self._scale_pts.append((scene_pt.x(), scene_pt.y()))
        m = QGraphicsEllipseItem(scene_pt.x() - 7, scene_pt.y() - 7, 14, 14)
        mp = QPen(QColor(0, 220, 120)); mp.setCosmetic(True); mp.setWidth(2)
        m.setPen(mp); m.setZValue(9); self.scene.addItem(m); self._scale_markers.append(m)
        if len(self._scale_pts) < 2:
            self._update_hint("Ruler: click the SECOND point a known distance away (a ruler mark).")
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
            self._update_hint("ruler calibration cancelled"); return
        self._apply_ruler_scale(mm / px)

    def _sync_det(self):
        """Mirror the calibration into the shared detection dict (older readers use it)."""
        try:
            self.det["plate"] = self.plate
            self.det["pxl_per_mm"] = self.ppm
        except Exception:
            pass

    def _apply_ruler_scale(self, ppm):
        """Set mm/px directly from a ruler measurement (independent of dish detection)."""
        self._push_undo("the Ruler calibration")   # CT-R1 F20: a calibration can be undone
        self.ppm = float(ppm)
        self._calib_source = "ruler"
        # keep plate_mm consistent so the Set-dish tool still works afterward
        if self.plate and self.plate.get("diam_px"):
            self.plate_mm = self.ppm * self.plate["diam_px"]
        self._sync_det()
        self._retag(); self._refresh_key()
        self._layout_cache = None
        self._draw_plate(); self._draw_scalebar(); self._render()
        self._update_hint("scale set from the ruler: %.4f mm/px  (%.2f px/mm) — Undo restores the old scale"
                          % (self.ppm, (1.0 / self.ppm) if self.ppm else 0.0))
        self.calibration_changed.emit(self.plate_mm)
        if self._on_change:
            self._on_change()

    def _apply_dish(self, cx, cy, r, diam_mm=None):
        """Set the dish to a manual circle and recompute mm/px. diam_mm = the real
        diameter (mm) of the rim just drawn; when given it becomes the working plate size."""
        self._push_undo("the Set plate calibration")   # CT-R1 F20: a calibration can be undone
        diam = 2.0 * r
        self.plate = {"center": (cx, cy), "radius": r, "diam_px": diam, "axis_ratio": 1.0}
        if diam_mm and diam_mm > 0:
            self.plate_mm = float(diam_mm)
        if self.plate_mm and diam > 0:
            self.ppm = float(self.plate_mm) / diam
        self._calib_source = "set plate"
        # propagate to the shared detection dict so the table + summary card recompute
        self._sync_det()
        self._retag(); self._refresh_key()
        self._layout_cache = None
        self._draw_plate(); self._draw_scalebar(); self._render()
        self._update_hint("plate set by hand: Ø=%.0f px = %g mm · %.4f mm/px — Undo restores the old scale"
                          % (diam, self.plate_mm or 0.0, self.ppm or 0.0))
        self.calibration_changed.emit(self.plate_mm)
        if self._on_change:
            self._on_change()

    def set_plate_mm(self, mm):
        """Live re-scale the CURRENT result to a new dish diameter (mm), reusing the already-
        detected dish's pixel diameter — no re-detection. Called when the Dish box or the
        85/100 quick-picks change. Returns False if no dish was detected. mm<=0 => pixels only."""
        diam_px = (self.plate or {}).get("diam_px")
        if not diam_px:
            self._update_hint("no dish outline on this image, so the Dish size has nothing to "
                              "rescale — use Set plate or the Ruler")
            return False
        mm = float(mm)
        # CT-R2 N6: a Dish-box change is its own undo step, so undoing a plaque edit never
        # changes the calibration silently. Typing "85" fires twice ("8", "85"): consecutive
        # Dish changes with nothing in between are ONE step, named from its first value.
        if self._dish_step_open and self._undo:
            start = self._undo[-1].get("dish_from")
        else:
            start = self.plate_mm
            self._push_undo("the Dish size change", dirty=False)
            self._undo[-1]["dish_from"] = start
        self._undo[-1]["what"] = "the Dish size change (%s → %g mm)" % (
            ("%g mm" % start) if start else "pixels only", mm)
        self._dish_step_open = True
        if mm <= 0:
            self.plate_mm = 0.0
            self.ppm = None
        else:
            self.plate_mm = mm
            self.ppm = mm / float(diam_px)
        # CT-R2 N7: the scale now comes from the dish and the Dish box, whatever set it before
        # (the Ruler included) -- except a rim drawn by hand with Set plate, which stays a hand
        # calibration ("set plate", so the result still counts as edited)
        self._calib_source = "set plate" if self._calib_source == "set plate" else "dish"
        self._sync_det()
        self._retag(); self._refresh_key()
        self._layout_cache = None
        self._draw_plate(); self._draw_scalebar(); self._render()
        self._update_hint("dish = %g mm  ->  %s"
                          % (mm, ("%.4f mm/px" % self.ppm) if self.ppm else "pixels only"))
        if self._on_change:
            self._on_change()
        return True

    # ---- scale bar: geometry from scalebar.bar_geometry, as in every export -- #
    def _scalebar_mm_used(self):
        """The mm length the bar draws at (resolves 'Auto', and a length that does not fit)."""
        g = self._sb_g
        return g["value"] if (g and g["unit"] == "mm") else None

    def _draw_scalebar(self):
        """(Re)draw the scale bar from the SAME geometry function the exports use, so the bar
        on screen is the bar in the file: clamped inside the image, label centred above."""
        for it in self._sb_items:
            try:
                self.scene.removeItem(it)
            except Exception:
                pass
        self._sb_items = []
        g = sbmod.bar_geometry(self.orig_bgr.shape, self.ppm, anchor=self._scalebar_anchor,
                               length_mm=self._scalebar_mm, plate=self.plate)
        self._sb_g = g
        if g is None:
            self._sb_geom = None
            return
        x0, y0, lpx, th, o = g["x0"], g["y0"], g["length_px"], g["thickness"], g["outline"]
        back = QGraphicsRectItem(x0 - o, y0 - o, lpx + 2 * o, th + 2 * o)
        back.setPen(QPen(Qt.NoPen)); back.setBrush(QBrush(QColor(0, 0, 0)))
        back.setZValue(20); self.scene.addItem(back); self._sb_items.append(back)
        bar = QGraphicsRectItem(x0, y0, lpx, th)
        bar.setPen(QPen(Qt.NoPen)); bar.setBrush(QBrush(QColor(*self._scalebar_rgb)))
        bar.setZValue(21); self.scene.addItem(bar); self._sb_items.append(bar)
        t = QGraphicsSimpleTextItem(g["label"]); t.setBrush(QColor(*self._scalebar_rgb))
        _op = QPen(QColor(0, 0, 0)); _op.setWidthF(0.6); _op.setCosmetic(True); t.setPen(_op)
        t.setFont(_canvas_font(9))
        t.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        br = t.boundingRect()
        if g["label_above"]:
            t.setPos(g["label_cx"], y0 - g["gap"])
            t.setTransform(QTransform.fromTranslate(-br.width() / 2.0, -br.height()))
        else:
            t.setPos(g["label_cx"], y0 + th + g["gap"])
            t.setTransform(QTransform.fromTranslate(-br.width() / 2.0, 0))
        t.setZValue(22)
        self.scene.addItem(t); self._sb_items.append(t)
        self._sb_geom = (x0, y0, lpx)

    def _sb_hit(self, scene_pt):
        """True if scene_pt is on/near the scale bar (so a drag moves it instead of editing)."""
        g = self._sb_g
        if not g:
            return False
        m = 0.02 * self.orig_bgr.shape[1]
        top = g["y0"] - g["gap"] - 1.8 * g["label_h"]
        return ((g["x0"] - m <= scene_pt.x() <= g["x0"] + g["length_px"] + m)
                and (top <= scene_pt.y() <= g["y0"] + g["thickness"] + m))

    def _move_scalebar(self, dx, dy):
        g = self._sb_g
        if not g:
            return
        H, W = self.orig_bgr.shape[:2]
        bx, by = self._scalebar_anchor if self._scalebar_anchor is not None else (g["x0"], g["y0"])
        # the same limits bar_geometry applies, so the bar cannot be dragged off the image
        # (CT-R1 F19) and what is stored is what the export will draw
        x_lo, x_hi = g["pad"], max(g["pad"], W - g["pad"] - g["length_px"])
        y_lo = g["label_h"] + g["label_base"] + g["gap"] + 2
        y_hi = max(y_lo, H - g["thickness"] - g["pad"])
        self._scalebar_anchor = (min(max(bx + dx, x_lo), x_hi), min(max(by + dy, y_lo), y_hi))
        self._mark_dirty()
        self._draw_scalebar()
        self._layout_cache = None

    # ---- legend key -------------------------------------------------------- #
    def legend_key(self):
        """The key of the plate figure as it is NOW (plaque_stats.legend_key dict, or None)."""
        return pgui.plate_key(self._plaques, precise=bool(self._det_flag("precise")))

    def _refresh_key(self):
        """Bring the legend text and (if switched on) the key drawn on the image up to date
        with the plaques on screen."""
        key = None
        try:
            key = self.legend_key()
            from plaque_stats import legend_key
            self.key_text.setText(legend_key.text_starter(key) if key else "")
            self.key_text.setCursorPosition(0)
        except Exception:                               # noqa: BLE001 -- a key never blocks editing
            key = None
        if self._key_item is not None:
            try:
                self.scene.removeItem(self._key_item)
            except Exception:
                pass
            self._key_item = None
        self._key_rect = None
        if not (self.key_on_figure and key):
            return
        try:
            from plaque_stats import legend_key
            sig = tuple(legend_key.entries_signature(key))
            if self._key_cache is None or self._key_cache[0] != sig:
                self._key_cache = (sig, pgui.key_image_for(self.orig_bgr.shape, key))
            patch = self._key_cache[1]
            if patch is None:
                return
            x, y = pgui.key_origin(self.orig_bgr.shape, patch.shape)
            item = QGraphicsPixmapItem(_rgb_to_pixmap(cv2.cvtColor(patch, cv2.COLOR_BGR2RGB)))
            item.setPos(x, y); item.setZValue(24)
            self.scene.addItem(item)
            self._key_item = item
            self._key_rect = (x, y, x + patch.shape[1], y + patch.shape[0])
        except Exception:                               # noqa: BLE001
            self._key_item = None; self._key_rect = None

    def _key_toggled(self, on):
        self.key_on_figure = bool(on)
        self._layout_cache = None
        self._refresh_key()
        self._render()
        self._update_hint("legend key %s the figure (on screen and in exported images)"
                          % ("placed on" if on else "removed from"))

    def _copy_key_text(self):
        QApplication.clipboard().setText(self.key_text.text())
        self._update_hint("legend text copied to the clipboard" if self.key_text.text()
                          else "no plaques on this plate, so there is no legend text to copy")

    def _clear_overlay(self):
        for it in self._overlay:
            try:
                self.scene.removeItem(it)
            except Exception:
                pass
        self._overlay = []

    def _label_layout(self):
        """[(text, side, bbox)] per plaque for the current label mode, or None for 'none'.
        Computed by the export's own functions at the export's sizes, so each label hangs off
        the same side of its plaque on screen and in the file. Cached until something that
        can move a label changes (selection changes re-render without re-planning)."""
        if self.label_mode == "none" or not self._plaques:
            return None
        g = self._sb_g
        sig = (tuple((p.get("_uid"), p.get("qc_flag")) for p in self._plaques), self.label_mode, self.ppm,
               (g["x0"], g["y0"], g["length_px"], g["label"]) if g else None, self._key_rect)
        if self._layout_cache is not None and self._layout_cache[0] == sig:
            return self._layout_cache[1]
        m = pgui.figure_metrics(self.orig_bgr.shape)
        texts = [pgui.label_text(i, p["area_pxl"], self.ppm, self.label_mode, self._pub(),
                                 note=pgui.size_note(p))
                 for i, p in enumerate(self._plaques, start=1)]
        sizes = [pgui.text_size(s, m["font_px"], m["stroke"]) for s in texts]
        avoid = [pgui.scalebar_rect(g)] if g else []
        if self._key_rect:
            avoid.append(self._key_rect)
        placed = pgui.layout_labels(self._plaques, sizes, self.orig_bgr.shape, m["gap"], avoid=avoid)
        out = [(s, side, pgui.plaque_bbox(p)) for s, (side, _r), p in zip(texts, placed, self._plaques)]
        self._layout_cache = (sig, out)
        return out

    def _render(self):
        self._clear_overlay()
        labels = self._label_layout()
        font = _canvas_font(8)
        num_pen = QPen(QColor(0, 0, 0)); num_pen.setWidthF(0.6); num_pen.setCosmetic(True)
        for i, p in enumerate(self._plaques):
            sel = p.get("_uid") in self.selected
            # colour and line style from the one class map the exports use (pgui.PLAQUE_CLASSES)
            _name, rgb, style = pgui.PLAQUE_CLASSES[pgui.plaque_class(p, bool(p.get("overlap")))]
            pen = QPen(_SEL if sel else QColor(*rgb), 2.4 if sel else 1.4); pen.setCosmetic(True)
            if style == "dashed" and not sel:
                pen.setStyle(Qt.DashLine)      # dashed + pink = "overlaps a neighbour"
            elif style == "dotted" and not sel:
                pen.setStyle(Qt.DotLine)       # dotted = counted, size not used (CT-R2 N3)
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
            if labels is None:
                continue
            text, side, bbox = labels[i]
            t = QGraphicsSimpleTextItem(text)
            # white glyph with a thin dark outline: readable on any background and
            # colour-blind-safe (was pure yellow, which washed out on pale plates)
            t.setBrush(QColor(255, 255, 255))
            t.setPen(num_pen)
            t.setFont(font)
            t.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
            # hang the label just outside the outline, on the side the export puts it
            ax, ay, dx, dy = pgui.label_anchor(bbox, side)
            br = t.boundingRect()
            gap = 3.0
            t.setPos(ax, ay)
            t.setTransform(QTransform.fromTranslate(
                dx * gap - (br.width() if dx < 0 else (br.width() / 2.0 if dx == 0 else 0.0)),
                dy * gap - (br.height() if dy < 0 else (br.height() / 2.0 if dy == 0 else 0.0))))
            t.setZValue(11)
            self.scene.addItem(t); self._overlay.append(t)

    def _update_hint(self, msg=None):
        cal = (f"{self.ppm:.4f} mm/px" if self.ppm else "pixels only (no mm scale)")
        nsel = len(self.selected)
        dish = self._dish_tag()
        base = (f"{len(self._plaques)} plaques"
                + (f" · {nsel} selected" if nsel else "")
                + (f" · {dish}" if dish else "")
                + f" · {cal}" + (" · unsaved edits" if self.dirty else ""))
        self._hint_msg = msg
        self.hint.setText((msg + "   ·   " + base) if msg else (base + "   —   hover here for the mouse and key shortcuts"))

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

    def _in_image(self, x, y):
        H, W = self.orig_bgr.shape[:2]
        return 0 <= x <= W - 1 and 0 <= y <= H - 1

    # ---- selection --------------------------------------------------------- #
    def _toggle_select_at(self, scene_pt):
        idx = self._find(scene_pt.x(), scene_pt.y())
        if idx is None:
            self._clear_selection(); return
        uid = self._plaques[idx].get("_uid")
        (self.selected.discard if uid in self.selected else self.selected.add)(uid)
        self._render(); self._update_hint(); self._emit_selection()

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
        self._emit_selection()

    def _select_all(self):
        self.selected = set(p.get("_uid") for p in self._plaques)
        self._render(); self._update_hint("selected all %d" % len(self.selected))
        self._emit_selection()

    def _clear_selection(self):
        if self.selected:
            self.selected.clear(); self._render()
        self._update_hint("selection cleared")
        self._emit_selection()

    def _remove_selected(self):
        if not self.selected:
            self._update_hint("nothing selected — click plaques (they turn red) first")
            return
        self._push_undo("the removal of %d selected plaque(s)" % len(self.selected))
        n = len(self.selected)
        self._plaques = [p for p in self._plaques if p.get("_uid") not in self.selected]
        self.selected.clear()
        self._changed(f"removed {n} selected plaque(s)")

    # ---- edit operations --------------------------------------------------- #
    def _snapshot(self):
        """Everything Undo restores: the plaques, the selection AND the calibration (Set plate
        and the Ruler used to be outside undo; CT-R1 F20)."""
        return {"plaques": [dict(p) for p in self._plaques], "selected": set(self.selected),
                "plate": (dict(self.plate) if self.plate else None), "ppm": self.ppm,
                "plate_mm": self.plate_mm, "calib": self._calib_source}

    def _restore(self, s):
        calib_changed = (s["ppm"] != self.ppm or s["plate_mm"] != self.plate_mm
                         or (s["plate"] or {}).get("diam_px") != (self.plate or {}).get("diam_px"))
        self._plaques = [dict(p) for p in s["plaques"]]
        self.selected = set(s["selected"])
        self.plate = dict(s["plate"]) if s["plate"] else None
        self.ppm = s["ppm"]; self.plate_mm = s["plate_mm"]; self._calib_source = s["calib"]
        self._sync_det()
        self._layout_cache = None
        if calib_changed:
            self._draw_plate(); self._draw_scalebar()
            self.calibration_changed.emit(self.plate_mm)

    def _push_undo(self, what="the last change", dirty=True):
        """One undo step, named (`what`) so Undo / Redo can say what they undid (CT-R2 N6)."""
        snap = self._snapshot()
        snap["what"] = what
        self._undo.append(snap)
        if len(self._undo) > 80:
            self._undo.pop(0)
        self._redo = []
        self._dish_step_open = False
        if dirty:
            self._mark_dirty()

    def _reorder(self):
        # Number plaques 1..N top-to-bottom, then left-to-right, so the on-canvas
        # labels, the results table INDEX, the CSV, the annotated figure and the
        # ground-truth export all read in the same human-obvious order with #1 at
        # the top of the image. Selection is by _uid, so it survives reordering.
        self._plaques.sort(key=engine_api.reading_order_key)   # shared with Batch (CT-R1 F17)
        self._mark_overlaps()

    def _mark_overlaps(self):
        """Tag each plaque with p['overlap'] = True when it touches/overlaps a neighbour,
        so _render can flag them and the table/stats can exclude them."""
        flags = engine_api.overlap_flags(self._plaques)
        for p, f in zip(self._plaques, flags):
            p["overlap"] = bool(f)

    def _retag(self):
        """Each plaque's QC flag (the table's own call), so the plaques whose size is not used
        are drawn, labelled and keyed as such on screen exactly as in the export (CT-R2 N3)."""
        pgui.tag_qc(self._plaques, self.orig_bgr, self.ppm, plate=self.plate)

    def _changed(self, msg=None):
        self._reorder()
        self._retag()
        self._refresh_key()
        self._render(); self._update_hint(msg)
        if self._on_change:
            self._on_change()

    def _erase_at(self, scene_pt):
        idx = self._find(scene_pt.x(), scene_pt.y())
        if idx is None:
            self._update_hint("nothing to erase there"); return
        self._push_undo("the erase of plaque %d" % (idx + 1))
        removed = self._plaques.pop(idx)
        self.selected.discard(removed.get("_uid"))
        self._changed("erased 1 plaque (%s)" % pgui.class_name(
            pgui.plaque_class(removed), precise=bool(self._det_flag("precise"))))

    def _add_point(self, scene_pt):
        if not self._in_image(scene_pt.x(), scene_pt.y()):
            self._update_hint("that click is outside the image — click on the plaque itself"); return
        tol = getattr(self, "trace_tol", None)
        tol_val = tol.value() if tol is not None else 20
        res = pgui.trace_at(self.candidates, self.proc_gray, scene_pt.x(), scene_pt.y(), tol=tol_val)
        if res is None:
            self._update_hint("couldn't auto-trace there — raise 'Trace tol', use Draw shape, "
                              "or drag to draw a circle"); return
        hull, area, center = res
        self._commit_new({"source": "manual", "kind": "contour", "_uid": self._next_uid(),
                          "contour": hull, "area_pxl": float(area), "center": center},
                         "added a traced plaque")

    def _add_freehand(self, pts):
        """Store a user-drawn outline as a real (possibly non-convex) contour plaque, so
        irregular shapes are measured by their true area — no circle fit."""
        if len(pts) < 3:
            self._update_hint("draw a longer outline — drag around the plaque, then release"); return
        H, W = self.orig_bgr.shape[:2]
        raw = np.array([[p.x(), p.y()] for p in pts], dtype=float)
        outside = bool((raw[:, 0] < 0).any() or (raw[:, 1] < 0).any()
                       or (raw[:, 0] > W - 1).any() or (raw[:, 1] > H - 1).any())
        if not ((raw[:, 0] >= 0) & (raw[:, 0] <= W - 1) & (raw[:, 1] >= 0) & (raw[:, 1] <= H - 1)).any():
            self._update_hint("that outline is outside the image, so it was not added"); return
        raw[:, 0] = np.clip(raw[:, 0], 0, W - 1); raw[:, 1] = np.clip(raw[:, 1], 0, H - 1)
        arr = np.round(raw).astype(np.int32)
        area = float(cv2.contourArea(arr))
        # CT-R1 F16: a figure-eight has no single area (its two loops cancel) -- say so
        # instead of storing a 20 px "plaque"
        if outline_crosses_itself(arr):
            self._update_hint("that outline crosses itself, so its area cannot be measured — draw "
                              "once around the plaque without crossing your own line"); return
        if area < 4:
            self._update_hint("that outline was too small"); return
        m = cv2.moments(arr)
        if m["m00"]:
            center = (m["m10"] / m["m00"], m["m01"] / m["m00"])
        else:
            center = (float(arr[:, 0].mean()), float(arr[:, 1].mean()))
        self._commit_new({"source": "freehand", "kind": "contour", "_uid": self._next_uid(),
                          "contour": arr.reshape(-1, 1, 2), "area_pxl": area, "center": center},
                         "added a freehand outline" + (" (the part outside the image was left out)"
                                                       if outside else ""))

    def _add_circle(self, center, r):
        cx, cy = center.x(), center.y()
        H, W = self.orig_bgr.shape[:2]
        # CT-R1 F16: an off-image circle became a plaque with MEAN_GRAY 0 and rescaled every
        # other plaque's TURBIDITY_REL
        if not self._in_image(cx, cy):
            self._update_hint("that circle's centre is outside the image, so it was not added — "
                              "start the drag on the plaque"); return
        if self.plate and self.plate.get("radius") and r > float(self.plate["radius"]):
            self._update_hint("that circle is larger than the dish, so it was not added — drag "
                              "from the plaque's centre to its edge"); return
        if cx - r < 0 or cy - r < 0 or cx + r > W - 1 or cy + r > H - 1:
            # only the part on the photo can be measured: store that part as the outline
            cnt = clipped_circle_contour(cx, cy, r, self.orig_bgr.shape)
            area = float(cv2.contourArea(cnt))
            m = cv2.moments(cnt)
            c = (m["m10"] / m["m00"], m["m01"] / m["m00"]) if m["m00"] else (cx, cy)
            self._commit_new({"source": "manual", "kind": "contour", "_uid": self._next_uid(),
                              "contour": cnt, "area_pxl": area, "center": c},
                             "added a circle; it runs past the image edge, so only the part on the "
                             "image is measured (%.0f of %.0f px²)" % (area, math.pi * r * r))
            return
        self._commit_new({"source": "manual", "kind": "circle", "_uid": self._next_uid(),
                          "center": (cx, cy), "radius": float(r),
                          "area_pxl": float(math.pi * r * r)}, "added a circle")

    @staticmethod
    def _contains(p, x, y):
        """True when (x, y) lies inside plaque p's outline."""
        if p["kind"] == "circle":
            r = float(p.get("radius", math.sqrt(max(p["area_pxl"], 1) / math.pi)))
            return math.hypot(x - p["center"][0], y - p["center"][1]) <= r
        return cv2.pointPolygonTest(np.asarray(p["contour"], dtype=np.int32).reshape(-1, 1, 2),
                                    (float(x), float(y)), False) >= 0

    def _replaced_by(self, newp):
        """[(index, why)] of the plaques a new hand outline REPLACES (CT-R2 N4): those flagged
        CORE? (outlined at the dark centre only) or NESTED (inside another plaque) whose centre
        lies inside the new outline -- the user has drawn the plaque they belong to. Any other
        plaque inside it stays: it is a plaque of its own."""
        import plaque_qc
        out = []
        for i, q in enumerate(self._plaques):
            f = q.get("qc_flag")
            if plaque_qc.has_flag(f, "CORE?"):
                why = "dark centre only"
            elif plaque_qc.has_flag(f, "NESTED"):
                why = "inside another plaque"
            else:
                continue
            if self._contains(newp, *q["center"]):
                out.append((i, why))
        return out

    def _commit_new(self, newp, msg):
        """Add a hand-made plaque as ONE undo step; a CORE? / NESTED plaque whose centre it
        contains is replaced, so the count does not grow (CT-R2 N4)."""
        rep = self._replaced_by(newp)
        self._push_undo("the added plaque")
        if rep:
            gone = set(self._plaques[i]["_uid"] for i, _w in rep)
            self._plaques = [q for q in self._plaques if q["_uid"] not in gone]
            self.selected -= gone
            msg = "replaced %s with your outline" % " and ".join(
                "plaque %d (%s)" % (i + 1, w) for i, w in rep)
        self._plaques.append(newp)
        self._changed(msg)

    def _engine_label(self):
        st = self.export_state()
        if st["precise"]:
            return "Precise"
        return "Published" if st["published"] else ("Sensitive" if st["sensitive"] else "Current")

    def _detect_region(self, roi):
        # CT-R1 F20: the tool always ran the Sensitive + small gates, so a Published result
        # gained plaques Published would never accept while still being called Published.
        # It now re-scans with the gates of the engine that produced the result on screen
        # (Precise has no box mode of its own: its classic recall pass is Sensitive + small).
        st = self.export_state()
        if st["precise"]:
            kw = dict(sensitive=True, small=True, published=False)
        else:
            # an Auto result re-scans a box at the small scale too (CT-R1 detection D1)
            kw = dict(sensitive=st["sensitive"], small=st["small"] or st.get("scale") == "auto",
                      published=st["published"])
        eng = self._engine_label()
        try:
            found = engine_api.detect_region(self.orig_bgr, roi, **kw)
        except Exception as e:
            self._update_hint("area detect failed: %s" % e); return
        fresh = [p for p in found if not self._inside_existing(*p["center"])]
        if not fresh:
            self._update_hint("no new plaques in that area with the %s engine's gates — use Add or "
                              "Draw shape for a plaque the engine does not accept" % eng); return
        self._push_undo("the %d Detect-area plaque(s)" % len(fresh))
        for p in fresh:
            p["_uid"] = self._next_uid(); self._plaques.append(p)
        self._changed("added %d detect-area plaque(s) (%s gates)" % (len(fresh), eng))

    def _undo_last(self):
        if not self._undo:
            self._update_hint("nothing to undo"); return
        s = self._undo.pop()
        cur = self._snapshot(); cur["what"] = s.get("what", "the last change")
        self._redo.append(cur)
        self._restore(s)
        self._dish_step_open = False
        # CT-R2 N13: the plate now matches neither the saved files nor the detection
        self._mark_dirty()
        self._changed("undid %s (Ctrl+Shift+Z redoes it)" % s.get("what", "the last change"))

    def _redo_last(self):
        if not self._redo:
            self._update_hint("nothing to redo"); return
        s = self._redo.pop()
        cur = self._snapshot(); cur["what"] = s.get("what", "the change")
        self._undo.append(cur)
        self._restore(s)
        self._dish_step_open = False
        self._mark_dirty()
        self._changed("redid %s" % s.get("what", "the change"))

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
        if self._auto_fit:
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

    def _stem(self):
        return os.path.splitext(os.path.basename(self.image_path))[0]

    _FIG_FILTER = ("PNG image (*.png);;TIFF image (*.tif *.tiff);;JPEG image (*.jpg *.jpeg);;"
                   "PDF (*.pdf);;SVG (*.svg)")

    def _write_figure_file(self, what, path, writer):
        """Run one figure save and ALWAYS say what happened (CT-R1 F22: a .pdf name used to
        fail with nothing saved and nothing said). Returns the path written or None."""
        try:
            out = writer(path)
        except Exception as e:                          # noqa: BLE001
            self._update_hint("could not save the %s: %s" % (what, e))
            self._info("Not saved", "The %s could not be saved to:\n\n%s\n\n%s" % (what, path, e))
            return None
        if os.path.abspath(out) != os.path.abspath(path):
            self._update_hint("'%s' is not a format this can write, so the %s was saved as %s"
                              % (os.path.splitext(path)[1] or "no extension", what, os.path.basename(out)))
        else:
            self._update_hint("saved the %s → %s" % (what, os.path.basename(out)))
        return out

    def export_all(self):
        """One click: write the CSV table + annotated figure + its legend key to the out
        folder and open it."""
        name = self._stem()
        os.makedirs(self.out_dir, exist_ok=True)
        csv_path = os.path.join(self.out_dir, f"data_{name}.csv")
        df = self.table()
        df.to_csv(csv_path, index=False)
        try:                                        # provenance for the app's main export (PT-31)
            st = self.export_state()
            pgui.write_run_metadata(
                self.out_dir, "app/plaque_canvas.export_all", self.image_path, csv_path, len(df),
                self._plaques, self.ppm, published=st["published"], sensitive=st["sensitive"],
                small=st["small"], watershed=st["watershed"], precise=st["precise"],
                plate_mm=st["plate_mm"], edited=st["edited"], edits=st["edits"],
                source_image=st["source_image"], orientation=st["orientation"],
                extra_settings={"mm_per_px": self.ppm, "labels": self.label_mode},
                detection=st["detection"])
        except Exception:                           # noqa: BLE001 -- never block an export
            pass
        fig_path = os.path.join(self.out_dir, f"figure_{name}.png")
        pgui.save_figure(self._plaques, self.orig_bgr, fig_path, self.ppm, labels=self.label_mode,
                         **self._figure_kwargs())
        key_note = ""
        try:                                        # the standing figure rule: the key ships too
            from plaque_stats import legend_key
            if legend_key.write_key_files(self.legend_key(), os.path.splitext(fig_path)[0], formats=("png",)):
                key_note = " + legend key"
        except Exception:                           # noqa: BLE001
            pass
        self.mark_saved()
        self._update_hint("✓ exported %d rows + annotated figure%s → 'out' folder" % (len(df), key_note))
        self._open_folder(self.out_dir)
        return self.out_dir

    def export_csv(self, path=None):
        """Export the per-plaque measurement table (the same rows shown on the right) to CSV."""
        name = self._stem()
        if path is None:
            path = self._ask_path("Export data table (CSV)", f"data_{name}.csv", "CSV (*.csv)")
            if not path:
                return None
        df = self.table()
        try:
            df.to_csv(path, index=False)
        except Exception as e:                          # noqa: BLE001
            self._update_hint("could not save the table: %s" % e)
            return None
        self._update_hint("saved %d rows → %s" % (len(df), os.path.basename(path)))
        self._info("CSV saved", "Saved %d plaque rows to:\n\n%s" % (len(df), path))
        return path

    def export_figure(self, path=None):
        """Download the annotated image (outlines + labels + scale bar) as a figure: PNG, TIFF
        or JPEG, or PDF / SVG; any other extension is saved as PNG and the hint says so."""
        name = self._stem()
        if path is None:
            path = self._ask_path("Download annotated figure", f"figure_{name}.png", self._FIG_FILTER)
            if not path:
                return None
        out = self._write_figure_file(
            "annotated figure", path,
            lambda p: pgui.save_figure(self._plaques, self.orig_bgr, p, self.ppm,
                                       labels=self.label_mode, **self._figure_kwargs()))
        if out:
            self._info("Figure saved", "Annotated figure (with scale bar) saved to:\n\n%s" % out)
        return out

    def export_legend_key(self, path=None):
        """Save the stand-alone legend key of the plate figure: every outline class on THIS
        plate with its colour, line style and plain name (plaque_stats/legend_key.py)."""
        key = self.legend_key()
        if not key:
            self._update_hint("no plaques on this plate, so there is nothing to put in a legend key")
            return None
        name = self._stem()
        if path is None:
            path = self._ask_path("Save legend key", f"figure_{name}_legend_key.png",
                                  "PNG image (*.png);;SVG (*.svg);;PDF (*.pdf);;TIFF image (*.tif *.tiff)")
            if not path:
                return None
        if os.path.splitext(path)[1].lower() not in (".png", ".svg", ".pdf", ".tif", ".tiff"):
            path = path + ".png"
        try:
            from plaque_stats import legend_key
            legend_key.save_key(key, path)
        except Exception as e:                          # noqa: BLE001
            self._update_hint("could not save the legend key: %s" % e)
            return None
        self._update_hint("saved the legend key → %s" % os.path.basename(path))
        return path

    def export_comparison(self, path=None):
        """Download a side-by-side 'input vs annotated output' figure."""
        name = self._stem()
        if path is None:
            path = self._ask_path("Download input vs annotated (side-by-side)",
                                  f"compare_{name}.png", self._FIG_FILTER)
            if not path:
                return None
        out = self._write_figure_file(
            "side-by-side figure", path,
            lambda p: pgui.save_comparison(self._plaques, self.orig_bgr, p, self.ppm,
                                           plaque_labels=self.label_mode, **self._figure_kwargs()))
        if out:
            self._info("Saved", "Input-vs-annotated figure saved to:\n\n%s" % out)
        return out

    def export_input(self, path=None):
        """Download the original input image (decoded; HEIC is written as PNG)."""
        name = self._stem()
        if path is None:
            path = self._ask_path("Download the original input image",
                                  f"input_{name}.png", self._FIG_FILTER)
            if not path:
                return None
        out = self._write_figure_file("input image", path, lambda p: pgui.save_image(self.orig_bgr, p))
        if out:
            self._info("Saved", "Original input image saved to:\n\n%s" % out)
        return out

    def export_plate_crop(self, path=None):
        """Crop the dish region and save a Fiji/ImageJ-calibrated TIFF (mm scale baked in).

        The TIFF opens in Fiji already scaled in millimetres, so cropping a plaque
        there keeps the scale and Analyze > Tools > Scale Bar draws a correct mm bar.
        """
        import plate_crop
        name = self._stem()
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

    def export_fiji_bundle(self, path=None):
        """Write the Fiji registration bundle: calibrated crop + ImageJ ROIs (same numbering)
        + a numbered map + a registration CSV, so the SAME plaque can be compared in Fiji."""
        from app import fiji_export
        name = self._stem()
        dest = path or os.path.join(self.out_dir, f"{name}_fiji")
        try:
            info = fiji_export.save_bundle(self._plaques, self.orig_bgr, self.plate, self.ppm,
                                           self.lawn_gray, dest, name, published=self._pub())
        except Exception as e:
            self._update_hint("the Fiji bundle could not be written: %s" % e)
            self._info("Fiji bundle failed", str(e))
            return None
        cal = "" if info["calibrated"] else (
            "\n\nNote: no dish was detected, so the crop is NOT calibrated — set the scale in "
            "Fiji, or compare by pixels (auto-align).")
        self._update_hint("✓ Fiji bundle (%d plaques) → %s" % (info["n"], os.path.basename(dest)))
        self._open_folder(dest)
        self._info("Fiji registration bundle saved",
                   "Saved for %d plaques to:\n\n%s\n\nOpen '%s_plate.tif' in Fiji, then either "
                   "load '%s_RoiSet.zip' in the ROI Manager (ROI #k = plaque #k), or trace your "
                   "own and use 'Compare vs Fiji…' next to the table.%s\n\n"
                   "'%s_fiji.txt' has the step-by-step."
                   % (info["n"], dest, name, name, cal, name))
        return dest

    def export_groundtruth(self, path=None):
        """Write the corrected plaque set as a reusable labels file (JSON + sibling CSV)."""
        name = self._stem()
        if path is None:
            path = self._ask_path("Save ground-truth labels", f"labels_{name}.json", "Label file (*.json)")
            if not path:
                return None
        recs = []
        for i, p in enumerate(self._plaques, start=1):
            cx, cy = p["center"]
            r_px = math.sqrt(max(p["area_pxl"], 1e-9) / math.pi)
            _dp, _amm, dia_mm = pgui.measure(p["area_pxl"], self.ppm, self._pub())
            recs.append({"index": i, "x_px": round(float(cx), 1), "y_px": round(float(cy), 1),
                         "r_px": round(float(r_px), 1), "area_px": round(float(p["area_pxl"]), 1),
                         "diam_mm": (round(float(dia_mm), 3) if self.ppm else None),
                         "source": p.get("source", "auto"), "kind": p["kind"]})
        meta = {"image": os.path.basename(self.image_path),
                "image_path": os.path.abspath(self.image_path),
                "mm_per_px": self.ppm, "n_plaques": len(recs),
                "n_manual": sum(1 for r in recs if r["source"] not in pgui.DETECTOR_SOURCES),
                "dish_diam_px": (self.plate or {}).get("diam_px"),
                "dish_center_px": (self.plate or {}).get("center"),
                "schema": "plaque-groundtruth-v1"}
        with open(path, "w") as fh:
            json.dump({"meta": meta, "plaques": recs}, fh, indent=2)
        csv_path = os.path.splitext(path)[0] + ".csv"
        pd.DataFrame(recs).to_csv(csv_path, index=False)
        # Also file a copy + metadata into the persistent training-data store, so labels accumulate
        # into a dataset for retraining. Best-effort: never let it block or break the export.
        store_note = ""
        try:
            import label_store
            try:
                from app import __version__ as _appver
            except Exception:                                       # noqa: BLE001
                _appver = None
            label_store.file_into_store(meta, recs, self.image_path,
                                        source="app-editor", app_version=_appver)
            store_note = "\n\nAlso filed into your training store (for retraining):\n%s" \
                % label_store.store_root()
        except Exception:                                           # noqa: BLE001
            pass
        self._update_hint("saved %d labels → %s" % (len(recs), os.path.basename(path)))
        self._info("Ground truth saved",
                   "Saved %d plaque labels (%d hand-edited):\n\n%s\n%s%s\n\n"
                   "Use these as the gold standard to score the engines (precision / recall) "
                   "and to retrain the classifier." % (len(recs), meta["n_manual"], path, csv_path, store_note))
        return path
