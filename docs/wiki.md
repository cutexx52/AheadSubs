# Wiki publication

[English](wiki.md) | [简体中文](wiki.zh-CN.md)

The repository owns documentation. The Wiki publishes generated English and Chinese navigation pages and references the matching overview images; do not maintain a second copy of the guides.

`tools/wiki.py` reads the `wiki:intro` and `wiki:navigation` marker pairs in each README. Edit those sections through the normal PR workflow. Local Markdown links become main-branch links; the language switch points to the two Wiki home pages; registered images use the matching language asset from the main branch. Keep both editions synchronized. New navigation entries belong in both README tables.

Run `python tools/check_docs.py` and `python tools/wiki.py` to validate without network access. To inspect generated Markdown, run `python tools/wiki.py --output .relay/wiki-preview`. CI checks marker pairs, document targets and image languages; missing or invalid input prevents publication.

The **Wiki** workflow runs after relevant `main` changes and supports **Run workflow** on `main` for recovery. It checks out the latest main branch, generates both pages, then commits only `Home.md` and `Home.zh-CN.md` to the separate Wiki repository. Other pages remain untouched; identical content produces no commit. Publication is serialized and uses the job's short-lived `GITHUB_TOKEN` with `contents: write`, without a personal token, dependency installation, artifact upload or model build. PRs only validate; they do not publish.

Enable Wiki and create its first page once before using the workflow (already done in AheadSubs). A checkout/push or validation failure fails the run visibly; check the Actions log and rerun on main after fixing the cause. Never force-push over concurrent Wiki edits. Manual changes to the two generated home pages will be replaced on the next sync. GitHub documents [Wiki Git access](https://docs.github.com/en/communities/documenting-your-project-with-wikis/adding-or-editing-wiki-pages); its community records [same-repository token access](https://github.com/orgs/community/discussions/56893).
