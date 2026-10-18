# Technical community implementation plan

**Goal:** Implement the approved eight-resident, 42-day SWE-bench community on the existing feature branch.

**Architecture:** Separate worker count from deliverable count: two residents may share one repository issue and one accepted patch. Add opt-in inventory replenishment and strict acceptance without changing old experiment semantics. Persist issued references and workspace checkpoints for deterministic recovery.

**Tech stack:** Python/Pydantic, YAML, existing Docker SWE-bench harness, pytest.

Approved scope: 6 solo + 1 joint outstanding jobs; morning replenishment only; no shelf expiry; two-day initial deadlines; one issue per joint job; official success required for payment; joint premium shared equally; 08–12/14–18 work and 22:00 social closing. Enable existing recall, budgets and work journals. New task-note summaries separate from immutable logs. Keep subjective relationships in private text and existing public reputation until further environment specifications. Home learning beyond nightly reflection is not yet specified.

1. Add regression tests in tests/core/environment/test_technical_community.py for stock replenishment, expiry, joint single-deliverable claims, strict payment and checkpoint restore. Add backward-compatible fields to core/environment/config.py, society/work.py and environment.py; update work scene allowances and prose.
2. Extend tasks/swebench/provider.py with deterministic unused-instance selection, joint workspace visibility and recorded command attribution, configurable deadlines, provider workspace checkpoint/restore and explicit evaluation failures. Update experiments/config.py, experiments/run.py and runtime/simulation/simulation.py. Test with fake providers/containers; no live Docker required for unit tests.
3. Add Lite/Verified preparation and configurations under experiments/configs/community/ using town residents and finances, approved slots, and recall/work notes/budgets. Validate configuration and dataset provenance locally.
4. Add editable per-task summary separate from the fact log, bounded internal note writing and context retrieval; keep skills index in system under total budgeting. Test note privacy, persistence and unchanged observations.
5. Run focused tests, then relevant runtime/analysis/evaluation compatibility tests. Document implementation, limitations, commands and verification. Commit locally on codex/feature-development; no push or live deployment.

Verification command: PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=/tmp/socio-test-deps:. python3 -m pytest -p pytest_asyncio.plugin <test paths> -q
Expected: passing behavioral tests, ruff clean, and new configs load. Real official evaluation remains a deployment smoke check and must not be claimed from mocked tests.
