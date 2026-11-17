# Wiki 发布

[English](wiki.md) | [简体中文](wiki.zh-CN.md)

仓库是文档的唯一维护来源。Wiki 发布自动生成的中英文导航页，并引用对应语言的概览图，不另行维护一份指南正文。

`tools/wiki.py` 读取各语言 README 中的 `wiki:intro` 和 `wiki:navigation` 标记区段。通过正常 PR 流程修改这些区段；本地 Markdown 链接转换为主分支链接，语言切换指向两版 Wiki 首页，登记的图片使用主分支中对应语言的文件。两版保持同步，新增导航入口写入两版 README 表格。

运行 `python tools/check_docs.py` 和 `python tools/wiki.py` 可离线验证。运行 `python tools/wiki.py --output .relay/wiki-preview` 可查看生成的 Markdown。CI 检查标记、文档目标与图片语言；输入缺失或无效会阻止发布。

**Wiki** 工作流在 `main` 的相关文件变更后运行，也支持在 `main` 使用 **Run workflow** 恢复同步。它读取最新主分支，生成两版页面，然后仅将 `Home.md` 和 `Home.zh-CN.md` 提交到独立 Wiki 仓库。其他页面不受影响；内容相同不产生提交。发布串行执行，使用任务自带、短期有效且具有 `contents: write` 权限的 `GITHUB_TOKEN`，无需个人 token、依赖安装、artifact 上传或模型构建。PR 只验证，不发布。

首次使用前需启用 Wiki 并创建第一个页面（AheadSubs 已完成）。检出、推送或验证失败会使运行明确失败；查看 Actions 日志，修复原因后在 main 重跑。不要强制推送覆盖并发修改。手动修改这两个生成首页会在下次同步时被覆盖。GitHub 提供 [Wiki Git 访问说明](https://docs.github.com/en/communities/documenting-your-project-with-wikis/adding-or-editing-wiki-pages)，社区记录了[同仓库 token 的使用方式](https://github.com/orgs/community/discussions/56893)。
