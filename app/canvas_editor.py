"""Embed the validated PlaqueEditor inside a Qt widget (reuses its drag/trace/remove/undo logic
on an embedded matplotlib canvas, so no interaction code is rewritten)."""
import matplotlib
matplotlib.use("QtAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT

from PySide6.QtWidgets import QWidget, QVBoxLayout

import plaque_gui as pgui


class _EmbeddedEditor(pgui.PlaqueEditor):
    """PlaqueEditor on an externally supplied figure, with a change callback for table sync."""

    def __init__(self, det, image_path, out_dir, fig, on_change=None):
        self._on_change = on_change
        super().__init__(det["display_rgb"], det["orig_bgr"], det["proc_gray"],
                         det["plaques"], det["pxl_per_mm"], image_path, out_dir,
                         det["candidates"], det["lawn_gray"], plate=det.get("plate"), fig=fig)

    def _redraw(self):
        super()._redraw()
        if self._on_change:
            self._on_change()


class EditorWidget(QWidget):
    """Interactive plaque canvas: left-drag = add circle, Trace mode click = auto-trace,
    right-click = remove, plus the editor's Mode/Undo/Save buttons and a Qt zoom/pan toolbar."""

    def __init__(self, det, image_path, out_dir, on_change=None, parent=None, face="#ffffff"):
        super().__init__(parent)
        self.fig = Figure(figsize=(7, 6), facecolor=face)
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.toolbar)
        lay.addWidget(self.canvas)
        self.editor = _EmbeddedEditor(det, image_path, out_dir, self.fig, on_change=on_change)
        self.canvas.draw_idle()

    @property
    def plaques(self):
        return self.editor.plaques

    def save(self):
        return self.editor._save()
