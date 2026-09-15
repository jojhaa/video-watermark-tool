# 🎬 视频批量水印与全能处理工具 (Video Watermark Tool)

[![Version](https://img.shields.io/badge/version-V0.0.1-blue.svg)](https://github.com/jojhaa/video-watermark-tool/releases)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows-0078D6.svg)](https://github.com/jojhaa/video-watermark-tool)

一款基于 **Python + Tkinter + FFmpeg** 构建的高性能视频批量处理全能桌面工具。支持动态反弹/跑马灯文字水印、PNG Logo 图片水印、分辨率降采样、格式转换与一键提取 MP3 音频。内置 6 款开源免费商用中文字体，支持 NVIDIA NVENC GPU 硬件加速与 CPU 线程调控，并具备精确码率防膨胀保持功能。

---

## 🌟 核心特性

- **🛡️ 动态防盗文字水印**：支持对角线碰撞反弹、跑马灯滚动、斜向漂移、随机跳动及 5 种静态固定位置轨迹。
- **🖼️ PNG Logo 图片水印**：支持透明 PNG Logo 叠加、自定义尺寸与透明度，同样支持动态反弹。
- **🔤 内置开源商用字体**：
  - 【思源黑体】（默认推荐）
  - 【小米 MiSans】（极简现代）
  - 【思源宋体】（典雅传统）
  - 【站酷快乐体】（活泼卡通）
  - 【站酷黄油体】（视觉冲击）
  - 【站酷小薇体】（秀丽手书）
- **⚡ 性能与硬件加速**：
  - 默认开启 NVIDIA NVENC GPU 硬件加速（CPU 占用下降 80%）。
  - 自定义限制 CPU 线程数（默认自动使用 50% 核心线程，防卡顿）。
- **📦 原码率与体积保持**：
  - 自动通过多重算法精准捕获原视频码率（即使 FFmpeg 提示 `bitrate: N/A` 也可通过公式倒推）。
  - 严格限制 NVENC/libx264 编码峰值码率，彻底防止导出文件体积异常飙升（实测 1.4 小时网课视频处理后体积严格保持 220MB）。
- **📊 3 阶段高频实时进度显示**：
  - 细分为 `[1/3 解压解码]` -> `[2/3 修改渲染]` -> `[3/3 压缩编码]` 三阶段，每 0.2 秒实时刷新渲染进度 %、FPS 与加速倍速。
- **🔒 C 语言机器码防反编译保护**：
  - 核心逻辑采用 Cython + MSVC 编译为 `.pyd` 原生 C 机器码 DLL，彻底抹除 Python 字节码，防止源码被反编译。

---

## 🚀 快速使用 (下载即可运行)

无需安装 Python 或 FFmpeg 环境，直接下载 Release 发布包双击使用：

1. 前往 [Releases 页面](https://github.com/jojhaa/video-watermark-tool/releases/tag/V0.0.1) 下载最新版本。
2. 可选择：
   - **`video-watermark-tool-v0.0.1.exe`**：独立单文件版本，双击直接运行。
   - **`video-watermark-tool-v0.0.1-portable.zip`**：解压便携版本。

---

## 👨‍💻 作者与项目说明

- **程序作者**：详见软件主界面右上角专属署名及内置动态链接。
- **开源协议**：本项目遵从 [MIT License](LICENSE) 许可协议。
