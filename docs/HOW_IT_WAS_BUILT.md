# How the Plaque Toolkit was built

A build-and-design narrative for scientist-developers. It explains where the toolkit
came from, how the pieces fit together, what each detection engine actually does, and —
importantly — exactly which parts you may cite and which you may not.

Every claim below is grounded in the source. File references are given inline so you can
read the code next to the prose.

---

## 1. Origin and lineage

The toolkit is built on top of a published, peer-reviewed method:

> Trofimova E, Jaschke PR. *Plaque Size Tool: An automated plaque analysis tool for
> simplifying and standardising bacteriophage plaque morphology measurements.* Virology
> 2021;561:1–5. [doi:10.1016/j.virol.2021.05.011](https://doi.org/10.1016/j.virol.2021.05.011)

The upstream algorithm — adaptive-local thresholding → contour detection → keep
non-overlapping, roughly-circular contours → measure convex-hull area — lives essentially
unchanged in `plaque_size_tool.py`. That module is treated as **the validated engine** and
is the one thing the rest of the codebase is careful not to disturb (`docs/ENGINES.md`,
`README.md`).

What was **kept unchanged**:

- The detection/sizing core in `plaque_size_tool.py`. When `use_published` is set, the
  toolkit reproduces the original byte-for-byte, including its quirks: values stored as
  2-decimal-place *strings*, `DIAMETER_MM` derived from the already-truncated `AREA_MM2`
  string, and no warning when the dish is not found (`_calculate_size_mm_published`,
  `plaque_size_tool.py:350`). This reproduces the literature to within ~0.04 mm.

What was **extended** (all in-house, see §8 for the honesty caveat):

- A maintained "Current" path with bug-fixes, numeric (non-truncated) values, and a
  corrected dish/calibration (`calculate_size_mm`, `plaque_size_tool.py:368`).
- A "Sensitive" mode that lowers the size gates for tiny plaques.
- A "Precise" mode fusing the classic detector with a YOLO segmentation model
  (`precise/`, `_plaqseg/`).
- A PySide6 desktop app with an interactive editor (`app/`).
- Cross-phage turbidity / optical-density / titer batch analysis
  (`plaque_turbidity.py`).
- HEIC support, watershed splitting, a physical scale bar, and an optional ML
  classifier.

The original upstream manual is preserved verbatim at `docs/UPSTREAM_README.md`.

---

## 2. Architecture

The central design rule: **only one module is allowed to touch the validated engine.**

The engine uses *process-global* flags — `use_published`, `watershed_enabled`,
`small_plaques` — rather than per-call parameters. That is dangerous in a multi-feature GUI:
two features could race on the same global. So every engine call is funnelled through
`app/engine_api.py`, which sets those flags atomically under a lock
(`_LOCK = threading.Lock()`, `app/engine_api.py:16`). `detect_single`
(`app/engine_api.py:34`) acquires the lock, sets `pst.use_published` /
`pst.watershed_enabled`, runs detection, and returns a plain dict of NumPy/Python types —
no Qt objects cross the boundary. The Qt thread pool is even pinned to a single worker
(`self.pool.setMaxThreadCount(1)`, `app/ui.py:636`) precisely because "the engine flags are
global."

```
                         ┌─────────────────────────────────────────────┐
                         │              PySide6 app (app/)              │
   user ── drag/drop ──▶ │  ui.py: Measure tab · Compare tab · About    │
                         │  plaque_canvas.py: QGraphicsView editor      │
                         │  workers.py: off-UI-thread Worker            │
                         └───────────────┬─────────────────────────────┘
                                         │  (the ONLY door to the engine)
                              ┌──────────▼───────────┐
                              │  app/engine_api.py   │  global-flag lock
                              │  detect_single()     │  detect_precise()
                              │  run_compare()       │  precise_available()
                              └───┬───────────┬──────┘
             ┌────────────────────┘           └───────────────────┐
   ┌─────────▼──────────┐                          ┌──────────────▼──────────────┐
   │ plaque_size_tool   │  VALIDATED engine        │  precise/ pipeline           │
   │ plaque_gui         │  (detection + sizing     │  pst_front → PlaqSeg YOLO →   │
   │ plaque_turbidity   │   + turbidity index)     │  combine (masks/gates/clf)   │
   └────────────────────┘                          │  _plaqseg/ · _research/clf/  │
                                                   └──────────────────────────────┘
```

**The app (`app/`).** `app/ui.py` builds the main window with three tabs:

- **Measure** — open/drag an image, pick a dish diameter and an engine, auto-detect, then
  hand-edit the result on a canvas and save size + turbidity. The engine dropdown is the
  `MODES` catalogue (`app/ui.py:29`); `_detect` routes to `engine_api.detect_single` for
  the three classic engines or to a dedicated Precise path (`app/ui.py:280`).
- **Compare turbidity** — point at a folder of phage plates (with optional blank-agar and
  flat-field references), run `engine_api.run_compare` → `plaque_turbidity.run_batch`, and
  render per-phage tables, QC notes, and box/histogram figures (`CompareTab`,
  `app/ui.py:413`).
- **About** — citation and the honesty note, rendered straight into the UI
  (`AboutTab`, `app/ui.py:579`).

Detection runs off the UI thread via `app/workers.py` (`Worker`), so the window stays
responsive during the heavy Precise pass.

**The editor (`app/plaque_canvas.py`).** A native-Qt `QGraphicsView` editor
(`PlaqueCanvas`, `app/plaque_canvas.py:287`) — chosen over the older OpenCV editor
(`plaque_gui.py`) and the earlier `app/canvas_editor.py` for reliable mouse handling. More
in §6.

**Calibration QC, surfaced everywhere.** The dish circle and a tilt warning are drawn on
every overlay and shown in the summary card when the dish axis-ratio exceeds 1.03
(`app/ui.py:354`, `app/plaque_canvas.py:441`). See §5.

---

## 3. The four detection engines

All four share the same measurement math (area, area-equivalent diameter, mm calibration
from the detected dish). They differ in *which* plaques they find and in *how much you can
trust the result* (`docs/ENGINES.md`).

### Published (validated)

The exact Trofimova & Jaschke 2021 algorithm, selected by `pst.use_published = True`. It is
forced to disable the extensions: `--published` forces `--watershed` and `--sensitive`
**off** (`app/engine_api.py:38–39`), so a citable run can never be altered by an in-house
feature. The dish for calibration is simply the largest enclosing-diameter contour
(`plaque_gui.py:97`). This is the **only** citable mode.

### Current (corrected) — the default

The same detection/sizing algorithm with two classes of fix (`calculate_size_mm`,
`plaque_size_tool.py:368`):

1. **Numeric values** — measurements stay numeric instead of being truncated to 2-dp
   strings mid-computation; `DIAMETER_MM` is computed from the true (unrounded) area.
2. **Corrected dish / calibration** — the dish is chosen as the **roundest** large contour,
   not just the biggest. The selector keeps the contour whose area best matches its
   enclosing circle (`calc_AREA_PXL_diff`) and, among those, the largest
   (`plaque_gui.py:99`). This stops the dark surround around a top-lit dish from hijacking
   the mm scale. On the bundled plates this leaves the count unchanged and shifts individual
   `DIAMETER_MM` by ≤ ~0.04 mm versus Published.

### Sensitive (tiny plaques)

Current with the size gates lowered to catch sub-0.4 mm plaques (`small=True,
sensitive=True`, `app/ui.py:293`). Higher recall, but more false positives (bubbles, glare,
dust, lawn texture). It is forced off under Published mode so it can never contaminate a
validated run.

### Precise (PST + PlaqSeg) — the strongest detector

Precise fuses the validated PST geometry with a YOLO-seg model and a chain of precision
gates. The algorithm lives in `precise/combine.py` (`combine_detections`,
`precise/combine.py:181`), fed by `precise/pst_front.py` (PST front end) and
`_plaqseg/run_plaqseg.py` (YOLO). Stages:

1. **PST front** (`precise/pst_front.py:31`) — runs `plaque_gui.run_detection` twice
   (normal + sensitive) to get the dish geometry, mm/px calibration, and two sets of PST
   plaque centers (normal-pass count for the density reference, sensitive-pass centers as
   recall candidates).
2. **Artifact masks** (`precise/combine.py:222`) — from the dish geometry: a **lawn ROI**
   (inner `LAWN_FRAC = 0.80` of the radius), a **blue-label** mask (`b - r > 25 & b > 90`,
   dilated), and a **hard dish-boundary** reject. Any detection on the rim, on the label, or
   outside the dish is dropped (`accepted()`).
3. **PlaqSeg YOLO primary** (`precise/combine.py:242`) — the tiled YOLO-seg model
   (`_plaqseg/models/small.pt`) detects plaques on the original image (1280-px tiles,
   1024 stride, global NMS; `_plaqseg/run_plaqseg.py:25`). Detections outside the lawn ROI
   or on the label are removed. PlaqSeg is the **primary** detector.
4. **Density switch** (`precise/combine.py:254`) — if PlaqSeg already found a dense field
   (`n_plaqseg ≥ DENSE_FACTOR · n_pst_sensitive`, `DENSE_FACTOR = 1.5`), take the PlaqSeg
   set as final and **skip** the recall passes. They only help on sparse plates; on dense
   plates they add noise.
5. **Gated PST-sensitive recall** (sparse/clean plates, `precise/combine.py:268`) — a
   PST-sensitive center is accepted only if it is inside the lawn ROI, **not** already
   matched to a PlaqSeg detection (within a match radius), **and** passes a center-vs-ring
   contrast floor (`CONTRAST_FLOOR = 0.030`) measured on a float, flat-fielded lawn
   (`float_flatten`, `precise/combine.py:98`; `center_ring_contrast`,
   `precise/combine.py:109`). The flat-field is internal to the recall pass only — no JPEG
   write, no CLAHE.
6. **Optional blob recovery** (sparse only, **off by default**, `precise/combine.py:286`) —
   `skimage.feature.blob_log` on the inverted flat lawn, behind the same masks and contrast
   gate. Off because it over-detects on textured lawns.
7. **Optional learned classifier gate** (`--clf`, `precise/combine.py:311`) — re-scores
   every candidate; see §4.
8. **Union + dedup** (`precise/combine.py:357`) — union of PlaqSeg + gated-PST +
   gated-blob, deduplicated by match radius.
9. **Sizing + output** (`precise/combine.py:378`) — per-plaque CSV, a colored overlay
   (green = PlaqSeg, blue = recovered, cyan lawn ring, orange dish, physical scale bar), and
   a one-line JSON summary. The summary also carries an `uncertainty_flag` when the two
   primary detectors disagree on count by more than 50% (`precise/combine.py:376`), which
   the UI surfaces as "Detectors disagree — verify by eye" (`app/ui.py:366`).

Precise needs PyTorch + ultralytics + the YOLO weights, so it runs only where those are
available — see §7 for the in-process vs two-env mechanics.

---

## 4. The ML classifier (plaque vs texture)

An optional learned **precision gate** that decides, per candidate, whether a detection is a
real plaque or lawn texture. It is opt-in.

- **Architecture.** A ResNet-18 with a 2-class head (`resnet18(weights=None)`; `m.fc =
  nn.Linear(m.fc.in_features, 2)`, `_research/clf/infer.py:26`). The checkpoint is
  `_research/clf/plaque_clf.pt`; inference is `_research/clf/infer.py`
  (`prob_plaque_batch`).
- **Input convention.** Each candidate is re-cropped to a scale-normalized **48×48** BGR
  patch so the detection fills ~`CLF_FILL = 0.55` of the frame — exactly the convention used
  to mine the training data (`clf_crop`, `precise/combine.py:134`; `CLF_PATCH = 48`).
- **Training data.** Detector-union labels plus an independent vision ground-truth set and
  OnePetri real-phage labels — 15,659 boxes total (`docs/ENGINES.md`).
- **Performance.** Leave-one-plate-out **F1 ≈ 0.96** on held-out plates
  (`docs/ENGINES.md`).
- **How it gates.** When enabled, every candidate (PlaqSeg primary + gated-PST + blob) is
  scored; anything below `CLF_THR` (default 0.5) is dropped. Crops that fall off the image
  cannot be scored and are kept (fail-open), matching the detector that produced them
  (`precise/combine.py:337`). Dropped counts per source are recorded in the summary.
- **Default state.** The CLI `run_precise.py --clf` and env var `PRECISE_CLF=1` are **OFF
  by default** (`CLF_ENABLED`, `precise/combine.py:85`) so the validated hand-tuned-contrast
  path is unchanged unless you ask for the gate. **However**, the desktop app and the
  in-process pipeline turn it **ON** by default for Precise (`run_inprocess(..., clf=True)`,
  `precise/pipeline.py:70`; `engine_api.detect_precise` calls `run_inprocess(... clf=True)`,
  `app/engine_api.py:225`), because the gate is the recommended Precise config there.

Honesty caveat: the classifier is trained against **detector output**, not a blinded manual
ground truth, so it can inherit detector biases. It is not human-validated (§8).

---

## 5. Calibration math

The mm scale comes entirely from the detected dish.

- **mm-per-pixel** = `plate_mm / dish_enclosing_circle_px`. In the engine:
  `mm_per_px = float(plate_size) / float(max_plate_diameter)` (`plaque_size_tool.py:385`);
  in the GUI helper: `pxl_per_mm = float(plate_size) / max_d` (`plaque_gui.py:110`). A unit
  trap worth knowing: the variable named `pxl_per_mm` throughout the GUI is *actually*
  mm-per-pixel — `plaque_gui`'s value is `plate_mm / dish_diam_px`. The Precise code is
  careful to pass it through unchanged as `mm_per_px` (`precise/pst_front.py:58`,
  `precise/run_precise.py:12`).

- **Area-equivalent diameter** = `2 · sqrt(area / π)`. For pixels:
  `2 * np.sqrt(area_pxl / np.pi)` (`plaque_gui.py:245`). For mm, the area is scaled by
  `mm_per_px²` first: `2 * sqrt(area_pxl · mm_per_px² / π)` (`plaque_size_tool.py:389`,
  `plaque_gui.py:248`). Diameter is always derived from the true area, not from a
  rounded-down intermediate (the Current-mode fix in §3).

- **Tilt (axis-ratio) check.** A tilted, non-orthographic phone shot makes the dish
  elliptical and biases every mm value. The toolkit fits an ellipse to the chosen dish hull
  (`cv2.fitEllipse`) and computes `axis_ratio = major / minor` (`dish_axis_ratio`,
  `plaque_size_tool.py:413`; the GUI computes the same on the *chosen* dish at
  `plaque_gui.py:156`). When `axis_ratio > 1.03`, the overlay and the app's summary card
  warn that calibration may be biased and ask the user to re-shoot square-on
  (`app/ui.py:354`; CLI note at `plaque_gui.py:808`). If no dish is detected, the tools fall
  back to **pixel-only** output and warn.

---

## 6. The interactive editor

`app/plaque_canvas.py` is a `QGraphicsView`-based editor (`PlaqueCanvas`) that turns
auto-detections into a hand-correctable plaque set. It keeps a stable public surface
(`.plaques`, `.save()`, `.export_groundtruth()`) so `app/ui.py` could swap it in with a
one-line change.

Tools and interactions (`_View`, `app/plaque_canvas.py:126`):

- **Add** — left-click a missed plaque to auto-trace it via `pgui.trace_at`
  (`_add_point`, `app/plaque_canvas.py:650`), or drag to draw a circle (`_add_circle`).
- **Erase** — click a detection to remove it; right-click erases in any tool
  (`_erase_at`, `app/plaque_canvas.py:641`).
- **Detect area (ROI re-scan)** — rubber-band a tight box and the detector re-scans inside
  it, adding only genuinely new plaques (`_detect_region` → `engine_api.detect_region`,
  `app/plaque_canvas.py:667`; the locked wrapper is `app/engine_api.py:81`).
- **Select / pan** — click toggles one plaque; Shift+drag box-selects, Ctrl+drag
  box-deselects; drag pans; wheel / +/- zooms at the cursor (`_box_select`,
  `app/plaque_canvas.py:599`). Undo (`u`), select-all (`Ctrl+A`), delete, fit-view are all
  bound.
- **Draggable scale bar** — a physical bar ("Auto" or a fixed 0.5–50 mm length) that can be
  grabbed and repositioned anywhere on the image, and is reproduced exactly in exports
  (`_draw_scalebar`, `app/plaque_canvas.py:461`; `_sb_hit`/`_move_scalebar`).

Exports (the `Export ▾` menu, `app/plaque_canvas.py:405`):

- **Data table (CSV)** — the per-plaque measurement rows (`export_csv`).
- **Annotated figure (PNG)** — outlines + numbers + scale bar (`export_figure`).
- **Input vs annotated (side-by-side)** (`export_comparison`).
- **Original input image** — decoded; HEIC written as PNG (`export_input`).
- **Ground-truth labels** — a JSON + sibling CSV of every (x, y, r, area, mm, source) record
  with metadata, schema `plaque-groundtruth-v1` (`export_groundtruth`,
  `app/plaque_canvas.py:769`). These hand-corrected labels are explicitly intended to drive
  engine scoring (precision/recall) and to retrain the classifier — i.e. they are the path
  to the human ground truth the toolkit currently lacks (§8).

---

## 7. Packaging

Precise needs two otherwise-incompatible worlds in one run: PST requires **numpy < 2** (the
upstream tool used `np.warnings`, removed in numpy 2.0), while PlaqSeg + the classifier need
**PyTorch + ultralytics + scikit-image**. The toolkit supports both ways of satisfying that,
and `app/engine_api.precise_available()` picks whichever is present (`app/engine_api.py:124`).

**Two-env (run-from-source).** A `plaque` env runs PST; a separate `plaqseg` env (Python
3.10, CPU torch, ultralytics, scikit-image — `environment-precise.yml`) runs PlaqSeg + the
classifier. `precise/run_precise.py` hands JSON/CSV between them as subprocesses. The app
locates the second interpreter portably with `app/env_paths.py` — the override env var
`PLAQSEG_PY`, an optional `env_paths.json`, the conda base derived from `sys.executable`, or
`conda run` (`find_env_python`, `app/env_paths.py:151`). This replaced the old hard-coded
Windows path so the same code runs on Windows/macOS/Linux.

**Unified env (frozen / in-process).** The key insight: **numpy 1.26 satisfies both** PST's
`numpy<2` pin *and* torch/ultralytics, so a single env (`plaqueapp`, `requirements_full.txt`
— numpy 1.26.4 + torch 2.x CPU + ultralytics + scikit-image + PySide6) can import
everything. `precise/pipeline.run_inprocess()` then runs every stage in the current
interpreter — no conda, no subprocess (`precise/pipeline.py:70`). `detect_precise` prefers
this whenever `torch` + `ultralytics` import in-process (`_torch_inprocess_available`,
`app/engine_api.py:106`) and otherwise falls back to the two-env subprocess path.

**PyInstaller specs** (`build/`, run from repo root):

- `build/plaque_app.spec` / `build/plaque_app_onedir.spec` — the **light** app; torch
  excluded; no Precise.
- `build/plaque_app_full.spec` — the **Full** app; `collect_all` for torch / torchvision /
  ultralytics / skimage, and the YOLO weights + classifier + `infer.py` bundled as data
  (`build/plaque_app_full.spec:22`, `:38`). Because frozen code resolves bundled data under
  `sys._MEIPASS`, the bundle mirrors the project layout (`app/resources`,
  `_plaqseg/models`, `_research/clf`), and every module checks `sys.frozen` to pick the root
  (`app/engine_api.py:23`, `precise/pipeline.py:29`, `precise/combine.py:43`). `infer.py`
  ships as a *data* file because `combine.py` loads it via `importlib` from an explicit path.
- `build/plaque_app_macos.spec` — the macOS `.app` (must be built on a Mac).

**Inno Setup installers** (`build/*.iss`). Both install side-by-side (distinct
`AppId`/name/dir), so building one never clobbers the other:

- `build/installer.iss` → `Output/PlaqueToolkitSetup.exe` (~85 MB; Published / Current /
  Sensitive).
- `build/installer_full.iss` → `Output/PlaqueToolkitFullSetup.exe` (~302 MB; **Precise built
  in**, in-process, no conda). Its header documents exactly that:
  "runs the Precise engine in-process with NO conda env and NO source checkout"
  (`build/installer_full.iss:6`).

**Acceptance gates** (headless, `docs/DEVELOPER.md`): `plaque_app.py --uitest` (build the GUI
offscreen → `UITEST OK`), `--smoke` (detect on bundled samples → `SMOKE OK`, also enforcing
the numpy<2 pin at `app/engine_api.py:328`), and `--precise-smoke` (in-process Precise →
`PRECISE_SMOKE OK`).

---

## 8. Honesty: what is — and is not — validated

This is the most important section. Conflating the validated engine with the in-house
extensions would be a real scientific error.

- **Only `Published` is citable.** It reproduces a peer-reviewed method (Trofimova &
  Jaschke 2021) byte-for-byte and may be described as such. Use it for any number that goes
  into a paper.

- **`Current`, `Sensitive`, `Precise`, and the classifier are in-house extensions that have
  NOT been independently validated.** `Current` is a near-identical superset of Published;
  `Sensitive` raises recall at the cost of false positives; `Precise` depends on PlaqSeg,
  which is itself **not peer-reviewed**; the classifier is trained against detector output
  rather than a blinded manual ground truth and can inherit detector biases. The app states
  this in its own About tab and in the engine helper text (`app/ui.py:36`, `:613`), and
  `docs/PUBLICATION.md` spells out that these modes do **not** inherit the published
  validation — you must validate them on your *own* plates and report that validation.

- **Turbidity is greyscale densitometry, not a separately validated assay**
  (`docs/PUBLICATION.md`); report it as relative optical density with the stated caveats.

- **The accuracy ceiling is imaging, not the algorithm.** These plates are typically
  top-lit, gradient-lit iPhone photos. On that input, ImageJ and the published ViralPlaque
  macro — which rely on global thresholding — fail; only adaptive-local PST and the trained
  PlaqSeg model cope (`docs/ENGINES.md`). Back-lit, evenly illuminated, straight-down
  plates are what unlock defensible numbers, especially for turbidity.

- **Human ground-truth labels are the unlock.** Because the classifier and the extended
  engines are bounded by detector-derived labels, the way to break the ceiling is blinded
  manual ground truth. The editor's `export_groundtruth` exists precisely to produce it —
  per-plaque labels usable to score the engines (precision/recall/F1) and to retrain the
  classifier (`app/plaque_canvas.py:769`).

---

## File map

| Path | Role |
|---|---|
| `plaque_size_tool.py` | **The validated engine** — detection + sizing + turbidity index + size CLI; holds the process-global flags. |
| `plaque_gui.py` | OpenCV editor + shared `run_detection` / `measure` / `trace_at` / `detect_region` / `save_results` reused by the app and Precise. |
| `plaque_turbidity.py` | Batch cross-phage turbidity (OD), titer, per-phage stats, figures (`run_batch`). |
| `app/engine_api.py` | **The only module that imports the validated engine**; locks the global flags; exposes `detect_single`, `measure_table`, `save_single`, `detect_region`, `detect_precise`, `run_compare`, `precise_available`, `smoke`. |
| `app/ui.py` | The PySide6 main window: Measure / Compare turbidity / About tabs; engine `MODES` catalogue; `launch()`, `uitest()`. |
| `app/plaque_canvas.py` | Native-Qt `QGraphicsView` editor: add/erase/trace, ROI re-scan, select, draggable scale bar, exports (CSV / figure / side-by-side / input / ground truth). |
| `app/workers.py` | Qt `Worker` threads (detection/compare run off the UI thread). |
| `app/env_paths.py` | Portable cross-platform discovery of the `plaque` / `plaqseg` conda interpreters. |
| `app/canvas_editor.py` | Earlier editor widget (superseded by `plaque_canvas.py` in the live app). |
| `precise/pst_front.py` | Precise stage 1: dish geometry + mm/px + PST normal/sensitive centers (calls `plaque_gui.run_detection`). |
| `precise/combine.py` | Precise stages 2–10: artifact masks, density switch, gated PST recall, optional blob, optional `--clf` gate, union, sizing, overlay + CSV + summary. |
| `precise/pipeline.py` | Single-process orchestrator (`run_inprocess`) — runs all Precise stages in the current interpreter (frozen Full app / `plaqueapp` env). |
| `precise/run_precise.py` | Two-env subprocess entry point (run-from-source path). |
| `_plaqseg/run_plaqseg.py` | Tiled YOLO-seg inference + global NMS (`detect_plaqseg`); model weights `_plaqseg/models/small.pt`, `nano.pt`. |
| `_research/clf/infer.py` + `plaque_clf.pt` | ResNet-18 plaque-vs-texture classifier loaded by the Precise `--clf` gate. |
| `environment.yml` / `requirements.txt` | The `plaque` env (Python 3.9, numpy<2, PySide6, OpenCV, pandas, matplotlib, pillow-heif). |
| `environment-precise.yml` | The `plaqseg` env (Python 3.10, CPU torch + ultralytics + scikit-image). |
| `requirements_full.txt` | The unified `plaqueapp` env (numpy 1.26.4 + torch CPU + ultralytics + …) for in-process Precise / the Full build. |
| `build/plaque_app*.spec` | PyInstaller specs: light onefile/onedir, the **Full** in-process build, and macOS. |
| `build/installer.iss` / `build/installer_full.iss` | Inno Setup scripts → light (~85 MB) and all-in-one (~302 MB, Precise built in) installers. |

---

*See also: `README.md` (entry point), `docs/ENGINES.md` (engines in depth), `docs/DEVELOPER.md`
(rebuild instructions), `docs/PUBLICATION.md` (the validation playbook), and
`docs/STRUCTURE.md` (every top-level item).*
