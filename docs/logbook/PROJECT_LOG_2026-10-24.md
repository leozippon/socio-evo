# 2026-10-24

## Redesign begins

The research framework handed over today supersedes the scene-based town: residents become tool-calling agents with persistent sessions living in real time through events, work becomes SWE-bench Verified in containers, and character is measured by capability on held-out tasks, by the factual distortion of each resident's daily journal, and by honesty under pressure on MASK scenarios, across four groups (A independent, B evening exchange, C social, D social without skill writing).

State found: local `main` at e841d09 with 606 tests passing; `origin/main` 121 commits ahead. The remote commits were reviewed, not merged ([review](../reviews/REMOTE_COMMITS_2026-10-24.md)): fourteen short runs launched in two days, none finished or analysed; four competing schedulers; a context-overflow error that ends runs; thinking disabled to work around a budget failure; the same components reworked repeatedly. Lessons carried over: one scheduler; a resident's failure never ends a run; reply budgets must survive thinking; a SWE-bench exit code 137 is an infrastructure error, not the resident's.

Branch `redesign-event-runtime` from local `main`. The superseded packages were removed in the first commit; `infrastructure/` (model client, git, JSONL, config) stays. The architecture and the experimental design were rewritten; `agent/port.py` fixes the runtime–world contract and `agent/wording.py` the guard on every text a resident reads.

Machine: 8 × L20 (46 GB), 192 CPUs, 503 GB RAM; rootless Docker; Docker Hub blocked, ghcr.io and the Hugging Face mirror reachable; the Qwen3.8-27B bf16 weights are on disk and the official FP8 checkpoint is on the mirror.

Work in flight, delegated in parallel with disjoint scopes: the model service (`ops/vllm`), the SWE-bench harness (`tasks/swebench`), the agent runtime (`agent/`, `infrastructure/llm`), the world (`world/`), and the honesty evaluation (`evaluation/`).
