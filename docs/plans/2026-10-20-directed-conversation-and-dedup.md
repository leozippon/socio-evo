# Directed conversation decisions and duplicate speech implementation plan

**Goal:** Resume both conversation action selection and reply generation only for speech addressed to the resident, retain targeted-departure behavior, and suppress confirmed duplicate utterances with brief resident feedback before launching a fresh three-day experiment.

**Architecture:** Keep activity selection and in-conversation decisions as distinct interruption domains. Reuse explicit speech recipients, existing Activity policies, streamed continuations and cancellation records. Check duplicate speech at the commit boundary against successfully published conversation history, then use the existing Wait and feedback path instead of broadcasting or retrying the model.

**Tech stack:** Python Activity/realtime engines, existing event and message records, pytest, Qwen Chat streaming and the existing Zenith launcher.

## Required behavior

An idle resident choosing its next Activity still resumes only when another resident opens a currently accessible conversation. Inside Conversation, new speech resumes either action selection or reply-body generation only if the resident is explicitly addressed. Public audibility is not directed address. A selected recipient leaving resumes its speaker's pending reply; other arrivals, departures, town news and Work decisions do not gain interruptions. Existing lifecycle draining, Rest wakeups and Wait message wakeups remain separate.

Keep the latest nonempty unpublished draft and one current situation, including during intent cancellation. Record real source event sequence numbers, changed fields, decision/request associations and one cancellation per request. Recheck the active Activity and targets before committing.

For the same conversation, suppress an utterance only when its whitespace-normalized text and recipient set equal that resident's last published utterance and nobody else has spoken since. Do not append a message or emit a new speech for the suppressed duplicate. Reuse Wait and give the resident a short action-result reminder. New incoming speech, different text or recipients, or a new conversation permits publication; do not add semantic matching, fixed turns or repeated global prompt rules.

## Implementation and validation

1. Update the Activity interruption policy and realtime speech routing using explicit addressed_targets. Cover conversation intent and body without widening idle activity-selection behavior.
2. Implement the small publication check using existing conversation records, and integrate a private one-time duplicate reminder with the existing wait result and observation.
3. Add focused regressions for addressed intent/Wait race, body cancellation, overheard and unrelated speech, target departures, source-event linkage, preserved drafts/budget, no repeated publication, meaningful negative cases and readable feedback. Run the full existing combined infrastructure/agent/interaction/activities/realtime/scheduler/activity-clock/community selection and lint/format checks.
4. Update scheduling documentation and project log, commit and push. Verify a complete detached Zenith snapshot with the identical Linux selection before switching the future default.
5. Launch a new isolated eight-resident, three-day, seed-0 realtime experiment at multiplier 15, max_tokens 4096, thinking disabled. Preserve all old results and the paused directed run. Verify process identity and accepted actions, save receipts and activate a quiet incremental heartbeat for the new run. Do not restart model, gateway or viewer services.
