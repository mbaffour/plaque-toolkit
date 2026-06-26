# build/plaque_app_macos.spec  —  macOS .app bundle (run ON a Mac):
#     conda run -n plaque pyinstaller --noconfirm build/plaque_app_macos.spec
# Produces dist/Plaque Toolkit.app  (windowed, with icon).  Driven by build_macos.sh.
#
# PyInstaller cannot cross-compile: this spec only works when run on macOS.
# Same exclude-torch policy as the Windows specs (Precise runs via local conda envs).
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_dynamic_libs

ROOT = os.path.dirname(SPECPATH)

datas = []
datas += collect_data_files("cv2")
datas += collect_data_files("pillow_heif")
datas += collect_data_files("matplotlib")
datas += [(os.path.join(ROOT, "app", "resources"), "app/resources")]

binaries = []
binaries += collect_dynamic_libs("pillow_heif")

hiddenimports = []
hiddenimports += collect_submodules("pillow_heif")
hiddenimports += [
    "plaque_size_tool", "plaque_gui", "plaque_turbidity", "heic_to_tiff",
    "app", "app.engine_api", "app.workers", "app.ui", "app.widgets",
    "app.canvas_editor", "app.env_paths",
    "imutils", "pandas", "PIL.ImageOps", "PIL.ImageStat", "PIL.ImageEnhance",
    "matplotlib.backends.backend_qtagg",
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
    excludes=["PyQt5", "PyQt6", "tensorflow", "torch", "scipy"],
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
