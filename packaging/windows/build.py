"""Build and smoke-test isolated Windows x64 ZIP and per-user installer artifacts."""
import argparse
from pathlib import Path
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile


SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parents[1]
APP = "AheadSubs"
SLUG = "aheadsubs"
FFMPEG_RELEASE = "https://github.com/FFmpeg-Builds/FFmpeg-Builds/releases/tag/autobuild-2026-10-31-12-59"
FFMPEG_URL = FFMPEG_RELEASE.replace("/tag/", "/download/") + "/ffmpeg-n8.1.3-27-g8dca1586f4-win64-lgpl-shared-8.1.zip"
FFMPEG_SHA256 = "5cef7bc48e513f3cee7c881e8b2999d835541edb1846c3e89443a67f8f8556ab"
INNO_URL = "https://github.com/jrsoftware/issrc/releases/download/is-7_1_1/innosetup-7.1.1-x64.exe"
INNO_SHA256 = "8a5a6711c3766a6e5fb74f280ba0e3551e719ce94538d901fdbd1f8f9920b3f0"
CUDA_PACKAGES = ["nvidia-cublas-cu12==12.8.4.1", "nvidia-cudnn-cu12==9.10.2.21"]
WPF_PROJECT = ROOT / "desktop" / "LocalVideoSubtitleTranslator.csproj"


def run(*arguments, **kwargs):
    subprocess.run([str(value) for value in arguments], check=True, **kwargs)


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verified_download(url, digest, directory):
    directory.mkdir(parents=True, exist_ok=True)
    result = directory / url.rsplit("/", 1)[-1]
    if result.is_file() and sha256(result) == digest:
        return result
    with tempfile.TemporaryDirectory(dir=directory) as temporary:
        staged = Path(temporary) / result.name
        # Use Windows curl so the tool uses the platform trust store and proxy settings.
        run("curl.exe", "--fail", "--silent", "--show-error", "--location", "--retry", "2",
            "--max-time", "240", "--output", staged, url)
        if sha256(staged) != digest:
            raise ValueError(f"Digest mismatch for {staged.name}")
        staged.replace(result)
    return result


def stage_python(stage, cuda):
    base = Path(sys.base_prefix)
    runtime = stage / "runtime"
    runtime.mkdir()
    for exe in ("python.exe", "pythonw.exe", "python3.dll", "python311.dll", "LICENSE.txt"):
        shutil.copy2(base / exe, runtime)
    for path in base.glob("vcruntime*.dll"):
        shutil.copy2(path, runtime)
    for folder in ("DLLs", "Lib", "tcl"):
        shutil.copytree(base / folder, runtime / folder,
                        ignore=shutil.ignore_patterns("__pycache__", "site-packages", "test", "tests", "ensurepip", "idlelib"))
    target = runtime / "Lib" / "site-packages"
    run(sys.executable, "-m", "pip", "--disable-pip-version-check", "install", "--quiet", "--no-deps",
        "--only-binary=:all:", "--no-compile", "--target", target, "-r", SCRIPTS / "requirements.lock",
        *(CUDA_PACKAGES if cuda else []))
    shutil.copy2(SCRIPTS / "sitecustomize.py", runtime / "Lib" / "sitecustomize.py")


def private_runtime(downloads, cuda):
    runtime_inputs = (CUDA_PACKAGES if cuda else [], sys.version, sha256(Path(sys.base_prefix) / "python311.dll"))
    fingerprint = hashlib.sha256(repr(runtime_inputs).encode())
    for source in (Path(__file__), SCRIPTS / "requirements.lock", SCRIPTS / "sitecustomize.py"):
        fingerprint.update(source.read_bytes())
    downloads.mkdir(parents=True, exist_ok=True)
    cached = downloads / ("python-runtime-" + fingerprint.hexdigest()[:16])
    if not cached.is_dir():
        with tempfile.TemporaryDirectory(prefix="python-runtime-build-", dir=downloads) as directory:
            scratch = Path(directory)
            stage_python(scratch, cuda)
            try:
                (scratch / "runtime").replace(cached)
            except OSError:
                if not cached.is_dir():
                    raise
    return cached


