# Installing & running the Plaque Toolkit

The Plaque Toolkit is a cross-platform desktop app (Windows, macOS, Linux) for
measuring bacteriophage plaques. There are two ways to use it:

1. **Run from source** (any OS) — create a conda environment and launch the app.
   Recommended for macOS/Linux and for anyone who already has conda.
2. **Windows installer / portable app** — a packaged `.exe` with no Python needed.

The app's core detection modes (**Published**, **Current**, **Sensitive**) need only
the one `plaque` environment. The optional **Precise** mode (PST + PlaqSeg YOLO)
additionally needs PyTorch + ultralytics; see the last section.

### Which Windows installer? (in `Output\`)

| Installer | Size | Includes Precise? | Needs conda? |
|---|---|---|---|
| **`PlaqueToolkitSetup.exe`** | ~85 MB | No — Published/Current/Sensitive only (Precise works if you have a local `plaqseg` env / source) | No |
| **`PlaqueToolkitFullSetup.exe`** | ~302 MB | **Yes — Precise built in** (torch + ultralytics + YOLO weights bundled) | **No** |

Pick the **Full** installer if you want Precise with zero setup; pick the smaller one if you
don't need Precise (or will supply the `plaqseg` env yourself).

---

## 1. Run from source (Windows / macOS / Linux)

### Prerequisites
Install a conda distribution if you don't have one:
[Miniconda](https://docs.conda.io/en/latest/miniconda.html) or
[Miniforge](https://github.com/conda-forge/miniforge) (Miniforge is recommended on
Apple Silicon). `mamba` works too and is faster.

### Create the environment

**Windows** (Anaconda Prompt or PowerShell):
```
conda env create -f environment.yml
```
Or double-click **`install.bat`** path note: that script installs a *built* app —
to create the source env just run the conda command above, or use the build below.

**macOS** — double-click **`setup.command`** in Finder (first time you may need to
right-click → Open to clear Gatekeeper, or run `chmod +x setup.command` once).

**Linux** — run **`./setup.sh`**.

All of these create a conda env named **`plaque`** from `environment.yml`
(Python 3.9, PySide6, OpenCV, pandas, matplotlib, pillow-heif, imutils, numpy<2).

### Launch the app

| OS | Double-click | or from a terminal |
|----|--------------|--------------------|
| Windows | **`Plaque Toolkit.bat`** | `conda run -n plaque python plaque_app.py` |
| macOS   | **`Plaque Toolkit.command`** | `conda run -n plaque python plaque_app.py` |
| Linux   | **`Plaque Toolkit.sh`** | `conda run -n plaque python plaque_app.py` |

The launchers auto-find your `plaque` env (common conda locations), and fall back to
`conda run`. To force a specific interpreter, set the `PLAQUE_PY` environment variable
to your env's `python` (or `pythonw.exe` on Windows).

### Quick self-test (headless)
```
conda run -n plaque python plaque_app.py --smoke
```
Prints the package versions and runs detection on the two bundled sample images.
You should see `SMOKE OK`.

---

## 2. Windows installer / portable app

On a Windows machine with the `plaque` env created:

```
conda run -n plaque pyinstaller --noconfirm build/plaque_app_onedir.spec
```

This produces `dist/PlaqueToolkit/PlaqueToolkit.exe` (a self-contained folder — no
Python needed to run it). Then either:

- **Portable:** zip `dist/PlaqueToolkit/` and copy it anywhere, or
- **Per-user install:** run **`install.bat`** (copies it to `%LOCALAPPDATA%` and adds a
  Start-menu shortcut; uninstall with `uninstall.bat`), or
- **Shareable installer:** with [Inno Setup](https://jrsoftware.org/isdl.php) installed,
  run `build_installer.bat` (or `ISCC build\installer.iss`) to get
  `Output/PlaqueToolkitSetup.exe`.

The installer intentionally does **not** bundle PyTorch/ultralytics, so it stays light
(~150 MB). Precise mode in the packaged app still works *if* the user has a local
`plaqseg` conda env (see below).

---

## 3. macOS app bundle

PyInstaller cannot cross-compile — the Mac `.app` must be built **on a Mac**. Run:

```
./build_macos.sh
```

This creates `dist/Plaque Toolkit.app` (windowed, with the icon) and, if
`create-dmg`/`hdiutil` is available, a `.dmg`. See the script header for details.

---

## 4. Optional: the Precise engine (second environment)

Precise (PST + PlaqSeg YOLO-seg) needs a second conda env named **`plaqseg`**:

```
conda env create -f environment-precise.yml
```

This installs Python 3.10, CPU PyTorch, ultralytics, scikit-image. You also need the
model weights at `_plaqseg/models/small.pt`. The app auto-detects the env via
`app/env_paths.py`:

- Windows: `…/envs/plaqseg/python.exe`
- macOS / Linux: `…/envs/plaqseg/bin/python`

To point at a non-standard location, set the `PLAQSEG_PY` environment variable, or drop
an `env_paths.json` in the project root:
```json
{ "plaqseg": "/opt/miniconda3/envs/plaqseg/bin/python" }
```

If the `plaqseg` env or weights are missing, the **Precise** button shows a friendly
message and the other three modes keep working.
