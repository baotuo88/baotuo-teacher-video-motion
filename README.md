# baotuo-teacher-video-motion

宝拓讲解视频工作台 · 基于可版本化 Skill 的视频制作平台。

基于版本化 whiteboard-teacher-video-motion / Frametell 的中文 Web 工作台。

> **当前是单机 Alpha，不是完整生产版。** 已打通浏览器创建项目 → 分镜编辑/确认 → 独立 Worker → 真实 MP4/SRT 导出。保留上游版本管理，不将计划功能写成已完成。

## 已实现

- 管理员登录：HttpOnly 会话、CSRF 校验、登录限速；保留 Basic 认证供 CLI 使用。
- 项目列表、项目复制、分镜新增/编辑/排序/删除；五种风格与三种受控布局。
- 乐观锁版本编辑、分镜确认、历史版本查看/恢复；任务保存不可变项目快照。
- 自定义**兼容聊天协议**的分镜模型：服务地址、模型、加密 Key、启用/禁用。AI 结果先审阅再应用，不自动覆盖。
- 独立持久化任务队列、幂等提交、阶段日志、实际子进程取消、显式重试；Worker 重启将运行中任务标为 interrupted，不自动重复付费请求。
- 静音画面预览和 Edge 在线配音路径；横屏 1920×1080、有/无字幕 MP4、SRT、预览图。
- Skill/引擎 commit 锁定、源码检查、候选样片验证、激活/回滚、文档查看。候选下载和验证目前走 CLI。

## 仍未完成

- 自定义图片/语音 API、素材上传和管理、SVG/GIF 在自定义项目里的编辑集成。
- 完整受控 Skill 编码执行器；目前读取 Skill 文档生成结构化分镜，再由受控模板编译，不执行模型任意代码。
- 多机、多租户、多 Worker、生产级渲染网络隔离、数据库迁移体系、磁盘配额/清理、端到端备份恢复。
- 上游新增能力自动识别/适配和后台一键下载/验证；当前不会宣称任何上游更新自动兼容。
- 真实自定义模型与 Edge 服务的线上验收：未提供账号，未消耗付费额度；分镜协议使用 mock 测试。

## 本地开发

需要 Python 3.11+（已测试 3.13）、Node >=22.19、Chrome/Chromium、ffmpeg/ffprobe。

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements-dev.txt
python scripts/dev.py
```

首次启动自动生成 `.env`（权限 600），管理员密码保存在其中，**不会打印到日志**。打开 http://127.0.0.1:8000，读取 `.env` 中的 `ADMIN_PASSWORD` 登录。该脚本同时启动 API 和独立 Worker，Ctrl+C 会停止两个进程。它不会自动下载或执行未知上游源码。

也可手动设置 `ADMIN_PASSWORD`、`PROVIDER_ENCRYPTION_KEY`、`PYTHONPATH=backend`，分别运行：

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
python -m app.worker
```

`DATA_ROOT` 默认 `.data`，`RUNTIME_ROOT` 默认 `.data/runtimes`。不要把数据卷放在 NFS；当前只允许一个 Worker，OS 文件锁防止重复启动。SQLite WAL 保存项目、版本、配置与队列。数据库/密钥/产物都需要备份，丢失加密密钥无法恢复 API Key。

## 首次准备 / 更新 Skill

```bash
export PYTHONPATH=backend
python -m app.cli check
python -m app.cli stage --skill <完整40位commit> --engine <完整40位commit>
# 审阅源码后，在隔离测试环境执行；这一步会执行上游代码
python -m app.cli verify <运行时ID> --trust-reviewed-code
python -m app.cli activate <运行时ID>
```

不得使用浮动 main/latest 替代 commit。静态检查不等于兼容；verify 使用自带 SVG/GIF 和静音样片验证，并不证明所有新增功能或供应商可用。之后可在后台切换已验证版本。任务提交时固定运行时，升级不改变已提交任务。

使用系统 FFmpeg：可设置 `FFMPEG_PATH`；浏览器可用 `CHROME_PATH` 指定。运行时源码不得手动修改。新能力仍需适配器及界面更新，而不是 git pull 后自动拥有全部功能。

## 模型服务

部署必须配置 `PROVIDER_ENCRYPTION_KEY`（Fernet key；开发脚本会生成）。后台填写完整 API 基地址，例如 `https://your-provider.example/v1`，请求会追加 `/chat/completions`。配置使用常见兼容聊天协议；第三方服务可能不兼容，须逐一验收。

