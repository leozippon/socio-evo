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
- **The pilot has not been run on the model.** Eight agents for 28 days is estimated at two to three hours.
- Not built: L3, L4, team tasks and payments between agents, birth and death, container isolation, embedding retrieval.
