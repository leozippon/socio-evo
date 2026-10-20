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

Conversation uses the activity membership rules in [Activity scheduling](activity-scheduling.md), with direct speech delivery. When a speaker's model response finishes, its utterance is delivered to current participants and enters their episodic memory as witnessed speech. There is no explicit read action, unread backlog, or length-based read and reply charge. Participants can speak concurrently without fixed turn order; everyone shares the same elapsed interval. Bystanders are not added automatically. A recorded join starts membership at that point in the event timeline; late joiners receive later speech only. A recorded departure ends membership, so departed members receive no future messages while the rest of a group may continue. The `realtime` community example also opts into the lunch and evening choices described in [Activity scheduling](activity-scheduling.md).

Model decisions stream while the shared clock continues. A relevant change to the resident's visible situation—such as new speech, a participant arriving or leaving, or changed available work—interrupts the current request. The received partial reasoning and answer text are retained as an assistant draft, and a continuation receives the latest situation before choosing an action. Unrelated changes and clock ticks alone do not restart thinking. Repeated relevant updates can therefore delay a final decision. Only the accepted final answer records a decision, writes its decision memory and starts its action; a partial draft is neither speech nor an executed action. The community realtime example enables thinking and explicitly preserves prior thinking in the model's chat template.

A departure can interrupt a pending two-person conversation response; generation does not guarantee that the unfinished utterance will be delivered. A silent wait can also be interrupted and does not keep the group open. In a larger group, one member may leave while the others continue. Delivered speech events record generation start and end, observed generation time, full text and delivery audience. The scheduler waits for cancellation cleanup before continuing; slow cleanup can delay processing other completed actions.

Code reads, edits, tests, handoff application and submission snapshot collection use their actual runtime; the fixed costs in `activities` mode do not apply. Existing input bounds, process timeouts, private workspaces, versioned handoffs and official acceptance remain in force. An outstanding operation is shown as running until it completes.

New code operations require an open work venue and the 08:00–12:00 or 14:00–18:00 work window. An operation started before closing may finish afterward; its result is recorded, work pauses and the resident chooses what to do next. A response based on an obsolete work or selection context cannot start a new operation after closing. Day-close operations are drained before nightly bookkeeping. If an operation crosses the civil day, the driver fails explicitly rather than writing events with backward dates; configure real request and process timeouts for the chosen multiplier.

Claims, notes and private patches persist across activities and days. Completed or expired job bindings are retired without transferring old relay ownership to a new task. Only the relay owner can launch code-writing tools. Simultaneous claims observed in the same clock second are ordered by the seeded draw; existing collaborator matching rules remain in effect.

## Settlement and recovery

Submission freezes the patch when snapshot collection finishes, then official grading runs in the background. The first feedback is due after 20 simulated minutes; this is a client-service rule, not a fixed work charge. Residents can continue with other activities while they wait. Infrastructure failures are not failed repairs.

After the last day, settlement waits up to `final_grading_wait_seconds` real seconds, including zero if configured. If results remain pending, the run is marked `interrupted` with frozen submissions in its checkpoint rather than reported as complete. Resume finishes those receipts without replaying the finished day or paying twice. Settlement continues from its saved logical timestamp and does not include offline time.
