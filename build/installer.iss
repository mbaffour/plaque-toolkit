; build/installer.iss  —  build the Windows installer with Inno Setup 6:
;     "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" build\installer.iss
; (Install Inno Setup first: https://jrsoftware.org/isdl.php  or  winget install JRSoftware.InnoSetup)
; It wraps the ONEDIR PyInstaller build (dist\PlaqueToolkit\) into PlaqueToolkitSetup.exe.

#define AppName "Plaque Toolkit"
#define AppVer  "1.0.0"
#define AppExe  "PlaqueToolkit.exe"

[Setup]
AppName={#AppName}
AppVersion={#AppVer}
DefaultDirName={autopf}\PlaqueToolkit
DefaultGroupName={#AppName}
OutputBaseFilename=PlaqueToolkitSetup
OutputDir=..\Output
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\{#AppExe}
SetupIconFile=..\app\resources\icon.ico
WizardStyle=modern

[Files]
; ONEDIR build output (built with build/plaque_app_onedir.spec)
Source: "..\dist\PlaqueToolkit\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}";          Filename: "{app}\{#AppExe}"
Name: "{commondesktop}\{#AppName}";  Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
