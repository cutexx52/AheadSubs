# Documentation illustrations

[English](README.md) | [简体中文](README.zh-CN.md)

The README workflow image explains player position → bounded audio look-ahead → local/cloud recognition and translation → timed SRT/cached cues → subtitle loading. The lower timeline distinguishes played media, the playhead and upcoming prepared cues. It is conceptual, not an application screenshot or a guarantee that every cue is already ready.

- English: [overview](aheadsubs-overview.png).
- Simplified Chinese: [overview](aheadsubs-overview.zh-CN.png), edited from the English reference with the same layout.
- Generated with the built-in `image_gen` tool. The [prompt specification and translation mapping](prompts.json) preserve the final design brief; no API-key CLI was used.
- [manifest.json](manifest.json) identifies language pairs. New text-bearing images must include both languages; explicitly register text-free shared assets instead of silently exempting them.

Review both rendered images, labels and arrows. Automated checks verify file pairs and language-appropriate references; humans/Agents still verify meaning and legibility. Captions and alt text belong in each language's consuming page.
