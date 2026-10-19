# Project log — 2026-10-20

## Activity prompts and documentation

Starting from `f5f41af`, the activity prompt design was simplified around a stable system context and a concise current Activity prompt. Detailed instructions remain available through environment-generated help. The shared Activity contract now has one documentation home, while the real-time document covers clock and speech behavior specific to that mode. The project summary introduces both opt-in modes and labels the retained scene-based account with its scheduler. Existing scene configurations remain supported.

The primary regression command was `python -m pytest -q tests/core/agent/test_prompts.py tests/core/interaction tests/runtime/activities tests/runtime/realtime tests/tasks/swebench`; it passed 362 tests locally in 16.72 seconds. On Zenith Linux, the focused checks produced these results:

- The primary prompt, interaction, activity, realtime and SWE-bench selection passed 362 tests in 16.21 seconds.
- Sandbox `NONE` grading and related path/management/evaluation selections passed 15 tests; 66 were deselected.
- Direct execution, HTTP management and isolated held-out evaluation checks passed 7 tests.
- The night-desk and scene-review selection passed 6 tests after a test-only correction. The original night-desk assertion failed on the `f5f41af` baseline; the correction retains ledger and personal/witnessed receipt ownership assertions. The same six checks passed locally and on Linux.
- Of 12 metadata selectors, 1 passed and 11 failed because this host does not permit user namespaces, so bubblewrap cannot create its sandbox.

The four focused groups contain 390 distinct passing tests; adding the single passing metadata selector gives 391 distinct passes. The 11 metadata failures are separate and platform-blocked. Of the 391 passes, 385 use the exact `20332d7` test sources and six use the supplied test-only correction; production code remained unchanged in that correction. These results do not amount to a full-suite pass. Ruff on the modified Python code and `git diff --check` passed.

An offline comparison using the same six fixtures measured a 33.0%–35.7% reduction in Unicode characters across system plus decision-user prompts for selection, work and conversation in both fixed-cost and real-time modes. Repeated non-empty lines fell to zero in every comparison. Recall was empty and work had not been claimed in these fixtures, so these measurements do not establish effects on resident behavior or character.

The earlier macOS full-suite attempt collected 978 tests and ended with 771 passed, 80 failed, 5 skipped and 35 errors before a stalled sandbox-dependent portion was interrupted. This is not a full-suite pass. Of the 115 failure/error records, 95 report missing Linux `bubblewrap`, eight report macOS resource-limit errors, five report denied HTTP binds, and one combines resource and process-permission errors. Three viewer records wrap study subprocess failures without their stderr, one sandbox startup times out, and one study fixture assertion follows a missing-sandbox failure. The night-desk assertion was reproduced on the unchanged `f5f41af` baseline and then corrected by changing only its test; the six related local and Linux checks pass. No regression attributable to the implementation was identified.

The provider's public guide is now included on demand for Activity work, while the legacy inline guide remains in its old mode. Preflight checks and their failure gate remain active. The deprecated `warning_seconds` configuration field is still read for frozen configurations, but the prompt no longer promises a final-five-minute warning. Linux validation used an existing host. It started no model or GPU workload, changed no production source or services, and did not run official Docker grading.
