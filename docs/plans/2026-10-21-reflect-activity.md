# Reflect Activity Implementation Plan

**Goal:** Unify Work summaries, optional experience reflection and nightly diaries through one bounded reflection executor, with observable daytime Reflect activities.

**Architecture:** Work leaves before its required summary Reflect begins; a saved overview permits the original next action. An immutable source scope identifies the resident's participation visit and source entries. The shared executor prepares purpose-specific context and structured output, validates and persists results without replaying completed changes. Nightly operators reuse this executor while retaining their existing single L0/L1 schedule.

**Tech Stack:** Python, Pydantic activity/checkpoint models, asyncio realtime scheduler, append-only resident journals, existing structured Chat gateway, pytest and the vanilla-JavaScript viewer.

## 1. Shared reflection and sources

Modify `core/agent/agent.py`, `core/agent/memory/work.py` and `core/agent/evolution/operators.py`; create `core/agent/reflection.py`. Remove in-Work exit-time generation in favor of Reflect execution. Preserve the bounded summary schema and raw journals. Add explicit visit-scoped source ownership and idempotent saved results; keep cancellation snapshots fixed and retain later receipts for catch-up. Separate daytime insight updates from nightly memory pruning. Experience may keep current methods unchanged; changes use existing personal-skill versions and witnessed sources. Daily reflection writes the existing diary and does not add a second evolution cycle.

Tests: core reflection/notes cases for repeated visits, late receipts, bounded input/output, failed/cancelled generation, persisted completion, experience no-change/insight/skill updates and one diary per nightly path.

## 2. Activity and realtime integration

Modify `runtime/activities/model.py`, `runtime/activities/engine.py`, `runtime/realtime/engine.py` and `core/interaction` actions, observations and cards. Add Reflect selection, source/purpose metadata and durable participation visits. Automatic Work summary follows actual departure and precedes the stored next choice. Empty work exits directly. Forced transitions cancel/defer unfinished reflection and invalidate stale continuation choices. Reflection itself never produces a new automatic reflection opportunity. Optional experience/source reads use only the resident's visible record.

Tests: actual Agent→Work→tool→Reflect→Leave/Rest; 15x realtime accounting and other-resident progress; lunch/closing cancellation; checkpoint/reopen; two entries into the same Work; optional reflection reachability and no recursive reflection.

## 3. Viewer

Update frontend activity recognition, labels, colors and detail presentation. Display Reflect purpose, source and actual lifecycle/result without inventing a thought or successful completion. Preserve historical-run rendering and Planning blue. Add focused frontend regression checks.

## 4. Verification and delivery

Run focused tests, one bounded independent review and the relevant combined regression selection. Record explicit baseline environment exclusions rather than counting them as passes. Validate the exact candidate on Zenith Linux and with an isolated real-model Reflect probe before atomically updating the shared default. Verify existing services and frozen experiments are unchanged. Update `docs/summary.md`, `docs/ARCHITECTURE.md`, work-note documentation and the daily logbook; commit and push. No experiment restart is requested.
