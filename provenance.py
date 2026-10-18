"""Run provenance for the size tools -- `run_metadata.json` beside the CSVs.

Before v1.1.0 a `data-green-*.csv` recorded only measurements: nothing about which
engine produced them (`--published` / `--upstream-exact` / `--sensitive` / `--small`
/ `--watershed`), the `-p` dish size, the resulting mm/px, or the toolkit version.
You could not tell from a CSV which code made it. `plaque_turbidity.py` already got
this right with its own `run_metadata.json`; this module generalises that pattern so
the size CLI and the batch runner write the same thing. See AUDIT-2026-09.md (PT-9).

Deliberately additive: no existing measurement column changes, so every downstream
consumer keeps working and no Published-mode number moves.
"""
import datetime
import hashlib
import json
import os
import platform
import sys
import uuid

try:
    from _version import __version__ as TOOLKIT_VERSION
except Exception:                       # pragma: no cover - standalone installs
    TOOLKIT_VERSION = "0.0.0+unknown"

METADATA_FILENAME = "run_metadata.json"
MAX_PREVIOUS_RUNS = 20


def engine_name(published=False, upstream_exact=False, sensitive=False, precise=False):
    """The user-facing engine label, matching README.md's four-engine table."""
    if precise:
        return "Precise"
    if upstream_exact:
        return "Published (--upstream-exact)"
    if published:
        return "Published"
    if sensitive:
        return "Sensitive"
    return "Current"


def library_versions():
    out = {}
    for mod, key in (("cv2", "opencv"), ("numpy", "numpy"), ("pandas", "pandas"),
                     ("PIL", "pillow"), ("imutils", "imutils")):
        try:
            m = __import__(mod)
            out[key] = getattr(m, "__version__", "?")
        except Exception:
            out[key] = "not installed"
    return out


def file_digest(path, nbytes=16):
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()[:nbytes]
    except Exception:
        return ""


def build_metadata(tool, engine, settings, images=None, extra=None):
    """Assemble the provenance record. `images` is a list of per-image dicts."""
    meta = {
        "tool": tool,
        "toolkit_version": TOOLKIT_VERSION,
        "engine": engine,
        "settings": dict(settings or {}),
        "timestamp_utc": datetime.datetime.utcnow().isoformat() + "Z",
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "library_versions": library_versions(),
        "images": list(images or []),
    }
    if extra:
        meta.update(extra)
    meta.setdefault("run_id", uuid.uuid4().hex[:12])
    return meta


def write_metadata(out_dir, tool, engine, settings, images=None, extra=None):
    """Write `run_metadata.json` into `out_dir`. Never raises -- provenance must not
    be able to destroy a measurement run."""
    try:
        os.makedirs(out_dir, exist_ok=True)
        meta = build_metadata(tool, engine, settings, images, extra)
        path = os.path.join(out_dir, METADATA_FILENAME)
        # Several runs often share one output folder (a Current batch, then a single
        # --published plate). Overwriting meant the earlier CSVs were then described by
        # the wrong engine (AUDIT-2026-10.md, PT-25). Keep earlier records under
        # `previous_runs`; a run that re-flushes its own record (same run_id) replaces it.
        try:
            with open(path) as f:
                old = json.load(f)
        except Exception:
            old = None
        if isinstance(old, dict):
            prev = old.pop("previous_runs", []) or []
            if old.get("run_id") != meta.get("run_id"):
                prev.insert(0, old)
            meta["previous_runs"] = prev[:MAX_PREVIOUS_RUNS]
        with open(path, "w") as f:
            json.dump(meta, f, indent=2, default=str)
        return path
    except Exception as exc:            # pragma: no cover - disk/permission problems
        print("  (could not write %s: %s)" % (METADATA_FILENAME, exc))
        return None
