[Setup]
AppName=Language Flag Pop-Up
AppVersion=1.8
DefaultDirName={localappdata}\Programs\LanguageFlagPopUp
DefaultGroupName=LanguageFlagPopUp
PrivilegesRequired=lowest
OutputDir=.
OutputBaseFilename=LanguageFlagPopUp_Setup
Compression=lzma
SolidCompression=yes
UninstallDisplayIcon={app}\language_flag_popup.exe
UninstallDisplayName=Language Flag Pop-Up
DisableProgramGroupPage=no
Uninstallable=yes

[Files]
Source: "dist\language_flag_popup.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Language Flag Pop-Up"; Filename: "{app}\language_flag_popup.exe"; IconFilename: "{app}\language_flag_popup.exe"
Name: "{userstartup}\Language Flag Pop-Up"; Filename: "{app}\language_flag_popup.exe"; Tasks: autostart

[Tasks]
Name: "autostart"; Description: "Run automatically when Windows starts"; GroupDescription: "Startup options:"

[Run]
Filename: "{app}\language_flag_popup.exe"; Description: "Run Language Flag Pop-Up now"; Flags: nowait postinstall skipifsilent
