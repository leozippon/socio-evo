# SWE-bench Verified 三题试点结果（2026-10-12）

已在 Zenith 开发机使用真实 `qwen-3.8-27b-fp8` 完成一次独立仓库修复试点。最终运行 ID：`swebench-verified-20261012-retry2`；官方验收 ID：`socio-swe-pilot-20261012`。

| 任务 | 内容 | 模型阶段 | 官方验收 |
|---|---|---|---|
| pallets__flask-5014 | Blueprint 空名称校验 | 8 步，约 20 秒，828 字节补丁 | resolved；1 个缺陷测试、59 个回归测试通过 |
| psf__requests-2317 | bytes 请求方法转换 | 第 8 步连续两次输出截断，约 186 秒；空补丁 | 未解决；空补丁不执行验收 |
| astropy__astropy-12907 | 嵌套复合模型的可分离矩阵 | 18 步，约 122 秒，504 字节补丁 | resolved；2 个缺陷测试、13 个回归测试通过 |

三题中正式解决 2 题。这个小样本只验证流程，不代表完整 SWE-bench Verified 成绩。官方汇总里的 `submitted_instances=3` 指预测文件包含三条记录，不是三份有效补丁；其中一条为空。

## 环境对照与限制

另跑了独立 gold-patch 正向对照。Flask 和 Astropy 均通过；Requests 的 HTTP 相关测试出现失败并在 300 秒超时，不能声称该任务的评分环境已验证可靠。此问题独立于模型生成阶段的格式失败。参考补丁、隐藏测试和对照日志没有进入修复代理的输入；代理只接收仓库名、公开问题与自己的命令输出。

首次和 retry1 启动暴露了镜像基线检查问题，日志保留。官方镜像在原始 base_commit 上增加环境配置提交（包括文件权限、构建依赖修改）；最终使用镜像 HEAD 作为模型补丁基线，并检查原始 base_commit 是其祖先。重跑从全新容器开始，未沿用失败试运行的补丁。最终两份补丁都在另一组全新容器内通过官方测试。

代码新增了独立修复代理、Docker 输出代理适配、官方评分入口、配置和文档。3 个针对性单元测试、Ruff 检查和 diff 空白检查通过。所有本次运行容器已由运行器回收；官方镜像保留供后续复用。原有虚拟环境、LiveCodeBench 配置与小镇结果保留。

## 查看结果

开发机目录：

```text
/personal_fast_storage/code/socio-evo/pilot-runs/swebench-verified-20261012-retry2/
```

- `manifest.json`：三题生成状态。
- `<instance>/commands.jsonl`：查看文件、编辑、测试的完整命令与输出。
- `<instance>/llm_calls.jsonl`：模型推理调用记录。
- `<instance>/model.patch`：成功生成的补丁。
- `predictions.jsonl`：官方格式预测文件。
- `evaluation/qwen-3.8-27b-fp8.socio-swe-pilot-20261012.json`：正式汇总。
- `evaluation/logs/run_evaluation/socio-swe-pilot-20261012/`：逐题报告及测试输出。

对照结果位于相邻的 `swebench-control-20261012/`。本地摘要另保存于工作区 `deployment/swebench-verified/results/`。

本次是仓库修复流程试点，尚未接入小镇居民、任务市场、社会互动或前端回放。下一阶段可增加 SWE-bench task provider，将 issue 分配、补丁提交、官方评分接入既有任务流程；先解决结构化输出截断并选择不依赖不稳定外部 HTTP 服务的任务。
