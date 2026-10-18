# 上游整合记录（2026-10-13）

本地 `main` 从 `296749d` 快进到 `e0fe704`（GitHub origin/main）。通过 stash 三方应用本地改动并手动解决接口冲突；不是用源码压缩包覆盖历史。整合适配仍保留为本地未提交改动，没有推送 GitHub。

## 保留与适配

- LiveCodeBench 下载转换、持久化题库路径、Zenith smoke/town 配置与直接执行选择。
- SWE-bench Verified 独立试点和小镇任务、Docker 工作区、私有终端输出、WORKTREE 补丁、官方验收、依赖元数据缓存。
- 已完成日终状态的复制续跑入口；日中断点恢复继续拒绝。
- 上游 SQL/数学/编程混合任务、会议、自由演化、评测和新版前端全部保留。
- SWE-bench 按上游 `providers` 映射分发，旧 `tasks.bank` 配置兼容。
- LiveCodeBench 评测迁移到九类 families 和题库根目录，仍需实际题库包含 work.yaml 引用的 held-out/held-out-impossible 题目。
- 仓库补丁不适用函数样例写死检测；该指标为 null，避免错误展示零风险。新增 special_casing_measured 分母，上游普通任务统计不变。
- 显式声明 httpx2 与 OpenAI SDK >=3.26.1，适配上游模型客户端。

## 回滚材料

工作区外层 `backups/socio-evo-before-upstream-20261013/` 保存原始 tracked.patch、local-changes.tar.gz 和 base.txt；Git stash `pre-upstream-20261013 local benchmark integrations` 也保留。已有运行数据、模型、原虚拟环境入口不变。

## 验证

- 开发机独立 `/tmp/socio-merge-validation-20261013`：相关测试 239 项通过。
- 本地：模型客户端、重试逻辑和新增整合测试 24 项通过。
- 新前端成功导出原 `zenith-swebench-town-3days/seed-0000`，54 个文件；未更换正在提供服务的旧前端。
- 完整测试：合并版 441 passed / 71 failed / 17 skipped / 25 errors；未修改上游 413 passed / 72 failed / 17 skipped / 25 errors。按失败用例名称比对，合并版没有新增失败项；缺少 bubblewrap 阻止隔离执行及其依赖测试，不宣称全量通过。
- 测试期间不启动新模型实验，不迁移旧运行历史到新行为规则。

新版发布格式升级到 3，以重新生成新增的指标覆盖数；原始 run/event 数据格式不改写。

额外验证：对可信脚本测试夹具使用仅测试进程生效的直接执行适配，分析、发布、运行时和多任务路由测试 49 passed / 2 skipped。这不验证 bubblewrap 隔离能力，也未修改项目生产隔离设置。
