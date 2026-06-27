"""
Interactive GUI companion for plaque_size_tool.

Runs the SAME automatic detection + calibration as plaque_size_tool.py, then lets
you correct the result by hand:

  * left-drag            -> add a missed plaque as a circle (click centre, drag to edge)
  * left-click (Trace)   -> add a missed plaque by auto-tracing its outline
  * right-click          -> remove a plaque (auto or manual) under the cursor
  * Undo button / 'u'    -> undo the last add/remove
  * Save button / 's'    -> write the combined result (overwrites the standard outputs)
  * Mode button / 't'    -> toggle between Circle and Trace add-modes

Manual measurements use the exact same pixel->mm calibration as the automatic ones,
so the numbers are directly comparable. Output files (overwritten on Save):
  out/data-green-<name>.csv   (adds a SOURCE column: auto / manual)
  out/out_<name>.<ext>        (auto plaques green, manual plaques blue)

Usage:
  python plaque_gui.py -i IMAGE [-p PLATE_MM] [-small]
  python plaque_gui.py IMAGE  [-p PLATE_MM] [-small]
  python plaque_gui.py            (opens a file picker)
"""

import argparse
import os

import cv2
import numpy as np
import pandas as pd
import imutils
from PIL import Image, ImageEnhance

import plaque_size_tool as pst

try:
    from scalebar import draw_scale_bar
except Exception:          # never let a missing helper break detection/saves
    draw_scale_bar = None

# Module-level toggle: stamp a physical scale bar onto saved annotated images.
# Set to False to disable everywhere this save_results is used (GUI editor, app,
# measure_samples.py). The actual draw is also guarded by try/except below.
draw_scalebar = True


