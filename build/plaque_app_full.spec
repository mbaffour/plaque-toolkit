# build/plaque_app_full.spec  —  SELF-CONTAINED ONEDIR build WITH the Precise engine.
#
# Unlike plaque_app_onedir.spec (the light build that omits torch), this bundles torch +
# ultralytics + scikit-image + the YOLO weights + the learned classifier, so the frozen
# app runs the Precise pipeline IN-PROCESS — no conda envs, no source checkout.
#
# Build with the unified 'plaqueapp' env's python (numpy 1.26 + torch CPU + ultralytics):
#     conda run -n plaqueapp pyinstaller --noconfirm build/plaque_app_full.spec
# Produces dist/PlaqueToolkitFull/PlaqueToolkit.exe (+ deps). Expect ~1.5-3 GB. -> installer_full.iss
import os
from PyInstaller.utils.hooks import (
    collect_data_files, collect_submodules, collect_dynamic_libs, collect_all,
)

ROOT = os.path.dirname(SPECPATH)

datas = []
binaries = []
hiddenimports = []

# ---- the heavy ML stack: torch, torchvision, ultralytics, skimage ---------- #
for pkg in ("torch", "torchvision", "ultralytics", "skimage"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# cv2 / pillow_heif / matplotlib data + libs
datas += collect_data_files("cv2")
datas += collect_data_files("pillow_heif")
datas += collect_data_files("matplotlib")
binaries += collect_dynamic_libs("pillow_heif")
hiddenimports += collect_submodules("pillow_heif")

# ---- app data files: resources + Precise models/classifier/infer source ----- #
# These are resolved at runtime under sys._MEIPASS, so the bundle layout must mirror
# the project layout (app/resources, _plaqseg/models, _research/clf).
datas += [(os.path.join(ROOT, "app", "resources"), "app/resources")]
datas += [(os.path.join(ROOT, "_plaqseg", "models", "small.pt"), "_plaqseg/models")]
datas += [(os.path.join(ROOT, "_plaqseg", "models", "nano.pt"), "_plaqseg/models")]
datas += [(os.path.join(ROOT, "_research", "clf", "plaque_clf.pt"), "_research/clf")]
# infer.py is loaded by precise/combine.py via importlib from an explicit file path,
# so it must ship as a DATA file at _research/clf/infer.py (not just as a module).
datas += [(os.path.join(ROOT, "_research", "clf", "infer.py"), "_research/clf")]

# ---- explicit hidden imports the analyzer can miss ------------------------- #
hiddenimports += [
    # project modules
    "plaque_size_tool", "plaque_gui", "plaque_turbidity", "heic_to_tiff", "scalebar",
    "app", "app.engine_api", "app.workers", "app.ui", "app.widgets", "app.canvas_editor",
    "app.style", "app.env_paths",
    # the in-process Precise package
    "precise", "precise.pipeline", "precise.combine", "precise.pst_front",
    "_plaqseg", "_plaqseg.run_plaqseg",
    # third-party that PyInstaller sometimes underlinks
    "cv2", "imutils", "pandas", "scipy", "scipy.ndimage",
    "PIL.ImageOps", "PIL.ImageStat", "PIL.ImageEnhance",
    "skimage.feature", "skimage.feature.blob",
    "matplotlib.backends.backend_qtagg",
    "torchvision.models", "torchvision.models.resnet",
]

a = Analysis(
    [os.path.join(ROOT, "plaque_app.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # NOTE: do NOT exclude torch/scipy here (the whole point of this build).
    excludes=["PyQt5", "PyQt6", "tensorflow"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name="PlaqueToolkit",
    debug=False, strip=False, upx=False,
    console=False,                      # windowed app
    disable_windowed_traceback=False,
    icon=os.path.join(ROOT, "app", "resources", "icon.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="PlaqueToolkitFull")
