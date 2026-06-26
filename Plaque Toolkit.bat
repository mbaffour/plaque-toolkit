@echo off
rem ====================================================================
rem  Plaque Toolkit - launch the app from source on Windows (no packaging).
rem  Tries, in order:
rem    1. PLAQUE_PY env var (if you set it to a pythonw.exe)
rem    2. the 'plaque' conda env python found next to a discoverable conda
rem    3. `conda run -n plaque` (works as long as conda is on PATH)
rem  The first one that works wins.  Double-click this file to run.
rem ====================================================================
setlocal EnableDelayedExpansion
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

rem --- 1. explicit override -------------------------------------------------
if defined PLAQUE_PY (
  if exist "%PLAQUE_PY%" (
    start "" "%PLAQUE_PY%" "plaque_app.py"
    exit /b 0
  )
)

rem --- 2. common local conda env locations ---------------------------------
for %%R in (
  "%USERPROFILE%\Miniconda3"
  "%USERPROFILE%\Anaconda3"
  "%USERPROFILE%\miniforge3"
  "%USERPROFILE%\mambaforge"
  "%ProgramData%\Miniconda3"
  "%ProgramData%\Anaconda3"
) do (
  if exist "%%~R\envs\plaque\pythonw.exe" (
    start "" "%%~R\envs\plaque\pythonw.exe" "plaque_app.py"
    exit /b 0
  )
)

rem --- 3. conda run fallback ------------------------------------------------
where conda >nul 2>nul
if %ERRORLEVEL%==0 (
  start "" conda run -n plaque pythonw plaque_app.py
  exit /b 0
)

echo Could not find the 'plaque' conda environment.
echo Create it first:   conda env create -f environment.yml
echo Or set PLAQUE_PY to your env's pythonw.exe and re-run.
pause
exit /b 1
