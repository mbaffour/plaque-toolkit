# build_app.ps1 -- freeze the Plaque Stats Shiny app into a standalone Windows folder.
#
#   Run:  powershell -ExecutionPolicy Bypass -File "build_app.ps1"
#
# Produces:  dist\Plaque Stats App\Plaque Stats App.exe  (ship the whole "Plaque Stats App" folder)

$ErrorActionPreference = "Stop"

# Always build from this script's own directory (build_exe/) so dist/ + build/ land here and
# the spec's SPECPATH-relative paths resolve.
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Here

# Resolve the interpreter portably (PT-5: no hard-coded personal paths).
# Override with $env:PLAQUE_PY, else look for the plaqueapp conda env in the usual
# places, else fall back to the py launcher / python on PATH.
$Py = $null
if ($env:PLAQUE_PY -and (Test-Path $env:PLAQUE_PY)) { $Py = $env:PLAQUE_PY }
if (-not $Py) {
    foreach ($base in @("$env:USERPROFILE\Miniconda3", "$env:USERPROFILE\Anaconda3",
                        "$env:USERPROFILE\miniforge3", "$env:USERPROFILE\mambaforge",
                        "$env:ProgramData\Miniconda3", "$env:ProgramData\Anaconda3")) {
        $cand = Join-Path $base "envs\plaqueapp\python.exe"
        if (Test-Path $cand) { $Py = $cand; break }
    }
}
if (-not $Py) { $Py = (Get-Command py -ErrorAction SilentlyContinue)?.Source }
if (-not $Py) { $Py = (Get-Command python -ErrorAction SilentlyContinue)?.Source }
if (-not $Py) { throw "No Python interpreter found. Set $env:PLAQUE_PY to your python.exe." }
Write-Host "==> Using interpreter: $Py"

Write-Host "==> Building 'Plaque Stats App' with PyInstaller (this can take a few minutes)..."
& $Py -m PyInstaller --noconfirm --clean "plaque_stats_app.spec"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller exited with code $LASTEXITCODE" }

$Exe = Join-Path $Here "dist/Plaque Stats App/Plaque Stats App.exe"
if (Test-Path $Exe) {
    Write-Host ""
    Write-Host "==> BUILD OK"
    Write-Host "    Executable : $Exe"
    Write-Host "    Ship folder: $(Join-Path $Here 'dist/Plaque Stats App')"
    Write-Host "    Launch it, and it will open http://127.0.0.1:<port>/ in your browser."
} else {
    throw "BUILD FAILED: expected exe not found at $Exe"
}

# ---------------------------------------------------------------------------
# FALLBACK (spec-free one-liner) -- if the .spec ever misbehaves, uncomment and run this instead.
# --collect-all pulls submodules + data + binaries for the whole package in one shot.
# ---------------------------------------------------------------------------
# & $Py -m PyInstaller --noconfirm --clean --console --name "Plaque Stats App" `
#     --collect-all shiny --collect-all htmltools --collect-all uvicorn `
#     --collect-submodules starlette --collect-submodules websockets `
#     --collect-submodules anyio `
#     --paths ".." `
#     --add-data "../app_py.py;." `
#     --add-data "../plaque_stats.py;." `
#     --add-data "../plaque_stats_launch.py;." `
#     --add-data "../TEMPLATE.csv;." `
#     --add-data "../example_data_wide.csv;." `
#     --add-data "../example_data_long.csv;." `
#     --add-data "../app.R;." `
#     "freeze_entry.py"
