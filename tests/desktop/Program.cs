using System.Net;
using System.Security.Cryptography;
using System.Text.Json;
using LocalVideoSubtitleTranslator;

byte[] bytes = [1, 2, 3, 4];
string digest = "sha256:" + Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
var stable = new ReleasePackage("0.9.0", "standard");
var cuda = stable with { Flavor = "cuda" };

object Asset(string name, string? hash, string state = "uploaded") => new
{
    name, size = bytes.Length, digest = hash, state,
    browser_download_url = "https://untrusted.invalid/installer.exe"
};

var standardSetup = Asset("aheadsubs-v0.10.0-windows-x64-setup.exe", digest);
var cudaSetup = Asset("aheadsubs-v0.10.0-windows-x64-cuda-setup.exe", digest);
var cudaZip = Asset("aheadsubs-v0.10.0-windows-x64-cuda-portable.zip", digest);
object[] assets = [standardSetup, cudaSetup, cudaZip];

async Task<ReleaseAsset?> Check(ReleasePackage package, bool installed = true, string tag = "v0.10.0",
    bool prerelease = false, bool draft = false, object[]? overrideAssets = null)
{
    using var client = new HttpClient(new StubHandler(request =>
    {
        Equal("https://api.github.com/repos/cutexx52/AheadSubs/releases/latest", request.RequestUri!.AbsoluteUri, "Endpoint");
        Equal(null, request.Headers.Authorization, "Public check needs no token");
        var release = new { tag_name = tag, draft, prerelease, assets = overrideAssets ?? assets };
        return new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent(JsonSerializer.Serialize(release)) };
    }));
    return await new ReleaseUpdates(client).CheckAsync(package, installed, CancellationToken.None);
}

var standardUpdate = await Check(stable) ?? throw new Exception("Missing newer standard installer");
Equal("/cutexx52/AheadSubs/releases/download/v0.10.0/aheadsubs-v0.10.0-windows-x64-setup.exe",
    standardUpdate.Download.AbsolutePath, "Standard installer");
Equal("github.com", standardUpdate.Download.Host, "Download origin");
Equal("https://github.com/cutexx52/AheadSubs/releases/tag/v0.10.0", standardUpdate.Notes.AbsoluteUri, "Release notes");
Equal("/cutexx52/AheadSubs/releases/download/v0.10.0/aheadsubs-v0.10.0-windows-x64-cuda-setup.exe",
    (await Check(cuda))!.Download.AbsolutePath, "CUDA installer");
Equal("/cutexx52/AheadSubs/releases/download/v0.10.0/aheadsubs-v0.10.0-windows-x64-cuda-portable.zip",
    (await Check(cuda, installed: false))!.Download.AbsolutePath, "CUDA portable");
Equal(null, await Check(stable with { Version = "0.10.0" }), "Already current");
Equal(null, await Check(stable with { Version = "1.0.0" }), "No downgrade");
Equal(new Version(0, 10, 0), (await Check(stable with { Version = "0.10.0-rc.2" }))?.Version, "Stable replaces preview");
Equal(null, await Check(stable, draft: true), "Draft ignored");
Equal(null, await Check(stable, prerelease: true), "Prerelease flag ignored");
Equal(null, await Check(stable, tag: "v0.10.0-rc.1"), "Preview tag ignored even without flag");
await Throws<InvalidDataException>(() => Check(stable, tag: "v0.10.0/../../other"));
await Throws<InvalidDataException>(() => Check(stable, overrideAssets: [cudaSetup]));
await Throws<InvalidDataException>(() => Check(stable, overrideAssets:
    [Asset("aheadsubs-v0.10.0-windows-x64-setup.exe", digest, state: "starter")]));
await Throws<InvalidDataException>(() => Check(stable, overrideAssets:
    [Asset("aheadsubs-v0.10.0-windows-x64-setup.exe", null)]));

using var noRelease = new HttpClient(new StubHandler(_ => new HttpResponseMessage(HttpStatusCode.NotFound)));
Equal(null, await new ReleaseUpdates(noRelease).CheckAsync(stable, true, CancellationToken.None), "No stable release");
using var rateLimit = new HttpClient(new StubHandler(_ => new HttpResponseMessage(HttpStatusCode.TooManyRequests)));
await Throws<HttpRequestException>(() => new ReleaseUpdates(rateLimit).CheckAsync(stable, true, CancellationToken.None));

var temp = Directory.CreateTempSubdirectory("aheadsubs-update-tests-");
try
{
    string Installer(string name) => Path.Combine(temp.FullName, name + ".exe");
    using var download = new HttpClient(new StubHandler(request =>
    {
        Equal(standardUpdate.Download, request.RequestUri, "Selected asset downloaded");
        return new HttpResponseMessage(HttpStatusCode.OK) { Content = new ByteArrayContent(bytes) };
    }));
    var updater = new ReleaseUpdates(download);
    await updater.DownloadAsync(standardUpdate, Installer("good"), CancellationToken.None);
    Equal(Convert.ToHexString(bytes), Convert.ToHexString(File.ReadAllBytes(Installer("good"))), "Verified bytes");
    await Throws<InvalidDataException>(() => updater.DownloadAsync(
        standardUpdate with { Digest = new byte[32] }, Installer("wrong-hash"), CancellationToken.None));
    await Throws<InvalidDataException>(() => updater.DownloadAsync(
        standardUpdate with { Size = bytes.Length + 1 }, Installer("wrong-size"), CancellationToken.None));
    await Throws<OperationCanceledException>(() => updater.DownloadAsync(
        standardUpdate, Installer("canceled"), new CancellationToken(canceled: true)));
}
finally
{
    temp.Delete(recursive: true);
}
Console.WriteLine("Windows update checks passed.");

static void Equal<T>(T expected, T actual, string context)
{
    if (!EqualityComparer<T>.Default.Equals(expected, actual))
        throw new Exception($"{context}: expected {expected}, got {actual}.");
}

static async Task Throws<T>(Func<Task> action) where T : Exception
{
    try { await action(); }
    catch (T) { return; }
    throw new Exception($"Expected {typeof(T).Name}.");
}

sealed class StubHandler(Func<HttpRequestMessage, HttpResponseMessage> response) : HttpMessageHandler
{
    protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        return Task.FromResult(response(request));
    }
}
