# baotuo-teacher-video-motion

宝拓讲解视频工作台 · 基于可版本化 Skill 的视频制作平台。

基于版本化 whiteboard-teacher-video-motion / Frametell 的中文 Web 工作台。

> **当前为单机自部署候选版本，尚未完成全部上线验收，不是完整多租户生产版。** 已打通浏览器创建项目 → 分镜编辑/确认 → 独立 Worker → 真实 MP4/SRT 导出。保留上游版本管理，不将计划功能写成已完成。

## 最新更新

### 2026-11-12

- 项目内完成分镜、图片与配音、导出和结果查看，支持桌面与手机布局。
- 生成结果安全应用并提供检查建议，制作配置按项目记忆。
- 草稿支持对比、导出和另存，历史任务支持分页及完整日志下载。
- 项目回收站支持恢复历史与成片入口，实时刷新保留播放器和日志阅读状态。

完整历史见 [更新记录](docs/releases/release-notes.md)。**以上功能代码已推送，镜像仍待发布验收，旧镜像不包含这些更新。**

## 最新发布进展

**此前版本镜像已发布，其 GitHub Actions 门禁通过；当前累计更新尚未发布。** 旧版发布代码：`73afc6f`（Linux amd64）。

- [CI 验收记录](https://github.com/baotuo88/baotuo-teacher-video-motion/actions/runs/42644496842)：测试、镜像构建、启动/持久化检查、真实容器视频渲染、GHCR发布全部成功。
- 固定镜像：`ghcr.io/baotuo88/baotuo-teacher-video-motion:sha-73afc6f`，已验证匿名读取。
- 镜像摘要：`sha256:d71ec268da9567d7bbac71fe26b0bd1852636bc9513c1ac4d2e8972c9d23035c`。
- 真实供应商与公网服务器 HTTPS 尚未验收；镜像发布不等于已经部署到你的服务器。

## 部署基础与验收状态

新增 HTTPS/Caddy 部署覆盖配置、独立 Worker 心跳与容器健康检查、后台“运行状态”面板、
请求体限制、统一登录/Basic 限速、磁盘/队列准入限制、日志轮转，以及可校验的停机备份/空目录恢复工具。
CI 保留固定上游版本真实容器渲染门禁，并新增关键浏览器回归。**当前版本已通过本地镜像构建、启动/持久化及真实容器视频渲染验收，尚未发布；不能用旧版 Actions 结果代表本次改动。**

部署、运行时初始化、备份、恢复、升级步骤见 **[单机上线手册](docs/deployment.md)**。
本地后端回归 **172 项通过**，七组隔离浏览器回归通过；历史上线加固记录见[验收文档](docs/verification/2026-11-09-release-hardening.md)，新增界面与发布门禁见[浏览器CI验收](docs/verification/2026-11-12-browser-ci.md)，本轮镜像和完整备份恢复结果见[发布前验收](docs/verification/2026-11-12-release-acceptance.md)。

**当前数据库为 v4。** 升级前备份完整数据卷，API 与 Worker 同步升级；旧镜像不能读取 v4 数据，回退需要恢复兼容的升级前备份。
真实供应商与公网 HTTPS 尚待部署环境验收；未擅自消耗 API 额度。

## 已实现

- 管理员登录：HttpOnly 会话、CSRF 校验、登录限速；保留 Basic 认证供 CLI 使用。
- 项目列表、项目复制、分镜新增/编辑/排序/删除；五种风格与三种受控布局。项目内五阶段工作流，任务实时日志和成片入口。
- 按项目保存制作设置；草稿冲突对比、导出与另存；历史任务分页与完整日志下载；项目回收站/恢复。
- 乐观锁版本编辑、分镜确认、历史版本查看/恢复；任务保存不可变项目快照。
- 自定义**兼容聊天协议**的分镜模型：服务地址、模型、加密 Key、启用/禁用。支持文本、图片和语音能力配置、模型列表获取及手动填写；新任务结果安全自动应用，提供本地规则检查建议（不等同于事实或媒体质量审核）。
- 独立持久化任务队列、幂等提交、阶段日志、实际子进程取消、显式重试；Worker 重启将运行中任务标为 interrupted，不自动重复付费请求。
- 素材库：静态 PNG/JPEG/WebP 上传、预览、搜索、归档；16-bit PCM WAV 上传和试听。
- 分镜绑定图片与逐页 WAV：图片搭配要点，配音按真实时长生成时间轴，素材 SHA-256 校验后复制到独立任务目录。
- 静音画面预览、上传配音和 Edge 在线配音路径；横屏 1920×1080、有/无字幕 MP4、SRT、预览图。
- Skill/引擎 commit 锁定、源码检查、候选样片验证、激活/回滚、文档查看。候选下载和验证目前走 CLI。

## 仍未完成

- 更多供应商专用协议、SVG/GIF 在自定义项目里的安全上传和编辑集成。
- 完整受控 Skill 编码执行器；目前读取 Skill 文档生成结构化分镜，再由受控模板编译，不执行模型任意代码。
- 多机、多租户、多 Worker、生产级渲染网络隔离、数据库迁移回滚工具、硬磁盘配额/自动清理、真实部署环境的备份恢复演练。
- 上游新增能力自动识别/适配和后台一键下载/验证；当前不会宣称任何上游更新自动兼容。
- 真实文本/图片/语音供应商与 Edge 服务的线上验收：本轮验收不调用真实付费接口；模拟供应商通过不代表全部真实服务可用。

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

部署必须配置 `PROVIDER_ENCRYPTION_KEY`（Fernet key；开发脚本会生成）。后台选择文本、图片或语音能力并填写 API 基地址，例如 `https://your-provider.example/v1`。分别使用兼容的聊天、图片生成或语音合成接口；支持获取模型列表，失败时可手动填写。第三方协议仍须逐一验收。

当前仅允许公网 HTTPS 443，不允许本机/私网/带凭据 URL；DNS 解析后绑定公网 IP、保持 TLS 域名校验、不跟随重定向、不自动继承系统代理。可由管理员显式设置受信任的 `PROVIDER_HTTP_PROXY`，详见部署手册；Docker Hub 构建代理与模型出站代理是不同配置。暂不支持本地 Ollama 等私网服务，也不支持任意请求脚本。保存不触发付费调用；生成前明确确认可能计费。Key 加密保存、不回显、不进入任务快照；子进程环境不继承 Key 或管理员密码。

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

**旧版镜像通过容器启动、持久化、Worker 与真实视频渲染检查。** 当前累计更新也通过本地容器验收，但尚未发布到GHCR；其他CPU架构及生产环境仍需实测。不要把本机渲染成功等同于新镜像部署成功。

公网部署前配置 HTTPS、`COOKIE_SECURE=1`、可信反向代理和访问控制；当前登录限速为单 API 进程内计数。完整生产审计未完成。

## 测试

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
node --check web/app.js
# 隔离浏览器回归：不使用真实项目/Key，不启动Worker
npm ci --prefix scripts/browser-tests
(cd scripts/browser-tests && npx playwright install --with-deps chromium)
python scripts/browser-ci.py
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

已提供 [GitHub Actions](.github/workflows/image.yml)：推送 `main` 或 `v*` 标签时先通过后端与浏览器测试，再构建 **linux/amd64** 镜像，通过容器启动/持久化/Worker 和真实视频渲染检查后发布至 `ghcr.io/baotuo88/baotuo-teacher-video-motion`。PR 仅检查，不发布；自动使用 `GITHUB_TOKEN`，无需提供模型 API Key 或管理员密码。

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
- 镜像：`ghcr.io/baotuo88/baotuo-teacher-video-motion:latest`（目前对应已发布旧版；新版本以对应提交的 Actions 验收为准）


## 素材与编辑器（当前开发版本）

素材库支持静态 PNG/JPEG/WebP 和 16-bit PCM WAV，单文件最多20MB。图片最多1600万像素，重新编码为PNG并移除元数据；WAV支持单/双声道、8–96kHz、0.2–120秒。暂不接受SVG/GIF/MP3。

在每页分镜中选择图片和配音：绑定图片后采用左文右图；导出选择「上传配音 · 逐页 WAV」时所有页面必须绑定音频，时长由音频决定。保存/重排不会丢失音轨选择。归档只从库中隐藏，不删除历史项目引用的文件。暂未做物理删除和存储配额。

编辑器分为宽分镜区和分组设置栏，提供分镜导航、固定保存操作、弹窗素材选择；桌面/平板/手机均有独立布局。上传失败会在弹窗内显示原因，不要求离开编辑器。

数据库从v1自动执行增量建表至v2，不覆盖旧项目；检测到未来版本会拒绝启动。旧镜像不具备该门禁，**升级前备份数据库，不得把旧版镜像直接连接已升级数据库**。

素材端到端验收（会创建素材和项目，音频为测试音，不是真人口播）：

```bash
python scripts/media-fixtures.py
node scripts/browser-assets.cjs
```

## 自动获取模型（当前开发版本）

模型服务页填写 Base URL 与 API Key 后，点击「获取模型列表」。后端请求基地址下的 `GET /models`，读取兼容格式 `{"data":[{"id":"model-id"}]}`，列表去重排序，支持搜索并选择。无需先保存配置；获取失败仍可手动填写模型 ID。

编辑已保存的服务时，Key 留空可使用数据库里的加密密钥；更改 Base URL 后必须重新输入 Key（保存配置也遵循此限制），避免将旧密钥发送给另一个服务。列表获取不保存草稿、不覆盖当前模型、不调用生成接口，也不自动跟随重定向或重试。

支持公网 HTTPS 443，保留 DNS 公网校验和 IP 绑定；超时20秒、响应最大2MB、最多5000个模型条目。列表成功只说明服务能返回模型信息，不保证模型支持聊天或当前Key具有生成权限。非兼容协议、需分页的列表、私网模型服务暂未支持。

开发验证使用 mock 网络响应，不需要真实 API Key；不宣称已经验证你的服务商。浏览器回归：`node scripts/browser-models.cjs`（需 dev.py 运行，响应由测试拦截，不保存模拟配置）。


## 文本、图片、语音生成（当前开发版本）

模型服务新增能力类型：文本分镜、图片生成、语音合成。每项可选择模型、读取模型列表。语音可填音色ID和语速；图片可选尺寸或不发送尺寸，由服务商决定。

1. 添加文本、图片、语音配置；同一地址可选择已有配置复用加密Key，无需明文回显。
2. 生成分镜并应用，或手动编辑；保存并确认当前版本。
3. 每页点击「AI生成图片」或「AI合成配音」，选择对应能力配置，确认可能计费。
4. 任务完成后预览图片/试听音频，点击「应用到本页」；应用产生新草稿，不自动替换确认版。
5. 所有页配音就绪后，重新确认分镜，导出选择「上传配音 · 逐页WAV」（也适用于生成入库的配音）。

协议范围明确限定：文本 `POST /chat/completions`；图片 `POST /images/generations`，返回 `data[0].b64_json` 或 `data[0].url`；语音 `POST /audio/speech`，发送 model/input/voice/speed/response_format=wav，返回二进制音频。不是任意HTTP服务自动兼容，不支持异步供应商任务轮询、任意鉴权或音色自动发现。具体模型是否支持尺寸/语速等参数需由实际服务验证。

图片URL下载单独校验公网HTTPS与DNS，不携带生成服务的Authorization、不跟随重定向。音频经受限FFmpeg转为单声道24kHz PCM WAV，沿用0.2–120秒限制。所有产物进入现有素材库并记录任务/配置版本/模型来源，不保存Key。

请求超时或供应商5xx可能已计费，任务标记「结果待确认」，不会自动重试；需要先核对服务商账单，再显式重试。调用期间取消不保证供应商停止计费。项目修改或分镜重排后拒绝自动应用旧结果，但可从素材库手动选择。当前配置修改后排队任务会拒绝执行，而非静默换模型。

**实现范围与设计差异：** 当前在现有Provider记录上增加能力类型，复用Key是建立新的密文副本，不是共享连接的统一密钥轮换。全局能力默认、不可变连接版本、独立测试中心、缺失素材批量计划仍待实现。配置复用后，源配置密钥变化不会同步到副本，须分别维护。

验证：`python scripts/generation-smoke.py` 在隔离目录模拟三类供应商返回，真实执行API、队列、素材处理与渲染；`node scripts/browser-capabilities.cjs` 使用mock检查界面，不调用付费服务。没有真实服务商验收前，请勿将此称为全自动生产链路已经上线。
