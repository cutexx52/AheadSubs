# Wiki 发布

[English](wiki.md) | [简体中文](wiki.zh-CN.md)

仓库是文档的唯一维护来源。Wiki 发布自动生成的中英文导航页，并引用对应语言的概览图，不另行维护一份指南正文。

实现验收：从对应语言 README 的简介与文档表格生成两版页面，CI 检查仓库链接和图片语言，仅从 `main` 发布。保留其他 Wiki 页面，无变化不提交，串行写入，鉴权失败明确报错。发布需要仓库 Actions secret `WIKI_TOKEN`，其凭据必须具有 Wiki 写入权限。
