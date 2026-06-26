"""Thin adapter — the ONLY module that imports the validated engine.

The engine uses process-global flags (small_plaques / use_published / watershed_enabled).
Every engine call funnels through here under a lock so the flags are set atomically and the
GUI never touches the engine directly.
"""
import os
import sys
import threading

import numpy as np

import plaque_size_tool as pst
import plaque_gui as pgui

_LOCK = threading.Lock()


def numpy_version():
    return np.__version__


def resource_path(name):
    """Locate a bundled resource both from source and inside a PyInstaller bundle."""
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, "app", "resources", name)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", name)


def read_image(path):
    return pst.read_image_bgr(path)


def detect_single(path, plate_mm=None, small=False, watershed=False, published=False, sensitive=False):
    """Run the validated detection on one image; return a results dict (no Qt types).
    sensitive=True lowers the size gates to catch tiny plaques (forced off under published)."""
    with _LOCK:
        pst.use_published = bool(published)
        pst.watershed_enabled = bool(watershed) and not bool(published)
        plate_size = str(plate_mm) if plate_mm else None
        (display_rgb, orig_bgr, proc_gray, plaques,
         ppm, candidates, lawn_gray, plate) = pgui.run_detection(
             path, plate_size, bool(small), bool(sensitive))
    return {
        "display_rgb": display_rgb,
        "orig_bgr": orig_bgr,
        "proc_gray": proc_gray,
        "plaques": plaques,
        "pxl_per_mm": ppm,
        "candidates": candidates,
        "lawn_gray": lawn_gray,
        "plate": plate,
        "n_plaques": len(plaques),
    }


def measure_table(plaques, orig_bgr, ppm, lawn_gray):
    """Per-plaque DataFrame mirroring what save_results writes, but WITHOUT writing files
    (for live display of the editable plaque set)."""
    import cv2
    import pandas as pd
    gray = cv2.cvtColor(orig_bgr, cv2.COLOR_BGR2GRAY)
    means = [pst.mean_gray_in_mask(gray, pgui._plaque_mask(gray.shape, p)) for p in plaques]
    lg = lawn_gray if lawn_gray is not None else pst.estimate_lawn_gray(gray)
    turb = pst.turbidity_indices(means, lg)
    rows = []
    for i, (p, mg, tb) in enumerate(zip(plaques, means, turb), start=1):
        dia_pxl, area_mm2, dia_mm = pgui.measure(p["area_pxl"], ppm)
        rows.append({"INDEX": i, "AREA_PXL": round(p["area_pxl"], 2),
                     "DIAMETER_PXL": round(dia_pxl, 2), "AREA_MM2": round(area_mm2, 2),
                     "DIAMETER_MM": round(dia_mm, 2), "MEAN_GRAY": round(mg, 2),
                     "TURBIDITY_REL": (round(tb, 3) if tb == tb else ""), "SOURCE": p["source"]})
    return pd.DataFrame(rows, columns=["INDEX", "AREA_PXL", "DIAMETER_PXL", "AREA_MM2",
                                       "DIAMETER_MM", "MEAN_GRAY", "TURBIDITY_REL", "SOURCE"])


def save_single(plaques, orig_bgr, image_path, out_dir, ppm, lawn_gray):
    return pgui.save_results(plaques, orig_bgr, image_path, out_dir, ppm, lawn_gray)


class PreciseUnavailable(RuntimeError):
    """Raised when the Precise (PST+PlaqSeg) pipeline cannot run on this machine
    (e.g. the plaqseg conda env or the YOLO weights are missing). Carries a friendly
    message so the GUI can show it without crashing."""


def _project_root():
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _torch_inprocess_available():
    """True iff torch + ultralytics import in THIS interpreter (the unified/frozen env),
    so Precise can run in-process with no conda subprocesses. Cheap-ish (imports torch),
    so cache the result."""
    global _TORCH_INPROC
    try:
        return _TORCH_INPROC
    except NameError:
        pass
    try:
        import torch        # noqa: F401
        import ultralytics  # noqa: F401
        _TORCH_INPROC = True
    except Exception:
        _TORCH_INPROC = False
    return _TORCH_INPROC


