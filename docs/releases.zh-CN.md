# 发布与 Actions 预算

[English](releases.md) | [简体中文](releases.zh-CN.md)

## 自动流程

每天 **UTC 02:17 / 香港时间 10:17**，Windows bundles 检查默认分支。仅同时满足以下条件才发布预览版：

1. 仓库是公开仓库；私有仓库跳过构建，避免默默消耗付费计算资源。
2. 距最近一次成功公开发布（稳定版或预览版）至少 **72 小时**，草稿不计。
3. 与该版本相比有影响程序的改动；仅 Markdown、`docs/` 图片、测试变化不触发，未知路径保守视为相关。
4. 默认分支当前准确提交的最近一次 push CI 已成功。

没有历史版本时，第一个符合条件的默认分支构建成为基准。历史标签缺失或不是祖先时停止，避免比较错误历史。GitHub 定时任务可能延迟，每日检查也不保证恰好 72 小时发布。公开仓库 60 天无活动可能停用定时任务，恢复工作时需在 Actions 重新启用。

预览标签为 `v<项目版本>-preview.<12位提交号>`，如 `v0.1.0-preview.abcdef123456`；同提交重试名称不变，标记 **Pre-release**，不设为 Latest。稳定版仍由显式推送的 `vX.Y.Z` 标签发布。项目版本由维护者更新，调度器不猜测 major/minor/patch 升级。

## 构建、验证、发布

固定源提交，在两个标准 `windows-2025` runner 并行构建标准/CUDA x64。各自运行单测、WPF 打包、私有运行时检查以及 `--verify-install`：在干净用户环境安装、冒烟、卸载。这不能代替真实 GPU 推理或全部 Windows 版本测试。

上传前创建草稿 Release。各变体按照本地 SHA256 清单核验安装包、便携 ZIP 和 FFmpeg 源码 ZIP。由标准版任务上传共用的源码 ZIP。两路全部成功，四个二进制、两个清单和源码 ZIP 均已上传、非空且各小于 2 GiB，已有标签仍指向构建 SHA，才公开草稿。发布说明链接到 LGPL 源码和构建材料。此工作流不建立长期 Actions artifacts 或模型及依赖缓存。

判定、构建和发布在同一工作流内完成，不依赖 `GITHUB_TOKEN` 创建标签后再次触发工作流。更新说明使用 GitHub 自动生成内容，以隐藏标记记录源提交。

## 当前公开仓库的预算

2026-11-17 已确认 AheadSubs 为公开仓库。公开仓库标准托管 runner 计算免费，独立于私有仓库额度；大型 runner 即使公开也计费，本项目不用。构建发布无需 Codex 定时任务或付费 AI API。Agent 审查使用独立服务额度，不包含在计算免费声明内。

| 项目 | 控制措施 |
| --- | --- |
| 每日资格检查 | 标准 Ubuntu，5 分钟超时；不符合条件不开 Windows |
| Windows 构建 | 两个标准 runner，各 45 分钟超时；不做无限自动重试 |
| 成功发布频率 | 至少间隔 72 小时，约每 30 天 10 次，取决于时点 |
| PR CI | 只跑 PR 和 main push，不重复跑功能分支 push；取消过时运行 |
| 二进制存储 | 直接放 Release 附件；不上传/下载 Actions artifact，不建持久缓存 |
| 私有化 | 停止构建，待维护者重新评估预算 |

提交 `aa966bc` 的一次[验证运行](https://github.com/cutexx52/AheadSubs/actions/runs/44109492224)：标准版 **2分48秒**，CUDA **8分08秒**（包含安装环境、测试的 job 墙钟时间）。按每月十次估算约 **110 Windows runner 分钟**，另有每日检查、CI、上传时间。这只是一次样本估算，不是耗时或全账号账单保证。按现行公开仓库标准 runner 政策，计算费用为 **$0**。

该次标准版文件约 266.3 + 216.9 MiB，CUDA 约 1489.3 + 1374.9 MiB，合计约 **3.27 GiB/版**。不把这些文件长期留在 Actions artifacts，而使用 Releases 分发；每个附件都检查 2 GiB 上限。GitHub 对 Release 总存储/带宽未列总量上限，但这不代表 Actions artifact 或 Packages 存储无限免费。

未修改或核实账号账单设置。账号支持时，为付费 Actions 预算开启 **stop usage**；不为此流程提高 cache 上限或启用大型 runner。账号其他存储、仓库、模型 API、审查订阅另计。仓库私有化或加入付费服务前重新评估。

## 手工验证、重试和恢复

- **只验证不发布：** Actions → Windows bundles → Run workflow，`mode=verify`，版本如 `0.1.0-check`。构建、安装、卸载两版，日志保留证据；二进制随 runner 销毁，不建 Release/标签。可选可信 PR 分支。
- **立即检查预览资格：** 默认分支运行 `mode=preview`，仍遵守 72 小时、改动和 CI 条件，不是强制发布绕过。
- **稳定版：** 经授权在目标提交推送版本标签；测试和打包成功后才公开。带 `-` 的版本仍是预发布。
- **失败：** 保留未公开草稿；同源提交可重跑失败工作流/job，或由次日检查再试。仅允许继续带同源标记的草稿，不覆盖公开或不相关版本。
- **失败后新提交：** 新 SHA 有新预览标签；排障后维护者可删除废弃草稿，工作流不删除公开版本和历史标签。
- **停用：** PR 删除 schedule，或在 Actions 禁用 Windows bundles（后者也停手工和标签构建）。发布串行且不取消正在运行的任务，避免中途终止上传。GitHub 并发组可能替换较早的待运行任务，必要时重跑被略过的标签构建。

## 官方依据

- [Actions 计费](https://docs.github.com/en/billing/concepts/product-billing/github-actions)：公开标准 runner、付费用量、存储。
- [Release 附件限制](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)：单文件上限、总存储/带宽。
- [定时行为](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)：默认分支、延迟和不活跃停用。
- [GITHUB_TOKEN 事件](https://docs.github.com/en/actions/concepts/security/github_token)：避免标签触发链假设。
