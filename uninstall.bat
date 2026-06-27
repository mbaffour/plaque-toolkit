@echo off
rem Remove a user-scope Plaque Toolkit install (from install.bat).
setlocal
set "DEST=%LOCALAPPDATA%\Programs\PlaqueToolkit"
set "LNK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Plaque Toolkit.lnk"
if exist "%DEST%" rmdir /s /q "%DEST%"
if exist "%LNK%" del "%LNK%"
echo Plaque Toolkit uninstalled.
pause
