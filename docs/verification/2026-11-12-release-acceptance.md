# 发布前完整链路与恢复验收

## 本轮新增验证

- 后端完整回归：172 passed；既有Starlette/httpx弃用警告1项。
- 七组隔离浏览器回归通过，不读取真实凭据或启动付费任务。
- `generation-smoke.py` 使用模拟文本/图片/语音供应商，经过真实API/Store/Worker与引擎产出两份MP4（5.7秒）、SRT与预览图。
- 更新生成验收：图片完成后直接提交语音，验证媒体自动应用延续确认，不再通过重复确认掩盖问题。
- `recovery-smoke.py` 在隔离副本将真实渲染项目移入回收站并保存制作设置，再备份到空目录、删除源副本、换目录恢复。
  验证回收站项目可恢复、制作设置保留、版本历史连续、任务入口可达、4个产物SHA256一致、3个模拟供应商与运行时完整、符号链接不依赖原目录。
- 新增自动化v4备份恢复测试，将以上数据管理行为加入日常后端回归。
- README与发布记录整理为“本地待发布功能”与“旧版已发布镜像”两个清晰状态，不使用旧CI结果担保当前代码。

## Docker网络诊断

- 直连 `auth.docker.io` 超时，显式使用已有本地HTTP代理响应200。
- 仅为当前build命令设置宿主机HTTP(S)_PROXY与构建步骤代理参数，无系统/daemon代理改动、无TLS降级、无镜像源替换。
- 重试成功拉取官方Node/Python基础镜像并进入系统依赖安装，说明前一次鉴权阻塞已绕过；构建与容器验收最终结果见下。

## 安全与边界

不修改真实项目、不调用付费生成、不上传.env或.data；未提交/推送Git或发布GHCR。
本地恢复演练不是生产服务器备份恢复演练；真实供应商、公网HTTPS与正式部署仍需环境验收。

## 镜像构建与启动验收补录

- 使用仓库原Dockerfile成功构建Linux amd64本地镜像 `baotuo-teacher-video-motion:local-acceptance`。
- 本地image ID：`sha256:022faf2190582ed9035d69274b5706e6b1679f51672a2929e2af1e3427305be1`（本地镜像ID，不是GHCR发布digest）。
- `python3 scripts/image-smoke.py baotuo-teacher-video-motion:local-acceptance` 通过：API、鉴权、持久化、回收站恢复、制作设置、非root用户、独立Worker与Node/Chromium/FFmpeg。
- 检查镜像环境，临时构建代理没有写入最终镜像环境。
- 同一镜像真实视频渲染验收通过（退出码0）：固定上游commit获取、依赖安装、SVG/GIF样片、1920×1080带音轨视频，以及项目实际MP4输出均通过。命令采用与CI相同的 `container-render-smoke.py`，只额外传入临时网络代理；无付费API调用。日志仅保存在本地 `.data/e2e/container-acceptance-20261112.log`。
- 测试容器与临时测试卷清理完成，现有业务服务未重启/改动。当前仅本地镜像验证成功；尚未推送代码、运行此次远端Actions或发布GHCR。

## 远端发布跟踪

- 累计功能提交 `abef853` 已推送main。
- 首次远端运行：[43221872863](https://github.com/baotuo88/baotuo-teacher-video-motion/actions/runs/43221872863)。后端test通过；browser中前四组通过，production-state日志保留断言失败，image正确跳过，没有发布。
- 根因：测试只等待空日志节点出现，未等待异步内容到达就断言日志内容。给模拟日志响应固定增加300ms延迟后本地稳定复现同一失败。
- 修正等待条件为日志内容实际可见，保留节点身份/内容断言与模拟延迟，不跳过或放宽发布门禁。本次修复仅测试/文档，不新增用户功能，因此沿用同日更新条目。

## 最终远端发布结果

- 修复提交 `66c068d` 已推送main；[Actions 43225375605](https://github.com/baotuo88/baotuo-teacher-video-motion/actions/runs/43225375605)状态success。
- test、browser（Ubuntu受管理Chromium全部七组）、image全部成功；镜像构建、启动/持久化、固定上游与实际视频渲染、GHCR发布各步骤均成功。
- 固定镜像：`ghcr.io/baotuo88/baotuo-teacher-video-motion:sha-66c068d`。
- Registry manifest摘要：`sha256:e52648e1d7bcb592f9a77164ed4d17de73eb4db25f777100c44038f3cb9dfc80`；匿名获取成功并校验响应内容SHA256，latest摘要相同。平台为linux/amd64；额外unknown平台条目为构建证明，不表示支持其他CPU架构。
- 最终文档更新仅记录发布证据，不引入新用户功能；README保留同日单个最新更新区块，发布说明未重复追加日期。
- 尚未部署到用户公网服务器，未自动更新Skill，未调用付费供应商。原文中“未推送/未发布”为此前阶段记录，以本段最终结果为准。
