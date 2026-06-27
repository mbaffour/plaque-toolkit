@echo off
setlocal

rem ============================================================
rem  Plaque Size Tool - drag-and-drop launcher (size + turbidity columns)
rem  Drag one or more plaque photos onto this file to measure them.
rem  HEIC (iPhone) is supported directly. Results go to the "out" folder.
rem ============================================================

set "SCRIPT_DIR=%~dp0"
set "PY=C:\Users\mbaff\Miniconda3\envs\plaque\python.exe"
if not exist "%PY%" set "PY=python"

if "%~1"=="" (
  echo.
  echo   Drag one or more plaque photos onto this file to measure them.
  echo.
  pause
  exit /b 0
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
:loop
if "%~1"=="" goto done
echo.
echo === Processing %~nx1 ===
"%PY%" "plaque_size_tool.py" -i "%~1" -p %PLATE% %SMALL% %PUB%
shift
goto loop

:done
echo.
echo All done. Results (CSV + annotated image) are in:
echo   %SCRIPT_DIR%out
echo.
start "" "%SCRIPT_DIR%out"
