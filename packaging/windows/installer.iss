#define AppVersion "0.1.0"

[Setup]
AppName=Pax Dei Planner
AppVersion={#AppVersion}
DefaultDirName={autopf}\PaxDeiPlanner
DefaultGroupName=Pax Dei Planner
UninstallDisplayIcon={app}\PaxDeiPlanner.exe
OutputBaseFilename=PaxDeiPlanner_Setup
Compression=lzma
SolidCompression=yes

[Files]
Source: "..\..\dist\paxdei_planner_ui\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Pax Dei Planner"; Filename: "{app}\PaxDeiPlanner.exe"
Name: "{autodesktop}\Pax Dei Planner"; Filename: "{app}\PaxDeiPlanner.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"

[Run]
Filename: "{app}\PaxDeiPlanner.exe"; Description: "Launch Pax Dei Planner"; Flags: nowait postinstall skipifsilent
