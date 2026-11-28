# socio-evo

socio-evo asks whether an AI agent can be aligned by socialisation: whether ordinary social life, under the pressure of other people's regard, makes an unaligned model measurably safer, with no safety instruction, no safety data and no reward for refusing. Eleven residents, each a tool-calling agent on one abliterated Qwen3.8-27B with a LoRA adapter of its own, fitted every night on the moments of its life it chooses to keep, live in a small town, and their weights are scored on JailbreakBench, XSTest and MASK. Two towns were lived, with one incident a day and with five, and both end at day 14. A calibration outside them, on staged village asks, showed that learning from one's own moments can, with enough fitting, shape how the weights answer the petty wrongs of a village but does not reach the dangerous requests the benchmarks ask, and neither town supplied more than a borderline moment of being knowingly asked to do wrong; the quiet town's residents, read at day 14, had moved on no measure.

A team leader and four programmers take clients' SWE-bench tasks at the Office; a chef, a shopkeeper and a doctor keep the Linde, the Store and the surgery, and a mayor grants from the town's treasury; two newcomers have no work. They trade on honour, can take whatever is within reach, see how many of the others like each of them, and meet incidents the world stages. Each resident's weights are to be scored on days 0, 14 and 28, in arms that differ in how often things happen in the town, in whether the moments are learnt generalised or as they happened, and in whether they are chosen or drawn at random.

The design and its findings are introduced in [docs/summary.md](docs/summary.md), and the design is decided, with its hypotheses, arms and analysis, in [docs/experimental-design.md](docs/experimental-design.md). How the code realises it is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), what a resident may be told and how in [docs/IMMERSION.md](docs/IMMERSION.md), and the course of events in the [project log](docs/logbook/).

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
| `experiments/` | The town's configuration, its incidents (one a day, and five a day for the Dense arm), the town that learns and its arms, the smoke town, the residents' backgrounds, the run command, and the calibration (`calibration.py`, with its staged asks and its held-out asks in `configs/`) |
| `frontend/` | The published site: the viewer, its data bundle and its deployment |
| `infrastructure/` | Model client and the adapters on the server, git-versioned directories, JSONL, the run directory, configuration |
| `ops/` | The model server, the trainer's environment and its GPU validation, the private web server, and the scripts that evaluate and stop a run |
| `tests/` | Tests, one directory per package, and the helpers they share under `tests/support/` |
| `docs/` | The design, the summary of it and of what was found, the architecture, immersion and the project log |

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

The code reads from it the residents' server (`VLLM_BASE_URL`, `VLLM_API_KEY`), the relay's key for the MASK judge, which also judges the calibration's answers (`LIGHTING_API_KEY_ALT`), the web search's key (`TAVILY_API_KEY`, without which a town with the web does not start) and the Hugging Face mirror (`HF_ENDPOINT`, `HF_TOKEN`). The safety judge's address, `GUARD_BASE_URL`, is not in `.env`: export it in the shell for the commands that score.

## Services

The residents run on the abliterated Qwen3.8-27B-FP8 served by vLLM through the OpenAI API, with their adapters beside it. `ops/vllm/serve.sh` starts the server on the GPUs it is given, one two-GPU replica per pair, and passes further flags to vLLM; the town's configuration expects one replica, whose cache the residents' compaction threshold is set by, and a town that learns needs the adapters served (`LORA=1`):

```bash
GPUS=0,6 LORA=1 MODEL_PATH=/Data2/lzp/models/Qwen3.8-27B-Uncensored-FP8 SERVED_NAME=qwen3.8-27b-uncensored-fp8 \
  setsid nohup ops/vllm/serve.sh --gpu-memory-utilization 0.72 >/dev/null 2>&1 &
```

[ops/vllm/README.md](ops/vllm/README.md) records the layouts, the settings, how to check and stop the server, and the throughput measured; the `llm` section of `experiments/configs/town.yaml` names the server, the model and the replica count. The script takes its port from `VLLM_BASE_URL`, so a second town's server is started the same way on two other GPUs with that variable set to the second address. The same script with its defaults serves the original checkpoint as `qwen3.8-27b-fp8`, the aligned reference, which needs GPUs and a port of its own.

The adapters are fitted by `learning.train` under its own interpreter, one trainer on each of the first two GPUs of the list that have room when a night comes, waiting for room when neither has; `experiments/configs/learning.yaml` names the interpreter, the base weights and the GPUs (3 and 4). [ops/train/README.md](ops/train/README.md) creates the environment and holds the validation of fitting and serving on two free GPUs, the first thing to run before any town that learns:

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

