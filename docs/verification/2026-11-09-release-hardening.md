# 单机上线加固验收（2026-11-09）

## 本轮实现

- Caddy HTTPS Compose 覆盖配置、Secure Cookie、限定可信代理 IP、日志轮转。
- 独立 Worker 5 秒心跳、容器健康检测；API liveness 与业务 readiness 分离。
- 管理端运行状态页：数据库、Worker、磁盘、管理员密码、密钥实际解密能力、已验证运行时。
- 就绪结果 10 秒缓存；数据库初始化异常返回未就绪，不泄露内部异常。
- 全局排队上限、剩余空间准入、流式请求体限制；登录与 Basic 共用线程安全限速。
- 非法 Origin/会话令牌安全拒绝；文本生成与图片/语音统一 unknown_outcome 状态。
- 停机备份、文件散列清单、数据库校验、空目录恢复；内部绝对链接重定位。
- CI 增加固定上游版本真实容器渲染门禁，成功之后才允许发布镜像。

## 已实际执行

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q`：120 passed，1 条第三方 TestClient 弃用警告。
- `node --check web/app.js`、`git diff --check`：通过。
- 本地构建、镜像部署、HTTPS 覆盖三种 Compose 配置语法校验：通过。
- `scripts/browser-system.cjs`：1440 / 768 / 390 宽度、就绪状态、刷新、无浏览器错误和横向溢出；人工查看手机截图。
- `scripts/browser-check.cjs`：导航、手机布局、真实视频 Range 下载 HTTP206，通过。
- `scripts/browser-capabilities.cjs`：三种能力配置、复用密钥、逐页生成对话框，通过（模拟服务）。
- `scripts/generation-smoke.py`：模拟供应商响应 + 真实 API/Worker/FFmpeg/Frametell，生成5.7秒真实视频、两版MP4、SRT、PNG。
  - 任务：`850f683ef24d41e792c6a7bdf42d0c3c`
  - 音频为440Hz测试音，不是真人配音；不代表真实供应商验收。
- `scripts/recovery-smoke.py`：完整隔离数据副本备份→校验→新目录恢复→删除源副本；
  4 个成片产物散列一致，3 个模拟服务配置保留，运行时源码校验通过，恢复后的链接全部指向恢复目录。
  报告：`.data/e2e/recovery-report.json`（不入 Git）。

## 当前发布状态与剩余验收

- 本地 Docker build 曾受 Docker Hub 网络超时阻挡，已通过 GitHub Actions 完成新镜像构建与真实容器渲染。
- 代码已推送；`73afc6f` 的 [Actions 42644496842](https://github.com/baotuo88/baotuo-teacher-video-motion/actions/runs/42644496842) 全部成功。
- `ghcr.io/baotuo88/baotuo-teacher-video-motion:sha-73afc6f` 已发布并确认可匿名读取；核对时 latest 与其摘要相同。
- 镜像索引摘要：`sha256:d71ec268da9567d7bbac71fe26b0bd1852636bc9513c1ac4d2e8972c9d23035c`，支持 Linux amd64。
- 当前本地回归121项通过；新增依赖下载适配测试保留原始锁文件与完整性字段。
- 剩余：真实供应商 API 端到端验收、公网域名/TLS 验收、真实生产数据卷恢复演练。

结论：已发布通过容器渲染验收的单机部署候选镜像；尚未部署到用户服务器。

## 发布执行补记

- 已推送 `556120b`，Actions `42642942520` 的测试、镜像构建、启动检查通过。
- 真实渲染门禁失败于依赖安装：上游锁文件使用的 registry.npmmirror.com 返回HTTP500（远端数据库错误）。GHCR发布按门禁跳过。
- 补充临时依赖目录安装适配：仅替换已知镜像域名为 registry.npmjs.org，保留版本、完整性字段，不修改上游原始锁文件；增加回归测试。
- 以上取代本文此前“尚未推送/CI尚未执行”的历史状态，后续运行以 Actions 为准。

第二轮发布：`73afc6f` 修复后所有门禁通过，成功发布GHCR，未跳过渲染检查。
