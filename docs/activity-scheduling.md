# Activity scheduling

`simulation.scheduling: activities` is an opt-in driver in which each resident chooses an activity and then uses tools within it. The default `scenes` scheduler and the existing `independent` mode remain available. See [Real-time scheduling](realtime-scheduling.md) for the wall-clock variant. Example configuration: `experiments/configs/community/activities.yaml`.

## Prompt and decisions

The system context holds stable information: who the resident is and the town's enduring rules. Each user prompt supplies only the current situation: time and place, people present, current work or conversation, available choices, and the limits that matter now. The activity card lists permitted tools and the facts needed to choose among them. The environment checks every operation again when it starts, so concise prompts do not weaken time, access, permission, or settlement rules. A resident can request `help` for detailed, generated instructions when needed; help does not alter activity state and carries no configured simulated-time cost.

There is no morning itinerary. A resident chooses among Work, Conversation, Rest and Move, then makes tool decisions while the activity continues. Selection and administrative choices such as claiming a job, confirming a partner, accepting an invitation and leaving do not consume configured simulated time. Repeated zero-time decisions are bounded and reported as an error.

The event engine processes operation completions, activity boundaries, invitations and assessments in timestamp order. All effects due at a moment are applied before new observations are built. Each resident has an independent simulated budget; a slow operation does not spend another resident's activity time. Applying repository changes still awaits the real command, so simulated concurrency does not guarantee parallel Docker execution.

An activity's duration is a limit, not a prepaid charge. Prompts state the current time, remaining duration, latest end, available tools and minimum costs. Size-dependent costs are checked again before launch. An operation that does not fit is rejected without execution; finishing exactly at the boundary is allowed.

Leave ends the current activity. From Work or Conversation, a resident can instead choose Rest directly, naming a clock time and whether it falls today or tomorrow; it need not leave and make another activity choice first. Each resident reuses its own Rest instance with fresh membership and timing for every entry, while the event log retains separate entry/exit intervals. An elapsed time today is rejected with the requested ending time and current time; it never silently becomes tomorrow. An overnight wake time survives the normal day-end return home, nightly bookkeeping and checkpoints. At the next day start, residents remain resting until that deadline, or wake immediately if it has already passed. A newly witnessed nearby task claim also wakes a Rest with wakeups enabled, including one waiting for a confirmed conversation. An actual interruption of Rest cancels the remaining plan. A rest transition waits for an already-started conversation response when the existing departure rule requires it; an expired deadline returns feedback rather than starting a new rest.

In configurations with `simulation.lunch_place`, noon is a fixed daily lunch destination. Residents finish an operation or move already underway, then travel there; an arrival after noon still counts for that day and does not trigger another lunch trip. Lunch adds no meal tool, hunger state or charge. At 18:00, residents in Work or a long Rest choose what to do for the evening; residents already in Conversation can continue. Evening guidance expresses a wish to share work experience, talk about everyday life and build friendships. Residents still choose their own company, place and whether to meet anyone. This setting is used by the community `activities` and `realtime` examples; other schedulers remain unchanged.

Default costs are configurable under `simulation.activity_timing`:

| Operation | Simulated cost |
| --- | --- |
| Read code | 60 seconds per requested 100-line block, at most 400 lines |
| Apply patch | 120 seconds per 100 patch lines, at most 16 KB |
| Command or local test | 300 seconds, subject to provider timeouts and resource limits |
| Search, diff, board or work feedback | 60 seconds |
| Export or apply a handoff; submit; invite within an activity | 60 seconds each |
| Read conversation messages | 500 text units per minute, rounded up to seconds |
| Reply | 250 text units per minute, rounded up to seconds |
| Move | Manhattan distance on town coordinates × 60 seconds |

A text unit is one CJK character or one other letter/digit word; punctuation is not counted. Reading captures the unread messages at launch, and newer messages require another read. Reply text is known before its cost is charged. Work tools are available only at a work venue during 08:00–12:00 and 14:00–18:00. At those boundaries, residents choose what to do next; the 22:00 day boundary returns everyone home for the nightly sequence.

## Work and conversation

Work can pause and resume. A resident may enter Work before claiming a job. The board lists current job holders, and the team-job guidance suggests approaching residents without a job first. Claims, private repository snapshots and task notes persist across activities and days. Joining public work does not grant a shared writable checkout. Parallel work uses versioned patch handoffs that the recipient must apply; conflicts preserve the recipient's snapshot and return feedback. Relay work gives one participant at a time permission to write, with permission passing only after successful application or a decline.

Submission freezes the patch and starts official assessment in the background. The first check is due after 20 simulated minutes; unfinished assessment reports delay and is checked again every five minutes. Infrastructure errors are not failed repairs and do not earn rewards. Pending claims are protected from expiry while assessment is outstanding. Existing acceptance and settlement rules determine success and payment.

Private chats and public groups use one conversation activity with a message stream and separate join/read positions. Membership starts at the resident's recorded join time: a late joiner can read only messages at or after that position. Leaving records the end of membership, so later speech is not delivered to that resident; in a group, the remaining members can continue. Waiting resumes when a new reply arrives. Immediate invitations use the execution time as their start; appointments specify a clock time. A rejected invitation reports that it was not sent and why, including the requested and current times when the appointment has expired. Only an existing successfully created invitation has a usable identifier. Incoming invitations retain their Rest wakeup behavior, and replies can wake their resting sender, including a wait for that specific invitation. They do not interrupt other activities: automatic reply notifications are delivered when the activity ends, with explicit status checks still available. A confirmed appointment can remind its participants when it is time to leave for the venue, based on walking time; a reminder may wake Rest, but does not reserve anyone or send them automatically. Declining or replacing an invitation makes its old reminder moot. An appointment starts only when at least two confirmed members are present and available; the default grace period is five minutes.

## Persistence and records

Nightly checkpoints save paused activities, message positions, invitations, handoffs and frozen submissions alongside the existing agent, economy and repository state. Recovery returns to the last completed-day checkpoint; it does not snapshot a command midway. Pending grading can resume from the same frozen patch. Exact seconds are retained in event payloads, while the legacy event timestamp remains a minute projection for memory, economy and day indexing. Activity outcomes summarize witnessed feedback and progress without adding a reflection call.

The real-time driver keeps these activity, work and persistence rules while changing time accounting and speech delivery; see [Real-time scheduling](realtime-scheduling.md).
