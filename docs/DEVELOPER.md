# Developer guide

How the Plaque Toolkit is put together, the environment design behind the **Precise** engine,
and how to rebuild the apps and installers.

---

## File map (code)

| Path | Role |
|---|---|
| `plaque_size_tool.py` | **The validated engine.** Detection + sizing + turbidity index + the size CLI. Holds process-global flags (`use_published`, `watershed_enabled`, `small_plaques`). |
| `plaque_gui.py` | Standalone OpenCV interactive editor; also exposes `run_detection()` / `measure()` / `save_results()` reused by the app and Precise. |
| `plaque_turbidity.py` | Batch cross-phage turbidity (OD), titer, per-phage stats, QC, figures (`run_batch()`). |
| `scalebar.py` | Reusable physical "5 mm" scale-bar overlay (pure cv2/numpy). |
| `add_scale.py` | CLI that stamps a scale bar onto any photo using the dish calibration. |
| `heic_to_tiff.py` | HEIC → TIFF converter (most tools read HEIC directly via pillow-heif). |
| `summarize_plates.py` | Aggregates `data-green-*.csv` → `summary.csv` (no re-detection). |
| `measure_samples.py` | Walks a sample-folder tree → per-photo normal + sensitive results + dish-check images + `SUMMARY.csv`. |
| `compile_excel.py` | Compiles per-photo PST results into one Excel workbook. |
| `make_figure.py`, `plot_sensitive_violin.py` | Publication violin figures (pooled distribution + per-plate medians). |
| `run_viralplaque.py` | Drives the external ImageJ ViralPlaque macro (cross-tool comparison; uses `_imagej/`). |
| `plaque_app.py` | Desktop-app entry point + headless self-tests (`--smoke`, `--uitest`, `--precise-smoke`). |
| `app/` | The PySide6 desktop app (see below). |
| `precise/` | The Precise pipeline (see below). |
| `_plaqseg/` | PlaqSeg YOLO runner + model weights (`models/small.pt`, `nano.pt`). |
| `_research/clf/` | The learned plaque-vs-texture classifier (`plaque_clf.pt` + `infer.py`) — **required by Precise when `--clf` is on**. |

### `app/` (the desktop GUI)

| Module | Role |
|---|---|
| `app/ui.py` | Builds and launches the main window; `launch()`, `uitest()`. |
| `app/engine_api.py` | **The only module that imports the validated engine.** Funnels every engine call through a lock so the process-global flags are set atomically; exposes `detect_single`, `measure_table`, `save_single`, `detect_precise`, `run_compare`, `precise_available`, `smoke`. |
| `app/workers.py` | Qt worker threads (detection/compare run off the UI thread). |
| `app/canvas_editor.py` | The editable image canvas (zoom, add/remove, dish circle). |
| `app/widgets.py`, `app/style.py` | Reusable widgets and theming. |
| `app/env_paths.py` | **Portable** discovery of the `plaque` / `plaqseg` conda interpreters (replaces the old hard-coded paths). |
| `app/resources/` | Bundled icon + sample images (also packaged into the frozen app). |

### `precise/` (the Precise pipeline)

| Module | Role |
|---|---|
| `precise/pst_front.py` | Stage 1: dish geometry + mm/px + PST normal/sensitive centers (calls `plaque_gui.run_detection`). |
| `precise/combine.py` | Stages 2–10: artifact masks, density switch, gated PST recall, optional blob, the optional `--clf` gate, union, sizing, overlay + CSV + summary. |
| `precise/pipeline.py` | **Single-process orchestrator** (`run_inprocess`) — runs every stage in the current interpreter (used by the frozen Full app and the unified `plaqueapp` env). |
| `precise/run_precise.py` | **Two-env subprocess** entry point (the run-from-source path; launched by `Precise Detect (best engine).bat`). |
| `precise/test_calibration.py` | Calibration sanity checks. |

---

## The two-env vs unified-env design

Precise needs two otherwise-incompatible worlds in one run:

- **PST** (`plaque_size_tool`, `plaque_gui`) requires **`numpy < 2`** (the upstream tool used
  `np.warnings`, removed in numpy 2.0) and OpenCV.
- **PlaqSeg + the classifier** need **PyTorch + ultralytics** (and `scikit-image`).

There are two supported ways to satisfy both, and `app/engine_api.precise_available()` /
`detect_precise()` automatically pick whichever is present:

1. **Two-env subprocess (run-from-source).** A `plaque` env runs PST; a separate `plaqseg`
   env (Python 3.10, CPU torch, ultralytics) runs PlaqSeg + the classifier.
   `precise/run_precise.py` hands data between them. The app locates the `plaqseg` interpreter
   portably via `app/env_paths.py` (override with `PLAQSEG_PY`, or an `env_paths.json` at the
   project root).
