"""Plaque Toolkit — unified desktop app (front-end over the validated engine modules)."""
import os as _os
import sys as _sys

# The repo root holds _version.py and the engine modules (plaque_size_tool, ...).
# Make sure it is importable even when only the `app` package directory is on sys.path.
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)

try:                                    # one source of truth: repo-root _version.py
    from _version import __version__
except Exception:                       # pragma: no cover - frozen/partial installs
    __version__ = "0.0.0+unknown"
