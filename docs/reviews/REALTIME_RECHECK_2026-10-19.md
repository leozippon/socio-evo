# Realtime recheck: fixes and follow-up findings

Evidence: `community-realtime-recheck-20261019-1711 / seed-0000`, frozen revision
`df12d6f`, 2026-10-19. Existing experimental results are unchanged.

## Implemented: persistent work instructions

Previously the repository operating notes were attached to a task specification at posting.
Activity observations use `status_view(include_evidence=False)`; reading the instructions
once did not ensure they remained available on later work decisions. The resident still
had terminal evidence, but could repeatedly invent test labels.

SWE-bench providers now expose a public `work_guide(part)`. Assigned work activities include
it in their mandatory situation text and offer **read repository work guide**, so the agent
can deliberately retrieve it again without running a shell. It is provider-specific and
uses no gold patch, hidden test patch or official grading labels.

The guide describes `/testbed`, the activated Python environment, shell/persistence/network
limits, pipefail, test discovery, interpreting failures, independent workspaces, handoffs
and actual WORKTREE submission. Django's runner uses labels relative to `tests/`:
`tests/backends/base/test_operations.py` maps to `backends.base.test_operations`;
`tests/admin_checks/tests.py` maps to `admin_checks`. Verify that files exist before using
examples. Source modules under `django/` are not test labels. Other repositories use the
installed pytest launcher and discovered paths under `tests/`, `testing/`, or contributor
instructions. A guide is not proof that tests ran; only actual output and official acceptance
establish those results. Disabled preflight is not described as successful preflight.

## Implemented: overnight rest and selection feedback

At 18:08 Jonas requested rest until 06:00; Tomas similarly chose 08:00. The engine interpreted
both as the same morning and rejected their end times. Final counts were 162 repeated failures
for Jonas, 138 for Tomas, plus one for Lucia. These are distinct from the old public-work reuse bug.

Rest clock times now mean the next occurrence: a time earlier than now rolls to the following
day. The current day's activity ends no later than its day boundary; normal night handling
continues after that. A request ending exactly now gets an explicit correction rather than an
ambiguous generic error. Future same-day rest preserves its requested end.

Environment feedback while no activity exists is retained independently of an Activity,
checkpointed, and included in the next activity-choice context. Successful activity entry clears
that feedback. The legacy selection rejection path also retains its reason. This fixes the
missing feedback path without imposing a forced activity choice. It does not implement a
new general repeated-failure detector.

## Investigated, not changed: conversation submission loop

Kofi made one real morning submission; its assessment returned retryable unavailability
at 11:42 (seq 1267). The persisted assessment_errors.jsonl records the local
official evaluator subprocess exiting with code 1; the generic service-unavailable
message is not proof of an external server outage. Retrying the same patch reuses the
evaluation folder, so the original evaluator.log was overwritten; a deeper cause is
not established by the retained log. Subsequent repeated statements were **speech**, not submissions.
At 11:54/11:56/11:59 raw calls attempted `do: submit` while in ConversationActivity.
The schema correctly disallowed submit there; repaired output became `do: reply`, saying
'Submitting the WORKTREE ... now' without executing it. Ravi repeatedly asked for submission.
After lunch Kofi entered work, actually resubmitted at 14:06 (seq 1460), and passed at
14:26 (seq 1585). The first infrastructure failure is separate from the later activity loop.

Proposed follow-up: explicitly expose current activity/tool boundaries and the leave→resume
work→submit route; retain a resident-chosen next intention across activity exit. Schema
correction must explain that an unsupported work action cannot be replaced by a statement
claiming it happened. Only a submission receipt changes submitted status. A conversation
must not silently execute work on behalf of its speaker. The new public guide already explains
this route when read in work; conversation-specific controls/correction remain future work.

## Investigated, not changed: repeated invitations and empty work reentry

Olga invited Aisha at 14:17:48. Aisha accepted the same pending invitation multiple times,
then accepted a second invite. Olga repeatedly resumed and left empty work-98. Conversation
finally started at 14:40:17 and delivered speech to both participants.

Code paths explain why this is possible:

- `invitation_ids` includes invited residents who already confirmed; accept is effectively
  idempotent but still emits another discussion record. The situation serializes invitations
  with `confirmed` excluded, so 'pending' hides whether the resident already accepted.
- Starting requires two confirmed, colocated, available residents. Realtime availability
  excludes residents with in-flight model/tool calls, correctly avoiding forced interruption.
  One resident thinking/working while the other becomes free can keep the invitation pending.
- The next choice can immediately resume an empty work activity instead of explicitly waiting
  ready for the confirmed conversation. Olga's raw 14:27 thought says she wants to talk but
  selects resume-work-98 in the hope it connects her to the conversation.
- Immediate invitations remain eligible until day end, unlike scheduled meetings' grace limit.
  Therefore duplicate immediate invitations can remain visible and cause repeated attempts.

Proposed follow-up: separate needs-response / confirmed-waiting / started / expired views;
remove accept from already-confirmed recipients' menus; display each participant's readiness
and the blocking reason; offer an explicit resident-chosen wait-for-this-conversation activity
that yields at a tool boundary. Do not automatically interrupt work or auto-join merely because
an invitation was accepted. Deduplicate equivalent pending invites. These changes need regressions
for staggered model completions, working owners, rest wake permissions and duplicate accepts.

## Investigated, not changed: Ravi misread the current time

Ravi's request at metadata time 960 explicitly says 16:00:12 and gives 14:00–18:00 workplace
hours. Response seq 1989, completed at 16:02:09, nevertheless says 'past the afternoon coding
block anyway (18:00 close)' and rests until 22:00. No missing clock or actual early closure
is supported by the evidence. The empty board independently made rest legitimate. Exact
model-internal causation cannot be established from this single response; historical closing
text may distract, but that remains a hypothesis.

Proposed follow-up: provide current date/time plus derived current open/closed and remaining
work interval as authoritative facts at the decision point; distinguish request-start from
completion time and historical records from current state. Keep actual environment validation;
do not infer that a model's clock assertion changes opening rules.

## Investigated, not changed: inaccurate nightly self-recollections

The cited errors were peer-rating thoughts, not the final diaries:

- Aisha seq 2935: 'I didn't work', despite Job 1 accepted and $60 paid.
- Olga seq 2937: 'finished two jobs, made $120', despite one Job 2 and $60 reward.

Both agents' persisted episodic streams contain their own accepted work and payment events.
The original peer-rating prompt for Aisha, however, includes only `work-note:task-2`
(her observations of Olga), omitting her own Job 1 and payment. Olga's includes Job 2 and
observed Job 1 and explicitly includes her own $60 payment, yet her answer still overclaims.
No dropped blocks were recorded; this was not token-budget exhaustion. Aisha's and Olga's
final diaries later correctly describe their own Job 1/Job 2 and respective $60 payments.

WorkNotes stores each resident's witnessed task events, including observations of others'
public jobs, in that resident's private note files. This is **not access to another agent's
private notes**. But every file is rendered as 'Your work notes for job N' and selected by
lexical relevance. At review there is no current task allowance, so recency/social relevance
can favor the other resident's job. `related_notes` limits selection to two; no authoritative
own daily ledger summary is mandatory. Current-task discovery also recognizes allowance
`task_id` but Activity allowance menus do not expose it that way.

Proposed follow-up: give each resident a compact verified summary of their own claims,
submissions, acceptance and receipts from events they were entitled to receive; distinguish
'you worked on' from 'you witnessed'; show actor/worker and source for note entries. Pin
own ledger facts for review/diary rather than relying on lexical overlap. Keep observations
of others usable but clearly attributed. Preserve and flag unsupported claims for research;
do not silently rewrite the raw thoughts or infer intentional deception.

## Validation

Local regression run: 115 passed across activity/realtime scheduling, SWE-bench provider,
preflight, and frontend replay checks. Static Ruff checks passed. Added tests cover next-day
rest/day-end clamping, same-day waits, equal-time correction, persisted no-activity feedback,
legacy rejection feedback, realtime rest availability, persistent/readable guide tool and
public-only provider instructions. No new experiment was launched and the frozen completed
experiment was not modified.