# --------------------------------------------------------------------------- #
#  Detection (mirrors plaque_size_tool.main() for a single image)
# --------------------------------------------------------------------------- #
def run_detection(image_path, plate_size, small, sensitive=False):
    """Return (display_rgb, orig_bgr, proc_gray, plaques, pxl_per_mm, candidates, lawn_gray, plate).
    sensitive=True lowers the size gates to catch very small plaques (more, noisier); it is
    forced OFF in --published mode so the validated algorithm is never altered."""
    pst.small_plaques = bool(small)
    pst.sensitive = bool(sensitive) and not pst.use_published
    pst.debug_mode = False

    # HEIC-safe read + in-memory dimming (no temp files)
    orig = pst.read_image_bgr(image_path)
    image = orig
    image_brightness = float(cv2.cvtColor(orig, cv2.COLOR_BGR2GRAY).mean())
    if image_brightness > 70:
        image = np.clip(orig.astype(np.float32) * 0.5, 0, 255).astype(np.uint8)

    binary_image, high_contrast, clr_high_contrast = pst.process_image(image, 2.5)
    contours = pst.get_contours(binary_image)
    image_size = binary_image.shape

    green_df, red_df, other_df, plate_df = pst.filter_contours(contours, image_size)
    if pst.watershed_enabled:
        rec = pst.recover_merged_plaques(image_size, green_df, red_df, other_df)
        green_df = green_df.copy()
        green_df["SOURCE"] = "auto"
        if not rec.empty:
            rec = rec.copy()
            rec["SOURCE"] = "watershed"
            green_df = pd.concat([green_df, rec], ignore_index=True)
    green_df_copy = pst.check_duplicate_plaques(green_df.copy())
    green_df_copy = pst.calculate_size_mm(plate_size, green_df_copy, plate_df)

    if green_df_copy.size > 0:
        green_df_copy["MEAN_COLOUR"] = green_df_copy.apply(
            lambda x: pst.get_mean_grey_colour(clr_high_contrast, x["CONTOURS"]), axis=1)
        keep = green_df_copy.apply(lambda x: abs(x["MEAN_COLOUR"]) >= 40, axis=1)
        green_df_copy = green_df_copy[keep]
    green_df_copy = pst.renumerate_df(green_df_copy)

    # choose the dish contour ONCE and reuse it for calibration, lawn mask and overlay.
    # Enhanced path: pick the ROUNDEST large contour so a bigger-but-lumpy blob (the dark
    # surround / halo around the dish) can't hijack the mm calibration. Published mode keeps
    # the original "largest contour" rule so the validated algorithm is unchanged.
    dish_idx = None
    if not plate_df.empty:
        try:
            _ad = plate_df.apply(pst.calc_AREA_PXL_diff, axis=1)
            if pst.use_published:
                dish_idx = plate_df["ENCL_DIAMETER_PXL"].idxmax()
            else:
                cand = plate_df[_ad <= float(_ad.min()) + 0.05]
                dish_idx = cand["ENCL_DIAMETER_PXL"].idxmax()
        except Exception:
            dish_idx = plate_df["ENCL_DIAMETER_PXL"].idxmax()

    # pixel -> mm calibration (scales off the chosen dish diameter)
    pxl_per_mm = None
    if plate_size and dish_idx is not None:
        try:
            max_d = float(plate_df.loc[dish_idx, "ENCL_DIAMETER_PXL"])
            if max_d > 0:
                pxl_per_mm = float(plate_size) / max_d
        except Exception:
            pxl_per_mm = None

    plaques = []
    for _, row in green_df_copy.iterrows():
        m = cv2.moments(row["CONTOURS"])
        if m["m00"] != 0:
            cx, cy = m["m10"] / m["m00"], m["m01"] / m["m00"]
        else:
            cx, cy = row["ENCL_CENTER"]
        plaques.append({
            "source": row.get("SOURCE", "auto"),
            "kind": "contour",
            "contour": np.asarray(row["HULL"], dtype=np.int32),
            "area_pxl": float(row["AREA_PXL"]),
            "center": (float(cx), float(cy)),
        })

    # candidate contours for auto-trace: every non-plate shape the detector found
    # (including the ones it filtered out of the green set), so a click can snap to
    # a real boundary even when the plaque was rejected by the circularity/size filter.
    candidates = []
    cand_df = pd.concat([green_df, red_df, other_df], ignore_index=True)
    for _, row in cand_df.iterrows():
        area = float(row["AREA_PXL"])
        if area <= 0 or area >= 100000:
            continue
        m = cv2.moments(row["CONTOURS"])
        if m["m00"] != 0:
            cc = (m["m10"] / m["m00"], m["m01"] / m["m00"])
        else:
            cc = tuple(row["ENCL_CENTER"])
        candidates.append({"hull": np.asarray(row["HULL"], dtype=np.int32),
                           "area": area, "center": cc})

    # lawn reference for turbidity: median grey of the dish interior minus plaques
    orig_gray = cv2.cvtColor(orig, cv2.COLOR_BGR2GRAY)
    dish_mask = None
    plate = None
    if dish_idx is not None:
        plate_hull = np.asarray(plate_df.loc[dish_idx, "HULL"], dtype=np.int32)
        dish_mask = pst._mask_from_contour(orig_gray.shape, plate_hull)
        (pcx, pcy), prad = cv2.minEnclosingCircle(plate_hull)
        # ellipticity of the CHOSEN dish via cv2.fitEllipse (same method the CLI warning uses).
        # >1.03 => tilt/foreshortening biases the mm calibration (which scales off the dish).
        axis_ratio = None
        try:
            if len(plate_hull) >= 5:
                (_c, (_a1, _a2), _ang) = cv2.fitEllipse(plate_hull)
                lo, hi = min(_a1, _a2), max(_a1, _a2)
                axis_ratio = (hi / lo) if lo > 0 else None
        except Exception:
            axis_ratio = None
        plate = {"hull": plate_hull.reshape(-1, 2),
                 "center": (float(pcx), float(pcy)),
                 "radius": float(prad),
                 "diam_px": float(plate_df.loc[dish_idx, "ENCL_DIAMETER_PXL"]),
                 "axis_ratio": axis_ratio}
    auto_masks = [pst._mask_from_contour(orig_gray.shape, p["contour"]) for p in plaques]
    lawn_gray = pst.estimate_lawn_gray(orig_gray, dish_mask, auto_masks)

    display_rgb = cv2.cvtColor(orig, cv2.COLOR_BGR2RGB)
    return display_rgb, orig, high_contrast, plaques, pxl_per_mm, candidates, lawn_gray, plate


