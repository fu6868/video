# 安装与环境准备

## 安装前

1. 安装 64 位 Windows CPython 3.11，确保命令 `py -3.11 --version` 成功。不要用 MSYS Python 代替。
2. 安装 Node.js 22 LTS 或更新兼容版本，确认 `node --version`、`npm --version` 成功。
3. 克隆或下载本仓库到普通用户可写目录。避免直接放在系统受保护目录。
4. 准备联网安装依赖的条件。日常推理可以只读取已准备好的本地权重，但首次安装依赖和主动下载模型需要网络。

## 标准安装顺序

1. 运行 `setup.bat`。它不会清理用户数据；存在 `.venv` 时会保留环境。
2. 如果提示 small / medium 模型缺失，先不要反复重装 Python。使用下列命令主动准备两个模型。
3. 运行 `scripts/preflight.py` 检查，再运行 `start.bat`。

```bat
.venv\Scripts\python.exe download_model.py small
.venv\Scripts\python.exe download_model.py medium
.venv\Scripts\python.exe scripts\preflight.py
start.bat
```

`setup.bat` 当前安装 `requirements-app.txt` 中的直接依赖；需要尽可能复现已记录的 Windows 环境时，可执行：

```bat
.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
```

锁文件是环境快照，不包含 CUDA 驱动、cuDNN 动态库、模型或 npm 依赖。前端依赖由 `frontend/package-lock.json` 与 `npm ci` 管理。

## 模型缓存位置

模型定位基于项目根目录，不依赖盘符。需要完整结构，例如：

```text
huggingface_cache/hub/
  models--Systran--faster-whisper-small/
    snapshots/<revision>/
      config.json
      model.bin
      tokenizer.json
      vocabulary.txt
  models--Systran--faster-whisper-medium/
    snapshots/<revision>/
      config.json
      model.bin
      tokenizer.json
      vocabulary.txt
```

从其他电脑迁移 Hugging Face 缓存时，请连同必要的 `blobs`、`refs` 和链接目标一起保留；不要只复制断开的 snapshot 链接。程序要求上述四项文件非空。

下载工具默认从 Hugging Face 获取 `Systran/faster-whisper-small` 或 `Systran/faster-whisper-medium`，保存到项目内缓存。不会在此时处理用户视频。需要代理/镜像时，请自行确认服务可信后显式设置环境变量；不要把凭据写入脚本或提交 Git：

```bat
set HF_ENDPOINT=https://你信任的镜像地址
.venv\Scripts\python.exe download_model.py small
```

完成后可执行 `set HF_ENDPOINT=` 清除当前 CMD 窗口中的设置。

## GPU 与 CPU

- GPU 优先模式使用 CUDA、`int8_float16`；CPU 使用 `int8`。
- GPU 模型初始化或实际推理失败时，程序可使用同一模型回退到 CPU，界面显示实际设备和回退原因。
- CUDA 环境需满足当前 CTranslate2 的要求。通常涉及 CUDA 12 与 cuDNN 9，但具体版本与安装方式以对应上游版本文档为准；本项目不会自动安装系统驱动或 CUDA。
- Windows 上请留意 cuBLAS / cuDNN DLL 的可访问性。程序尝试加载 Python 环境中 `nvidia/*/bin` 以及 `CUDA_PATH` / `CUDA_PATH_V12_8` 指向的 `bin`。
- CPU 回退属于可用路径，不是 GPU 已验证的证明。

检查硬件：`nvidia-smi`。实际初始化探针：

```bat
.venv\Scripts\python.exe scripts\preflight.py --smoke
```

该探针加载 small 并执行初始化推理，不等于完整的中文/英文视频质量验收。medium 的实际使用还需在应用中选择 medium 并处理有权使用的测试素材。

上游参考：
- https://github.com/SYSTRAN/faster-whisper
- https://opennmt.net/CTranslate2/installation.html

## 常见问题

### “py / npm 不是内部或外部命令”

确认安装了相应组件，关闭并重开终端。Python Launcher 命令为 `py -3.11`，不要只依据默认 `python` 的版本判断。

### 安装结束报本地模型缺失

新仓库不包含权重，这是预期情况。完成显式下载或放置缓存后重跑环境检查。

### 端口 8765 被占用

启动器会检测是否已有可识别的映言实例：同一应用运行时会打开页面；其他程序占用时会提示。不要随意结束不明进程。先确认占用程序再处理。

### 网页空白或提示未构建

在 `frontend` 目录运行 `npm ci`、`npm run build`，然后使用 `start.bat` 访问 FastAPI 提供的同源页面，而不是双击 `frontend/index.html`。

### 下载失败

检查网络、可写空间和所选下载端点。不要禁用 TLS 校验。删除或重建缓存前先备份有效权重，避免无必要的重复下载。

### 停止、升级与备份

在启动窗口按 `Ctrl+C`。升级前在服务停止后备份 `data` 与必要模型缓存，再拉取新代码并重新运行安装/检查。复制正在写入的 SQLite 主文件而忽略 WAL 不能当作可靠备份。
