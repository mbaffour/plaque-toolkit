@echo off
rem ============================================================
rem  Install Plaque Toolkit for the current user (no admin needed).
rem  Copies the onedir build to %LOCALAPPDATA% and adds a Start-menu shortcut.
rem  (For a shareable .exe installer instead, use build_installer.bat + Inno Setup.)
rem ============================================================
setlocal
set "SRC=%~dp0dist\PlaqueToolkit"
set "DEST=%LOCALAPPDATA%\Programs\PlaqueToolkit"
set "SM=%APPDATA%\Microsoft\Windows\Start Menu\Programs"

if not exist "%SRC%\PlaqueToolkit.exe" (
  echo Build the app first:
  echo    conda run -n plaque pyinstaller --noconfirm build\plaque_app_onedir.spec
  pause & exit /b 1
)

echo Installing to "%DEST%" ...
if exist "%DEST%" rmdir /s /q "%DEST%"
xcopy /e /i /q /y "%SRC%" "%DEST%" >nul

powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%SM%\Plaque Toolkit.lnk'); $s.TargetPath='%DEST%\PlaqueToolkit.exe'; $s.WorkingDirectory='%DEST%'; $s.Save()"

echo.
echo Installed. Search "Plaque Toolkit" in the Start menu.  (Uninstall: uninstall.bat)
pause
