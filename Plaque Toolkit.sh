#!/usr/bin/env bash
# ====================================================================
#  Plaque Toolkit - launch the app from source on Linux.
#  Run:  ./"Plaque Toolkit.sh"   (chmod +x once if needed)
#  Activates the 'plaque' conda env and runs plaque_app.py.
# ====================================================================
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

# 1. explicit override
if [ -n "${PLAQUE_PY:-}" ] && [ -x "$PLAQUE_PY" ]; then
  exec "$PLAQUE_PY" plaque_app.py
fi

# 2. common local conda env interpreters
for base in "$HOME/miniconda3" "$HOME/anaconda3" "$HOME/miniforge3" \
            "$HOME/mambaforge" "/opt/conda" "/opt/miniconda3"; do
  if [ -x "$base/envs/plaque/bin/python" ]; then
    exec "$base/envs/plaque/bin/python" plaque_app.py
  fi
done

# 3. conda / mamba run fallback
for c in conda mamba micromamba; do
  if command -v "$c" >/dev/null 2>&1; then
    exec "$c" run -n plaque python plaque_app.py
  fi
done

echo "Could not find the 'plaque' conda environment."
echo "Create it first:   conda env create -f environment.yml   (or ./setup.sh)"
exit 1
