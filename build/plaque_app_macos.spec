# build/plaque_app_macos.spec  —  macOS .app bundle WITH the Precise engine (run ON a Mac):
#     conda run -n plaqueapp pyinstaller --noconfirm build/plaque_app_macos.spec
# Produces dist/Plaque Toolkit.app  (windowed, with icon).  Driven by build_macos.sh.
#
# PyInstaller cannot cross-compile: this spec only works when run on macOS. Build it with a Mac
# conda env that has torch (CPU) + ultralytics + scikit-image (the macOS equivalent of the
# Windows 'plaqueapp' env) so the frozen app runs the Precise pipeline IN-PROCESS — this mirrors
# build/plaque_app_full.spec on Windows (no conda envs needed at run time).
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
datas += [(os.path.join(ROOT, "app", "resources"), "app/resources")]
datas += [(os.path.join(ROOT, "_plaqseg", "models", "small.pt"), "_plaqseg/models")]
datas += [(os.path.join(ROOT, "_plaqseg", "models", "nano.pt"), "_plaqseg/models")]
datas += [(os.path.join(ROOT, "_research", "clf", "plaque_clf.pt"), "_research/clf")]
datas += [(os.path.join(ROOT, "_research", "clf", "infer.py"), "_research/clf")]
datas += [(os.path.join(ROOT, "docs"), "docs")]

hiddenimports += [
    # project modules
    "plaque_size_tool", "plaque_gui", "plaque_turbidity", "heic_to_tiff", "scalebar",
    "plate_crop",
    "app", "app.engine_api", "app.workers", "app.ui", "app.widgets", "app.canvas_editor",
    "app.style", "app.env_paths", "app.plaque_canvas",
    "app.imagej_roi", "app.fiji_match", "app.fiji_export", "app.fiji_dialog",
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

# build_macos.sh generates icon.icns from icon.png next to the resources; use it if present.
_icns = os.path.join(ROOT, "app", "resources", "icon.icns")
icon = _icns if os.path.exists(_icns) else None

a = Analysis(
    [os.path.join(ROOT, "plaque_app.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # NOTE: do NOT exclude torch/scipy here — Precise is bundled (mirrors the Windows Full build).
    excludes=["PyQt5", "PyQt6", "tensorflow"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name="Plaque Toolkit",
    debug=False, strip=False, upx=False,
    console=False,                      # windowed app
    disable_windowed_traceback=False,
    icon=icon,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Plaque Toolkit")

app = BUNDLE(
    coll,
    name="Plaque Toolkit.app",
    icon=icon,
    bundle_identifier="org.plaquetoolkit.app",
    info_plist={
        "CFBundleName": "Plaque Toolkit",
        "CFBundleDisplayName": "Plaque Toolkit",
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleVersion": "1.0.0",
        "NSHighResolutionCapable": True,
        "NSRequiresAquaSystemAppearance": False,
    },
)