当前仅允许公网 HTTPS 443，不允许本机/私网/带凭据 URL；DNS 解析后绑定公网 IP、保持 TLS 域名校验、不跟随重定向、不继承代理。暂不支持本地 Ollama 等私网服务，也不支持任意请求脚本。保存不触发付费调用；生成前明确确认可能计费。Key 加密保存、不回显、不进入任务快照；子进程环境不继承 Key 或管理员密码。

## Docker Compose

```bash
cp .env.example .env
# 设置随机 ADMIN_PASSWORD 和 PROVIDER_ENCRYPTION_KEY
# 后者生成命令见 .env.example
 docker compose up -d --build
 docker compose exec console python -m app.cli --root /data/runtimes check
# 同样使用 stage / verify / activate 准备容器内的运行时
```

提供 API 控制台和独立 Worker，默认只监听宿主机 127.0.0.1:8000，共享持久化卷。容器非 root、cap_drop、no-new-privileges，Worker 默认限制 2 CPU/4GB RAM。并非不可信代码沙箱；Alpha 只编译受控模板，不对外开放任意代码执行。

**目前 Compose 配置校验通过，但 Docker Hub 鉴权端点连接超时，尚未完成镜像 build/up 验证。** 容器中的 Chromium、沙箱和不同 CPU 架构仍需实测。不要把本机渲染成功等同于 Docker 部署成功。

公网部署前配置 HTTPS、`COOKIE_SECURE=1`、可信反向代理和访问控制；当前登录限速为单 API 进程内计数。完整生产审计未完成。

## 测试

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
node --check web/app.js
# 启动 dev.py 后，可显式运行浏览器测试（会创建项目并渲染，不调用付费服务）
node scripts/browser-smoke.cjs
# 成片完成后检查界面、移动端和视频分段下载
node scripts/browser-check.cjs
```

本机全局 pytest 插件会崩溃，因此验证时禁用自动插件加载。单元测试不调用付费服务；已准备 `.data/runtimes/active.json` 时会额外测试真实引擎多页字幕时间戳。

浏览器端到端操作和本机真实渲染结果见 [验证记录](docs/verification/2026-11-09-workspace-alpha.md)。

## 设计与许可

- [完整交付范围](docs/design/delivery-plan.md)
- [总体设计](docs/design/web-workbench.md)
- [版本化运行时](docs/adr/0001-versioned-upstream-runtime.md)
- [单机持久化队列取舍](docs/adr/0002-single-host-durable-worker.md)

原 Skill 自有代码 MIT，Frametell 引擎 AGPL-3.0-only。进程/容器隔离不免除许可义务，商用及分发前审阅相关条款。自身许可证尚待确定；参考项目只借鉴设计，没有复制其平台源码。

## GitHub 自动构建与发布

已提供 [GitHub Actions](.github/workflows/image.yml)：推送 `main` 或 `v*` 标签时先测试，再构建 **linux/amd64** 镜像，通过容器启动/持久化/Worker 检查后发布至 `ghcr.io/baotuo88/baotuo-teacher-video-motion`。PR 仅检查，不发布；自动使用 `GITHUB_TOKEN`，无需提供模型 API Key 或管理员密码。

服务器可直接拉取镜像，无需安装源码或本地构建：

```bash
# 在服务器 .env 设置 IMAGE=ghcr.io/baotuo88/baotuo-teacher-video-motion:latest
# 同时设置该服务器自己的 ADMIN_PASSWORD 和 PROVIDER_ENCRYPTION_KEY
docker compose -f compose.registry.yaml pull
docker compose -f compose.registry.yaml up -d
```

初次部署仍须准备上游运行时。自动发布镜像不等于自动部署服务器，也不等于自动升级 Skill。完整上传、GHCR 权限、私有镜像、初始化及更新步骤见 [GitHub 镜像部署说明](docs/design/github-container.md)。

镜像是否已发布以仓库 Actions 和 Packages 的实际结果为准。 `.env`、`.data` 和本地密钥被 Git/Docker 忽略，CI 另检查跟踪文件，切勿手动上传这些内容。

## 仓库与镜像

- 项目名称：`baotuo-teacher-video-motion`
- GitHub：https://github.com/baotuo88/baotuo-teacher-video-motion
- 构建记录：https://github.com/baotuo88/baotuo-teacher-video-motion/actions
- 镜像：`ghcr.io/baotuo88/baotuo-teacher-video-motion:latest`（首次工作流成功后可用）
