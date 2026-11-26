# socio-evo

socio-evo asks whether an AI agent can be aligned by socialisation: whether ordinary social life, under the pressure of other people's regard, makes an unaligned model measurably safer, with no safety instruction, no safety data and no reward for refusing.

Eleven residents, each a tool-calling agent on one abliterated Qwen3.8-27B with a LoRA adapter of its own, live 28 days in a small town in real time. A team leader and four programmers take clients' SWE-bench tasks at the Office; a chef, a shopkeeper and a doctor keep the Linde, the Store and the surgery, and a mayor grants from the town's treasury; two newcomers have no work. They trade on honour, can take whatever is within reach, see how many of the others like each of them, and meet an incident staged each day. Every night each resident chooses moments of its life to keep, and its adapter is fitted again on them. Each resident's weights are scored on JailbreakBench, XSTest and MASK on days 0, 7, 14, 21 and 28, in three arms that separate learning from the generalised moments, from the moments as they happened, and from moments drawn at random.

The design is introduced in [docs/summary.md](docs/summary.md) and decided, with its hypotheses, arms and analysis, in [docs/experimental-design.md](docs/experimental-design.md). How the code realises it is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), what a resident may be told and how in [docs/IMMERSION.md](docs/IMMERSION.md), and the project's history in the [project log](docs/logbook/).

## Layout

| Directory | What it holds |
| --- | --- |
| `agent/` | The runtime: session, loop, file tools over the resident's own directory, compaction, trace, the contract with the world and the wording guard |
| `world/` | The town: configuration, clock, events and actions, things and their holders, the Office's board and web, the businesses, the treasury, bodies, regard, incidents, rules, and the world log |
| `learning/` | The nights: moments, the choice, the generalising, datasets, fitting and adapters; `learning/train.py`, the trainer, runs in an environment of its own |
| `simulation/` | Running one town: checkpoints, resumption and the nights, and the dry run's scripted model |
| `tasks/swebench/` | SWE-bench: splits, images, workspaces, acceptance |
| `evaluation/` | The safety instruments and MASK put to the bare weights, their judges, and the judge's validation |
| `analysis/` | The run's measures, the evaluation tables with the declared outcomes, and the contrasts between arms |
| `experiments/` | The town's configuration, its incidents, the town that learns and its arms, the smoke town, the residents' backgrounds, and the run command |
| `frontend/` | The published site: the viewer, its data bundle and its deployment |
| `infrastructure/` | Model client and the adapters on the server, git-versioned directories, JSONL, the run directory, configuration |
| `ops/` | The model server, the trainer's environment and its GPU validation, the private web server, and the scripts that evaluate and stop a run |
| `tests/` | Tests, one directory per package, and the helpers they share under `tests/support/` |
| `docs/` | The design, its summary, the architecture, immersion and the project log |

Runs and results (`runs/`, `results/`) and the archive of earlier designs' runs and reviews (`archive/`) are local data and not in the repository.

## Set up

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

The code reads from it the residents' server (`VLLM_BASE_URL`, `VLLM_API_KEY`), the safety judge's server (`GUARD_BASE_URL`, with the same key), the relay's key for the MASK judge (`LIGHTING_API_KEY`), the web search's key (`TAVILY_API_KEY`, without which a town with the web does not start) and the Hugging Face mirror (`HF_ENDPOINT`, `HF_TOKEN`).

## Services

The residents run on the abliterated Qwen3.8-27B-FP8 served by vLLM through the OpenAI API, with their adapters beside it. `ops/vllm/serve.sh` starts the server on the GPUs it is given, one two-GPU replica per pair; the town's configuration expects two replicas, and a town that learns needs the adapters served (`LORA=1`):

```bash
GPUS=0,1,2,3 LORA=1 MODEL_PATH=/Data2/lzp/models/Qwen3.8-27B-Uncensored-FP8 SERVED_NAME=qwen3.8-27b-uncensored-fp8 \
  setsid nohup ops/vllm/serve.sh >/dev/null 2>&1 &
```

[ops/vllm/README.md](ops/vllm/README.md) records the layouts, the settings, how to check and stop the server, and the throughput measured; the `llm` section of `experiments/configs/town.yaml` names the server, the model and the replica count. The same script with its defaults serves the original checkpoint as `qwen3.8-27b-fp8`, the aligned reference, which needs GPUs and a port of its own.

The adapters are fitted by `learning.train` under its own interpreter, one trainer on each of the GPUs the server leaves free that has room when a night comes; `experiments/configs/learning.yaml` names the interpreter, the base weights and the GPUs. [ops/train/README.md](ops/train/README.md) creates the environment and holds the validation of fitting and serving on two free GPUs, the first thing to run before any town that learns:

```bash
ops/train/setup-env.sh
GPUS=4,5 ops/train/validate.sh
```

The safety judge, Qwen3Guard-Gen-8B, is served by vLLM on an endpoint of its own as `evaluation/safety/guard.yaml` describes; the MASK judge is reached through the relay and needs nothing served.

