# 单机工作台 Alpha 验证

日期：2026-11-09。本轮交付可运行的垂直流程，不代表完整生产版已交付。

## 自动测试

`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q`：41 项通过，1 项第三方 TestClient 弃用警告。

覆盖：运行时锁定/完整性/激活门禁、项目版本冲突、确认失效、历史版本不可变、任务快照、幂等提交、并发领取、恢复不自动重试、排队取消与真实子进程取消、密钥加密/留空保留、SSRF 地址和 DNS 私网拒绝、mock 分镜生成、JS 字符串转义、会话/CSRF/登录限速、多页独立音轨与真实引擎字幕时间。

`node --check web/app.js` 和 `docker compose config --quiet` 通过。

## 浏览器真实操作

Playwright + 本机 Google Chrome，1440×1000 桌面视口：

1. 管理员登录；创建自定义项目“铅笔的秘密 · 多页验收”。
2. 添加两页分镜，分别使用逐条讲解与步骤流程布局；编辑口播和要点。
3. 保存 v2、确认分镜、提交静音制作任务。
4. 关闭测试浏览器后，独立 Worker 继续渲染。
5. 任务完成，产出 MP4、SRT、预览 PNG。
6. 检查项目、模型设置、运行时、任务四个页面，无 JavaScript pageerror。
7. 390×844 移动视口无横向溢出。
8. 登录后 MP4 Range 请求返回 206、video/mp4、1024 字节；支持浏览器按需读取。

截图留在 `.data/e2e/`，测试脚本为 `scripts/browser-smoke.cjs`、`scripts/browser-check.cjs`。测试脚本会显式创建项目，不作为应用启动时动作。

## 实际产物

修正字幕时间后运行的任务 ID：`8c84cd5a077d41b79a5ea3db72a7d71d`。

- 运行时 `1ead9de6eafc9d21a7f8aca1`，Skill/引擎固定 commit。
- 两页、24fps、1920×1080，约9.208秒。
- `.data/jobs/<任务ID>/project/out/video-有字幕.mp4`
- `.data/jobs/<任务ID>/project/out/video-无字幕.mp4`
- 同目录 `字幕.srt` 与 `preview.png`。
- 本次音轨为静音验证，不声称已有真实配音；未消费任何付费 API。

发现并修复：上游时间轴对于带 o=0 的音频片段不添加 pageEnd 停顿，原本复制的手工字幕规则在第二页错位0.3秒。现在直接调用候选运行时的 `engine/tools/script.mjs` 生成字幕；回归测试核对第二页开始 3.700秒，不再由平台复制引擎时间规则。

## 限制与未验收

- Docker Hub auth.docker.io 获取基础镜像 token 超时；镜像 build/up 和容器内 Chromium 未通过验收。
- 自定义聊天 API 使用 mock 适配测试，尚未配置/调用真实供应商；官方参考页面请求被阻止，不依赖未读取页面作兼容性保证。
- Edge 在线配音路径已编码，当前机器缺少 edge-tts 且未调用该在线服务；安装 requirements 后仍须单独验收。
- 无素材上传、图片/语音自定义 API、完整 Skill 编码执行器、跨任务增量缓存、多机队列、完整生产隔离和备份还原验收。
- 本地 dev.py 会同时启动 API/Worker、首次生成权限600的 .env；不向日志打印密码。默认仅本机访问。
