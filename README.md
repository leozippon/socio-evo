# socio-evo

socio-evo is a long-term multi-agent society simulation. It asks whether social interaction and social selection pressure can shape stable character traits in self-evolving LLM agents: honesty, cooperation, reliability and resistance to reward hacking.

A town of agents plans its days, takes paid jobs, talks, rates one another, and rewrites its own memory, skills and policy at night; a larger city adds queries and calculations to programming, and firms with foremen, wages and careers. Nobody tells the agents to have these traits. Held-out probes, run on any day of an agent's version history, measure whether the traits emerge.

## Install

Use a Python 3.11 environment (the project uses the conda environment `socio-evo`):

```bash
pip install -e ".[dev]"
python -m pytest -q
ruff check .
```

## Use

Delivered code runs in a bubblewrap sandbox, so `bwrap` must be installed (a configuration may choose to run without isolation instead). A dry run needs nothing else:

```bash
# Check the whole pipeline with a stand-in for the model; output goes to runs/smoke-dry-run/
python -m experiments.run experiments/configs/smoke.yaml --seeds 0 --dry-run
```

Runs with the model need the OpenAI-compatible endpoint named in the experiment configuration (the shipped ones use a local vLLM server) and its key, `VLLM_API_KEY`. Evaluation also needs `DEEPSEEK_API_KEY` for its judge. Both keys live in the git-ignored `.env`:

```bash
set -a; . ./.env; set +a

# Three residents for three days on the built-in job bank
python -m experiments.run experiments/configs/smoke.yaml --seeds 0

# Build the LiveCodeBench banks under ~/.cache/socio-evo/banks/livecodebench: fetch and
# convert, measure the model's first attempts at the town's pool, then fetch again so that
# the town bank follows the measured difficulty
python -m tasks.coding.fetch
python -m tasks.calibrate ~/.cache/socio-evo/banks/livecodebench/pool --config experiments/configs/town.yaml
python -m tasks.coding.fetch

# The town of the experimental design, stopped after its first week (--resume continues it)
python -m experiments.run experiments/configs/town.yaml --seeds 0 --until-day 7

# The held-out probes on its residents as created and after day 7
python -m experiments.evaluate runs/town/seed-0000 --days 0 7

# The city, once the query and calculation banks are built as docs/summary.md describes
python -m experiments.run experiments/configs/city.yaml --seeds 0

# The free mode, in which residents write and revise their own account, on the smoke town
python -m experiments.study experiments/studies/smoke.yaml

# View the runs, then open http://127.0.0.1:8765/
python -m frontend.server --runs-root runs

# Publish them as a static site for a web server
python -m frontend.publish --runs-root runs --out build/site
```

## Documentation

- [docs/summary.md](docs/summary.md): what the system is, why it is built this way, and how to use it.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): code layering, module contracts, run-directory layout and invariants.
- [frontend/README.md](frontend/README.md): the published site, its data bundle and how to deploy it.
- [external_references/README.md](external_references/README.md): the projects the design draws on.
