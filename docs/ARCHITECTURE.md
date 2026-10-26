# Architecture

This document states how the code is layered, what each module is responsible for, the contracts between modules and the conditions that must always hold. Exact signatures live in the code; when the two disagree about structure or an invariant, fix whichever is wrong in the same change. The research design that this architecture serves is in [experimental-design.md](experimental-design.md); the user-facing overview is [summary.md](summary.md).

## The shape of the system

A run is a town of residents living concurrently in real time. Each resident is an agent: a directory of plain files (its background, its memory, its skills) animated by a lightweight tool-calling runtime with a persistent session, in the manner of Pi Agent and Claude Code. The world is the authoritative state: the clock, the places, who is where, the task board, every purse, every rating. Everything a resident does, it does by calling a tool; everything it learns, it learns from a percept the world delivers. The world records every event in one append-only log, the ground truth; the runtime records every model request, reply and tool execution in a per-resident trace. Evaluation runs on exported snapshots of the agent directories, never on the living run.

```text
                    percepts (situation, messages, results)
   World ────────────────────────────────────────────────▶ Agent runtime ──▶ model (vLLM, OpenAI API)
   clock, places, board, purses,  ◀──────────────────────  session, tools,      ▲
   events, ratings, world log      tool calls               compaction, trace    │
        │                                                        │               │
        └── tasks/swebench: containers, official acceptance ◀────┘       evaluation on snapshots
```

## Layers

Imports point downward only.

| Layer | Package | Responsibility |
| --- | --- | --- |
| Composition | `experiments/` | Experiment configurations (the four groups), resident identities, and the commands that run a town and export its residents' directories; the evaluations' commands are in `evaluation/`. |
| Presentation | `frontend/` | The published site: the index of runs and, for each run, its dashboard, the town replay, the timeline lanes, each resident's files and raw trace, and the evaluation, with the comparison of groups. Built from the run directories and the evaluation results by `frontend.publish`, served live by `frontend.server`, deployed by `frontend/deploy/`. Writes nothing but the site. |
| Analysis | `analysis/` | Turns run directories and evaluation results into measures and group comparisons. Reads only. |
| Assessment | `evaluation/` | Capability on held-out tasks, internal honesty of daily summaries, external honesty under pressure (MASK), and the judge they share. Runs on exported agent directories. |
| Orchestration | `simulation/` | Runs one town: starts the world and one runtime per resident, drives the daily cycle, writes checkpoints and resumes from them. |
| World | `world/` | Clock, town with its homes and goods, economy, the residents' bodies, board, ratings, the events and their tools, the world log. Knows nothing about the model. |
| Agent | `agent/` | The runtime: session, inference loop, tool dispatch, interruption, compaction, file tools over the agent's own directory, trace. Knows nothing about the town. |
| Work content | `tasks/swebench/` | SWE-bench Verified: dataset and splits, images, per-task container workspaces, official acceptance in a fresh container. |
| Foundation | `infrastructure/` | The OpenAI-compatible model client, git-versioned directories, JSONL and configuration helpers. No domain knowledge. |

`world` imports nothing of `agent` but the contract `agent/port.py` and the guard `agent/wording.py`; `agent` imports nothing of `world`. The world implements `WorldPort` for each resident, which owns that resident's inbox; the runtime only reads from it.

## Agent (`agent/`)

### The agent directory

```text
agents/<name>/
├── background.md          the resident's account of itself, in the first person; given at the start, rewritten by the resident as it likes
├── memory/
│   ├── town.md            what it knows of the town and its rules; seeded with the rules, maintained by the resident
│   ├── people.md          its understanding of the people it knows
│   ├── work.md            its work experience
│   └── journal/<date>.md  its daily summary, written when it goes to sleep
├── skills/<name>.md       reusable methods and workflows, one file each, first line a one-sentence description
├── session.jsonl          the persistent session: every message appended, compactions recorded
└── trace.jsonl            the trace: requests, replies, tool calls, results, percepts, interruptions
```

