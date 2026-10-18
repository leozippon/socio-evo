# Independent action scheduling

## Entry points and compatibility

`simulation.scheduling` accepts `scenes` (the unchanged default) or `independent`.
The community Lite and Verified profiles now select `independent`. Old YAML files,
`PlanDay` itineraries, work-round scenes and conversation scenes continue to use `scenes`.
Independent mode currently requires the community repository provider; configured scripted
meetings remain supported by the legacy scheduler. Existing finished runs are not rewritten.

## Day and action clock

At 07:00 the environment starts the day and replenishes completed jobs **before** residents
choose their short goals. Goal planning takes five minutes. Each later action can include
an optional replacement goal without an extra time charge. The current goal is shown in
every daytime decision and persisted in the completed-day checkpoint.

- Work windows: 08:00–12:00 and 14:00–18:00, in an open work place.
- Early morning and lunch: read the board, claim work, move, exchange remarks or invitations;
  no terminal work. The cafe remains open during lunch.
- Simple actions: five minutes. Terminal work: twenty minutes, one bounded command.
- A work action must fit completely: 11:40 can start, 11:45 cannot. Results finishing at
  12:00 or 18:00 are applied before closing. Returning home on midday/workplace closure
  takes five minutes. At 22:00 everyone returns home for the existing review, economy,
  standing update, diary and evolution sequence.
- Each resident has an independent pending action. The driver advances to the earliest
  completion, opening/closing, feedback or intervention. Busy residents receive accumulated
  news only when they next decide. Idle waiting currently uses five-minute steps.
- Results and repository edits are produced at the action's completion, never exposed in
  advance. Equal-time decisions/completions use the seeded draw; real model latency does
  not decide who gets a contested task. Shared-repository commands run sequentially at
  their respective completion points; equal-time ordering is seeded.

The simulation clock is independent of wall time. Model requests at the same simulated
moment can run concurrently, but the driver waits for those replies to preserve reproducible
state transitions. Slow services can still slow real elapsed experiment time.

## Voluntary discussion

Residents can invite a named person, provide a topic and suggest 5–60 minutes, face to face
or by message. Accepting does not reserve either person. Either can request the start;
arrivals/departures at that time complete first, then both people must be free in the same
open place. A stale request is rejected and can be tried again. Remote contact does not
create remote discussion or teleport participants.

Active discussions are visible to nearby residents, who may join at a free turn boundary.
Only members are reserved. Every five-minute turn has one rotating speaker; other members
can listen, leave or answer a time-extension proposal. Public speech is also heard by nearby
nonmembers, including busy workers, without making them participants or interrupting them.
Private speech is heard only by its addressee.

A discussion ends at its agreed limit, when fewer than two members remain, or at the place's
closing time. Extending it requires every current member's consent and cannot exceed closing.
Pending invitations expire at day end. Private goals are displayed only in the resident's
view or the viewer's truth mode.

## Submission and official grading

Submitting takes five minutes and transfers the already saved `WORKTREE` patch. Editing via
a full diff in a submission is rejected in independent mode: edits belong in work actions.
The frozen patch is graded in a separate task. While waiting the resident can move, talk,
and plan; the claimed job remains occupied and cannot be submitted a second time in parallel.

Feedback is applied after `simulation.grading_minutes` (default 20 simulated minutes),
capped at 22:00 so settlement precedes nightly accounting. Wall-clock grading speed never
chooses the simulated feedback time. If grading is still running then, real execution waits
at that event. Official success pays; rejection allows another attempt. Infrastructure
failures use the existing retryable event and deadline compensation, not a quality failure.

## Work execution budget

The community config gives a command 60 real seconds. Containers retain the existing two-CPU,
6 GiB, 256-process and no-network limits. Output is limited to 16,000 characters, and the
persisted diff to 2 MB. Oversized diffs are rejected and the previous patch retained.

After each community work command the provider saves the patch and force-removes the
container, terminating detached descendants as well as foreground work. The next command
restores the patch into a fresh official image. Installed packages, ignored build artifacts,
shell variables and background services do not persist; repository edits and command logs
do. Submission reads the saved patch and does not create another idle container. These
limits bound execution, not an exact equal amount of intellectual effort per command.

## Events, replay and recovery

`action_started` and `action_completed` carry start/end times and the action; `goal_updated`
carries the private goal. `discussion` records invitations, membership and agreed end times;
`submission_pending` records the promised feedback time. Existing outcome events remain the
source of payments, acceptance and social observations. Analysis can inspect the `operation`
field of `activity` actions to separate movement, invitations and discussion controls.

Replay shows activity intervals and goals in the People panel. Old logs need neither field.
Recovery is from the latest **completed day**, not a live process checkpoint. Environment,
agent memory, goals and repository patches roll back together; an interrupted day's actions
are replayed. Invitations and discussions finish or expire by 22:00, and no ongoing process
or pending assessment is serialized into a day checkpoint.

## Verification

Tests use real Agent/card/context and Simulation protocols with scripted replies, plus fake
repository tools. They cover independent completion, delayed evidence, same-time claim draws,
noon boundaries, nonblocking invitations, start-time rechecks, shared time, consent, exit,
deferred grading, whole-day execution, failed-day recovery and analysis of the completed run.
Provider tests check shared patches and forced cleanup/rollback; a Node replay check covers
new events and legacy state. Real Docker cleanup and official grading remain deployment-host
smoke checks, not claims established by mock tests.

Local verification on 2026-10-18: 326 tests passed across agent memory/context, interaction
cards, environment work rules, SWE-bench provider, community profiles and both scheduling
paths. Nine legacy tests requiring the unavailable Linux isolation environment were excluded.
Python lint, JavaScript syntax, activity replay and diff whitespace checks passed.
No live model experiment or deployment was performed.
