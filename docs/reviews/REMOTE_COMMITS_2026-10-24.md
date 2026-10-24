# Review of unmerged remote commits (main e841d09 .. origin/main f485730)

Date: 2026-10-24. Scope: the 121 commits on `origin/main` not in local `main` (merge base e841d09, 2026-10-18 to 2026-10-22, 118 by one author, 3 by Codex). Net diff: 238 files, +31,445 / -350. This is a brief, read-only review; the test suite was not run. Claims about runs come from the remote logbooks and were not independently reproduced.

## 1. Theme grouping

| Theme | ~Commits | Representative commits | Most-touched files |
| --- | --- | --- | --- |
| Deployment and run receipts (docs-only, mostly "Record ...") | 42 | 921e535, 98f4119, 1405cce, 4173aed, b072025, ece98b5, b9c369f | `docs/logbook/PROJECT_LOG_2026-10-2{0,1,2}.md` |
| Activity and realtime schedulers (independent clock, Activities, realtime wall clock, Rest, lunch, early arrival, workplace hours, task replenishment) | 22 | c2bfc51, 1d8fac6, 8dd00e5, 0ce0907, 292f405, f5f41af, dfd9d6c, 032b9c8, 878258e, f2d61e3, 97c4d26, 68f8afa | `runtime/activities/engine.py` (+3132, 31 commits), `runtime/realtime/engine.py` (+1137, 26), `runtime/scheduler/activity.py` (+762) |
| Conversation, invitations, streamed interruption and continuation drafts, output retries | 16 | 0c31f1d, 8048075, 8300d1c, 308551c, 661e741, 3a32cdb, 6fd353f, fc1f9e3, 3e6f124, d34b514, 373c5c3, 1bbb292, cffce9c, 6b13182, a094d52, edb1f92 | `core/agent/agent.py` (19 commits), `core/interaction/activity_card.py` (18), `core/agent/continuation.py`, `core/agent/context.py` |
| Work context, work summaries, Reflect activity, personal skills, evolution cadence, paired tasks | 17 | d7ddf42, cbdac34, 96f9c0d, c5aa9d0, ef4d3f5, 3ec09a0, 438ac53, 293a0a6, a8cb2eb, da30535, 3bc7f7f, 4465149, 2095bf2, 6124a74, ab4730c, f485730 | `core/agent/reflection.py` (+690), `core/agent/memory/work.py` (+591), `core/agent/personal_skills.py`, `core/environment/environment.py` (14 commits) |
| SWE-bench Verified integration and grading infrastructure | 5 | 6da0e2a (75-file dump), 77a641f, 381755f, 92e57a0, c19b479 | `tasks/swebench/*` (new), metadata manifests |
| Viewer / frontend | 20 | 63952a9, e9c6aee, 73fb2d7, 22dea2a, 2098469, 6c1db7d, c3c31ac, 268c959, 9b8ad2c, 3794094 | `frontend/static/js/**`, `tests/frontend/*.mjs` |

About 45 small plan documents were added under `docs/plans/`, plus about 20 new top-level docs (`docs/activity-scheduling.md`, `docs/realtime-scheduling.md`, `docs/independent-scheduling.md`, `docs/technical-community.md`, `docs/swebench-*.md`, `docs/zenith-livecodebench.md`, ...). `docs/experimental-design.md` is unchanged; a competing study design was added in Chinese at `docs/plans/2026-10-22-social-learning-study-design.md`.

## 2. Design changes vs local main

The intended design shifts from the scene-based town (slots, work rounds, conversation turns, evening review) to residents who choose and stay in Activities. The scene scheduler is kept as the default for shipped configs, and three opt-in schedulers are added. `runtime/simulation/config.py` now accepts `scheduling: scenes | independent | activities | realtime`.

