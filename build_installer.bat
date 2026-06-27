@echo off
rem ============================================================
rem  Build the Windows installer (PlaqueToolkitSetup.exe).
rem  Needs: the ONEDIR build (dist\PlaqueToolkit\) + Inno Setup 6.
rem ============================================================
setlocal
set "ROOT=%~dp0"
set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=C:\Program Files\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"

if not exist "%ISCC%" (
  echo Inno Setup 6 not found - installing via winget ^(accept any prompts^)...
  winget install --id JRSoftware.InnoSetup -e --accept-source-agreements --accept-package-agreements
  set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
)
if not exist "%ISCC%" (
  echo.
  echo Could not find/install Inno Setup. Get it from https://jrsoftware.org/isdl.php then re-run.
  pause & exit /b 1
)
if not exist "%ROOT%dist\PlaqueToolkit\PlaqueToolkit.exe" (
  echo Onedir build missing. Build it first:
  echo    conda run -n plaque pyinstaller --noconfirm build\plaque_app_onedir.spec
  pause & exit /b 1
)

"%ISCC%" "%ROOT%build\installer.iss"
echo.
echo Installer written to: %ROOT%Output\PlaqueToolkitSetup.exe
pause
