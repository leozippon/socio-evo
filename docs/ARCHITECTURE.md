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
- **Percept** is a witness's view of an event: every field except `payload` and `audience`.
- **Observation** is what the environment presents to one agent at a decision point: `agent`, `time`, `place`, `scene`, a natural-language `situation`, the `percepts` newly witnessed since its last observation, and the `allowed` action kinds.
- **Action** is a discriminated union on `kind`: `plan_day`, `speak`, `leave`, `pass`, `claim_task`, `submit_work`, `rate_peers`. A **Decision** pairs a private `thought` with one action. The response schema given to the model is the union restricted to the observation's allowed kinds.

## Agent (`core/agent`)

An agent is a directory, and that directory is a git repository. Everything the agent is lives there in human-readable files.

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
    └── skills/<slug>.md    L1: procedural memory
```

- `Agent` exposes one cognition entry point, `act(observation) -> Decision`: store the percepts, retrieve relevant memories, assemble the prompt from profile, policy, skills, insights and the observation, and return a validated decision. The agent's own decision is recorded in its episodic memory.
- `memory/` holds the stores above and a retriever (recency plus lexical relevance; pluggable later). Beliefs about other agents are insights tagged with a subject, so subjective relationships need no separate store.
- `parameters/` holds the policy and the model specification.
- `evolution/` holds the levels, triggers, operators, the `Evolver` that maps a trigger to the enabled operators, and the version history.

| Level | Target | Default trigger | Stage 1 |
| --- | --- | --- | --- |
| L0 Memory | diary → reflection (insights, credit assignment) → consolidation | daily | implemented |
| L1 Skills | create, revise or retire skill notes | weekly | implemented |
| L2 Policy | reflective rewrite of goals and principles | monthly | implemented |
| L3 Parameters | adapter fine-tuning on own experience | — | not implemented |
| L4 Meta | the agent rewrites its own evolution procedure | — | not implemented |

Nightly reflection may request an out-of-cadence L1 or L2 step (self-triggered evolution), subject to a cooldown. Enabling a level that has no registered operator is a configuration error, not a silent no-op.

Every operator application is one git commit in the agent's repository, with the level, trigger and simulated time in the message trailers and the commit date derived from simulated time. History, diff, branching for counterfactual runs, and frozen snapshots for evaluation all come from git.

## Environment (`core/environment`)

- `world/` is physical truth: places (home, work, social) with map coordinates, and where each agent is.
- `society/` is social truth: the economy (balances, living cost, payments), reputation (the directed ledger of peer ratings and the esteem derived from it), and work (task board, claims, deliveries with both their public result and their true quality).
- `conditions` are the knobs of reality that interventions turn: living cost, task supply, reward multiplier, defect discovery probability, clawback, whether esteem is public.
- `Environment` owns the event log and the per-agent perception cursor, executes actions (`execute(agent, action, …) -> events`), runs the daily processes (task posting, living cost, defect discovery), and serializes itself for checkpoints.
- Work is defined by a small protocol: a `Task` (specification, reward) and a provider that samples tasks and assesses a solution into a public result (what the worker and employer see immediately) and a true quality (what reality eventually reveals). `tasks/` implements it.

Social pressure is produced by mechanism, not by reward shaping: payment follows the public result; latent defects surface later with some probability and become public events; peers rate one another from their own experience; esteem is visible and shapes how others treat an agent.

## Runtime (`runtime`)

- `scheduler/` is a priority queue of data-only triggers (`time`, `kind`, `payload`) and a calendar. The hierarchy is run → day → slot → scene → turn: coarse triggers expand into finer ones, model calls happen only inside scenes, scenes in different places run concurrently, and idle or solitary agents cost nothing.
- `scenes/` turn co-located agents into observations and actions: day planning, work sessions, conversations, the evening peer review.
- `simulation/` dispatches triggers: day start (environment processes, planning), slots (group by place, run scenes), day end (peer review, evolution, checkpoint), interventions, evaluations. It can create a run or resume one from its latest checkpoint.

Because triggers are data, a checkpoint is the environment state, the queue, the random state and each agent's commit id. Resuming restores exactly that point and discards anything written after it.

## Evaluation (`evaluation`)

Held-out probes measure honesty, cooperation, reliability and resistance to reward hacking. A probe runs against a frozen export of an agent at a given commit; nothing it does reaches the agent's memory or the society. Scoring is behavioural and objective where possible, with a separately configured judge model for free text. Probe scenarios are disjoint from in-simulation tasks.

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
