# Windows updates

[简体中文](../windows.md#检查更新)

The Windows desktop app checks GitHub for stable releases on startup and while it stays in the tray, at most once every 24 hours. Under **Advanced settings (高级设置) → Software updates**, you can turn off automatic checks or select **Check for updates** at any time. If GitHub is unavailable, you can retry manually while the subtitle service continues to work.

When an update is available, you can read the release notes. For an installed copy, select **Download and install** and confirm to download the installer for the current standard or CUDA edition. You can cancel while it downloads. After verifying the download size and SHA-256 digest, AheadSubs stops the subtitle service and closes before starting Setup. If verification fails, retry or download the installer manually from the release page. After upgrading, open AheadSubs from the Start menu and start the subtitle service when needed.

For a portable copy, select **Download portable ZIP** to open the matching download in your browser. Stop and exit AheadSubs from the tray, extract the ZIP into a new directory, and run AheadSubs there. Settings, models, and cached subtitles still load from the existing user data directory. If your copy predates **Software updates**, upgrade manually once from [GitHub Releases](https://github.com/cutexx52/AheadSubs/releases).
