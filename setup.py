"""Legacy setup.py shim. The real metadata lives in pyproject.toml; the version
lives in _version.py (one source of truth -- see AUDIT-2026-09.md, PT-13)."""
import os
import runpy

from setuptools import setup

_HERE = os.path.dirname(os.path.abspath(__file__))
__version__ = runpy.run_path(os.path.join(_HERE, "_version.py"))["__version__"]

with open(os.path.join(_HERE, "README.md"), "r") as fh:
    long_description = fh.read()

setup(name='plaque-toolkit',
      version=__version__,
      description='Bacteriophage plaque size & turbidity measurement toolkit '
                  '(built on the Plaque Size Tool, Trofimova & Jaschke 2021, Apache-2.0)',
      long_description=long_description,
      long_description_content_type='text/markdown',
      url='https://github.com/mbaffour/plaque-toolkit',
      author='Michael Baffour Awuah',
      # Our own source is Apache-2.0. NOTE: the *distributed repository as a whole*
      # (Full build: Ultralytics-derived Precise engine + CC BY-NC-SA 4.0 weights) is
      # AGPL-3.0-or-later -- see LICENSING.md and CITATION.cff.
      license='Apache-2.0',
      install_requires=['numpy<2', 'opencv-python', 'imutils', 'pandas', 'Pillow',
                        'matplotlib>=3.9'],
      extras_require={'heic': ['pillow-heif>=0.13'],
                      'excel': ['openpyxl>=3.0'],
                      'test': ['pytest>=7']},
      py_modules=['plaque_size_tool', 'plaque_turbidity', '_version'],
      zip_safe=False,
      keywords='bacteriophage phage virus viral plaque size turbidity')
