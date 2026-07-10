@echo off

setlocal

cd /d "%~dp0"

title Plaque Stats - Run CLI (example)



echo ==================================================

echo    Run CLI analysis on the EXAMPLE data

echo ==================================================

echo.

echo The exact command being run (copy / adapt it for your own CSV):

echo.

echo   python plaque_stats.py example_data_wide.csv --group group --value diameter_mm --replicate replicate --out results --title "Plaque diameter by phage"

echo.

echo Your figures + tables will be written into the 'results' folder.

echo.



rem --- Find a Python interpreter --------------------------------------------

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

rem Generate the example data first if it isn't there yet.

if not exist "%~dp0example_data_wide.csv" (

    echo example_data_wide.csv not found - generating the examples first...

    %PYCMD% "%~dp0plaque_stats.py" --make-example

    echo.

)



%PYCMD% "%~dp0plaque_stats.py" "%~dp0example_data_wide.csv" --group group --value diameter_mm --replicate replicate --out "%~dp0results" --title "Plaque diameter by phage"

if errorlevel 1 (

    echo.

    echo *** The analysis failed - read the messages above. ***

    pause

    goto :eof

)



echo.

echo Success. Opening the results folder...

start "" "%~dp0results"

echo.

pause

endlocal

