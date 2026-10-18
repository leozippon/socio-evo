# Community review fixes and live smoke plan

Approved scope: repair four review findings, add regression coverage, commit locally,
then attempt an eight-resident, three-day experiment on the existing Zenith machine.

- Preserve current finances and the claimed issue specification in required decision
  context. Separate current desk evidence from required state; pack it before history
  under the shared token budget. Keep the existing scene status API behavior by default.
- Derive replay deliverable counts from task definitions, not the number of workers.
  Retain old single-part and two-part log compatibility.
- Apply retryable assessment deadline events to replay claims.
- Verify with agent prompt/budget, scheduler observation, and frontend event tests;
  run related compatibility tests, then commit without pushing.
- Restore the existing model service, synchronize committed source, preflight Docker,
  dataset and actual inference, and start a uniquely named three-day run. Preserve
  previous outputs and record actual launch status separately from completed results.

Validation: 328 portable Python tests passed (9 Linux sandbox-dependent cases
excluded), plus Node activity/shared-issue/deadline replay checks. A broader macOS
run passed 367 tests but could not run 8 tests and 22 dependent fixtures because
bubblewrap is unavailable; this is not a claim that the full suite passed.
