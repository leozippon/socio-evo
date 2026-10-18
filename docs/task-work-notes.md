# Task work notes

Each resident can keep an independent journal for each job they encounter. This is an
opt-in cognition feature, separate from the general episodic stream, diaries, and skills.
Existing configurations retain their behavior. No model call is required to maintain it.

## Files and contents

Inside each resident's directory:

```
memory/work/task-1/events.jsonl
memory/work/task-1/state.json
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
