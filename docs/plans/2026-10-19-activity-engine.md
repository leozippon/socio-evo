# Event-driven activity engine implementation plan

**Goal:** Implement the approved two-level, four-activity model with operation-based time, private workspaces and message streams; test and commit locally without deployment or experiments.

**Architecture:** An opt-in `simulation.scheduling: activities` driver runs a deterministic seconds-based event heap. Persistent Rest/Move/Work/Conversation objects replace per-action replanning. Agent activity selection and in-activity tool decisions share the existing memory/retrieval/budget machinery but have separate entry points and prompt purposes. Existing `scenes` and `independent` behavior and minute-based historical records stay compatible; exact seconds are recorded in new event payloads, with minute projections for existing economic/memory APIs.

**Tech Stack:** Python dataclasses/Pydantic, asyncio, heapq, existing environment/task/assessment APIs, SWE-bench Docker workspaces, pytest, JavaScript replay.

## Approved semantics

- No morning planning; activity selection, claiming and partner confirmation are zero-time, batched deterministically. A bounded zero-time-transition guard reports a broken policy instead of spinning.
- Tools reserve configured costs before starting. Read/edit costs are bounded by requested size; text communication uses character/word counts. Commands/tests reserve a fixed budget and retain real timeouts. Results and changes become observable only at simulated completion; no tool crosses activity/venue/day boundaries.
- Activity budgets are ceilings, not prepaid time. Work can pause/resume across activities and days. A person participates in one activity at a time. Joint public work has independent participant budgets and private workspaces; parallel subtask or serial relay cooperation uses immutable handoffs, explicit application and conflict feedback.
- Conversation membership has join cursors and per-member read cursors. Replies arrive at completion, read is explicit, no fixed speaker order, waiting is event-driven, and fewer than two members ends the conversation. Invitations do not interrupt busy tools. Appointments require confirmation, presence and availability, with five-minute grace.
- Assessment starts after submission, first feedback is due after 20 simulated minutes. Unfinished assessment reports delay without a false rejection; outstanding assessment state survives days/checkpoints.
- Activity outcomes are factual, witnessed summaries, preserving existing work journals/economy/night evolution. No extra model reflection is inserted.

## Implementation steps

1. Add `runtime/activities/model.py`: common activity/member/status records, four activity subclasses, message/invitation/handoff records, seconds heap and tool-cost config. Add unit tests for timing, serialization and membership.
2. Extend `core/interaction/actions.py`, `card.py`, `observation.py` and add `activity_card.py` with two-level forms. Extend Agent entry points in `core/agent/agent.py` while preserving legacy `act`. Test schema isolation and actual prompts.
3. Add `runtime/activities/engine.py`: boundary queue, batched selection/claiming, tool completion, rest/movement, pausable work and time reminders. Add tests for independent progression, hard boundaries, zero-time guard, delayed visibility and restart.
4. Implement message-stream conversations, permissions, invitations/appointments and length-based read/reply costs. Test group departure, join history, privacy, busy listeners and expiry.
5. Add private SWE-bench workspace mode and handoff export/integration with conflict rollback in `tasks/swebench/provider.py`; wire `experiments/run.py`. Test snapshots, isolated workers, relay ownership and conflict behavior with fakes.
6. Reuse official assessment/settlement in the engine; persist activity state through Simulation checkpoints. Test background/delayed assessment, shared payout, cross-day pause/resume and interrupted-day replay.
7. Wire opt-in configuration, examples and frontend replay/publisher support. Run focused regressions, lint, syntax checks; document actual coverage and limitations; commit locally. No remote mutation.

## Verification

Use `/opt/anaconda3/bin/python3`, `PYTHONPATH=/tmp/socio-community-deps:.`, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, pytest-asyncio explicit plugin. Run deterministic model/provider tests locally; Docker integration is mock-tested on macOS and must not be represented as a live official-harness validation. Re-run the existing independent clock, interaction, active-context, benchmark and frontend replay suites as appropriate.
