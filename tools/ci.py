"""Decide whether a pull request merge commit can use documentation-only CI."""

from pathlib import Path
import subprocess
import sys


def is_documentation(path: str) -> bool:
    if path.endswith(".md"):
        return "/" not in path or path.startswith(("docs/", ".github/")) or path in {
            "packaging/README.md", "packaging/README.zh-CN.md",
        }
    return path.startswith("docs/images/") and (
        path.endswith((".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif"))
        or path in {"docs/images/manifest.json", "docs/images/prompts.json"}
    )


def docs_only(repo: Path) -> bool:
    # Actions checks out a synthetic PR merge. Its first parent is the base
    # snapshot, so this diff excludes changes already on the base branch.
    try:
        changed = subprocess.check_output(
            ["git", "diff", "--no-renames", "--name-only", "-z", "HEAD^1", "HEAD", "--"],
            cwd=repo,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError:
        print("Could not compare the PR against its base. Running full CI.", file=sys.stderr)
        return False
    paths = changed.decode("utf-8", errors="surrogateescape").split("\0")[:-1]
    return bool(paths) and all(is_documentation(path) for path in paths)


if __name__ == "__main__":
    print(f"docs_only={str(docs_only(Path(__file__).resolve().parents[1])).lower()}")
