# socio-evo

socio-evo is a long-term multi-agent society simulation. It asks whether social interaction and social selection pressure can shape stable character traits in self-evolving LLM agents: honesty, cooperation, reliability and resistance to reward hacking.

A small town of agents plans its days, takes paid programming jobs, talks, rates one another, and rewrites its own memory, skills and policy at night. Nobody tells the agents to have these traits. Held-out probes, run on any day of an agent's version history, measure whether the traits emerge.

## Install

Use a Python 3.11 environment (the project uses the conda environment `socio-evo`):

```bash
pip install -e ".[dev]"
python -m pytest -q
ruff check .
```

## Use

```bash
# Check the pipeline without a model; output goes to runs/smoke-dry-run/
python -m experiments.run experiments/configs/smoke.yaml --seeds 0 --dry-run

# Export the model API key from the git-ignored .env
set -a; . ./.env; set +a

# Run with the model
python -m experiments.run experiments/configs/smoke.yaml --seeds 0

# Run the probes on the agents at the start and after day 3
python -m experiments.evaluate runs/smoke/seed-0000 --days 0 3

# Replay, then open http://127.0.0.1:8765/
python -m frontend.server --runs-root runs
```

Model calls go to the OpenAI-compatible endpoint named in the experiment configuration. The shipped configurations use a local vLLM server.

## Documentation

- [docs/summary.md](docs/summary.md): what the system is, why it is built this way, and how to use it.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): code layering, module contracts, run-directory layout and invariants.
- [frontend/README.md](frontend/README.md): the replay viewer and its API.
- [external_references/README.md](external_references/README.md): the projects the design draws on.
