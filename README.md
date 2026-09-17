<div align="center">

# 映言 · 本地视频转写工作台

**视频留在原处，字幕与文字稿由你决定如何导出。**

Windows 本地运行 · faster-whisper · React + FastAPI · SRT / TXT

[安装指南](docs/INSTALL.md) · [使用说明](docs/USAGE.md) · [开发与测试](docs/DEVELOPMENT.md) · [安全说明](SECURITY.md)

</div>

---

映言是一款通过浏览器操作的本地视频转写工具。它直接读取你选择的视频或多层文件夹，使用本机模型生成原语言字幕和文字稿，不需要把视频复制到项目目录或上传云端。

```text
选择视频 / 文件夹 → 递归扫描 → 勾选并转写 → 阅读结果
                                              ├─ 字幕 SRT → ZIP / 原位分发
                                              └─ 文字稿 TXT → ZIP / 原位分发
```

## 功能

- **本地文件浏览**：在网页内浏览磁盘、多选来源、递归扫描，支持粘贴绝对路径；不使用视频上传控件。
- **批量转写**：支持 small（快速）与 medium（标准）模型，逐视频识别语言，也可手动指定语言。GPU 优先，失败时可回退到同一模型的 CPU 推理。
- **原语言结果**：生成 SRT 字幕、TXT 文字稿或两者；不做自动翻译、摘要、润色或简繁转换。
- **长视频处理**：PyAV 流式解码，约一分钟的有界音频窗口；工作进程串行处理视频。
- **进度与恢复**：显示处理状态、实际音频位置及队列信息；支持当前视频结束后暂停、重试异常任务及历史批次。
- **结果阅读**：查看文字稿与字幕时间轴、复制全文；当前搜索主要用于字幕列表。
- **独立导出**：字幕与文字稿分别打包或分发，可重复导出而不重新调用模型。
- **保护源文件**：结果先保存在应用内部；分发需确认，已有同名文件默认跳过，不覆盖、不自动改名。

> 当前同名不同扩展名的视频可能产生导出命名冲突。请在创建批次时每组只选一个，详见[使用说明](docs/USAGE.md#命名冲突)。

## 系统要求

| 项目 | 要求 |
|---|---|
| 操作系统 | Windows 10 / 11，64 位；安装与启动入口以 Windows 为目标 |
| Python | CPython **3.11**，安装时包含 Python Launcher（`py`） |
| 前端工具链 | Node.js **22 LTS 或更新的兼容版本**及 npm；项目记录中的验证版本为 Node 24 |
| 模型 | 本地 faster-whisper `small` / `medium`；仓库不包含权重 |
| GPU | 可选 NVIDIA CUDA 环境；不可用时使用 CPU int8，速度会降低 |
| 空间 | 需要另行预留依赖、模型、内部结果和 ZIP 导出空间；源码包不包含这些文件 |

GPU 运行还依赖与 CTranslate2 兼容的 CUDA/cuDNN 动态库。仅检测到显卡不代表推理可用，详见[安装指南](docs/INSTALL.md#gpu-与-cpu)。

## 快速开始

### 1. 获取源码

```bat
git clone https://github.com/fu6868/video.git
cd video
```

也可使用 GitHub 的 **Code → Download ZIP**，解压到可写目录。项目不要求放在某个固定盘符或名为 `vidoe` 的文件夹中。

### 2. 安装依赖与构建网页

双击 `setup.bat`，或在项目目录执行：

```bat
setup.bat
```

脚本创建/复用项目内 `.venv`，安装 Python 依赖，安装前端依赖并构建网页。不会删除现有视频、模型、数据库或结果。

**新克隆的仓库没有模型。** 如果安装最后一步提示模型缺失，这是预期的前置条件提示；先完成下一步，再重跑 `setup.bat` 或环境自检。

### 3. 显式准备模型

如果已有完整模型缓存，把它放到项目的 `huggingface_cache` 目录；否则在安装过依赖后执行以下命令。它们会联网下载权重，属于你主动触发的操作：

```bat
.venv\Scripts\python.exe download_model.py small
.venv\Scripts\python.exe download_model.py medium
.venv\Scripts\python.exe scripts\preflight.py
```

也可以双击 `download_model.bat`，分别选择 small 和 medium。目前环境自检检查两个模型，因此建议两者都准备。应用日常转写只加载本地权重，**不会静默下载模型**。

### 4. 启动

```bat
start.bat
```

就绪后自动打开 **http://127.0.0.1:8765**。浏览器关闭不会取消后台任务；要停止整个应用，请在启动窗口按 `Ctrl+C`。

## 常用操作

1. 添加文件夹或视频，等待扫描并勾选需要处理的条目。
2. 选择输出格式、模型和语言，开始转写。
3. 打开已完成任务，查看结果来源、文字稿或字幕。
4. 选择“打包 ZIP”下载，或确认“分发到视频旁边”。两种格式与两类导出操作互不排斥。
5. 从历史记录重新打开批次、继续导出或重试异常项。

结果文件只替换原视频最后一个扩展名，例如：

```text
01. Interview.final.MP4
01. Interview.final.srt
01. Interview.final.txt
```

## 仓库结构

```text
backend/                 API、扫描、队列、推理、文本处理和导出
frontend/                React + TypeScript + Vite 前端源码及锁文件
scripts/start.py         本机启动器
scripts/preflight.py     环境检查与可选推理初始化探针
scripts/package_source.py  可重复的干净源码打包工具
tests/                   使用临时目录的自动化测试
docs/                    安装、使用、开发、发布和验证说明
setup.bat / start.bat     Windows 安装、启动入口
run_checks.bat           本地自检入口
requirements-app.txt     应用直接依赖
requirements-lock.txt    Windows 环境依赖快照
```

`.venv`、`node_modules`、`frontend/dist`、`huggingface_cache`、`data`、日志、备份及个人验收记录只在本机保留，不进入 Git。详细范围见 [发布说明](docs/RELEASING.md)。

## 测试与验证

```bat
run_checks.bat
```

不加载模型的代码测试可单独执行：

```bat
.venv\Scripts\python.exe -m pytest tests -q
cd frontend
npm run check
npm run build
```

项目内曾记录 Windows/GPU、多层目录、长音频和实际批量转写验收。公开仓库仅保留[脱敏验证摘要](docs/VALIDATION.md)，不发布课程素材、识别文本、个人路径或任务数据库。这些记录不是识别准确率或所有硬件兼容性的保证。

## 边界与隐私

- 这是**单机工具**，不是公网多人服务。不要用 ngrok、反向代理或 `0.0.0.0` 暴露后端。
- 不包含 OCR、翻译、说话人分离、摘要、文本编辑、视频播放器、烧录字幕和云端同步。
- 语音识别可能出错，正式使用前请核对字幕，尤其专有名词、数字及多人重叠语音。
- 仅处理有权使用的素材。分享截图、日志和导出结果前请自行脱敏。

## 许可

本项目采用 [MIT License](LICENSE)，版权归 **2026 fu6868** 所有。允许使用、修改、商用和再分发（包括闭源复用），但必须保留版权及许可声明。软件按“原样”提供，不作任何担保，完整条款以 `LICENSE` 为准。

第三方依赖与模型各自适用其上游许可证，权重未随本仓库分发；本项目的 MIT 许可不替代它们的许可。
