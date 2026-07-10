@echo off

setlocal

cd /d "%~dp0"

title Plaque Stats - Make Example + Template



echo ==================================================

echo    Make Example + Template Data

echo ==================================================

echo.

echo This writes three files into THIS folder so you can see the

echo expected data format:

echo     TEMPLATE.csv            (blank-ish template to copy into)

echo     example_data_wide.csv   (worked WIDE example, 3 phages x 3 plates)

echo     example_data_long.csv   (worked LONG example)

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

echo Running:  plaque_stats.py --make-example

echo.

%PYCMD% "%~dp0plaque_stats.py" --make-example

if errorlevel 1 (

    echo.

    echo *** Could not generate the example files - read the messages above. ***

    echo     The 'plaqueapp' env needs pandas/numpy (see requirements.txt).

    pause

    goto :eof

)



echo.

echo Done. TEMPLATE.csv and example_data_*.csv are now in:

echo     %~dp0

echo Open TEMPLATE.csv in Excel to see the layout.

echo.

pause

endlocal

