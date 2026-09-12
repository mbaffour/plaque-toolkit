@echo off
rem ============================================================
rem  Measure EVERY plate in a folder -> one data-green-<plate>.csv each + summary.csv
rem  Drag a FOLDER of plate photos onto this file (or put them in the 'plates' folder).
rem  Name each photo after its plate (e.g. WT-1.jpg) so the CSV is named the same.
rem  HEIC (iPhone) is supported. Results go to the 'out' folder.
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

set "PUB="
choice /C CO /M "Mode - [C]urrent (corrected) or [O]riginal published"
if errorlevel 2 set "PUB=--published"

set "PLATE=100"
set /p "PLATE=Petri dish diameter in mm [default 100]: "

cd /d "%SCRIPT_DIR%"
echo.
echo === Measuring every plate in: %FOLDER% ===
%PYCMD% "plaque_size_tool.py" -d "%FOLDER%" -p %PLATE% %SMALL% %PUB%
echo.
echo === Building summary.csv (one row per plate) ===
%PYCMD% "summarize_plates.py" -o "out"
echo.
echo Per-plate CSVs (data-green-*.csv) + summary.csv are in:
echo   %SCRIPT_DIR%out
start "" "%SCRIPT_DIR%out"
pause
