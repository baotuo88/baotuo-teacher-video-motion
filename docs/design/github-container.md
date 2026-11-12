# GitHub 自动测试、构建与发布镜像

## 已提供的配置

`.github/workflows/image.yml` 包含三个阶段：

1. **test**：Python 3.13 + Node 24；安装依赖、阻止跟踪本地密钥/数据、运行 pytest、前端语法检查、两份 Compose 配置校验。
2. **browser**：隔离API和数据库运行七组浏览器回归，不读取生产凭据，不调用付费接口；失败上传测试证据。
3. **image**：等待test和browser通过后，Buildx 构建 linux/amd64 镜像；实际启动 API 与 Worker 容器，验证鉴权、项目持久化、非 root 和 Node/Chromium/FFmpeg 工具；再验证固定上游样片与真实视频渲染，通过后发布到 GHCR。

触发规则：

| 事件 | 测试/构建 | 发布 |
| --- | --- | --- |
| 推送 main | 是 | latest + sha-短提交号 |
| 推送 v 开头标签，例如 v0.2.0 | 是 | v0.2.0 + sha-短提交号，不覆盖 latest |
| 向 main 提交 PR | 是 | 否，不登录 GHCR |
| Actions 手动运行 | 是 | 仅 main 或 v 标签允许发布 |

镜像地址按实际仓库自动生成并转换为小写：`ghcr.io/<owner>/<repository>`。
目前**仅构建 linux/amd64**。arm64 浏览器/渲染仍未验收，不先承诺多架构支持。

## 上传项目

项目仓库：https://github.com/baotuo88/baotuo-teacher-video-motion 。以下命令用于首次初始化上传，已有 Git 仓库不必重复执行。

在 GitHub 新建空仓库，然后在本地执行（替换账号与仓库名）：

```bash
git init -b main
git add .
# 提交前确认暂存区没有 .env / .data / API Key
python3 scripts/check-publish-files.py
git diff --cached --stat
git commit -m "feat: initial whiteboard studio alpha"
git remote add origin https://github.com/baotuo88/baotuo-teacher-video-motion.git
git push -u origin main
```

如果选择网页上传，必须包含 `.github/workflows/image.yml`；不能把整个文件夹连同 `.env`、`.data` 一起上传。推荐 Git 上传，以便 .gitignore 生效。密钥一旦提交，仅删除文件不够，必须轮换密钥并清理历史。

## GitHub 设置

- 仓库 Settings → Actions → General：启用 Actions，允许所用 Actions；组织策略可能限制第三方 Action 或 packages 写入权限。
- 工作流对构建发布 job 请求 `packages: write`，使用 GitHub 自动注入的 `GITHUB_TOKEN` 登录 GHCR，**不需要把管理员密码、模型 Key 或个人 PAT 放进 workflow**。
- 首次发布后在账号/组织的 Packages 页面找到镜像，按需求设置 Public；不要假设公开仓库的镜像自动公开。
- 如日志出现 denied，检查 package 是否已经由其他仓库拥有、该仓库是否被授予 Actions access，以及组织权限策略。
- PR 不发布。不要改成 `pull_request_target` 后执行不可信分支代码。

## 从镜像部署（无需服务器编译）

服务器只需要 `compose.registry.yaml` 和本地 `.env`：

```bash
cp .env.example .env
# 编辑 .env，设置自己的强密码与密钥，加入：
# IMAGE=ghcr.io/baotuo88/baotuo-teacher-video-motion:latest
# 生产更推荐固定 v 标签或 sha256 digest

docker compose -f compose.registry.yaml pull
docker compose -f compose.registry.yaml up -d
```

`ADMIN_PASSWORD` 至少16位；加密密钥可在已拉取镜像中生成：

```bash
docker run --rm --entrypoint python ghcr.io/baotuo88/baotuo-teacher-video-motion:latest \
  -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

将结果写入服务器 `.env` 的 `PROVIDER_ENCRYPTION_KEY`，妥善备份，**后续升级不能随意重新生成**，否则数据库已有 API Key 无法解密。不要把本地开发密码原样用于公网部署。

控制台和 Worker 使用同一个镜像、不同启动命令，数据保存在 `runtime-data` 命名卷。默认监听服务器 127.0.0.1:8000，需要 HTTPS 反向代理，或通过 SSH 隧道访问：

```bash
ssh -L 8000:127.0.0.1:8000 user@your-server
```

私有镜像先登录 GHCR：使用具备包读取权限的凭据（通常为 classic PAT 的 read:packages；组织可能要求 SSO 授权）。不要把凭据直接拼进命令或提交进仓库：

```bash
printf '%s' "$GHCR_TOKEN" | docker login ghcr.io -u baotuo88 --password-stdin
```

## 首次运行时安装

镜像包含平台和系统工具，**不包含上游 Skill、引擎、项目、管理员密码或 API Key**。首次部署仍须下载并验证固定版本：

```bash
docker compose -f compose.registry.yaml exec console python -m app.cli --root /data/runtimes check
docker compose -f compose.registry.yaml exec console python -m app.cli --root /data/runtimes stage \
  --skill <完整commit> --engine <完整commit>
# 管理员完成代码审阅后执行；会安装依赖并执行上游代码
docker compose -f compose.registry.yaml exec console python -m app.cli --root /data/runtimes verify \
  <运行时ID> --trust-reviewed-code
docker compose -f compose.registry.yaml exec console python -m app.cli --root /data/runtimes activate <运行时ID>
```

基础容器smoke不下载上游；后续独立渲染步骤会下载固定commit并执行样片与项目真实MP4渲染，不调用付费API。服务器首次安装仍需执行上述verify，CI通过不代替目标环境验收。

## 后续发布与更新

- 平台代码 push main：触发镜像构建与发布，**不会自动更新服务器**。
- 服务器更新：先备份数据库和数据卷，在无运行中任务时执行 pull、up -d；避免直接杀掉正在渲染的 worker。
- 发布版本：`git tag v0.2.0 && git push origin v0.2.0`。
- 回退镜像：将 IMAGE 改回先前标签/digest，up -d；数据库兼容性另行确认，不承诺任意跨版本回退。
- 上游 Skill 更新：独立使用 stage/verify/activate，**不等于重新构建平台镜像**。新功能仍需相应适配器/界面。

## 当前验证边界

提交 `66c068d` 已通过[全部发布门禁](https://github.com/baotuo88/baotuo-teacher-video-motion/actions/runs/43225375605)并发布 `sha-66c068d`，匿名读取核验成功。数据库为v4，升级前停止接收任务、备份完整数据卷并同步更新API/Worker；旧版程序不能直接读取v4。真实供应商、公网HTTPS及生产环境恢复演练仍需部署现场验收。
