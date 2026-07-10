#!/usr/bin/env python3
"""freeze_entry.py -- PyInstaller entry point for the "Plaque Stats App" executable.

Everything the frozen app needs is imported at MODULE TOP LEVEL so PyInstaller's
static import graph follows it and bundles it. Do not move these imports inside
functions -- that hides them from the analyzer and breaks the frozen build.
"""
import os

# Headless matplotlib before ANY pyplot import (plaque_stats/app_py import pyplot).
os.environ.setdefault("MPLBACKEND", "Agg")
import matplotlib
matplotlib.use("Agg")

# --- explicit imports so PyInstaller bundles the whole app + engine ---
import plaque_stats          # noqa: F401  shared stats/plot engine (same code as the CLI)
import app_py                # noqa: F401  Shiny UI + server; defines app_py.app
import plaque_stats_launch   # the launcher: local server + browser


if __name__ == "__main__":
    raise SystemExit(plaque_stats_launch.main())
