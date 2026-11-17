"""Check tracked Markdown language pairs and local file links (no network needed)."""
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]


def check():
    files = [Path(p) for p in subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "*.md"],
        cwd=ROOT, text=True, encoding="utf-8").splitlines()]
    errors = []
    for path in sorted(set(files)):
        text = (ROOT / path).read_text(encoding="utf-8")
        english = path.with_name(path.name.replace(".zh-CN.md", ".md"))
        chinese = english.with_name(english.stem + ".zh-CN.md")
        for counterpart in (english, chinese):
            if not (ROOT / counterpart).is_file():
                errors.append(f"{path}: missing language counterpart {counterpart}")
        switch = f"[English]({english.name}) | [简体中文]({chinese.name})"
        if switch not in text:
            errors.append(f"{path}: missing language switch")
        # Ignore fenced examples; links in actual prose and images must resolve.
        prose = re.sub(r"```.*?```", "", text, flags=re.S)
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", prose):
            if re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith("#"):
                continue
            filename = unquote(target.split("#")[0])
            if not (ROOT / path.parent / filename).exists():
                errors.append(f"{path}: broken local link {target}")
    return errors, len(set(files))


if __name__ == "__main__":
    errors, count = check()
    print("\n".join(errors) if errors else f"Documentation pairs and local links: {count} pages passed")
    raise SystemExit(bool(errors))
