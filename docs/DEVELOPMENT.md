# 开发与测试

## 模块

- `backend/app.py`：本地 HTTP 服务、会话/来源校验、API、SSE、worker 生命周期与静态页面。
- `backend/storage.py`：SQLite、迁移、事务和数据查询。
- `backend/filesystem.py`：来源登记、目录扫描、元数据、指纹。
- `backend/inference.py`：本地模型加载、CUDA/CPU、流式音频窗口与词级时间归属。
- `backend/worker.py`：串行队列、工作进程单实例锁、已有结果复用、内部结果生成。
- `backend/texts.py`：SRT 与段落处理。
- `backend/exports.py`：ZIP、预检查与不覆盖分发。
- `frontend/src/App.tsx`：任务与历史页面；`components`：文件选择器、虚拟列表、阅读面板及导出确认。

## 快速检查

在项目根目录，使用已安装依赖的 Python 3.11：

```bat
.venv\Scripts\python.exe -m compileall -q backend scripts tests
.venv\Scripts\python.exe -m pytest tests -q
cd frontend
npm ci
npm run check
npm run build
```

这些自动化测试使用临时目录，不需要真实模型权重。部分大目录测试使用伪造元数据；长音频窗口测试使用生成的正弦波。不要把它们说成语音准确率验收。Windows CI 运行同类检查，不下载模型、不使用真实视频。

`run_checks.bat` 还会运行环境 preflight，要求本机具备模型缓存。

## 安全开发方式

建议每次构建后由 FastAPI 同源提供页面，而不是暴露开发服务器：

```bat
set VIDOE_DATA=%TEMP%\video-dev-data
set VIDOE_NO_WORKER=1
.venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8765
```

`VIDOE_NO_WORKER=1` 适合 API/界面开发，不会执行推理。需要真实 worker 时清除它，并改用专用测试素材。不要对正在运行的生产数据库启动第二个后端。

Vite 配置保留了开发代理，但后端有严格的 Host/Origin 检查；不能假定跨端口代理上的写操作均可用。正式启动以 `start.bat` 同源页面为准。不要通过放开生产来源检查解决开发配置问题。

## 环境变量

| 名称 | 用途 |
|---|---|
| `VIDOE_DATA` | 内部数据库与结果目录；默认项目的 `data` |
| `VIDOE_NO_WORKER=1` | 关闭推理 worker，供测试和检查使用 |
| `VIDOE_NO_BROWSER=1` | 启动时不自动打开浏览器 |
| `VIDOE_TEST=1` | 测试专用 Host 例外；不要在正式运行时开启 |
| `VIDOE_PARENT_PID` | worker 由服务设置的父进程信息；不要手动配置 |
| `HF_ENDPOINT` | 显式模型下载所用的端点，可选 |
| `CUDA_PATH` / `CUDA_PATH_V12_8` | 可选的 CUDA DLL 查找目录 |

模型读取固定基于项目内缓存路径，下载脚本也将权重明确写入该路径，不依赖用户全局 HF_HOME。

## API 概览

- `/api/health`：轻量健康状态。
- `/api/session`：建立本地会话 cookie。
- `/api/system/status`：设备、模型与工作进程状态。
- `/api/fs/roots`、`/api/fs/list`：本地文件浏览。
- `/api/sources`、`/api/scans`：登记来源与扫描。
- `/api/batches`：批次、队列和进度。
- `/api/jobs/{id}/artifacts/{kind}`：读取结果。
- `/api/exports/preflight`、`/api/exports`：导出预检查及确认。
- `/api/events`：SSE 状态更新。

业务 API 需要本地会话；除明确允许浏览/登记路径的接口外，以资源 ID 操作。具体字段以 `backend/app.py` 与前端类型定义为准。

## 提交前

运行检查；确认没有视频、字幕、日志、数据库、模型、密钥、个人路径或历史备份进入提交。不要重新提交内部验收脚本。公开 Issue 应使用最小复现或合成素材，不上传未脱敏的任务数据库。
