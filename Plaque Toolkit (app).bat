@echo off
rem Launch the unified Plaque Toolkit app from source (no packaging needed).
rem The standalone build is dist\PlaqueToolkit.exe once you've run PyInstaller.
setlocal
set "SCRIPT_DIR=%~dp0"
set "PYW=C:\Users\mbaff\Miniconda3\envs\plaque\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw"
cd /d "%SCRIPT_DIR%"
start "" "%PYW%" "plaque_app.py"
