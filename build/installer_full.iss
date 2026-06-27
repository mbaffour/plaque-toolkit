; build/installer_full.iss  —  installer for the SELF-CONTAINED build (Precise included).
;     "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" build\installer_full.iss
; Wraps the heavy ONEDIR PyInstaller build (dist\PlaqueToolkitFull\, built with
; build\plaque_app_full.spec) — which bundles torch + ultralytics + the YOLO weights +
; the learned classifier — into Output\PlaqueToolkitFullSetup.exe. This install runs the
; Precise engine in-process with NO conda env and NO source checkout.
;
; It installs SIDE-BY-SIDE with the light build (different AppId/AppName/DefaultDirName/
; OutputBaseFilename), so the existing PlaqueToolkitSetup.exe is untouched.

#define AppName "Plaque Toolkit (full)"
#define AppId   "PlaqueToolkitFull"
#define AppVer  "1.0.0"
#define AppExe  "PlaqueToolkit.exe"

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVer}
DefaultDirName={autopf}\PlaqueToolkitFull
DefaultGroupName={#AppName}
OutputBaseFilename=PlaqueToolkitFullSetup
OutputDir=..\Output
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\{#AppExe}
SetupIconFile=..\app\resources\icon.ico
WizardStyle=modern

[Files]
; ONEDIR build output (built with build/plaque_app_full.spec)
Source: "..\dist\PlaqueToolkitFull\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}";          Filename: "{app}\{#AppExe}"
Name: "{commondesktop}\{#AppName}";  Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