def precise_available():
    """Best-effort check that the Precise pipeline *could* run here.
    Returns (ok: bool, reason: str). Cheap — checks files/dirs + import availability,
    never launches a (heavy) subprocess.

    Two ways Precise can run:
      1. IN-PROCESS — torch + ultralytics importable in the current interpreter (the
         unified 'plaqueapp' env or the frozen self-contained app). No conda needed.
      2. TWO-ENV SUBPROCESS — a separate 'plaqseg' conda env, located portably via
         app.env_paths.plaqseg_python() (the run-from-source path on dev machines)."""
    root = _project_root()
    weights = os.path.join(root, "_plaqseg", "models", "small.pt")
    if not os.path.exists(weights):
        return False, "the PlaqSeg model weights (_plaqseg/models/small.pt) were not found."

    # Path 1: in-process torch (unified env / frozen app).
    if _torch_inprocess_available():
        return True, ""

    # Path 2: two-env subprocess fallback (run-from-source on a machine with both envs).
    runner = os.path.join(root, "precise", "run_precise.py")
    if not os.path.exists(runner):
        return False, ("precise/run_precise.py is not bundled and torch/ultralytics are "
                       "not importable in this interpreter.")
    try:
        from app.env_paths import plaqseg_python
    except Exception:  # pragma: no cover - app pkg always importable here
        from env_paths import plaqseg_python
    plaqseg_py = plaqseg_python()
    if not plaqseg_py or not os.path.exists(plaqseg_py):
        return False, ("the PlaqSeg environment was not found. Precise needs either "
                       "torch + ultralytics in this Python, or a second conda env "
                       "('plaqseg') with PyTorch + ultralytics. Set the PLAQSEG_PY "
                       "environment variable to point at its python if it lives in a "
                       "non-standard location.")
    return True, ""


def detect_precise(path, plate_mm=None, out_dir=None, timeout=900, progress=None):
    """Run the Precise (PST + PlaqSeg) two-env pipeline on one image and return a results
    dict compatible with the table/summary code. Slow (CPU heavy) — call on a worker thread.

    Raises PreciseUnavailable with a friendly message if the env/model/runner is missing or
    the subprocess fails. ``progress`` is an optional callable(str) for status lines."""
    import subprocess
    import json
    import glob
    import pandas as pd

    ok, reason = precise_available()
    if not ok:
        raise PreciseUnavailable(
            "The Precise engine is not available: " + reason +
            "\n\nUse Published, Current, or Sensitive mode instead.")

    root = _project_root()
    runner = os.path.join(root, "precise", "run_precise.py")
    tag = os.path.splitext(os.path.basename(path))[0]
    if out_dir is None:
        out_dir = os.path.join(os.path.dirname(path), "out_precise")
    os.makedirs(out_dir, exist_ok=True)

    # Geometry/calibration + the original BGR come from the validated engine (fast, plaque env)
    # so the table / overlay / scale bar have what they need regardless of the precise CSV.
    base = detect_single(path, plate_mm=plate_mm, small=True)

    # ---- IN-PROCESS path (unified 'plaqueapp' env or frozen self-contained app) -------- #
    # If torch + ultralytics import here, run the whole Precise pipeline in THIS process —
    # no conda envs, no subprocess. This is what makes the self-contained installer work.
    if _torch_inprocess_available():
        if progress:
            progress("Running Precise pipeline in-process (PST + PlaqSeg + classifier)…")
        try:
            from precise.pipeline import run_inprocess
            summ = run_inprocess(path, plate_mm=(plate_mm or 100), out_dir=out_dir,
                                 clf=True, blob=False, tag=tag)
        except Exception as e:  # surface a friendly message; keep the GUI alive
            raise PreciseUnavailable(
                "The in-process Precise pipeline failed:\n\n%s\n\n"
                "Published / Current / Sensitive modes still work." % e)
        csv_path = summ.get("csv") or os.path.join(out_dir, "precise_%s.csv" % tag)
        pdf = pd.read_csv(csv_path)
        overlay = summ.get("overlay")
        result = dict(base)
        result["precise"] = True
        result["precise_df"] = pdf
        result["precise_summary"] = summ
        result["precise_overlay"] = overlay
        result["precise_csv"] = csv_path
        result["n_plaques"] = int(summ.get("n_final", len(pdf)))
        return result

    # ---- TWO-ENV SUBPROCESS fallback (run-from-source with separate plaque/plaqseg envs) #
    # run_precise.py is launched with the running interpreter, which from source is the
    # 'plaque' env python (a real interpreter that can run the .py and import plaque_gui).
    cmd = [sys.executable, runner, "--image", path, "--out", out_dir,
           "--tag", tag, "--plate-mm", str(plate_mm or 100)]
    if progress:
        progress("Running Precise pipeline (PST + PlaqSeg)… this can take a minute.")
    try:
        proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as e:
        raise PreciseUnavailable("Could not launch the Precise runner: %s" % e)
    except subprocess.TimeoutExpired:
        raise PreciseUnavailable("The Precise pipeline timed out (>%ds)." % timeout)

    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        msg = "\n".join(tail[-8:]) if tail else "unknown error"
        raise PreciseUnavailable(
            "The Precise pipeline failed to complete.\n\n" + msg +
            "\n\nThis usually means the PlaqSeg env or model is misconfigured. "
            "Published / Current / Sensitive modes still work.")

    csv_path = os.path.join(out_dir, "precise_%s.csv" % tag)
    if not os.path.exists(csv_path):
        raise PreciseUnavailable("The Precise pipeline produced no output CSV.")

    pdf = pd.read_csv(csv_path)
    summ = {}
    sum_path = os.path.join(out_dir, "summary_%s.json" % tag)
    if os.path.exists(sum_path):
        try:
            summ = json.load(open(sum_path))
        except Exception:
            summ = {}
    overlays = glob.glob(os.path.join(out_dir, "precise_overlay_%s.jpg" % tag))
    overlay = overlays[0] if overlays else None

    result = dict(base)
    result["precise"] = True
    result["precise_df"] = pdf
    result["precise_summary"] = summ
    result["precise_overlay"] = overlay
    result["precise_csv"] = csv_path
    result["n_plaques"] = int(summ.get("n_final", len(pdf)))
    return result