def stage_ffmpeg(stage, downloads):
    filename = verified_download(FFMPEG_URL, FFMPEG_SHA256, downloads)
    binary = stage / "bin"
    notices = stage / "notices" / "ffmpeg"
    binary.mkdir()
    notices.mkdir(parents=True)
    with zipfile.ZipFile(filename) as archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            parts = member.filename.split("/")
            name = parts[-1]
            if len(parts) >= 3 and parts[-2] == "bin":
                if not (name.lower().endswith(".dll") or name.lower() in {"ffmpeg.exe", "ffprobe.exe"}):
                    continue
                output = binary / name
            elif len(parts) == 2 and name.lower().startswith(("license", "copying", "readme")):
                output = notices / name
            else:
                continue
            with archive.open(member) as source, output.open("wb") as destination:
                shutil.copyfileobj(source, destination)
    (notices / "SOURCE.txt").write_text(
        f"FFmpeg LGPL shared binaries from {FFMPEG_RELEASE}\n"
        f"Binary archive: {FFMPEG_URL}\nSHA-256: {FFMPEG_SHA256}\n"
        "FFmpeg source: https://github.com/FFmpeg/FFmpeg/tree/8dca1586f4\n"
        "Build scripts: https://github.com/FFmpeg-Builds/FFmpeg-Builds/tree/autobuild-2026-10-31-12-59\n",
        encoding="utf-8",
    )
    if not ((binary / "ffmpeg.exe").is_file() and (binary / "ffprobe.exe").is_file()):
        raise RuntimeError("Unexpected upstream FFmpeg archive layout")


def stage_app(stage, dotnet, version, cuda):
    for directory, extensions in {"subtitle_relay": {".py"}, "integrations": {".as", ".lua"}, "docs": {".md"}}.items():
        for source in (ROOT / directory).rglob("*"):
            if source.is_file() and source.suffix in extensions:
                destination = stage / source.relative_to(ROOT)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
    for filename in ("Subtitle Relay.pyw", "README.md", "LICENSE", "NOTICE"):
        source = ROOT / filename
        if source.is_file():
            shutil.copy2(source, stage)
    compiler = Path(os.environ["SystemRoot"]) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
    run(compiler, "/nologo", "/target:winexe", "/platform:x64", "/reference:System.Windows.Forms.dll",
        f"/win32icon:{ROOT / 'assets' / 'aheadsubs.ico'}", f"/out:{stage / (APP + '.exe')}", SCRIPTS / "launcher.cs")
    if dotnet:
        run(dotnet, "publish", WPF_PROJECT, "-c", "Release", "-r", "win-x64", "--self-contained", "true",
            "-p:DebugType=None", "-p:DebugSymbols=false", "-o", stage / "UI", cwd=ROOT)
        if not (stage / "UI" / "AheadSubs.exe").is_file():
            raise RuntimeError("Native desktop entry point is absent from publish output")
        (stage / "UI" / "aheadsubs-release.json").write_text(
            json.dumps({"Version": version, "Flavor": "cuda" if cuda else "standard"}),
            encoding="utf-8",
        )


