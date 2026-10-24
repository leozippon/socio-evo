# 2026-10-24

## Redesign begins

The research framework handed over today supersedes the scene-based town: residents become tool-calling agents with persistent sessions living in real time through events, work becomes SWE-bench Verified in containers, and character is measured by capability on held-out tasks, by the factual distortion of each resident's daily journal, and by honesty under pressure on MASK scenarios, across four groups (A independent, B evening exchange, C social, D social without skill writing).

State found: local `main` at e841d09 with 606 tests passing; `origin/main` 121 commits ahead. The remote commits were reviewed, not merged ([review](../reviews/REMOTE_COMMITS_2026-10-24.md)): fourteen short runs launched in two days, none finished or analysed; four competing schedulers; a context-overflow error that ends runs; thinking disabled to work around a budget failure; the same components reworked repeatedly. Lessons carried over: one scheduler; a resident's failure never ends a run; reply budgets must survive thinking; a SWE-bench exit code 137 is an infrastructure error, not the resident's.

Branch `redesign-event-runtime` from local `main`. The superseded packages were removed in the first commit; `infrastructure/` (model client, git, JSONL, config) stays. The architecture and the experimental design were rewritten; `agent/port.py` fixes the runtime–world contract and `agent/wording.py` the guard on every text a resident reads.

Machine: 8 × L20 (46 GB), 192 CPUs, 503 GB RAM; rootless Docker; Docker Hub blocked, ghcr.io and the Hugging Face mirror reachable; the Qwen3.8-27B bf16 weights are on disk and the official FP8 checkpoint is on the mirror.

Work in flight, delegated in parallel with disjoint scopes: the model service (`ops/vllm`), the SWE-bench harness (`tasks/swebench`), the agent runtime (`agent/`, `infrastructure/llm`), the world (`world/`), and the honesty evaluation (`evaluation/`).

## What landed

- Model service: Qwen3.8-27B-FP8 (official checkpoint) under vLLM 0.32 in a dedicated `vllm` env, serving `qwen3.8-27b-fp8` on all eight L20s with a 262k window; the runtime's integration test against it passes. The user's reference deployment at `/Data/lzp/vllm-service` (FP8 KV cache, L20-tuned block-FP8 kernels, TP2) was handed to the service builder to adopt what measures faster. Constraint from the user: eight GPUs for the next 24–48 hours, at most four afterwards; the serve script is to take the GPU set as a parameter.
- SWE-bench Verified (`tasks/swebench`): splits of 56 training and 100 held-out tasks, fixed by seed; matplotlib excluded (its images hold files owned by a UID that rootless Docker here cannot map) and three tasks whose gold patch cannot pass offline; all 156 images pulled (45 GB) and every task gold-validated; the upstream history newer than the base commit is pruned in each workspace so the fix cannot be read; out-of-memory kills grade as errors.
- Agent runtime (`agent/`), world (`world/`), honesty evaluation (`evaluation/judge.py`, `evaluation/mask`, `evaluation/honesty.py`), day records and analysis (`evaluation/records.py`, `evaluation/journals.py`, `analysis/`), capability harness (`world/solo.py`, `evaluation/capability.py`) and the timeline viewer (`frontend/`), each with its tests; the composition layer (`simulation/`, `experiments/`) is in progress.
- Judge: the relay service's DeepSeek V4.1 Flash with thinking disabled (at temperature 0 the thinking variant looped on the extraction prompt until the token limit); the judged text precedes the per-claim context so a day's record is one cacheable prefix. The honesty smoke test gave sensible verdicts in 11 calls and 8.3k prompt tokens; the MASK pipeline ran three scenarios on the live model in a minute.

## First real work

A fresh resident (Mei's background, reasoning effort low) resolved two of three held-out tasks in the capability harness: django-14373 in 14–17 requests and 2–5 minutes, sympy-13372 in 17 requests and 7 minutes; the third was lost to the service being restarted for tuning. Per request the prompt was 6–16k tokens with 60–80% served from the prefix cache; replies took 60–120 s under three-way concurrency. The model reached for `read_repo_file` with an offset and for editing repository files with its own-file `edit_file`; both are being added as work tools. Replies with `finish_reason: abort` from a server shutting down passed through as ordinary turns; the client is being made to retry them.
