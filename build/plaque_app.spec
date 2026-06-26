# build/plaque_app.spec  —  run from the repo root:
#     conda run -n plaque pyinstaller --noconfirm build/plaque_app.spec
# Produces a portable single-file dist/PlaqueToolkit.exe
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_dynamic_libs

# SPECPATH is the folder containing this spec (…/build); the repo root is its parent.
ROOT = os.path.dirname(SPECPATH)

datas = []
datas += collect_data_files("cv2")
datas += collect_data_files("pillow_heif")          # libheif data
datas += collect_data_files("matplotlib")           # mpl-data
datas += [(os.path.join(ROOT, "app", "resources"), "app/resources")]   # bundled sample images

binaries = []
binaries += collect_dynamic_libs("pillow_heif")     # native HEIF/AVIF DLLs (the #1 risk)

hiddenimports = []
hiddenimports += collect_submodules("pillow_heif")
hiddenimports += [
    "plaque_size_tool", "plaque_gui", "plaque_turbidity", "heic_to_tiff", "scalebar",
    "app", "app.engine_api", "app.workers", "app.ui", "app.widgets", "app.canvas_editor",
    "app.style", "app.env_paths",
    "imutils", "pandas",
    "PIL.ImageOps", "PIL.ImageStat", "PIL.ImageEnhance",
    "matplotlib.backends.backend_qtagg",
]

a = Analysis(
    [os.path.join(ROOT, "plaque_app.py")],
    pathex=[ROOT],                      # so `import plaque_size_tool` etc. resolve
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["PyQt5", "PyQt6", "tensorflow", "torch", "scipy"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PlaqueToolkit",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,                      # windowed release (--smoke/--uitest still return exit codes)
    disable_windowed_traceback=False,
    icon=os.path.join(ROOT, "app", "resources", "icon.ico"),
)
