@echo off
setlocal
cd /d "%~dp0"
title Ingest labels into the training store

echo ==================================================
echo   Ingest ground-truth labels into the training store
echo ==================================================
echo.
echo Drag a FOLDER of labels_*.json (or a single .json) onto this file,
echo or run it and type a path. Each is filed into  training_data\  with a
echo copy of its image + a catalog row, ready for retraining.
echo.

rem --- find a Python interpreter ------------------------------------------
rem --- find a Python interpreter (portable: no hard-coded paths -- PT-5) ----
set "PYCMD="
if defined PLAQUE_PY if exist "%PLAQUE_PY%" set "PYCMD="%PLAQUE_PY%""
if not defined PYCMD for %%B in (
    "%USERPROFILE%\Miniconda3" "%USERPROFILE%\Anaconda3" "%USERPROFILE%\miniforge3"
    "%USERPROFILE%\mambaforge" "%ProgramData%\Miniconda3" "%ProgramData%\Anaconda3"
) do (
    if not defined PYCMD if exist "%%~B\envs\plaqueapp\python.exe" set "PYCMD="%%~B\envs\plaqueapp\python.exe""
)
if not defined PYCMD (
    where conda >nul 2>nul
    if not errorlevel 1 set "PYCMD=conda run --no-capture-output -n plaqueapp python"
)
if not defined PYCMD (
    where py >nul 2>nul
    if not errorlevel 1 set "PYCMD=py -3"
)
if not defined PYCMD set "PYCMD=python"

:run
set "TARGET=%~1"
if "%TARGET%"=="" set /p "TARGET=Folder or labels_*.json to ingest: "
if "%TARGET%"=="" (
    echo Nothing given.
    pause
    goto :eof
)
%PYCMD% "%~dp0ingest_labels.py" "%TARGET%"
if errorlevel 1 (
    echo.
    echo *** Ingest failed - read the messages above. ***
)
echo.
pause
endlocal