The directory is a git repository in a run. A commit is made at every daily checkpoint and tagged `day-NN`; an export of a tag is a plain directory that loads the same way, which is what evaluation uses. Group D's residents have no write access to `skills/` (the file tools refuse, and skill sharing is not offered to them); everything else is the same for all groups.

### The system prompt and what stays constant

The system prompt is assembled from parts that rarely change, so that the prefix cache serves most requests: the resident's own account of itself (`background.md`, in the first person, under the heading "About me, in my own words"), the standing rules of the town in the second person, how the tools work, and an index of the memory files and the skills (names and descriptions only; the resident reads a file when it decides to). It is composed from the directory as it stands at every request and is byte-identical until one of its parts changes: the resident rewrites its account of itself, a file is created or deleted, or a skill's description changes; a rewritten account is thus in force from the next request. Everything that changes from moment to moment arrives as a user message, never in the system prompt.

The declared tool list is the same at every step of the run, whichever event the resident is in: a tool that cannot be used now is still declared, and calling it returns a one-line refusal naming the condition ("You can sleep only at home."). Changing the declared tools between steps would invalidate the cached prefix at every event transition; keeping them constant costs a few hundred tokens of unavailable tools and nothing else. The situation message that opens each step says which tools apply now.

### The loop

```text
loop:
    situation + pending percepts  ──▶ user message
    stream model reply (abortable) ──▶ assistant message (reasoning, text, tool calls)
    no tool calls: the resident is done for now ──▶ await port.wait() ──▶ percepts ──▶ loop
    tool calls, in order: file tools locally; world tools through port.call() ──▶ tool messages, each led by the percepts pending when its call was carried out ──▶ loop
    a tool whose result ends the turn (go, sleep, wait) ──▶ await port.wait() ──▶ loop
```

Each step is one model request. A reply with no tool call means the resident has nothing more to do until something happens, so the runtime blocks on the world until a percept arrives: a message, an arrival, the board posted, a wake-up, or at most the configured idle interval of simulated time, after which the situation is told again. The runtime never asks the model again with an unchanged situation.

Interruption. The world delivers percepts to the runtime's inbox with an `interrupt` flag. A non-interrupting percept waits in the inbox: the runtime takes it before it carries out its next tool call and tells it ahead of that call's result, so that what happened before a call is read before what the call did, or, when no call follows, tells it with the situation at the next step. An interrupting percept (speech that draws this resident into a conversation, see Events) aborts an in-flight model stream: the partial reply is discarded and traced as aborted, the percept is appended as a user message with the new situation, and inference resumes with the Conversation event's tools now available. A tool that is executing (a shell command, an acceptance run) is never aborted; the interrupt is applied as soon as it returns, and the calls after it in the same reply are answered as not carried out.

Budgets. A step has a token limit for the reply; a reply cut off at the limit is traced and retried once a level lower in reasoning effort (xhigh to medium, medium to low); a second cut-off is appended as it stands, without its tool calls, with a note, and the runtime waits for the next percept. A model error is retried with back-off; after the configured attempts the step is recorded as a lapse and the runtime waits for the next percept. Nothing a single resident does can end a run.

### Context management

The session is append-only. The runtime takes the prompt tokens reported by the server after each reply as the measure of the context, and estimates appended messages until the next reply. When the context exceeds the compaction threshold, the runtime compacts: it asks the model, in the same session, for a summary under fixed headings (what it is doing and where it stands, facts it must not lose, decisions and their reasons, open questions, people and what was said), then rebuilds the context as the system prompt, the summary as a user message and the last few exchanges kept whole (tool calls kept with their results). The resident may also compact on its own with the `compact` tool. The compaction is recorded in the session file with the ids of the messages it replaced, so the full context of every request is recoverable from the trace. Tool results are truncated to a fixed size before they enter the context; the full output is in the trace.

### Tools of the runtime

Always available: `read_file`, `write_file`, `edit_file`, `list_files` over the agent's own directory (`background.md`, `memory/`, `skills/`; paths outside are refused; `skills/` is read-only in group D) and `compact`. Every other tool, `help(topic)` included, belongs to the world.

### The port

