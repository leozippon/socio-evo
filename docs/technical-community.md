# Technical community

The opt-in profiles in `experiments/configs/community/` implement the approved small
technical community. Existing experiments retain append-style posting and their original
acceptance rules. No existing run is migrated automatically.

## Residents and schedule

Both profiles use Mei, Tomas, Aisha, Jonas, Lucia, Ravi, Olga, and Kofi, with the original
profiles and balances (120, 180, 30, 60, 250, 70, 80, 50). Living costs are 20 per day;
Jonas additionally pays 8 and Ravi 10. Family members are background, not running agents.
Lite runs three simulated days for debugging; Verified runs 42 days.

The five homes retain their resident assignments. Workshop and library open 08:00–12:00
and 14:00–18:00. Café Linde opens 08:00–22:00; Anchor opens 18:00–22:00. Existing nightly
reflection and self-modification remain. A separate daytime home-learning action is not
implemented by this change.

The community profiles now use the opt-in [independent action clock](independent-scheduling.md).
Initial task stock is posted at 07:00; successful acceptance immediately replaces a job. Each resident then chooses a new action
when their own previous action finishes; the old scene scheduler remains available.

## Closing and conversation responses

In the activity and realtime schedulers, a venue closing at noon or 18:00 ends indoor
activities after already-started realtime operations finish. Residents remain outside
that venue and choose their own next activity, including waiting for reopening or
moving to an open social venue. There is no automatic homeward trip before day end.
At 22:00 everyone still returns home. Paused tasks and repository progress survive.

At a decision opportunity, residents are prompted to accept, decline or defer pending
conversation invitations. Accepting twice emits no duplicate notification. Declining
preserves the invitation history and does not cancel other group members' participation.
`defer invitation` proposes a later open time today: the original is superseded and all
other participating residents must confirm the new proposal. Old confirmations never
silently carry over. Started conversations cannot be rescheduled through this tool.
Invitations and replies do not interrupt running work or reserve a busy resident.

## Free preparation hour

07:00–08:00 is optional preparation time using the same four activities. A resident
may select Work at home to inspect public notices, claim a job, review prior work
feedback/notes or arrange partners; no new planning call or compulsory activity is
introduced. Invitations and appointments can be arranged remotely. In-person
conversation still requires co-presence and an open location (for example shared
homes); public venue opening hours and home access rules do not change.

Repository reads/edits, commands, tests, handoffs and submissions remain locked
before 08:00 and require an open workplace afterwards. Residents decide when to
travel; current travel/departure estimates are shown during preparation. Early
arrivals wait outside until the doors open. At 08:00 a held job can be continued in
Work without resetting progress; there is no automatic commute or forced work.
Residents who do not need preparation may keep resting. In realtime mode activity
selection itself uses wall time, so departure estimates also remind residents to
allow for decision latency.

## Work lifecycle

- Initially six solo issues and one joint issue are posted. With `posting_mode: replenish`
  and `replacement_timing: immediate`, successful final acceptance archives the completed
  job through its retained delivery/evaluation records and immediately posts one new job
  with the same worker count (and trade/job sheet). New jobs use the existing public
  competition and team-confirmation rules; the previous submitter has no priority.
  Open and claimed jobs count toward stock, so the next morning does not add duplicates.
  Old configs default to `replacement_timing: morning`; append mode is unchanged.
- Community profiles keep unclaimed notices indefinitely. If a shelf life is configured,
  a retired unclaimed notice immediately receives a same-worker-count replacement.
  Expired claims return the same issue to the board unpaid, without adding another job.
  A claim initially allows two days, including the claiming day; solo and joint limits
  are independently configurable.
- One claim per person. Existing random claim conflict resolution remains. Joint jobs
  require an invitation and confirmation and have two workers but **one SWE-bench issue**.
- Partners share one checkout. Sequential terminal commands preserve attribution. They
  choose their own division of labour, relay, or review. Either may submit one integrated
  patch (`WORKTREE` collects it). This does not require two separate deliveries.
