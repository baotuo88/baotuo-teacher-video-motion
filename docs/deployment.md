# 单机上线与恢复手册

适用：Linux amd64、单管理员、单 API 进程、单 Worker、本机 Docker 数据卷。
建议至少 4 核 / 8GB 内存 / 30GB 可用磁盘；不要部署到 NFS 或同时启动多个 Worker。
这是一套有限范围的自部署候选版本，不是多租户 SaaS 或完全隔离的不可信代码平台。

## 1. 发布前门禁

- 全部 Python 测试、前端语法、Compose 校验通过。
- CI 构建容器，API/Worker 冒烟通过；**固定上游版本真实渲染通过后才发布 GHCR**。
- 使用镜像 digest 或 `sha-*` 标签部署，不建议生产长期追踪 `latest`。
- 真实模型联调、HTTPS、备份恢复演练必须在自己的环境单独验收。模拟 API 测试不等于供应商可用。
- Frametell 为 AGPL-3.0-only；部署前确认适用的源码提供和许可证义务，不能用进程隔离规避。

## 2. HTTPS 部署

将这些文件放在同一部署目录：`compose.registry.yaml`、`compose.production.yaml`、`deploy/Caddyfile`、`.env`。
复制 `.env.example`，生成至少 32 字符随机管理员密码及 Fernet Key；`.env` 权限设为 `600`。
不要把 `.env` 上传 GitHub。管理员 Key 与加密 Key 要另存离线安全位置。

```bash
# 先拉取已通过 CI 的指定镜像；以下是标签示例，替换为实际发布版本
# .env: IMAGE=ghcr.io/baotuo88/baotuo-teacher-video-motion:sha-73afc6f
# .env: DOMAIN=你的域名，ACME_EMAIL=证书邮箱
# .env: ADMIN_PASSWORD=随机密码，PROVIDER_ENCRYPTION_KEY=Fernet密钥
chmod 600 .env

docker compose -f compose.registry.yaml -f compose.production.yaml config --quiet
docker compose -f compose.registry.yaml -f compose.production.yaml pull
docker compose -f compose.registry.yaml -f compose.production.yaml up -d
```

域名 A/AAAA 应正确指向服务器；开放 TCP 80/443（可选 UDP443），**不要对公网开放 8000**。
Caddy 自动申请证书并设置 HSTS，API 启用 Secure Cookie。8000 仍只绑定宿主机回环地址。
代理使用 `172.30.99.0/24` 专用网络，只信任 Caddy 的 `172.30.99.2` 转发头；若与现有网络冲突，
同时调整网络段、Caddy 固定 IP 和 `FORWARDED_ALLOW_IPS`，不要改成 `*`。
使用 HTTPS 模式后，请从 HTTPS 域名登录，不再用 HTTP localhost 登录页面。

## 3. 初始化运行时（首次部署必须执行）

镜像不自动执行最新远端代码；首次部署 `/health` 正常而 `/ready` 返回 503 是预期行为。
审阅指定上游源码与许可后执行：

```bash
# 以下命令中的 compose 文件组合应与部署时保持一致
# 为缩短命令，bash 可定义函数：
dc() { docker compose -f compose.registry.yaml -f compose.production.yaml "$@"; }
dc exec console python -m app.cli --root /data/runtimes stage \
  --skill b19409957a9b08a3ae5e779a04f2f42559dc84d8 \
  --engine 6145f7e3482628543bd6f2d68fe3b618d366213a
dc exec console python -m app.cli --root /data/runtimes verify \
  1ead9de6eafc9d21a7f8aca1 --trust-reviewed-code
dc exec console python -m app.cli --root /data/runtimes activate 1ead9de6eafc9d21a7f8aca1
```

需要访问 GitHub/npm，验证会实际执行渲染，耗时数分钟，不调用付费模型。
更新仍采用 stage → verify → activate；不会自动支持上游每一项新功能。

## 4. 上线验收

1. 访问 `https://域名/health` 应返回 200（API 存活）。
2. 访问 `https://域名/ready` 应返回 200（数据库、Worker、空间、密钥和运行时就绪）。
3. 登录“运行状态”，确认全部检查通过；该页不会显示密钥。
4. 配置文本/图片/语音模型，先获取模型列表，然后确认费用后逐类生成一页，检查输出可用。
5. 确认分镜、应用生成素材，选择“上传配音 · 逐页 WAV”模式导出；下载 MP4/SRT 并人工检查画面、声音、字幕。
6. 重启 API/Worker，确认项目、配置、素材仍保留；Worker 中断不会自动重放可能收费的任务。
7. 按下一节备份，并恢复到一个**隔离的新目录/卷**验收，不要直接覆盖现网。

