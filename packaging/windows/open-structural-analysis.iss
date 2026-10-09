#ifndef AppVersion
#define AppVersion "2026.1"
#endif

#define AppName "Open Structural Analysis"
#define AppPublisher "Open Structural Analysis contributors"
#define AppExeName "open-structural-analysis.exe"

[Setup]
AppId={{7B4A4D7C-0F9A-4E7E-9D0D-202610000001}}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\Open Structural Analysis
DefaultGroupName={#AppName}
OutputDir=..\..\dist
OutputBaseFilename=OpenStructuralAnalysis-{#AppVersion}-Windows-x86_64-Setup
SetupIconFile=..\..\build\windows\openstructuralanalysis.ico
UninstallDisplayIcon={app}\{#AppExeName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\..\dist\open-structural-analysis\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\{#AppExeName}"

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Iniciar {#AppName}"; Flags: postinstall nowait skipifsilent
