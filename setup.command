#!/usr/bin/env bash
# Plaque Toolkit - one-time setup on macOS. Double-click in Finder (or run in Terminal).
# Creates the 'plaque' conda environment from environment.yml.
# Shared setup body: create the 'plaque' conda env from environment.yml.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

# Prefer mamba (fast), else conda, else micromamba.
TOOL=""
for c in mamba conda micromamba; do
  if command -v "$c" >/dev/null 2>&1; then TOOL="$c"; break; fi
done
if [ -z "$TOOL" ]; then
  echo "ERROR: no conda/mamba/micromamba on PATH."
  echo "Install Miniconda (https://docs.conda.io/en/latest/miniconda.html) or Miniforge first."
  exit 1
fi
echo "Using $TOOL to create the 'plaque' environment from environment.yml ..."

if "$TOOL" env list | grep -qE '(^|/)plaque[[:space:]]'; then
  echo "An env named 'plaque' already exists. Updating it ..."
  "$TOOL" env update -n plaque -f environment.yml --prune
else
  "$TOOL" env create -f environment.yml
fi

echo
echo "Done. Launch the app with:"
echo "   $TOOL run -n plaque python plaque_app.py"
echo "or double-click the 'Plaque Toolkit' launcher for your OS."
echo
echo "Optional: for the 'Precise' engine, also run:"
echo "   $TOOL env create -f environment-precise.yml"

read -r -p "Press Return to close..." _