Worker 每 5 秒更新独立心跳，长时间渲染不会被误判死亡；30 秒过期判为未就绪。
Docker healthcheck 标记 unhealthy 不会自动重启活着但卡住的进程，需要外部告警及人工处理。
`MIN_FREE_DISK_MB`（默认1024）仅是提交任务/上传的剩余空间门槛，**不是硬配额**；
`MAX_PENDING_JOBS` 默认20，限制全局排队+执行中任务数；并非供应商费用上限。
容器日志轮转为每服务3×10MB。仍需监测磁盘使用，不自动删除历史素材或成片。

## 5. 备份与恢复（停机快照）

备份包含数据库、素材、成片及运行时，可能很大；包含敏感内容和加密 API Key，按机密文件保护。
**必须先停止 API 和 Worker**。工具会拒绝仍持有锁的 Worker，但无法代替人工确认 API 已停止。
备份不要放在 `/data` 内。另行保管加密密钥，否则恢复后不能解密已有 API Key。

```bash
mkdir -p backups
# 容器非 root UID=10001，挂载目录须允许该 UID 写入；不要 chmod 777
sudo chown 10001:10001 backups
sudo chmod 700 backups
dc stop console worker
# 选择唯一备份名；已有目录不会被覆盖
dc run --rm --no-deps -v "$PWD/backups:/backups" console \
  python -m app.backup backup /backups/backup-20261109 \
  --data /data --confirm-services-stopped
dc run --rm --no-deps -v "$PWD/backups:/backups" console \
  python -m app.backup verify /backups/backup-20261109
dc up -d console worker
```

备份使用 SQLite backup API 生成独立数据库、逐文件 SHA-256 清单和数据库完整性校验；不会自动归档/加密/上传异地。
校验用于发现意外损坏，不是抗恶意篡改签名。失败的备份不可用于恢复，保留失败现场或人工删除后重做。

恢复到空目录示例（需安装项目依赖；运行用户需有权限）：

```bash
PYTHONPATH=backend python -m app.backup restore backups/backup-20261109 \
  --data /安全位置/restored-data --confirm-services-stopped
```

Docker 可用同一 `dc run` 方式额外挂载一个空目标目录到 `/restore`，指定 `--data /restore`。
启动隔离实例时挂载恢复数据、设置**原来的** `PROVIDER_ENCRYPTION_KEY`，再验收历史项目、素材与下载。
禁止 `docker compose down -v`：它会删除数据卷。只备份 SQLite 文件不等于备份整套素材。

## 6. 升级与故障回退

1. 停止接收制作任务，确认没有运行中的任务，停机完成备份。
2. 记录当前镜像 digest、运行时 ID 和加密 Key 的保管位置。
3. 修改 IMAGE 为新版本，pull/up，执行 `/ready` 和实际一页视频验收。
4. 回退镜像前检查数据库兼容性；程序拒绝打开高于自身支持的数据库版本。
   不兼容时恢复升级前快照到新卷，再使用旧镜像；不要强行降级或手改 schema 版本。

## 已知边界

- 真实供应商接口/计费、DNS/TLS、镜像构建是否通过，必须看本次实际验收记录。
- 支持公开 HTTPS 的兼容接口，不支持任意私网 API、任意厂商异步任务协议。
- 尚无多租户、批量自动生成、共享连接轮换、完整 Skill 编码执行器及渲染网络强隔离。
- 上游代码是管理员批准的可信代码；不要允许不可信用户上传或任意切换执行代码。

### 探针与故障状态补充

- 就绪检查结果缓存 10 秒，避免外部探针重复触发源码扫描；修改配置后最多等待 10 秒再刷新。
- 已保存的服务密钥会进行本地解密校验，不会调用供应商 API；换成格式正确但不同的 Fernet Key 也会被判为未就绪。
- 数据库初始化失败、数据库版本不兼容或卷不可写时，`/ready` 返回 503，不返回内部路径或异常详情。
- 文本、图片、语音的付费请求超时或服务端 5xx 都可能已计费，任务显示“结果待确认”，不自动重试。
- 所有运行时必须保存在备份的数据根目录内。工具会将内部绝对符号链接转为相对链接，以支持换目录恢复；拒绝指向数据根目录外的链接。
- 可复现的本地恢复演练：先执行 `python scripts/generation-smoke.py`，再执行 `python scripts/recovery-smoke.py`。
  该演练只操作隔离副本，不停止、修改或备份当前在线服务。

