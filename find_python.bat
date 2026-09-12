@echo off
rem ============================================================================
rem  find_python.bat  --  locate a usable Python for the toolkit (Windows).
rem
rem  Usage (from another .bat, do NOT use setlocal here -- the caller needs the
rem  variables this sets):
rem
rem      call "%~dp0find_python.bat" plaque
rem      if not defined PYCMD ( echo No Python found & pause & exit /b 1 )
rem      %PYCMD% "plaque_size_tool.py" -i "%~1"
rem
rem  Argument 1 = conda env name to prefer (default: plaque).
rem  Sets PYCMD  = a command prefix, already quoted where a path is involved.
rem       PYWCMD = the same for the windowless interpreter (pythonw), when known.
rem
rem  Resolution order (first hit wins):
rem    1. %PLAQUE_PY%          explicit override (an interpreter path)
rem    2. <conda base>\envs\<env>\python.exe, for the usual install locations
rem    3. conda run -n <env> python
rem    4. py -3                the Windows launcher (a real Python, not the
rem                            Microsoft Store stub)
rem    5. python               last resort, whatever is on PATH
rem
rem  This replaces a hard-coded C:\Users\<author>\Miniconda3\... path that only
rem  ever worked on one machine -- see AUDIT-2026-09.md (PT-5).
rem ============================================================================

set "PLAQUE_ENV=%~1"
if "%PLAQUE_ENV%"=="" set "PLAQUE_ENV=plaque"
set "PYCMD="
set "PYWCMD="

rem --- 1. explicit override ---------------------------------------------------
if defined PLAQUE_PY if exist "%PLAQUE_PY%" (
    set "PYCMD="%PLAQUE_PY%""
    goto :found
)

rem --- 2. a conda env in one of the usual places -------------------------------
for %%B in (
    "%USERPROFILE%\Miniconda3"
    "%USERPROFILE%\Anaconda3"
    "%USERPROFILE%\miniforge3"
    "%USERPROFILE%\mambaforge"
    "%LOCALAPPDATA%\Continuum\miniconda3"
    "%LOCALAPPDATA%\Continuum\anaconda3"
    "%ProgramData%\Miniconda3"
    "%ProgramData%\Anaconda3"
    "%ProgramData%\Miniforge3"
    "%CONDA_PREFIX%"
) do (
    if not defined PYCMD if exist "%%~B\envs\%PLAQUE_ENV%\python.exe" (
        set "PYCMD="%%~B\envs\%PLAQUE_ENV%\python.exe""
        set "PYWCMD="%%~B\envs\%PLAQUE_ENV%\pythonw.exe""
    )
)
if defined PYCMD goto :found

rem --- 3. conda / mamba on PATH ------------------------------------------------
for %%C in (conda mamba micromamba) do (
    if not defined PYCMD (
        where %%C >nul 2>nul
        if not errorlevel 1 set "PYCMD=%%C run --no-capture-output -n %PLAQUE_ENV% python"
    )
)
if defined PYCMD goto :found

rem --- 4. the py launcher (NOT the Store stub) ---------------------------------
where py >nul 2>nul
if not errorlevel 1 (
    py -3 -c "import sys" >nul 2>nul
    if not errorlevel 1 (
        set "PYCMD=py -3"
        set "PYWCMD=pyw -3"
        goto :found
    )
)

rem --- 5. plain python on PATH -------------------------------------------------
where python >nul 2>nul
if not errorlevel 1 (
    python -c "import sys" >nul 2>nul
    if not errorlevel 1 set "PYCMD=python"
)

:found
if not defined PYWCMD if defined PYCMD set "PYWCMD=%PYCMD%"
exit /b 0