2. **Unified env / frozen app (in-process).** **numpy 1.26 satisfies both** PST's `numpy<2`
   pin *and* torch/ultralytics, so a single env (**`plaqueapp`**) can import everything.
   `precise/pipeline.run_inprocess()` then runs all stages in one process — no conda
   subprocesses. This is what makes the self-contained **Full** installer work.

`torch_inprocess_available()` decides between them: if torch + ultralytics import in the
current interpreter, Precise runs in-process; otherwise it falls back to the subprocess path.

> **Frozen paths.** Under PyInstaller, bundled data (`_plaqseg/models`, `_research/clf`,
> `app/resources`) is extracted to `sys._MEIPASS`; the code checks `sys.frozen` and resolves
> the root accordingly, so the same modules run from source and frozen.

---

## Environments

| Env | Python | Purpose | File |
|---|---|---|---|
| `plaque` | 3.9 | The app + validated engine + turbidity (numpy<2, PySide6, OpenCV, pandas, matplotlib, pillow-heif). | `environment.yml` / `requirements.txt` |
| `plaqseg` | 3.10 | Two-env Precise: CPU torch + ultralytics + scikit-image. | `environment-precise.yml` |
| `plaqueapp` | — | Unified env (numpy 1.26 + torch + ultralytics) used to build the **Full** in-process app and to run `--precise-smoke`. | `requirements_full.txt` |

> **Hard pin:** never `pip install --upgrade numpy` in `plaque`/`plaqueapp` — keep `numpy < 2`.

---

## Headless self-tests (CI / acceptance gates)

```bash
# construct the GUI offscreen (no engine run) — should print "UITEST OK"
conda run -n plaque python plaque_app.py --uitest

# detection smoke on the bundled samples — should print "SMOKE OK"
conda run -n plaque python plaque_app.py --smoke

# in-process Precise on the bundled sample (needs torch+ultralytics) — "PRECISE_SMOKE OK"
conda run -n plaqueapp python plaque_app.py --precise-smoke

# Precise pipeline imports cleanly
conda run -n plaqueapp python -c "import precise.pipeline; print('OK')"
```

---

## Rebuilding the apps and installers

All specs live in `build/` and are run **from the repo root**.

| Target | Build command | Output | Notes |
|---|---|---|---|
| Portable single-file app | `conda run -n plaque pyinstaller --noconfirm build/plaque_app.spec` | `dist/PlaqueToolkit.exe` | No Precise (torch excluded). |
| Onedir app (for the light installer) | `conda run -n plaque pyinstaller --noconfirm build/plaque_app_onedir.spec` | `dist/PlaqueToolkit/` | No Precise; faster launch than onefile. |
| **Full** app (Precise built in) | `conda run -n plaqueapp pyinstaller --noconfirm build/plaque_app_full.spec` | `dist/PlaqueToolkitFull/` | Bundles torch + ultralytics + YOLO weights + classifier. Large (~1.5–3 GB before installer compression). |
| macOS `.app` | `./build_macos.sh` (runs `build/plaque_app_macos.spec`) | `dist/Plaque Toolkit.app` (+ `.dmg`) | **Must be built on a Mac** (PyInstaller can't cross-compile). |

### Installers (Inno Setup)

Both `.iss` scripts install **side by side** (different AppId/name/dir), so building one never
clobbers the other.

| Installer | Source spec output | ISS | Command |
|---|---|---|---|
| `Output/PlaqueToolkitSetup.exe` (~85 MB) | `dist/PlaqueToolkit/` | `build/installer.iss` | `build_installer.bat` (or `ISCC build\installer.iss`) — auto-installs Inno Setup via winget if missing. |
| `Output/PlaqueToolkitFullSetup.exe` (~302 MB) | `dist/PlaqueToolkitFull/` | `build/installer_full.iss` | `ISCC build\installer_full.iss` |

Inno Setup 6 is required (`ISCC.exe`). `build_installer.bat` searches the common install
locations and falls back to `winget install JRSoftware.InnoSetup`.

---

## Cross-platform run-from-source

`environment.yml` + the launchers (`Plaque Toolkit.bat` / `.command` / `.sh`,
`setup.command` / `setup.sh`) cover Windows/macOS/Linux. The launchers auto-find the `plaque`
env in common conda locations and fall back to `conda run`; force a specific interpreter with
the `PLAQUE_PY` environment variable. `build_macos.sh` produces the Mac `.app`.

The root `.bat` launchers (`Measure Plaques.bat`, etc.) hard-code the local
`C:\Users\mbaff\Miniconda3\envs\plaque\python.exe` and fall back to `python` on PATH — they are
this machine's drag-and-drop convenience scripts. The portable, cross-platform entry points are
the `Plaque Toolkit.*` launchers and the app itself.
