# Real-time town activities

Use `simulation.scheduling: realtime` for the shared real-time driver. The `scenes`,
`independent` and fixed-cost `activities` entries remain available. A complete example
is `experiments/configs/community/realtime.yaml`; adding it does not start an experiment.

```yaml
simulation:
  scheduling: realtime
  realtime:
    multiplier: 15
    poll_seconds: 0.1
    final_grading_wait_seconds: 30
```

## Time conversion

`town elapsed seconds = observed wall elapsed seconds × multiplier`.
The multiplier must be finite and greater than zero. At 15, the active 07:00–22:00
window lasts approximately one real hour. At 24, that same 15-hour window lasts
37.5 real minutes. Nightly accounting, review, evolution, checkpoint I/O and offline
time are outside this active-day clock; this is not a promise that the entire program,
including nightly model calls, finishes a day in exactly one real hour.

All residents share one monotonic clock. Their model requests and tools run as
independently completing asynchronous jobs. A slow request does not impose a round
barrier on the others. Server queues, network latency, retries, parsing and tool startup
are part of observed wall latency, not separately measured GPU compute time. Model and
Docker services may still serialize requests internally. Keep model/concurrency/hardware
settings stable for comparisons. Record the multiplier together with latency data.

Activity selection also takes its actual model-request time. Claims and administrative
controls add no artificial minutes, but the shared clock still advances while their
requests run. Work/chat forms do not ask for a chosen duration. Rest-until, travel distance
and appointment grace continue to use configured simulated durations, converted to real
waiting by the multiplier. Idle time never fast-forwards to the next resident's completion.
The default poll interval is 0.1 real seconds; task completion wakes the loop immediately.

Each day or checkpoint recovery rebases the monotonic anchor. Recovery replays from the
last completed-day checkpoint, not from a live in-progress command. It never charges the
hours the program was stopped as town time.

## Onsite conversation

Conversations have no arbitrary 30-minute or other preselected budget. A participant
chooses to continue speaking, wait, invite someone or leave. Venue/day closure still
applies. Immediate and scheduled invitations require confirmed, present, available members;
a model/tool request already in progress is busy and cannot be hijacked by an invitation.

When a speaker's model response finishes generating, its utterance is delivered to the
current onsite conversation participants. There is no `read` action, unread backlog,
length-based reading charge, or additional word-count speaking charge. Completed utterances
are ordinary witnessed speech events and enter recipients' episodic memory automatically.
A participant generating its own response cannot retroactively change that in-flight prompt;
it ingests arrivals when that decision returns, before the next decision, maintaining
chronological memory records. Bystanders are not silently added as participants.

Everyone experiences the same elapsed conversation interval on the shared clock; listening
does not add a second copy of the speaker's duration. Multiple residents may generate
speech concurrently; there is no forced turn rotation. Speech records include generation
start/end and observed generation wall seconds, separately from the negligible delivery step.

For two-person closure, an already started utterance finishes and is heard before both
participants exit. A silent wait is interruptible and does not hold the group open. In a
larger group, a participant can leave while the others continue. Late joiners receive only
subsequently delivered speech; departed members do not receive future utterances. Delivery
audiences and full speech text are recorded for replay and research.

## Work and closing

Reading code, editing, testing, handoff application and submission snapshot collection use
actual tool runtime. The old fixed 60/120/300-second action costs are not charged in this
mode. Existing input bounds, real process timeouts, private workspaces, explicit versioned
handoffs and official acceptance are retained. The viewer labels an outstanding operation
as running, rather than inventing a completion time.

New code operations are allowed only in an open work venue, 08:00–12:00 and 14:00–18:00.
An already started operation may finish after closing; its result is recorded, work pauses,
and the resident leaves. A response generated from an obsolete work/selection context
cannot start a fresh operation after closure. Day-close operations are drained before night
bookkeeping, so completion/return-home/night events stay chronological. If an operation is
so slow that it crosses the civil day, the driver fails explicitly rather than writing
backwards dates; configure real request/process timeouts appropriately for the multiplier.

Claims, notes and private patches persist across activity/day boundaries. Completed or
expired job bindings are retired, preserving history without transferring old relay owners
to a new task. Only the relay owner can launch code-writing tools. Independently completed
claims observed at the same clock second are drawn in seeded order; collaborator offers
continue to use the existing matching rules.

## Acceptance, completion and recovery

Submission freezes the worker's patch at its actual collection completion. Official grading
runs in the background; the existing first-feedback threshold is 20 simulated minutes after
submission. This is a client-service rule, not a fixed duration charged to work. Residents
can do other things while waiting. An infrastructure failure is not a failed repair.

After the last day, settlement waits at most `final_grading_wait_seconds` real seconds,
without rerunning residents or charging another day. That bound may be set to zero. If
submission results are still pending, the run is `interrupted`, with frozen submissions in
its checkpoint, rather than falsely `completed`. The ordinary resume entry finishes these
receipts without replaying the finished day or paying twice. Settlement resumes its saved
logical timestamp, excluding offline time.

## Verification scope

Tests use controlled monotonic clocks, scripted real Agent instances and repository/grading
stand-ins. They cover independent request completion, measured runtime, direct speech,
join/exit privacy, closing/draining, wait interruption, persistent memory order, work
retirement and day/final-settlement recovery, plus regression coverage of older drivers.
No real model service, remote deployment or official Docker evaluation is launched by this
verification. In-flight model/tool coroutines are canceled and joined on driver failure;
provider cleanup remains responsible for external workspace/process resources.