# --------------------------------------------------------------------------- #
#  Measurement + manual segmentation helpers
# --------------------------------------------------------------------------- #
def measure(area_pxl, pxl_per_mm):
    """Area-equivalent diameter (px), area (mm^2), diameter (mm) -- as the tool does."""
    dia_pxl = 2.0 * np.sqrt(area_pxl / np.pi)
    if pxl_per_mm:
        area_mm2 = area_pxl * pxl_per_mm * pxl_per_mm
        dia_mm = 2.0 * np.sqrt(area_mm2 / np.pi)
    else:
        area_mm2, dia_mm = 0.0, 0.0
    return dia_pxl, area_mm2, dia_mm


def trace_by_contour(candidates, x, y):
    """Snap to the smallest detector contour that contains (x, y). None if no hit."""
    best, best_area = None, None
    for c in candidates:
        if cv2.pointPolygonTest(c["hull"], (float(x), float(y)), False) >= 0:
            if best_area is None or c["area"] < best_area:
                best, best_area = c, c["area"]
    if best is None:
        return None
    return best["hull"], best["area"], best["center"]


def trace_at(candidates, gray, x, y):
    """Auto-trace at (x, y): prefer a detector contour, fall back to flood-fill."""
    res = trace_by_contour(candidates, x, y)
    return res if res is not None else autotrace(gray, x, y)


