# Codex Lookout · Codex 瞭望台

**一眼看清，哪些 Codex 会话还在正常运行。**

鼠标移到 Mac 屏幕顶部的刘海／状态条，就能看到正在运行的会话、最近观测到的阶段、距上次进展的时间和需要关注的问题。点击会话，回到 Codex 处理。不需要打开网页。

[English](README.md) · [信号与判断边界](docs/signal-evidence.md) · [隐私说明](PRIVACY.md) · [参与贡献](CONTRIBUTING.md)

独立社区项目，与 OpenAI 无隶属关系，也未经其背书。

<p align="center"><img src="docs/assets/notch-preview.png" width="460" alt="Codex Lookout 顶部悬浮窗，展示合成会话的阶段与健康状态"></p>

使用合成会话数据，通过真实 SwiftUI 视图渲染；不包含私人会话。

## 能做什么

- 原生顶部悬浮窗：会话、子任务、阶段、健康状态、工具名称与耗时都在一处。
- 阶段与健康分开显示：最近有推理、输出或压缩记录，不等于模型此刻一直在做这件事。
- 持续 2 分钟没有可见进展时提示查看；重试和 token 用量统计不会被当成进展。
- 菜单栏备用入口；可设置数据目录、采样间隔、任务数量、显示位置、隐藏标题，以及自愿开启登录时启动。
- 可选的本机网页：搜索、筛选、事件时间线、用量计数，以及明确标注的合成演示。
- 本机只读：无需登录或 API Key，无遥测、无主动网络探针，不修改 Codex 配置，不中断任务。

当前界面为简体中文，同时提供中英文文档。

## 安装

需要 **Apple Silicon 芯片、macOS 13 或更新版本**。Intel 版尚未验证。

1. 在 [0.1.0 公开预览版](https://github.com/Kidz0419/codex-lookout/releases/tag/v0.1.0) 下载 macOS arm64 ZIP。
2. 解压，把 **Codex Lookout.app** 移到「应用程序」，然后打开。
3. 在首次使用窗口确认数据目录；默认读取 `CODEX_HOME`，未设置则使用 `~/.codex`。
4. 鼠标移到屏幕顶部查看会话；通过菜单栏图标打开设置或退出。

发行包自带 Python 运行时，使用者无需安装 Python、Xcode，也无需打开终端。默认构建仅有 ad-hoc 签名，**尚无 Developer ID 签名和 Apple 公证**；下载后 macOS 可能要求你明确批准打开，也可以自行从源码构建。发布验证与待验收设备情况见 [发布清单](docs/release-checklist.md)。

有刘海时按系统提供的安全区域定位；没有对应几何信息时放在顶部中央。不使用摄像头，不需要摄像头或辅助功能权限。登录时启动默认关闭。

## 如何理解状态

| 信息 | 含义 |
| --- | --- |
| 阶段 | 最近被记录的推理、输出、工具、等待或压缩活动；完成记录只说明刚发生过，不代表仍在持续。 |
| 近期有进展 | 观察到推理、输出、成功工具活动或压缩事件；不保证网络始终正常。 |
| 需要关注 | 120 秒没有可见进展、本轮明确连接异常，或运行状态未确认；结合下方原因判断。 |
| 距最近进展 | 错误重试和用量计数不刷新这个时间。 |
| 运行数量 | 按主会话合并子任务；最近失败或状态未知的会话可以留在列表中，但不算运行中。 |
| 数据过期 | 采集暂时不可用或更新延迟；保留的旧快照会明确标注。 |

默认每 **2 秒**采集最近 **200 个未归档本机会话**。设置可选择 2/5/10 秒和 100/200/500 个任务。本版不覆盖远端或云端会话。

无法可靠判断完成百分比、剩余时间、实时 token/s，或连接问题究竟来自本地网络、代理、服务商还是上游。长推理、安静运行的工具、记录延迟都可能表现为没有新事件。Codex 本地数据格式属于内部实现，升级后可能需要适配，详见 [信号说明](docs/signal-evidence.md)。

## 从源码运行

在 Apple Silicon Mac 上安装 Xcode command-line tools 和 Python 3.9+：

```sh
git clone https://github.com/Kidz0419/codex-lookout.git
cd codex-lookout
./native/build.sh
open 'dist/Codex Lookout.app'
```

开发构建依赖本机 Python。制作自带运行时的发行包，需要原生 arm64 Python 3.10+：

```sh
PULSE_BUILD_PYTHON=/path/to/python3 ./native/build.sh --release
python3 scripts/smoke-release.py 'dist/Codex Lookout.app'
./scripts/package-release.sh
```

构建依赖安装在项目的 `native/.build/`，不会全局安装。ZIP 和校验文件输出到 `dist/releases/`。详细流程见 [构建与签名](docs/building.md)。测试入口：

```sh
./scripts/test.sh
```

测试使用隔离的合成数据，不修改真实 Codex 会话。

## 可选网页

可以从原生菜单打开详细面板，也可以在源码目录运行：

```sh
python3 launch.py
# 自定义目录和端口：
python3 server.py --codex-home ~/.codex --port 4318 --limit 80
```

只监听 `127.0.0.1`，默认采集 80 个近期任务，每 3 秒更新。在终端启动的服务可按 Ctrl+C 停止。原生应用退出时只停止自己启动的服务，不停止独立运行的服务。

## 隐私与卸载

界面不返回完整提示词、思考文本、工具参数和输出、认证文件或压缩内容。**会话标题和项目路径本身仍可能包含隐私。**「隐藏标题」作用于原生界面，分享网页前需要单独检查内容。详见 [隐私说明](PRIVACY.md)。

卸载时，先关闭已启用的登录时启动，从菜单栏退出，再删除 **Codex Lookout.app**。独立终端启动的网页服务需在终端停止。卸载 Lookout 不会删除 Codex 会话。遇到目录、采集或显示问题可查看 [故障排查](docs/troubleshooting.md)。

欢迎兼容性修复、翻译、无障碍改进和经过脱敏的问题报告。项目采用 [MIT 许可证](LICENSE)，打包运行时保留各自许可证。
