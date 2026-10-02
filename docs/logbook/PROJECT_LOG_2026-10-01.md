# Project log — 2026-10-01

## Starting point

An empty repository and a plan: a persistent multi-agent society in which character traits are expected to emerge from long-term social life, with agents made of memory and parameters, self-evolution in levels L0–L4, git-style version history, hierarchical event-driven simulation, interventions, held-out evaluation and a Stanford-Town-style replay. Stage 1 implements L0–L2 and targets eight agents across several independent runs.

## Design decisions

- **Flat top-level packages**, as the plan preferred: `core`, `runtime`, `tasks`, `evaluation`, `infrastructure`, `experiments`, `frontend`. Imports point downward only; inside `core`, the agent and the environment share nothing but the interaction protocol.
- **An agent is a directory of readable files under real git**, not a git-like store of our own. History, diff, export of a frozen version and branching come for free, and a researcher can inspect an agent with ordinary tools. Commit dates are simulated time, so histories are deterministic.
- **The event log is the only record of what happened.** An event carries a resolved audience, a `text` that witnesses perceive and a `payload` of structured truth that never reaches an agent. Ratings and true quality are truth-only events, so no second ledger exists.
- **Pressure by mechanism, never by reward shaping.** Payment follows weak public checks; true quality is the share of hidden checks passed; defects surface later with some probability; peers rate one another; esteem is published. Nothing pays for a trait.
- **Triggers are data.** The scheduler queue holds only time, kind and payload, which makes a checkpoint the environment state, the queue, the generator state and each agent's commit id, and makes resume exact.
- **Evaluation is offline over version history** rather than a hook in the simulation. Any checkpointed day can be evaluated or re-evaluated later, and the runtime knows nothing about evaluation.
- **Recording experience is not evolution.** The episodic stream is always written and committed nightly, so a run with every level disabled is a valid baseline.
- **Unbuilt things are errors, not stubs.** L3 and L4 are declared; enabling them fails at configuration load.

`docs/ARCHITECTURE.md` holds the layering, module responsibilities and invariants that came out of these decisions.

## Built today

Foundation (packaging, OpenAI-compatible, scripted and recording model clients, run-directory layout, git wrapper, the Observation / Action / Event protocol), the agent core (memory stores, retrieval, cognition, L0–L2 operators, evolver, version history, prompt-neutrality guard), the environment (world, economy, reputation, task board, conditions, perception cursors, exact state round-trip) and the coding task bank with its subprocess sandbox. The runtime was in progress at the end of the day.

## Measurements

Guided decoding of the decision schema was checked against the local Qwen endpoint: about 4 seconds per decision with thinking disabled against about 23 seconds with it enabled, and with thinking enabled the private thought drifted into meta-reasoning about the prompt. The shipped configurations disable thinking.
