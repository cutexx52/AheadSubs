#ifndef IncludesCuda
  #define IncludesCuda "no"
#endif

[Setup]
AppId=LocalVideoSubtitleTranslator
AppName=AheadSubs
AppVersion={#ReleaseVersion}
DefaultDirName={localappdata}\Programs\AheadSubs
DefaultGroupName=AheadSubs
UsePreviousGroup=no
AppMutex=Local\LocalVideoSubtitleTranslator.Settings
PrivilegesRequired=lowest
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
MinVersion=10.0.19045
Compression=lzma2/fast
LZMANumBlockThreads=2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\..\assets\aheadsubs.ico
OutputDir={#ReleaseDir}
OutputBaseFilename={#ArtifactName}-setup
UninstallDisplayIcon={app}\AheadSubs.exe
CloseApplications=yes
RestartApplications=no

[Files]
Source: "{#StageDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
Type: files; Name: "{userprograms}\Local Video Subtitle Translator\Local Video Subtitle Translator.lnk"
Type: dirifempty; Name: "{userprograms}\Local Video Subtitle Translator"
Type: files; Name: "{userdesktop}\Local Video Subtitle Translator.lnk"
Type: files; Name: "{app}\Local Video Subtitle Translator.exe"
Type: files; Name: "{app}\UI\LocalVideoSubtitleTranslator.exe"
#if IncludesCuda == "no"
; These directories contain only vendor libraries staged by the CUDA package.
Type: filesandordirs; Name: "{app}\runtime\Lib\site-packages\nvidia\cublas"
Type: filesandordirs; Name: "{app}\runtime\Lib\site-packages\nvidia\cudnn"
Type: filesandordirs; Name: "{app}\runtime\Lib\site-packages\nvidia_cublas_cu12-12.8.4.1.dist-info"
Type: filesandordirs; Name: "{app}\runtime\Lib\site-packages\nvidia_cudnn_cu12-9.10.2.21.dist-info"
#endif

[Icons]
Name: "{group}\AheadSubs"; Filename: "{app}\AheadSubs.exe"; WorkingDir: "{app}"
Name: "{userdesktop}\AheadSubs"; Filename: "{app}\AheadSubs.exe"; Tasks: desktopicon

[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; Flags: unchecked

[Run]
Filename: "{app}\AheadSubs.exe"; Description: "Open AheadSubs"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\runtime\python.exe"; Parameters: "-m subtitle_relay.desktop.bridge automation cli-remove"; WorkingDir: "{app}"; Flags: runhidden skipifdoesntexist; RunOnceId: "RemoveAheadSubsFromPath"
