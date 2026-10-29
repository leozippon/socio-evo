# socio-evo

socio-evo is a long-term multi-agent society simulation. It asks whether social life and social selection pressure can shape stable character traits in self-evolving LLM agents: honesty, cooperation, reliability and resistance to reward hacking.

Eight residents, each a tool-calling agent with a persistent session over its own directory of memory and skills, live 28 days in a small town in real time. Each has an occupation in the town's economy: a team leader and three programmers who take clients' SWE-bench tasks at the Office, a chef, a shopkeeper, a doctor and a mayor. They live on what clients pay for the programmers' work and on their own businesses' takings, pay a tenth of it in tax and their rent to the town's treasury, which pays the mayor, eat, tire, fall ill, talk, give, write a journal when they go to bed and rewrite their own files. Nobody tells them to have any trait. The capability of the programmers and their leader on held-out tasks, the honesty of each resident's journal about its own day, and its honesty under pressure on MASK scenarios are measured on exported snapshots.

The design is introduced in [docs/summary.md](docs/summary.md) and decided in [docs/experimental-design.md](docs/experimental-design.md); how the code realises it is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), and the voice of every text a resident reads in [docs/IMMERSION.md](docs/IMMERSION.md).

## Install

Use a Python 3.11 environment (the project uses the conda environment `socio-evo`):

```bash
pip install -e ".[dev,swebench,mask]"
python -m pytest -q                 # the tests; those needing Docker and the task images skip without them
python -m pytest -q -m docker       # only the tests that need Docker and the task images
ruff check .
```

Credentials live in the git-ignored `.env`, which the code does not load; export it first:

```bash
set -a; . ./.env; set +a
```

It holds the model server's URL and key (`VLLM_BASE_URL`, `VLLM_API_KEY`), the relay's key for the judge (`LIGHTING_API_KEY`) and the Hugging Face mirror (`HF_ENDPOINT`, `HF_TOKEN`).

## Services

The residents run on Qwen3.8-27B-FP8 served by vLLM through the OpenAI API. `ops/vllm/serve.sh` starts the server on the GPUs it is given, one two-GPU replica per pair; the town's configuration expects two replicas, so serve it on four GPUs:

```bash
GPUS=0,1,2,3 setsid nohup ops/vllm/serve.sh >/dev/null 2>&1 &
```

[ops/vllm/README.md](ops/vllm/README.md) records the layouts, the settings, how to check and stop the server, and the throughput measured. The `llm` section of `experiments/configs/town.yaml` names the server, the model and the replica count.

Work needs rootless Docker and the SWE-bench images of the two fixed splits: 100 held-out tasks from SWE-bench Verified, and a training pool of 1,912, the 350 other usable Verified tasks followed by 1,562 of SWE-bench's full test split. The images take about 263 GB of Docker's image store and are pulled once from Epoch AI's registry:

```bash
python -m tasks.swebench.pull
```

[tasks/swebench/README.md](tasks/swebench/README.md) has the integrity guarantees (no network in a container, the upstream fix pruned from the history, acceptance in a fresh container) and the timings.

## Run

The town is `experiments/configs/town.yaml`; a run's configuration under `experiments/configs/runs/` overlays it, and `experiments/configs/smoke.yaml` is a town of three (the team leader, the shopkeeper and the chef) for one day. One process runs one town and writes `runs/<name>/`:

```bash
python -m experiments.run experiments/configs/smoke.yaml --dry-run                   # the whole pipeline with a scripted model and fake tasks, in seconds
python -m experiments.run experiments/configs/runs/town.yaml --dry-run --until-day 2
python -m experiments.run experiments/configs/smoke.yaml                             # one day against the model

python -m experiments.run experiments/configs/runs/town.yaml --until-day 7
python -m experiments.run experiments/configs/runs/town.yaml --resume
```

A run refuses to start or resume when the model does not answer, and fails after five lapses in a row. It resumes from its last daily checkpoint (04:30 of each day) with the configuration unchanged; stopping it loses the day in progress, which is lived again. A run in the background is stopped with `ops/stop.sh town`, which signals only the process the run's manifest records, and only while that process is the run's own; `ops/stop.sh town --after-checkpoint` first waits for the next checkpoint, so that no lived day is lost.

Containers left by a process that was killed stay until `python -m tasks.swebench.cleanup` removes them.