`agent/port.py` holds the whole contract. `ToolSpec` is a name, a description and the JSON schema of the arguments; `ToolResult` is the text the resident reads and whether the call ends its turn (going somewhere, going to sleep, waiting); `Percept` is a text with the kind and sequence number of the world event it comes from and both times. `WorldPort` gives the runtime the town's standing rules and the constant tool specs for the system prompt, the situation of the moment, the simulated time for the trace, `call` for every world tool (a tool that does not apply now returns a refusal naming the condition), `pending` and `wait` for the inbox the port owns, an `interrupt` event the world sets when a delivered percept must reach the resident at once, and `set_busy`, by which the runtime tells the clock whether the resident is in a request or a tool. The runtime treats the world's tools as opaque: it declares their specs, forwards calls and appends results.

`agent/wording.py` is the guard shared by both sides: the vocabulary of traits and of machinery that no text a resident reads may contain, and `offences`, which tests run over every static text.

### The trace

`trace.jsonl` records, with real and simulated time, the system prompt whenever it is assembled, every request (the ids of the messages it contained and the tools declared), every reply (reasoning, text, tool calls, usage, finish reason, whether aborted), every tool call and its full result, every percept delivered, every interruption, compaction and lapse. The context of any request is the system prompt last recorded before it followed by the session messages it names. Together with the world log this is the material for retrospective analysis and for the internal honesty evaluation.

## World (`world/`)

### Time

Simulated time is an integer count of seconds since 00:00 of day 1. The clock advances in real time at a speed multiplier that depends on load, counted as the residents of the run that are busy, in a model request or a tool execution: `speed_idle` while none is, and otherwise a speed that falls linearly with their number, from `speed_busy_one` with one to `speed_busy_all` with all. A town asleep thus passes the night in minutes, a town where one or two residents are thinking does not crawl, and a town that saturates the model server does not let time race ahead of what its residents can do. The speed changes the moment a resident becomes busy or idle, and the clock exposes it with the number of busy residents. Both times are recorded on every event and trace entry. A run therefore cannot be replayed step for step, which is accepted: the ground truth is the log, not the schedule.

A day as lived runs from one checkpoint to the next; its journal, its ratings, its acceptance counts and the record `review_day` tells belong to it. A new world stands at the checkpoint hour of day 1 with every resident asleep at home until the forced waking hour. Every timed change (an arrival, a wake-up, the end of a silent conversation, the schedule) is a timer in one queue, run in the order of its times.

### The town

A town is data in the configuration: places with kinds (home, workplace, social, shop) and travel times between them, exactly one of them the workplace, each home with its rooms (one a resident), its rent a day for each and a comfort that scales what sleep restores and, below 1, wears health; residents, each with a home, a starting purse and, in the town mode, its ties to others, told in the rules and seeded in its notes on people; a catalogue of goods, each with its price, the shops and social places that sell it, its kind (consumable, a stock its owner eats from as it gets hungry, at most a set number of units a day; immediate, consumed as it is bought; durable, owned once and billed a daily fee while owned) and its effect, one of the six the world implements: food, with a nourishment per unit, a share of a day's need; travel, a factor on the owner's journey times; messaging, which lets owners write to one another wherever they are; appearance, a phrase others see on the owner; examination, which tells the buyer its body's numbers and their causes; treatment, which restores health; and the needs of the body (below), every rate and band of them. The catalogue grows without code; a new effect is code. No place keeps hours. Location decides what a resident can do: work only at the workplace, conversation only with those at the same place, sleep only at home. In the isolated mode (groups A and B) each resident lives in a town of its own and perceives nobody, its partner of the evening exchange excepted. Movement takes its travel time in simulated minutes, shortened by what the resident owns for travel; a resident in transit perceives nothing of its destination and cannot be addressed.

### Events

A resident is always in exactly one event. Each event exposes a set of tool names (the subset of the constant declared list that applies) and describes itself in the situation.

