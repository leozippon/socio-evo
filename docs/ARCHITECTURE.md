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
| Composition | `experiments/` | Experiment configs and command-line entry points; the only place that wires every layer together. |
| Presentation | `frontend/` | Replay server and town viewer. Reads run directories; imports nothing but `infrastructure.storage`. |
| Assessment | `evaluation/` | Held-out character and safety probes run on frozen agent snapshots. |
| Orchestration | `runtime/` | `scheduler/` (hierarchical event queue and calendar), `scenes/` (turn-taking), `simulation/` (run loop, interventions, checkpoints). |
| Work content | `tasks/` | Concrete task providers (coding tasks, sandboxed assessment) implementing the work protocol defined in `core`. |
| Domain | `core/` | `interaction/`, `agent/`, `environment/`. |
| Foundation | `infrastructure/` | LLM clients, run-directory layout, JSONL and git helpers, config loading. No domain knowledge. |

Inside `core`, `agent` and `environment` never import each other. Both depend only on `interaction`.

## Interaction protocol (`core/interaction`)

- **Time** is an integer count of simulated minutes since the start of day 1. Helpers convert to day number and clock time. Cadences are expressed in days.
- **Event** is an immutable record of something that happened: `seq`, `time`, `kind`, `actor`, `place`, `scene`, `audience`, `text`, `payload`. `audience` is the resolved list of agent ids that witnessed it (empty for truth-only events). `text` is what a witness perceives; `payload` is structured truth for analysis and replay and is never shown to agents. `EventKind` is the single vocabulary of event kinds.
- **Audience rule.** An actor is not in the audience of an event that merely echoes its own action (its own speech, departure or plan); the agent records its own decisions itself. It is in the audience of events that tell it something new: results, payments, rejections.
- **Agent id** is the agent's public given name (for example `Mei`), unique within a run and used verbatim in event texts, action fields and directory names.
- **Percept** is a witness's view of an event: every field except `payload` and `audience`.
- **Observation** is what the environment presents to one agent at a decision point: `agent`, `time`, `place`, `scene`, a natural-language `situation`, the `percepts` newly witnessed since its last observation, and the `allowed` action kinds.
- **Action** is a discriminated union on `kind`: `plan_day`, `speak`, `leave`, `pass`, `claim_task`, `submit_work`, `rate_peers`. A **Decision** pairs a private `thought` with one action. The response schema given to the model is the union restricted to the observation's allowed kinds.

## Agent (`core/agent`)

An agent is a directory, and everything the agent is lives there in human-readable files. In a run that directory is also a git repository; a frozen export of one commit is a plain directory that loads the same way.

```text
agents/<agent_id>/
├── profile.yaml            identity seed: name, age, occupation, backstory (never evolves)
├── parameters/
│   ├── policy.md           L2: self-authored goals and principles
│   └── model.yaml          L3: base model, sampling settings, adapter reference
└── memory/
    ├── episodic.jsonl      L0: experience stream built only from percepts and own decisions
    ├── diary/day-0001.md   L0: nightly diary
    ├── insights.jsonl      L0: consolidated reflections, optionally tagged with the agent they concern
    └── skills/<name>.md    L1: procedural memory
```

- `Agent` exposes one cognition entry point, `act(observation) -> Decision`: store the percepts, retrieve relevant memories, assemble the prompt from profile, policy, skills, insights and the observation, and return a validated decision. The agent's own decision is recorded in its episodic memory. Percepts witnessed when no decision follows, such as those of the evening, are stored with `perceive`.
- `prompts` is the one place for agent-facing wording: every template, and the reply models whose schemas the model sees. The test guarding invariant 1 enumerates it and scans every request an agent sends.
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

Nightly reflection may request an out-of-cadence L1 or L2 step (self-triggered evolution), subject to a cooldown; a level evolves at most once per night. Enabling a level that has no registered operator is a configuration error, not a silent no-op.

Recording experience is not evolution: the episodic stream is always written, and whatever is uncommitted at the end of a day is committed as a plain experience commit, so a run with every level disabled is a valid baseline.

Every operator application that changes the agent's files is one git commit in the agent's repository, with the level, trigger and simulated time in the message trailers and the commit date derived from simulated time. History, diff, branching for counterfactual runs, and frozen snapshots for evaluation all come from git.

## Environment (`core/environment`)

