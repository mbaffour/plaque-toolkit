@echo off
setlocal
cd /d "%~dp0"
title Agreement - tool vs manual measurements

echo ==================================================
echo   Method comparison: tool vs manual measurements
echo ==================================================
echo.
echo Compares an automated measurement against a manual reference
echo (Pearson r, ICC, Bland-Altman bias + limits of agreement).
echo Drag a CSV with two numeric columns (tool + manual) onto this
echo file, or just run it to use the bundled example.
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
set "DATA=%~1"
if "%DATA%"=="" (
    if not exist "%~dp0example_agreement.csv" %PYCMD% "%~dp0agreement.py" --make-example
    set "DATA=%~dp0example_agreement.csv"
    echo No file given - using the bundled example: example_agreement.csv
)
echo.
echo Running the agreement analysis...
echo   (columns are auto-detected; override with --tool COL --manual COL)
echo.
%PYCMD% "%~dp0agreement.py" "%DATA%" --unit mm --what "plaque diameter" --out "%~dp0results"
if errorlevel 1 (
    echo.
    echo *** The analysis failed - read the messages above. ***
    echo     Your file needs two numeric columns; name them so they are
    echo     recognised (e.g. toolkit_mm and manual_mm / fiji_mm), or run
    echo     agreement.py with  --tool COL --manual COL.
    pause
    goto :eof
)

echo.
echo Done. Figures + report + stats are in the 'results' folder. Opening it...
start "" "%~dp0results"
echo.
pause
endlocal
