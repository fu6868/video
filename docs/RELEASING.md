# 干净源码发布

## 原则

**排除，不删除。** 本机应用继续保留运行环境、模型和历史结果；GitHub 只存源码、配置、锁文件、测试、安装/启动脚本和公开文档。

| 保留在源码仓库 | 仅保留本机，排除发布 |
|---|---|
| backend / frontend/src | .venv、venv、node_modules |
| 前端配置与 package-lock.json | frontend/dist、缓存、tsbuildinfo |
| requirements-app / requirements-lock | huggingface_cache、模型权重 |
| setup / start / run_checks | data、数据库、识别文本、ZIP、日志、PID |
| 通用模型下载/环境检查工具 | 源视频、音频、字幕文件 |
| 通用测试、公开 docs、CI | 备份、个人验收脚本、内部 MCP 日志与计划 |

安装启动脚本不是要去掉的“运行垃圾”，删除它们会让克隆者无法安装使用。模型权重和运行数据库不需要 Git LFS，本项目直接不上传它们。

## 生成 ZIP

```bat
.venv\Scripts\python.exe scripts\package_source.py
```

产物：

- `releases/video-source.zip`：顶层目录 `video/`，不含 .git 或运行目录。
- `releases/video-source.manifest.json`：文件清单、大小和 SHA-256，不含本机绝对路径。

工具只读允许清单中的源码，拒绝链接、超大文件及若干常见凭据模式；不会打包个人课程、历史报告或复制依赖。它只是基础防漏检查，不能替代人工安全审查。新增源码目录/公开文档时，应同步维护其清单。

GitHub 的 Code → Download ZIP 则来自 Git 已跟踪文件，因此还应检查暂存区；`.gitignore` 不会移除已经提交的文件。

## 提交前

```bat
git status --short
git diff --cached --stat
git ls-files
```

确认：

- 没有媒体、模型、任务数据、日志、绝对个人路径或凭据。
- 锁文件保留，构建产物排除。
- README 不引用被排除的个人验收原件。
- 自动化测试、TypeScript 与构建通过；不要宣称尚未执行的真实推理或 CI 已通过。

首次发布优先显式添加所需路径，不要无检查地 `git add .`。提交后使用普通 `git push -u origin main`，不要强推。远程出现新提交时先检查其内容。

## GitHub 登录与提交身份

HTTPS 推送需要本机可用的 GitHub 授权。推荐 Git Credential Manager 浏览器登录或 GitHub CLI 的交互登录。不要在聊天、README、远程 URL 或脚本里粘贴访问令牌。

提交身份与 GitHub 推送授权是两回事。按你希望显示的署名设置仓库级 `user.name` 和 `user.email`；如需要保护邮箱，可从 GitHub 邮箱设置中复制自己的 noreply 地址。

## 发布标签与许可证

需要 GitHub Release 时，在确认提交后由维护者创建版本标签，并附上源码 ZIP 与校验信息。本次普通推送不自动发布版本或修改仓库可见性。

本仓库已由维护者选择采用 [MIT License](../LICENSE)，版权署名为 `Copyright (c) 2026 fu6868`。发布源码 ZIP 时必须包含根目录 `LICENSE`，保留版权及许可声明；打包工具会自动纳入该文件。第三方依赖与模型继续适用各自上游许可。