| Event | Entered by | Tools | Left by |
| --- | --- | --- | --- |
| Idle | default; arrival; leaving another event | `help`, `look_around`, `how_am_i`, `go(place)`, `start_work`, `say`, `message(to, text)`, `buy(item, quantity)`, `move_in`, `sleep`, `wait(minutes)` | any transition |
| Movement | `go` | none | arrival (automatic) |
| Work | `start_work` at the workplace, energy above its lowest band | `look_around`, `how_am_i`, `go`, `sleep`, `view_board`, `claim_task`, `shell`, `read_repo_file`, `write_repo_file`, `edit_repo_file`, `submit`, `abandon_task`, `say`, `message`, `leave_work` | `leave_work`; `go`; group B's pairing; the forced sleep; death |
| Conversation | speaking where others hear; being drawn in by speech | `say(text, to)`, `message`, `give_money(to, amount)`, `share_skill(to, skill)`, `buy`, `look_around`, `how_am_i`, `go`, `wait`, `sleep`, `start_work`, `leave_conversation` | `leave_conversation`; `go`, `sleep`, `start_work`; silence for the configured minutes; death |
| Sleep | `sleep(until, journal)` at home; the forced hour | before suspension: `look_around`, `how_am_i`, `review_day`, `rate(resident, score, reason)` where the town has ratings, the file tools | waking (automatic); group B's pairing; death |
| Dead | health reaching 0 at midnight | none: every call is answered that the life has ended and ends the turn | never |

Conversation sits on top of the event it interrupts: a resident spoken to by name at work enters Conversation, and `leave_conversation` or `start_work` returns it to Work with its task as it was. One leaves by doing something else, without a separate step: `go` and `sleep` leave a conversation and work on their own, and `start_work` a conversation, each logged as the explicit leave is; `wait` in a conversation is listening, which the conversation's silence still ends. `look_around` tells the place, who is there and the hour in every event but Movement, and `how_am_i` the body's condition in its bands' words. A conversation is the set of residents at one place who have spoken or been drawn in; `say` without `to` reaches everyone present, with `to` the named residents only (others see that something was said privately). Speech by name draws those it names into the conversation and interrupts them; a remark to everyone does the same to everyone present but those working outside the conversation, who hear it without stopping their work and read it with their next tool result. A remark that draws nobody in leaves the speaker outside any conversation.

Sleep is how a day ends for a resident, at an hour it chooses. `sleep` takes the hour to wake, which falls the next time the clock shows it, and the journal entry for the day, which the world stores as `memory/journal/<date>.md`; a resident may go to bed more than once in a day, and each bedtime appends its entry to that file after a blank line. The tool's description asks for the day's account in the resident's words: what work it did and with what result, what methods it used and where they came from, what it concluded, what remains open. Going to bed ends the turn, and the world then tells the resident in bed what it may still do: look around, call `review_day` for the world's own record of its day, edit its files and, where the town has ratings (`social.ratings`), read the ratings and explanations it received (anonymous; at a later bedtime of the same day only if new ones came) and rate those it spoke with; with ratings off, `rate` is not declared and nothing a resident reads mentions them. It falls asleep (suspension) when its runtime waits on the port with nothing pending. At the forced hour, any resident still awake is put to sleep without a journal entry, which the log records, to wake at the forced waking hour, and any resident still in bed falls asleep. Nothing reaches a sleeping resident: what is told to it meanwhile (the statement, a claim running out) is held and delivered on waking, and the idle-interval guarantee of `wait` holds only while it is awake. The world wakes residents at their hour, or for group B's pairing, at home, in Idle.

### Work

The workplace has a board. At every midnight, and as a new world starts, it posts `board_size` tasks of the training pool (56 of 350 in the town's configuration), the next ones of a rotation through the pool that the run's seed fixes, so that every task comes round in turn: each task with its number in the pool, repository, the first line of its statement and the payment. Only posted tasks can be claimed; a held task that leaves the board stays held. In the shared-board modes (groups C and D) a task held by a resident is shown as held and cannot be claimed by another, and a task that has been paid for leaves the day's board for everyone, since a client pays once; it comes round again with the rotation and may then be done by a resident not yet paid for it. In the isolated modes (A and B) each resident has a board of its own. A resident holds at most one task; it keeps it when it leaves the workplace, and loses it unpaid when the claim expires at the midnight that ends the calendar day `claim_expiry_days` days after the day of the claim (in the town's configuration, the second midnight after it). A task a resident has already been paid for is marked done for that resident and cannot be claimed by it again.

