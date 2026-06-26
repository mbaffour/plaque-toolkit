#!/usr/bin/env bash
# ====================================================================
#  Plaque Toolkit - launch the app from source on macOS.
#  Double-click in Finder (you may need to `chmod +x` it once, or right-click
#  > Open the first time to clear Gatekeeper). It activates the 'plaque' conda
#  env and runs plaque_app.py.
#
#  First-time make-executable (Terminal):  chmod +x "Plaque Toolkit.command"
# ====================================================================
set -e
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

run_app() { exec "$@" python plaque_app.py 2>/dev/null || exec "$@" python plaque_app.py; }

# 1. explicit override
if [ -n "${PLAQUE_PY:-}" ] && [ -x "$PLAQUE_PY" ]; then
  exec "$PLAQUE_PY" plaque_app.py
fi

# 2. common local conda env interpreters
for base in "$HOME/miniconda3" "$HOME/anaconda3" "$HOME/miniforge3" \
            "$HOME/mambaforge" "/opt/miniconda3" "/opt/anaconda3" "/opt/homebrew/Caskroom/miniforge/base"; do
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
echo "Create it first:   conda env create -f environment.yml"
echo "Or run ./setup.command"
read -r -p "Press Return to close..." _
exit 1
