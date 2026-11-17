string GetTitle() { return "AheadSubs - Stop audio pre-read"; }
string GetVersion() { return "1"; }
string GetDesc() { return "Stop audio pre-read for the current PotPlayer window."; }
string GetLoginTitle() { return "AheadSubs - Stop audio pre-read"; }
string GetLoginDesc() { return "Click OK to stop audio pre-read for this window."; }
string GetUserText() { return "Optional"; }
string GetPasswordText() { return ""; }
array<string> GetSrcLangs() { array<string> languages = {""}; return languages; }
array<string> GetDstLangs() { array<string> languages = {"zh-CN"}; return languages; }
void ServerLogout() {}

void StopRelayAudio(any@ argument) {
    string encoded;
    if (argument !is null && argument.retrieve(encoded)) {
        HostExecuteProgram("@RELAY_PYTHONW@", "\"@RELAY_LAUNCHER@\" --pot-stop-file \"" + encoded + "\"");
    }
}

string ServerLogin(string User, string Pass) {
    string media = HostGetPlayingFileName();
    if (media.empty()) return "400 Open a local video first";
    HostCreateThread(StopRelayAudio, HostBase64Enc(media));
    return "200 OK";
}

string Translate(string Text, string &in SrcLang, string &in DstLang) { return Text; }
