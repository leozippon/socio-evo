# 实验主页整理

主页保留四次完整真实推理实验：zenith-direct-smoke、zenith-livecodebench-smoke、zenith-swebench-town-3days、zenith-swebench-town-latest-20261013。三次 dry-run、两次中断诊断与被续跑包含的一天 SWE-bench 结果移到 `/personal_fast_storage/code/socio-evo/archived-runs/20261013-home-cleanup/`，可以移回 runs 恢复；原始文件不删除。

主页按续跑时间（存在时）或开始时间倒序排列。每条记录显示开始、结束及可选续跑时间，固定 Asia/Shanghai（UTC+8），与模拟日进度分开。未来发布的新运行自动使用相同展示方式。发布器从 continuation.json 读取续跑时间，并将其加入文件变更检测。

验证：已在实际浏览器刷新主页，确认只剩四条 Completed 记录、最新实验置顶、北京时间和续跑时间正确，窄窗口布局正常。Python lint 和 diff 检查通过。
