# webapp/app.py — Plaque Toolkit on the web (Shiny for Python).
# -----------------------------------------------------------------------------------------------
# Upload a plate photo -> set the dish size -> DETECT with the Precise engine (PST + PlaqSeg +
# ResNet gate, the SAME validated in-process code as the desktop app) -> see the annotated plate +
# a per-plaque table -> download the CSV / annotated image. Runs in any browser (incl. Chrome OS).
#
# Reuses the repo's engine directly (precise.pipeline.run_inprocess), so numbers match the desktop
# Full app. CPU inference is slower (~20-60 s/plate) but works on a free Hugging Face Space.
#
# Run locally:   shiny run --launch-browser webapp/app.py      (from the repo root, plaqueapp env)
# -----------------------------------------------------------------------------------------------
import os
import sys
import shutil
import tempfile

os.environ.setdefault("MPLBACKEND", "Agg")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                       # repo root — where precise/, _plaqseg/, etc. live
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pandas as pd
from shiny import App, ui, render, reactive, req

# ------------------------------------------------------------------ engine ----
def _run_precise(image_path, plate_mm, clf):
    """Call the repo's in-process Precise pipeline. Returns (summary, df, overlay_path)."""
    import precise.pipeline as pipe
    out_dir = tempfile.mkdtemp(prefix="precise_web_")
    summary = pipe.run_inprocess(image_path, plate_mm=float(plate_mm), out_dir=out_dir,
                                 clf=bool(clf))
    csv, overlay = summary.get("csv"), summary.get("overlay")
    df = pd.read_csv(csv) if csv and os.path.exists(csv) else pd.DataFrame()
    return summary, df, overlay


HELP = """
<div style="max-width:820px;line-height:1.5">
<h4>What this is</h4>
<p>The <b>Plaque Toolkit</b> measurement engine, in your browser. Upload a Petri-dish photo, tell it
the dish diameter, and it detects and measures the plaques with the <b>Precise</b> engine — the same
validated code as the desktop app (PST detector + PlaqSeg YOLO + a ResNet precision gate).</p>
<h4>How to use it</h4>
<ol>
<li><b>Upload</b> a plate photo (JPG / PNG / TIFF). A flat, evenly lit, top-down shot works best.</li>
<li>Set the <b>dish diameter (mm)</b> — the true outer dish size (e.g. 90 mm). This is the scale, so
   get it right: every size depends on it.</li>
<li>Click <b>Measure</b>. On a free CPU host the first run wakes the server and can take ~1 min;
   after that ~20–60 s per plate.</li>
<li>Read the <b>annotated plate</b> + the <b>measurements</b> table (area-equivalent diameter,
   <code>d = 2·√(A/π)</code>), and <b>download</b> the CSV / image.</li>
</ol>
<h4>Good to know</h4>
<ul>
<li><b>Diameters are area-equivalent</b> (the diameter of a circle with the same area) — validated
   against manual Fiji tracing (ICC 0.974). See the repo's <code>validation/</code>.</li>
<li>Precise is <b>conservative on very dense plates</b> (it under-counts rather than guessing). For
   crowded plates, the desktop app adds manual add/erase tools.</li>
<li>Nothing is stored — your image is processed in a temp folder and discarded.</li>
</ul>
</div>
"""

app_ui = ui.page_sidebar(
    ui.sidebar(
        ui.input_file("image", "Plate photo", accept=["image/*", ".tif", ".tiff", ".jpg", ".jpeg", ".png", ".bmp"]),
        ui.input_numeric("plate_mm", "Dish diameter (mm)", 90, min=10, max=200, step=1),
        ui.input_checkbox("clf", "Precision gate (ResNet filter) — recommended", True),
        ui.input_action_button("go", "Measure", class_="btn-primary"),
        ui.output_ui("status"),
        width=320,
    ),
    ui.navset_tab(
        ui.nav_panel("Result",
                     ui.output_ui("summary_box"),
                     ui.output_image("overlay", height="auto"),
                     ui.download_button("dl_overlay", "Download annotated image")),
        ui.nav_panel("Measurements",
                     ui.output_data_frame("table"),
                     ui.download_button("dl_csv", "Download CSV")),
        ui.nav_panel("How to use", ui.HTML(HELP)),
    ),
    title="Plaque Toolkit — measure plaques online",
)


def server(input, output, session):
    result = reactive.value(None)          # (summary, df, overlay_path) or None
    busy = reactive.value(False)

    @reactive.effect
    @reactive.event(input.go)
    def _measure():
        f = input.image()
        if not f:
            ui.notification_show("Upload a plate photo first.", type="warning")
            return
        busy.set(True)
        result.set(None)
        # copy upload to a temp file with a real extension the readers accept
        src = f[0]["datapath"]
        ext = os.path.splitext(f[0]["name"])[1] or ".png"
        tmp = tempfile.mkdtemp(prefix="upload_")
        img = os.path.join(tmp, "plate" + ext)
        shutil.copyfile(src, img)
        try:
            with ui.Progress(min=0, max=1) as p:
                p.set(0.1, message="Detecting plaques…",
                      detail="Precise engine on CPU — this can take ~20–60 s.")
                summary, df, overlay = _run_precise(img, input.plate_mm(), input.clf())
                p.set(1.0, message="Done")
            result.set((summary, df, overlay))
        except Exception as e:                              # noqa: BLE001
            ui.notification_show("Measurement failed: %s" % e, type="error", duration=None)
            result.set(None)
        finally:
            busy.set(False)

    @render.ui
    def status():
        if busy.get():
            return ui.p("Working… please wait.", style="color:#b45309;font-weight:600")
        r = result.get()
        if r is None:
            return ui.p("Upload a plate, set the dish size, and click Measure.", style="color:#667")
        return ui.p("✓ Done — see the Result and Measurements tabs.", style="color:#0e7d5b;font-weight:600")

    @render.ui
    def summary_box():
        r = result.get()
        if r is None:
            return ui.HTML("")
        s, df, _ = r
        n = s.get("n_final", len(df))
        return ui.HTML(
            "<div style='border-left:4px solid #0e7d5b;background:#f0f7f4;padding:.6em 1em;"
            "border-radius:6px;margin-bottom:10px'><b>%d plaques</b> &nbsp;·&nbsp; "
            "median Ø <b>%.2f mm</b> &nbsp;·&nbsp; mean Ø <b>%.2f mm</b> &nbsp;·&nbsp; "
            "scale <b>%.4f mm/px</b> &nbsp;·&nbsp; density: %s</div>"
            % (n, s.get("median_diam_mm", float("nan")), s.get("mean_diam_mm", float("nan")),
               s.get("mm_per_px", float("nan")), s.get("density_regime", "?")))

    @render.image
    def overlay():
        r = result.get()
        req(r is not None)
        _, _, path = r
        req(path and os.path.exists(path))
        return {"src": path, "width": "100%", "style": "max-width:900px;border-radius:8px"}

    @render.data_frame
    def table():
        r = result.get()
        req(r is not None)
        _, df, _ = r
        return df

    # ---- downloads ----
    @render.download(filename="plaque_measurements.csv")
    def dl_csv():
        r = result.get(); req(r is not None)
        _, df, _ = r
        yield df.to_csv(index=False)

    @render.download(filename="plaque_annotated.jpg")
    def dl_overlay():
        r = result.get(); req(r is not None)
        _, _, path = r
        req(path and os.path.exists(path))
        with open(path, "rb") as fh:
            yield fh.read()


app = App(app_ui, server)
