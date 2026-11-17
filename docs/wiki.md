# Wiki publication

[English](wiki.md) | [简体中文](wiki.zh-CN.md)

The repository owns documentation. The Wiki publishes generated English and Chinese navigation pages and references the matching overview images; do not maintain a second copy of the guides.

Implementation acceptance: generate both pages from the corresponding README introduction and documentation table, validate repository links and image languages in CI, and publish only from `main`. Preserve unrelated Wiki pages, avoid empty commits, serialize writes, and report authentication failures explicitly. Publishing requires the repository Actions secret `WIKI_TOKEN` with Wiki write access.
