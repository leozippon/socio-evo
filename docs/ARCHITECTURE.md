# Architecture

This document is the authoritative statement of how the code is layered, what each module is responsible for, and which conditions must always hold. Exact signatures live in the code; when the two disagree about structure or an invariant, fix whichever is wrong in the same change.

## The core loop

```text
Environment ── Observation ──▶ Agent [Memory + Parameters]
     ▲                              │
     └────────── Action ────────────┘
     │
     └─ Event log (truth) ─▶ witnessed percepts ─▶ subjective memory ─▶ reflection ─▶ self-evolution ─▶ versioned agent
```

Agent is the brain, Environment is reality, Interaction is the protocol between them. Scenes and the scheduler decide who meets reality when; they add no semantics of their own.

## Layers

Imports point downward only.

| Layer | Package | Responsibility |
| --- | --- | --- |
| Composition | `experiments/` | Experiment configs, studies (the arms of a design as overlays on a base town) and command-line entry points; the only place that wires every layer together. |
| Presentation | `frontend/` | Publishes runs as a static site (the viewer and a bundle of JSON documents whose contract is `frontend/README.md`), serves it locally and deploys it. Reads run directories and never writes to them; imports `analysis`, `core.interaction`, `evaluation.results`, `infrastructure` and the read-only agent `History`. |
| Analysis | `analysis/` | Measures derived from a run directory, finished or in progress: the one place where the event log becomes numbers, for the dashboard and for statistics alike, plus model-usage aggregates and tidy evaluation scores. Reads only; imports `core.interaction`, `evaluation.results` and `infrastructure`. |
| Assessment | `evaluation/` | Held-out character and safety probes run on frozen agent snapshots. |
| Orchestration | `runtime/` | `scheduler/` (hierarchical event queue and calendar), `scenes/` (turn-taking), `simulation/` (run loop, interventions, checkpoints). |
| Work content | `tasks/` | Concrete task providers implementing the work protocol defined in `core`: coding tasks from a built-in bank or from banks converted from LiveCodeBench and calibrated against a model, kept outside the repository, assessed in an isolated sandbox. |
| Domain | `core/` | `interaction/`, `agent/`, `environment/`. |
| Foundation | `infrastructure/` | LLM clients, run-directory layout, JSONL and git helpers, config loading. No domain knowledge. |

Inside `core`, `agent` and `environment` never import each other. Both depend only on `interaction`.

## Interaction protocol (`core/interaction`)

