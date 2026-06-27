# Repository structure

Every top-level item, what it is, and whether it's safe to move. The tree is necessarily
complex because the toolkit ships a CLI, a desktop app, two installers, a deep-learning engine,
and a research/validation history — this map keeps it navigable.

> **Do not move/rename** anything marked **🔒 load-bearing** — code imports, launchers,
> installers, and the Precise engine reference these by hard-coded path.

---

## Documentation

| Item | Purpose |
|---|---|
| `README.md` | **Project entry point.** What it is, quick start, the four engines, links into `docs/`. Stays at root. |
| `docs/` | All other documentation (see below). |
| `Manual_images/` | Screenshots referenced by the upstream manual (`docs/UPSTREAM_README.md`). 🔒 (referenced by relative links) |

### `docs/`

| Item | Purpose |
|---|---|
| `docs/USER_GUIDE.md` | How to do each task (measure, edit, batch, turbidity, scale bars, outputs, troubleshooting). |
| `docs/ENGINES.md` | The four detection modes in depth + when to use each + validation status. |
| `docs/INSTALL.md` | Install on Windows/macOS/Linux; the two installers; the optional Precise env. |
| `docs/PUBLICATION.md` | The honest validation playbook (ground truth, stats, negative control, Methods text). |
| `docs/DEVELOPER.md` | File map, the two-env vs unified-env design, the ML classifier, rebuilding the installers. |
| `docs/PLAQUE_SIZE_TOOL.md` | Focused reference for the core `plaque_size_tool.py` size CLI. |
| `docs/UPSTREAM_README.md` | The original upstream Plaque Size Tool manual, preserved verbatim (image links repointed to `../Manual_images/`). |
| `docs/STRUCTURE.md` | This file. |
| `docs/guide.html`, `docs/setup_and_run.html` | Interactive HTML guides (self-contained; open in a browser). |

---

## Engine & app code 🔒

| Item | Purpose |
|---|---|
| `plaque_size_tool.py` | The validated detection/sizing engine + size CLI. |
| `plaque_gui.py` | OpenCV interactive editor + shared detection helpers. |
| `plaque_turbidity.py` | Batch cross-phage turbidity (OD), titer, stats, figures. |
| `scalebar.py`, `add_scale.py` | Physical scale-bar overlay (library + CLI). |
| `heic_to_tiff.py` | HEIC → TIFF converter. |
| `summarize_plates.py` | Aggregate per-plate CSVs → `summary.csv`. |
| `measure_samples.py`, `compile_excel.py` | Sample-tree batch measurement + Excel compilation. |
| `make_figure.py`, `plot_sensitive_violin.py` | Publication violin figures. |
| `run_viralplaque.py` | Drives the external ImageJ ViralPlaque macro (uses `_imagej/`). |
| `plaque_app.py` | Desktop-app entry point + headless self-tests. |
| `app/` | The PySide6 desktop app (UI, engine adapter, workers, canvas, portable env discovery, resources). |
| `precise/` | The Precise pipeline (`pst_front`, `combine`, `pipeline`, `run_precise`). |
| `_plaqseg/` | PlaqSeg YOLO runner + model weights (`models/small.pt`, `nano.pt`). |
| `_research/clf/` | The learned plaque-vs-texture classifier (`plaque_clf.pt` + `infer.py`) — used by Precise's `--clf` gate. |
| `setup.py`, `pyproject.toml` | Packaging metadata for the underlying tool. 🔒 |

---

## Launchers (drag-and-drop / double-click) 🔒

