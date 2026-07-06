"""Capture clean screenshots for docs/TOOL_ATLAS.html (real fonts, cropped widgets).

Run:  conda run -n plaqueapp python build/make_atlas_shots.py
Writes PNGs into docs/atlas_img/.  Uses the real 'windows' Qt platform (brief window flashes)
so text renders properly; grabs whole tabs plus close-ups of the summary card, table, editor.
"""
import os
import sys

sys.path.insert(0, os.path.abspath("."))
from PySide6.QtWidgets import QApplication          # noqa: E402
from PySide6.QtGui import QFontDatabase, QFont      # noqa: E402
from app import engine_api, style                   # noqa: E402
from app.ui import MainWindow                        # noqa: E402

OUT = os.path.join("docs", "atlas_img")
os.makedirs(OUT, exist_ok=True)

app = QApplication.instance() or QApplication(sys.argv)
for fp in ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf"):
    if os.path.exists(fp):
        fid = QFontDatabase.addApplicationFont(fp)
        fams = QFontDatabase.applicationFontFamilies(fid)
        if fams:
            app.setFont(QFont(fams[0], 10))
            break
app.setStyleSheet(style.get_stylesheet("light"))

win = MainWindow(); win.resize(1340, 880)
m = win.measure_tab


def save(widget, name):
    ok = widget.grab().save(os.path.join(OUT, name))
    print(("ok " if ok else "FAIL "), name)


app.processEvents()
save(win, "measure_empty.png")

sample = engine_api.resource_path("sample.tif")
det = engine_api.detect_single(sample, plate_mm=100)
m.image_path = sample
m.on_detected(det)
app.processEvents()
save(win, "measure_full.png")
save(m.summary_card, "summary_card.png")
save(m.table, "results_table.png")
save(m.editor, "editor.png")

# other tabs (0 Measure, 1 Batch, 2 Compare turbidity, 3 Validate, 4 About)
for idx, name in ((1, "batch.png"), (2, "compare.png"), (3, "validate.png"), (4, "about.png")):
    win.tabs.setCurrentIndex(idx)
    app.processEvents()
    save(win, name)

print("platform:", app.platformName())
print("done ->", os.path.abspath(OUT))