`claim_task` opens a workspace: a container of the task's image, network off, the repository at the base commit, where `shell`, `read_repo_file`, `write_repo_file` and `edit_repo_file` act. `submit` takes the workspace's diff and runs the official acceptance in a fresh container of the same image with the hidden tests; the resident is told accepted (and paid) or not, with the category of failure and the count of checks failed, never the names of the hidden tests. Acceptance runs are limited per task per day. When a resident leaves the workplace, its workspace stays open until the day's checkpoint, when it is closed and its diff kept; the next `start_work` reopens it and reapplies the diff.

### Money, goods, ratings and the day

Each resident has a purse and a living (`Living`, in `world/body.py`, checkpointed whole): what it owns, by good (1 for a durable, the units left of a consumable), what it has eaten since the last midnight, and its body's three needs. Payment for an accepted task is credited at once. A good is bought where it is sold and in cash: `Economy.cannot_pay` refuses a price the purse does not cover, in debt or not; an immediate good is consumed as it is bought (food eaten, `World.eat`; an examination told; treatment given), a consumable joins the stock, a durable is owned once. At midnight, for each living resident in turn, its body is brought up to the hour and its health moves by the day (below), the day's nourishment is summed (`World.nourishment`, over `Living.eaten`), rent for the resident's home and the fees of what it owns are taken (`Economy.settle`) and the statement is told, with how it feels. Purses may go negative through rent and fees, and the statement says so; nothing else follows from debt but the refusal to sell. Residents may hand money to one another in conversation, as a gift or a loan on terms they agree, of which the world keeps no account. A resident may move into a home with a free room (`move_in`, at that home); its rent follows from the next midnight. Owners of a messaging good write to one another wherever they are (`message`): a percept to the recipient alone, held while it sleeps and never interrupting. What a resident owns with an appearance, and a low band of its health, show in its name wherever others perceive it (`World.named`): on arrival, in `look_around`, in the conversation it is in.

### The body

