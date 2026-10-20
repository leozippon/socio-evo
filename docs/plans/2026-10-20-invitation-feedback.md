# Invitation and Rest feedback implementation plan

**Goal:** Make rejected invitations and expired Rest requests unambiguous, distinguish completed calls from successful invitations, and clarify the existing immediate invitation and Work entry choices.

**Architecture:** Reuse the existing Activity operations, invitation store and now entry. Return a small explicit outcome through the existing tool-completion path so realtime and the frontend do not turn a caught rejection into a successful-looking completion. Keep requested appointment/Rest times distinct from the execution clock, without adding inference-start timestamps or a new retry mechanism.

## Scope

Expired appointment feedback says the invitation was not sent, gives the requested appointment time and execution time, and asks for a new time. Expired Rest feedback likewise includes the requested ending time and current time, preserving today/tomorrow semantics and useful subminute precision. A rejected attempt creates no invitation or usable new identifier; a successful creation returns its real identifier. Existing invitations must not be misreported as newly created.

New tool results distinguish failure from completion. The frontend uses structured outcome data, including existing explicit errors; old records without an outcome remain neutral rather than presumed successful. A completed command or test is not thereby a passing test or accepted repair. Residents and the interface receive the same failure outcome and reason.

Immediate invitations continue using the existing null/now input and take their start from execution time. Only appointments supply a clock time. Add one short Work definition at its current prompt source: residents may enter Work before claiming a job. Do not add invitation modes, polling, automatic retries or repeated system reminders.

## Validation and delivery

Cover an appointment crossed during a real-time decision, expired today Rest and valid tomorrow Rest, immediate invitation execution time, no created invitation/id on rejection, genuine success lookup, and frontend failure versus unknown historical completion. Run focused tests, the combined Python selection and relevant existing frontend checks, then lint/format and independently review. Commit and push together with living documentation. On Zenith, validate the complete candidate on Linux before switching the future default; publish only changed frontend assets with backups and existing publication locking. Preserve the current frozen experiment, old results and all services; do not launch or restart an experiment for this task.
