# SWE-bench 小镇实验

居民通过任务板接单，用自己的模型调用执行 `use the terminal`，在隔离仓库查看/修改/测试代码，再用 `WORKTREE` 提交实际补丁。没有独立修复代理代替居民工作。身份、记忆、交流、评价、收支及每日反思仍使用原有小镇流程。

## 当前配置

`experiments/configs/zenith/swebench-town.yaml`：3 位居民，1 个模拟日，2 个独立任务（Flask 5014、Astropy 12907），每段工作时间最多 12 次决策。任务各支付 60 crowns，初始余额 100，日生活成本 20。Requests 未计入：其参考补丁对照在外部 HTTP 测试上失败/超时。当天工作不足以证明长期能力或品格演化。

```bash
cd /personal_fast_storage/code/socio-evo
PYTHONPATH=/personal_fast_storage/qwen-serving/tools/swebench-pilot \
  /personal_fast_storage/qwen-serving/run-socio.sh -m experiments.run \
  experiments/configs/zenith/swebench-town.yaml --seeds 0
```

当前有效运行：`zenith-swebench-town-v3/seed-0000`。第一次 `zenith-swebench-town/seed-0000` 因终端输出被普通记忆裁剪而主动中断，保留作故障诊断，不能将其表现当作有效能力结论。第二次 `zenith-swebench-town-v2/seed-0000` 已得到两题通过验收，但官方依赖清单下载长时间阻塞，日终前中断并保留。第三次重跑使用官方固定提交依赖清单缓存与网络超时。

[本机小镇入口](http://127.0.0.1:8765/#/run/zenith-swebench-town-v3/seed-0000/town)

需要开发机前端 8765 的 SSH 转发保持连接。可以从成员的事件流查看终端输出、交流、提交结果，再查看日记和每日反思。

## 存储与验收

开发机结果：`/personal_fast_storage/code/socio-evo/runs/zenith-swebench-town-v3/seed-0000/`。

- `events.jsonl`：接单、命令、输出、提交、评分、付款、交流等事件；终端输出仅对所属居民可见。
- `llm_calls.jsonl`：居民真实推理记录。
- `agents/`：居民记忆、日记及参数版本。
- `repositories/workspaces/<hash>/workspace.json`：居民、任务、官方镜像基线的对应关系。
- 同目录 `commands.jsonl`、`last_command.json`、`working.patch`：完整命令记录、当前终端与实际改动。
- `repositories/evaluations/<hash>/`：官方验收、预测补丁、日志与评分缓存。

验收在独立干净容器中运行。居民看不到隐藏测试、参考补丁或测试名称，只得到总体通过/未通过反馈。`quality` 为官方 resolved 的 0/1；环境或验收器错误会中断试验，不会自动判居民为零分。相同补丁的检查和提交复用验收缓存。

结束或中断会移除本次创建的居民工作容器，保留补丁、日志和官方镜像。暂不支持本配置的 `--dry-run` 和 `--resume`；需要新建运行名后重跑，避免社会状态与工作目录回滚到不同时间点。

## 验证

接入测试 166 项通过，包括动作表单、接单权限、私有输出、WORKTREE 转换和完整终端屏幕。真实 Docker 工作区的创建、补丁保存及恢复探针通过。较大范围回归有 8 项环境失败，修改前相同：缺少 bubblewrap，以及一项直接执行测试未设置 API Key；不把它们计为测试通过。

## 官方依赖清单缓存

`/personal_fast_storage/datasets/swebench-verified/http-cache.json` 保存官方 GitHub 固定提交 `182ce3dd15dfa3537391c3efaf9c3ff407d134d4` 的 Flask requirements 原文（dev、docs、tests、typing），每份带 SHA256 校验。验收器只对依赖元数据下载使用缓存，未缓存或替换测试结果；未命中缓存时设置连接/读取超时。每次验收记录缓存文件整体哈希。此缓存不向居民容器挂载。

## 已完成结果

[2026-10-12 实验报告](swebench-town-results-20261012.md)：最终 v3 一天完成，Flask 由 Tomas 修复并通过官方验收，Astropy 未接单，三位居民日记和 L0 反思均已保存。

## 从第一天续跑到第三天

`zenith-swebench-town-3days/seed-0000` 从已完成的 v3 日终检查点复制并继续；原始 v3 不变。继承第一天的事件、居民版本、余额、任务状态、随机状态和仓库补丁，仅改变实验名与总天数。`continuation.json` 记录来源及校验哈希。这是同一条轨迹的延长，不是独立重复实验。

```bash
PYTHONPATH=/personal_fast_storage/qwen-serving/tools/swebench-pilot \
  /personal_fast_storage/qwen-serving/run-socio.sh -m experiments.extend \
  /personal_fast_storage/code/socio-evo/runs/zenith-swebench-town-v3/seed-0000 \
  --name zenith-swebench-town-3days --days 3
```

此命令只接受已完成且事件与最终检查点对齐的运行，拒绝覆盖已有目标；仍不支持 SWE-bench 日中断点恢复。每日仍发布同一组 Flask/Astropy 两道题，不代表六道独立题目。保持生活成本 20、原有日程决策规则、12 轮工作决策和空干预列表；第 2 天触发 L1，第 3 天触发 L2。

[三天续跑入口](http://127.0.0.1:8765/#/run/zenith-swebench-town-3days/seed-0000/town)。运行日志位于 `/personal_fast_storage/qwen-serving/logs/swebench-town-3days.log`。

## 上游整合（2026-10-13）

本地基础已快进至 `e0fe704`，完整保留上游多任务类型、会议、自由演化、分析和前端。SWE-bench 使用新 `providers` 映射中的 programming 接口，仍由独立 Docker 仓库和官方测试验收，保留命令私有性、完整终端屏幕、WORKTREE、元数据缓存和完成日续跑。该试点仍只允许单部分编程任务，不与 SQL/数学混发。

新版 Character 分析对仓库补丁不适用的“写死样例”检测显示为无数据，而非零；其余可从日志计算的统计正常保留。`special_casing_measured` 记录此检测实际覆盖的提交数。升级不会给旧实验补造新的行为或评测结果。
