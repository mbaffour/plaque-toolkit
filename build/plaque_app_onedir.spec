# build/plaque_app_onedir.spec  —  ONEDIR build for the installer (faster launch than onefile):
#     conda run -n plaque pyinstaller --noconfirm build/plaque_app_onedir.spec
# Produces dist/PlaqueToolkit/PlaqueToolkit.exe (+ dependency folder) -> fed to installer.iss
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_dynamic_libs

ROOT = os.path.dirname(SPECPATH)

datas = []
datas += collect_data_files("cv2")
datas += collect_data_files("pillow_heif")
datas += collect_data_files("matplotlib")
datas += [(os.path.join(ROOT, "app", "resources"), "app/resources")]

# NOTE on Precise in the frozen build:
# The packaged .exe is for users WITHOUT Python and intentionally does NOT support the
# Precise engine. Precise spawns subprocesses in two conda envs (plaque + plaqseg) that
# import the source modules (plaque_gui, plaque_size_tool, etc.), so it needs the source
# checkout + both envs — i.e. the run-from-source path. The frozen app therefore reports
# Precise as unavailable (Published / Current / Sensitive all work). Keeping torch and the
# 23 MB weights out of the bundle is what keeps it light.

binaries = []
binaries += collect_dynamic_libs("pillow_heif")

hiddenimports = []
hiddenimports += collect_submodules("pillow_heif")
hiddenimports += [
    "plaque_size_tool", "plaque_gui", "plaque_turbidity", "heic_to_tiff", "scalebar", "plate_crop",
    "app", "app.engine_api", "app.workers", "app.ui", "app.widgets", "app.canvas_editor",
    "app.style", "app.env_paths", "app.plaque_canvas",
    "app.imagej_roi", "app.fiji_match", "app.fiji_export", "app.fiji_dialog",
    "imutils", "pandas", "PIL.ImageOps", "PIL.ImageStat", "PIL.ImageEnhance",
    "matplotlib.backends.backend_qtagg",
]

a = Analysis(
    [os.path.join(ROOT, "plaque_app.py")],
    pathex=[ROOT],
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
    pyz, a.scripts, [], exclude_binaries=True,
    name="PlaqueToolkit",
    debug=False, strip=False, upx=False,
    console=False,                      # windowed app
    disable_windowed_traceback=False,
    icon=os.path.join(ROOT, "app", "resources", "icon.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="PlaqueToolkit")
