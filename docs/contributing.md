# 开发与贡献

本项目采用 Python 3.11+ 和 FFmpeg / ffprobe；Windows .NET 构建按[打包文档](../packaging/README.md)配置。播放器适配器测试还需安装对应播放器。

```cmd
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[local,cloud,desktop,fsmn-vad]"
.venv\Scripts\python -m unittest discover -s tests -v
.venv\Scripts\python -m subtitle_relay --help
```

NVIDIA 本地后端的额外运行库及 Windows 支持情况见[安装指南](windows.md)。使用 CPU 排查时，启动后台用 `--device cpu`。

项目文档正文保存在 `docs/`，通过主仓库的 Pull Request 审查。新增、重命名或移除文档时，请同时检查 README 和 [Wiki 首页](https://github.com/cutexx52/AheadSubs/wiki)上的链接。Wiki 首页可在 GitHub 上编辑，也可通过独立的 Wiki Git 仓库维护。

提交前覆盖改动对应的边界：

- 改播放器适配时，记录版本和宿主行为，验证开启、关闭、跳转、文件切换和多窗口隔离。
- 改协议、时间轴或缓存时，先使用模拟播放状态验证，再验证实际播放器读取 SRT。
- 改推理后端时，测试时间是输入音频相对值，译文数量等于输入数量，失败不会将不完整结果写入缓存。
- 改打包时，使用全新的用户环境检查启动、模型准备、播放、托盘退出和卸载。

问题报告建议提供 Windows 版本、播放器版本、模型、复现操作及是否为缓存命中。复现时可临时开启诊断，分享之前请删除密钥、可定位私有媒体的路径和其他个人信息。