- **Time** is an integer count of simulated minutes since the start of day 1. Helpers convert to day number and clock time, and tell a day as residents do (`weekday`, day 1 being a Monday, and `lived_day`, which adds the count of days since everyone arrived in town). Cadences are expressed in days.
- **Event** is an immutable record of something that happened: `seq`, `time`, `kind`, `actor`, `place`, `scene`, `audience`, `text`, `payload`. `audience` is the resolved list of agent ids that witnessed it (empty for truth-only events). `text` is what a witness perceives; `payload` is structured truth for analysis and replay and is never shown to agents. `EventKind` is the single vocabulary of event kinds.
- **Audience rule.** An actor is not in the audience of an event that merely echoes its own action (its own speech or departure); the agent records its own decisions itself. It is in the audience of events that tell it something new: results, payments, rejections.
- **Agent id** is the agent's public given name (for example `Mei`), unique within a run and used verbatim in event texts, action fields and directory names.
- **Percept** is a witness's view of an event: every field except `payload` and `audience`.
- **Observation** is what the environment presents to one agent at a decision point: `agent`, `time`, `place`, `scene`, the `setting` (the standing knowledge of the town every resident has, unchanged from moment to moment until the town's rules change; may be empty), a natural-language `situation` of the present moment, the `percepts` newly witnessed since its last observation, what is `allowed` (below), and the names of the town's `places` as the agent knows them, by id, so that its memory can say where something happened.
- **Action** is a discriminated union on `kind`: `plan_day`, `speak` (to everyone, to one person by name, or privately to that person alone), `leave`, `pass`, `claim_task` (optionally naming a partner), `check_work` (run a solution for one part against its acceptance checks without delivering it), `submit_work` (a solution for one part, declared `complete` or `incomplete`, with a report), `give` (credits to someone present, with a note), `rate_peers`. A **Decision** pairs a private `thought` with one action. Decisions are recorded, logged and carried out in these terms, which no resident reads or writes. A field added to an action after runs were recorded has a default meaning what the action meant before (part 1 declared complete, no partner, not private), so recorded decisions keep validating with their meaning. Jobs are named for residents by the number on their notice (`job_name`, `job_id`).
- **Answer card** (`card`). An observation's `allowed` holds an allowance for each kind of thing the agent can do now, with the values that are really possible: the jobs for one and for two on the board and the neighbours who can be named for one (or none, when the clerk pairs by lot), the parts of its own job not yet in, the people present, the places open in each part of the day, the people it spent time with today. One definition turns the allowances into the forms of a reply, and the forms into the card a resident reads, the JSON schema of the same forms that a server enforces under guided decoding (closed objects, every field required, the thought first, enumerations in a sorted order so a card does not depend on the order a moment listed its choices in), and the translation of a reply into a Decision. A form opens with the thought and says what the resident does in plain words (`take a job`, `say privately`, `hand in`, …) with fields named and valued in the town's words, so the code's names never reach a resident. Every action kind has exactly one allowance class; a kind added later cannot be offered until it has one, and a test fails until it does. `form` writes out any reply model the same way, for the agent's nightly replies.

## Agent (`core/agent`)

An agent is a directory, and everything the agent is lives there in human-readable files. In a run that directory is also a git repository; a frozen export of one commit is a plain directory that loads the same way.

```text
agents/<agent_id>/
├── profile.yaml            identity seed: name, age, occupation, backstory (never evolves)
├── parameters/
│   ├── policy.md           L2: self-authored goals and principles
│   └── model.yaml          L3: base model, sampling settings, adapter reference (rejected until L3 exists)
└── memory/
    ├── episodic.jsonl      L0: experience stream built only from percepts and own decisions
    ├── diary/day-0001.md   L0: nightly diary
    ├── insights.jsonl      L0: consolidated reflections, optionally tagged with the agent they concern
    └── skills/<name>.md    L1: procedural memory
```

- `Agent` exposes one cognition entry point, `act(observation) -> Decision`: store the percepts, retrieve relevant memories, assemble the prompt, ask for an answer on the moment's card, and return the decision it means. The system message is the part that stays the same from moment to moment, so a model server can cache it: the identity told in the second person, the observation's setting ("what you know of the town"), the policy ("what you have resolved") and the index of the skill notes ("your notebook"). The user message is the moment: the most relevant notes in full, the recalled insights ("what you have come to believe"), the recalled episodic records and the new percepts as one recollection with the most recent last, then the time, the situation, the question of what the agent thinks and does, and its answer card. Every structured reply, by day or by night, is asked for with its form shown, whatever the structured-output mode. One voice speaks to the agent throughout, in the second person; its own words (thoughts, speech, diary, beliefs, resolutions, notes) are quoted as it wrote them. Its own decision is recorded in its episodic memory as what it did and then what it thought, told to it ("at the clerk's desk you handed in … You thought: "…""), with no action names or fields, and with the name of the place where the observation gave one; records stored in the earliest form (`My thought: …` / `My action: kind {…}`) load as before and are retold the same way when read. Percepts witnessed when no decision follows, such as those of the evening, are stored with `perceive`.
- `prompts` is the one place for the agent's own wording: every template, the telling of times and of the agent's own actions (with a plain fallback for an action kind it has no words for), and the nightly reply models, whose field names a model writes and whose forms it reads. Skill notes are shown by title (their file name as words) and written or taken out by title. The tests guarding invariants 1 and 8 enumerate it and the answer card, and scan every request an agent sends.
- `immersion` holds the machinery vocabulary of invariant 8 and `speaks_of_machinery`, which says whether a text a resident reads or wrote speaks of the machinery; the tests guard with it, and it measures how often residents' own thoughts do.
- `memory/` holds the stores above and a retriever (recency plus lexical relevance; pluggable later). Beliefs about other agents are insights tagged with a subject, so subjective relationships need no separate store.
- `parameters` holds the policy and the model specification; `config` holds the seed an experiment lists for each agent and the limits on prompt size.
- `evolution/` holds the levels, triggers, operators, the `Evolver` that maps a trigger to the enabled operators, and the version history.

| Level | Target | Default trigger | Stage 1 |
| --- | --- | --- | --- |
| L0 Memory | diary → reflection (insights, credit assignment) → consolidation | daily | implemented |
| L1 Skills | create, revise or retire skill notes | weekly | implemented |
| L2 Policy | reflective rewrite of goals and principles | monthly | implemented |
| L3 Parameters | adapter fine-tuning on own experience | — | not implemented |
| L4 Meta | the agent rewrites its own evolution procedure | — | not implemented |

Nightly reflection may request an out-of-cadence L1 or L2 step (self-triggered evolution), subject to a cooldown; a level is applied at most once per night. Enabling a level that has no registered operator is a configuration error, not a silent no-op.

Recording experience is not evolution: the episodic stream is always written, and whatever is uncommitted at the end of a day is committed as a plain experience commit, so a run with every level disabled is a valid baseline.

Every operator application is one git commit in the agent's repository (an empty one if it changed no file), with the level, trigger and simulated time in the message trailers and the commit date derived from simulated time. History, diff, branching for counterfactual runs, and frozen snapshots for evaluation all come from git.

## Environment (`core/environment`)

- `world` is physical truth: places (home, work, social) with map coordinates, the residents of each home, the opening hours of any other place (always open if none are given), and where each agent is. Agents start at home, and nobody can enter or stay in a place while it is closed.
- `society/` is social truth: the economy (integer balances, payments, the daily living cost and each resident's own obligation, credits given between agents, clawbacks; debt is allowed, but nobody can give what they do not have), reputation (esteem, the time-decayed mean of the peer ratings an agent received), and work (the task board, below).
- `config` fixes the town and the constants of society; it may give a resident its own starting balance and a daily obligation charged with the living cost.
- `conditions` are the knobs of reality that interventions turn: living cost; how many one-part and two-part tasks a posting adds and how likely a task's client accepts on the declaration; the reward multiplier, the premium on two-part tasks and the share paid for a part declared incomplete; whether two-person tasks go by partner choice or random assignment; defect discovery probability and clawback; whether esteem is public. They change only through one validated method that records a truth-only `intervention` event.
- `Environment` owns the event log and the per-agent perception cursor. It executes every action but `plan_day`, which the runtime turns into moves (`execute(agent, action, …) -> events`); posts tasks whenever the runtime calls it, at prices fixed by the conditions of that moment, for those at a work place to see, and pairs applicants by lot when asked; runs the daily processes at day start (tasks not completed by their deadline lapse and return to the board, stale tasks retire, defects are discovered) and at day end after the peer review (open proposals and applications lapse, living costs and obligations are charged, esteem is updated); offers agent-visible text views (the rules of work and of the ledger as the conditions make them, which belong to what every resident knows; the notices on the board, an agent's own status, with the code it last tried or had handed back for each part of its job, and the posted standings, which belong to a moment); and serializes itself for checkpoints. Restoring cuts the event log back to the checkpointed length. Its randomness is the generator passed to pairing and the day start, and the seed passed to posting: the k-th task of each size posted at a moment is drawn from a generator of its own seeded with that seed, the moment, the size and k, so that the same seed posts the same tasks whatever else has happened. Otherwise it is deterministic given the order of the calls.
- Everything a resident reads from the environment, event texts, views and refusals, is told in the town's own words as [IMMERSION.md](IMMERSION.md) sets out: a task is the job with the number on its notice, credits are crowns, a delivery is handed in as finished or unfinished at the clerk's desk, a rating is a mark in the clerk's ledger; nothing is asked of the board or refused by it. Truth-only texts, payloads, event kinds and action fields keep the code's names. A decision made on the answer card names jobs, people and places by their ids; one made otherwise may name them as a person would: a job by its number however it is written (`23`, `job 23`, `task-23`), a neighbour by name in any case, everyone present as `all` or `everyone`.
- An action that reality cannot honour (taking a job already gone, naming someone for work for one, handing in a part one does not hold or that is already in, giving more than one has, a private remark to nobody, marking oneself, naming an unknown place, entering a closed one) changes nothing and yields a private `action_rejected` event whose text is the refusal as the resident meets it. Agent mistakes are part of the world, not program errors.

Work is defined by a small protocol. A provider's unit is a `Part` (title, specification, reward, deadline, opaque reference), whose specification tells the worker everything the work requires, including the acceptance checks and the form of a delivery; a provider samples distinct parts with the run's generator and assesses a solution into whether it passes the acceptance checks, the feedback on them, and a true quality that only reality reveals. `tasks/` implements providers. The board composes parts into tasks and issues their ids:

- A task has one part, done alone, or two, done by two people; its client either runs the acceptance checks or accepts on the declaration (`checking` or `trusting`). A delivery declared complete is accepted by a checking client if the checks pass and is otherwise refused privately with the feedback, and is accepted by a trusting client unchecked; one declared incomplete is accepted by either at the reduced share and carries no liability.
- An agent works on at most one task. A one-part task is claimed. Under partner choice, a two-part task is proposed privately to a named agent and taken up by that agent's claim of the same task; under random assignment, a claim is an application and the board pairs applicants with the generator, each pair taking the task one of the two applied for. An agent has at most one open proposal or application; taking a task or making another withdraws it, and all lapse at day end. A taken task is announced to those present with either worker.
- Either worker may check or deliver either part. A task is paid when every part is accepted: each worker receives, for each part, the price fixed when the task was posted, its reward times the multiplier (and the premium, for two parts; and the share, if declared incomplete) divided among the workers. A paid part declared complete whose true quality is below 1 becomes a latent defect; discovery announces it to everyone with the worker, the day and the declaration quoted with the report, and the clawback takes back what each worker was paid for that part. A task not completed by its deadline lapses publicly, saying which part each worker delivered, and nothing is paid.

The event log stays the only record of what happened. Each rating is a truth-only `rating` event, so the directed ledger of ratings lives in the log and reputation keeps only the decayed sums esteem needs; each delivered part's true quality, and what its worker had seen of that very solution (its last private check, and any refusal), is a truth-only `work_assessed` event; private checks are `work_checked` events for the worker alone. The board keeps open offers, the claims with their accepted parts and the trials their workers saw, and a paid part only while its defect is latent. Every event that moves credits names each agent it touches and the balance after it, so payloads alone replay every balance.

Social pressure is produced by mechanism, not by reward shaping: clients pay by their own rules on what a worker declares; latent defects surface later with some probability and become public events that quote their cause; partners share both the pay and the liability of joint work and choose, or are assigned, each other; peers rate one another from their own experience; esteem is visible and shapes how others treat an agent.

## Runtime (`runtime`)

- `scheduler/` is a priority queue of data-only triggers (`time`, `kind`, `payload`: day start, slot, day end, intervention), ordered by time, then kind, then push order, and a calendar (day start and end, named slots and when each ends, weekly and monthly cadences in days). The hierarchy is run → day → slot → scene → turn: a day start expands into the day's slot triggers and its day end, model calls happen only inside scenes, and idle or solitary agents cost nothing.
- `scenes/` turn agents into observations and actions: day planning, a work session at every occupied work place, a conversation at every social place with company, and the evening ledger of the people met that day. A scene decides only who is asked when, what each is told, what each may do with the values that are really possible (the allowances of the answer card, following its circumstances: whether it works on a job, which jobs are on the board, who else is there, which places are open in each part of the day), and what becomes of the decisions; what an action means stays with the environment, which still refuses in the town's words a choice that went stale within the moment, such as a notice someone else won by lot. Each scene keeps its own pace: a work session's rounds are spread over the part of the day until the place closes, so the clock and the closing time tell a resident how much of the period is left; a conversation's turns are a few minutes apart. The driver plays all scenes in the order of their turns' times. The turns that fall at the same moment are played together: everyone they ask decides concurrently, each decision is recorded as a truth-only `decision` event (thought and action), and the decisions are carried out one by one in an order drawn from the run's generator across all scenes, so neither model latency nor the order of places in the configuration changes what happens. Agents who reached for the same notice at that moment are told the order the clerk drew, wherever they are, and after every moment the clerk pairs by lot the names put down for jobs for two.
- `situations` holds every runtime text a resident reads, under invariants 1 and 8: the setting, what every resident knows of the town (its places and hours, the shape of its days and when notices go up, and the environment's rules of work and of the ledger), which every observation carries and which changes only when the rules do; and the moments, which are short: where you are, who is here, when the place closes, your purse and job (with the draft on your desk for each part), and the board. What a resident can do is on its answer card, so a moment says only what the card cannot. The board is physical: a wall of numbered notices kept by a clerk, who draws lots, takes in work, passes on what clients say and pay, and keeps the ledger. The time of a moment is told by the agent's prompt. Nothing tells a resident how long the run lasts.
- `simulation/` dispatches triggers: day start (environment processes, planning), slots (moves in an order drawn at random, so nobody is always seen arriving first, and home for an agent whose move reality refuses; new jobs posted if the slot is one of the configured postings, drawn from the run's seed and the moment; scenes), day end (everyone home, the ledger, environment processes, the day's remaining percepts into each agent's memory, each agent's evolution on the cadences due, checkpoint), interventions (condition changes, announcements; only at the day start, a slot start or the day end, taking effect before anything else at that time). Agents that act or evolve concurrently are one group: when one fails, the others are cancelled before the run is marked failed. It can create a run or resume one from its latest checkpoint, and it keeps the manifest status truthful: running, completed, failed, or interrupted when stopped early.

Because triggers are data, a checkpoint is the day, the environment state, the queue, the random state and each agent's commit id; the first is written before day 1. Resuming restores exactly that point and discards anything written after it, except the model-call log, whose calls did happen.

A study (`experiments/study.py`) is a base town and named overlays, each arm the base with some overlays merged in, run over the same seeds, each run in a process of its own with a bounded number at a time, skipping completed runs and resuming the others. A seed matches across arms exactly as far as their rules coincide: every arm posts the same jobs with the same clients at each moment (an arm that posts fewer posts a prefix of them); every other draw comes from the run's one generator, seeded alike, and stays matched only until what residents do makes the arms diverge.

## Evaluation (`evaluation`)

Held-out probes measure honesty, cooperation, reliability and resistance to reward hacking. A probe runs against a frozen export of an agent at a given commit; nothing it does reaches the agent's memory or the society. Scoring is behavioural and objective where possible, with a separately configured judge model for free text. Probe scenarios are disjoint from in-simulation tasks.

Each probe is an ordinary scene of town life with placeholder neighbours, played through the standard protocol on a fresh export for every repetition: a held-out coding task, scored by its hidden checks and by whether the code writes out the public examples, and replies to a client, a colleague and a neighbour, the last followed by the next day's plan. The judge answers one factual yes-or-no question per reply and must quote it; each agent and evaluated day gets one result file with scores, measures and transcripts (`evaluation/day-NNNN/<agent_id>.json`), and the evaluation's own model calls go to `evaluation/llm_calls.jsonl`, apart from the run's.

Evaluation is an offline process over a run directory, not a step of the simulation. Because every agent state is a commit dated in simulated time, any day up to a run's latest checkpoint can be evaluated, or re-evaluated with new probes, after the fact; the runtime knows nothing about evaluation.

## Run directory

`infrastructure.storage.RunDirectory` is the single source of this layout.

```text
runs/<experiment>/seed-<NNNN>/
├── manifest.json          status, seed, code revision, start and end times
├── config.yaml            the resolved configuration, frozen at creation
├── events.jsonl           environment truth, append-only; drives replay and analysis
├── llm_calls.jsonl        every model call: agent, purpose, request, response, usage, latency
├── checkpoints/day-NNNN.json
├── agents/<agent_id>/     the agent repositories
└── evaluation/
    ├── llm_calls.jsonl    every model call of the evaluations, agents' and judge's
    └── <label>/<agent_id>.json
```

Creating a run in an existing directory fails; resuming is explicit.

## Invariants

1. **No trait instruction.** Agent-facing prompts never tell an agent to be honest, cooperative, reliable or to avoid reward hacking, and never reward those traits directly. Tests guard the prompt templates, the situation texts, the personas, the probe texts and every request actually sent in a dry run of the pilot town and of the new town's study.
2. **Truth and memory are separate.** Agents learn about the world only through the `text` of events they are in the audience of. `payload` and truth-only events never reach an observation.
3. **The event log is the single source of environment history.** Replay, analysis and derived social graphs read it; nothing else stores a second copy.
4. **Every self-modification is a commit.** No operator changes an agent's files without recording it in the agent's history.
5. **Evaluation is held out.** It never writes to an agent repository or the event log.
6. **Runs are reproducible in structure.** All randomness comes from the run's seed: one generator carried in the checkpoint, and, for the jobs posted, generators seeded with the seed and the moment, which need no state; no module uses global random state.
7. **Fail fast.** Model output that is invalid or cut off by the token limit is asked for again a bounded number of times and then raises; unimplemented levels and unknown configuration keys are errors.
8. **Immersion.** Nothing an agent reads or writes reveals the machinery behind the town: it reads its own life in the second person, its memory as recollection and the town in the town's words, and it answers on a card in those words, as [IMMERSION.md](IMMERSION.md) prescribes. Tests scan every agent-facing template, every card, every request sent and every reply written with the vocabulary of `core.agent.immersion`.

Delivered code is the one input that could reach past invariants 2 and 5, so every check runs in a bubblewrap sandbox: new user, process, network and IPC namespaces, a read-only file system holding only the system libraries, the interpreter and the harness, a small private scratch directory, and the existing limits on CPU time, memory, file size, process creation and wall-clock time. The code cannot read the task banks, the run directory, the project or any home directory, see the process environment, reach the network, or see or signal another process, and the expected values never enter it: the verdict is reached outside. Running without isolation is a named choice for machines without bubblewrap, never a fallback; where bubblewrap is missing or fails, assessment raises.
