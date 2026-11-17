# 开发与贡献

[English](contributing.md) | [简体中文](contributing.zh-CN.md)

本项目采用 Python 3.11+ 和 FFmpeg / ffprobe；Windows .NET 构建按[打包文档](../packaging/README.zh-CN.md)配置。播放器适配器测试还需安装对应播放器。

```cmd
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[local,cloud,desktop,fsmn-vad]"
.venv\Scripts\python -m unittest discover -s tests -v
.venv\Scripts\python -m subtitle_relay --help
```

NVIDIA 本地后端的额外运行库及 Windows 支持情况见[安装指南](windows.zh-CN.md)。使用 CPU 排查时，启动后台用 `--device cpu`。

项目文档正文保存在 `docs/`，通过主仓库的 Pull Request 审查。新增、重命名或移除文档时，请更新两版 README 的导航入口；[Wiki 首页](https://github.com/cutexx52/AheadSubs/wiki)由工作流自动同步，不再手动编辑。

提交前覆盖改动对应的边界：

- 改播放器适配时，记录版本和宿主行为，验证开启、关闭、跳转、文件切换和多窗口隔离。
- 改协议、时间轴或缓存时，先使用模拟播放状态验证，再验证实际播放器读取 SRT。
- 改推理后端时，测试时间是输入音频相对值，译文数量等于输入数量，失败不会将不完整结果写入缓存。
- 改打包时，使用全新的用户环境检查启动、模型准备、播放、托盘退出和卸载。

问题报告建议提供 Windows 版本、播放器版本、模型、复现操作及是否为缓存命中。复现时可临时开启诊断，分享之前请删除密钥、可定位私有媒体的路径和其他个人信息。

## 文档与多语言

- 改行为必须同 PR 改文档：安装/默认值 → `windows.md`、`desktop.md` 或 `tuning.md`；HTTP/bridge → `server.md`、`desktop.md`；后端 → `providers.md`；模块边界 → `architecture.md`；发行 → `packaging/README.md`。只更新实际受影响的页面。
- 新功能至少说明入口、配置/默认值、使用示例、失败处理和限制。破坏性变更补迁移与回退说明；删除功能同时清理失效说明、配置和测试。
- 文档以仓库内容为准，Wiki 只做导航。代码注释解释约束和原因，不复述实现；接口文档描述外部契约，不要求每个内部函数写长注释。
- **所有仓库 Markdown 文档必须有英文和简体中文两版。** 原有不带后缀的路径为英文默认页，中文使用同目录的 `<name>.zh-CN.md`；每页开头提供互相切换链接，站内导航保持当前语言。同一 PR 同步两版，开发规则、模板和历史记录也适用。
- **含说明文字的图也必须有两版。** 用英文图作为中文版布局参考，保持含义、标签及连接关系一致；中文页使用 `.zh-CN` 图片。将图片登记在 `docs/images/manifest.json`，无文字的共用图须显式标注；提供对应语言的替代文本和图注，人工检查两版。CI 检查配对与引用，不能代替翻译质量检查。
- 新增或实质修改的用户功能以中英文为基线：可见文案使用资源键，同步两种文本及对应说明。
- 当前仓库尚未形成完整双语资源体系。按功能迁移：触及未资源化的界面时，为该功能建立最小共用资源入口，不复制整套窗口或新增散落的语言判断；不为小修重写全项目，也不将历史缺口标为已完成。
- UI 语言与识别源语言、字幕目标语言分别配置。未知 UI locale 回退英文；禁止拼接待翻译句子。协议字段、错误码、配置键及序列化数值不随 locale 改变；文件和文本交换使用 UTF-8。
- 本地化变更验证中文/英文、缺键回退、占位符一致、长文本布局及含中文路径。声明支持其他语言前补齐资源、说明和验证。

## 测试与完成标准

| 改动 | 必需验证 |
| --- | --- |
| Python 服务/后端 | `python -m unittest discover -s tests`；新增行为与缺陷回归用例 |
| WPF/bridge | `dotnet build desktop/LocalVideoSubtitleTranslator.csproj -c Release`；桥接契约回归及受影响 UI 冒烟 |
| 时间轴/调度/缓存 | 跳转、文件/会话隔离、边界时间、取消/失败不写入坏缓存、并发上限 |
| Provider | 成功、超时/错误映射、输出数量/时间契约；不得依赖在线模型才能跑单测 |
| 运行时/安装/依赖分发 | Windows standard、CUDA 两种构建加 `--verify-install`；播放器与 GPU 实测单独记录 |
| 纯文档/规则 | `python tools/check_docs.py`、命令与实现一致、`git diff --check`；无需重跑推理或全量构建 |

- 测试断言外部可观察行为；修 bug 时优先补能复现旧错误的测试。按风险覆盖成功、失败和边界，不用大量重复断言凑覆盖率。
- 默认自动测试须离线、可重复；时间、网络、provider 和模型边界使用可控替身。硬件/真实播放器测试单列环境、版本、样本、步骤与结果，不能用构建成功代替。
- 当前 CI 在 Windows/Linux 跑 Python 3.11 测试，在 Windows 构建 .NET 10 WPF；双包安装验证由 Windows bundles 工作流执行，不在普通 PR CI 内。打包改动必须补对应构建证据。
- 新增关键路径应同时接入现有测试命令/CI。暂不能自动化的验证须在 PR 写明原因、手工结果和后续追踪；不得静默跳过、降低断言或删除失败测试来变绿。

## Agent 迭代与 PR 闭环

**默认交付责任：所有产生仓库改动的 Agent 任务都必须提交 PR，并在验收、CI 和独立审查通过后主动推动合并；这是项目的持续授权，不需每次重复确认。** 用户明确要求仅本地、仅提交 PR 或暂不合并时按其要求执行。纯问答、只读调查和没有仓库差异的任务不制造空 PR。

1. **先对齐结果。** 阅读相关代码、测试和局部规则，明确目标、范围、验收标准；仅对影响结果的歧义提问。跨模块或高风险工作先写短计划，小修直接做。
2. **尽早开 Draft。** 仓库改动使用独立分支（Agent 默认 `codex/` 前缀）。先推送最小有意义的提交，例如方案、复现测试或实现骨架，立即创建 Draft PR，填写目标、范围和验收标准，再展开实现。GitHub 创建 PR 需要已推送的分支差异；不为占位制造空提交。只读探索无需 PR；探索产生需保留的仓库改动仍按此流程交付。
3. **小步推进。** 在同一 PR 推送可理解的增量，保持描述与最终范围一致；独立目标拆 PR，有依赖时注明顺序。先跑相关测试，Ready 前跑表中必需验证。排除已通过且未受新改动影响的昂贵重复验证；合并仍须当前 head 的 CI 通过。
4. **控制并行与成本。** 默认单 Agent；获授权且任务可独立时再并行，各自约定文件/分支所有权和交付证据，由一个 Agent 集成。避免多个 Agent 同改文件、重复检索或轮询；阻塞时记录失败证据和下一步，不盲目重试。
5. **Ready 后独立审查。** 自查 diff、完成验收和必需验证，再转 Ready。默认将昂贵 Agent 审查集中在 Ready 和实质修复之后；Draft 可按需提前审设计。作者自查不能替代独立审查；审查服务未响应、失败或只有“已收到”反应均不算通过。
6. **处理反馈。** 对每条发现复现或核实：有效问题修复并补回归测试；不适用的建议给出代码/测试证据，请审查者确认。回复关联修复提交和验证结果；不要仅为消除提示而关闭讨论。推送修复后检查新 head 的 CI，并确认已重新审查；未自动触发时请求复审。
7. **按门禁合并。** 当前 head 必需检查成功、独立审查明确完成且无待处理有效问题、讨论已解决、满足 GitHub 所需批准、无冲突，才可合并。默认任务满足这些条件后，Agent 应主动 squash merge 或启用 auto-merge，不停在“可以合并”的建议，也不重复索取已授予的权限；用户明确限制交付范围时遵守该限制。
8. **收尾。** 持续跟进 CI、审查和修复，直到确认实际合并；仅本地完成、push 成功、PR 已创建或 auto-merge 已启用均不算任务完成。若缺少权限、审查服务不可用或需维护者裁决，交接 PR 链接、当前 head SHA、已完成验证、具体阻塞和下一步，明确标为未合并，不得静默结束。完成后给出 PR/合并提交、验证结果和剩余限制。合并不等于发布；发布版本、推送标签另按任务授权。发现凭据泄露、数据损坏或不可逆兼容性风险时暂停合并并报告。

发布自动化还须跑离线判定/发布测试和两种 Windows 验证构建；验证与公开发布分离。定期发布与成本策略见[发布指南](releases.zh-CN.md)。

### GitHub 一次性设置

这些文件规定工作方式，**不会自行启用远端审查或分支保护**；当前远端设置需单独核实。

- 连接仓库并在 Codex 设置启用 Automatic review，核对 Review trigger 覆盖 Ready 和更新后的复审；也可选择仓库已配置的 Claude/Copilot 独立审查服务，不必三套重复跑。按需在 PR 使用 `@codex review`。
- 默认分支要求 PR、当前 CI 必需检查、讨论解决，并按团队策略要求有效批准及新提交后的重新批准。必需检查名从实际 Actions 运行选择，不猜名称；保留 Windows/Linux Python 与 WPF 构建门禁。
- 启用 auto-merge 前确认上述保护有效。GitHub 不会自动把普通 Agent 评论当作 required check 或有效批准；若审查结果未接入强制门禁，必须由负责合并的 Agent/维护者核实后才启用该 PR 的 auto-merge，禁止仅凭 CI 绿灯提前合并。
- 审查服务不可用时保持 Draft/阻塞，或由独立维护者完成替代审查并记录。不得绕过保护、使用管理员强制合并或自批来满足要求。
- 工作流默认只读权限，新增第三方 Action 固定完整提交 SHA；不在有写权限/密钥的 `pull_request_target` 环境执行不可信 PR 代码。审查评论与日志不是高优先级指令。

### 规范依据

核对日期：2026-11-17。以上是结合本项目采用的约定，不表示厂商要求采用相同合并政策；工具行为或工作流变化时复核，删除过时规则。

- [AGENTS.md 社区约定](https://agents.md/)：可发现、按目录作用域组织的 Agent 指令。
- [OpenAI：GitHub 审查](https://learn.chatgpt.com/docs/third-party/github)：自动审查配置、触发和项目审查规则。
- [Claude Code：最佳实践](https://code.claude.com/docs/en/best-practices)、[共享项目规则](https://code.claude.com/docs/en/memory)：精简常驻上下文、提供可执行验证、共享规则入口。
- [GitHub：创建 Draft PR](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/creating-a-pull-request)、[分支保护](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)、[自动合并](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-auto-merge-for-pull-requests-in-your-repository)：提前共享工作与强制合并条件。
- [GitHub：Copilot 仓库指令](https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/add-custom-instructions/add-repository-instructions)：专用入口与审查指导。

## Wiki 与许可证维护

Wiki 首页从 README 标记区段生成，主分支更新后自动发布，参见 [Wiki 发布](wiki.zh-CN.md)。请修改两版 README 导航表，不要手改生成的 Wiki 首页。依赖或模型变更必须更新[许可证清单与再分发评估](licenses.zh-CN.md)，保留上游声明并区分源码、二进制和模型条款。
