# Invitation and Rest feedback implementation plan

**Goal:** Make rejected invitations and expired Rest requests unambiguous, distinguish completed calls from successful invitations, and clarify the existing immediate invitation and Work entry choices.

**Architecture:** Reuse the existing Activity operations, invitation store and now entry. Return a small explicit outcome through the existing tool-completion path so realtime and the frontend do not turn a caught rejection into a successful-looking completion. Keep requested appointment/Rest times distinct from the execution clock, without adding inference-start timestamps or a new retry mechanism.

## Scope

Expired appointment feedback says the invitation was not sent, gives the requested appointment time and execution time, and asks for a new time. Expired Rest feedback likewise includes the requested ending time and current time, preserving today/tomorrow semantics and useful subminute precision. A rejected attempt creates no invitation or usable new identifier; a successful creation returns its real identifier. Existing invitations must not be misreported as newly created.

New tool results distinguish failure from completion. The frontend uses structured outcome data, including existing explicit errors; old records without an outcome remain neutral rather than presumed successful. A completed command or test is not thereby a passing test or accepted repair. Residents and the interface receive the same failure outcome and reason.

Immediate invitations continue using the existing null/now input and take their start from execution time. Only appointments supply a clock time. Add one short Work definition at its current prompt source: residents may enter Work before claiming a job. Do not add invitation modes, polling, automatic retries or repeated system reminders.

## Validation and delivery

Cover an appointment crossed during a real-time decision, expired today Rest and valid tomorrow Rest, immediate invitation execution time, no created invitation/id on rejection, genuine success lookup, and frontend failure versus unknown historical completion. Run focused tests, the combined Python selection and relevant existing frontend checks, then lint/format and independently review. Commit and push together with living documentation. On Zenith, validate the complete candidate on Linux before switching the future default; publish only changed frontend assets with backups and existing publication locking. Preserve the current frozen experiment, old results and all services; do not launch or restart an experiment for this task.

## Supplement: partner availability and invitation replies

The board also shows current job holders from the same claim source used to decide whether a resident is already occupied. A single brief suggestion for team jobs prefers residents without a claim; it does not prohibit other choices or reveal private work.

Invitation responses wake a resting sender according to the existing wake settings, including a Rest waiting for that particular invitation. Match rescheduling through the original invitation/supersedes relationship and ignore unrelated replies for a targeted wait. Incoming invitations retain their existing Rest wakeup behavior.

For a sender in another Activity, preserve the original response in the event log but defer automatic delivery until the Activity ends. A small persisted queue is sufficient; omit the affected invitation from automatic views while its response is held, while an explicit help/status query can still read the actual state. Deliver the private notification at the current clock after any direct Rest transition, keep its source-event reference, and do not replay accept/decline side effects or introduce older timestamps into memory. Test a busy next-tool observation, end-of-Activity delivery, a direct transition into Rest, relevant versus unrelated replies and checkpoint restoration. No new notification framework or experiment restart is required.
