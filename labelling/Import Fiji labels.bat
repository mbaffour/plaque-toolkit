@echo off
setlocal
cd /d "%~dp0"
title Import Fiji labels into the training store

echo ==================================================
echo   Import Fiji plaque labels into the training store
echo ==================================================
echo.
echo Drag the  plaque_labels_*.csv  (saved by the Fiji macro) onto this file,
echo or run it and type the path. You'll be asked for the image and the mm/px
echo (use the same calibration the app shows, e.g. ~0.0393 mm/px).
echo.

rem --- find a Python interpreter ------------------------------------------
set "PYEXE=C:\Users\mbaff\Miniconda3\envs\plaqueapp\python.exe"
if exist "%PYEXE%" (
    set "PYCMD="%PYEXE%""
    goto :run
)
where conda >nul 2>nul
if not errorlevel 1 (
    set "PYCMD=conda run --no-capture-output -n plaqueapp python"
    goto :run
)
set "PYCMD=python"

:run
set "CSV=%~1"
if "%CSV%"=="" set /p "CSV=Path to plaque_labels_*.csv: "
if "%CSV%"=="" (
    echo Nothing given.
    pause
    goto :eof
)
set /p "IMG=Path to the plate image (blank to skip the image copy): "
set /p "MMPP=mm per pixel (blank if unknown): "

set "IMGARG="
set "MMARG="
if not "%IMG%"=="" set "IMGARG=--image "%IMG%""
if not "%MMPP%"=="" set "MMARG=--mm-per-px %MMPP%"

%PYCMD% "%~dp0fiji_import.py" --results "%CSV%" %IMGARG% %MMARG%
if errorlevel 1 (
    echo.
    echo *** Import failed - read the messages above. ***
)
echo.
pause
endlocal
