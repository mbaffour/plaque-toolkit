@echo off
rem ============================================================
rem  ONE plate, ORIGINAL published Plaque Size Tool behaviour.
rem  Hardwired to --published (reproduces Trofimova & Jaschke 2021 output:
rem  same plaque count; diameters within <=0.04 mm of the literal original).
rem  Drag ONE plate photo onto this file. HEIC (iPhone) is supported.
rem ============================================================
setlocal
set "SCRIPT_DIR=%~dp0"
set "PY=C:\Users\mbaff\Miniconda3\envs\plaque\python.exe"
if not exist "%PY%" set "PY=python"

if "%~1"=="" (
  echo.
  echo   Drag ONE plate photo onto this file to measure it.
  echo.
  pause & exit /b 0
)

set "SMALL="
choice /C NS /M "Plaque size - [N]ormal or [S]mall plaques under 2.5mm"
if errorlevel 2 set "SMALL=-small"

set "PLATE=100"
set /p "PLATE=Petri dish diameter in mm [default 100]: "

cd /d "%SCRIPT_DIR%"
echo.
echo === ORIGINAL published mode - %~nx1 ===
"%PY%" "plaque_size_tool.py" -i "%~1" -p %PLATE% %SMALL% --published
echo.
echo CSV written to:  %SCRIPT_DIR%out\data-green-%~n1.csv
start "" "%SCRIPT_DIR%out"
pause
