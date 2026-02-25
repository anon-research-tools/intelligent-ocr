; Inno Setup script for 高校 OCR 工具
; Compile this with Inno Setup Compiler (iscc)
; Download: https://jrsoftware.org/isdownload.php

#define MyAppName "智能OCR工具"
#define MyAppVersion "2.2.4"
#define MyAppPublisher "数字文献学"
#define MyAppURL "https://github.com/anon-research-tools/intelligent-ocr"
#define MyAppExeName "智能OCR工具.exe"

[Setup]
; Application info
AppId={{12345678-1234-1234-1234-123456789012}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}

; Install paths
DefaultDirName={autopf}\{#MyAppName}
DisableDirPage=no
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes

; Output settings
OutputDir=..\..\dist\installer
OutputBaseFilename=智能OCR工具_安装程序_v{#MyAppVersion}
SetupIconFile=..\..\desktop\resources\icon.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

; Windows version requirements (Windows 10 or later)
MinVersion=10.0

; Privileges - allow installation without admin for per-user install
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; Installer appearance
UninstallDisplayIcon={app}\{#MyAppExeName}

; Architecture
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
english.BeveledLabel=Smart OCR - Digital Philology

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Main application files from PyInstaller output
Source: "..\..\dist\智能OCR工具\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
// Visual C++ Redistributable detection
// Required for PyInstaller applications using native extensions

const
  VC_REDIST_X64_2015_2022 = '{36F68A90-239C-34DF-B58C-64B30153CE35}';  // Visual C++ 2015-2022 x64

function IsVCRedistInstalled: Boolean;
var
  ProductCode: String;
begin
  // Check for Visual C++ 2015-2022 Redistributable (x64)
  ProductCode := VC_REDIST_X64_2015_2022;
  Result := RegKeyExists(HKLM, 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\' + ProductCode) or
            RegKeyExists(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\' + ProductCode);

  // Also check for any VC++ 14.x runtime
  if not Result then
  begin
    Result := RegKeyExists(HKLM, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64');
  end;
end;

function InitializeSetup(): Boolean;
begin
  Result := True;

  // Check for Visual C++ Redistributable
  if not IsVCRedistInstalled then
  begin
    if MsgBox('此程序需要 Microsoft Visual C++ Redistributable 运行库。' + #13#10 +
              '是否继续安装？' + #13#10#13#10 +
              '如果程序无法启动，请从 Microsoft 官网下载并安装：' + #13#10 +
              'Visual C++ Redistributable for Visual Studio 2015-2022',
              mbConfirmation, MB_YESNO) = IDNO then
    begin
      Result := False;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    // Post-installation tasks (if any)
    Log('Installation completed successfully');
  end;
end;

function GetUninstallString: String;
var
  UninstallPath: String;
  UninstallString: String;
begin
  Result := '';
  UninstallPath := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#SetupSetting("AppId")}_is1';
  if RegQueryStringValue(HKLM, UninstallPath, 'UninstallString', UninstallString) then
    Result := UninstallString
  else if RegQueryStringValue(HKCU, UninstallPath, 'UninstallString', UninstallString) then
    Result := UninstallString;
end;

function IsUpgrade: Boolean;
begin
  Result := GetUninstallString <> '';
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  UninstallString: String;
  ResultCode: Integer;
begin
  Result := '';

  // If upgrading, uninstall the old version first
  if IsUpgrade then
  begin
    UninstallString := GetUninstallString;
    if UninstallString <> '' then
    begin
      UninstallString := RemoveQuotes(UninstallString);
      if Exec(UninstallString, '/SILENT /NORESTART', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
      begin
        Log('Previous version uninstalled successfully');
      end;
    end;
  end;
end;
