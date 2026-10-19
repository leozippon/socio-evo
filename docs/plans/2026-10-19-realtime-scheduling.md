# Real-time activity scheduling implementation plan

**Goal:** Add an opt-in shared real-time clock with configurable scaling and directly heard
onsite conversation. Preserve all three previous schedulers. Test and commit locally;
no experiment, deployment or push.

**Architecture:** `realtime` subclasses the activity engine's task/membership/assessment
primitives but owns an asynchronous driver. Each resident has at most one outstanding
model request or tool operation. A monotonic clock supplies all timestamps; pending
requests do not block boundary events or other residents. Completion time includes
observed request latency (including server/network queuing), rather than an estimated
fixed action cost. Rest/travel/appointments retain simulated durations.

1. Add validated `RealtimeTiming` and injectable `WallClock`; default multiplier 15
   maps the 15-hour active day to one real hour. Rebase on each day/resume; offline and
   nightly housekeeping time does not advance the active clock.
2. Add real-time activity reply forms with no arbitrary chat/work budget and no read
   tool. Keep legacy forms untouched. Immediate/appointment invitations are retained.
3. Implement independently completing LLM requests, repository operations, handoffs and
   submission snapshots. Log measured durations. Block new work after closure, allow
   started operations to finish, then leave. Stop new decisions at day close and drain
   already started operations before night bookkeeping, with chronological timestamps.
4. Deliver completed speech immediately to the current onsite conversation members,
   including busy listeners. No read action or read duration; store directly witnessed
   speech in memory before the next decision and before leaving. Late joiners receive
   only speech delivered while they are members. Never force-cancel another speaker's
   already started utterance merely because a partner requests to leave.
5. Retire completed/expired work bindings in the new driver so relay ownership and
   old sessions cannot migrate to unrelated jobs. Keep pending assessments resumable
   instead of falsely declaring the final day completed.
6. Wire configuration/provider setup/Simulation and example YAML. Add clock, concurrent
   completion, closure, delivery/privacy, rest/travel, cleanup and checkpoint regressions.
   Run legacy regressions and lint. Document actual timing semantics and limitations.

## Completed verification

- 204 scheduler/interaction/provider/config/replay tests, including 27 real-time cases.
- 21 active-recall/context-budget regression tests.
- Ruff lint/format, JavaScript syntax, replay checks and `git diff --check` passed.
- Controlled clock and scripted model/repository tests only; no model service, official
  Docker evaluation, deployment or experiment started.
