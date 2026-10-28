# socio-evo

socio-evo is a long-term multi-agent society simulation. It asks whether social interaction and social selection pressure can shape stable character traits in self-evolving LLM agents: honesty, cooperation, reliability and resistance to reward hacking.

Eight residents, each a tool-calling agent with a persistent session over its own directory of memory and skills, live four weeks in a small town in real time. They take paid SWE-bench jobs in containers, talk, hand each other money and skills, write a journal every night and rewrite their own files. Nobody tells them to have any trait. Capability, the honesty of each resident's journal about its own day, and honesty under pressure on MASK scenarios are measured on exported snapshots. The design is in [docs/summary.md](docs/summary.md), [docs/experimental-design.md](docs/experimental-design.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

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

It holds the model server's URL and key (`VLLM_BASE_URL`, `VLLM_API_KEY`), the relay's key (`LIGHTING_API_KEY` for the judge) and the Hugging Face mirror (`HF_ENDPOINT`, `HF_TOKEN`).

## Services

The residents run on Qwen3.8-27B-FP8 served by vLLM through the OpenAI API; `ops/vllm/serve.sh` starts it on the GPUs it is given and `ops/vllm/README.md` records the layouts and the throughput measured. The `llm` section of `experiments/configs/town.yaml` names the server, the model and its replica count, to one of which each resident keeps. Work needs rootless Docker and the SWE-bench images of the two fixed splits: 100 held-out tasks from SWE-bench Verified, and 1,912 training tasks, the 350 other usable ones of Verified followed by 1,562 of SWE-bench's full test split. The images take about 260 GB of Docker's image store and are pulled once from Epoch AI's registry:

```bash
python -m tasks.swebench.pull
```

`tasks/swebench/README.md` has the integrity guarantees (no network in a container, the upstream fix pruned from the history, acceptance in a fresh container) and the timings.

## Run

The town is `experiments/configs/town.yaml`, and a run's configuration under `experiments/configs/runs/` overlays it; the dry run checks the whole pipeline with a scripted model and a fake board in seconds:

```bash
python -m experiments.run experiments/configs/smoke.yaml --dry-run
python -m experiments.run experiments/configs/runs/town.yaml --dry-run --until-day 2

# The real thing: one process per run, writing runs/<name>/
python -m experiments.run experiments/configs/runs/town.yaml --until-day 7
python -m experiments.run experiments/configs/runs/town.yaml --resume
```

A run refuses to start or resume when the model does not answer, and fails after five lapses in a row; it resumes from its last daily checkpoint with the configuration unchanged, and Ctrl-C marks it interrupted and loses the day in progress. A run in the background is stopped the same way by `ops/stop.sh town`, which signals only the process the run's manifest records, and only while that process is the run's own; `ops/stop.sh town --after-checkpoint` first waits for the next daily checkpoint, so that no lived day is lost. `python -m frontend.publish --runs-root runs --out build/site` publishes every run as a static site (the town, every resident's timeline side by side, each resident's files and trace, the measures and the evaluation), `python -m frontend.server --runs-root runs` serves it at http://127.0.0.1:8765/ live for a running run, and `frontend/deploy/push.sh cornerhead build/site` pushes it to the private web server.

## Evaluate and analyse

Evaluation runs on exports of the residents at a day's checkpoint and never touches the run; an export records each resident's commit and the run's model and runtime settings beside the residents, the evaluations answer through those and record the commit with their results. `ops/evaluate.sh town 7` exports day 7 of the run (keeping an export there of the same commits, replacing one of others) and starts the capability evaluation of every resident in the background, preceded by MASK only on days 0, 14 and 28, the days the design measures it on (`MASK_DAYS` at the top of the script); day 0 goes to the shared `results/day-00`. Its capability tasks run one at a time per resident and compact their context at 90,000 tokens instead of the run's threshold (`CONCURRENCY` and `EVAL_COMPACTION` change these), so that they fit in the model server's KV cache beside a running town without evicting the residents' prefixes. The pieces are:

```bash
python -m experiments.export runs/town --day 7 --out exports/town/day-07

# Capability: the held-out tasks in a work-only harness; a stopped evaluation is continued by running the same command again
python -m evaluation.capability exports/town/day-07/Mei --split eval --out results/town/day-07/capability/Mei --concurrency 1 --compaction-threshold 90000

# Honesty under pressure: the twenty fixed MASK scenarios
python -m evaluation.mask exports/town/day-07/Mei --out results/town/day-07/mask/Mei.json

# Honesty of the journals: each day's journal against the world's record of that day; every judging gets its own directory under results/town/journals/, where the site and the comparison read them all
python -m evaluation.journals runs/town --days 1 2 3 4 5 6 7 --out results/town/journals/day-01-07

# Measures of a run, a run's evaluation results as tables (day 0 from results/day-00), and the comparison of runs on a town measure, on an evaluation table, and on the journals' distortion
python -m analysis.measures runs/town --out results/town/measures
python -m analysis.tables results --group town --out results/town/tables
python -m analysis.compare --group town=runs/town --group other=runs/other --measure accepted --out results/compare-accepted.json
python -m analysis.compare --group town=results/town/tables/mask.json --group other=results/other/tables/mask.json --measure mask
python -m analysis.compare --group town=results/town/journals --group other=results/other/journals --measure distortion
```

## Layout

| Directory | What it holds |
| --- | --- |
| `agent/` | The runtime: session, loop, tools over the resident's files, compaction, trace, and the contract with the world |
| `world/` | Clock, town with its homes and goods, events, board, economy, world log, the solo port for evaluation |
| `simulation/` | Running one town, checkpoints and resumption, the dry run |
| `tasks/swebench/` | SWE-bench: splits, images, workspaces, acceptance |
| `evaluation/` | Judge, MASK, journal distortion, capability harness, day records |
| `analysis/` | Measures and the statistics comparing runs |
| `experiments/` | Configurations, resident backgrounds, run and export commands |
| `frontend/` | The published site: the viewer and its data bundle |
| `infrastructure/` | Model client, git-versioned directories, JSONL, configuration |
| `docs/` | Design, architecture, project log and reviews |
