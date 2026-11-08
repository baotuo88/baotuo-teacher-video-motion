# 白板讲解视频 Web 工作台设计

日期：2026-11-08。状态：建议方案，尚未实现或部署。

## 1. 目标与范围

将 whiteboard-teacher-video-motion 的 Skill 工作流产品化：中文 Web 工作台、管理员配置外部服务、异步生成与渲染、Docker Compose 单机部署。

首版假定单管理员、单工作空间，默认渲染并发 1；不做公网多租户、计费、任意 JavaScript 编辑器或影视级视频生成。保留以后增加成员权限的空间，不先引入 Kubernetes、MinIO 或复杂插件市场。

原项目依据：[README](https://github.com/liangdabiao/whiteboard-teacher-video-motion/blob/b19409957a9b08a3ae5e779a04f2f42559dc84d8/README.md)、[SKILL](https://github.com/liangdabiao/whiteboard-teacher-video-motion/blob/b19409957a9b08a3ae5e779a04f2f42559dc84d8/SKILL.md)。

## 2. 推荐技术栈与部署

- Web：React + TypeScript + Vite + Tailwind，中文界面，表单编辑而非任意代码编辑。
- 服务端：FastAPI + SQLAlchemy + Alembic，复用 Python 素材/配音处理经验。
- 持久化：PostgreSQL 保存项目、版本、配置、任务及日志索引；本地命名卷保存素材和成片。
- 异步任务：Celery + Redis；数据库为任务状态的权威来源，Redis 不作为唯一状态存储。
- 渲染：独立 renderer，内置固定版本 Node、Chromium、FFmpeg、中文字体、Frametell 与配套脚本。
- 反向代理：Nginx 提供编译后前端并转发 /api，SSE 展示任务进度。

Compose 拓扑：

```text
浏览器 → web（唯一对外端口） → api → PostgreSQL
                              ↓
                            Redis
                              ↓
                    generation-worker（外部 API）
                              ↓ 制作版本/任务
                       renderer（浏览器/FFmpeg）
                              ↓
                       素材、预览和成片卷
```

api 与 generation-worker 使用同一应用镜像不同启动命令；renderer 单独镜像。renderer 仅连接内部网络与所需任务基础设施，不持有外部 API Key。渲染时拒绝浏览器访问非本机资源，不能仅依赖 Compose 网络隔离；不能将 Docker 容器视为任意恶意代码的充分沙箱。

构建时安装引擎和依赖，锁定源码 commit 与依赖版本，启动时不 git pull/npm install。原 setup.py 声明版本但没有真正锁定 clone 到该版本，需要替换此行为。视频工程存放 /data/projects，运行时存放 /opt/whiteboard，避免原项目限制的链接递归。

Compose 提供数据库/队列健康检查、迁移流程、持久化卷、资源限制、优雅退出和 restart 策略。非 root、cap_drop、no-new-privileges，不挂载 Docker socket；Chromium 沙箱兼容性需要实测，不能靠默认 --no-sandbox 作为安全方案。首次管理员密码、加密主密钥由部署配置提供，无默认公开密码。

## 3. 产品流程

1. 登录工作台，新建主题、受众、目标时长、风格和横竖屏。
2. 选择生成服务，提交“生成分镜”；前端可以关闭，任务继续。
3. 编辑每页标题、口播、画面说明，并明确确认分镜；未确认不得自动进入付费制作。
4. 按页生成/上传素材，选择配音和试听，支持局部重新生成。
5. 生成低分辨率预览和终态截图，检查图文是否一致；不把 lint 通过视为内容正确。
6. 提交不可变制作版本，渲染成片。
7. 下载有/无字幕 MP4 与 SRT，保存历史版本和失败原因。

页面：项目列表、新建向导、分镜编辑器、素材/配音工作区、预览与导出、任务中心、后台设置。

## 4. 深模块与接入方式

### Production Module

Interface：提交分镜生成、确认分镜、提交制作、查询/取消任务。内部隐藏阶段编排、版本、重复请求、费用风险、产物和恢复。

### Provider Module

Interface：按能力执行结构化文本生成、素材生成、配音及连接检查。Adapter 对应真实变化的协议，例如已有 Edge 配音/用户音频、HTTP 配音；不将每个供应商的字段扩散到业务代码。

### Render Module

Interface：render(制作版本, 输出规格) → 进度/产物，cancel(任务)。内部完成模板编译、工作目录准备、浏览器生命周期、缓存和 FFmpeg 检查。

首版采用“模型生成严格 JSON 场景描述 → 校验 → 受信任模板编译为 Frametell 页面”，不执行模型直接生成的任意 JS。模板先覆盖标题、要点、流程、对比、SVG 图解、局部动效六类。这样牺牲部分自由构图，换取稳定性与可编辑性；复杂手绘机械动效需要后续补模板，不宣称完整复刻 Skill 的开放式编码能力。

原 lib/motion-svg.js、素材拆帧/manifest 思路可复用；ftnew/ftrender 可先通过固定参数列表的子进程 Adapter 接入，但不开放任意命令。ftasset.py 的模型常量/apiz CLI 与 ftvoice.py 的固定后端必须拆出 Provider Adapter，不能只在网页增加 Base URL 输入框。

## 5. 后台自定义 API

每个服务配置：名称、协议类型、Base URL、模型、加密 Key、管理员可配置的有限自定义请求头、超时、并发限制、启用状态、支持能力、非敏感参数默认值。

能力分开：结构化文本、SVG、栅格图片、GIF/短动效、语音。各能力可以绑定不同配置；项目提交任务时保存配置版本和非敏感参数快照，密钥仅在执行时按引用解密，不嵌入制作文件。

首批 Adapter：

- 常见兼容聊天协议：结构化分镜生成，必须校验 JSON Schema，兼容服务不保证支持所有参数。
- Edge TTS：可选免费在线配音，不视为离线服务或可用性保证。
- 兼容语音 HTTP 协议：模型、音色、语速等由实际协议确定。
- 上传 SVG/GIF/PNG/JPEG/音频：无生成 API 时仍可制作。
- apiz 素材 Adapter：保留原有能力，前提是实测供应商服务仍可用。
- 后续增加明确供应商协议 Adapter；首版不提供任意 Python/JS 请求脚本。

“自定义地址”不等于“任意 API 自动兼容”。普通图片生成接口不会因此具备原生 SVG 或 GIF 输出。UI 显示能力矩阵，不支持的动作禁用；不能静默将 PNG 当 SVG 或将静态图片冒充动效。

连接测试默认不生成付费素材；实际小额调用需显式确认，分别检测文本、语音和素材能力。更改 Key 留空表示保持原值，清除必须显式操作；服务端永不回传明文 Key。

## 6. 数据与任务一致性

核心实体：Project、ProjectRevision、Scene、AssetRevision、ProviderConfig、Job、JobEvent、Artifact。

Job 状态：queued → running → succeeded / failed / cancel_requested → cancelled。分镜待确认是项目制作阶段，不是挂起中的 worker。

- 请求幂等键、任务版本唯一约束；任务执行租约和心跳，检测退出/崩溃。
- 数据库事务 outbox 投递到队列，重投递必须幂等；Celery 不提供业务恰好一次保证。
- 单项目写任务串行，不可变版本可供独立渲染；运行中编辑创建下一版本。
- 对付费请求记录提交意图和供应商 request/job ID；支持幂等键时传递。远端可能已收费而本地超时的请求标记“结果待确认”，不盲目重试。
- 取消终止实际子进程组和浏览器并回收租约，不仅改变 UI 状态。
- 缓存键覆盖模板/引擎版本、场景、配音和所有素材哈希；支持单页重渲。
- SSE 持久化事件序号及断线续传，阶段进度以实际事件报告，不伪造平滑百分比。

## 7. 安全与运维

- 登录、HttpOnly 会话、CSRF 防护、项目访问控制、下载鉴权、速率和磁盘配额。
- Key 使用认证加密保存，加密主密钥不在数据库；日志脱敏；备份时单独保护和备份主密钥。
- 自定义 Base URL 和素材下载均存在 SSRF 风险：限制 http/https，校验所有解析地址与重定向，默认阻止 loopback、链路本地/云元数据和非授权私网目标；私有模型仅由管理员明确授权特定主机/端口，防 DNS 重绑定并配置出站策略。
- 下载限时限量，校验真实文件类型；上传限制大小、像素、帧数，防解压炸弹和路径穿越。
- SVG 严格允许列表清洗，禁止脚本、事件属性、外部引用、foreignObject 等；不将上游的清洗直接视作安全审计通过。
- 首版用渲染视频/截图预览，不在应用同源页面内直接执行生成 HTML/JS。
- 任务工作目录隔离、临时文件清理、产物保留策略；备份数据库和产物卷，验证还原。
- 默认 1 个渲染 worker，建议从 4 vCPU / 8GB RAM 试运行并压测校准，不作为容量保证；amd64/arm64 浏览器与 FFmpeg 镜像均需验收。

## 8. 许可

原仓库自有代码 MIT，Frametell 为 AGPL-3.0-only。进程隔离、容器隔离均不自动免除许可义务。建议先按开源自部署产品设计；若闭源商用，先评估具体使用/修改/分发方式，必要时取得授权或更换引擎。开源参考只借鉴思路，不默认复制代码。

## 9. 分阶段交付与验收

A. 垂直闭环：Compose、登录、手工分镜、自带/上传素材、用户音频、单页预览与 MP4 导出；不依赖付费 API 验收。

B. AI 制作：加密服务配置、能力测试、结构化分镜、在线配音、素材生成和局部重试；使用 mock HTTP 服务验证自定义地址，再用已授权真实服务验收，不默认消费额度。

C. 稳定化：任务恢复/取消、缓存、版本历史、备份恢复、鉴权和 SSRF/上传安全测试、多页音画同步和资源基准测试。

必须实测：docker compose config/build/up；健康检查；中文字体；音视频轨与字幕；关闭浏览器后任务继续；worker 重启不重复付费；更换素材使缓存失效；Key 不进入响应/日志/产物；未经确认不开始付费制作；默认禁用外部服务时可以通过已有音频和素材导出样片。

## 10. 当前交付状态

当前只有研究和设计文档；没有可运行 Web 应用、Compose 文件或已验证渲染镜像。实施应优先验证 A 的真实渲染闭环，再扩展 UI 和 AI 功能。

## 11. 已核验的开源参考

只参考设计，不直接引入整套平台。下列 main 链接在本次调研读取，实施借用代码前应固定版本并重新审查许可。

| 项目 | 第一方依据 | 借鉴与限制 |
| --- | --- | --- |
| Dify | [Compose](https://github.com/langgenius/dify/blob/main/docker/docker-compose.yaml)、[LICENSE](https://github.com/langgenius/dify/blob/main/LICENSE) | API/worker 职责拆分、共享配置和健康检查；其许可证含多租户及品牌附加限制，非纯 Apache-2.0，不直接复制前端或平台。 |
| Open WebUI | [连接配置](https://github.com/open-webui/open-webui/blob/main/backend/open_webui/config.py)、[Compose](https://github.com/open-webui/open-webui/blob/main/docker-compose.yaml)、[LICENSE](https://github.com/open-webui/open-webui/blob/main/LICENSE) | 管理员持久化服务连接，容器内按服务名寻址，数据卷独立；当前 Open WebUI License 含品牌条件，不笼统视作 MIT/BSD。 |
| MoneyPrinterTurbo | [配置示例](https://github.com/harry0703/MoneyPrinterTurbo/blob/main/config.example.toml)、[LICENSE](https://github.com/harry0703/MoneyPrinterTurbo/blob/main/LICENSE) | 多语音后端的 base_url/api_key/model_id 配置思路；仓库 MIT，外部 API/素材仍独立授权。本次未验证其运行及部署拓扑。 |

后台连接帮助应特别注明：容器里的 localhost 指当前容器，不是宿主机或另一服务。内部服务优先填写 Compose 服务名；宿主机模型连接需显式配置允许的地址与网络策略。
