# Task work notes

Each resident has private, append-only operational journals per job when
`cognition.work_notes.enabled` is true. Actual conversation remains ordinary memory,
including conversations about work.

## Raw records and overviews

`memory/work/task-N/events.jsonl` preserves the original operations, feedback and
resident-authored interpretations. `state.json` is a derived view. Intentions are not
executed actions, and a summary is not proof of success. Other residents' private
records and hidden test results are never added. Old `note.md` files remain readable.

On a voluntary Work exit, a visit that contains actual job research or operations schedules a separate Reflect Activity. Work ends first; one bounded overview per relevant job is saved before continuing the already chosen next action. A visit with no operational receipts needs no summary. Each return to a Work Activity has a new participation identity. Stored overviews carry the source visit, entry range and time span, so later participation and late feedback cannot silently change a completed scope. The prompt and JSON schema limit a work overview to 1600 characters or less under a smaller context budget.

A long work session still uses one overview request per job, not a model call for every
6000 characters. The fixed input snapshot contains the full range when it fits; otherwise
it contains an operation index and explicitly shortened excerpts. The saved input mode
makes clear that an overview does not establish full-text reading. Original records are
retained. New appends cannot be silently included in an older snapshot.

Mandatory transitions cancel pending note generation without marking it complete.
Unfinished ranges are handled at night; historical overview consolidation is also a
separate nightly step. Neither historical merges nor a backlog from a previous activity
runs in the voluntary exit path. Retries retain the existing finite bound.

## Context and explicit reading

Current Work receives its job overview plus recent operations and feedback directly.
Fresh test failures and code-search results never wait for a summary before becoming
readable. Older raw detail is available through `read work record`, up to three reads
per decision, each bounded to 6000 characters with an entry/character continuation.
This page size does not determine the number of summary calls.

Task-bound conversations receive the job overview; unrelated activities do not receive
raw work logs. Active recall and nightly reflection use summaries by default. Real speech
is not replaced by job summaries. Shared context budgeting applies to all injected notes.

## Validation

Core checks cover activity/job isolation, persisted scope completion, cancellation,
late receipts and failure recovery. Realtime checks exercise delayed summary generation
at a 15x clock, summary persistence before the deferred next action, repeated Work visits, other residents' progress and forced transitions.
A separate real-model probe validates the resident's bounded overview and job-specific
storage without mutating an active experiment.

## Peer review: own receipts versus witnessed work

Evening Review now pins an attributed work ledger in its mandatory situation text, independently
of lexical/recency retrieval and optional memory token allocation. It contains today's own task,
submission/acceptance/rejection/delay notices, own payment receipts, and a separate section for
other residents' jobs personally witnessed. Every record carries a timestamp, event source,
task id and actor. A pending submission is not an accepted repair; another resident's payment
or an observed delivery is not the reviewer's income or work.

The source is the event log filtered by the reviewer's audience permission and review time.
Only witness-facing text is rendered; hidden work_assessed truth, private code/test patches,
others' private payment records and future events are excluded. Public assignment membership
handles jointly assigned jobs and prior-day claims; expiration/reassignment avoids crediting
another worker's later repair to the former assignee. Reading this ledger does not consume
pending percepts or change ratings, rewards, journals or archived experiment data.

Task note headings also explain that 'your notes' means a private record held by you, which
may describe someone else's work. Observed entries identify the actor explicitly; authored
intentions and interpretations remain labeled separately from confirmed results.

Validation: 263 regression tests passed across scheduling, SWE-bench, interaction schemas,
active/context retrieval, work notes and replay. Dedicated checks cover receipts in the actual
Agent review request with context budgeting both enabled and disabled, joint/carryover work,
reassignment, unavailable/failed assessment, private/hidden/future data and perception cursors.
