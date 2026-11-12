# 浏览器CI与镜像验收门禁

## 实现

- `scripts/browser-test-support.cjs` 统一七组测试的启动配置，保留本地单脚本模式；隔离模式不读取.env或.data/runtimes。
- `scripts/browser-tests/package-lock.json` 固定 Playwright 1.65.0 与完整性摘要，独立npm依赖不进入产品镜像；`.dockerignore`排除嵌套node_modules。
- `scripts/browser-ci.py` 使用临时数据库/运行时目录、随机密码/加密Key、临时端口及API-only进程，串行运行七组回归、保存日志/截图/结果，退出时清理API及失败子进程。
- 隔离模式浏览器阻止非测试origin网络访问；模拟供应商/任务接口，不启动Worker或真实付费生成。
- GitHub Actions增加browser job，Ubuntu安装受管理Chromium；image改为依赖test和browser。截图/测试日志附件保留7天。
- 扩展 `image-smoke.py`，增加制作设置、移入回收站后容器重启、恢复项目与历史入口检查。该扩展尚未在新镜像中执行，原因见下。

## 已验证

- 后端171项通过，一项既有Starlette/httpx弃用警告。
- 在本机用临时API/数据库执行全部7组隔离浏览器回归，通过；结果见本地 `.data/browser-ci/results.json`。
  包含布局、分镜阶段、草稿恢复、输入保护、项目内任务、回收站、制作设置、播放器保留、历史分页和日志。
- npm ci和完整性锁文件安装通过；依赖审计报告0 vulnerabilities（非完整安全审计）。
- workflow YAML可解析，image的needs包含test/browser。
- Compose本地构建配置与registry+production配置以占位环境变量检查通过，未输出或读取部署凭据。
- `check-publish-files.py`、JS语法、Python脚本编译、`git diff --check`通过。

## 验收限制（不能宣称已发布）

1. 本机macOS12不受当前Playwright受管理Chromium支持，`playwright install chromium`明确失败。
   隔离浏览器验收使用 `BROWSER_TEST_CHROME=/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`。
   CI配置使用Ubuntu受管理Chromium，但本轮没有推送，尚无远端Actions运行结果。
2. 尝试 `docker build --progress=plain -t baotuo-teacher-video-motion:local-acceptance .` 失败于Docker Hub基础镜像鉴权网络：
   `https://auth.docker.io/token` 连接超时，尚未执行应用构建。
   未更换不可信镜像源、未关闭TLS校验、未修改系统Docker代理/DNS。
3. 因新镜像未构建出来，本轮没有完成容器启动/回收站扩展验收或真实容器视频渲染，未发布任何新镜像。
4. 没有提交/推送Git；本次主要改动为测试和CI，未重启或修改现有本地业务服务。

## 下一步

恢复Docker Hub连通后重跑镜像构建 → image-smoke → container-render-smoke；或在准备好发布后推送并检查该提交的GitHub Actions。
推送前仍需统一检查所有累计未提交改动、更新README/发布说明，不能只推CI文件而漏掉测试所需的新业务代码和脚本。

后续进展：宿主机临时代理使Docker Hub鉴权与基础镜像下载恢复，进入构建依赖安装；原超时不是应用编译错误。最终结果见 [发布验收](2026-11-12-release-acceptance.md)，本记录中的“本轮构建失败”是此前尝试结果。
