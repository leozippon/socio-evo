# socio-evo: collective AutoResearch

An event-driven society carrying out one shared research project. This version builds on `leozippon/socio-evo` branch `redesign-event-runtime` (`8cca4f9`) and its shared-workspace pilot.

The town and academy choose their own question, submit a proposal on simulation day 7 and an initial manuscript on day 28, and receive living funds according to an external scientific review. Residents use Lightingtheword `DeepSeek-V4.1-Flash`; the separate judge uses `gpt-6.1-sol`. No local inference service or SWE-bench dataset is needed for these experiments.

See [the design summary](docs/summary.md) and [the research protocol and operation guide](docs/research.md). The original SWE-bench/personality study remains available through its [legacy workflow](docs/archive/upstream-workflow.md) and configurations.

## Prepare on Zenith

Use Python 3.11+ and Docker on the execution host. Keep all run state, evidence, logs and reports in project storage, outside the checkout.

```bash
pip install -e '.[research,dev]'
docker build -t socio-evo-research:local -f ops/research/Dockerfile .
set -a; . "$HOME/.config/socio-evo/credentials.env"; set +a
```

The private file supplies `LIGHTING_API_KEY` and `TAVILY_API_KEY`; `SEMANTIC_SCHOLAR_API_KEY` is optional. Keys are never committed. Provider connectivity, model compatibility and Docker execution must pass the pair launcher's preflight before either arm starts. See the protocol for commands, resume, optional GPUs and the read-only viewer.

## Verify

```bash
python -m pytest -q tests/world tests/agent tests/simulation tests/experiments tests/infrastructure
ruff check .
```

Additional legacy tests require SWE-bench dependencies, Docker images and Linux utilities. Tests construct temporary worlds; production experiments run only on Zenith. The earlier 14-day pilot is separate from the new two-arm study and is not resumed with a changed protocol.
