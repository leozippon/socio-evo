# Per-resident task work notes

Goal: persistent task-scoped logs and progress, automatically loaded for current work and
selectively retrieved elsewhere. Keep completed experiments unchanged through an opt-in flag.

1. Project only a validated public task identifier into witnessed work percepts; never copy
   private assessment payloads. Preserve it in the resident's episodic record.
2. Store append-only observations and intentions under each agent's memory/work/task-N.
   Materialize current progress from those entries; intentions are never treated as results.
3. Record current work views and own chosen task actions, even if execution later fails.
   Consume subsequent percepts for actual outcomes, idempotently by event sequence.
4. Automatically prioritize current-task notes; retrieve topical notes in other scenes.
   Add owned work logs to active recall with provenance; reuse shared token packing.
5. Test privacy, task separation, duplicate observations, archive/reload, bounded context,
   topic selection, active recall, outcome-vs-intention, and whole-town compatibility.

No live deployment or experiment restart is part of this change.
