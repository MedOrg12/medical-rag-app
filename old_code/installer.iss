; Medical Research RAG Pipeline - Inno Setup Installer Script
; This script creates a Windows installer (.exe) for the application
;
; Prerequisites to build this installer:
; 1. Install Inno Setup from: https://jrsoftware.org/isdl.php
; 2. Open this file in Inno Setup Compiler
; 3. Click "Build" -> "Compile"
;
; The installer will be created in the "Output" folder

#define MyAppName "Medical Research RAG Pipeline"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "MoCode98"
#define MyAppURL "https://github.com/MoCode98/medical-research-rag"
#define MyAppExeName "START_APP.bat"

[Setup]
; NOTE: The value of AppId uniquely identifies this application
AppId={{8F9A2B3C-4D5E-6F7A-8B9C-0D1E2F3A4B5C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\MedicalResearchRAG
DisableProgramGroupPage=yes
LicenseFile=LICENSE
; Uncomment the following line to run in administrative mode
; PrivilegesRequired=admin
OutputDir=installer_output
OutputBaseFilename=MedicalResearchRAG_Setup
SetupIconFile=app_icon.ico
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Application files
Source: "docker-compose.yml"; DestDir: "{app}"; Flags: ignoreversion
Source: "Dockerfile"; DestDir: "{app}"; Flags: ignoreversion
Source: "docker-entrypoint.sh"; DestDir: "{app}"; Flags: ignoreversion
Source: ".dockerignore"; DestDir: "{app}"; Flags: ignoreversion
Source: "requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "app.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "ingest.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "query.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "query_enhanced.py"; DestDir: "{app}"; Flags: ignoreversion

; Source code directories
Source: "src\*"; DestDir: "{app}\src"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "api\*"; DestDir: "{app}\api"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "static\*"; DestDir: "{app}\static"; Flags: ignoreversion recursesubdirs createallsubdirs

; PDF files (medical research papers)
Source: "pdfs\*"; DestDir: "{app}\pdfs"; Flags: ignoreversion recursesubdirs createallsubdirs

; Icon file
Source: "app_icon.ico"; DestDir: "{app}"; Flags: ignoreversion

; Batch scripts
Source: "START_APP.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "STOP_APP.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "DOWNLOAD_MODELS.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "POST_INSTALL_SETUP.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "CHECK_STATUS.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "DEBUG_INGESTION.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "wait_for_ingestion.ps1"; DestDir: "{app}"; Flags: ignoreversion

; Scripts folder (backup, restore, PDF metadata tools)
Source: "scripts\*"; DestDir: "{app}\scripts"; Flags: ignoreversion recursesubdirs createallsubdirs

; Documentation
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion isreadme
Source: "DOCKER_SETUP.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "BUILD_INSTALLER.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "WINDOWS_INGESTION_TROUBLESHOOTING.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "QUICK_START_DOCKER.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "QUICK_START_WEB_UI.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "WINDOWS_INSTALLER_README.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}\Start Medical RAG"; Filename: "{app}\START_APP.bat"; WorkingDir: "{app}"; IconFilename: "{app}\app_icon.ico"
Name: "{autoprograms}\{#MyAppName}\Stop Medical RAG"; Filename: "{app}\STOP_APP.bat"; WorkingDir: "{app}"; IconFilename: "{app}\app_icon.ico"
Name: "{autoprograms}\{#MyAppName}\Check Status"; Filename: "{app}\CHECK_STATUS.bat"; WorkingDir: "{app}"; IconFilename: "{app}\app_icon.ico"
Name: "{autoprograms}\{#MyAppName}\Complete Setup (First Time)"; Filename: "{app}\POST_INSTALL_SETUP.bat"; WorkingDir: "{app}"; IconFilename: "{app}\app_icon.ico"
Name: "{autoprograms}\{#MyAppName}\Download AI Models"; Filename: "{app}\DOWNLOAD_MODELS.bat"; WorkingDir: "{app}"; IconFilename: "{app}\app_icon.ico"
Name: "{autoprograms}\{#MyAppName}\Debug Ingestion"; Filename: "{app}\DEBUG_INGESTION.bat"; WorkingDir: "{app}"; IconFilename: "{app}\app_icon.ico"
Name: "{autoprograms}\{#MyAppName}\Open Web Interface"; Filename: "http://localhost:8000"; IconFilename: "{app}\app_icon.ico"
Name: "{autoprograms}\{#MyAppName}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Medical Research RAG"; Filename: "{app}\START_APP.bat"; WorkingDir: "{app}"; IconFilename: "{app}\app_icon.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\WINDOWS_INSTALLER_README.txt"; Description: "View Setup Instructions"; Flags: postinstall shellexec skipifsilent unchecked
Filename: "{app}\POST_INSTALL_SETUP.bat"; Description: "Complete setup now (download AI models, ~5GB, 10-30 min)"; Flags: postinstall nowait skipifsilent

[Code]
function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
begin
  Result := True;

  // Check if Docker Desktop is installed
  if not RegKeyExists(HKEY_LOCAL_MACHINE, 'SOFTWARE\Docker Inc.\Docker\1.0') and
     not RegKeyExists(HKEY_CURRENT_USER, 'SOFTWARE\Docker Inc.\Docker\1.0') then
  begin
    if MsgBox('Docker Desktop is not installed on your system.' + #13#10 + #13#10 +
              'This application requires Docker Desktop to run.' + #13#10 + #13#10 +
              'Would you like to visit the Docker Desktop download page?' + #13#10 +
              '(You can install it after this setup completes)',
              mbConfirmation, MB_YESNO) = IDYES then
    begin
      ShellExec('open', 'https://www.docker.com/products/docker-desktop/', '', '', SW_SHOW, ewNoWait, ResultCode);
    end;

    MsgBox('Please install Docker Desktop before running the application.' + #13#10 + #13#10 +
           'The installer will continue, but the application will not work until Docker is installed.',
           mbInformation, MB_OK);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    // Create empty directories for data
    CreateDir(ExpandConstant('{app}\vector_db'));
    CreateDir(ExpandConstant('{app}\data'));
    CreateDir(ExpandConstant('{app}\logs'));
  end;
end;
