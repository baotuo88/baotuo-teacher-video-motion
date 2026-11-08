# whiteboard-teacher-video-motion 项目分析

核验日期：2026-11-08。源码版本：`b19409957a9b08a3ae5e779a04f2f42559dc84d8`。

## 结论

这是一个带配套脚本、素材处理组件、示例和参考文档的 Agent Skill，不是单独的视频生成模型，也不是现成的网页视频编辑器。根目录 SKILL.md 提供 name、description、触发场景与执行流程，且明确声明为独立 Skill。

来源：[SKILL.md](https://github.com/liangdabiao/whiteboard-teacher-video-motion/blob/main/SKILL.md)、[README](https://github.com/liangdabiao/whiteboard-teacher-video-motion/blob/main/README.md)。

## 实现

- AI 助手负责分镜、口播与页面代码；脚本负责建工程、素材、配音、检查与渲染。来源：[README 工作流](https://github.com/liangdabiao/whiteboard-teacher-video-motion/blob/main/README.md)。
- SVG 由 P.vector 逐笔绘制；GIF 拆帧后按引擎时间轴播放，而非直接播放 GIF。来源：[motion-svg.js](https://github.com/liangdabiao/whiteboard-teacher-video-motion/blob/main/lib/motion-svg.js)、[ftasset.py](https://github.com/liangdabiao/whiteboard-teacher-video-motion/blob/main/scripts/ftasset.py)。
- Frametell 引擎在安装时另行拉取，渲染产物为 MP4 与字幕；不是依赖安装上游 whiteboard-teacher-video 项目。来源：[setup.py](https://github.com/liangdabiao/whiteboard-teacher-video-motion/blob/main/scripts/setup.py)、[ftrender.py](https://github.com/liangdabiao/whiteboard-teacher-video-motion/blob/main/scripts/ftrender.py)。
- 环境包括 Python、Node >=22.19、Chrome/Edge、git，以及 Pillow、edge-tts、npm 依赖。来源：[package.json](https://github.com/liangdabiao/whiteboard-teacher-video-motion/blob/main/package.json)、README。

## 使用边界

适用于知识讲解、流程说明、结构图、产品原理等白板动画，而非真人数字人或电影级连续视频。仓库所称的模型型号、供应商报价和成片测试成绩仅为作者描述，此次未独立验证外部服务，也未安装依赖或执行渲染。

免费与离线不可混为一谈：示例素材可本地复用，但首次安装要下载依赖，默认 Edge TTS 配音要访问在线服务；自备音频或已有缓存才可能避免配音联网。来源：[ftvoice.py](https://github.com/liangdabiao/whiteboard-teacher-video-motion/blob/main/scripts/ftvoice.py)、[edge_tts_speak.py](https://github.com/liangdabiao/whiteboard-teacher-video-motion/blob/main/scripts/edge_tts_speak.py)。

许可：本仓库自有代码标为 MIT，引擎为 AGPL-3.0-only；将其产品化时需要单独评估引擎许可义务，不能将整个依赖链视作 MIT。来源：[许可说明](https://github.com/liangdabiao/whiteboard-teacher-video-motion/blob/main/vendor/ATTRIBUTION.md)。

本次只读克隆到 `/tmp/whiteboard-teacher-video-motion-review` 分析，没有将它安装为本地技能，也没有执行仓库脚本。
