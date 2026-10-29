; ===========================================================================
;  ConvertCAD.iss - Inno Setup script for the Windows INSTALLER
;
;  Build it with scripts\build_installer.bat (recommended): the script builds
;  the program first, reads the version and calls the Inno Setup compiler.
;  By hand:  ISCC.exe /DAppVersion=1.0.0 installer\ConvertCAD.iss
;
;  Needs Inno Setup 6.3 or later (free): https://jrsoftware.org/isinfo.php
;  Input:   dist\ConvertCAD\           (the portable folder, build_exe.bat)
;  Output:  dist\ConvertCAD-<version>-win64-setup.exe
;
;  The installer copies the SAME folder as the portable zip (LibreDWG for
;  DWG output, the OCR engines and models, Tesseract when bundled). Users
;  install nothing else. No administrator rights are needed: by default it
;  installs for the current user; "Install for all users" asks for them.
; ===========================================================================

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\ConvertCAD"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif
#define AppName "ConvertCAD"
#define AppPublisher "abdelhaouari"
#define AppURL "https://github.com/abdelhaouari-AE/ConvertCAD"
#define AppExe "ConvertCAD.exe"

[Setup]
; AppId identifies the program for upgrades and uninstall: never change it.
AppId={{6E0B5D1A-3C7F-4B2E-9A64-C0F2D8A1B7E3}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir={#OutputDir}
OutputBaseFilename={#AppName}-{#AppVersion}-win64-setup
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName} {#AppVersion}
VersionInfoVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} setup
VersionInfoProductName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; 64-bit Windows 10 / 11 only (the program is 64-bit)
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
; current user by default (no admin rights), all users on request
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
; close a running ConvertCAD before updating it
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[CustomMessages]
english.SendToTask=Add ConvertCAD to the "Send to" menu (right-click on PDF files)
french.SendToTask=Ajouter ConvertCAD au menu "Envoyer vers" (clic droit sur les PDF)

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "sendto"; Description: "{cm:SendToTask}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; an update replaces the whole program: no file of the old version is left
Type: filesandordirs; Name: "{app}\_internal"

[Files]
; the portable marker must never be installed (settings go to the profile)
Source: "{#SourceDir}\*"; DestDir: "{app}"; Excludes: "ConvertCAD.portable"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon
Name: "{usersendto}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: sendto

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
