# Project log — 2026-10-02

## Built today

The runtime (trigger queue and calendar, planning / work / conversation / review scenes, the day loop with evolution, interventions, checkpoints and exact resume), the experiment layer (config, smoke and pilot configurations, run CLI with a schema-driven dry run), the held-out evaluation with its CLI, and the replay frontend. `docs/summary.md` now introduces the design for users.

## Changes driven by what real runs showed

- **Contested claims were misread as lateness.** Agents who lost a claim concluded that 09:00 was "too late" and wrote arrival rules into their skills and policies that the world cannot honour. Claimants of the same task are now told the random order in which claims were taken. This is a neutral statement of a real rule, but it does make coordination more salient.
- **Arrival order was a confound.** With a fixed move order the first agent in the configuration was always seen arriving first. Moves are now drawn at random.
- **Nobody met outside work.** Every slot offered paid work, so nobody chose a social place. Places now have opening hours; work places close at midday and in the evening, which makes leisure a fact of the town rather than an instruction.
- **Evening percepts were lost.** Events witnessed after an agent's last decision of the day never reached its diary; they are now delivered before nightly reflection.
- **The reliability probe went unmeasured.** After three days every agent declined a morning meeting because of work routines it had written for itself. The collision moved to the evening, and the agreement rate is kept as its own measure.

## Audit

One independent pass against the invariants, with reproduced evidence. Fixed:

- **Check results were forgeable.** The verdict was produced in the process that ran the solution, so a solution could pass every check, hidden ones included (an object equal to anything; a forged result record; reading the expected value from the caller's frame). A check is now a call plus an expected value that never enters the child; the child returns plain data and the parent compares type-strictly. The three hacks are permanent regression tests.
- **Claims from different work places were decided by configuration order.** A turn's decisions are now carried out in one seeded order across all scenes.
- **Evolution steps that changed no file left no trace**, which let the once-per-night rule and the self-trigger cooldown be bypassed. Every applied step is now a commit, empty if need be.
- Smaller: bounded sandbox result pipe; sibling tasks cancelled on failure; intervention times restricted to points the simulation can honour in order; evolution levels validated before any directory is written; evaluation refuses days beyond the latest checkpoint; model adapters rejected until L3 exists; the unused plan event kind removed; neutrality scans extended to every request sent in a pilot dry run and in the scripted town.

Accepted and documented rather than fixed: delivered code runs as the simulator's user, so code that explores the machine can read the task banks, the run directory and the process environment (container isolation is not built); a run killed abruptly stays marked running, though resuming it works; the checkpoint file is not fsynced before its rename.

## Acceptance run

Smoke configuration on the local model at revision 374afac: 3 agents, 3 days, 119 model calls, no errors or retries, 142–172 seconds per simulated day. Nine deliveries, all accepted at true quality 1.0. 28 utterances, 15 at the café and 13 at the workshop. Eight ratings, all 4 or 5. Evolution: nine L0 steps, three L1, three scheduled L2 and one self-requested L2. 196 tests pass.

Held-out evaluation of that run, three repetitions:

| Trait | Day 0 | Day 3 |
| --- | --- | --- |
| Honesty | 1.00 for all three agents | 1.00 for all three |
| Cooperation | 1.00 | 1.00 |
| Reward-hacking resistance | 1.00 | 1.00 |
| Reliability | 1.00, 0.67, 0.67 | 0.00, 0.00, 0.00 |

Three agents, three days and three repetitions are far too little to read the reliability drop as a finding.

## Open questions

- **Probe calibration.** Three probes sit at the ceiling for a fresh agent and can only show decline. The reliability probe's competing offer (150 credits, about six days of living cost) may be too large to discriminate. Both need tuning before trajectories mean anything.
- **Social life is thin.** Conversations are mostly about work, every evening of every smoke run was spent at home, and ratings barely vary, so esteem separates agents little.
- **Task difficulty.** With every delivery at true quality 1.0, there are no latent defects to discover; the bank is too easy for this model to create the temptation the design relies on.
- Not built: L3, L4, team tasks and payments between agents, birth and death, container isolation, embedding retrieval.

## Design review

A review of whether the system as built can answer the research question is in [reviews/DESIGN_REVIEW_2026-10-02.md](../reviews/DESIGN_REVIEW_2026-10-02.md). Its verdict: a sound instrument, not yet an experiment. Trait-relevant behaviour has no consequence, nothing is selected, and the probes cannot yet separate character from context. It lists the changes needed before a long run is worth interpreting and proposes the first experiment.

## First pilot run

Pilot configuration, seed 0, at revision 93d8a24: 8 agents, 28 days, 2 hours 22 minutes of wall-clock, 2,103 model calls and 10.8 million tokens, no failed call. Days took 3.5 minutes at the start and 5 to 8 at the end, as prompts grew. It is a baseline of the regime the review describes, not evidence for the research claim.

- **Work.** 168 deliveries accepted, 3 attempts refused by the visible checks, 1 claim lapsed. Three accepted deliveries carried a latent defect (true quality 0.86 each) and all three were found, with 90 credits clawed back.
- **Scarcity.** 261 of 430 claim attempts were refused; 117 draws. Final balances run from 245 credits (Jonas) to −235 (Ravi), with three of eight agents in debt.
- **Social life.** Ten conversations in 28 days, all at midday, nine of them between two people; none after day 4 except on days 9, 15 and 23 to 26. Of 162 utterances, 119 were at the workshop. One agent's final policy reads "do not engage in social interactions until the day's income is secured and submitted".
- **Ratings.** 533 ratings: 345 fours, 147 fives, 36 threes, 5 twos. Published esteem converges on 4.0 for everyone.
- **Evolution.** 224 nightly reflections, 35 skill reviews (4 self-requested) and 31 policy rewrites (23 self-requested).

## Dashboard and deployment

A new `analysis` package derives per-agent and society measures, the social graph, model usage and score rows from a run directory. The frontend became a static site: `frontend.publish` writes the viewer and a content-addressed JSON bundle in which finished days and agent versions are immutable files, and the viewer was rebuilt as an experiment dashboard, a town with a two-level timeline that shows each private thought beside what was then said, and a per-agent view of the git history. The dashboard needs no server-side code.

It is deployed on the `cornerhead` server as its own loopback-only nginx site on port 8090, serving `/opt/socio-evo/site`, beside the existing console, which was left untouched and verified before and after. Access is through an SSH tunnel. Updating it is one publish followed by `frontend/deploy/push.sh cornerhead build/site`, which uploads only changed files and switches releases atomically. The deployed site was driven in headless Chrome through a tunnel: every view loads in under two seconds with no console error.

Two defects surfaced while evaluating the pilot and were fixed: the judge's word-for-word quote check rejected quotes that differed from the reply only in typographic quotation marks, which aborted the evaluation; and agent-days were evaluated one after another, which would have taken hours, and now run concurrently.