- Activities (`runtime/activities/`): Work, Conversation, Rest, Move, a "Planning" label for activity selection (348b11e), and a Reflect activity (a8cb2eb). Each activity has its own tools, help text and interruption rules. Tool costs are simulated, set per activity.
- Realtime (`runtime/realtime/`, `RealtimeEngine(ActivityEngine)`): simulated time advances by the measured wall-clock time of LLM requests and tools, times a multiplier (15 in every launched run). LLM decisions are streamed and cancelled when something visible changes (8300d1c), later limited to replies addressed to the resident (6fd353f). A partially generated answer is kept as a "continuation draft" and fed back on the next request (661e741, 3a32cdb, `core/agent/continuation.py`).
- Conversations: persistent conversation instances, invitations with acceptance separate from joining, wake-ups for new conversations, duplicate-speech suppression, and a private thought on replies (373c5c3).
- Work: SWE-bench Verified tasks in per-resident Docker repositories (6da0e2a, 77a641f), private per-job work journals (`work/task-N/events.jsonl`), Work context built from the job's original log under a shared token budget (3bc7f7f, 2095bf2), and a bounded summary written by Reflect before leaving Work (293a0a6, a8cb2eb, da30535).
- Paired tasks with a required shared work discussion (ef4d3f5) were added on 10-21. One day later all community profiles were switched to 8 solo jobs with 0 joint jobs (f485730), and the study design rules out joint jobs.
- Personal skills (3ec09a0): residents can select, write or retire notebook methods during any daytime decision. Skill bodies are no longer injected into the prompt automatically; the resident has to call `use skill`. Invariant 4 in `docs/ARCHITECTURE.md` was weakened from "every self-modification is a commit" to "every self-modification is recorded".
- Evolution cadence (438ac53): the default L1 skill review changed from weekly to daily. Because no shipped config pins a `schedule`, this changes `town`, `city`, `firm`, `pilot` and the `trust` study.
- Lunch at a fixed restaurant; evenings are left to the residents (dfd9d6c).
- "Zenith" means the remote GPU development machines. Many commits and configs are tied to them: `experiments/configs/zenith/*.yaml`, including copies named after commits and timestamps (`swebench-town-e841d09-20261013-2303.yaml`), plus `experiments/configs/community/*.yaml` with hard-coded machine storage paths.
- The study design (`docs/plans/2026-10-22-social-learning-study-design.md`) defines arms A–D, adds an optional arm E, uses solo jobs throughout, sets per-resident daily token/tool/message budgets (T/Q/S), a 3-day pilot followed by formal runs starting at 7 days with 10–20 seeds, post-tests on unseen SWE-bench tasks, and nine home-made character scenarios. It says itself that most of these controls are not implemented yet.

## 3. Alignment with the target framework

Aligned or useful:
- The SWE-bench Verified provider and grading (`tasks/swebench/`): per-resident containers, offline metadata cache, environment preflight, and treating "no verdict" as an infrastructure error instead of a score of 0 (`tasks/swebench/provider.py:563-571`, `AssessmentUnavailable`). Local main has no SWE-bench support at all.
- The Activity abstraction (one activity with its own tools and help) is close to the target's Event abstraction (Idle/Work/Conversation/Movement/Sleep events that each expose tools). Rest corresponds to Sleep/Idle, Move to Movement.
- Private work journals and bounded work summaries with source provenance (`core/agent/memory/work.py`, `core/agent/reflection.py`) can serve the internal honesty evaluation: compare each summary with its raw log to detect factual distortion. That evaluator is not built.
- Arms A–D in the study design match the target groups, with the same contrasts. The design is a plan only.
- Living cost against wages and the end-of-day rating review are kept. Activity engines feed `sim._met`, so the evening `Review` still runs (`runtime/simulation/simulation.py:416`).

