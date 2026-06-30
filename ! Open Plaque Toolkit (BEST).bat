@echo off
rem =====================================================================
rem  One-click launcher for the BEST plaque app:
rem  the installed all-in-one build with the Precise engine built in.
rem =====================================================================
setlocal
set "APP=%LOCALAPPDATA%\Programs\PlaqueToolkitFull\PlaqueToolkit.exe"

if exist "%APP%" (
    start "" "%APP%"
    exit /b 0
)

echo.
echo   Could not find the installed app at:
echo       %APP%
echo.
echo   Fix: install it from   Output\PlaqueToolkitFullSetup.exe
echo   or open "Plaque Toolkit (full)" from the Windows Start menu.
echo.
pause
