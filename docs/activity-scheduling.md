# Activity scheduling

The opt-in `simulation.scheduling: activities` mode implements event-driven activity
selection. The `scenes` and `independent` entries remain available and existing run
configurations are unchanged. A complete example is
`experiments/configs/community/activities.yaml`. This change does not launch a run.

## Decisions and the clock

An agent calls `choose_activity` when free and `choose_tool` while working or
conversing. Both reuse the existing automatic retrieval, active recall, context
budget and task notes. There is no morning planning call. Rest and movement finish
without polling the model every five minutes. Activity selection, claiming jobs,
confirming partners, accepting invitations and leaving take no simulated time.
Repeated zero-time decisions are bounded and reported as an error rather than
silently advancing the clock.

`ActivityEngine` processes a seconds-based heap of completion, boundary, invitation
and assessment events. All effects due at a moment finish before new observations
are constructed. Residents can have different operation completion times; a slow
operation does not consume other residents' simulated budgets. The implementation
awaits real repository commands when applying their completion event, so wall-clock
throughput is not a guarantee of parallel Docker execution.

An activity's duration is a ceiling, not an additional charge. Before each tool,
the prompt gives exact current time, location, remaining seconds, latest end,
available tools and minimum costs. It adds a warning during the last five minutes.
Actual size-dependent costs are checked again before launch. There is no prompt
injection into an already running model call or terminal command; reminders are
received at the next tool decision. An operation that does not fit is rejected
without executing it. Finishing exactly at the boundary is allowed.

Default costs, configurable under `simulation.activity_timing`:

| Operation | Simulated cost |
| --- | --- |
| Read code | 60 seconds per requested 100-line block, at most 400 lines |
| Apply patch | 120 seconds per 100 patch lines, at most 16 KB |
| Command or local test | 300 seconds; provider wall timeout and resource limits still apply |
| Search, diff, notice board or work feedback | 60 seconds |
| Export/apply handoff | 60 seconds |
| Submit | 60 seconds |
| Invitation inside an activity | 60 seconds |
| Read conversation messages | 500 text units/minute, rounded up to whole seconds |
| Reply | 250 text units/minute, rounded up to whole seconds |
| Movement | Manhattan distance on town coordinates × 60 seconds |

A text unit is one CJK character or one other letter/digit word. Punctuation is
not counted. Read captures the unread message set at launch, allowing an upfront
cost; newer messages require another read. Reply content is known before launch.
Free residents may arrange appointments during activity selection. Work tools
operate only in work venues during 08:00–12:00 and 14:00–18:00. Notice viewing,
claiming, invitations and other non-code controls remain available outside work
hours. Closed venues trigger a timed trip home; the 22:00 day boundary returns
residents home for the existing nightly sequence.

## Work and acceptance

A work activity may pause or be resumed. Claims, private repository snapshots and
per-task notes outlive activities and simulated days. Joining a public work activity
does not create a shared writable checkout. SWE-bench uses independent workspaces
for this scheduler; legacy shared-workspace behavior remains the default for old
schedulers.

Parallel work uses explicit patch handoffs. A handoff freezes a versioned diff;
its recipient must apply it. A three-way Git conflict leaves the saved recipient
snapshot unchanged and returns feedback. Relay work gives one participant write
permission at a time, including any older private activity for that same job.
Offering a relay handoff releases write permission; successful application passes
it to the recipient, while declining returns it to the sender. A conflict keeps
the handoff pending for resolution or decline.

Submission freezes the patch and starts official assessment in the background.
The submitter can choose another activity immediately. The first check is due
20 simulated minutes later. An unfinished assessment reports delay, then is checked
every five simulated minutes. Infrastructure errors are not failed repairs and do
not pay rewards. Existing official acceptance and settlement rules determine actual
success and payment. Pending claims are protected from expiration while the
assessment is outstanding.

## Conversation membership

A single `ConversationActivity` covers private chats and public groups. It has a
message stream and separate per-member join/read positions, without fixed turns.
Members choose read, reply, wait or leave. Waiting wakes on a completed new reply.
Joining reveals only subsequent messages; leaving removes future delivery. Fewer
than two remaining members ends the conversation and cancels unfinished tools.
Notifications contain no message body; the explicit read result supplies it.
Research event payloads retain full content with audience information.

Invitations never interrupt running work tools. A resident can finish an operation,
leave work, move and join. Appointments start only with at least two confirmed,
present, available people. The default grace is five minutes; insufficient turnout
cancels the appointment. Rest can opt into invitation wake-up. Public/invited
permissions are checked again on joining.

## Persistence, logs and verification

Nightly checkpoints include paused activities, messages/cursors, invitations,
immutable handoffs and frozen pending submissions. Existing agent history,
economy and repository checkpoints remain in use. Recovery rolls back to the last
completed day; it is not a mid-command snapshot. Pending grading can restart from
the same frozen patch after recovery. Experiment cleanup cancels outstanding
assessment coroutines before closing providers. A final day may still have pending
assessment if the real harness has not finished; its frozen submission remains in
the checkpoint, and it must not be interpreted as a pass or failure.

New log kinds distinguish activity entry/exit, tool start/completion/cancellation,
message notification/read, handoff and feedback. `payload.sim_seconds` preserves
exact seconds; the existing event `time` is the integer-minute projection used by
legacy memory, economy and day indexing. The viewer shows session/tool occupancy;
historical minute-based views can aggregate several sub-minute events together.
Activity outcomes summarize witnessed feedback and retained progress; they do not
add a free model reflection call.

Deterministic local tests cover clock ordering, cost/boundary rejection, separate
agent decision entry points, membership privacy, message races, invitation grace,
private/relay handoffs, delayed grading, checkpoint recovery and legacy replay.
Handoff merge/conflict tests use real local Git through a container adapter.
No live Docker official-harness run, deployment or model experiment is part of
this implementation verification.
