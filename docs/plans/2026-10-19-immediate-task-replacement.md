# Immediate Task Replacement Implementation Plan

**Goal:** Replace accepted or retired jobs immediately with a public job requiring
exactly the same number of workers, without replacing failed or expired claims.

**Architecture:** Add an opt-in immediate timing for replenish mode; keep the legacy
morning timing as the default for old configs. Use one deterministic posting helper
for initial stock and replacements, preserving worker count, trade, sheet and the
issued-reference exclusion. Existing settlement events retain the completed job's
archive and official report. Do not change the running frozen experiment.

**Tech Stack:** Python/Pydantic environment, asyncio activity/realtime engines, pytest.

## Tasks
1. Add failing regression tests in tests/core/environment/test_technical_community.py:
   immediate solo and joint replacement, failure/outage, expiry, retirement, no
   preferential claim, no duplicate morning refill, and exhausted pool.
2. Add replacement_timing to core/environment/config.py, default morning; enable
   immediate timing in experiments/configs/community/{activities,realtime,lite,verified}.yaml.
3. In core/environment/environment.py extract deterministic single posting from
   _post; use it for a completed successful claim and an unclaimed retired notice.
   Preserve existing demand counting and return expired tasks rather than replace.
   Emit explicit replacement-unavailable feedback when the finite pool is empty.
4. Update rules and runtime/activities/engine.py pending-assessment context plus
   runtime/realtime/engine.py submission feedback: rest/socialize while awaiting
   acceptance; another job may only be claimed after the existing claim is released.
5. Run targeted environment and activity tests, then the related combined regression
   suites; run ruff and git diff --check; commit locally, without remote deployment.

## Verification
Use PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=/tmp/socio-community-deps:. and
/opt/anaconda3/bin/python3 -m pytest -p pytest_asyncio.plugin for the named suites.
The new tests should first fail against morning-only behavior, then pass. Verify
append and morning configs retain their prior semantics. No experiments are started.

## Verification results

- Initial new tests failed against the old morning-only behavior (4 failures), then
  passed after implementation. The final technical-community suite has 12 passing tests.
- Related community/activity/realtime/scenes/SWE-bench/interaction/memory/frontend
  regression suites: 281 passed. Additional environment suite: 101 passed, 2 deselected.
- Two pre-existing expanded-suite failures remain outside this change: a coding-provider
  test requires unavailable Linux bubblewrap on this macOS host; the old night-desk test
  asserts that the ledger sentence ends the entire review prompt, which predates the
  mandatory attributed review context. The latter failure was reproduced from an
  untouched HEAD archive at commit 6801fd5. No test assertion was weakened to hide it.
- Ruff checks, formatting and git diff --check passed. No live experiment was restarted
  or changed; new defaults apply only when a new config is loaded.
