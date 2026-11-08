# 单机 Alpha 先使用 SQLite 持久化队列与独立 Worker

状态：accepted（仅限单机 Alpha）。

本阶段部署面向单管理员、单机本地卷；采用 SQLite WAL、事务领取任务、版本乐观锁和独立 Worker 进程。相比立即引入 PostgreSQL/Celery/Redis，能用更少部署依赖验证实际渲染与任务持久化，不把长任务挂在 Web 请求中。OS 文件锁只允许一个 Worker；崩溃中的任务标记 interrupted，不自动重放可能计费的操作。

该方案明确不支持多机、NFS 共享队列或多 worker 横向扩展。完整生产版仍需迁移到已设计的 PostgreSQL/队列，并拆分带密钥的生成进程与无密钥渲染进程。业务调用经 Store Interface，不直接在路由编写 SQL。当前数据库初始化仅有 v1 schema，后续变更必须引入显式迁移。
