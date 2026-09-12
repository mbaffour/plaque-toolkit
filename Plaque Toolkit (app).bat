@echo off
rem Launch the unified Plaque Toolkit app from source (no packaging needed).
rem The standalone build is dist\PlaqueToolkit.exe once you've run PyInstaller.
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
cd /d "%SCRIPT_DIR%"
start "" %PYWCMD% "plaque_app.py"
