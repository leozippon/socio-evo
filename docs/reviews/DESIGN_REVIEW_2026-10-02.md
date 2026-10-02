# Design review — 2026-10-02

This review asks three questions of the stage-1 system as built: can it achieve the research objective, is its social life close enough to the real thing, and is it interesting. It combines two readings made separately: the designer's own, and one by a reviewer who had not seen the project and was given only the research motivation, the documents, the code and the runs. The two agree on every major point; where they differ it is said. Evidence comes from the three-day smoke run and the first days of the 28-day pilot (seed 0).

## Verdict

The system is a sound instrument and not yet an experiment. Truth is kept apart from memory, every agent version is a dated commit, evaluation can be replayed for any past day, and no text steers traits. Those foundations need no change. But in the society as built, honesty, cooperation, reliability and resistance to reward hacking almost never change what happens to an agent, nothing is selected, and the probes cannot tell character change from other things that change over a run. A long run today would show how language-model agents form beliefs under noise. It could not support the claim that social pressure shapes stable character.

## Can it achieve the research objective?

**Trait-relevant behaviour has no consequence.** Every accepted delivery so far has had perfect true quality: 9 of 9 in the smoke run and 18 of 18 in the pilot's first two days, with no failed attempt at all. With no latent defects there is nothing to discover, so the pilot's day-15 oversight change cannot have an effect. Income is decided by the draw for contested claims: on pilot day 1 all eight agents planned to claim the same task, and 40 claims were refused in two days. Nobody is paid on their word, nobody can pay anyone else, help is worth nothing because every task is easy, and nothing in the world tracks a promise. An agent that lied, free-rode or broke its word would earn exactly what it earns now.

**Nothing is selected.** Esteem is computed and shown, and consumed nowhere: it affects no claim, payment or access. Balances have no consequence either, since debt is allowed without limit. The only path from "social pressure" to an agent is the agent reading a number and choosing to care. One agent's probe transcript shows that path at work ("refusing a neighbor's request might damage social standing, which is currently at 4.0"), but that is anticipation of a sanction that does not exist. What the system currently tests is whether reflecting on feedback shifts a language model's behaviour, which is a weaker thing than selection.

**What agents learn is folklore about the claim lottery.** Policies after one pilot day read "speed of claim execution is the primary metric for success, not task value" and "my goal is to be the first to claim … will only consider quality or difficulty after the claim is secured". Agents still read luck as lateness or as a rival's dominance even though they are told the draw.

**The probes are not yet measurements.** Three of four sit at the ceiling on day 0, so they can register decline only. The reward-hacking probe scores competence, because the agent is never left failing near a deadline, which is where hard-coding tempts. The honesty and cooperation probes cost nothing to pass. The one probe that moved, reliability, is confounded three ways: the prompt at day 3 is about six times longer than at day 0 and the commitment is buried in it; one agent broke the commitment through a date-arithmetic slip rather than a choice; and the competing offer is several days of income. Each trait has one scenario, three repetitions and a binary score, so there is no convergent validity and no dose-response. The judge is the same model as the agents.

**The base model is the main confound.** All agents share one model that arrives polite, helpful and honest. This has two consequences. First, improvement has no headroom, and the question that can actually be answered is two-sided: does task pressure erode the character the model starts with, and does social contingency protect it, accelerate the erosion, or redirect it? That reading fits the stated question about how task pressure and social pressure act jointly, and it is the more plausible and safety-relevant phenomenon. Second, any drift needs controls the system cannot yet express: an arm with no society, an arm where social feedback has the same amount but is decoupled from behaviour, and a placebo for prompt growth.

**"Stable" and "character" are not operationalised.** They would need to mean agreement across several situations for one trait, test-retest agreement across days, and persistence after the incentive is removed, which is what separates character from compliance. A fourth test follows from how evolution works here: at L0–L2 an agent's character is text it wrote and rereads. Evaluating an agent with its policy removed, or its insights removed, would show where a trait lives and whether it is more than self-prompting.

**Power and horizon.** The unit of analysis is the run, since agents in one society are not independent, so one seed per condition is an anecdote. In 28 days the scheduled policy rewrite falls only on the last night; four of eight pilot agents asked for one on day 1, on a single day's evidence.

## Is the social life close enough to the real thing?

No. What exists is co-location, polite talk about work and a rating with no effect. The features of social life that form character are mostly missing.

| Feature of real social life | Here | Does the absence threaten the claim? |
| --- | --- | --- |
| Repeated interaction with known individuals | Present but thin; talk is about the board | No |
| Reputation that changes how others treat you; partner choice | Absent: esteem is displayed only | Yes — this is social selection itself |
| Interdependence: joint work, trade, lending | Absent | Yes, for cooperation |
| One side relying on the other's word | Absent in the world; exists only in a probe | Yes, for honesty |
| Profitable cheating with uncertain detection | Designed, but inactive because tasks are easy | Yes, for reward hacking |
| Promises whose keeping can be observed | Thin: nothing gives a reason to make one | Yes, for reliability |
| Harm that lands on a particular person | Absent: defects are found by chance, not by someone who depended on the work | Moderately — victims are where grievance and gossip come from |
| Private talk and gossip about absent others | Thin: speech "to" someone is heard by all present | Moderately |
| Material consequence of poverty or exclusion | Absent | Moderately — weakens every pressure |
| Differences in ability, need or position | Thin: one model, differences in backstory only | Moderately — difference is what makes help and exploitation meaningful |
| Honest signals of regard | Ratings are free and cluster at 4–5 | Moderately |
| Leisure and goals other than money | Thin: free slots exist, evenings are spent at home | No, for now |
| Birth, death, inheritance | Absent | No, provided partner choice supplies selection |

