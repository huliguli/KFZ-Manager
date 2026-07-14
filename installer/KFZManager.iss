; Inno Setup script for KFZManager (onedir build -> per-user installer).
; Build:  ISCC.exe /DMyAppVersion=1.0.0 installer\KFZManager.iss
;
; Per-user install (no admin/UAC) so the in-app updater can run the installer
; silently and replace the program files without elevation. The app's data
; (%APPDATA%\KFZManager) is never touched by install/uninstall.

#define MyAppName "KFZManager"
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#define MyAppExe "KFZManager.exe"
#define MyAppPublisher "Mijonex"

[Setup]
AppId={{7D2B4E91-5C38-4F6A-9B07-E31A6D80C254}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
VersionInfoVersion={#MyAppVersion}
WizardStyle=modern
; Per-user install: no admin rights needed (lets silent auto-update work).
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\{#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=KFZManager-Setup
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\{#MyAppExe}
UninstallDisplayName={#MyAppName}
Compression=lzma2
SolidCompression=yes
; Close the running app (Restart Manager) before replacing files during update.
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "de"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; The whole PyInstaller onedir folder (exe + _internal/) ships as-is.
Source: "..\dist\KFZManager\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Run]
; Relaunch after install. No 'skipifsilent', so a silent auto-update also
; relaunches the freshly updated app.
Filename: "{app}\{#MyAppExe}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall
