#!/usr/bin/env bash
# ====================================================================
#  build_macos.sh - build the macOS "Plaque Toolkit.app" bundle.
#
#  MUST be run ON a Mac: PyInstaller cannot cross-compile, so a Windows or
#  Linux machine cannot produce a .app. Run this on macOS with the 'plaque'
#  conda env created (see environment.yml / setup.command).
#
#  What it does:
#    1. (re)generates app/resources/icon.icns from icon.png using macOS sips+iconutil
#    2. runs PyInstaller with build/plaque_app_macos.spec  -> dist/Plaque Toolkit.app
#    3. smoke-tests the frozen app headlessly
#    4. optionally builds a .dmg (create-dmg if installed, else hdiutil)
#
#  Like the Windows build, this does NOT bundle torch/ultralytics; the optional
#  "Precise" engine runs via a local 'plaqseg' conda env on the user's Mac
#  (environment-precise.yml). Tell users to create that env if they need Precise.
#
#  Usage:
#    ./build_macos.sh              # build the .app (+ .dmg if a dmg tool exists)
#    ./build_macos.sh --no-dmg     # skip the .dmg
# ====================================================================
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "ERROR: build_macos.sh must run on macOS (PyInstaller cannot cross-compile)." >&2
  exit 1
fi

MAKE_DMG=1
[[ "${1:-}" == "--no-dmg" ]] && MAKE_DMG=0

# Pick the runner for the 'plaque' env: prefer conda/mamba run, else PLAQUE_PY.
RUN=()
if [[ -n "${PLAQUE_PY:-}" && -x "${PLAQUE_PY}" ]]; then
  RUN=("$PLAQUE_PY" -m)
else
  for c in conda mamba micromamba; do
    if command -v "$c" >/dev/null 2>&1; then RUN=("$c" run -n plaque); break; fi
  done
fi
if [[ ${#RUN[@]} -eq 0 ]]; then
  echo "ERROR: no conda/mamba found and PLAQUE_PY not set. Create the env first:" >&2
  echo "  conda env create -f environment.yml" >&2
  exit 1
fi
echo "Using runner: ${RUN[*]}"

# --- 1. icon.icns from icon.png (best-effort; spec falls back to no icon) ---
PNG="app/resources/icon.png"
ICNS="app/resources/icon.icns"
if [[ -f "$PNG" ]] && command -v sips >/dev/null 2>&1 && command -v iconutil >/dev/null 2>&1; then
  echo "Generating $ICNS from $PNG ..."
  ICONSET="$(mktemp -d)/icon.iconset"; mkdir -p "$ICONSET"
  for s in 16 32 64 128 256 512; do
    sips -z $s $s     "$PNG" --out "$ICONSET/icon_${s}x${s}.png"     >/dev/null
    sips -z $((s*2)) $((s*2)) "$PNG" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
  done
  iconutil -c icns "$ICONSET" -o "$ICNS" || echo "  (iconutil failed; building without a custom icon)"
else
  echo "  (skipping icns generation; sips/iconutil or icon.png not available)"
fi

# --- 2. PyInstaller build ---------------------------------------------------
echo "Building the .app with PyInstaller ..."
"${RUN[@]}" pyinstaller --noconfirm build/plaque_app_macos.spec

APP="dist/Plaque Toolkit.app"
if [[ ! -d "$APP" ]]; then
  echo "ERROR: build did not produce $APP" >&2
  exit 1
fi
echo "Built: $APP"

# --- 3. smoke-test the frozen app (headless) --------------------------------
BIN="$APP/Contents/MacOS/Plaque Toolkit"
if [[ -x "$BIN" ]]; then
  echo "Smoke-testing the frozen app ..."
  if "$BIN" --smoke; then echo "SMOKE OK"; else echo "WARNING: frozen smoke test failed" >&2; fi
fi

# --- 4. .dmg (optional) -----------------------------------------------------
if [[ "$MAKE_DMG" -eq 1 ]]; then
  DMG="dist/Plaque Toolkit.dmg"
  rm -f "$DMG"
  if command -v create-dmg >/dev/null 2>&1; then
    echo "Building DMG with create-dmg ..."
    create-dmg --volname "Plaque Toolkit" --app-drop-link 450 120 \
      "$DMG" "$APP" || echo "  (create-dmg failed; app bundle is still usable)"
  else
    echo "Building DMG with hdiutil ..."
    STAGE="$(mktemp -d)"; cp -R "$APP" "$STAGE/"; ln -s /Applications "$STAGE/Applications" || true
    hdiutil create -volname "Plaque Toolkit" -srcfolder "$STAGE" -ov -format UDZO "$DMG" \
      || echo "  (hdiutil failed; app bundle is still usable)"
  fi
  [[ -f "$DMG" ]] && echo "DMG: $DMG"
fi

echo
echo "Done. Drag '$APP' to /Applications (or share the .dmg)."
echo "Note: for the Precise engine, the user must create a 'plaqseg' conda env on their Mac:"
echo "      conda env create -f environment-precise.yml"
