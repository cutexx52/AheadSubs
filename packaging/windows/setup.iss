#ifndef IncludesCuda
  #define IncludesCuda "no"
#endif

[Setup]
AppId=LocalVideoSubtitleTranslator
AppName=Local Video Subtitle Translator
AppVersion={#ReleaseVersion}
DefaultDirName={localappdata}\Programs\Local Video Subtitle Translator
DefaultGroupName=Local Video Subtitle Translator
PrivilegesRequired=lowest
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
MinVersion=10.0.19045
Compression=lzma2/fast
LZMANumBlockThreads=2
SolidCompression=yes
WizardStyle=modern
OutputDir={#ReleaseDir}
OutputBaseFilename={#ArtifactName}-setup
UninstallDisplayIcon={app}\Local Video Subtitle Translator.exe
CloseApplications=yes
RestartApplications=no

[Files]
Source: "{#StageDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

#if IncludesCuda == "no"
[InstallDelete]
; These directories contain only vendor libraries staged by the CUDA package.
Type: filesandordirs; Name: "{app}\runtime\Lib\site-packages\nvidia\cublas"
Type: filesandordirs; Name: "{app}\runtime\Lib\site-packages\nvidia\cudnn"
Type: filesandordirs; Name: "{app}\runtime\Lib\site-packages\nvidia_cublas_cu12-12.8.4.1.dist-info"
Type: filesandordirs; Name: "{app}\runtime\Lib\site-packages\nvidia_cudnn_cu12-9.10.2.21.dist-info"
#endif

[Icons]
Name: "{group}\Local Video Subtitle Translator"; Filename: "{app}\Local Video Subtitle Translator.exe"; WorkingDir: "{app}"
Name: "{userdesktop}\Local Video Subtitle Translator"; Filename: "{app}\Local Video Subtitle Translator.exe"; Tasks: desktopicon

[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; Flags: unchecked

[Run]
Filename: "{app}\Local Video Subtitle Translator.exe"; Description: "Open Local Video Subtitle Translator"; Flags: nowait postinstall skipifsilent
