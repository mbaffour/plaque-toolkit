@echo off
setlocal
cd /d "%~dp0"
title Hand-label plaques in Fiji / ImageJ

echo ==================================================
echo   Hand-label plaques in Fiji / ImageJ
echo ==================================================
echo.
echo STEPS:
echo   1. Fiji opens (or open it yourself from https://fiji.sc/).
echo   2. Plugins ^> Macros ^> Install...   ->  pick:
echo        %~dp0fiji_label.ijm
echo   3. Open your plate photo:  File ^> Open
echo   4. Run  "PT: set up plaque labelling"   (Plugins ^> Macros menu)
echo   5. Draw an OVAL on each plaque; press  t  after each.
echo   6. Run  "PT: save plaque labels"  ->  writes  plaque_labels_<image>.csv
echo   7. Run  "Import Fiji labels.bat"  and drop that CSV on it.
echo.

set "FIJI="
for %%P in (
  "C:\Fiji.app\ImageJ-win64.exe"
  "%USERPROFILE%\Fiji.app\ImageJ-win64.exe"
  "%USERPROFILE%\Downloads\Fiji.app\ImageJ-win64.exe"
  "%USERPROFILE%\Desktop\Fiji.app\ImageJ-win64.exe"
  "%USERPROFILE%\Documents\Fiji.app\ImageJ-win64.exe"
  "C:\Program Files\Fiji.app\ImageJ-win64.exe"
) do if exist "%%~P" set "FIJI=%%~P"

if defined FIJI (
  echo Launching Fiji:  %FIJI%
  start "" "%FIJI%"
) else (
  echo Could not find Fiji automatically. Install it from https://fiji.sc/, open it,
  echo then follow steps 2-7 above. The macro to install is:
  echo    %~dp0fiji_label.ijm
)
echo.
pause
endlocal
