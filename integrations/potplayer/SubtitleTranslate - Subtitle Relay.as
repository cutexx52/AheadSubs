string relay_url = "http://127.0.0.1:8769";
array<string> relay_languages = {
    "en", "ja", "ko", "zh-CN", "zh-TW", "fr", "de", "es", "ru", "pt"
};

string GetTitle() { return "AheadSubs (local service)"; }
string GetVersion() { return "1"; }
string GetDesc() { return "Translate existing subtitle lines using the running AheadSubs service."; }
string GetLoginTitle() { return "AheadSubs"; }
string GetLoginDesc() { return "Start AheadSubs in its Windows settings app. Default port: 8769."; }
string GetUserText() { return "Loopback server (optional)"; }
string GetPasswordText() { return ""; }
array<string> GetSrcLangs() { return relay_languages; }
array<string> GetDstLangs() { return relay_languages; }

string ServerLogin(string User, string Pass) {
    if (!User.empty()) {
        if (User.findFirst("http://127.0.0.1:") != 0) return "400 Use an IPv4 loopback URL";
        relay_url = User;
    }
    string health = HostUrlGetString(relay_url + "/v1/health", "SubtitleRelay/1");
    if (health.findFirst("subtitle-relay") < 0) return "503 Start AheadSubs first";
    return "200 OK";
}

void ServerLogout() {}

string Translate(string Text, string &in SrcLang, string &in DstLang) {
    string form = "source=" + HostUrlEncode(SrcLang) + "&target=" + HostUrlEncode(DstLang)
                + "&text=" + HostUrlEncode(Text);
    string response = HostUrlGetString(relay_url + "/v1/text", "SubtitleRelay/1",
                                      "Content-Type: application/x-subtitle-relay\r\n", form);
    JsonReader reader;
    JsonValue result;
    if (!reader.parse(response, result) || !result.isObject()) return "";
    JsonValue translated = result["translation"];
    if (!translated.isString()) return "";
    SrcLang = "UTF8";
    DstLang = "UTF8";
    return translated.asString();
}
