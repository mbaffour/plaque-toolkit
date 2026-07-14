@echo off

setlocal

cd /d "%~dp0"

title Plaque Stats - Analysis App



echo ==================================================

echo    Plaque Stats and Violins  -  Browser App

echo ==================================================

echo.

echo This starts the app and opens it in your web browser at:

echo     http://127.0.0.1:8000

echo.

echo Keep THIS window open while you work. Press Ctrl+C (or just

echo close the window) when you are finished, to stop the app.

echo.



rem --- Find a Python interpreter --------------------------------------------

set "PYEXE=C:\Users\mbaff\Miniconda3\envs\plaqueapp\python.exe"

if exist "%PYEXE%" (

    set "PYCMD="%PYEXE%""

    echo Using Python: %PYEXE%

    goto :run

)



echo Default plaqueapp Python not found at:

echo     %PYEXE%

echo Trying 'conda run -n plaqueapp' instead...

where conda >nul 2>nul

if not errorlevel 1 (

    set "PYCMD=conda run --no-capture-output -n plaqueapp python"

    goto :run

)



echo conda not found either; falling back to 'python' on your PATH...

set "PYCMD=python"



:run

echo.

rem Always use port 8000, and free it first so a leftover server from a previous run
rem can't keep serving the OLD app. Only the listener on this exact port is stopped.
set "PLAQUE_PORT=8000"
for /f "tokens=5" %%P in ('netstat -ano ^| findstr "127.0.0.1:8000" ^| findstr LISTENING') do taskkill /F /PID %%P >nul 2>nul

rem Prefer the launcher module; fall back to 'shiny run' if it isn't importable.

%PYCMD% -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('plaque_stats_launch') else 1)"

if not errorlevel 1 (

    echo Launching via the plaque_stats_launch helper...

    %PYCMD% -m plaque_stats_launch

    goto :end

)



echo Launching via 'shiny run'...

%PYCMD% -m shiny run --launch-browser --port 8000 "%~dp0app_py.py"



:end

echo.

echo The app has stopped. If you saw errors above and it never opened,

echo make sure the 'plaqueapp' conda env has shiny installed:

echo     pip install shiny openpyxl

echo.

pause

endlocal