def run_compare(directory, plate_mm=None, small=False, blank=None, flat=None, dark=None,
                core=1.0, group_by_prefix=False, dilution=None, volume_ul=None,
                watershed=False, published=False, out_dir="out_turbidity"):
    """Batch cross-phage turbidity. Writes per_phage.csv/qc.csv/figures into out_dir and
    returns the plaque-level DataFrame + out_dir."""
    import plaque_turbidity as ptb
    with _LOCK:
        pst.use_published = bool(published)
        pst.watershed_enabled = bool(watershed) and not bool(published)
        df = ptb.run_batch(
            directory, str(plate_mm) if plate_mm else None, bool(small),
            blank or None, flat or None, out_dir,
            group_by_prefix=bool(group_by_prefix), dark_path=dark or None,
            core_frac=float(core), make_overlays=True,
            dilution=dilution, volume_ul=volume_ul, make_plots=True)
    return {"df": df, "out_dir": out_dir}


def smoke(extra=None):
    """Headless self-test used as the M0 packaging acceptance gate (works in the frozen exe)."""
    import cv2
    print("python  :", sys.version.split()[0])
    print("numpy   :", numpy_version())
    print("opencv  :", cv2.__version__)
    try:
        import pillow_heif  # noqa: F401
        print("heif    : available")
    except Exception as e:
        print("heif    : MISSING ->", e)

    ok = numpy_version().startswith("1.")          # the numpy<2 hard pin
    targets = [extra] if extra else [resource_path("sample.tif"), resource_path("sample.heic")]
    for p in targets:
        try:
            r = detect_single(p, plate_mm=100)
            print(f"  {os.path.basename(p)}: {r['n_plaques']} plaques  (cal={r['pxl_per_mm']})")
            ok = ok and r["n_plaques"] > 0
        except Exception as e:
            print(f"  {os.path.basename(p)}: ERROR {e}")
            ok = False
    print("SMOKE", "OK" if ok else "FAIL")
    return 0 if ok else 1
