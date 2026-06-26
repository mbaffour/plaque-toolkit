"""Cross-platform discovery of the conda environment pythons the toolkit needs.

The app runs in the ``plaque`` conda env; the Precise pipeline additionally needs a
``plaqseg`` env (PyTorch + ultralytics). Historically those interpreter paths were
hard-coded to one Windows machine (``C:\\Users\\mbaff\\Miniconda3\\envs\\...``), which made
the app non-portable. This module derives them at runtime so the same code runs on
Windows, macOS and Linux.

Resolution order for ``find_env_python(name)`` (first hit wins):
  1. Explicit override env var  ``PLAQUE_PY`` / ``PLAQSEG_PY``  (any env name -> ``<NAME>_PY``).
  2. A sibling config file ``env_paths.json`` next to the project root (optional), e.g.
        {"plaqseg": "/opt/miniconda3/envs/plaqseg/bin/python"}
  3. The conda base derived from the RUNNING interpreter (``sys.executable``):
        <base>/envs/<name>/python.exe          (Windows)
        <base>/envs/<name>/bin/python          (macOS / Linux)
     The base is found whether we are already inside an env (.../envs/<x>/python) or
     in the conda root, and also honours $CONDA_PREFIX / $CONDA_EXE / $CONDACONDA.
  4. ``conda`` on PATH:  ``conda run -n <name> python`` is verified to work and that
     interpreter path is returned.

Returns an absolute path string if a usable interpreter is found, else ``None``.
The helper is import-light (no torch/cv2) so it is cheap to call from a UI thread.
"""
import json
import os
import shutil
import subprocess
import sys


def _is_windows():
    return os.name == "nt"


def _env_python_in(base, name):
    """Return the interpreter path for env ``name`` under conda ``base`` if it exists."""
    if _is_windows():
        cand = os.path.join(base, "envs", name, "python.exe")
    else:
        cand = os.path.join(base, "envs", name, "bin", "python")
    return cand if os.path.exists(cand) else None


def _python_in_prefix(prefix, name=None):
    """Given a conda PREFIX that is itself the target env (e.g. CONDA_PREFIX pointing at
    .../envs/plaqseg), return its interpreter if it matches ``name`` (or any if name is None)."""
    if name is not None and os.path.basename(os.path.normpath(prefix)) != name:
        return None
    if _is_windows():
        cand = os.path.join(prefix, "python.exe")
    else:
        cand = os.path.join(prefix, "bin", "python")
    return cand if os.path.exists(cand) else None


def conda_base_dirs():
    """Yield plausible conda *base* directories, most-likely first, derived portably.

    Covers: the running interpreter's location (whether in base or in an env), the
    standard CONDA_* env vars, and a handful of common install locations. Only existing
    directories are yielded; callers should still verify the env under them exists.
    """
    seen = []

    def add(d):
        if d:
            d = os.path.normpath(d)
            if d not in seen and os.path.isdir(d):
                seen.append(d)

    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    # If sys.executable is .../envs/<x>/python(.exe) -> base is two levels up from
    #   <x>/python.exe (win)  or three from <x>/bin/python (posix).
    # If it is the base interpreter -> base is its own dir (win) or one up (posix).
    norm = os.path.normpath(exe_dir)
    parts = norm.split(os.sep)
    if "envs" in parts:
        i = len(parts) - 1 - parts[::-1].index("envs")   # last "envs"
        add(os.sep.join(parts[:i]))                      # parent of envs == base
    # base interpreter cases
    if _is_windows():
        add(exe_dir)                                     # base\python.exe
    else:
        add(os.path.dirname(exe_dir))                    # base/bin/python -> base

    # CONDA_* hints
    cp = os.environ.get("CONDA_PREFIX")
    if cp:
        cpn = os.path.normpath(cp)
        cparts = cpn.split(os.sep)
        if "envs" in cparts:
            i = len(cparts) - 1 - cparts[::-1].index("envs")
            add(os.sep.join(cparts[:i]))
        else:
            add(cpn)                                     # CONDA_PREFIX is the base
    ce = os.environ.get("CONDA_EXE")                     # .../condabin/conda(.exe) or .../bin/conda
    if ce:
        add(os.path.dirname(os.path.dirname(ce)))

    # Common install roots as a last resort.
    home = os.path.expanduser("~")
    for d in ("miniconda3", "anaconda3", "miniforge3", "mambaforge"):
        add(os.path.join(home, d))
    if _is_windows():
        for d in ("Miniconda3", "Anaconda3", "Miniforge3"):
            add(os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), d))
    else:
        for d in ("/opt/miniconda3", "/opt/anaconda3", "/opt/conda",
                  "/usr/local/miniconda3", "/usr/local/anaconda3"):
            add(d)
    for d in seen:
        yield d


