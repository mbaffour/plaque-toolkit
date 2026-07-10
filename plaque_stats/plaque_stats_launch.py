#!/usr/bin/env python3
"""plaque_stats_launch.py — one-command launcher for the Plaque Stats browser app.

Starts the Shiny for Python app (app_py.py) as a local web server and opens the
browser. One module serves three consumers:
  * pip console script:   plaque-stats-app  [--port N] [--host H] [--no-browser]
  * folder launcher:      python -m plaque_stats_launch
  * frozen exe:           build_exe/freeze_entry.py imports this and calls main()

It is purely additive — plaque_stats.py and app_py.py are untouched, so
`import plaque_stats`, `python plaque_stats.py …`, and `shiny run app_py.py`
all keep working exactly as before.

Environment overrides (used by automated verification / power users; CLI flags win):
    PLAQUE_PORT=8765        force the server port (else first free at/after 8000)
    PLAQUE_HOST=127.0.0.1   bind host
    PLAQUE_NO_BROWSER=1     do not open a web browser (headless)
"""
from __future__ import annotations

import argparse
import os
import socket
import sys
import tempfile
import threading
import time
import webbrowser

# Keep matplotlib headless before anything imports pyplot (app_py imports it).
os.environ.setdefault("MPLBACKEND", "Agg")

# Env var app_py.py reads to find example data this launcher may have generated
# somewhere other than next to the module (keeps the two modules decoupled).
EXAMPLE_DIR_ENV = "PLAQUE_STATS_EXAMPLE_DIR"


def _base_dir() -> str:
    """Directory this module lives in — or the unpack dir when frozen."""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
    return os.path.dirname(os.path.abspath(__file__))


def _dir_is_writable(d: str) -> bool:
    try:
        t = os.path.join(d, ".pst_write_test")
        with open(t, "w") as fh:
            fh.write("")
        os.remove(t)
        return True
    except Exception:  # noqa: BLE001
        return False


def _ensure_example_data() -> str:
    """Guarantee example_data_wide.csv exists somewhere app_py can read.

    Prefers the module's own dir (source / editable / frozen bundle already ship
    it). Otherwise regenerates it with plaque_stats.make_example() into the module
    dir if writable, else a stable temp dir, advertised via EXAMPLE_DIR_ENV.
    """
    import plaque_stats as ps

    base = _base_dir()
    if os.path.exists(os.path.join(base, "example_data_wide.csv")):
        os.environ.setdefault(EXAMPLE_DIR_ENV, base)
        return base

    if _dir_is_writable(base):
        try:
            ps.make_example(base)
            os.environ[EXAMPLE_DIR_ENV] = base
            return base
        except Exception:  # noqa: BLE001
            pass

    tmp = os.path.join(tempfile.gettempdir(), "plaque_stats_example")
    os.makedirs(tmp, exist_ok=True)
    if not os.path.exists(os.path.join(tmp, "example_data_wide.csv")):
        ps.make_example(tmp)
    os.environ[EXAMPLE_DIR_ENV] = tmp
    return tmp


def _probe_host(host: str) -> str:
    # For a wildcard bind, probe/connect on loopback.
    return "127.0.0.1" if host in ("0.0.0.0", "::") else host


def _port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((_probe_host(host), port))
            return True
        except OSError:
            return False


def _pick_port(host: str, start: int, tries: int = 20) -> int:
    for cand in range(start, start + tries):
        if _port_is_free(host, cand):
            return cand
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:  # let the OS choose
        s.bind((_probe_host(host), 0))
        return s.getsockname()[1]


def _open_when_ready(host: str, port: int, url: str) -> None:
    probe = _probe_host(host)
    for _ in range(60):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            if s.connect_ex((probe, port)) == 0:
                break
        time.sleep(0.5)
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001
        pass


def main(argv=None) -> int:
    env_port = os.environ.get("PLAQUE_PORT")
    env_host = os.environ.get("PLAQUE_HOST")
    env_nobrowser = os.environ.get("PLAQUE_NO_BROWSER") in ("1", "true", "True")

    p = argparse.ArgumentParser(
        prog="plaque-stats-app",
        description="Launch the Plaque Stats browser (Shiny) app.")
    p.add_argument("--port", type=int, default=None,
                   help="server port (default: PLAQUE_PORT env, else first free at/after 8000)")
    p.add_argument("--host", default=None,
                   help="bind host (default: PLAQUE_HOST env, else 127.0.0.1)")
    p.add_argument("--no-browser", dest="browser", action="store_false",
                   help="do not auto-open a web browser")
    p.set_defaults(browser=None)          # None => fall back to env / default
    ns = p.parse_args(argv)

    host = ns.host or env_host or "127.0.0.1"
    open_browser = ns.browser if ns.browser is not None else (not env_nobrowser)

    # port precedence: --port flag > PLAQUE_PORT env (both exact) > auto-advance from 8000
    forced = ns.port
    if forced is None and env_port:
        try:
            forced = int(env_port)
        except ValueError:
            forced = None
    port = forced if forced is not None else _pick_port(host, 8000)

    # Make sure "Load example data" will work from any install form.
    _ensure_example_data()

    # Import the app explicitly (so freezers bundle it) with a friendly hint if
    # the optional Shiny dependency is missing.
    try:
        import app_py
    except ModuleNotFoundError as e:
        if getattr(e, "name", "") == "shiny":
            sys.stderr.write(
                "The browser app needs Shiny. Install it with:\n"
                '    pip install "plaque-stats[app]"\n'
                "  (or:  pip install shiny openpyxl)\n")
            return 1
        raise
    import shiny

    url = "http://%s:%d" % (_probe_host(host), port)
    print("Plaque Stats App — serving at %s" % url)
    print("Keep this window open; press Ctrl+C (or close it) to stop the app.")

    if open_browser:
        threading.Thread(target=_open_when_ready, args=(host, port, url), daemon=True).start()

    # reload MUST stay False for a frozen build (no loose sources to watch, and
    # reload re-imports the app by "module:attr" string, which fails when frozen).
    shiny.run_app(app_py.app, host=host, port=port, reload=False, launch_browser=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
