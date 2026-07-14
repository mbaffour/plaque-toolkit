# -*- mode: python ; coding: utf-8 -*-
# agreement_app.spec -- freeze the Agreement (tool vs manual) Shiny app into a standalone folder.
#
# Build (from agreement/build_exe/):
#   & "C:/Users/mbaff/Miniconda3/envs/plaqueapp/python.exe" -m PyInstaller --noconfirm --clean agreement_app.spec
# Output:
#   dist/Plaque Agreement App/Plaque Agreement App.exe   (one-dir bundle; ship the whole folder)
#
# Mirrors plaque_stats/build_exe/plaque_stats_app.spec (same shiny/uvicorn stack), for the
# agreement app + its scipy-backed engine. One-dir for robust startup with the shiny www/ assets.

import os
import importlib.util

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

BUILD_DIR = SPECPATH                       # agreement/build_exe/
PROJECT = os.path.dirname(SPECPATH)        # the agreement/ folder (app_py.py, agreement.py, GUIDE.html)


def _proj(*parts):
    return os.path.join(PROJECT, *parts)


def _maybe(mods):
    out = []
    for m in mods:
        try:
            if importlib.util.find_spec(m) is not None:
                out.append(m)
        except (ImportError, ModuleNotFoundError, ValueError):
            pass
    return out


# DATA FILES: the app resolves example CSV + GUIDE via os.path.join(HERE, ...) where HERE =
# dirname(abspath(app_py.__file__)) = the bundle root when frozen -> drop these at '.'.
datas = []
for fn in ("app_py.py", "agreement.py", "GUIDE.html",
           "example_agreement.csv", "example_output.png"):
    src = _proj(fn)
    if os.path.exists(src):
        datas.append((src, "."))
# Shiny + htmltools + shinychat static assets (served to the browser) + matplotlib mpl-data.
datas += collect_data_files("shiny")
datas += collect_data_files("htmltools")
datas += collect_data_files("shinychat")
datas += collect_data_files("matplotlib", subdir="mpl-data")

hiddenimports = []
for pkg in ("uvicorn", "starlette", "websockets", "shiny", "shinychat", "htmltools", "anyio"):
    hiddenimports += collect_submodules(pkg)

hiddenimports += _maybe([
    "uvicorn.logging",
    "uvicorn.loops.auto", "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto", "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto", "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan.on", "uvicorn.lifespan.off",
    "websockets", "wsproto", "h11", "anyio", "sniffio", "asgiref",
    "starlette", "starlette.middleware", "click", "watchfiles",
    "linkify_it", "uc_micro", "markdown_it",
    "app_py", "agreement", "shiny", "shiny._main",
    # engine deps: agreement.py uses scipy.stats + numpy + pandas
    "openpyxl", "pandas", "numpy", "scipy", "scipy.stats",
    "matplotlib.backends.backend_agg",
    "matplotlib.backends.backend_svg",
    "matplotlib.backends.backend_pdf",
])

_DROP_PREFIX = ("shiny.pytest", "shiny.playwright")
hiddenimports = sorted({h for h in hiddenimports if not h.startswith(_DROP_PREFIX)})

a = Analysis(
    [os.path.join(BUILD_DIR, "freeze_entry.py")],
    pathex=[PROJECT, BUILD_DIR],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter", "PyQt5", "PyQt6", "PySide2", "PySide6",
        "pytest", "playwright", "IPython", "notebook", "jupyter",
        # deep-learning stack the plaqueapp env carries for the desktop Precise engine;
        # the agreement app never touches it (drops ~700 MB). scipy is KEPT (engine needs it).
        "torch", "torchvision", "torchaudio", "sympy", "networkx",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Plaque Agreement App",
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=True, disable_windowed_traceback=False, argv_emulation=False,
    target_arch=None, codesign_identity=None, entitlements_file=None, icon=None,
)

coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, upx_exclude=[],
               name="Plaque Agreement App")
