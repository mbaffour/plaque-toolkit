"""PT-5: no launcher or script may hard-code the author's own machine.

22 files contained `C:\\Users\\mbaff\\...`. The worst of them were the top-level
drag-and-drop `.bat` launchers -- the README's "no app, no commands" onboarding
path for non-programmers -- whose only fallback was a bare `python`, which on a
typical Windows box is the Microsoft Store stub or a system Python without cv2.

Two categories are deliberately exempt and are listed explicitly, so adding a new
exemption is a visible decision:
  * app/env_paths.py -- its docstring *documents* the old hard-coding.
  * validation/ -- archived provenance records of where the ground-truth data was
    measured. Editing them would falsify the record.
"""
import os
import re

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PERSONAL = re.compile(r"[Cc]:[\\/]+Users[\\/]+mbaff\b")

ALLOWED = {
    os.path.join("app", "env_paths.py"),
    os.path.join("validation", "ground_truth", "labels_IMG_3907.json"),
    os.path.join("validation", "ground_truth", "labels_IMG_3912.json"),
    os.path.join("validation", "figures", "run_config_area.json"),
    os.path.join("validation", "figures", "run_config_diameter.json"),
    os.path.join("tests", "test_no_hardcoded_paths.py"),
}

SKIP_DIRS = {".git", "__pycache__", "build", "dist", "_plaqseg", "_research",
             "training_data", "Test_plates", "Manual_images", "plates"}
TEXT_EXTS = {".bat", ".ps1", ".sh", ".command", ".py", ".md", ".html", ".json",
             ".cff", ".yml", ".yaml", ".spec", ".txt", ".iss"}


def _text_files():
    for root, dirs, files in os.walk(REPO_ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if os.path.splitext(f)[1].lower() not in TEXT_EXTS:
                continue
            full = os.path.join(root, f)
            yield full, os.path.relpath(full, REPO_ROOT)


def test_no_personal_paths_outside_the_documented_exemptions():
    offenders = []
    for full, rel in _text_files():
        if rel in ALLOWED:
            continue
        try:
            text = open(full, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        if PERSONAL.search(text):
            offenders.append(rel)
    assert not offenders, "hard-coded personal path in: %s" % sorted(offenders)


def test_every_launcher_resolves_python_at_runtime():
    """A .bat that runs a Python script must go through a discovery chain, not a
    literal interpreter path. (plaque_stats/Run R App.bat drives Rscript, not
    Python, and only mentions Python in a message -- it is not in scope here.)"""
    for full, rel in _text_files():
        if not rel.endswith(".bat"):
            continue
        text = open(full, encoding="utf-8", errors="replace").read()
        if ".py" not in text:
            continue
        has_chain = ("find_python.bat" in text
                     or "conda run" in text
                     or "PLAQUE_PY" in text
                     or "envs\\" in text)
        assert has_chain, "%s runs Python with no discovery chain" % rel


def test_find_python_helper_exists_and_offers_the_documented_fallbacks():
    helper = os.path.join(REPO_ROOT, "find_python.bat")
    assert os.path.exists(helper)
    text = open(helper, encoding="utf-8").read()
    for expected in ("PLAQUE_PY", "conda run", "py -3", "python"):
        assert expected in text, expected


def test_top_level_launchers_call_the_helper():
    expected = [
        "Measure Plaques.bat", "Batch Plates (CSV per plate).bat",
        "Compare Turbidity.bat", "Edit Plaques (GUI).bat", "Add Scale Bar.bat",
        "Original Plaque Size Tool (1 plate).bat",
        "Original Plaque Size Tool (batch).bat",
        "Plaque Toolkit (app).bat", "Precise Detect (best engine).bat",
    ]
    for name in expected:
        path = os.path.join(REPO_ROOT, name)
        assert os.path.exists(path), name
        text = open(path, encoding="utf-8", errors="replace").read()
        assert "find_python.bat" in text, name
        assert "%PYCMD%" in text or "%PYWCMD%" in text, name
