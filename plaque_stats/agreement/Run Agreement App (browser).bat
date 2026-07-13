@echo off
setlocal
cd /d "%~dp0"
title Agreement App - tool vs manual (browser)

echo ==================================================
echo   Agreement App  -  tool vs manual (browser GUI)
echo ==================================================
echo.
echo Opens in your web browser at  http://127.0.0.1:8010
echo Upload a paired CSV (tool + manual columns), see the figure
echo and all the statistics, and download everything.
echo.
echo Keep THIS window open while you work; press Ctrl+C (or close it)
echo to stop the app.
echo.

rem --- find a Python interpreter ------------------------------------------
set "PYEXE=C:\Users\mbaff\Miniconda3\envs\plaqueapp\python.exe"
if exist "%PYEXE%" (
    set "PYCMD="%PYEXE%""
    goto :run
)
echo Default plaqueapp Python not found; trying 'conda run -n plaqueapp'...
where conda >nul 2>nul
if not errorlevel 1 (
    set "PYCMD=conda run --no-capture-output -n plaqueapp python"
    goto :run
)
echo conda not found; falling back to 'python' on your PATH...
set "PYCMD=python"

:run
echo Launching...
%PYCMD% -m shiny run --launch-browser --port 8010 "%~dp0app_py.py"

echo.
echo The app has stopped. If it never opened, make sure 'plaqueapp' has shiny:
echo     pip install shiny openpyxl
echo.
pause
endlocal