def smoke_test(stage, cuda):
    # The tested process must depend on the staged package, not the builder's PATH or HOME.
    env = dict(os.environ, PATH=str(Path(os.environ["SystemRoot"]) / "System32"),
               PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1")
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    python = stage / "runtime" / "python.exe"
    code = (
        "from pathlib import Path; import shutil, tkinter, _tkinter, _ssl, sqlite3, "
        "av, ctranslate2, kaldi_native_fbank, onnxruntime, openai, jwt, psutil, pystray, subtitle_relay; "
        "from subtitle_relay.inference.chatgpt_auth import _dpapi; "
        "assert 'RS256' in jwt.algorithms.get_default_algorithms() and _dpapi(_dpapi(b'check'), decrypt=True) == b'check'; "
        "root=Path(__import__('sys').base_prefix).parent; "
        "assert Path(shutil.which('ffmpeg')).parent == root / 'bin'; "
        "assert Path(subtitle_relay.__file__).resolve().is_relative_to(root); "
        f"assert (root / 'runtime/Lib/site-packages/nvidia/cublas/bin').is_dir() == {cuda!r}; "
        "assert tkinter.Tcl().eval('info patchlevel')"
    )
    run(python, "-c", code, env=env, cwd=stage.parent)
    run(python, "-m", "subtitle_relay", "--help", env=env, cwd=stage.parent)
    with tempfile.TemporaryDirectory(dir=stage.parent) as data:
        reply = subprocess.check_output([python, "-m", "subtitle_relay.desktop.bridge", "status"],
                                        env={**env, "LOCALAPPDATA": data}, cwd=stage.parent)
        state = json.loads(reply)
        if not state.get("ok") or not state.get("ffmpeg_detected") or "credentials" not in state:
            raise RuntimeError("Bundled desktop control bridge failed its smoke check")
    for exe in ("ffmpeg.exe", "ffprobe.exe"):
        run(stage / "bin" / exe, "-version", env=env, cwd=stage.parent, stdout=subprocess.DEVNULL)


def smoke_installer(installer, directory, cuda, version, native):
    import winreg

    uninstall_key = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\LocalVideoSubtitleTranslator_is1"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, uninstall_key, access=winreg.KEY_READ | winreg.KEY_WOW64_64KEY):
            raise RuntimeError("Installer smoke requires a user profile without an existing app installation")
    except FileNotFoundError:
        pass
    target = directory / "test installation"
    silent = ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART")
    try:
        run(installer, *silent, "/NOICONS", f"/DIR={target}")
        smoke_test(target, cuda)
        if native:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, uninstall_key, access=winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                location, _ = winreg.QueryValueEx(key, "InstallLocation")
            if Path(location).resolve() != target.resolve():
                raise RuntimeError("The install location must match the update detection path")
            metadata = json.loads((target / "UI" / "aheadsubs-release.json").read_text(encoding="utf-8"))
            if metadata != {"Version": version, "Flavor": "cuda" if cuda else "standard"}:
                raise RuntimeError("Installed update metadata does not match the bundle")
    finally:
        uninstaller = target / "unins000.exe"
        if uninstaller.is_file():
            run(uninstaller, *silent)


def find_iscc(downloads):
    path = shutil.which("ISCC.exe")
    if path:
        return Path(path)
    inno = downloads / "inno-7.1.1"
    executable = inno / "ISCC.exe"
    if not executable.is_file():
        installer = verified_download(INNO_URL, INNO_SHA256, downloads)
        run(installer, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/NOICONS", "/CURRENTUSER", f"/DIR={inno}")
    if not executable.is_file():
        raise RuntimeError("Inno Setup did not provide ISCC.exe; supply --iscc explicitly")
    return executable


def build(args):
    if sys.platform != "win32" or platform.machine().upper() != "AMD64" or sys.version_info[:2] != (3, 11):
        raise SystemExit("Building this distribution requires Windows x64 and CPython 3.11 with Tcl/Tk")
    args.version = args.version.removeprefix("v")
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*)?", args.version):
        raise SystemExit("Use a version such as 0.1.0 or 0.1.0-rc.1")
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    downloads = args.download_cache.resolve()
    name = f"{SLUG}-v{args.version}-windows-x64" + ("-cuda" if args.cuda else "")
    dotnet = (args.dotnet or "dotnet") if args.native else None
    with tempfile.TemporaryDirectory(prefix="build-", dir=out) as temporary:
        work = Path(temporary)
        stage = work / name
        stage.mkdir()
        shutil.copytree(private_runtime(downloads, args.cuda), stage / "runtime")
        stage_ffmpeg(stage, downloads)
        stage_app(stage, dotnet, args.version, args.cuda)
        smoke_test(stage, args.cuda)
        archive = work / (name + "-portable.zip")
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=3) as zipped:
            for path in sorted(stage.rglob("*")):
                if path.is_file():
                    zipped.write(path, path.relative_to(work))
        files = [archive]
        if not args.portable_only:
            iscc = args.iscc or find_iscc(downloads)
            run(iscc, "/Q", f"/DStageDir={stage}", f"/DReleaseDir={work}", f"/DReleaseVersion={args.version}",
                f"/DArtifactName={name}", "/DIncludesCuda=yes" if args.cuda else "/DIncludesCuda=no",
                SCRIPTS / "setup.iss")
            installer = work / (name + "-setup.exe")
            if args.verify_install:
                smoke_installer(installer, work, args.cuda, args.version, args.native)
            files.append(installer)
        checksums = work / (name + "-SHA256.txt")
        checksums.write_text(
            "".join(f"{sha256(file)}  {file.name}\n" for file in files), encoding="ascii")
        for file in (*files, checksums):
            file.replace(out / file.name)
    print("Windows release artifacts:")
    for file in files:
        result = out / file.name
        print(f"  {result} ({result.stat().st_size / 2**20:.1f} MiB)")


if __name__ == "__main__":
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default=os.getenv("SUBTITLE_RELAY_RELEASE_VERSION") or project["version"])
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument("--download-cache", type=Path, default=ROOT / ".relay" / "packaging-tools")
    parser.add_argument("--cuda", action="store_true", help="include optional NVIDIA CUDA wheel libraries")
    parser.add_argument("--native", action="store_true", help="include the self-contained WPF desktop")
    parser.add_argument("--dotnet", type=Path, help="path to the .NET 10 SDK dotnet.exe")
    parser.add_argument("--iscc", type=Path, help="path to Inno Setup compiler ISCC.exe")
    parser.add_argument("--portable-only", action="store_true")
    parser.add_argument("--verify-install", action="store_true", help="install and remove a test copy in a clean profile")
    build(parser.parse_args())
