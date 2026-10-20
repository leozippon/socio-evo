# Activity interruption implementation plan

**Goal:** Resume a streamed reply only for new speech in its conversation or departure of a resident explicitly addressed by that reply; ordinary observations do not cancel other decisions.

**Architecture:** Activity-specific interruption rules share one cancellation entry point and event-linked diagnostics. Conversation first chooses an explicit reply target set, then generates speech, making targets available before streaming begins without guessing from partial natural language. Existing continuation and context packing retain the latest nonempty draft and one current observation. Lifecycle termination remains separate from information-triggered continuation.

**Tech stack:** Existing Python Activity/realtime engines, agent/LLM clients, Pydantic answer cards and pytest; no new event subscription framework.

## Decisions and invariants

The tool-choice step chooses reply recipients or another existing action without a thought field; a reply then generates its words with the minimal text-only answer card, reusing the existing structured decision and budget path. Waiting, leaving and switching to Rest retain their existing flow. Explicit targets must be current other conversation members. A group reply resolves to the current other members at intent acceptance; later arrivals are listeners but are not retroactively added as targets. Actual hearing and addressed recipients remain distinct.

Only a running Conversation reply watches new speech from that conversation and departures among its recorded targets. Non-target departures, arrivals, public news and other conversations do not cancel it. Other Activity decisions accept queued observations on their next turn. A target departure must be allowed to occur instead of being held until an unfinished directed reply completes; pending draft text is not delivered speech. Existing day-end, forced-close and cleanup rules remain separate, preserving already-committed speech delivery where applicable.

Every actual cancellation records actor, Activity, decision/request correlation, simulated time, changed field names and source event sequence numbers. Record the cause before consuming unread observations. Distinguish continuation from lifecycle stop; do not duplicate a cancellation entry when several paths detect the same cause.

Before accepting a final result, validate its action against current membership, target availability, permissions and timing. Invalid results must not be executed. Preserve the shared latest-draft/current-observation budget assembly and explicit required-input overflow behavior.

## Implementation and acceptance

1. In `core/interaction/activity_card.py` and the smallest necessary agent interface, separate explicit reply intent from speech generation. Keep prompts short and avoid an additional long thought in the intent step.
2. In `runtime/realtime/engine.py`, retain reply targets and the reply phase in the existing running-operation state. Replace broad fingerprint cancellation with the per-Activity rules, including the explicit speech invalidation path. Revalidate before final acceptance.
3. Connect source speech/departure events to the shared cancellation entry point and propagate a stable decision association into LLM metadata. Do not log full environments or draft bodies as new diagnostic payloads.
4. Add focused regressions under `tests/runtime/realtime/` and applicable interaction/agent tests: ignored unrelated changes; new local conversation speech; target versus non-target departure; intent/word phases; group targets; cause event IDs surviving observation consumption; one cancellation record; stale-action rejection. Verify failure on the old broad policy where practical.
5. Run affected tests, then the combined infrastructure, agent, interaction, activities, realtime, scheduler/activity-clock and community-config selection. Run Ruff lint/format and diff checks. Independently audit the recipient and cancellation invariants once, without speculative expansion.
6. Update current scheduling documentation and the project log, commit and push. Verify a complete code snapshot on Zenith with the same Linux selection before updating the default for future launches. The running experiment remains frozen at 3a32cdb; this task does not launch a replacement experiment.
