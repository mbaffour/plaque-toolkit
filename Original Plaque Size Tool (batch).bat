@echo off
rem ============================================================
rem  WHOLE FOLDER, ORIGINAL published Plaque Size Tool behaviour.
rem  This is the original tool's batch mode (-d FOLDER) run with --published.
rem  Drag a FOLDER of plate photos onto this file (or put them in the 'plates'
rem  folder). Name each photo after its plate. HEIC (iPhone) is supported.
rem  -> one data-green-<plate>.csv per plate + summary.csv, in the 'out' folder.
rem ============================================================
setlocal
set "SCRIPT_DIR=%~dp0"
rem --- Find a Python interpreter (portable; see find_python.bat) -------------
call "%~dp0find_python.bat" plaque
if not defined PYCMD (
  echo.
  echo   No usable Python was found.
  echo   Install the toolkit environment first:  conda env create -f environment.yml
  echo   or set PLAQUE_PY to your python.exe.
  echo.
  pause
  exit /b 1
)

set "FOLDER=%~1"
if "%FOLDER%"=="" set "FOLDER=%SCRIPT_DIR%plates"
if not exist "%FOLDER%" (
  echo.
  echo  Put your plate photos in:  %FOLDER%
  echo  or drag a folder onto this file, then run again.
  echo.
  pause & exit /b 1
)

set "SMALL="
choice /C NS /M "Plaque size - [N]ormal or [S]mall plaques under 2.5mm"
if errorlevel 2 set "SMALL=-small"

set "PLATE=100"
set /p "PLATE=Petri dish diameter in mm [default 100]: "

cd /d "%SCRIPT_DIR%"
echo.
echo === ORIGINAL published mode - measuring every plate in: %FOLDER% ===
%PYCMD% "plaque_size_tool.py" -d "%FOLDER%" -p %PLATE% %SMALL% --published
echo.
echo === Building summary.csv (one row per plate) ===
%PYCMD% "summarize_plates.py" -o "out"
echo.
echo Per-plate CSVs (data-green-*.csv) + summary.csv are in:
echo   %SCRIPT_DIR%out
start "" "%SCRIPT_DIR%out"
pause
