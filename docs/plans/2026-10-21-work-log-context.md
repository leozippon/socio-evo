# Work log context

Work receipts remain in each resident’s existing `memory/work/task-N/events.jsonl`. Operational event kinds, not keywords or job references in conversation, identify receipts. Ordinary conversation memory stays unchanged. Default context uses bounded resident-written summaries; only a current Work activity receives the latest operational feedback directly. Up to three explicit range reads per decision can retrieve the current assigned job’s original entries, including early output. Each range result replaces the preceding range and the default recent feedback window.

## Persistence and coverage

Physical append order is the stable entry identity, including journals written before this change. Coverage is an entry number and character offset, never a timestamp. Each summary records its actual time span and exact delivered range. A request snapshots the upper entry number before generation; newly appended records are left for the next boundary. Failed or cancelled requests do not advance coverage. Original receipts are never removed.

## Boundaries and budgets

The resident summarizes after deciding to leave Work or switch to Rest, before the exit decision can be accepted. No summary request runs while continuing Work. Real-time summaries remain in the interruptible decision task; each request has an isolated draft and shares the parent trace association. Mandatory transitions cancel an in-progress summary and preserve the unfinished range. Completed or forcibly paused work is caught up before nightly experience commit, independently of whether memory evolution or the diary is enabled.

Each request reads at most 6000 characters, reducing the segment for a smaller configured context budget; large individual entries continue at an exact character offset. The boundary processes bounded segments until its initial snapshot is covered. Summaries are at most 1600 characters each. At four accumulated summaries, the same boundary merges the oldest two adjacent covered ranges before processing further receipts. Active summaries are ordered by their covered range, rather than append time. A merge that exceeds the configured input budget folds bounded pieces locally and replaces the two source summaries only after every piece succeeds. Output bounds shrink under small configured budgets using the actual context counter. There is no intermediate Work summarization, summary tree, or second raw fact store.

## Context routes

Operational episodic entries are stored as references. Existing historical operational records are excluded from recall and nightly diary material when notes are enabled; active recall indexes summary text instead of original receipts. Current feedback is read once from the current job’s recent journal entries, replacing duplicate operational percepts and feedback embedded in the runtime situation. Explicit reads replace that recent window; active recall does not repeat summaries already selected through the work-note route. Other jobs receive only relevant summaries. Observation explicitly supplies the latest own-job identity and current Work membership; permissions never come from searching old memories.
