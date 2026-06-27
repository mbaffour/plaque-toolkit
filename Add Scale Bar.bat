@echo off
setlocal

rem ============================================================
rem  Add Scale Bar - drag-and-drop launcher
rem  Drag one (or more) plate photos onto this file to stamp a physical
rem  scale bar (e.g. "5 mm") onto each, using the petri-dish calibration.
rem  HEIC (iPhone) is supported. Output: <name>_scaled.jpg next to the input.
rem ============================================================

set "SCRIPT_DIR=%~dp0"
set "PY=C:\Users\mbaff\Miniconda3\envs\plaque\python.exe"
if not exist "%PY%" set "PY=python"

if "%~1"=="" (
  echo.
  echo   Drag one or more plate photos onto this file to add a scale bar.
  echo.
  pause
  exit /b 0
)

set "PLATE=100"
set /p "PLATE=Petri dish diameter in mm [default 100]: "

cd /d "%SCRIPT_DIR%"
:loop
if "%~1"=="" goto done
echo.
echo === Scaling %~nx1 ===
"%PY%" "add_scale.py" -i "%~1" --plate-mm %PLATE%
set "LAST=%~dpn1_scaled.jpg"
if exist "%LAST%" start "" "%LAST%"
shift
goto loop

:done
echo.
echo All done. Scaled images saved next to each input as ^<name^>_scaled.jpg
echo.