def _config_override(name):
    """Look for an optional env_paths.json next to the project root mapping name->path."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for cfg in (os.path.join(root, "env_paths.json"),
                os.path.join(os.path.expanduser("~"), ".plaque_toolkit_envs.json")):
        try:
            if os.path.exists(cfg):
                with open(cfg) as f:
                    data = json.load(f)
                p = data.get(name)
                if p and os.path.exists(p):
                    return p
        except Exception:
            pass
    return None


def _conda_run_python(name):
    """Last resort: ask `conda run -n <name>` for its interpreter path and verify it."""
    conda = shutil.which("conda") or shutil.which("mamba")
    if not conda:
        return None
    try:
        out = subprocess.run(
            [conda, "run", "-n", name, "python", "-c",
             "import sys; print(sys.executable)"],
            capture_output=True, text=True, timeout=60)
        if out.returncode == 0:
            p = (out.stdout or "").strip().splitlines()[-1].strip()
            if p and os.path.exists(p):
                return p
    except Exception:
        pass
    return None


def find_env_python(name):
    """Return an absolute path to the python interpreter of conda env ``name``, or None.

    Cross-platform (Windows ``envs/<name>/python.exe`` vs posix ``envs/<name>/bin/python``).
    Honours the ``<NAME>_PY`` env var override (e.g. PLAQSEG_PY), an optional
    ``env_paths.json`` config, the running interpreter's conda base, and finally
    ``conda run``. Never raises; cheap enough for the UI thread."""
    # 1. explicit env-var override, e.g. PLAQSEG_PY / PLAQUE_PY
    override = os.environ.get("%s_PY" % name.upper())
    if override and os.path.exists(override):
        return override

    # 2. optional config file
    cfg = _config_override(name)
    if cfg:
        return cfg

    # 2b. if we are ALREADY running inside that env, just use ourselves.
    self_prefix = os.environ.get("CONDA_PREFIX")
    if self_prefix:
        p = _python_in_prefix(self_prefix, name)
        if p:
            return p
    # also handle being launched as .../envs/<name>/python directly
    me = os.path.normpath(os.path.dirname(os.path.abspath(sys.executable)))
    if os.path.basename(me) == name or (
            not _is_windows() and os.path.basename(os.path.dirname(me)) == name):
        return sys.executable

    # 3. derive from conda base(s)
    for base in conda_base_dirs():
        p = _env_python_in(base, name)
        if p:
            return p

    # 4. conda run fallback
    return _conda_run_python(name)


def plaque_python():
    """Interpreter for the validated 'plaque' env. Falls back to the running interpreter
    (the app itself normally runs in that env)."""
    return find_env_python("plaque") or sys.executable


def plaqseg_python():
    """Interpreter for the 'plaqseg' (PyTorch + ultralytics) env, or None if not present."""
    return find_env_python("plaqseg")


if __name__ == "__main__":
    # `python app/env_paths.py` -> quick diagnostic of what was resolved.
    print("platform   :", sys.platform, "| os.name:", os.name)
    print("sys.exec   :", sys.executable)
    print("plaque  py :", plaque_python())
    print("plaqseg py :", plaqseg_python())
    print("bases      :", list(conda_base_dirs()))
