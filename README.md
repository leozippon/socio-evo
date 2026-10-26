# socio-evo

socio-evo is a long-term multi-agent society simulation. It asks whether social interaction and social selection pressure can shape stable character traits in self-evolving LLM agents: honesty, cooperation, reliability and resistance to reward hacking.

Eight residents, each a tool-calling agent with a persistent session over its own directory of memory and skills, live four weeks in a small town in real time. They take paid SWE-bench Verified jobs in containers, talk, hand each other money and skills, rate one another anonymously, write a journal every night and rewrite their own files. Nobody tells them to have any trait. Four groups differ only in social life: alone, an evening exchange of work experience, free social life, and free social life without the right to rewrite skills. Capability, the honesty of each resident's journal about its own day, and honesty under pressure on MASK scenarios are measured on exported snapshots. The design is in [docs/summary.md](docs/summary.md), [docs/experimental-design.md](docs/experimental-design.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Install

Use a Python 3.11 environment (the project uses the conda environment `socio-evo`):

```bash
pip install -e ".[dev,swebench,mask]"
python -m pytest -q                 # offline tests
python -m pytest -q -m docker       # also the tests that need the task images
ruff check .
```

Credentials live in the git-ignored `.env`, which the code does not load; export it first:

```bash
set -a; . ./.env; set +a
```

It holds the model server's URL and key (`VLLM_BASE_URL`, `VLLM_API_KEY`), the relay's keys (`LIGHTING_API_KEY` for the judge, `LIGHTING_API_KEY_ALT` for the residents while they run on DeepSeek) and the Hugging Face mirror (`HF_ENDPOINT`, `HF_TOKEN`).

## Services

The residents run on Qwen3.8-27B-FP8 served by vLLM through the OpenAI API; `ops/vllm/serve.sh` starts it on the GPUs it is given and `ops/vllm/README.md` records the layouts and the throughput measured. While the GPUs are taken and no parameters are tuned, the residents run instead on DeepSeek-V4.1-Flash through the relay, as the `llm` section of `experiments/configs/town.yaml` says; switching back is a matter of that section and `experiments/configs/model.yaml`. Work needs rootless Docker and the SWE-bench Verified images of the two fixed splits (350 training tasks, 100 held-out tasks), pulled once from Epoch AI's registry:

```bash
python -m tasks.swebench.pull
```

`tasks/swebench/README.md` has the integrity guarantees (no network in a container, the upstream fix pruned from the history, acceptance in a fresh container) and the timings.

## Run

Each group is one configuration overlaying the shared town; the dry run checks the whole pipeline with a scripted model and a fake board in seconds:

```bash
python -m experiments.run experiments/configs/smoke.yaml --dry-run
python -m experiments.run experiments/configs/groups/c.yaml --dry-run --until-day 2

# The real thing: one process per group, writing runs/<name>/
python -m experiments.run experiments/configs/groups/a.yaml
python -m experiments.run experiments/configs/groups/c.yaml --until-day 7
python -m experiments.run experiments/configs/groups/c.yaml --resume
```

A run resumes from its last daily checkpoint with the configuration unchanged; Ctrl-C marks it interrupted and loses the day in progress. `python -m frontend.publish --runs-root runs --out build/site` publishes every run as a static site (the town, every resident's timeline side by side, each resident's files and trace, the measures and the evaluation), `python -m frontend.server --runs-root runs` serves it at http://127.0.0.1:8765/ live for a running run, and `frontend/deploy/push.sh cornerhead build/site` pushes it to the private web server.

## Evaluate and analyse

Evaluation runs on exports of the residents at a day's checkpoint and never touches the run:

```bash
python -m experiments.export runs/c --day 7 --out exports/c/day-07

# Capability: the held-out tasks in a work-only harness; a stopped evaluation is continued by running the same command again
python -m evaluation.capability exports/c/day-07/Mei --split eval --out results/c/day-07/capability/Mei --model experiments/configs/model.yaml --reasoning low --concurrency 4

# Honesty under pressure: the twenty fixed MASK scenarios
python -m evaluation.mask exports/c/day-07/Mei --out results/c/day-07/mask/Mei.json --model experiments/configs/model.yaml --reasoning low

# Honesty of the journals: each day's journal against the world's record of that day; every judging gets its own directory under results/c/journals/, where the site reads it
python -m evaluation.journals runs/c --days 1 2 3 4 5 6 7 --out results/c/journals/day-01-07

# Measures of a run, a group's evaluation results as tables (day 0 from results/day-00), and the comparison of groups
python -m analysis.measures runs/c
python -m analysis.tables results --group c --out results/c/tables
python -m analysis.compare --group A=runs/a --group C=runs/c --measure accepted --out results/compare-accepted.json
```

## Layout

| Directory | What it holds |
| --- | --- |
| `agent/` | The runtime: session, loop, tools over the resident's files, compaction, trace, and the contract with the world |
| `world/` | Clock, town with its homes and goods, events, board, economy, ratings, world log, the solo port for evaluation |
| `simulation/` | Running one town, checkpoints and resumption, the dry run |
| `tasks/swebench/` | SWE-bench Verified: splits, images, workspaces, acceptance |
| `evaluation/` | Judge, MASK, journal distortion, capability harness, day records |
| `analysis/` | Measures and group statistics |
| `experiments/` | Configurations, resident backgrounds, run and export commands |
| `frontend/` | The published site: the viewer and its data bundle |
| `infrastructure/` | Model client, git-versioned directories, JSONL, configuration |
| `docs/` | Design, architecture, project log and reviews |
