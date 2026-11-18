"""Build and smoke-test isolated Windows x64 ZIP and per-user installer artifacts."""
import argparse
import base64
import csv
from pathlib import Path
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile


SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parents[1]
APP = "AheadSubs"
SLUG = "aheadsubs"
FFMPEG_REVISION = "8dca1586f468bfcbb78ae3ed618af1361d9f140a"
FFMPEG_TARBALL = f"ffmpeg-{FFMPEG_REVISION}.tar.gz"
FFMPEG_URL = f"https://codeload.github.com/FFmpeg/FFmpeg/tar.gz/{FFMPEG_REVISION}"
FFMPEG_SHA256 = "5ce832c43ca0a336c747db9dcd448655c64c25e33cb9868e1cc5b24abb04dbaa"
FFMPEG_RECIPE = SCRIPTS / "build-ffmpeg.sh"
FFMPEG_BUILD_GUIDE = SCRIPTS / "ffmpeg-source.txt"
FFMPEG_NOTICES = ("COPYING.LGPLv3", "COPYING.GPLv3", "CREDITS")
WINPTHREADS_VERSION = "14.0.0.r598.ge3d18511f-1"
WINPTHREADS_URL = f"https://mirror.msys2.org/mingw/sources/mingw-w64-winpthreads-{WINPTHREADS_VERSION}.src.tar.zst"
WINPTHREADS_SHA256 = "1da3dad4f6916d0c23e8fe76c38ed79946fb32078f94047c0475229b8112a1db"
WINPTHREADS_BINARY_URL = ("https://repo.msys2.org/mingw/ucrt64/"
                         f"mingw-w64-ucrt-x86_64-libwinpthread-{WINPTHREADS_VERSION}-any.pkg.tar.zst")
WINPTHREADS_BINARY_SHA256 = "c35d6be83d141c8cfbb61f1637dd4b53aac8f5562d766aa26d0741c40bad4e4d"
WHISPER_AUDIO_SHA256 = "60a1d8638f718cbf6d245aed3e5a5aa61c1f822a0b0fe9b48a7c928d47c23909"
CTRANSLATE2_CUDNN_SHA256 = "9edbcdff73b0af070eb160b2ce66e59feca04aa017351d8eedcc5e8e149967d2"
INTEL_OMP_SHA256 = "982233366b0afcda1e0f55a0b134097e35b779613f54ddb69e685e6cd06b755f"
INTEL_OMP_WHEEL = "intel_openmp-2025.3.0-py2.py3-none-win_amd64.whl"
INTEL_OMP_URL = f"https://files.pythonhosted.org/packages/79/69/05addedd727061b61a85b4fd989754edb628b5be1cd5d161727f98cf4d86/{INTEL_OMP_WHEEL}"
INTEL_OMP_WHEEL_SHA256 = "8ff899d01a41b92ffe0e618b221ea633127d16df726086082d381c431c31339d"
LICENSE_FILES = (
    ("ctranslate2", "4.9.0", "LICENSE", "OpenNMT/CTranslate2/a22ba1c63ee35d1a0d25db149aa2a66d36a6a732",
     "54aa79d9fe3c09e67a16dcd95b9e88676405a6ec174efda31036983cf7672ecb"),
    ("onednn", "3.1.1", "LICENSE", "uxlfoundation/oneDNN/64f6bcbcbab628e96f33a62c3e975f8535a7bde4",
     "dd12452e1ae11e3282271aa5895d8175296b83e936a027209f9399d26a407d0f"),
    ("onednn", "3.1.1", "THIRD-PARTY-PROGRAMS", "uxlfoundation/oneDNN/64f6bcbcbab628e96f33a62c3e975f8535a7bde4",
     "9117585dfc6b5cd0fafc063312f28a86ec82eb97bf68316dcefcaaa7fc11428e"),
    ("silero-vad", "v6", "LICENSE", "snakers4/silero-vad/fba061dc5559f696e62171e9a0741782b0fdc23c",
     "2e63e9a38b6e8fc0c7bc37ce174caca1862870856c6daf5697cfb785e925520b"),
)
INNO_URL = "https://github.com/jrsoftware/issrc/releases/download/is-7_1_1/innosetup-7.1.1-x64.exe"
INNO_SHA256 = "8a5a6711c3766a6e5fb74f280ba0e3551e719ce94538d901fdbd1f8f9920b3f0"
CUDA_PACKAGES = ["nvidia-cublas-cu12==12.8.4.1", "nvidia-cudnn-cu12==9.10.2.21"]
WPF_PROJECT = ROOT / "desktop" / "AheadSubs.csproj"


