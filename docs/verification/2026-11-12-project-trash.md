# 项目回收站与恢复验收

## 行为

- 「删除项目」现在明确提示移入回收站，可从项目列表恢复。未保存编辑不会进入回收站，确认框提醒先导出或另存。
- 正在排队/运行的项目仍拒绝移入。删除与提交/领取使用SQLite写事务串行化。
- 将活动项目行移入独立 `project_trash` 表，既有编辑、确认、提交、自动应用等活动项目检查继续生效；不删除revisions、production_settings、jobs、events、素材和成片。
- 回收站弹窗显示项目标题、页数、版本、移入时间，提供恢复、刷新及失败提示；没有彻底删除按钮/API。
- 恢复保持项目ID和所有历史引用，新增一个版本并按原状态延续确认；制作设置版本同步提升（包括原先没有设置行的默认配置），防止旧标签页覆写。
- 重复恢复/过期版本返回404/409，不覆盖已有项目；恢复不重新执行任务。
- 仅覆盖本次升级后移入项目，旧版已永久删除的项目不会凭空恢复。

## 验证

- `test_project_trash.py`：历史、制作设置、任务快照保留，恢复确认状态与版本；回收站期间提交拒绝；旧项目/设置写入冲突；鉴权、CSRF；v3→v4迁移；并发恢复只创建一次；重启后恢复。
- 既有删除测试更新为验证保留历史/设置，继续覆盖活动任务拦截与SSE removed通知。
- `browser-project-tasks.cjs`：取消删除无副作用、确认移入、回收站查看、恢复冲突后项目仍在、恢复后列表出现且版本更新、桌面/390px弹窗无横向溢出，全部通过。
- 数据库变更为v4。确认本地无queued/running任务后，使用SQLite backup API保存 `.data/backups/studio-before-v4-20261112-011724.sqlite3`（600权限），同步重启API/Worker。此备份只保护本次数据库迁移，不等于完整素材/运行时备份。
- 没有修改/删除真实项目来演示回收站；业务写入测试均使用临时数据库或浏览器模拟接口。未调用付费生成接口。

## 未完成

回收站没有分页或彻底清理策略；完整数据备份仍是管理员责任。SSE负载测试、浏览器CI、统一发布验收仍待后续。当前仍是本地代码，未推送或发布镜像。

最终回归：全量 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q` **171 passed**（一项既有Starlette/httpx弃用警告）；`node --check web/app.js`、`git diff --check`通过。浏览器 `browser-workspace`、`browser-studio`、`browser-task-history`、`browser-production-state`、`browser-scene-scroll` 全部通过，页面错误为空。重启后schema=4、活动任务=0，`/ready`为ready、`/health`为ok。