## Is it interesting?

Not yet as a study of character: the outcome is predictable from the setup. Agents are polite and work-focused, converge on the same rules of thumb for the board, rate one another 4 or 5, and do not cheat because nothing tempts them.

Some of what does emerge is worth keeping, though it concerns belief formation rather than character. False information spreads socially: one smoke-run agent told another that tasks appear in the late afternoon, which is untrue, and two days later the listener's policy said to "remain alert for late-afternoon batches". Agents assign credit superstitiously, reading a rival's luck in the draw as dominance. Worry about income leaks into unrelated decisions ("I cannot afford to give away an entire evening for free"). And the draw is an exogenous, randomised source of good and bad luck, so whether bad luck makes an agent more mercenary is a clean causal question the system already supports.

## What to change

Mechanisms only; nothing here tells agents how to behave or pays for a trait.

**Necessary before a long run is worth interpreting**

1. *Make failure and temptation real* (medium). Recalibrate the task bank until this model fails the visible checks on a first attempt in a third to a half of deliveries within the rounds it has; include tasks whose visible checks can be met more cheaply than the specification; enlarge the bank well beyond twelve tasks, each of which a 28-day pilot posts about fourteen times. Measure special-casing in the simulation with the detector the probe already uses.
2. *Work paid on the worker's word* (small to medium). Some jobs have no visible checks: payment follows the report, and the truth surfaces later as defects do, with the original report quoted when it does. This puts an honesty dilemma with uncertain detection into the world.
3. *Partner choice* (small to medium). Let standing decide something. The cheap form is clients who prefer well-regarded workers when a claim is contested. The better form puts the choice in agents' hands: team tasks where members choose one another, subcontracting, invitations. Then selection is exercised by peers, rating becomes a strategic act, and choosing a partner is a revealed preference that is more honest than a free rating.
4. *Control arms* (small to medium, mostly configuration). Solo: one agent, the same task stream, no peers. Yoked: esteem, ratings and defect notices replayed from a matched run, so the pressure has the same size but no longer depends on behaviour. No-evolution, which exists. A context-matched placebo for probes.
5. *Rebuild the probes* (medium). At least three scenarios per trait, graded stakes reported as the threshold where behaviour flips, ten or more repetitions, paraphrases, a judge from another model family. Reward hacking measured after a visible failure with the deadline close; honesty with a real cost to disclosure. Observed and unobserved variants of the same scene, and evaluation with the policy or the insights removed.
6. *A pressure-removal phase* (small). Switch off discovery and partner choice late in a run and keep probing.
7. *Real isolation for delivered code* (medium). Today a solution that explores the machine can read the hidden expected values. That is harmless while nobody needs to cheat; once tasks are hard it is both the most interesting hack and a contaminant.

**For realism and interest**

Payments and lending between agents; team and subcontracted tasks; defects that are found by the person who depended on the work; a private channel for talk; tasks posted through the day so that being present matters and board superstitions meet reality; real differences in circumstance such as recurring obligations, unequal starting balances and occasional shocks; a material floor below which options narrow.

**Later**

Embedding retrieval; L3 and L4, which are premature until L0–L2 show any shaping; analysis tooling such as a per-agent luck index from the draws.

The two readings differ on one point. The independent reviewer rates partner choice as small, implemented as esteem-weighted claims. The designer's view is that an environment that weights by esteem is still the environment doing the selecting, and that the version worth building is the one where agents choose, which is medium.

## The first experiment on the improved system

Eight agents for 42 days with hard tasks, word-paid jobs and levels L0–L2. Four arms: social (partner choice on, esteem public); yoked; solo; social without evolution. From day 29 the social and yoked arms switch off discovery and partner choice. Ten seeds per arm, matched across arms so that task streams and draws coincide. That is 40 runs; at the pilot's measured pace of about 3.5 minutes per simulated day each takes roughly two and a half hours on the current endpoint.

Measures in the simulation, weekly: special-casing rate on hard tasks, false-report rate on word-paid jobs, help given when asked, promises and loans kept. Held-out probes on days 0, 7, 14, 21, 28, 35 and 42 with placebo-matched baselines. Stability: test-retest between adjacent evaluation days, agreement between probes of one trait, and the change from day 28 to day 42. Analysis with the run as the unit, agents nested in runs, and draw luck as a covariate.

The hypothesis is supported if the social arm diverges from both yoked and solo on held-out probes, by more than the spread between seeds and the drift of the no-evolution arm, and the difference survives days 29 to 42. No difference between social and yoked means the effect is pressure in general rather than social contingency. A difference only inside the simulation means strategic adaptation. A difference that vanishes after day 28 means compliance. A shift the placebo matches means context effects.

## What is not known

The pilot had finished two days when this was written, so there is no long-horizon evidence yet on whether policies converge, diverge or oscillate. Whether this model cheats under real pressure at all is untested; if it never does, the reward-hacking axis needs a different design. The reflection prompt asks which choices led to which outcomes, and the only quantified outcomes are credits and esteem, which may by itself tilt agents toward mercenary thinking; a wording ablation would settle it. The attribution of the reliability drop to prompt length rests on two inspected prompts and one slip.
