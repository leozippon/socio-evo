# Shared acceptance feedback

Goal: Every collaborator receives the client's verdict, and later decisions retain the latest known result after event cursors advance. Do not deploy or change the current frozen experiment.

## Implementation

- Failed WORK_SUBMITTED notices go to the claim's complete worker roster, including partners at other places. Success retains the existing coworker/public audience. WORK_ASSESSED stays research-only.
- Store one bounded, typed latest AcceptanceNotice per resident in Environment state. It contains task/part, submitter, verdict time/event, accepted flag and client-facing feedback, never hidden quality or private terminal/test output.
- Pin the latest completed verdict in status_view, including compact/no-evidence views. Label it as a completed attempt with provenance; newer pending submissions have an explicit separate current status. Completion releases the claim but preserves the receipt.
- Add default-empty checkpoint state for compatibility and round-trip persistence. Existing logs/results are not rewritten.

## Verification

Cover both submitters and remote partners, refusal then successful rework, private-check isolation, compact context after perception consumption, checkpoint restore, successful archived claims, newer pending submissions, background outages and activity/realtime entrypoints. Run related regressions, lint/format checks, then commit locally. Keep the heartbeat monitoring the unchanged a17ae6c experiment.

## Verification result

Eight new regression cases passed, including both activity schedulers. The combined
related regression selection passed **435 tests**, with two previously documented
baseline exclusions: macOS cannot run the Linux sandbox trade test, and the legacy
night-desk suffix assertion predates mandatory review context. The 65-test core
Environment regression file also passed without exclusions. Ruff lint/format and
diff checks passed. Resident-facing receipts use job names and the clerk's record;
internal event provenance stays in serialized state. No current run is migrated.