- Local tests run through the terminal. Final acceptance uses the official SWE-bench
  evaluator in a separate checkout. Only a passed result pays. Failed attempts can be
  revised before the deadline without posting another job; an incomplete declaration
  never bypasses checks. While background acceptance is pending, the job still occupies
  its workers' one-job slots. Prompts explicitly allow leaving Work to socialize or rest,
  explain the expected feedback time (and possible delay), and prohibit resubmission.
  Successful acceptance releases the slots; residents can then compete for new jobs.
- A solo issue pays 60. With the configured 1.5 joint premium a joint issue pays 90 total,
  split equally (45 each). Statements in submitted reports are retained as written even
  when the resident's declaration differs from the verified result.
- Evaluator infrastructure failures emit a retryable `work_delayed` event, not zero skill
  or a failed repair. The deadline receives at most one extra day per affected simulated
  day. Diagnostic details stay in `repositories/assessment_errors.jsonl`.
- Issues are selected without replacement from the bank, with issued references persisted
  in the environment checkpoint. If the finite bank is exhausted, replenishment stops;
  issues are not silently recycled. Immediate replacement emits
  `task_replacement_unavailable` when no unused issue remains. Customers and the clerk
  remain rules, not LLM agents.

## Memory and context

The community enables automatic lexical retrieval, active recall, the shared dynamic token
budget, and per-resident/per-task notebooks. Identity, backdrop, principles and the skill
index belong to the system message; selected skill bodies, insights, history, current
situation and allowed actions belong to the user message. There are no embedding searches
or separate memory-selector model calls. Important task evidence is prioritized within the
same budget, and ordinary retrieval retains its configured count and excerpt limits.

Each resident can update a working summary once before an external action. The summary is
separate from observed events and is explicitly labelled as the resident's interpretation.
Other contexts retrieve it only when relevant. See [task notes](task-work-notes.md) and
[context budgeting](active-recall-context-budget.md).

Subjective social beliefs remain private text. Existing public standing and post-hoc
relationship analytics are retained; these are not a new private relationship-score store.

## Preparation and launch

New profiles require [offline evaluation readiness](offline-swebench-evaluation.md).
The Verified metadata snapshot is bundled; prepare official Docker images before
launch. Infrastructure faults in activity/realtime acceptance retry the original
submitted snapshot in the background, without asking residents to submit again.

Official evaluation needs a Linux host with working Docker and the project's SWE-bench
optional dependencies. The model endpoint and dataset paths in these profiles must exist
on that host. These commands do not deploy a model or configure Docker:

```bash
python -m pip install -e '.[swebench]'
python -m tasks.swebench.fetch --variant lite --out /personal_fast_storage/datasets/swebench-lite
python -m tasks.swebench.fetch --variant verified --out /personal_fast_storage/datasets/swebench-verified
python -m experiments.run experiments/configs/community/lite.yaml --seeds 0
# After validating the Lite workflow:
python -m experiments.run experiments/configs/community/verified.yaml --seeds 0
```

The fetch command resolves a dataset revision and writes `test.json` and `manifest.json`
(dataset, revision, SHA-256, instance list). It refuses to overwrite an existing directory.
Gold patches and hidden test patches remain evaluator-side and are excluded from public
issue descriptions. For a controlled task subset, set `tasks.instances`; the initial pool
must contain at least seven distinct issues.

Community runs support `--resume`: completed-day checkpoints include repository patches
and command logs, and recovery rolls back partial-day workspace changes along with the
simulation. A dataset or instance-pool identity mismatch is rejected before restoring
workspaces. Repository snapshots cover versioned changes and added files collected by
`git diff`; shell processes, installed packages, ignored files and container state are not
checkpointed. Legacy SWE-bench pilot runs retain their no-resume restriction.

## Validation scope

Behavioral tests cover inventory, expiry/relisting, invitation confirmation, shared
workspace identity and command attribution, one-patch settlement, retryable grading
outages, checkpoint rollback and dataset identity, private note updates, and configuration.
Docker calls in the new provider tests are mocked. A real Lite run and official grading
on the deployment host remain necessary before interpreting experiment outcomes.

Local verification on 2026-10-18: 295 focused tests passed (one Linux-only test excluded),
Python lint, JavaScript syntax and diff whitespace checks passed. Broader compatibility
runs also encountered existing host requirements: missing bubblewrap on macOS and an
unsupported resource-limit setup in the direct execution harness. These checks do not
establish that the Docker evaluator or model service is available on the deployment host.