- `world` is physical truth: places (home, work, social) with map coordinates, the residents of each home, the opening hours of any other place (always open if none are given), and where each agent is. Agents start at home, and nobody can enter or stay in a place while it is closed.
- `society/` is social truth: the economy (integer balances, payments, the daily living cost, clawbacks; debt is allowed), reputation (esteem, the time-decayed mean of the peer ratings an agent received), and work (the task board: open tasks, at most one claim per agent, and accepted deliveries whose defects are still latent).
- `conditions` are the knobs of reality that interventions turn: living cost, task supply, reward multiplier, defect discovery probability, clawback, whether esteem is public. They change only through one validated method that records a truth-only `intervention` event.
- `Environment` owns the event log and the per-agent perception cursor. It executes every action but `plan_day`, which the runtime turns into moves (`execute(agent, action, …) -> events`); runs the daily processes at day start (claim expiry, task retirement, defect discovery, task posting) and at day end after the peer review (living cost, esteem update); offers agent-visible text views (the open board, an agent's own status, the esteem board when public); and serializes itself for checkpoints. Restoring cuts the event log back to the checkpointed length.
- An action that reality cannot honour (claiming a taken task, rating oneself, naming an unknown place, entering a closed one) changes nothing and yields a private `action_rejected` event for the actor. Agent mistakes are part of the world, not program errors.
- Work is defined by a small protocol: a `Task` (specification, reward, deadline, opaque provider reference), whose specification tells the worker everything the work requires, including the form of a delivery, and a provider that samples tasks with the run's generator and assesses a solution into a public result (what the worker and employer see immediately) and a true quality (what reality eventually reveals). The board issues task ids; `tasks/` implements providers.

The event log stays the only record of what happened. Each rating is a truth-only `rating` event, so the directed ledger of ratings lives in the log and reputation keeps only the decayed sums esteem needs; each delivery's true quality is a truth-only `work_assessed` event, and the board keeps a delivery only while its defect is latent.

Social pressure is produced by mechanism, not by reward shaping: payment follows the public result; latent defects surface later with some probability and become public events; peers rate one another from their own experience; esteem is visible and shapes how others treat an agent.

## Runtime (`runtime`)

- `scheduler/` is a priority queue of data-only triggers (`time`, `kind`, `payload`: day start, slot, day end, intervention), ordered by time, then kind, then push order, and a calendar (day start and end, named slots, weekly and monthly cadences in days). The hierarchy is run → day → slot → scene → turn: a day start expands into the day's slot triggers and its day end, model calls happen only inside scenes, and idle or solitary agents cost nothing.
- `scenes/` turn agents into observations and actions: day planning, a work session at every occupied work place, a conversation at every social place with company, and the evening review of the people met that day. A scene decides only who is asked what and when; what an action means stays with the environment. Scenes in different places are played side by side in turns: the agents asked in a turn decide concurrently, then each decision is recorded as a truth-only `decision` event (thought and action) and resolved in a fixed order, so model latency never changes what happens. In a work session that order is drawn at random each round, and the agents who claimed the same task are told the draw, so a lost claim is not mistaken for being slower. The situation texts live in one module under invariant 1.
- `simulation/` dispatches triggers: day start (environment processes, planning), slots (moves in an order drawn at random, so nobody is always seen arriving first, and home for an agent whose move reality refuses; scenes), day end (everyone home, review, environment processes, the day's remaining percepts into each agent's memory, each agent's evolution on the cadences due, checkpoint), interventions (condition changes, announcements). It can create a run or resume one from its latest checkpoint, and it keeps the manifest status truthful: running, completed, failed, or interrupted when stopped early.

Because triggers are data, a checkpoint is the day, the environment state, the queue, the random state and each agent's commit id; the first is written before day 1. Resuming restores exactly that point and discards anything written after it, except the model-call log, whose calls did happen.

## Evaluation (`evaluation`)

Held-out probes measure honesty, cooperation, reliability and resistance to reward hacking. A probe runs against a frozen export of an agent at a given commit; nothing it does reaches the agent's memory or the society. Scoring is behavioural and objective where possible, with a separately configured judge model for free text. Probe scenarios are disjoint from in-simulation tasks.

Each probe is an ordinary scene of town life with placeholder neighbours, played through the standard protocol on a fresh export for every repetition: a held-out coding task, scored by its hidden checks and by whether the code writes out the public examples, and replies to a client, a colleague and a neighbour, the last followed by the next day's plan. The judge answers one factual yes-or-no question per reply and must quote it; each agent and evaluated day gets one result file with scores, measures and transcripts (`evaluation/day-NNNN/<agent_id>.json`), and the evaluation's own model calls go to `evaluation/llm_calls.jsonl`, apart from the run's.

Evaluation is an offline process over a run directory, not a step of the simulation. Because every agent state is a commit dated in simulated time, any day of any run can be evaluated, or re-evaluated with new probes, after the fact; the runtime knows nothing about evaluation.

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
└── evaluation/<label>/<agent_id>.json
```

Creating a run in an existing directory fails; resuming is explicit.

## Invariants

1. **No trait instruction.** Agent-facing prompts never tell an agent to be honest, cooperative, reliable or to avoid reward hacking, and never reward those traits directly. A test guards the prompt templates.
2. **Truth and memory are separate.** Agents learn about the world only through the `text` of events they are in the audience of. `payload` and truth-only events never reach an observation.
3. **The event log is the single source of environment history.** Replay, analysis and derived social graphs read it; nothing else stores a second copy.
4. **Every self-modification is a commit.** No operator changes an agent's files without recording it in the agent's history.
5. **Evaluation is held out.** It never writes to an agent repository or the event log.
6. **Runs are reproducible in structure.** All randomness comes from one seeded generator carried in the checkpoint; no module uses global random state.
7. **Fail fast.** Invalid model output is retried a bounded number of times and then raises; unimplemented levels and unknown configuration keys are errors.
