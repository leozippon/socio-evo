# Real-time activity scheduling

`simulation.scheduling: realtime` is the opt-in wall-clock variant of [Activity scheduling](activity-scheduling.md). The `scenes`, `independent` and fixed-cost `activities` schedulers remain available. Example configuration: `experiments/configs/community/realtime.yaml`.

```yaml
simulation:
  scheduling: realtime
  realtime:
    multiplier: 15
    poll_seconds: 0.1
    final_grading_wait_seconds: 30
```

## Shared clock

Town time advances by observed wall time multiplied by `multiplier`, which must be finite and positive. At 15, the active 07:00–22:00 period lasts about one real hour; at 24, about 37.5 minutes. Nightly accounting, reflection, evolution, checkpoint I/O and time while the program is stopped are outside this active-day clock, so a complete run day is not guaranteed to finish within that duration.

Residents share one monotonic clock, while model requests and tools complete independently. Request queues, network latency, retries, parsing and startup contribute to observed wall time; this is not a measurement of GPU compute time. Services may serialize work internally, so keep model, concurrency and hardware settings stable when comparing runs and record the multiplier with latency data. Activity choices and actual request time advance the shared clock. Administrative controls add no artificial delay. Rest, travel and appointment grace use their configured simulated durations. Idle time does not fast-forward to another resident's completion; the 0.1-second default poll is also woken by task completion.

The clock anchor is reset at day start and checkpoint recovery. Recovery replays the last completed day, not an in-progress command, and excludes offline time.

## Conversation and work

Conversation uses the activity membership rules in [Activity scheduling](activity-scheduling.md), with direct speech delivery. When a speaker's model response finishes, its utterance enters the listeners' episodic memory as witnessed speech. A spontaneous public conversation is audible to nearby residents, including those who have not joined; other conversations address their participants. There is no explicit read action, unread backlog, or length-based read and reply charge. Participants can speak concurrently without fixed turn order; everyone shares the same elapsed interval. Bystanders are not added automatically. A recorded join starts membership at that point in the event timeline; late joiners receive later speech only. A recorded departure ends membership, so departed members receive no future messages while the rest of a group may continue. The `realtime` community example also opts into the lunch and evening choices described in [Activity scheduling](activity-scheduling.md).

Model requests stream while the shared clock continues. Each Activity defines its interruption conditions. A resident choosing its next activity resumes when another resident opens a conversation it can currently access; the new observation shows the available conversation without automatically joining it. Remote or inaccessible private conversations, later arrivals and speech do not retrigger this selection rule. Other ordinary observations do not interrupt activity selection or Work decisions. Conversation first chooses an action and, for a reply, an explicit list of addressed members. This choice has no thought or speech field. A reply then generates a brief private thought and its words on one answer card. The thought is recorded with the decision for inspection; only the words are delivered to listeners. These cards retain automatically retrieved context and do not add internal recall or note-writing choices. Addressed members are fixed for that reply and are distinct from everyone who can hear it. The recipient list is bounded by the number of currently eligible members, including in the JSON Schema used for format correction.

Both conversation action selection and reply generation resume for new speech explicitly addressed to the resident in that conversation. Speech audible to bystanders or addressed to other members waits for the next observation. A pending reply also resumes when one of its selected recipients leaves. Other members arriving or leaving, nearby conversations and unrelated town events do not interrupt these decisions. A departed target causes a new choice of action and recipients while preserving the latest received draft; a closed conversation cannot resume a reply. A target's exit is not held open waiting for an unfinished directed draft. Normal day-end draining and already-delivered speech retain their existing lifecycle rules.

A continuation keeps the most recently received nonempty answer draft alongside stable context and one current situation. New observations replace previous snapshots. Cancellation before any new answer text arrives keeps the last available draft. Decisions are checked against the current Activity and available actions before final acceptance. Only accepted actions are committed; partial drafts are neither speech nor executed actions. The community realtime example disables thinking. Original calls remain in the model-call log, and interruption events record the decision/request association, changed fields and source event numbers without repeating full environments or drafts.

Retries within the same observation keep the received draft without appending the whole situation again. A cut-off reply keeps its output allowance; an invalid reply receives a short format correction. Environment changes instead resume with the latest observation and the most recent draft. Before each request, enabled context budgets account for the required current situation, latest draft and format correction before allocating the remaining input allowance to optional context by priority. The final assembled-request check still reserves the full output allowance. If required input alone cannot fit, the call fails explicitly before reaching the model.

A silent conversation wait retains its existing message-wakeup and deadline behavior. Before publication, an utterance identical to the speaker’s last utterance after whitespace normalization is suppressed if its recipients are unchanged and nobody else has spoken in between. The resident instead waits and receives a brief private action-result reminder. Different wording or recipients, a new incoming utterance or a new conversation permits speech; this does not impose a turn order or semantic similarity filter. Delivered speech events record generation start and end, observed generation time, full text and delivery audience. The scheduler waits for cancellation cleanup before resuming; slow cleanup can delay processing other completed actions.

Code reads, edits, tests, handoff application and submission snapshot collection use their actual runtime; the fixed costs in `activities` mode do not apply. Existing input bounds, process timeouts, private workspaces, versioned handoffs and official acceptance remain in force. An outstanding operation is shown as running until it completes.

New code operations require an open work venue and the 08:00–12:00 or 14:00–18:00 work window. An operation started before closing may finish afterward; its result is recorded, work pauses and the resident chooses what to do next. A response based on an obsolete work or selection context cannot start a new operation after closing. Day-close operations are drained before nightly bookkeeping. If an operation crosses the civil day, the driver fails explicitly rather than writing events with backward dates; configure real request and process timeouts for the chosen multiplier.

Claims, notes and private patches persist across activities and days. Completed or expired job bindings are retired without transferring old relay ownership to a new task. Only the relay owner can launch code-writing tools. Simultaneous claims observed in the same clock second are ordered by the seeded draw; existing collaborator matching rules remain in effect.

## Settlement and recovery

Submission freezes the patch when snapshot collection finishes, then official grading runs in the background. The first feedback is due after 20 simulated minutes; this is a client-service rule, not a fixed work charge. Residents can continue with other activities while they wait. Infrastructure failures are not failed repairs.

After the last day, settlement waits up to `final_grading_wait_seconds` real seconds, including zero if configured. If results remain pending, the run is marked `interrupted` with frozen submissions in its checkpoint rather than reported as complete. Resume finishes those receipts without replaying the finished day or paying twice. Settlement continues from its saved logical timestamp and does not include offline time.