def autotrace(gray, x, y, tol=20, max_area=100000):
    """Bounded flood-fill fallback around (x, y); return (hull, area, center) or None."""
    h, w = gray.shape[:2]
    xi, yi = int(round(x)), int(round(y))
    if not (0 <= xi < w and 0 <= yi < h):
        return None

    mask = np.zeros((h + 2, w + 2), np.uint8)
    flags = 4 | (255 << 8) | cv2.FLOODFILL_MASK_ONLY | cv2.FLOODFILL_FIXED_RANGE
    cv2.floodFill(gray.copy(), mask, (xi, yi), 0, tol, tol, flags)
    region = mask[1:-1, 1:-1]
    region = cv2.morphologyEx(region, cv2.MORPH_CLOSE,
                              cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))

    filled = int(region.sum() // 255)
    if filled < 10 or filled > 0.2 * h * w:   # too tiny or bled into the whole plate
        return None

    cnts = imutils.grab_contours(
        cv2.findContours(region, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE))
    chosen = None
    for c in cnts:
        if cv2.pointPolygonTest(c, (xi, yi), False) >= 0:
            chosen = c
            break
    if chosen is None and cnts:
        chosen = max(cnts, key=cv2.contourArea)
    if chosen is None:
        return None

    hull = cv2.convexHull(chosen)
    area = cv2.contourArea(hull)
    if area <= 0 or area > min(max_area, 0.2 * h * w):   # not a plausible single plaque
        return None
    m = cv2.moments(hull)
    if m["m00"] != 0:
        center = (m["m10"] / m["m00"], m["m01"] / m["m00"])
    else:
        center = (float(x), float(y))
    return hull.astype(np.int32), float(area), center


# --------------------------------------------------------------------------- #
#  Save (overwrites the standard plaque_size_tool outputs)
# --------------------------------------------------------------------------- #
def _plaque_mask(shape, p):
    mask = np.zeros(shape[:2], dtype="uint8")
    if p["kind"] == "circle":
        cv2.circle(mask, (int(round(p["center"][0])), int(round(p["center"][1]))),
                   max(int(round(p["radius"])), 1), 255, -1)
    else:
        cv2.drawContours(mask, [np.asarray(p["contour"], dtype=np.int32)], -1, 255, -1)
    return mask


def save_results(plaques, orig_bgr, image_path, out_dir, pxl_per_mm, lawn_gray=None):
    os.makedirs(out_dir, exist_ok=True)
    gray = cv2.cvtColor(orig_bgr, cv2.COLOR_BGR2GRAY)

    # turbidity: mean grey inside each plaque (original image) + normalised index
    means = [pst.mean_gray_in_mask(gray, _plaque_mask(gray.shape, p)) for p in plaques]
    if lawn_gray is None:
        lawn_gray = pst.estimate_lawn_gray(gray)
    turb = pst.turbidity_indices(means, lawn_gray)

    rows = []
    annotated = orig_bgr.copy()
    for i, (p, mg, tb) in enumerate(zip(plaques, means, turb), start=1):
        dia_pxl, area_mm2, dia_mm = measure(p["area_pxl"], pxl_per_mm)
        rows.append({
            "INDEX_COL": i,
            "AREA_PXL": round(p["area_pxl"], 2),
            "DIAMETER_PXL": round(dia_pxl, 2),
            "AREA_MM2": round(area_mm2, 2),
            "DIAMETER_MM": round(dia_mm, 2),
            "MEAN_GRAY": round(mg, 2),
            "TURBIDITY_REL": round(tb, 3),
            "SOURCE": p["source"],
        })
        color = (0, 255, 0) if p["source"] == "auto" else (255, 0, 0)  # BGR
        if p["kind"] == "circle":
            cv2.circle(annotated, (int(round(p["center"][0])), int(round(p["center"][1]))),
                       int(round(p["radius"])), color, 2)
        else:
            cv2.drawContours(annotated, [np.asarray(p["contour"], dtype=np.int32)], -1, color, 2)
        cx, cy = int(round(p["center"][0])), int(round(p["center"][1]))
        label = f"#{i}:{dia_mm:.2f}" if pxl_per_mm else f"#{i}:{dia_pxl:.0f}px"
        cv2.putText(annotated, label, (cx, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (25, 51, 0), 1)

    name = os.path.splitext(os.path.split(image_path)[1])[0]
    ext = os.path.splitext(os.path.split(image_path)[1])[1]
    if ext.lower() in (".heic", ".heif"):   # OpenCV cannot write HEIC
        ext = ".png"
    csv_path = os.path.join(out_dir, f"data-green-{name}.csv")
    img_path = os.path.join(out_dir, f"out_{name}{ext}")
    pd.DataFrame(rows, columns=["INDEX_COL", "AREA_PXL", "DIAMETER_PXL", "AREA_MM2",
                                "DIAMETER_MM", "MEAN_GRAY", "TURBIDITY_REL", "SOURCE"]).to_csv(csv_path, index=False)
    # Physical scale bar (e.g. "5 mm"). pxl_per_mm is actually mm/px, so pass it straight.
    if draw_scalebar and draw_scale_bar is not None:
        try:
            draw_scale_bar(annotated, pxl_per_mm)
        except Exception:
            pass          # never let the overlay break a save
    cv2.imwrite(img_path, annotated)
    return csv_path, img_path, len(rows)


# --------------------------------------------------------------------------- #
#  Interactive editor
# --------------------------------------------------------------------------- #
class PlaqueEditor:
    def __init__(self, display_rgb, orig_bgr, proc_gray, plaques, pxl_per_mm,
                 image_path, out_dir, candidates=None, lawn_gray=None, plate=None,
                 small=False, plate_size=None, sensitive=False, fig=None):
        self._ext_fig = fig          # if given, embed into this figure (e.g. inside a Qt app)
        self.display_rgb = display_rgb
        self.orig_bgr = orig_bgr
        self.proc_gray = proc_gray
        self.plaques = plaques
        self.pxl_per_mm = pxl_per_mm
        self.image_path = image_path
        self.out_dir = out_dir
        self.candidates = candidates or []
        self.lawn_gray = lawn_gray
        self.plate = plate           # detected dish (drawn for calibration QC); may be None
        self.small = bool(small)     # remembered so the in-editor Sensitive button can re-detect
        self.plate_size = plate_size
        self.sensitive = bool(sensitive)

        self.mode = "circle"          # or "trace"
        self.undo_stack = []
        self.artists = []
        self.drag_center = None
        self.preview = None
        self._build()

    # ---- figure / widgets ----
    def _build(self):
        import matplotlib.pyplot as plt
        from matplotlib.widgets import Button
        self.plt = plt

        if self._ext_fig is not None:                 # embedded (Qt) mode
            self.fig = self._ext_fig
            self.ax = self.fig.add_subplot(111)
        else:
            self.fig, self.ax = plt.subplots(figsize=(11, 8.5))
            try:
                self.fig.canvas.manager.set_window_title(
                    "Plaque editor - " + os.path.basename(self.image_path))
            except Exception:
                pass
        self.fig.subplots_adjust(left=0.03, right=0.99, top=0.94, bottom=0.11)
        self.ax.imshow(self.display_rgb)
        self.ax.set_xticks([]); self.ax.set_yticks([])
        self._draw_plate()

        self.b_mode = Button(self.fig.add_axes([0.04, 0.02, 0.17, 0.055]), "Mode: Circle")
        self.b_undo = Button(self.fig.add_axes([0.22, 0.02, 0.11, 0.055]), "Undo")
        self.b_save = Button(self.fig.add_axes([0.34, 0.02, 0.11, 0.055]), "Save")
        self.b_help = Button(self.fig.add_axes([0.46, 0.02, 0.11, 0.055]), "Help")
        self.b_mode.on_clicked(lambda e: self._toggle_mode())
        self.b_undo.on_clicked(lambda e: self._undo())
        self.b_save.on_clicked(lambda e: self._save())
        self.b_help.on_clicked(lambda e: self._help())
        self.b_sens = None
        if self._ext_fig is None:        # standalone window: offer a live Sensitive toggle
            self.b_sens = Button(self.fig.add_axes([0.59, 0.02, 0.22, 0.055]),
                                 "Sensitive: " + ("ON" if self.sensitive else "OFF"))
            self.b_sens.on_clicked(lambda e: self._toggle_sensitive())

        self.fig.canvas.mpl_connect("button_press_event", self._on_press)
        self.fig.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self.fig.canvas.mpl_connect("button_release_event", self._on_release)
        self.fig.canvas.mpl_connect("key_press_event", self._on_key)

        self._redraw()
        self._title()

    def show(self):
        self.plt.show()

    # ---- plate / dish overlay (calibration QC) ----
    def _draw_plate(self):
        """Draw the detected dish so you can confirm the mm calibration is trustworthy.
        Orange dashed circle = the enclosing circle the calibration scales off; thin solid
        outline = the actual detected dish boundary; label shows diameter + tilt ratio."""
        if not self.plate:
            self.ax.set_title("", fontsize=9)
            return
        from matplotlib.patches import Circle, Polygon
        cx, cy = self.plate["center"]
        r = self.plate["radius"]
        self.ax.add_patch(Circle((cx, cy), r, fill=False, color="orange",
                                 lw=1.6, ls="--", alpha=0.9))
        hull = self.plate.get("hull")
        if hull is not None and len(hull) >= 3:
            self.ax.add_patch(Polygon(np.asarray(hull, dtype=float), closed=True,
                                     fill=False, color="orange", lw=1.0, alpha=0.55))
        ar = self.plate.get("axis_ratio")
        tag = "detected plate  Ø=%.0f px" % self.plate["diam_px"]
        if ar:
            tag += ",  axis ratio %.2f%s" % (ar, "  - tilted, mm may be biased" if ar > 1.03 else "")
        self.ax.text(cx, cy - r, tag, color="orange", fontsize=7, ha="center", va="bottom",
                     bbox=dict(boxstyle="round,pad=0.2", fc="black", ec="orange", alpha=0.5))

    # ---- helpers ----
    def _toolbar_active(self):
        try:
            return getattr(self.fig.canvas.manager.toolbar, "mode", "") not in ("", None)
        except Exception:
            return False

    def _title(self, msg=None):
        cal = ("%.4f mm/px" % self.pxl_per_mm) if self.pxl_per_mm else "pixels only"
        base = (f"{len(self.plaques)} plaques  |  add-mode: {self.mode}  |  {cal}   "
                f"(left-drag = circle, right-click = remove, t = mode, u = undo, s = save)")
        self.ax.set_title((msg + "   --   " + base) if msg else base, fontsize=9)
        self.fig.canvas.draw_idle()

    def _push_undo(self):
        self.undo_stack.append([dict(p) for p in self.plaques])

    def _find_plaque(self, x, y):
        """Index of the smallest plaque containing (x, y), else nearest centre within 15 px."""
        best, best_area = None, None
        for i, p in enumerate(self.plaques):
            inside = False
            if p["kind"] == "circle":
                inside = np.hypot(x - p["center"][0], y - p["center"][1]) <= p["radius"]
            else:
                inside = cv2.pointPolygonTest(np.asarray(p["contour"], dtype=np.int32),
                                              (float(x), float(y)), False) >= 0
            if inside and (best_area is None or p["area_pxl"] < best_area):
                best, best_area = i, p["area_pxl"]
        if best is not None:
            return best
        nearest, nd = None, 15.0
        for i, p in enumerate(self.plaques):
            d = np.hypot(x - p["center"][0], y - p["center"][1])
            if d < nd:
                nearest, nd = i, d
        return nearest

    # ---- drawing ----
    def _redraw(self):
        from matplotlib.patches import Circle
        for a in self.artists:
            try:
                a.remove()
            except Exception:
                pass
        self.artists = []
        for i, p in enumerate(self.plaques, start=1):
            color = "lime" if p["source"] == "auto" else "deepskyblue"
            if p["kind"] == "circle":
                c = Circle(p["center"], p["radius"], fill=False, color=color, lw=1.4)
                self.ax.add_patch(c)
                self.artists.append(c)
            else:
                cnt = np.asarray(p["contour"], dtype=np.int32).reshape(-1, 2)
                xs = np.append(cnt[:, 0], cnt[0, 0])
                ys = np.append(cnt[:, 1], cnt[0, 1])
                line, = self.ax.plot(xs, ys, color=color, lw=1.2)
                self.artists.append(line)
            t = self.ax.text(p["center"][0], p["center"][1], str(i),
                             color="yellow", fontsize=7, ha="center", va="center")
            self.artists.append(t)
        self.fig.canvas.draw_idle()

    # ---- events ----
    def _on_press(self, event):
        if event.inaxes != self.ax or self._toolbar_active() or event.xdata is None:
            return
        x, y = event.xdata, event.ydata
        if event.button == 3:                       # right click -> remove
            idx = self._find_plaque(x, y)
            if idx is None:
                self._title("nothing to remove there")
                return
            self._push_undo()
            removed = self.plaques.pop(idx)
            self._redraw()
            self._title(f"removed a {removed['source']} plaque")
            return
        if event.button == 1:
            if self.mode == "circle":
                from matplotlib.patches import Circle
                self.drag_center = (x, y)
                self.preview = Circle((x, y), 0.1, fill=False, color="yellow", lw=1.5, ls="--")
                self.ax.add_patch(self.preview)
                self.fig.canvas.draw_idle()
            else:
                self._add_trace(x, y)

    def _on_motion(self, event):
        if self.drag_center is None or event.inaxes != self.ax or event.xdata is None:
            return
        r = np.hypot(event.xdata - self.drag_center[0], event.ydata - self.drag_center[1])
        self.preview.set_radius(max(r, 0.1))
        self.fig.canvas.draw_idle()

    def _on_release(self, event):
        if self.drag_center is None:
            return
        cx, cy = self.drag_center
        self.drag_center = None
        if self.preview is not None:
            self.preview.remove()
            self.preview = None
        if event.xdata is None:
            self.fig.canvas.draw_idle()
            return
        r = float(np.hypot(event.xdata - cx, event.ydata - cy))
        if r < 3:
            self.fig.canvas.draw_idle()
            return
        self._push_undo()
        self.plaques.append({"source": "manual", "kind": "circle",
                             "center": (cx, cy), "radius": r, "area_pxl": float(np.pi * r * r)})
        self._redraw()
        self._title("added circle")

    def _add_trace(self, x, y):
        res = trace_at(self.candidates, self.proc_gray, x, y)
        if res is None:
            self._title("auto-trace failed here - use circle mode instead")
            return
        hull, area, center = res
        self._push_undo()
        self.plaques.append({"source": "manual", "kind": "contour",
                             "contour": hull, "area_pxl": area, "center": center})
        self._redraw()
        self._title("added traced plaque")

    def _on_key(self, event):
        if event.key in ("t", "T"):
            self._toggle_mode()
        elif event.key in ("u", "U", "ctrl+z"):
            self._undo()
        elif event.key in ("s", "S"):
            self._save()
        elif event.key in ("h", "H"):
            self._help()

    def _toggle_mode(self):
        self.mode = "trace" if self.mode == "circle" else "circle"
        self.b_mode.label.set_text("Mode: " + ("Trace" if self.mode == "trace" else "Circle"))
        self._title()

    def _toggle_sensitive(self):
        """Re-run auto-detection with sensitive mode flipped, KEEPING any manual edits.
        Standalone only — the app drives detection through the locked engine_api adapter."""
        if self._ext_fig is not None or self.b_sens is None:
            return
        manual = [p for p in self.plaques if p.get("source") == "manual"]
        self._push_undo()
        self.sensitive = not self.sensitive
        try:
            (_disp, _orig, proc, plaques, _ppm, candidates, lawn_gray, _plate) = run_detection(
                self.image_path, self.plate_size, self.small, self.sensitive)
        except Exception as e:
            self.sensitive = not self.sensitive          # revert flag on failure
            self.undo_stack.pop()                         # discard the unused checkpoint
            self._title(f"sensitive toggle failed: {e}")
            return
        self.plaques = plaques + manual                   # calibration/dish are unchanged
        self.proc_gray = proc
        self.candidates = candidates or []
        self.lawn_gray = lawn_gray
        self.b_sens.label.set_text("Sensitive: " + ("ON" if self.sensitive else "OFF"))
        self._redraw()
        self._title(f"sensitive {'ON' if self.sensitive else 'OFF'}: "
                    f"{len(plaques)} auto + {len(manual)} manual")

    def _undo(self):
        if not self.undo_stack:
            self._title("nothing to undo")
            return
        self.plaques = self.undo_stack.pop()
        self._redraw()
        self._title("undid last change")

    def _save(self):
        csv_path, img_path, n = save_results(
            self.plaques, self.orig_bgr, self.image_path, self.out_dir,
            self.pxl_per_mm, self.lawn_gray)
        print(f"Saved {n} plaques -> {csv_path}")
        print(f"Annotated image  -> {img_path}")
        self._title(f"SAVED {n} plaques to {os.path.relpath(csv_path)}")

    def _help(self):
        print(__doc__)
        self._title("help printed to the console window")


# --------------------------------------------------------------------------- #
#  Entry point
# --------------------------------------------------------------------------- #
def parse_args():
    ap = argparse.ArgumentParser(description="Interactive plaque measurement editor")
    ap.add_argument("image", nargs="?", help="path to the input image")
    ap.add_argument("-i", "--image", dest="image_opt", help="path to the input image")
    ap.add_argument("-p", "--plate_size", help="plate diameter (mm) for mm measurements")
    ap.add_argument("-small", "--small_plaque", action="store_true",
                    help="for plaques < 2.5 mm or low-resolution images")
    ap.add_argument("-o", "--out", default="out", help="output directory (default: out)")
    ap.add_argument("--selftest", action="store_true",
                    help="run detection + a synthetic edit + save without opening a window")
    ap.add_argument("--published", action="store_true",
                    help="use exact published Plaque Size Tool detection/sizing behaviour")
    ap.add_argument("--watershed", action="store_true",
                    help="split touching/merged plaques via watershed before editing")
    ap.add_argument("-sensitive", "--sensitive", action="store_true",
                    help="also catch very small plaques (lowers size gates; more, noisier; off under --published)")
    a = ap.parse_args()
    return ((a.image_opt or a.image), a.plate_size, a.small_plaque, a.out, a.selftest,
            a.published, a.watershed, a.sensitive)


def pick_file():
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        path = filedialog.askopenfilename(
            title="Select a plaque image",
            filetypes=[("Images", "*.tif *.tiff *.jpg *.jpeg *.png"), ("All files", "*.*")])
        root.destroy()
        return path
    except Exception:
        return None


def main():
    image, plate_size, small, out_dir, selftest, published, watershed, sensitive = parse_args()
    pst.use_published = published
    pst.watershed_enabled = bool(watershed) and not published
    if not image:
        image = pick_file()
        if not image:
            print("No image selected.")
            return

    display_rgb, orig, proc, plaques, ppm, candidates, lawn_gray, plate = run_detection(
        image, plate_size, small, sensitive)
    cal = ("%.5f mm/px" % ppm) if ppm else "pixels only (no -p given or plate not found)"
    if sensitive and not published:
        print("(sensitive mode ON: catching very small plaques - more, and some false positives)")
    print(f"Auto-detected {len(plaques)} plaques.  Calibration: {cal}")
    if plate and plate.get("axis_ratio") and plate["axis_ratio"] > 1.03:
        print(f"  NOTE: detected dish axis ratio {plate['axis_ratio']:.2f} (>1.03) - "
              f"photo may be tilted; mm calibration could be biased.")

    if selftest:
        h, w = orig.shape[:2]
        r = 40.0
        plaques.append({"source": "manual", "kind": "circle",
                        "center": (w / 2.0, h / 2.0), "radius": r, "area_pxl": float(np.pi * r * r)})
        # seed the auto-trace test on a real detected plaque if we have one
        if plaques and plaques[0]["source"] == "auto":
            tx, ty = plaques[0]["center"]
        else:
            tx, ty = w / 2.0, h / 3.0
        res = trace_at(candidates, proc, tx, ty)
        if res:
            hull, area, center = res
            plaques.append({"source": "manual", "kind": "contour",
                            "contour": hull, "area_pxl": area, "center": center})
            print(f"auto-trace OK (area={area:.0f}px)")
        else:
            print("auto-trace returned None at the test point (acceptable)")
        csv_path, img_path, n = save_results(plaques, orig, image, out_dir, ppm, lawn_gray)
        print(f"SELFTEST saved {n} rows -> {csv_path}")
        print(f"SELFTEST image     -> {img_path}")
        return

    PlaqueEditor(display_rgb, orig, proc, plaques, ppm, image, out_dir, candidates, lawn_gray,
                 plate=plate, small=small, plate_size=plate_size, sensitive=sensitive).show()


if __name__ == "__main__":
    main()
