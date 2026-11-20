"""Every repo-root module the two CLIs and the app engine import must be packaged.

`pyproject.toml` lists the top-level modules by hand (`py-modules`). A module that is imported
but not listed works from a checkout and fails after `pip install` (AUDIT-2026-10 PT-39 was
`provenance`; click-through 2026-11 added `plaque_qc` for `--qc` and `plaque_scales` for
`--multiscale`). This walks the imports, including the ones inside functions.
"""
import ast
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENTRY = ["plaque_size_tool", "plaque_turbidity", "plaque_gui", "summarize_plates"]


def _root_imports(name, seen):
    path = os.path.join(ROOT, name + ".py")
    if name in seen or not os.path.isfile(path):
        return
    seen.add(name)
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    for node in ast.walk(tree):
        mods = []
        if isinstance(node, ast.Import):
            mods = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            mods = [node.module.split(".")[0]]
        for m in mods:
            _root_imports(m, seen)


def test_every_imported_root_module_is_in_py_modules():
    with open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8") as fh:
        text = fh.read()
    block = re.search(r"py-modules\s*=\s*\[(.*?)\]", text, re.S).group(1)
    listed = set(re.findall(r'"([^"]+)"', block))
    needed = set()
    for e in ENTRY:
        _root_imports(e, needed)
    missing = sorted(needed - listed)
    assert not missing, "imported by the CLIs but not in pyproject py-modules: %s" % missing
