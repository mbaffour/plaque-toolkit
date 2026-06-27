@echo off
setlocal
rem ============================================================
rem  PRECISE plaque detector - the best combined engine:
rem    PST validated dish + mm calibration  ->  artifact masks (lawn ROI,
rem    blue-label, dish boundary)  ->  PlaqSeg YOLO primary detector
rem    ->  density switch  ->  gated PST-sensitive recall boost  ->  union.
rem  High precision; best on dense countable plates. Drag ONE plate photo on.
rem  Output: out_precise\<name>\ (annotated overlay + per-plaque CSV + summary).
rem  Note: needs the 'plaque' AND 'plaqseg' conda envs (already set up).
rem ============================================================
set "SCRIPT_DIR=%~dp0"
set "PY=C:\Users\mbaff\Miniconda3\envs\plaque\python.exe"
if not exist "%PY%" set "PY=python"

if "%~1"=="" (
  echo.
  echo   Drag ONE plate photo onto this file to detect plaques.
  echo.
  pause & exit /b 0
)

set "PLATE=100"
set /p "PLATE=Petri dish diameter in mm [default 100]: "

set "OUT=%SCRIPT_DIR%out_precise\%~n1"
cd /d "%SCRIPT_DIR%"
echo.
echo === Precise detection: %~nx1  (this runs PlaqSeg on CPU, give it a minute) ===
"%PY%" "precise\run_precise.py" --image "%~1" --out "%OUT%" --tag "%~n1" --plate-mm %PLATE%
echo.
echo Output folder: %OUT%
start "" "%OUT%"
pause
