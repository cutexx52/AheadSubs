# 播放器适配接口

## PotPlayer

启动后台后，在正在播放的 PotPlayer 窗口按 **Ctrl+Alt+J** 开启预读，按 **Ctrl+Alt+K** 停止。各窗口单独控制，重载字幕保留播放位置。左上角提示确认启停。适配器常态每 600 ms 查询一次后台，跳转后短暂改用 150 ms。

后台需要可读取的文件路径。适配器尝试用标题上的文件名定位已打开的文件，然后查找该窗口已确认的目录。仍无法定位时会请用户选择正在播放的文件。PotPlayer 快捷键使用第一条内嵌音轨，沿用助手里的源语言、目标语言和双语设置。需要指定其他音轨时，可运行 `python -m subtitle_relay potplayer --help` 或 `python -m subtitle_relay potplayer-open --help` 查看手动绑定和开播命令。

可选的 AngelScript 扩展可从助手安装。**Subtitle Relay (local service)** 是 PotPlayer 的现有字幕翻译入口，使用 [`/v1/text`](server.md#文本翻译)。**Subtitle Relay - Start audio pre-read** 启动本地视频预读。使用预读字幕时，将 PotPlayer 的 **字幕 → 实时字幕翻译** 设为 **不使用**。再翻译已生成的双语字幕可能改变换行，并在同一时间点先后显示两个版本。

## mpv

mpv 0.42+ 的原生右键菜单可载入 `integrations/mpv/subtitle_relay.lua`。在助手里选择 **安装 mpv 菜单**，指定配置目录并重启 mpv，在 **Subtitle Relay** 菜单启用。便携版应选择对应的 `portable_config` 目录。菜单可调整来源、目标语言和预读时长。

独立 IPC 适配器也可由 CLI 启动。多个 mpv 窗口应各用一个管道名。

```cmd
mpv.exe --input-ipc-server=relay-window-1 D:\video\clip.mkv
python -m subtitle_relay mpv relay-window-1 --source ja --target zh --ahead 20
```

## 实现新适配器

Python 共享循环 `run_adapter()` 接受实现以下方法的播放器对象。

| 方法 | 合约 |
| --- | --- |
| `state()` | 返回 `path`、`position`，并尽量提供 `audio`、`duration` 和 `speed`。尚未就绪时返回 `None`。位置使用原媒体时间，单位秒。 |
| `publish(path, revision)` | 将指定 SRT 加载到当前窗口。用 `(path, revision)` 抑制重复重载，首条字幕出现后才首次加载。 |

播放文件、音轨、语言或位置变化时，更新同一窗口的会话；播放器退出或用户停止时释放会话。非 Python 适配器可以直接使用[后台 HTTP v1](server.md)。调试后台时，可运行 `python -m subtitle_relay clock D:\video\clip.mkv --position 45 --target zh` 模拟播放头，使用 `--realtime` 可按真实时间推进。
