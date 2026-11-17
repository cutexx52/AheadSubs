"""Budget-aware release planning and draft publication; uses only stdlib and gh."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tomllib

ROOT = Path(__file__).resolve().parents[1]
VERSION = re.compile(r"v?\d+\.\d+\.\d+(?:-[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*)?\Z")
# Documentation and tests do not change shipped behavior. Unknown files default to relevant.
DOC_NAMES = {".github/pull_request_template.md", ".github/copilot-instructions.md"}


def run(*args):
    return subprocess.check_output(args, cwd=ROOT, text=True, encoding="utf-8").strip()


def api(route, *args):
    return json.loads(run("gh", "api", route, *args))


def find_release(tag):
    # /releases/tags/{tag} is documented for published releases, not drafts.
    # Authenticated list access includes drafts for a token with push permission.
    repo = os.environ["GITHUB_REPOSITORY"]
    pages = api(f"repos/{repo}/releases?per_page=100", "--paginate", "--slurp")
    return next((r for page in pages for r in page if r["tag_name"] == tag), None)


def relevant(path):
    return not (path.endswith(".md") or path.startswith(("docs/", "tests/")) or path in DOC_NAMES)


def published(releases):
    return sorted((r for r in releases if not r["draft"] and r.get("published_at")),
                  key=lambda r: r["published_at"], reverse=True)


def preview_due(releases, now, changed):
    history = published(releases)
    if history:
        last = datetime.fromisoformat(history[0]["published_at"].replace("Z", "+00:00"))
        if now - last < timedelta(hours=72):
            return False, "Last successful release was less than 72 hours ago."
    if not any(relevant(p) for p in changed):
        return False, "No distributed application changes since the last release."
    return True, "Application changed and the release interval is satisfied."


def source_asset(tag):
    return f"aheadsubs-{tag}-windows-x64-ffmpeg-source.zip"


def variant_assets(tag, flavor):
    stem = f"aheadsubs-{tag}-windows-x64{flavor}"
    return {f"{stem}{suffix}" for suffix in ("-setup.exe", "-portable.zip", "-SHA256.txt")}


def asset_names(tag):
    return variant_assets(tag, "") | variant_assets(tag, "-cuda") | {source_asset(tag)}


def validate_assets(tag, assets):
    expected = asset_names(tag)
    if {a["name"] for a in assets} != expected or len(assets) != len(expected):
        raise RuntimeError("Expected both Windows variants, their checksums and the FFmpeg corresponding source")
    if any(a.get("state") != "uploaded" or not 0 < a["size"] < 2**31 for a in assets):
        raise RuntimeError("Assets must be uploaded, nonempty and below GitHub's 2 GiB limit")


def output(values):
    for key, value in values.items():
        print(f"{key}={value}")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            for key, value in values.items():
                f.write(f"{key}={value}\n")


def plan():
    repo = os.environ["GITHUB_REPOSITORY"]
    event = os.environ["GITHUB_EVENT_NAME"]
    sha = run("git", "rev-parse", "HEAD")
    metadata = api(f"repos/{repo}")
    if metadata["private"]:
        output({"build": "false", "reason": "Private repository: automatic builds disabled for budget safety."})
        return
    preview = event == "schedule" or os.environ.get("RELEASE_MODE") == "preview"
    publish = preview or event == "push"
    if preview:
        if sha != api(f"repos/{repo}/commits/{metadata['default_branch']}")["sha"]:
            raise RuntimeError("Previews may only use the current default branch commit")
        pages = api(f"repos/{repo}/releases?per_page=100", "--paginate", "--slurp")
        history = published([r for page in pages for r in page])
        if history:
            baseline = history[0]["tag_name"]
            # checkout fetches full history and tags; reject missing/non-ancestor release bases.
            run("git", "merge-base", "--is-ancestor", baseline, sha)
            changed = run("git", "diff", "--name-only", baseline, sha).splitlines()
        else:
            changed = run("git", "ls-files").splitlines()
        now = datetime.now(timezone.utc)
        due, reason = preview_due(history, now, changed)
        if not due:
            output({"build": "false", "reason": reason})
            return
        runs = api(f"repos/{repo}/actions/workflows/ci.yml/runs?head_sha={sha}&event=push&per_page=100")["workflow_runs"]
        if not runs or runs[0]["status"] != "completed" or runs[0]["conclusion"] != "success":
            output({"build": "false", "reason": "Waiting for successful default-branch CI at this exact commit."})
            return
        version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
        # Commit identity makes failure retries idempotent, even on a later day.
        tag = f"v{version.split('-')[0]}-preview.{sha[:12]}"
    else:
        tag = os.environ.get("GITHUB_REF_NAME", "") if event == "push" else os.environ["RELEASE_VERSION"]
        tag = "v" + tag.removeprefix("v")
    if not VERSION.fullmatch(tag):
        raise RuntimeError("Invalid release version")
    output({"build": "true", "publish": str(publish).lower(), "sha": sha,
            "tag": tag, "prerelease": str("-" in tag).lower()})


def draft(tag, sha):
    repo = os.environ["GITHUB_REPOSITORY"]
    # Enumerate instead of interpreting every API failure as a missing release.
    existing = find_release(tag)
    marker = f"<!-- aheadsubs-source:{sha} -->"
    if existing:
        if not existing["draft"] or marker not in (existing.get("body") or ""):
            raise RuntimeError("Refusing to overwrite a public or unrelated release")
        return
    notes = api(f"repos/{repo}/releases/generate-notes", "-f", f"tag_name={tag}", "-f", f"target_commitish={sha}")["body"]
    source_url = f"https://github.com/{repo}/releases/download/{tag}/{source_asset(tag)}"
    ffmpeg_notice = ("The Windows packages include FFmpeg under LGPL v3 or later. "
                     f"[Corresponding source and build instructions]({source_url}).\n\n"
                     "Windows 安装包包含按 LGPL v3 或更新版本授权的 FFmpeg。"
                     f"[对应源码和构建说明]({source_url})。")
    args = ["gh", "release", "create", tag, "--repo", repo, "--target", sha,
            "--draft", "--title", f"AheadSubs {tag}", "--notes", f"{marker}\n\n{ffmpeg_notice}\n\n{notes}"]
    if "-" in tag:
        args += ["--prerelease"]
    run(*args)


def upload(tag, sha):
    repo = os.environ["GITHUB_REPOSITORY"]
    release = find_release(tag)
    if not release or not release["draft"] or f"<!-- aheadsubs-source:{sha} -->" not in (release.get("body") or ""):
        raise RuntimeError("Upload target must be our draft at the planned commit")
    files = sorted((ROOT / "dist").glob("*"))
    names = {p.name for p in files}
    source = source_asset(tag)
    flavor = next((f for f in ("", "-cuda") if names == variant_assets(tag, f) | {source}), None)
    if flavor is None:
        raise RuntimeError("Expected one variant's installer, archive, checksum and FFmpeg source")
    manifest, = (p for p in files if p.name.endswith("-SHA256.txt"))
    checked = set()
    for line in manifest.read_text(encoding="ascii").splitlines():
        digest, name = line.split("  ", 1)
        if name not in names or name == manifest.name or name in checked:
            raise RuntimeError("Invalid checksum filename")
        with (ROOT / "dist" / name).open("rb") as f:
            if hashlib.file_digest(f, "sha256").hexdigest() != digest:
                raise RuntimeError("Checksum mismatch")
        checked.add(name)
    if checked != names - {manifest.name}:
        raise RuntimeError("Incomplete checksum coverage")
    if any(not 0 < p.stat().st_size < 2**31 for p in files):
        raise RuntimeError("Release files must be nonempty and below 2 GiB")
    # Both manifests cover the deterministic source ZIP. Only the standard job
    # uploads it, so parallel uploads cannot overwrite each other's source.
    uploads = [p for p in files if not flavor or p.name != source]
    run("gh", "release", "upload", tag, *map(str, uploads), "--repo", repo, "--clobber")
    print("Verified and uploaded:", ", ".join(p.name for p in uploads))


def publish_release(tag, sha):
    repo = os.environ["GITHUB_REPOSITORY"]
    release = find_release(tag)
    if not release or not release["draft"] or f"<!-- aheadsubs-source:{sha} -->" not in (release.get("body") or ""):
        raise RuntimeError("Release is not the expected draft")
    validate_assets(tag, release["assets"])
    # For existing stable tags, verify they still point at the built commit.
    refs = run("git", "ls-remote", "origin", f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}").splitlines()
    if refs:
        target = next((line.split()[0] for line in refs if line.endswith("^{}")), refs[0].split()[0])
        if target != sha:
            raise RuntimeError("Release tag no longer matches the built commit")
    run("gh", "release", "edit", tag, "--repo", repo, "--draft=false",
        "--latest=false" if "-" in tag else "--latest")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "draft", "upload", "publish"))
    parser.add_argument("--tag", default=os.environ.get("RELEASE_TAG"))
    parser.add_argument("--sha", default=os.environ.get("RELEASE_SHA"))
    args = parser.parse_args()
    if args.command == "plan":
        plan()
    else:
        if not args.tag or not VERSION.fullmatch(args.tag) or not re.fullmatch(r"[0-9a-f]{40}", args.sha or ""):
            parser.error("Valid tag and full source SHA required")
        {"draft": draft, "upload": upload, "publish": publish_release}[args.command](args.tag, args.sha)
