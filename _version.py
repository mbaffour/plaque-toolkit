"""Single source of truth for the Plaque Toolkit version.

Every other place that reports a version (``setup.py``/``pyproject.toml``,
``app/__init__.py``, ``plaque_size_tool``, ``plaque_turbidity``, the provenance
records written next to every CSV) imports this module, so a release only ever
needs one edit here plus the two machine-readable citation files that cannot
import Python (``CITATION.cff`` and ``.zenodo.json``).

Keep it dependency-free and import-light: it is imported by the engine modules
and by the frozen app at start-up.
"""

__version__ = "1.1.0"
