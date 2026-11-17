using System.IO;
using System.Net;
using System.Net.Http;
using System.Net.Http.Json;
using System.Security.Cryptography;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;

namespace LocalVideoSubtitleTranslator;

internal sealed record ReleasePackage(string Version, string Flavor)
{
    public bool IsSupported => ReleaseUpdates.ParseVersion(Version) is not null &&
        Flavor is "standard" or "cuda";
}

internal sealed record ReleaseAsset(Version Version, Uri Notes, Uri Download, long Size, byte[] Digest);

internal sealed partial class ReleaseUpdates(HttpClient client)
{
    private const string Repository = "https://github.com/cutexx52/AheadSubs";
    private const string LatestRelease = "https://api.github.com/repos/cutexx52/AheadSubs/releases/latest";

    private sealed record Release(
        [property: JsonPropertyName("tag_name")] string? Tag,
        bool Draft, bool Prerelease, Asset[]? Assets);

    private sealed record Asset(string? Name, string? State, long Size, string? Digest);

    [GeneratedRegex(@"\Av?(?<core>(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*))(?:-[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*)?\z")]
    private static partial Regex VersionFormat();

    [GeneratedRegex(@"\Asha256:[0-9a-fA-F]{64}\z")]
    private static partial Regex DigestFormat();

    internal static Version? ParseVersion(string? value)
    {
        var match = VersionFormat().Match(value ?? "");
        return match.Success && Version.TryParse(match.Groups["core"].Value, out var version) ? version : null;
    }

    public async Task<ReleaseAsset?> CheckAsync(ReleasePackage package, bool installed, CancellationToken token)
    {
        var current = ParseVersion(package.Version) ?? throw new InvalidDataException();
        using var request = new HttpRequestMessage(HttpMethod.Get, LatestRelease);
        request.Headers.UserAgent.ParseAdd("AheadSubs");
        request.Headers.Accept.ParseAdd("application/vnd.github+json");
        request.Headers.Add("X-GitHub-Api-Version", "2026-03-10");
        using var response = await client.SendAsync(request, token).ConfigureAwait(false);
        if (response.StatusCode == HttpStatusCode.NotFound)
            return null;
        response.EnsureSuccessStatusCode();
        var release = await response.Content.ReadFromJsonAsync<Release>(cancellationToken: token).ConfigureAwait(false)
            ?? throw new InvalidDataException();
        if (release.Draft || release.Prerelease || release.Tag?.Contains('-') == true)
            return null;
        var latest = ParseVersion(release.Tag) ?? throw new InvalidDataException();
        // A stable build supersedes a preview with the same major, minor and patch.
        if (latest < current || (latest == current && !package.Version.Contains('-')))
            return null;

        string flavorSuffix = package.Flavor == "cuda" ? "-cuda" : "";
        string packageSuffix = installed ? "-setup.exe" : "-portable.zip";
        string name = $"aheadsubs-v{latest}-windows-x64{flavorSuffix}{packageSuffix}";
        var asset = release.Assets?.SingleOrDefault(asset => asset.Name == name && asset.State == "uploaded");
        if (asset is null || asset.Size <= 0 || !DigestFormat().IsMatch(asset.Digest ?? ""))
            throw new InvalidDataException();
        return new(latest, new Uri($"{Repository}/releases/tag/{release.Tag}"),
            new Uri($"{Repository}/releases/download/{release.Tag}/{name}"), asset.Size,
            Convert.FromHexString(asset.Digest!["sha256:".Length..]));
    }

    public async Task DownloadAsync(ReleaseAsset asset, string path, CancellationToken token)
    {
        using var response = await client.GetAsync(asset.Download, HttpCompletionOption.ResponseHeadersRead, token)
            .ConfigureAwait(false);
        response.EnsureSuccessStatusCode();
        if (response.Content.Headers.ContentLength is long size && size != asset.Size)
            throw new InvalidDataException();

        using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        await using var source = await response.Content.ReadAsStreamAsync(token).ConfigureAwait(false);
        await using var output = new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.None, 81920, useAsync: true);
        var buffer = new byte[81920];
        long written = 0;
        int read;
        while ((read = await source.ReadAsync(buffer, token).ConfigureAwait(false)) != 0)
        {
            written += read;
            if (written > asset.Size)
                throw new InvalidDataException();
            hash.AppendData(buffer, 0, read);
            await output.WriteAsync(buffer.AsMemory(0, read), token).ConfigureAwait(false);
        }
        if (written != asset.Size || !CryptographicOperations.FixedTimeEquals(hash.GetHashAndReset(), asset.Digest))
            throw new InvalidDataException();
    }
}
