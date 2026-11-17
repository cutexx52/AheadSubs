# Releases and Actions budget

[English](releases.md) | [简体中文](releases.zh-CN.md)

## Implementation plan

- Check daily; publish a preview only after 72 hours since the last successful release and only for changes that affect the distributed app.
- Use standard GitHub-hosted Linux and Windows runners. Disable automatic publishing if the repository becomes private; do not silently consume paid compute.
- Build and verify standard and CUDA x64 installers and portable archives at one fixed commit. Publish only after every variant succeeds; retain stable releases as explicit version-tag releases.
- Avoid long-lived Actions artifacts and model caches. Publish binaries as Release assets, validate checksums and file limits, and document retry and failure behavior.
- Make every maintained Markdown page English by default with a reciprocal Simplified Chinese link. Check page coverage and links in CI.

Acceptance: offline scheduler tests, documentation checks, full service tests, Windows package verification for both variants, independent PR review, then merge.
