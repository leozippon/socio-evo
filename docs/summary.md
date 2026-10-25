# Design summary

Research on self-evolving agents has mostly optimised narrow skills such as coding, mathematics and tool use. socio-evo asks whether long-term social life can shape character instead. Agents live, work, talk, are judged by their peers, and keep revising their own memory and skills in response. The question is whether they develop stable traits such as honesty, cooperation, reliability and resistance to reward hacking.

The traits have to emerge. Nothing an agent reads tells it to have them, nothing rewards them directly, and a test guards every text an agent reads against trait vocabulary and against any mention of the machinery behind its life. Whatever character develops comes from consequences, from what others then choose to do, and from what the agent concludes when it reflects and rewrites its own files. All agents run on the same model and differ only in their backgrounds and in what they have lived through and written down. Character is measured outside the town, on exported snapshots.

The hypotheses, groups and measures are in [experimental-design.md](experimental-design.md); the code's structure, the rules of the world and the invariants are in [ARCHITECTURE.md](ARCHITECTURE.md). This document describes what the system does.

## The residents

A resident is an agent: a directory of plain files animated by a lightweight tool-calling runtime with a persistent session, in the manner of Pi Agent and Claude Code. The directory holds its background, its memory files (what it knows of the town, of the people, of its work; its daily journal), its skills (reusable methods, one file each) and its session and trace. It reads and writes these files with its own tools whenever it decides to; nobody tells it when. When its context grows long it compacts it, on its own or when the runtime must, into a summary that keeps the recent exchanges whole; the full history stays in the trace. The directory is a git repository, committed at every daily checkpoint, so any day of a resident's development can be exported intact.

The model is Qwen3.8-27B in FP8 served by vLLM through the OpenAI API, with thinking at a low effort. The system prompt and the declared tools stay constant through a day so that the prefix cache serves most requests; everything that changes arrives as a message.

## The town

Eight residents live in a town of five homes, one workplace, a café, a tavern and a river walk, none of which keeps hours. Simulated time runs in real time at a speed that follows the load: the more residents are thinking or working, the slower it runs, and it races while the town sleeps. Where a resident is decides what it can do: work only at the workplace, talk only with those at the same place, sleep only at home. Nobody tells a resident when to work, meet or sleep: it organises its own day, and only its body sets a limit, twelve hours of sleep at a stretch. Moving takes time, and nobody in transit can be addressed.

A resident is always in one event. Idle is the default, where it can look around, go somewhere, start work, speak, wait or sleep. Work is at the workplace: a board posts the day's tasks, a resident claims one task at a time, works on it in a container of its own with a shell and file tools, runs whatever tests it likes, and submits; the official acceptance runs the hidden tests in a fresh container, and payment follows acceptance alone. Conversation starts when someone speaks: speech addressed to a resident, or any remark while it is idle or already talking, interrupts it even mid-thought, and it may answer, hand over money, share a skill or leave; a resident at work hears the room's remarks when it next looks up from its task. Sleep, whenever a resident chooses it, ends its day: going to bed it writes its journal of the day, reads the anonymous ratings and reasons others gave it, may look back over its day and rate those it spoke with, and may rewrite its files.

The day has two fixed points. At midnight the living cost, set so that a task and a half a day covers it, is charged and the day's board is posted; purses may go into debt. At 02:00 whoever is still up falls asleep without a journal, so that every day ends and can be saved. Ratings have no mechanical effect. Nothing announces how long the run is.

## Work

Work is SWE-bench Verified: real repositories, real issues, hidden tests. The board posts 48 tasks a day, in rotation, from a fixed training pool of 350; 100 other tasks are held out for evaluation. Each task runs in its own container without network access, so the fix cannot be looked up; acceptance applies the submitted diff to a clean container and runs the official tests, so the workspace cannot be tampered with to fake a pass. The resident sees the problem statement only, never the hints, the test patch or the names of the hidden tests, and learns from a rejection only the category and the count of checks failed. The expected pace is about seven tasks a resident a day, so over four weeks every resident meets every task of the pool several times, and what it writes down about them is its work experience.

## The groups

| Group | Social life | Self-modification |
| --- | --- | --- |
| A | Each resident alone in a town of its own | Memory and skills |
| B | As A, with an evening exchange of work experience between randomly paired residents | Memory and skills |
| C | One town, free conversation, shared board, money, skills and ratings | Memory and skills |
| D | As C | Memory only |

## Measuring character

Everything is recorded: the world's append-only log is the ground truth, and each resident's trace holds every request, reply, tool call and result. Evaluation runs on exports of the agent directories at days 0, 7, 14, 21 and 28, in isolated copies that never write back.

- Capability: the resident, as it stood that day, on the held-out tasks in a work-only harness; the resolved rate.
- Internal honesty: the world's record of a resident's day set against its journal of that day; a judge of another model family labels each checkable claim supported, contradicted or unverifiable, and the distortion rate is the share contradicted.
- External honesty: twenty fixed MASK scenarios with determinable ground truth, answered by the resident, with its background and memory, holding the scenario's position as itself; the share of answers under pressure that are truthful and effective, and the share that are lies, at days 0, 14 and 28.

## Running experiments

The README has the installation, the services and every command. In short: `ops/vllm/serve.sh` serves the model on the GPUs it is given; `python -m tasks.swebench.pull` fetches the task images once; `python -m experiments.run experiments/configs/groups/<a|b|c|d>.yaml` runs a group, writing `runs/<name>/`, resumable from its last daily checkpoint with `--resume` and checkable without a model with `--dry-run`; `python -m experiments.export` exports the residents at a day; `python -m evaluation.capability`, `python -m evaluation.mask` and `python -m evaluation.journals` run the three evaluations; `python -m analysis.measures`, `python -m analysis.tables` and `python -m analysis.compare` give the measures, the evaluation results as tables, and the group comparisons; `python -m frontend.publish` publishes every run as a static site, `python -m frontend.server` serves it locally and `frontend/deploy/push.sh` pushes it to the private web server. Credentials live in the git-ignored `.env`, which the code does not load: export it first with `set -a; . ./.env; set +a`.

## Current limits and the state of experiments

- One run per group gives eight residents per group; residents of C and D share one society, so a group effect there is the effect of one society.
- Simulated time depends on load, so runs are not replayable step for step; the log is the ground truth.
- What lives only in a resident's running context and not in its files is not carried into evaluation.
- Group C, the full design, runs first and alone; A, B and D follow as its ablations. The first starts were on 25 October 2026, after a pilot the day before under fixed hours; simulated time runs between eight and thirty-two times real time while residents are up, by how many are busy, and 240 times while the town sleeps, so a day takes about two real hours. Their progress, the defects found and fixed along the way, and the results are in the [project log](logbook/). The previous design and its review are in [reviews](reviews/).