Contradicting, or adding complexity the target does not need:
- Four schedulers where the target needs one Event runtime. `independent` (c2bfc51) was superseded the next day by `activities` (1d8fac6) but was kept. `realtime` makes simulated time depend on GPU throughput and queueing, so a seed cannot be replayed and arms on different hardware are not comparable. The remote study design itself says the main experiment should use the deterministic Activity scheduler, yet all 14 launched runs used realtime.
- Run length and scale: the target is 28-day runs. Every remote run was 3 days with seed 0, and the study design proposes "7 days to start".
- External honesty: the target uses MASK. The remote design uses nine home-made scenarios; MASK appears only as a deferred idea (`docs/reviews/DESIGN_PLAN_2026-10-12.md:121`).
- Streaming cancellation with continuation drafts, invitation lifecycles, team discussions, early arrival, workplace hours and repeated Planning card wording are simulation polish. None of them is required by the target, and each adds failure surface. The Activity engine is a single class of about 87 methods (`invitation_action` is 222 lines, `select` 195, `wake_rests` 185).
- Daytime personal-skill edits are an extra write path that is always on. Arm D (memory-only) would have to disable it, and the design admits that D must cover "all write entries".
- Paired tasks were built (ef4d3f5, 878 lines) and then removed from all profiles the next day (f485730). The code stays in the repository.

## 4. Suspected defects and misleading decisions

1. No experiment completed and none was analysed. The logbooks record 14 three-day realtime runs launched in about 48 hours (e.g. `community-prompts-3d-20261020-0104`, `community-streaming-3d-...153720`, `community-draft-3d-...173513`, `community-budget-3d-...190607`, `community-directed-dedup-v2-3d-...224709`, `community-thought-3d-20261021-015020`, `community-team-3d-...113603`, `community-reflect-gpu{1,2}-3d-...`, `community-current-work-gpu2-3d-20261022-000554`). Every recorded outcome is a failure, a user-requested replacement, or "startup observations only". No logbook entry reports a completed run or any measured social or character outcome. Most "Record ..." commits are deployment receipts.
2. Required-context growth was never fixed. Two runs died with `ContextOverflow: Required task/identity/reply format exceeds input budget` (`core/agent/context.py:160`): directed-dedup-v2 on day 3, thought run on day 2 (`PROJECT_LOG_2026-10-21.md` lines 63 and 112). The log calls this "an unresolved risk"; later launches state they do "not claim to fix" it. Because the error is raised rather than recorded as a lapse, one oversized request ends the whole run, against architecture invariant 7 ("lose no run to one reply"). An earlier overflow in the correction path was patched separately (3a32cdb), which is a sign of fixes at the symptom level.
3. Model thinking was disabled to get around nightly failures, without a root-cause fix. The thinking-enabled run (8300d1c) failed on night 1: 8 of 8 residents lapsed L0 because diary outputs ran out (`PROJECT_LOG_2026-10-20.md`, "Frozen streamed run failed"). Every later run sets `enable_thinking=false`. The run named "community-thought" (0e37e12) refers to a private thought field, not model thinking, which is misleading when results are read.
4. The same components were fixed repeatedly, a sign of design churn:
   - Rest: 292f405, 032b9c8 ("keep rest deadlines within the current day") then reversed by 878258e ("preserve explicit rest deadlines across days"), f2d61e3, 97c4d26, 68f8afa.
   - Work context and summaries, redesigned seven times in two days: c5aa9d0, 293a0a6, a8cb2eb, da30535, 3bc7f7f, 4465149 (merge), 2095bf2.
   - Invitations: 0c31f1d, a17ae6c, 1bbb292, cffce9c, then a094d52 "Restore invitations", a regression fix.
   - Conversation thoughts: 373c5c3 "Restore private thoughts", then 6b13182.
   - Planning colour: 2098469, 6c1db7d, c3c31ac, plus 3 log commits.