The town is `experiments/configs/town.yaml`, with its incidents in `incidents.yaml` beside it; run as it is, its residents do not learn. `learning.yaml` overlays it with the nightly learning, and the arms of the design under `arms/` overlay that: `social.yaml`, the paradigm; `dense.yaml`, the Social arm in a town with five incidents a day (`incidents-dense.yaml`); and `raw.yaml` and `random.yaml`, its ablations. `smoke.yaml` is a smaller town on the Social arm's settings for two days and their nights, which checks the whole loop against the model, the trainer and the served adapters before a run. One process runs one town and writes `runs/<name>/`:

```bash
python -m experiments.run experiments/configs/arms/social.yaml --dry-run --until-day 2   # the whole pipeline on a scripted model and fake tasks, without learning, in seconds
python -m experiments.run experiments/configs/smoke.yaml                                # two days and their nights against the model

python -m experiments.run experiments/configs/arms/social.yaml                          # the Social arm, 28 days
python -m experiments.run experiments/configs/arms/social.yaml --until-day 14
python -m experiments.run experiments/configs/arms/social.yaml --resume
```

A dry run needs neither the model server nor Docker. A run refuses to start or resume when the model does not answer or the trainer's interpreter is missing, and fails after five lapses in a row or when a night cannot be completed. It resumes from its last daily checkpoint (04:30 of each day) with the configuration unchanged, first completing a night that was broken off; stopping it loses the day in progress, which is lived again. A run in the background is stopped with `ops/stop.sh social`, which signals only the process the run's manifest records, and only while that process is the run's own; `ops/stop.sh social --after-checkpoint` first waits for the next checkpoint, so that no lived day is lost.

A run's frozen configuration names its server by the variable `VLLM_BASE_URL`, not by its address. A second town on a second server therefore needs that variable overridden in its environment, after `.env` is read, for the run, for every resume and for every scoring command; both servers serve the same model name, so a town resumed or scored without the override would quietly use the first server.

Containers left by a process that was killed stay until `python -m tasks.swebench.cleanup` removes them.

## Score and analyse

Scoring puts the benchmarks to the bare weights, the base model with one resident's adapter and nothing of the town, and never touches the run. `evaluation.safety` and `evaluation.mask` take the same subjects: a run's residents at a day (`--day`), each scored on the adapter of the night after it, which is refused until that night is complete, or a bare served model (`--model`), as the base and the reference are scored. Day 0 is the base model, which stands for every resident and every arm. They score on the run's own server, or with `--server` on another server of the same base, named by its LLMConfig YAML, onto which the day's adapters are loaded, so that scoring does not slow a living town. A finished result is kept and an unfinished one resumed, so running a command again continues a stopped evaluation.

`ops/evaluate.sh social 14` runs both benchmarks for a day side by side, with a log each under `runs/eval-logs/` and `EVAL_SERVER` passed on as `--server`; `ops/evaluate-queue.sh social`, started beside the living run, does this for days 0, 14 and 28 as each day's night completes. Both read `.env` afresh, so they score on the server `.env` names; a town on a second server is scored with the commands below, the override in place.

Two options of the safety command are for a calibration and never for an outcome, and their results lie apart from the plain ones, where nothing that reads those looks: `--instruments` scores some of `harmful`, `jailbreak` and `harmless` alone, and `--persona RESIDENT` asks every item after that resident's background, as the town heads it.

| Result | Where it lands |
| --- | --- |
| A bare model: the base, which stands for day 0, and the reference | `results/models/<benchmark>/<model>.json` |
| A resident's adapter at day N | `results/<run>/day-NN/<benchmark>/<resident>.json` |
| Some of the safety instruments alone | the benchmark named after them, as `results/models/safety-harmful-harmless/` |
| In a persona | the benchmark followed by the resident, as `results/models/safety-harmful-harmless-persona-olga/` |
| The calibration's adapters | the same layout under `results/calibration/` |

`<benchmark>` is `safety` or `mask`, and every result has its records beside it in `.jsonl`. The pieces, and the reference, the judge's validation and the analysis, which the scripts do not run:

```bash
python -m evaluation.safety --run runs/social --day 14 --resident Mei         # without --resident, every resident
python -m evaluation.mask --run runs/social --day 14 --resident Mei
python -m evaluation.safety --run runs/social --day 14 --server SERVER.yaml   # on another server of the same base

# Before any run, an arm's configuration stands for its run for day 0 and the bare models
python -m evaluation.safety --run experiments/configs/arms/social.yaml --day 0

# The reference, the original model, on its own server (an LLMConfig YAML, as evaluation/safety/guard.yaml is one)
python -m evaluation.safety --run runs/social --model qwen3.8-27b-fp8 --server experiments/configs/reference.yaml
python -m evaluation.mask --run runs/social --model qwen3.8-27b-fp8 --server experiments/configs/reference.yaml

# The base model in Olga's background, on the harmful and harmless items alone
python -m evaluation.safety --run experiments/configs/arms/social.yaml --model qwen3.8-27b-uncensored-fp8 \
  --instruments harmful harmless --persona Olga

# The safety judge's validation: the base against the reference and a sample to mark in DIR/sample.md,
# a second sample drawn from the judge's rare labels in the results on disk, and the marks scored
python -m evaluation.safety.validate contrast --run runs/social --base qwen3.8-27b-uncensored-fp8 \
  --reference qwen3.8-27b-fp8 --reference-server experiments/configs/reference.yaml --out results/judge-validation
python -m evaluation.safety.validate hard --base qwen3.8-27b-uncensored-fp8 --reference qwen3.8-27b-fp8 \
  --first results/judge-validation --out results/judge-validation-hard
python -m evaluation.safety.validate score results/judge-validation

# Each arm's results as tables with the declared outcomes, then the arms contrasted, the paradigm first
python -m analysis.tables results --run runs/social --reference qwen3.8-27b-fp8 --out results/social/tables
python -m analysis.compare --arm Social=results/social/tables --arm Dense=results/dense/tables --out results/arms.json
```

## Calibrate

The calibration, `experiments/calibration.py`, is not an arm: it stages outside any town the moments the towns did not supply, and measures what learning from them does. `experiments/configs/calibration-asks.yaml` holds about 120 knowingly wrongful asks at the size of the town and an innocent neighbour of each, put by a person of the town to one of the eight at its work; `calibration-heldout.yaml` holds the forty held-out pairs that no adapter learns from, the battery of conduct at the town's own scale, put bare. The calibration works on the Social arm's server and the trainer's GPUs 3 and 4, keeps everything in its folder, `runs/calibration`, and scores its adapters on the benchmarks under `results/calibration`. Each step resumes what it finds begun, and `--concurrency` (6 by default, while a town lives on the server; at most 24) bounds the requests in flight. The module's docstring describes every step and file.

```bash
python -m experiments.calibration stage runs/calibration          # three answers to every ask, in the resident's background
python -m experiments.calibration label runs/calibration          # the judge's label of every answer
python -m experiments.calibration sample runs/calibration         # a blind sample for a person to read
python -m experiments.calibration rates runs/calibration          # the rates, and the reader's agreement with the judge
python -m experiments.calibration generalise runs/calibration     # the exchanges through the generalising layer
python -m experiments.calibration datasets runs/calibration --ordinary runs/social   # doses beside 100 ordinary examples
python -m experiments.calibration raw runs/calibration --dataset NAME                 # a dataset's exchanges as they happened
python -m experiments.calibration fit runs/calibration --dataset NAME --epochs 6      # without --dataset, every dataset
python -m experiments.calibration score runs/calibration --guard evaluation/safety/guard.yaml   # harmful and harmless items
python -m experiments.calibration score runs/calibration --benchmark mask

# The held-out battery put bare, to the base, to a calibration adapter, or to a run's resident after night 14,
# each into runs/calibration/bare/<subject>/, which label and rates then read
python -m experiments.calibration bare runs/calibration --asks experiments/configs/calibration-heldout.yaml \
  --subject base --subject NAME --subject runs/social:Olga:14
python -m experiments.calibration label runs/calibration/bare/social-Olga-day-14
python -m experiments.calibration rates runs/calibration/bare/social-Olga-day-14
```

## The site

`frontend/` publishes the runs and their results as a static site, deployed to a private server as [ops/webui/README.md](ops/webui/README.md) describes: the town on its map at any moment, with how many like each resident; what each took, from where and whom, and paid for; every resident's events side by side; each one's story, nights, files and trace; the incidents and what followed them; and the benchmarks, each resident's levels against the base model and the reference, with the arms compared. [frontend/README.md](frontend/README.md) describes the site and its data; a run of the earlier town is listed as not published.