### 可选的供应商出站代理

默认直连；如果部署主机无法稳定访问供应商，可由管理员设置 `PROVIDER_HTTP_PROXY=http://主机:端口`。
仅支持无认证 HTTP CONNECT 代理，不读取系统/浏览器代理，不允许 Web 用户配置代理。
连接使用已验证的公网目标 IP 建立隧道，并按原始供应商域名验证 TLS 证书；不会关闭证书校验或自动重放生成请求。
代理是管理员信任的网络基础设施，应只使用自己的代理。Docker 中 `127.0.0.1` 是容器自身，不能照搬本机代理地址。
连接失败发生在生成 HTTP 请求发出之前时显示 GEN_CONNECT；发送之后的超时/中断仍显示结果待确认。

### 项目制作配置迁移（数据库 v3）

- 本次代码首次启动会将 SQLite 升级为 v3，增加独立的项目制作设置表与任务/日志索引；旧项目默认静音，音色默认晓晓。
- 音轨、Edge 音色和文本模型服务选择按项目保存，不改变分镜版本；设置并发修改返回冲突，不盲目覆盖。
- 升级前应确认无运行/排队任务，停止 API 和 Worker，备份完整数据卷；两者必须使用相同版本再启动，不能混跑旧 Worker。
- v2 程序无法读取 v3 数据库。若回滚旧镜像，需恢复升级前的完整备份到新卷；不要手动修改 `user_version`。

### 项目回收站迁移（数据库 v4）

- 首次启动升级为 v4，增加 `project_trash` 表；移入回收站时保留分镜历史、制作设置、任务与文件，暂停项目编辑和新任务提交。
- 从「项目列表 → 回收站」恢复会提升项目版本及制作设置版本，以拒绝删除前旧标签页的写入；原项目ID、确认状态与任务归属保留。
- 此功能只覆盖升级后移入回收站的项目。旧版本已永久删除的项目不会自动找回；请检查升级前备份。
- 回收站暂不提供彻底删除，也不会释放素材/成片占用空间。它不是独立备份，仍需定期备份完整数据卷并异地保存。
- 升级前无活动任务时停止API/Worker并备份；两者同时更新。v3及更早程序不能读取v4数据库，回退旧镜像需恢复升级前完整快照到新卷，不能只修改 `user_version`。

### 浏览器回归发布门禁

- GitHub Actions 新增独立 `browser` job，使用锁定的 Playwright 依赖及 Ubuntu Chromium，运行七组关键浏览器行为回归。
- 测试使用临时数据目录、随机管理员凭据和仅API进程，不读取本地 `.env`、Skill运行时或生产数据，不启动Worker，不执行付费模型调用。
- `image` 依赖后端 `test` 和 `browser` 同时通过；原有容器启动/持久化验收与真实视频渲染门禁仍保留。
- 失败可查看 Actions 的 `browser-regression-evidence` 附件（保留7天）。本地复现见 `scripts/browser-tests/README.md`。
- 推送代码前本地通过不等同于远端Actions已通过；必须以该提交的Actions结果及镜像digest为准。

### 本地构建网络诊断与临时代理

Docker Hub鉴权超时不等于项目代码构建失败。先分别检查直连与受信任代理的Docker Hub连接；不要关闭TLS验证或随意替换镜像源。

若宿主机已有受信任HTTP代理，可仅为本次构建设置代理（示例端口需按实际修改）：

```bash
HTTPS_PROXY=http://127.0.0.1:7890 \
HTTP_PROXY=http://127.0.0.1:7890 \
NO_PROXY=localhost,127.0.0.1 \
docker build --progress=plain \
  --build-arg HTTPS_PROXY=http://host.docker.internal:7890 \
  --build-arg HTTP_PROXY=http://host.docker.internal:7890 \
  -t baotuo-teacher-video-motion:local-acceptance .
```

前两个变量用于宿主机Docker客户端鉴权请求；build-arg用于构建步骤中的包下载。`host.docker.internal`适用于Docker Desktop；Linux环境需单独确认代理地址和容器可达性。不要把代理凭据写入Dockerfile或提交到仓库；不要假设以上参数能替代Docker daemon自身的网络配置。

构建成功后仍须运行 `python3 scripts/image-smoke.py baotuo-teacher-video-motion:local-acceptance`，并执行容器内真实视频渲染验收。本地标签不是GHCR发布标签。
