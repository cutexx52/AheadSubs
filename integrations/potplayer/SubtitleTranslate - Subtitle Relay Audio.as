string GetTitle() { return "Subtitle Relay (audio pre-read setup)"; }
string GetVersion() { return "1"; }
string GetDesc() { return "Open the audio pre-read controls for the current local video."; }
string GetLoginTitle() { return "Subtitle Relay audio pre-read"; }
string GetLoginDesc() { return "Click OK to open the controls. No account is needed."; }
string GetUserText() { return "Optional"; }
string GetPasswordText() { return ""; }
array<string> GetSrcLangs() { array<string> languages = {"en"}; return languages; }
array<string> GetDstLangs() { array<string> languages = {"zh-CN"}; return languages; }
void ServerLogout() {}

void OpenRelayAudioControls(any@ argument) {
    string encoded;
    if (argument !is null && argument.retrieve(encoded)) {
        HostExecuteProgram("@RELAY_PYTHONW@", "\"@RELAY_LAUNCHER@\" --pot-media-b64 \"" + encoded + "\"");
    }
}

string ServerLogin(string User, string Pass) {
    string media = HostGetPlayingFileName();
    if (media.empty()) return "400 Open a local video first";
    HostCreateThread(OpenRelayAudioControls, HostBase64Enc(media));
    return "200 OK";
}

string Translate(string Text, string &in SrcLang, string &in DstLang) { return ""; }
