# -*- mode: python ; coding: utf-8 -*-
# plaque_stats_app.spec -- freeze the Shiny for Python app into a standalone Windows folder.
#
# Build (from build_exe/):
#   & "C:/Users/mbaff/Miniconda3/envs/plaqueapp/python.exe" -m PyInstaller --noconfirm --clean plaque_stats_app.spec
# Output:
#   dist/Plaque Stats App/Plaque Stats App.exe   (one-dir bundle; ship the whole folder)
#
# ONE-DIR vs ONE-FILE:
#   This spec builds ONE-DIR (a folder with the .exe + an _internal/ payload). One-dir is the
#   robust choice for the shiny/uvicorn/starlette stack: hundreds of shiny www/ assets and
#   htmltools lib/ files stay as real files on disk (fast startup, easy to inspect/patch), and
#   there is no per-launch self-extraction to a temp dir. ONE-FILE is possible (set
#   exclude_binaries=False on EXE and drop COLLECT) but it self-extracts every launch to
#   %TEMP%\_MEIxxxx, is slower to start, and antivirus flags it more often. Prefer one-dir; wrap
#   the folder in an installer (Inno Setup) for distribution.

import os
import importlib.util

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# SPECPATH is injected by PyInstaller = the directory containing THIS spec (build_exe/).
# The flat package (app_py.py, plaque_stats.py, data files) is its parent.
BUILD_DIR = SPECPATH
PROJECT = os.path.dirname(SPECPATH)


def _proj(*parts):
    return os.path.join(PROJECT, *parts)


def _maybe(mods):
    """Keep only modules that are actually importable in this env (prunes not-installed ones
    like sniffio / wsproto / appdirs so PyInstaller doesn't warn or fail on them)."""
    out = []
    for m in mods:
        try:
            if importlib.util.find_spec(m) is not None:
                out.append(m)
        except (ImportError, ModuleNotFoundError, ValueError):
            pass
    return out


# ---------------------------------------------------------------------------
# DATA FILES
#   The app resolves example CSVs via  os.path.join(HERE, "example_data_wide.csv")  where
#   HERE = dirname(abspath(app_py.__file__)). When frozen, PyInstaller sets app_py.__file__ to
#   <bundle>/app_py.py, so we drop these files at the archive ROOT ('.') to match. Same reason
#   plaque_stats.make_example() (dirname(__file__)) then writes into the bundle root.
# ---------------------------------------------------------------------------
datas = []
for fn in ("app_py.py", "plaque_stats.py", "plaque_stats_launch.py",
           "TEMPLATE.csv", "example_data_wide.csv", "example_data_long.csv",
           "app.R", "README.md"):
    src = _proj(fn)
    if os.path.exists(src):
        datas.append((src, "."))

# Shiny + htmltools static assets: www/ (py-shiny js, shared bootstrap/sass/fonts/datepicker)
# and htmltools lib/ (react etc). These are served to the browser -- the app is blank without them.
# shinychat ships www/attachment-types.json which shiny.ui._chat LOADS AT IMPORT TIME -- without it
# the frozen app crashes on `from shiny import ...` (FileNotFoundError). Bundle its data too.
datas += collect_data_files("shiny")
datas += collect_data_files("htmltools")
datas += collect_data_files("shinychat")
# matplotlib mpl-data (matplotlibrc + fonts) needed by the Agg/SVG/PDF backends.
# (PyInstaller's built-in matplotlib hook also adds this; duplicate (src,dest) pairs are deduped.)
datas += collect_data_files("matplotlib", subdir="mpl-data")


# ---------------------------------------------------------------------------
# HIDDEN IMPORTS
#   The uvicorn/starlette/shiny stack loads many submodules dynamically (loop + protocol
#   auto-selectors, lifespan handlers, websocket impls, shiny render/ui/reactive, markdown deps).
#   collect_submodules() sweeps whole packages; the explicit _maybe() list nails the specific
#   dynamic entry points and app modules, pruning anything not installed.
# ---------------------------------------------------------------------------
hiddenimports = []
for pkg in ("uvicorn", "starlette", "websockets", "shiny", "shinychat", "htmltools", "anyio"):
    hiddenimports += collect_submodules(pkg)

hiddenimports += _maybe([
    # uvicorn dynamic loop / protocol / lifespan selectors (the classic frozen-uvicorn misses)
    "uvicorn.logging",
    "uvicorn.loops.auto", "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto", "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto", "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan.on", "uvicorn.lifespan.off",
    # ASGI / async plumbing
    "websockets", "wsproto", "h11", "anyio", "sniffio", "asgiref",
    "starlette", "starlette.middleware",
    "click", "watchfiles",
    # shiny markdown / linkify dependency chain
    "linkify_it", "uc_micro", "markdown_it",
    # our own app modules (also forced via freeze_entry, listed here for belt-and-braces)
    "app_py", "plaque_stats", "plaque_stats_launch",
    "shiny", "shiny._main",
    # data / stats / io engine
    "openpyxl", "pandas", "scipy", "scipy.stats",
    # matplotlib export backends used by the download buttons
    "matplotlib.backends.backend_agg",
    "matplotlib.backends.backend_svg",
    "matplotlib.backends.backend_pdf",
])

# Drop test-only shiny submodules that require uninstalled extras (pytest / playwright),
# and de-duplicate.
_DROP_PREFIX = ("shiny.pytest", "shiny.playwright")
hiddenimports = sorted({h for h in hiddenimports if not h.startswith(_DROP_PREFIX)})


# ---------------------------------------------------------------------------
# ANALYSIS / BUILD (one-dir)
# ---------------------------------------------------------------------------
a = Analysis(
    [os.path.join(BUILD_DIR, "freeze_entry.py")],
    pathex=[PROJECT, BUILD_DIR],          # so app_py / plaque_stats / plaque_stats_launch import
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # GUI toolkits we never use (Agg-only) + test frameworks -> smaller, fewer false pulls
        "tkinter", "PyQt5", "PyQt6", "PySide2", "PySide6",
        "pytest", "playwright", "IPython", "notebook", "jupyter",
        # Deep-learning stack the plaqueapp env carries for the DESKTOP app's Precise
        # engine — the stats/violin app never touches it. Excluding it drops ~700 MB.
        "torch", "torchvision", "torchaudio", "sympy", "networkx",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,               # one-dir: binaries go into COLLECT, not the exe
    name="Plaque Stats App",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                           # UPX off: safer for antivirus + no upx dependency
    console=True,                        # console window prints the URL + server logs
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Plaque Stats App",
)
