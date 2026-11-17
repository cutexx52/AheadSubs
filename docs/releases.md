# Releases and Actions budget

[English](releases.md) | [简体中文](releases.zh-CN.md)

## What happens automatically

Every day at **02:17 UTC / 10:17 Hong Kong time**, Windows bundles checks the default branch. A preview is eligible only when:

1. The repository is public. Private repositories skip this workflow to avoid silently consuming paid compute.
2. At least **72 hours** have elapsed since the latest published release (stable or preview). Drafts do not count.
3. The diff from that release contains application-related changes. Markdown, `docs/` assets and tests alone do not qualify; unknown paths count conservatively.
4. The latest push CI run for the exact default-branch commit has succeeded.

Without a previous release, the first eligible default-branch build becomes the baseline. Missing/non-ancestor release tags fail closed rather than comparing the wrong history. GitHub may delay schedules; daily checks mean publication can occur later than exactly 72 hours. Public-repository schedules may stop after 60 days without activity; re-enable them in Actions when needed.

A preview uses `v<project-version>-preview.<12-character-commit>`, for example `v0.1.0-preview.abcdef123456`. The SHA-based name is stable across retries and cannot be mistaken for a stable version. Previews are marked **Pre-release**, never Latest. Stable releases still require an explicitly pushed `vX.Y.Z` tag. Update the project version deliberately for the next release line; the scheduler does not invent major/minor/patch bumps.

## Build, verify, publish

The workflow fixes one source SHA, then builds standard and CUDA x64 variants in parallel on standard `windows-2025` runners. Each runs unit tests, WPF packaging, private-runtime checks and `--verify-install` (install, smoke-test, uninstall in a clean profile). These checks do not prove real GPU inference or all Windows editions.

A draft release is prepared before build uploads. Each successful variant verifies its installer, ZIP and FFmpeg source ZIP against its local SHA256 manifest. The standard job uploads the shared corresponding-source ZIP once. Publication requires both jobs, four binaries, two manifests and the source ZIP, all uploaded and nonempty under 2 GiB each, and any existing tag still matching the built SHA. The release notes link to the LGPL source and build materials. No long-lived Actions artifacts or model/dependency caches are created by this workflow.

The same workflow performs planning, building and publication; it does not rely on a `GITHUB_TOKEN`-created tag triggering another workflow. Release notes use GitHub's generated notes with the source SHA recorded in a hidden marker.

## Budget: designed for the current public repository

Verified on 2026-11-17: AheadSubs is public. Standard GitHub-hosted runner compute in public repositories is free independently of private-repository allowances. Larger runners are billed even for public repositories; this project uses none. No Codex recurring task or paid AI API is needed to build or publish. Agent code review has its own service allowance and is not included in this compute claim.

| Item | Budget control |
| --- | --- |
| Daily eligibility check | Standard Ubuntu, 5-minute timeout; no Windows job when ineligible |
| Windows builds | Two standard runners, 45-minute timeout each; no automatic retry loop |
| Successful release frequency | At most one per 72 hours; approximately 10 per 30 days, depending on timing |
| PR CI | Run on PRs and `main` pushes, not duplicate feature-branch pushes; superseded runs cancel |
| Binary storage | Direct Release assets; no Actions artifact upload/download or persistent cache |
| Private visibility | Fail closed / skip builds until maintainers deliberately revisit the budget |

One [verification run](https://github.com/cutexx52/AheadSubs/actions/runs/44109492224) at commit `aa966bc` took **2m48s** for standard and **8m08s** for CUDA (job wall time, including tests/setup). At ten such builds, that is roughly **110 Windows runner-minutes/month**, plus eligibility checks, CI and publication uploads. This is an estimate from one sample, not a guaranteed duration or whole-account bill. The public standard-runner compute charge under the current policy is **$0**.

That run produced approximately 266.3 + 216.9 MiB standard and 1489.3 + 1374.9 MiB CUDA binaries: about **3.27 GiB per release**. Keeping those as Actions artifacts would be wasteful; GitHub Releases is the distribution destination. Each asset is checked against GitHub's 2 GiB limit. Release storage/bandwidth has no documented total quota; this does not imply unlimited Actions artifact or Packages storage.

No account billing settings were changed or verified. Keep paid Actions budgets with **stop usage** enabled where your account supports them; do not increase cache limits or enable larger runners for this workflow. Account-wide storage, other repositories, paid model APIs and review subscriptions remain separate. Revisit this plan before making the repository private or adding paid services.

## Manual checks, retries and recovery

- **Verify without publishing:** Actions → Windows bundles → Run workflow → `mode=verify`, version such as `0.1.0-check`. Both variants are built/installed/uninstalled; logs retain evidence, but binaries are discarded with the runner and no release/tag is created. Can run on a trusted PR branch.
- **Check preview eligibility now:** run `mode=preview` on the default branch. It observes the same 72-hour, diff and CI gates; it is not a force-publish bypass.
- **Stable release:** push an authorized version tag at the intended commit. Tag builds run tests and packaging before publication. Prerelease-style tags with `-` remain prereleases.
- **Failure:** the draft stays unpublished. Rerun the failed workflow/jobs while the source is unchanged, or let the next daily check retry. Same-tag drafts can be resumed only with the matching source marker. Public or unrelated releases are never overwritten.
- **New commits after failure:** a new eligible SHA gets a new preview tag. Maintainers can delete abandoned drafts after diagnosis; the workflow does not delete public releases or historical tags.
- **Disable automatic previews:** remove the schedule via a PR or disable Windows bundles in Actions (the latter also stops manual/tag builds). Runs are serialized with cancellation disabled so a newer run does not interrupt uploads. GitHub can replace an older pending run in a concurrency group; rerun an omitted tag build if necessary.

## Sources

- [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions): public standard runners versus paid usage and storage.
- [Release asset limits](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases): individual file limit and release storage/bandwidth.
- [Schedule behavior](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule): default branch, delays and inactivity.
- [GITHUB_TOKEN event behavior](https://docs.github.com/en/actions/concepts/security/github_token): avoid chained tag-trigger assumptions.