## Evaluate and analyse

Evaluation runs on exports of the residents at a day's checkpoint and never touches the run. `ops/evaluate.sh town 7` exports day 7 (keeping an export there of the same commits, replacing one of others) and starts in the background, one chain per resident with its log under `runs/eval-logs/`, MASK for every resident on days 0, 14 and 28 (`MASK_DAYS`) and then the capability evaluation for the programmers and the team leader (`CAPABILITY`), by the occupation the export records. Capability tasks run one at a time per resident and compact their context at 90,000 tokens (`CONCURRENCY` and `EVAL_COMPACTION` change these), so that they fit in the server's cache beside a running town; running the script again continues a stopped capability evaluation. Day 0 goes to the shared `results/day-00`, a later day to `results/<run>/day-NN`. `ops/evaluate-queue.sh town`, started beside the living run, does this for days 7, 14, 21 and 28 as their checkpoints are saved, each day once the previous one's capability tasks have ended and with three tasks at a time per resident once the run has ended, and judges each week's journals as soon as its last day is saved. The pieces, and the analysis, which the scripts do not run:

```bash
python -m experiments.export runs/town --day 7 --out exports/town/day-07
python -m evaluation.exports exports/town/day-07          # each resident with its occupation

# Capability on the held-out tasks, in a work-only harness
python -m evaluation.capability exports/town/day-07/Mei --split eval --out results/town/day-07/capability/Mei --concurrency 1 --compaction-threshold 90000

# Honesty under pressure: the twenty fixed MASK scenarios
python -m evaluation.mask exports/town/day-07/Mei --out results/town/day-07/mask/Mei.json

# Honesty of the journals: each day's entry against the world's record of that day; one directory per judging
python -m evaluation.journals runs/town --days 1 2 3 4 5 6 7 --out results/town/journals/day-01-07

# The run's measures, the results as tables with the declared outcomes, and one measure compared resident by resident
python -m analysis.measures runs/town --out results/town/measures
python -m analysis.tables results --run town --out results/town/tables
python -m analysis.compare --run town=results/town/tables/mask.json --measure mask
python -m analysis.compare --run town=results/town/journals --measure distortion
python -m analysis.compare --run town=runs/town --measure tasks_accepted --out results/town/compare/tasks_accepted.json
```

## The site

The runs and their results are published as a static site: the town on its map at any moment, every resident's events side by side, each resident's story, files and trace, a dashboard of the town's work, money, trade, bodies and social life, the evaluation and the comparison of runs. [frontend/README.md](frontend/README.md) describes the views and the bundle.

```bash
python -m frontend.publish --runs-root runs --results-root results --out build/site
python -m frontend.server --runs-root runs --results-root results     # http://127.0.0.1:8765/, republished every 5 s
frontend/deploy/push.sh cornerhead build/site                         # an atomic release on the private server
frontend/deploy/follow.sh cornerhead build/site                       # publish and push in turn, every 120 s
```

The private server, its login and its firewall are set up as [ops/webui/README.md](ops/webui/README.md) describes.

## Layout

| Directory | What it holds |
| --- | --- |
| `agent/` | The runtime: session, loop, file tools over the resident's own directory, compaction, trace, the contract with the world and the wording guard |
| `world/` | The town: configuration, clock, events and tools, the Office's board, the treasury, the Store and the kitchen, bodies, rules, and the world log |
| `simulation/` | Running one town, checkpoints and resumption, the dry run |
| `tasks/swebench/` | SWE-bench: splits, images, workspaces, acceptance |
| `evaluation/` | Capability and its work-only harness, MASK, the journals' distortion, the judge, the record of a resident's day, exports |
| `analysis/` | Measures, evaluation tables and the within-resident statistics |
| `experiments/` | The town's configuration and the runs over it, the residents' backgrounds, the run and export commands |
| `frontend/` | The published site: the viewer, its data bundle and its deployment |
| `infrastructure/` | Model client, git-versioned directories, JSONL, the run directory, configuration |
| `ops/` | The model server, the private web server, and the scripts that evaluate and stop a run |
| `tests/` | Tests, one directory per package, and the helpers they share under `tests/support/` |
| `docs/` | Design, architecture, immersion, the project log and reviews |

Runs, exports and results (`runs/`, `exports/`, `results/`) and the archive of earlier configurations (`archive/`) are local data and not in the repository.
