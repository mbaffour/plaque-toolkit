@echo off
setlocal

rem ============================================================
rem  Plaque Size Tool - interactive GUI editor
rem  Drag ONE plaque photo onto this file (or double-click to pick one).
rem  HEIC (iPhone) is supported directly. In the window you can:
rem    left-drag = add a circle, Trace mode click = auto-trace,
rem    right-click = remove, Save = write results to the "out" folder.
rem    The window also has a "Sensitive: ON/OFF" button to re-detect tiny plaques live,
rem    and draws an orange circle around the detected dish (calibration check).
rem ============================================================

set "SCRIPT_DIR=%~dp0"
set "PY=C:\Users\mbaff\Miniconda3\envs\plaque\python.exe"
if not exist "%PY%" set "PY=python"

cd /d "%SCRIPT_DIR%"

set "SMALL="
choice /C NS /M "Plaque size - [N]ormal or [S]mall plaques under 2.5mm"
if errorlevel 2 set "SMALL=-small"

set "SENS="
choice /C NY /M "Also catch very small (tiny) plaques - sensitive mode [N]o or [Y]es"
if errorlevel 2 set "SENS=--sensitive"

set "PLATE=100"
set /p "PLATE=Petri dish diameter in mm [default 100]: "

if "%~1"=="" (
  "%PY%" "plaque_gui.py" -p %PLATE% %SMALL% %SENS%
) else (
  "%PY%" "plaque_gui.py" -i "%~1" -p %PLATE% %SMALL% %SENS%
)
