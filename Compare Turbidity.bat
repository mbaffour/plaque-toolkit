@echo off
setlocal

rem ============================================================
rem  Compare plaque TURBIDITY across phages (batch optical density)
rem  Drag the FOLDER of phage plate photos onto this file.
rem  Name each image after its phage (e.g. T4.heic, T7.heic).
rem  HEIC (iPhone) is supported directly.
rem  Optional blank-agar + flat-field references give absolute OD;
rem  without them you get lawn-relative transmittance.
rem ============================================================

set "SCRIPT_DIR=%~dp0"
set "PY=C:\Users\mbaff\Miniconda3\envs\plaque\python.exe"
if not exist "%PY%" set "PY=python"

if "%~1"=="" (
  echo.
  echo   Drag the FOLDER of phage plate photos onto this file.
  echo.
  pause
  exit /b 0
)

set "FOLDER=%~1"

set "SMALL="
choice /C NS /M "Plaque size - [N]ormal or [S]mall plaques under 2.5mm"
if errorlevel 2 set "SMALL=-small"

set "PLATE=100"
set /p "PLATE=Petri dish diameter in mm [default 100]: "

set "BLANK="
set /p "BLANKPATH=Path to blank-agar image for absolute OD (Enter to skip): "
if not "%BLANKPATH%"=="" set "BLANK=--blank "%BLANKPATH%""

set "FLAT="
set /p "FLATPATH=Path to flat-field image (Enter to skip): "
if not "%FLATPATH%"=="" set "FLAT=--flat "%FLATPATH%""

cd /d "%SCRIPT_DIR%"
"%PY%" "plaque_turbidity.py" -d "%FOLDER%" -p %PLATE% %SMALL% %BLANK% %FLAT%

echo.
echo Done. Results (plaques_all.csv, per_phage.csv, qc.csv, overlays) are in:
echo   %SCRIPT_DIR%out_turbidity
echo.
start "" "%SCRIPT_DIR%out_turbidity"
pause