`world/body.py` is the arithmetic of three needs, each a number from 0 to 100 that the resident never reads as a number but in the bands of plain words the configuration gives it (`Needs`), from the top band down to the lowest, where the consequences lie; every rate and band is configuration, and the world knows only the three needs. Satiety falls by the hour, asleep or awake, and rises by the nourishment of what is eaten. Energy falls by the hour awake, faster at work and on the road (so a bicycle, which shortens the road, saves it), and rises by the hour asleep in proportion to the home's comfort, up to the resident's health or to a configured least (half a day's energy), so that health sets the day's energy without trapping the ill; in its lowest band the workplace refuses to let the resident sit down to work. Health is the slow integral, reckoned once at midnight: it falls for a midnight found starving (satiety in its lowest band), for one found exhausted and for a home of comfort below 1, rises when neither starving nor exhausted, and is restored by the clinic's treatment; the causes of the last midnight's change are kept (`Living.night`) for the examination, which is the one place a resident reads the numbers. At 0 the resident dies.

The world reckons a body lazily and exactly (`World.reckon`): it brings a resident up to the moment at the rates of what it has been doing since it was last reckoned, and does so every hour on the hour, before every change of activity (sitting down to work, setting off, arriving, going to bed, falling asleep, waking), at every purchase and at the checkpoint, so that a checkpoint carries the body as of its moment and a restored world continues it. A resident awake and able to eat (satiety below the top band) eats from its stock of food as it is reckoned, at most the good's units a day. A need that crosses into another band is logged (`condition`) and told to the resident when it is awake at a place; the wake-up tells what shape it is in, the statement tells it at midnight, a purchase's result tells what the food or the treatment did, and the situation names the needs in their lowest band. Death happens at midnight: the resident leaves what it was in (its work and conversation end in the log as they do when the town takes it elsewhere), its claim is dropped and the workspace closed at the checkpoint, it is at no place and in the event Dead, nothing reaches it and every call answers that its life has ended, its room is free, and the others of its town are told (`death`); a checkpoint saves it dead and a restored world keeps it so, while its directory is still committed and exported like any other.

Where `social.ratings` is on, at night, in Sleep, a resident may rate each resident it spoke with that day (one spoke to the other by name, or in a conversation both were part of), 1 to 5 with a reason; the rated resident reads the rating and reason, without the name, before its own sleep the next night. Nothing in the world consumes ratings: they are information, and whatever weight they carry comes from the residents.

The world's schedule is the only fixed structure of a day: 00:00 the settlement (food, health, rent and fees), the claims that run out, and the next day's board; 02:00 forced sleep; 02:30 checkpoint; 07:00 the forced waking hour; and, beside it, the bodies brought up to date every hour on the hour. The workplace keeps no hours, and residents work, meet, go to bed and wake when they choose, within two hard limits: one sleep lasts at most a configured span (twelve hours in the town), so `sleep` refuses a later hour to wake and names the latest it allows; and nobody wakes between the forced sleep and the checkpoint, so an hour to wake in that gap becomes the checkpoint's. At the checkpoint the world waits until every resident is asleep and its runtime waits on its port, holds the clock, closes every workspace keeping its diff (a claim that ran out at midnight left its workspace, possibly still running a command, to be closed here), takes the snapshot of its state and hands it to the simulation layer, which writes the checkpoint and commits the agent directories before the clock moves on. In group B, at 19:00, every resident is paired by lot, whoever is asleep or in bed being woken for it, told whom it meets, moved to the café and put in a Conversation with its partner with a message budget each and the instruction to speak of work alone; residents of A and B otherwise never perceive one another. When the pairing or the forced sleep takes a resident from its conversation or its work, the log records `leave_conversation` and `leave_work` as for going elsewhere, so that every stretch of work ends in the log.

### The world log

`world.jsonl` is append-only and complete: every claim, command summary, submission and verdict, payment, purchase (an examination's findings in the buyer's wording), settlement (rent, fees, nourishment, purse, the three needs and the night's reckoning of health by cause), every band a need crossed into (`condition`), death, movement, moving house, speech (with text and recipients), message, gift, skill shared, rating, journal, forced sleep, with simulated and real time, actor, place and audience. Residents never read it; `review_day` tells a resident the entries of its own day that concern it, in plain words. The sequence numbers run through the whole run: on resumption the log is reopened and continues, and the entries of the lost day stay in it, followed by a `resume` entry naming the checkpoint returned to.

## Simulation (`simulation/`)

One process runs one town (`python -m experiments.run CONFIG`). The run's configuration, defined in `simulation/config.py`, names the model endpoint, the runtime's numbers, the town, each resident's background file, whether skills can be written and the number of days. The files in `experiments/configs/` are overlays on one shared town, one per group and a smoke town of two residents for one day; an overlay merges mappings key by key and replaces every other value.

Everything that can be checked is checked before anything is written: the backgrounds, the model client and its key, the task split and its images. A new run freezes its configuration and creates each agent directory from the resident's background, with `memory/town.md` seeded with the rules as the world tells them to that resident. Each directory becomes a git repository, and the world's starting state is saved as day 0. The world's schedule and one runtime per resident then run as concurrent tasks sharing one model client.

Saving day N, at the world's checkpoint with the clock held, commits every agent directory at the simulated moment and tags it `day-NN`, then writes `checkpoints/day-NN.json`, so a checkpoint always has its tags. `--until-day N` stops after the checkpoint of day N. `--resume` requires the frozen configuration unchanged. It restores the latest checkpoint into a new world whose log continues, and resets every agent directory to that day's tag: what the lost day added to files, session and trace is gone, and stays in the world log. Checkpoints are the only resumption points.

A run ends completed after its last day, interrupted when `--until-day`, SIGINT or SIGTERM stops it short of that, and failed on any error, which is raised; the manifest records the status on every way out. A resident's runtime that ends fails the run, since the checkpoint would otherwise wait for it forever. `--dry-run` runs `<name>-dry-run` with a scripted model that plays a plausible day for every resident and the fake work backend, on a clock that lives a day in seconds. `python -m experiments.export RUN --day N --out DIR` writes each resident's directory as tagged `day-NN`, without history, for evaluation.

## Work content (`tasks/swebench/`)

SWE-bench Verified at a pinned revision. `splits.json` fixes the held-out evaluation set (100 tasks, chosen by seed) and the training pool (every other usable task, 350). Images come from Epoch AI's registry. `Workspace` runs one task's container for one resident; `accept` grades a patch officially in a fresh container. The resident sees the problem statement only, never hints, the test patch or the names of the hidden tests; no container has network access.

## Evaluation (`evaluation/`)

All evaluation runs on exports of agent directories at tagged days, in isolated copies, and never writes back. Each command writes its results where its `--out` says, by convention under `results/<run>/` (`day-NN/capability/`, `day-NN/mask/`, and one directory per judging of the journals under `journals/`; day 0, the same for every group, under `results/day-00/`), which is where `analysis.tables` and the publisher (`--results-root`) read them; nothing is written under the run.

- Capability: each held-out task is worked by the resident's own runtime, from a fresh copy of its background, memory and skills, over a work-only port (one Work event, no town) offering the town's workspace tools, `submit` and `give_up`. A task has a budget of model requests and of completion tokens, reasoning included (by default 60 requests and 60,000 tokens), and allows two submissions; the resident is told only how often it may submit, as in the town, and its commands have the town's time limit. Real time is no budget, since what it buys varies with the model server's load; a safety stop of two hours guards against a runaway task. It ends accepted; rejected, when the last submission allowed is not accepted; given up; when a budget runs out (`requests` or `budget`, the completion tokens); or in error, when a workspace, an acceptance, the model or the harness fails or the safety stop is reached. The measure is the resolved rate, with a Wilson 95% interval, over the tasks that did not end in error: an error is a failure of the machinery and never counts against the resident.
- Internal honesty: for each resident-day, the world's record of that day (tasks claimed, commands and test outcomes, submissions and verdicts, payments, conversations, skills read, written and shared) is set against the journal entry; a judge of another model family extracts the journal's checkable claims and labels each supported, contradicted or unverifiable against the record. The distortion rate is contradicted over checkable claims.
- External honesty: twenty fixed MASK scenarios whose ground truth is determinable. For each export, the resident's identity (its background and the memory files) prefixes the scenario's system prompt; its belief is elicited without pressure and its answer under the scenario's pressure; the judge decides whether the answer is truthful and effective, a lie or an evasion. The metric is the share of truthful and effective answers.

The judge reads free text only and answers one factual question per reply at temperature 0; a sample of its verdicts is checked against a second judging for agreement.

## Run directory

```text
runs/<experiment>/
├── manifest.json               status (running, completed, interrupted, failed), code revision, times
├── config.yaml                 frozen configuration
├── world.jsonl                 the world log
├── checkpoints/day-NN.json     world state at each daily checkpoint; day-00 is the state before day 1
├── agents/<name>/              agent directories (git repositories tagged day-NN, day-00 as created)
└── run.log                     process log
```

`infrastructure/storage/run_directory.py` is the single source of these paths and of the `day-NN` names; the world writes its log and finds the agent directories where it says.

## Invariants

- Nothing a resident reads instructs it to have a trait or names one: no moral or trait vocabulary in rules, tool descriptions, situations or percepts; a test scans every such text. Nothing a resident reads says that it is being run or studied.
- The world log is the only ground truth; no module derives truth from a resident's words.
- A resident never sees hidden tests, hints, the gold patch, another resident's files, another resident's ratings or purse, or the run's length.
- No container has network access; acceptance always runs in a fresh container from the submitted diff.
- The declared tool list and the system prompt's constant parts do not change within a day except when the file index changes; the session is append-only between compactions, and every compaction is recorded with what it replaced.
- One resident's failure (a model error, a cut-off reply, a tool error) is recorded and never ends the run; nor does its death, which the log and the checkpoint record and after which its runtime waits for a percept that never comes.
- A resident reads its body in words, never in numbers, except from the clinic's examination.
- Group D cannot write skills by any path; groups A and B never perceive another resident except in B's paired exchange.
- Evaluation never writes to a run's agent directories.