| Item | Purpose |
|---|---|
| `Measure Plaques.bat` | Auto-measure size + turbidity (Current engine). |
| `Edit Plaques (GUI).bat` | Interactive click-editor with live Sensitive toggle + dish circle. |
| `Batch Plates (CSV per plate).bat` | Measure a folder → one CSV per plate + `summary.csv`. |
| `Original Plaque Size Tool (1 plate).bat` / `(batch).bat` | Hard-wired **Published** (citable) engine. |
| `Compare Turbidity.bat` | Cross-phage optical-density turbidity. |
| `Precise Detect (best engine).bat` | The Precise (PST + PlaqSeg) detector (two-env path). |
| `Add Scale Bar.bat` | Stamp a physical scale bar onto a photo. |
| `Plaque Toolkit (app).bat` | Launch the app from source (this machine's paths). |
| `Plaque Toolkit.bat` / `.command` / `.sh` | **Portable** app launchers (Windows/macOS/Linux). |
| `setup.command` / `setup.sh` | Create the `plaque` env on macOS / Linux. |
| `install.bat` / `uninstall.bat` | Install the built app to the Start menu (no admin) / remove it. |
| `build_installer.bat` | Build the light Windows installer via Inno Setup. |
| `build_macos.sh` | Build the macOS `.app` (run on a Mac). |
| `Plaque Toolkit (all versions)/` | A hub folder of numbered launchers + an interactive HTML readme. |

---

## Environments & build 🔒

| Item | Purpose |
|---|---|
| `environment.yml` / `requirements.txt` | The `plaque` env (Python 3.9, numpy<2, PySide6, OpenCV…). |
| `environment-precise.yml` | The optional `plaqseg` env (CPU torch + ultralytics). |
| `requirements_full.txt` | Deps for the unified `plaqueapp` env (in-process Precise / Full build). |
| `build/` | PyInstaller specs (`*.spec`) + Inno Setup scripts (`installer.iss`, `installer_full.iss`). The `_work/`, `_pyi_work/`, `localpycs/` subfolders are build scratch (gitignored). |
| `.gitattributes` / `.gitignore` | Line-ending rules (LF scripts, CRLF .bat) + ignore rules. |
| `LICENSE` | License. |

---

## Build outputs & installers (generated; gitignored)

| Item | Purpose |
|---|---|
| `dist/` | Built apps: `PlaqueToolkit.exe` (portable), `PlaqueToolkit/` (onedir), `PlaqueToolkitFull/` (Precise), the portable zip. |
| `Output/` | The shareable installers: `PlaqueToolkitSetup.exe` (~85 MB) and `PlaqueToolkitFullSetup.exe` (~302 MB, Precise built in). |

---

## Sample data, research artifacts & results

| Item | Purpose |
|---|---|
| `Test_plates/` | Bundled sample plates (`large/`, `small/`) to try the tools. 🔒 (referenced by docs/examples) |
| `Plaques to measure/` | The 21-plate study (7 phages × 3 replicates) with its compiled Excel, violins, and plot CSVs. 🔒 |
| `plates/` | Default input folder for `Batch Plates (CSV per plate).bat` (currently holds two sample plates). |
| `IMG_3901.jpeg`, `IMG_3964.jpeg` | Calibration/ground-truth input photos referenced by several `_research/` scripts. **Keep.** |
| `_research/` | Validation & method-development history: ground truth, blob/ensemble experiments, sweeps, the classifier (`clf/`). 🔒 (`clf/` is a Precise dep). |
| `_imagej/` | ImageJ + the ViralPlaque macros used by `run_viralplaque.py` for the cross-tool comparison. 🔒 |
| `_robust/`, `_vfolder/` | Small image fixtures used in ad-hoc testing (gitignored). |
| `out/`, `out_turbidity/`, `out_precise*/` | Tool results — created on first run, regenerable (gitignored). |
| `_roboflow_key.txt` | A secret (gitignored; never commit). |
| `__pycache__/`, `*.pyc` | Python bytecode cache (gitignored). |

---

## What was reorganized

- The scattered docs (`USER_GUIDE.md`, `PLAQUE_SIZE_TOOL.md`, `INSTALL.md`, `guide.html`,
  `setup_and_run.html`) were **moved into `docs/`**; the old root `README.md` (the upstream
  manual) was preserved as `docs/UPSTREAM_README.md` and a new entry-point `README.md` written.
- The interactive HTML readme in `Plaque Toolkit (all versions)/` had its footer links
  repointed to `../docs/…`.
- Regenerable turbidity test-output folders (`out_turb_*`, `_vt2`) and the gitignored
  `_gen_samples.py` scratch were removed; `.gitignore` was extended to cover them and other
  scratch/secret/build-output patterns.
- **Nothing load-bearing was moved** — all code modules, packages, launchers, installers, and
  the Precise engine stayed exactly where their hard-coded paths expect them.
