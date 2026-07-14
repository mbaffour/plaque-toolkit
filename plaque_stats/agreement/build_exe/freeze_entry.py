#!/usr/bin/env python3
"""freeze_entry.py -- PyInstaller entry point for the "Plaque Agreement App" executable.

Everything the frozen app needs is imported at MODULE TOP LEVEL so PyInstaller's static
import graph follows it and bundles it. Then start the Shiny app on a local port and open
the browser. Mirrors plaque_stats/build_exe/freeze_entry.py.
"""
import os
import socket
import sys
import threading
import time
import webbrowser

# Headless matplotlib before ANY pyplot import (agreement/app_py import pyplot).
os.environ.setdefault("MPLBACKEND", "Agg")
import matplotlib
matplotlib.use("Agg")

# --- explicit imports so PyInstaller bundles the whole app + engine ---
import agreement          # noqa: F401  the method-comparison engine (scipy / matplotlib / pandas)
import app_py             # noqa: F401  the Shiny UI + server; defines app_py.app


def _pick_port(start=8010, tries=30):
    for p in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:   # let the OS choose one
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _open_when_ready(url, port):
    for _ in range(60):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.4)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                break
        time.sleep(0.5)
    try:
        webbrowser.open(url)
    except Exception:
        pass


def main():
    env_port = os.environ.get("PLAQUE_PORT")
    port = int(env_port) if env_port else _pick_port(8010)
    # make sure "Load example data" works even from a read-only install location
    try:
        base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
        exp = os.path.join(base, "example_agreement.csv")
        if not os.path.exists(exp):
            agreement.make_example(exp)
    except Exception:
        pass
    import shiny
    url = "http://127.0.0.1:%d" % port
    print("Plaque Agreement App -- serving at %s" % url)
    print("Keep this window open; press Ctrl+C (or close it) to stop the app.")
    if os.environ.get("PLAQUE_NO_BROWSER") not in ("1", "true", "True"):
        threading.Thread(target=_open_when_ready, args=(url, port), daemon=True).start()
    # reload MUST stay False for a frozen build.
    shiny.run_app(app_py.app, host="127.0.0.1", port=port, reload=False, launch_browser=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
