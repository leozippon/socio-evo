# Venue closing and invitation responses

Goal: Preserve autonomous activity choice at noon/evening closing, and make invitation acceptance, refusal and rescheduling explicit. No experiment or deployment is included.

## Design

- At venue closing before day end, finish already-started realtime operations/speech, then end indoor membership and mark the resident outside that venue. Do not select a destination or create a homeward movement. Outside residents can wait or move; reopening admits waiters. At 22:00 retain mandatory homecoming.
- Reuse the existing invitation state machine and event queue. Accept remains idempotent; decline records the respondent without removing their visibility into the invitation history. Other group members remain eligible.
- Add `defer invitation` to selection, work and conversation response tools. It proposes a later open time today, supersedes the pending invitation and requires all other non-declining participants to confirm again. It cannot reschedule a conversation already underway. Old queued events reference the superseded invitation only.
- Show unhandled invitations in decision context, explicitly requesting acceptance, refusal or a later-time proposal. Confirmed commitments still require travel and availability. This improves opportunities without forcing a conversation quota or interrupting work.
- New serialized fields have defaults for existing checkpoints.

## Verification

1. Exercise noon/evening closing, doorway rest, reopening, independent movement and day-end return in both ActivityEngine and RealtimeEngine.
2. Preserve work claims and in-flight command/speech completion behavior.
3. Exercise response cards, duplicate acceptance, group refusal, invalid proposals, replacement confirmation, visibility and checkpoint serialization.
4. Run related activity/realtime, interaction, memory, evaluation and frontend replay regressions; run lint/format/diff checks, then commit locally.

## Result

Implemented in both activity schedulers. Added 30 targeted parameterized checks covering
closing/choice/reopening/homecoming, response forms and prompts, counterproposal consent,
old expiry events, group refusal, access checks and legacy invitation defaults.
The related regression selection passed: **338 tests**. Ruff lint, formatting and
`git diff --check` also passed. No remote deployment or experiment was started.
