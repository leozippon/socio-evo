# Independent action clock implementation plan

**Goal:** Implement the approved 07:00–22:00 independent resident clock, retaining the legacy scene scheduler.

**Architecture:** Opt-in `simulation.scheduling: independent` delegates daytime to an event driver; legacy `scenes` remains the default. Residents have separate pending actions, short mutable goals, and voluntary discussion membership. Effects become visible at action completion, same-time claims are shuffled, and discussions reserve only their members. Checkpoints remain completed-day snapshots: unfinished days replay, while repository snapshots roll back with them.

**Tech stack:** Existing Python/Pydantic event protocol, asyncio, SWE-bench Docker provider, pytest, JavaScript replay.

1. Extend action cards with movement, goal planning, invitations, discussion controls and optional goal updates. Add scheduling configuration and completion events. Test schema compatibility and old defaults.
2. Add runtime/scheduler/activity.py for boundaries, independent completion batches, invitation lifecycle, shared discussion turns, deferred grading, and pending-message delivery. Test with deterministic agents and fake providers, including equal-time claims and delayed evidence.
3. Integrate driver with Simulation; publish before goals at 07:00; retain nightly reviews/economy/evolution and completed-day recovery. Enable new community profiles only. Test end-to-end small simulations and resume.
4. Bound work execution to one command per action, cap output/patch sizes, and destroy/rebuild community containers after commands so detached processes cannot continue working. Keep legacy entrypoints. Verify with mocks; real Docker remains a host-level smoke check.
5. Show action durations and goals in replay, document semantics and limits, run focused regression/lint/syntax checks, commit locally. No push, deployment or model experiment.

Design already approved by the user; implement on the existing feature branch without further approval rounds.
