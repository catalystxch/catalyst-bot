; ============================================================
; CATalyst — Inno Setup installer script
; ============================================================
; Build the PyInstaller bundle first (python build.py), then open
; this file in Inno Setup Compiler (ISCC.exe) to produce the
; distributable .exe installer.
;
; Inno Setup download: https://jrsoftware.org/isinfo.php
;
; The release workflow signs CATalyst-owned Catalyst.exe first, builds this
; installer from that signed bundle, then signs the final installer. Do not
; sign upstream splash.exe with the CATalyst certificate. Users run the
; installer first, so Windows checks its signature before the payload.
; ============================================================

#ifndef MyAppName
#define MyAppName        "CATalyst"
#endif
#ifndef MyAppVersion
#define MyAppVersion     "1.0.0"
#endif
#ifndef MyAppId
#define MyAppId          "{{B7F7C8A3-5E1A-4D9B-9F43-CC51A3B9D2E7}"
#endif
#ifndef MyAppUninstallKey
#define MyAppUninstallKey "Software\Microsoft\Windows\CurrentVersion\Uninstall\{B7F7C8A3-5E1A-4D9B-9F43-CC51A3B9D2E7}_is1"
#endif
#define MyAppPublisher   "MonkeyZoo"
#define MyAppURL         "https://github.com/catalystxch/catalyst-bot"
#define MyAppExeName     "Catalyst.exe"
#define MySourceDir      "dist\Catalyst"

[Setup]
; A fresh GUID per product. DO NOT re-use across unrelated products.
; Generate your own in Inno Setup: Tools -> Generate GUID.
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
VersionInfoVersion={#MyAppVersion}

; Install to Program Files by default.  All per-user data
; (bot.db, .env, logs, crash.log, backups) is written to
; %APPDATA%\Catalyst\ by user_paths.py, so Program Files
; can stay read-only as Microsoft intends.
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
UsePreviousAppDir=yes

; Website downloads stay in current-user mode by default.  Existing in-app
; upgrades pass /CURRENTUSER or /ALLUSERS explicitly to preserve their scope.
; Do not offer an easy-to-miss mode dialog: selecting a different scope is how
; a second CATalyst copy and a stale shortcut can be left behind.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline

OutputBaseFilename=Catalyst-Setup-{#MyAppVersion}
OutputDir=Output
Compression=lzma2/ultra
SolidCompression=yes
WizardStyle=modern
SetupLogging=yes

; Uninstaller
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}

; Require Windows 10 or later (WebView2 needs it)
MinVersion=10.0.17763

; Let silent upgrades replace the running app cleanly. CATalyst launches the
; installer only after the user confirms the update and the bot is stopped.
CloseApplications=yes
RestartApplications=no

; Show license during install (optional — create LICENSE.txt first)
; LicenseFile=LICENSE.txt

; Icons for Add/Remove Programs and shortcuts
SetupIconFile=assets\bot_icon_new.ico

; Wizard branding — MonkeyZoo logo on left panel, app icon top-right.
; Inno Setup 6+ accepts PNG directly and auto-scales.
WizardImageFile=assets\MonkeyZoo_Logo.png
WizardSmallImageFile=assets\bot_icon_new.png

; Run the app after install (optional checkbox on the final page)
; See [Run] section below

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
; Pack the entire PyInstaller output folder. The wildcard with
; recursesubdirs picks up _internal\ and every bundled asset.
Source: "{#MySourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; Explicitly include the .env.example so users can see a template
; (user_paths.py seeds .env from this on first launch if needed).
; Harmless if already matched by the wildcard above.
Source: "{#MySourceDir}\.env.example"; DestDir: "{app}"; Flags: ignoreversion onlyifdoesntexist

[Icons]
; Start Menu group entry
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{autoprograms}\{#MyAppName} (Help)"; Filename: "{#MyAppURL}"
Name: "{autoprograms}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"

; Desktop shortcut (opt-in via task checkbox)
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; IconFilename: "{app}\{#MyAppExeName}"

[Run]
; Offer to launch the app after install finishes.
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
; Silent in-app upgrades pass /CATALYST_RELAUNCH=1 so the updated app reopens.
Filename: "{app}\{#MyAppExeName}"; Flags: nowait skipifnotsilent; Check: ShouldAutoRelaunch

[UninstallDelete]
; The uninstaller removes the install dir, but per-user data in
; %APPDATA%\Catalyst\ is deliberately left behind so a
; reinstall picks up the user's existing wallet settings and
; trade history. Users who want a clean wipe can delete
; %APPDATA%\Catalyst\ manually.

[Code]
const
  AppUninstallKey = '{#MyAppUninstallKey}';

function ShouldAutoRelaunch: Boolean;
begin
  Result := ExpandConstant('{param:CATALYST_RELAUNCH|0}') = '1';
end;

function ExistingInstallLocation(RootKey: Integer; var Location: String): Boolean;
begin
  Result := RegQueryStringValue(
    RootKey,
    AppUninstallKey,
    'InstallLocation',
    Location
  ) and (Location <> '');
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  UserLocation: String;
  MachineLocation: String;
  HasUserInstall: Boolean;
  HasMachineInstall: Boolean;
begin
  Result := '';
  HasUserInstall := ExistingInstallLocation(HKCU, UserLocation);
  HasMachineInstall := ExistingInstallLocation(HKLM, MachineLocation);

  if IsAdminInstallMode and HasUserInstall and not HasMachineInstall then
  begin
    Result :=
      'CATalyst is already installed for the current user at ' + UserLocation +
      '. This installer was started with a different install scope. ' +
      'Run it normally (without /ALLUSERS) so the existing copy is updated.';
  end
  else if (not IsAdminInstallMode) and HasMachineInstall and not HasUserInstall then
  begin
    Result :=
      'CATalyst is already installed for all users at ' + MachineLocation +
      '. This installer was started with a different install scope. ' +
      'Use CATalyst''s in-app updater or rerun this installer with /ALLUSERS.';
  end;
end;

procedure VerifyInstalledVersion;
var
  InstalledVersion: String;
  ExpectedVersion: String;
begin
  ExpectedVersion := '{#MyAppVersion}.0';
  if not GetVersionNumbersString(
    ExpandConstant('{app}\{#MyAppExeName}'),
    InstalledVersion
  ) then
  begin
    RaiseException(
      'CATalyst setup could not verify the installed executable version.'
    );
  end;

  if InstalledVersion <> ExpectedVersion then
  begin
    RaiseException(
      'CATalyst setup installed the wrong executable version. Expected ' +
      ExpectedVersion + ', found ' + InstalledVersion + '.'
    );
  end;
  Log('Verified installed CATalyst version ' + InstalledVersion + ' at ' +
    ExpandConstant('{app}\{#MyAppExeName}'));
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    VerifyInstalledVersion;
  end;
end;
