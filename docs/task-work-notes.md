# Task work notes

Each resident can keep an independent journal for each job they encounter. This is an
opt-in cognition feature, separate from the general episodic stream, diaries, and skills.
Existing configurations retain their behavior. Automatic factual logging requires no model call. With `work_notes.editable: true`,
a resident may additionally write one bounded working summary before each external decision.

## Files and contents

Inside each resident's directory:

```
memory/work/task-1/events.jsonl
memory/work/task-1/state.json
memory/work/task-1/note.md
```

`events.jsonl` is an append-only journal. Each entry has an ID, simulation time, source,
text, and type. Witnessed task events (claims, commands, checks, submissions, rejections,
payments, and end-of-day desk reports) are observations. An action chosen by the resident
is an **intention**, not proof that it ran or succeeded. Work views retain the task
situation the resident was shown. Unwitnessed tests and private environment truth are
never copied into the journal.

`state.json` is a readable materialized view containing the latest observation, intention,
and work view. It is not an LLM-generated summary or a verified completion status.
Reads derive state from the journal, so an interrupted state-file write cannot change
what the agent remembers. Replayed event IDs are deduplicated. Reopening the same resident
files preserves notes; no automatic backfill from older experiment logs is performed.

Only tasks encountered by a resident get files, rather than creating empty files for the
entire task bank. Different residents' notes about the same job remain independent.
A proposal or public result can be recorded by its witnesses, but does not expose another
resident's private notebook. Symlinked notebook paths are rejected.

## Context injection

- **While working:** the task-specific action allowances identify the current job; its
  recent notes are automatically included with priority 95.
- **Other decisions:** an explicit job reference or overlap of at least two meaningful
  keywords selects related notes (priority 60). At most `related_notes` are selected.
  Unrelated conversation receives no work notes. This is lexical matching, not embeddings.
- **Diary and evolution:** journals touched that day contribute compact views to diary,
  reflection, skill, policy, and revision prompts (priority 75).
- **Active recall:** the existing bounded memory query can retrieve older journal entries,
  with timestamps and source references. It searches only that resident's persistent notes
  and excludes entries later than the current simulation time.

Automatic views include the latest `recent_entries` non-work-view entries, falling back
to the latest work view if none exist. Each text is clipped to `excerpt_chars`; full logs
remain on disk. Timestamp, source, and the intention/observation distinction accompany
injected excerpts. Task state in the current observation remains authoritative.

When shared context budgeting is enabled, these blocks share its input limit with other
memory and evidence. They do not get a separate unlimited budget, and may be shortened or
omitted if mandatory request content leaves insufficient space. Without shared budgeting,
entry counts and excerpt limits still apply, but there is no whole-request token guarantee.

The journal records externally visible work and the resident's chosen-action thought;
it does not invent a root cause, next-step plan, test success, or a skill improvement.
Generalizable lessons can still be produced by the existing nightly evolution process.

## Enable in a new run

```yaml
cognition:
  work_notes:
    enabled: true
    related_notes: 2
    recent_entries: 4
    excerpt_chars: 1600
  active_recall:
    enabled: true
  context_budget:
    enabled: true
```

`experiments/configs/context/swebench-work-notes.yaml` is a three-day pilot enabling all
three features. It retains the existing local inference endpoint and remote dataset path;
check deployment paths before running it. This implementation does not deploy or launch
that experiment automatically.

Validation covers task routing, hidden-payload exclusion, private files, symlink refusal,
idempotent replay, reopening, time filtering, context selection, active recall, nightly
injection, the disabled baseline, and a three-day simulation using mocked inference.

## Resident-managed summaries

`editable` defaults to false for old experiments and is enabled in the community profiles.
The internal `update work notes` action replaces `note.md` and appends a versioned `note`
entry to the journal. It does not advance simulated time or change the environment. A
resident can only update a notebook they have already encountered. Each decision permits
at most one update, alongside the separate bounded active-recall loop.

The summary can record the problem, evidence, edits, tests, uncertainties, and next steps.
It is explicitly attributed to the resident and is not treated as a verified observation.
The latest summary as of the decision time is injected together with separately labelled
factual excerpts under the shared token budget. Historical entries remain available for
active recall. `state.json` includes the latest summary but remains a derived view.

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