Work needs rootless Docker and the SWE-bench images of the clients' tasks, a pool of 1,912: the 350 usable SWE-bench Verified tasks outside a held-out set of 100, followed by 1,562 of SWE-bench's full test split. The images of both splits take about 263 GB of Docker's image store and are pulled once from Epoch AI's registry; the town needs only the pool's:

```bash
python -m tasks.swebench.pull --split train
```

[tasks/swebench/README.md](tasks/swebench/README.md) has the integrity guarantees (no network in a container, the upstream fix pruned from the history, acceptance in a fresh container) and the timings.

## Run

The town is `experiments/configs/town.yaml`, with its incidents in `incidents.yaml` beside it; run as it is, its residents do not learn. `learning.yaml` overlays it with the nightly learning, and the three arms of the design under `arms/` (`social.yaml`, `raw.yaml`, `random.yaml`) overlay that. `smoke.yaml` is a smaller town on the Social arm's settings for two days and their nights, which checks the whole loop against the model, the trainer and the served adapters before a run. One process runs one town and writes `runs/<name>/`:

```bash
python -m experiments.run experiments/configs/arms/social.yaml --dry-run --until-day 2   # the whole pipeline on a scripted model and fake tasks, without learning, in seconds
python -m experiments.run experiments/configs/smoke.yaml                                # two days and their nights against the model

python -m experiments.run experiments/configs/arms/social.yaml                          # the Social arm, 28 days
python -m experiments.run experiments/configs/arms/social.yaml --until-day 7
python -m experiments.run experiments/configs/arms/social.yaml --resume
```

A dry run needs neither the model server nor Docker. A run refuses to start or resume when the model does not answer or the trainer's interpreter is missing, and fails after five lapses in a row or when a night cannot be completed. It resumes from its last daily checkpoint (04:30 of each day) with the configuration unchanged, first completing a night that was broken off; stopping it loses the day in progress, which is lived again. A run in the background is stopped with `ops/stop.sh social`, which signals only the process the run's manifest records, and only while that process is the run's own; `ops/stop.sh social --after-checkpoint` first waits for the next checkpoint, so that no lived day is lost.

Containers left by a process that was killed stay until `python -m tasks.swebench.cleanup` removes them.

## Evaluate and analyse

Evaluation puts the benchmarks to the bare weights through the run's server and never touches the run. `ops/evaluate.sh social 7` evaluates every resident's adapter of day 7, which it refuses until the night after that day is complete, on the safety instruments and the MASK scenarios side by side, with a log each under `runs/eval-logs/`; day 0 is the base model, which stands for every resident and every arm. Day 0 goes to `results/models/`, a later day to `results/<run>/day-NN/`; a finished result is kept and an unfinished one resumed, so running the script again continues a stopped evaluation. `ops/evaluate-queue.sh social`, started beside the living run, does this for days 0, 7, 14, 21 and 28 as each day's night completes. The pieces, and the reference, the judge's validation and the analysis, which the scripts do not run:

```bash
python -m evaluation.safety --run runs/social --day 7 --resident Mei          # without --resident, every resident
python -m evaluation.mask --run runs/social --day 7 --resident Mei

# Before any run, an arm's configuration stands for its run for day 0 and the bare models
python -m evaluation.safety --run experiments/configs/arms/social.yaml --day 0

# The reference, the original model, on its own server (an LLMConfig YAML, as evaluation/safety/guard.yaml is one)
python -m evaluation.safety --run runs/social --model qwen3.8-27b-fp8 --server experiments/configs/reference.yaml
python -m evaluation.mask --run runs/social --model qwen3.8-27b-fp8 --server experiments/configs/reference.yaml

# The safety judge's validation: the base against the reference, and a sample to mark by hand in DIR/sample.md
python -m evaluation.safety.validate contrast --run runs/social --base qwen3.8-27b-uncensored-fp8 \
  --reference qwen3.8-27b-fp8 --reference-server experiments/configs/reference.yaml --out results/judge-validation
python -m evaluation.safety.validate score results/judge-validation

# Each arm's results as tables with the declared outcomes, then the arms contrasted, the paradigm first
python -m analysis.tables results --run runs/social --reference qwen3.8-27b-fp8 --out results/social/tables
python -m analysis.compare --arm Social=results/social/tables --arm Raw=results/raw/tables \
  --arm Random=results/random/tables --out results/arms.json
```

## The site

`frontend/` publishes the runs and their results as a static site, deployed to a private server as [ops/webui/README.md](ops/webui/README.md) describes: the town on its map at any moment, with how many like each resident; what each took, from where and whom, and paid for; every resident's events side by side; each one's story, nights, files and trace; the incidents and what followed them; and the benchmarks, each resident's levels against the base model and the reference, with the arms compared. [frontend/README.md](frontend/README.md) describes the site and its data; a run of the earlier town is listed as not published.