def run(*arguments, **kwargs):
    subprocess.run([str(value) for value in arguments], check=True, **kwargs)


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verified_download(url, digest, directory, *, filename=None, curl="curl.exe"):
    directory.mkdir(parents=True, exist_ok=True)
    result = directory / (filename or url.rsplit("/", 1)[-1])
    if result.is_file() and sha256(result) == digest:
        return result
    with tempfile.TemporaryDirectory(dir=directory) as temporary:
        staged = Path(temporary) / result.name
        run(curl, "--fail", "--silent", "--show-error", "--location", "--retry", "2",
            "--max-time", "240", "--output", staged, url)
        if sha256(staged) != digest:
            raise ValueError(f"Digest mismatch for {staged.name}")
        staged.replace(result)
    return result


def make_pyav_optional(target):
    # Keep the upstream decoder available when PyAV is installed. The packaged
    # app passes PCM arrays and ships the MIT-licensed upstream code with lazy imports.
    audio = target / "faster_whisper/audio.py"
    if sha256(audio) != WHISPER_AUDIO_SHA256:
        raise RuntimeError("Review the Windows faster-whisper adaptation for this wheel")
    source = audio.read_bytes().replace(b"\nimport av\n", b"\n")
    for line in (b"    resampler = av.audio", b"    iterator = iter(frames)", b"    fifo = av.audio"):
        source = source.replace(line, b"    import av\n\n" + line)
    audio.write_bytes(source)
    record, = target.glob("faster_whisper-*.dist-info/RECORD")
    with record.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.reader(stream))
    entry, = (row for row in rows if row[0] == "faster_whisper/audio.py")
    digest = base64.urlsafe_b64encode(hashlib.sha256(source).digest()).decode().rstrip("=")
    entry[1:] = [f"sha256={digest}", str(len(source))]
    with record.open("w", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerows(rows)


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
    make_pyav_optional(target)
    # The upstream wheel is compiled with WITH_CUDNN=OFF. CUDA bundles carry
    # the complete NVIDIA wheel in its own directory, including this DLL.
    duplicate_cudnn = target / "ctranslate2/cudnn64_9.dll"
    if sha256(duplicate_cudnn) != CTRANSLATE2_CUDNN_SHA256:
        raise RuntimeError("Review the CTranslate2 native libraries for this wheel")
    duplicate_cudnn.unlink()
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


def private_ffmpeg(source, downloads, msys2):
    bash = msys2 / "usr/bin/bash.exe"
    if not bash.is_file():
        raise RuntimeError("Install the MSYS2 UCRT64 build tools or specify --msys2")
    env = dict(os.environ, MSYSTEM="UCRT64", CHERE_INVOKING="1", MSYS2_PATH_TYPE="minimal")
    packages = "pacman -Q mingw-w64-ucrt-x86_64-{gcc,crt,headers,binutils,nasm,libwinpthread} make"
    tools = subprocess.check_output([bash, "--login", "-c", packages], env=env)
    fingerprint = hashlib.sha256(FFMPEG_SHA256.encode() + FFMPEG_RECIPE.read_bytes() + tools).hexdigest()
    cached = downloads / f"ffmpeg-win64-{fingerprint[:16]}"
    if not cached.is_dir():
        with tempfile.TemporaryDirectory(prefix="ffmpeg-build-", dir=downloads) as temporary:
            work = Path(temporary)
            tree = work / "source"
            tree.mkdir()
            output = work / "install"
            run(bash, "--login", FFMPEG_RECIPE.as_posix(), source.as_posix(), output.as_posix(),
                min(os.cpu_count() or 2, 12), env=env, cwd=tree)
            (output / "toolchain.txt").write_bytes(tools)
            try:
                output.replace(cached)
            except OSError:
                if not cached.is_dir():
                    raise
    return cached


def stage_ffmpeg(stage, downloads, msys2, companion):
    source = verified_download(FFMPEG_URL, FFMPEG_SHA256, downloads, filename=FFMPEG_TARBALL)
    build = private_ffmpeg(source, downloads, msys2)
    curl = msys2 / "usr/bin/curl.exe"
    threads_source = verified_download(WINPTHREADS_URL, WINPTHREADS_SHA256, downloads, curl=curl)
    threads_binary = verified_download(WINPTHREADS_BINARY_URL, WINPTHREADS_BINARY_SHA256, downloads, curl=curl)
    binary = stage / "bin"
    notices = stage / "notices" / "ffmpeg"
    binary.mkdir()
    notices.mkdir(parents=True)
    built_bin = build / "aheadsubs-ffmpeg/bin"
    for path in (*built_bin.glob("*.dll"), *(built_bin / exe for exe in ("ffmpeg.exe", "ffprobe.exe"))):
        shutil.copy2(path, binary)
    # UCRT64 supplies the imported POSIX clocks. Bundle the verified DLL and
    # corresponding source together, independently of the SDK's installed copy.
    threads_notice = notices / "libwinpthread"
    threads_notice.mkdir()
    windows_tar = Path(os.environ["SystemRoot"]) / "System32/tar.exe"
    for member, destination in (("ucrt64/bin/libwinpthread-1.dll", binary / "libwinpthread-1.dll"),
                                ("ucrt64/share/licenses/libwinpthread/COPYING", threads_notice / "COPYING")):
        destination.write_bytes(subprocess.check_output([windows_tar, "-xOf", threads_binary, member]))
    licenses = msys2 / "ucrt64/share/licenses"
    for name in ("libgcc", "crt"):
        shutil.copytree(licenses / name, notices / name)
    shutil.copy2(build / "toolchain.txt", notices)
    shutil.copy2(FFMPEG_BUILD_GUIDE, notices / "README.txt")
    with tarfile.open(source) as archive:
        for name in FFMPEG_NOTICES:
            with archive.extractfile(f"FFmpeg-{FFMPEG_REVISION}/{name}") as contents:
                (notices / name).write_bytes(contents.read())
    (notices / "SOURCE.txt").write_text(
        f"FFmpeg {FFMPEG_REVISION}, licensed under LGPL v3 or later.\n"
        f"Corresponding source and build script: {companion.name}\n"
        f"Upstream source archive: {FFMPEG_URL}\nSHA-256: {FFMPEG_SHA256}\n"
        f"winpthreads binary package: {WINPTHREADS_BINARY_URL}\nSHA-256: {WINPTHREADS_BINARY_SHA256}\n"
        f"winpthreads source package: {WINPTHREADS_URL}\nSHA-256: {WINPTHREADS_SHA256}\n",
        encoding="utf-8",
    )
    with zipfile.ZipFile(companion, "w") as archive:
        for path, name in ((source, source.name), (threads_source, threads_source.name),
                           (FFMPEG_RECIPE, FFMPEG_RECIPE.name), (FFMPEG_BUILD_GUIDE, "README.txt"),
                           *((notices / name, name) for name in FFMPEG_NOTICES),
                           (notices / "libwinpthread/COPYING", "libwinpthread/COPYING")):
            with path.open("rb") as stream, archive.open(zipfile.ZipInfo(name), "w") as member:
                shutil.copyfileobj(stream, member)


def stage_inference_notices(stage, downloads):
    notices = stage / "notices"
    for project, version, name, upstream, digest in LICENSE_FILES:
        url = f"https://raw.githubusercontent.com/{upstream}/{name}"
        license_file = verified_download(url, digest, downloads, filename=f"{project}-{version}-{name}.txt")
        destination = notices / project
        destination.mkdir(exist_ok=True)
        shutil.copy2(license_file, destination / f"{name}.txt")

    dll = stage / "runtime/Lib/site-packages/ctranslate2/libiomp5md.dll"
    if sha256(dll) != INTEL_OMP_SHA256:
        raise RuntimeError("Review the Intel OpenMP notices for this CTranslate2 wheel")
    wheel = verified_download(INTEL_OMP_URL, INTEL_OMP_WHEEL_SHA256, downloads)
    destination = notices / "intel-openmp-2025.3.0"
    destination.mkdir()
    with zipfile.ZipFile(wheel) as archive:
        for entry in ("intel_openmp-2025.3.0.dist-info/LICENSE.txt",
                      "intel_openmp-2025.3.0.data/data/share/doc/compiler/licensing/openmp/third-party-programs.txt"):
            (destination / Path(entry).name).write_bytes(archive.read(entry))


def stage_dotnet_notices(stage):
    config = json.loads((stage / "UI/AheadSubs.runtimeconfig.json").read_text(encoding="utf-8"))
    assets = json.loads((WPF_PROJECT.parent / "obj/project.assets.json").read_text(encoding="utf-8"))
    for framework in config["runtimeOptions"]["includedFrameworks"]:
        name, version = framework["name"], framework["version"]
        relative = Path(f"{name.lower()}.runtime.win-x64") / version
        package = next((Path(folder) / relative for folder in assets["packageFolders"]
                        if (Path(folder) / relative).is_dir()), None)
        if package is None:
            raise RuntimeError(f"Could not locate the published runtime pack for {name} {version}")
        files = {file.name.upper(): file for file in package.iterdir() if file.is_file()}
        license_file = files.get("LICENSE.TXT") or files.get("LICENSE")
        if license_file is None:
            raise RuntimeError(f"Missing runtime license for {name} {version}")
        destination = stage / "notices" / f"{name}-{version}"
        destination.mkdir(parents=True)
        shutil.copy2(license_file, destination / "LICENSE.txt")
        if "THIRD-PARTY-NOTICES.TXT" in files:
            shutil.copy2(files["THIRD-PARTY-NOTICES.TXT"], destination)


def stage_app(stage, dotnet, version, cuda):
    for directory, extensions in {"aheadsubs": {".py"}, "subtitle_relay": {".py"},
                                  "integrations": {".as", ".lua"}, "docs": {".md"}}.items():
        for source in (ROOT / directory).rglob("*"):
            if source.is_file() and source.suffix in extensions:
                destination = stage / source.relative_to(ROOT)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
    for filename in ("AheadSubs.pyw", "Subtitle Relay.pyw", "README.md", "LICENSE", "NOTICE"):
        source = ROOT / filename
        if source.is_file():
            shutil.copy2(source, stage)
    compiler = Path(os.environ["SystemRoot"]) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
    run(compiler, "/nologo", "/target:winexe", "/platform:x64", "/reference:System.Windows.Forms.dll",
        f"/win32icon:{ROOT / 'assets' / 'aheadsubs.ico'}", f"/out:{stage / (APP + '.exe')}", SCRIPTS / "launcher.cs")
    (stage / "cli").mkdir()
    run(compiler, "/nologo", "/target:exe", "/platform:x64", f"/out:{stage / 'cli' / 'aheadsubs.exe'}",
        SCRIPTS / "cli-launcher.cs")
    if dotnet:
        run(dotnet, "publish", WPF_PROJECT, "-c", "Release", "-r", "win-x64", "--self-contained", "true",
            "-p:DebugType=None", "-p:DebugSymbols=false", "-o", stage / "UI", cwd=ROOT)
        if not (stage / "UI" / "AheadSubs.exe").is_file():
            raise RuntimeError("Native desktop entry point is absent from publish output")
        stage_dotnet_notices(stage)
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
    site_packages = stage / "runtime/Lib/site-packages"
    if any(site_packages.glob("av-*.dist-info")) or (site_packages / "av.libs").exists():
        raise RuntimeError("Unexpected PyAV files in the Windows payload")
    if (site_packages / "ctranslate2/cudnn64_9.dll").exists():
        raise RuntimeError("Unexpected CTranslate2 copy of cuDNN in the Windows payload")
    ffmpeg = stage / "bin/ffmpeg.exe"
    license_info = subprocess.check_output([ffmpeg, "-L"], env=env, stderr=subprocess.STDOUT, text=True)
    if ("GNU Lesser General Public License" not in license_info
            or any(flag in license_info for flag in ("--enable-gpl", "--enable-nonfree", "--enable-libx264", "--enable-libx265"))):
        raise RuntimeError("The bundled FFmpeg build must use the expected LGPL configuration")
    code = (
        "from pathlib import Path; import shutil, tkinter, _tkinter, _ssl, sqlite3, "
        "ctranslate2, faster_whisper, kaldi_native_fbank, onnxruntime, openai, jwt, psutil, pystray, aheadsubs; "
        "from importlib.util import find_spec; from faster_whisper.vad import get_vad_model; "
        "assert find_spec('av') is None and get_vad_model(); "
        "from aheadsubs.inference.chatgpt_auth import _dpapi; "
        "assert 'RS256' in jwt.algorithms.get_default_algorithms() and _dpapi(_dpapi(b'check'), decrypt=True) == b'check'; "
        "root=Path(__import__('sys').base_prefix).parent; "
        "assert Path(shutil.which('ffmpeg')).parent == root / 'bin'; "
        "assert Path(aheadsubs.__file__).resolve().is_relative_to(root); "
        f"assert (root / 'runtime/Lib/site-packages/nvidia/cublas/bin').is_dir() == {cuda!r}; "
        "assert tkinter.Tcl().eval('info patchlevel')"
    )
    run(python, "-c", code, env=env, cwd=stage.parent)
    run(python, "-m", "aheadsubs", "--help", env=env, cwd=stage.parent)
    run(python, "-m", "subtitle_relay", "--help", env=env, cwd=stage.parent)
    run(stage / "cli" / "aheadsubs.exe", "--help", env=env, cwd=stage.parent)
    with tempfile.TemporaryDirectory(dir=stage.parent) as data:
        env["LOCALAPPDATA"] = data
        reply = subprocess.check_output([python, "-m", "aheadsubs.desktop.bridge", "status"],
                                        env=env, cwd=stage.parent)
        state = json.loads(reply)
        if not state.get("ok") or not state.get("ffmpeg_detected") or "credentials" not in state:
            raise RuntimeError("Bundled desktop control bridge failed its smoke check")
        reply = subprocess.check_output([python, "-m", "subtitle_relay.desktop.bridge", "status"],
                                        env=env, cwd=stage.parent)
        if not json.loads(reply).get("ok"):
            raise RuntimeError("Legacy desktop control bridge failed its smoke check")
        reply = subprocess.check_output([python, "-m", "aheadsubs.desktop.bridge", "folder-tasks"],
                                        env=env, cwd=stage.parent)
        if json.loads(reply).get("rules") != []:
            raise RuntimeError("Bundled folder task bridge failed its smoke check")
        reply = subprocess.check_output([python, "-m", "aheadsubs.desktop.bridge", "automation", "mcp-enable"],
                                        env=env, cwd=stage.parent)
        config = json.loads(reply)["mcp_config"]["mcpServers"]["aheadsubs"]
        check_mcp = (
            "import anyio, os, sys; from mcp import ClientSession, StdioServerParameters; "
            "from mcp.client.stdio import stdio_client\n"
            "async def check():\n"
            "    params = StdioServerParameters(command=sys.executable, args=sys.argv[1:], env=dict(os.environ))\n"
            "    async with stdio_client(params) as streams:\n"
            "        async with ClientSession(*streams) as client:\n"
            "            await client.initialize()\n"
            "            tools = await client.list_tools()\n"
            "            assert any(tool.name == 'aheadsubs_generate_subtitles' for tool in tools.tools)\n"
            "            result = await client.call_tool('aheadsubs_status')\n"
            "            assert not result.is_error and result.structured_content['ok']\n"
            "anyio.run(check)"
        )
        run(config["command"], "-c", check_mcp, *config["args"], env={**env, **config["env"]},
            cwd=stage.parent, timeout=30)
        old_args = ["subtitle_relay.cli" if arg == "aheadsubs.cli" else arg for arg in config["args"]]
        run(config["command"], "-c", check_mcp, *old_args, env={**env, **config["env"]},
            cwd=stage.parent, timeout=30)
        run(python, SCRIPTS / "smoke_media.py", data, env=env, cwd=stage.parent, timeout=45)


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
        # Exercise cleanup of installed payloads left by pre-LGPL builds.
        for relative in ("av/__init__.py", "av.libs/legacy.dll", "av-18.1.0.dist-info/METADATA",
                         "ctranslate2/cudnn64_9.dll"):
            path = target / "runtime/Lib/site-packages" / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("obsolete", encoding="ascii")
        legacy_module = target / "subtitle_relay" / "obsolete.py"
        legacy_module.parent.mkdir(parents=True, exist_ok=True)
        legacy_module.touch()
        run(installer, *silent, "/NOICONS", f"/DIR={target}")
        if legacy_module.exists():
            raise RuntimeError("Installer retained the obsolete Python package")
        smoke_test(target, cuda)
        if native:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, uninstall_key, access=winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                location, _ = winreg.QueryValueEx(key, "InstallLocation")
            if Path(location).resolve() != target.resolve():
                raise RuntimeError("The install location must match the update detection path")
            metadata = json.loads((target / "UI" / "aheadsubs-release.json").read_text(encoding="utf-8"))
            if metadata != {"Version": version, "Flavor": "cuda" if cuda else "standard"}:
                raise RuntimeError("Installed update metadata does not match the bundle")
        reply = subprocess.check_output([target / "runtime" / "python.exe", "-m",
                                         "aheadsubs.desktop.bridge", "automation", "cli-install"], cwd=target)
        if not json.loads(reply).get("cli_installed"):
            raise RuntimeError("Installer smoke could not register the bundled CLI on the user PATH")
    finally:
        uninstaller = target / "unins000.exe"
        if uninstaller.is_file():
            run(uninstaller, *silent)
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            path, _ = winreg.QueryValueEx(key, "Path")
    except FileNotFoundError:
        path = ""
    if os.path.normcase(str(target / "cli")) in map(os.path.normcase, path.split(";")):
        raise RuntimeError("The uninstaller left the bundled CLI on the user PATH")


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
        companion = work / f"{SLUG}-v{args.version}-windows-x64-ffmpeg-source.zip"
        stage_ffmpeg(stage, downloads, args.msys2.resolve(), companion)
        stage_inference_notices(stage, downloads)
        stage_app(stage, dotnet, args.version, args.cuda)
        smoke_test(stage, args.cuda)
        archive = work / (name + "-portable.zip")
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=3) as zipped:
            for path in sorted(stage.rglob("*")):
                if path.is_file():
                    zipped.write(path, path.relative_to(work))
        files = [archive, companion]
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
    parser.add_argument("--version", default=(os.getenv("AHEADSUBS_RELEASE_VERSION")
                                              or os.getenv("SUBTITLE_RELAY_RELEASE_VERSION")
                                              or project["version"]))
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument("--download-cache", type=Path, default=ROOT / ".relay" / "packaging-tools")
    parser.add_argument("--cuda", action="store_true", help="include optional NVIDIA CUDA wheel libraries")
    parser.add_argument("--native", action="store_true", help="include the self-contained WPF desktop")
    parser.add_argument("--dotnet", type=Path, help="path to the .NET 10 SDK dotnet.exe")
    parser.add_argument("--iscc", type=Path, help="path to Inno Setup compiler ISCC.exe")
    parser.add_argument("--msys2", type=Path, default=Path(os.getenv("AHEADSUBS_MSYS2", "C:/msys64")),
                        help="path to MSYS2 with the UCRT64 compiler, NASM, and make")
    parser.add_argument("--portable-only", action="store_true")
    parser.add_argument("--verify-install", action="store_true", help="install and remove a test copy in a clean profile")
    build(parser.parse_args())