5. The evolution cadence changed silently (438ac53). `EvolutionConfig.schedule` now defaults to daily L1 for every config that does not pin a schedule, including `experiments/studies/trust.yaml`. That is about 7x the L1 cost and breaks comparability with earlier runs. An exception, `_LEGACY_SCHEDULED_DEFAULT`, was added so the free mode keeps validating (`core/agent/evolution/config.py`).
6. Grading treats OOM as a timeout. `tasks/swebench/evaluate.py` `exec_run_with_timeout` counts exit code 137 (SIGKILL, including OOM) as a timeout, so the harness records an unresolved task, not an infrastructure error. The logbook documents OOM kills (exit 137) on Django tests (`PROJECT_LOG_2026-10-20.md`, "Three-day run snapshot failure"). The module docstring says "official grading [is] unchanged".
7. Interruption and correction overhead is large. In the draft run, 40 of the first 75 calls were cancellations. In reflect-gpu1, 81 calls included 15 interruptions and 11 format corrections. The first answer is free-form and only retries enforce the schema, so roughly 1 in 7 calls is a correction. All of this counts against any compute-budget comparison between arms.
8. Validation is weaker than the receipts suggest. Linux runs routinely deselect "13 baseline environment cases", and 11 of 12 metadata selectors failed because bubblewrap could not run (`PROJECT_LOG_2026-10-20.md`). The final commit f485730 was never validated on Linux: SSH timed out (`PROJECT_LOG_2026-10-22.md`).
9. Repository hygiene and private data:
   - The logbooks contain a public IP and SSH port for the development host, host names, PIDs and many private evidence paths. 6da0e2a is a 75-file "save local work" dump.
   - Configs carry machine-specific absolute paths, and configs copied per commit sit under `experiments/configs/zenith/`.
   - About 65 new docs violate the single-source rule: four scheduling docs, `docs/summary.md` paragraphs restating ARCHITECTURE details, and two competing study designs.
   - The activity engines reach into private simulation internals (`self.sim._met`, `runtime.scenes.scene._decide/_announce_draws`).
10. There is no evidence that daytime personal skills are ever used. The logs report no rate of `use skill` calls in any run. Since skill bodies are no longer injected automatically (3ec09a0), skills may stop influencing behaviour at all, which would weaken the self-evolution signal under study.

## 5. Cherry-pick recommendations (priority order)

Take these, porting by hand where noted:
1. `tasks/swebench/` as of origin/main, together with its tests (`tests/tasks/swebench/`) and `core/environment/rejection.py` (`AssessmentUnavailable`, `TaskUnavailable`). It originates from 6da0e2a, 77a641f, 381755f, 92e57a0 and 2095bf2. Port the files, not the commits: 6da0e2a is a mixed dump. Fix the exit-137 handling in `evaluate.py` before using it. This is the only complete implementation of the target's work tasks.
2. Offline Verified metadata and preflight (77a641f: `verified-4.1.0-manifest.json`, `http_cache.py`, `environment_spec.py`, `preflight.py`). They give reproducible grading and catch broken images before a run.
3. Repository snapshot diagnostics (381755f). It fails fast with the failing git stage and keeps the previous patch, which matches the Failure Principle.
4. The design of work journals and bounded work summaries (`core/agent/memory/work.py`, the summary part of `core/agent/reflection.py`). Re-implement them small. They are the substrate for the internal honesty evaluation; keep source-entry provenance.
5. The idea behind 3a32cdb (count required material before optional context in the budget), but make overflow a recorded lapse instead of ending the run.
6. As a reference only: arms A–D, the per-seed paired analysis and the infrastructure-error rules from `docs/plans/2026-10-22-social-learning-study-design.md`. Replace its home-made honesty scenarios with MASK and its 7-day horizon with 28 days.

Leave behind:
- `realtime` scheduler and streamed interruption / continuation drafts (8dd00e5, 8300d1c, 661e741, 6fd353f, 3e6f124, d34b514): not reproducible, large overhead, and the source of several run failures.
- `independent` scheduler (c2bfc51): superseded the next day.
- `runtime/activities/engine.py` as written: one 3.1k-line class carrying invitation, team and early-arrival logic. Redesign a minimal Event runtime from the target spec, using it only as a reference for activity/tool boundaries.
- Paired tasks and team discussions (ef4d3f5, 3794094): reverted in effect by f485730.
- Daily L1 default (438ac53): if daily L1 is wanted, set it explicitly in a config.
- Always-on daytime personal-skill editing (3ec09a0, 6124a74, ab4730c): it complicates arm D and has no usage evidence.
- All "Record ..." receipts, frontend colour and card-wording commits, `experiments/configs/zenith/*` and machine-specific community configs.
