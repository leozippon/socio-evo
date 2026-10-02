# socio-evo

A long-term multi-agent society simulation that asks whether social interaction and social selection pressure can shape stable character traits, such as honesty, cooperation, reliability and resistance to reward hacking, in self-evolving LLM agents. Agents are never instructed to have these traits; the simulation tests whether they emerge from living, working, competing and evolving among peers.

The design is described in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Install and test

Python 3.11 is required.

```bash
pip install -e ".[dev]"
python -m pytest -q
ruff check .
```
