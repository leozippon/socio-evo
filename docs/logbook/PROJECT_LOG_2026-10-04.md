# Project log — 2026-10-04

## Overview

The day replaced the first town with a second one, in answer to the [design review](../../archive/reviews/DESIGN_REVIEW_2026-10-02.md): first the experimental design, then the voice in which residents are spoken to, then the code. Six commits were made that day (e9c6333, 0c742fd, 60c959b, fca516c, 4657970, 296749d). The rest of the day's work, the runtime that survives an unreadable reply, the rebuilt probe battery, and the analysis of traits and studies with the viewer that shows them, was left uncommitted and was committed on 2026-10-12 as 5c0d25b and f421c28. It is recorded here because this is when it was done.

## Experimental design

`docs/experimental-design.md` (e9c6333) states what the experiment is meant to show. It tests three hypotheses: selection (when agents choose whom they work with, character holds up better than under random pairing with everything else equal), pressure (scarcity erodes character, and selection changes how much) and stability (what selection produces carries over to unseen situations, agrees across situations and persists after selection is switched off). The town is rebuilt around four dilemmas, one per trait, each with a cost now and a consequence later through other people: hard jobs whose visible checks are weaker than their specification, clients who pay on the worker's declaration, jobs for two with shared pay and liability, and crowns that residents can hand one another. The arms are selection, assignment, solo and no evolution, with pressure crossed with the first two and a late phase that switches partner choice and fault discovery off. The held-out probes are redesigned as several families per trait at graded stakes, scored from typed actions, with a judge of another model family, held-out and impossible coding tasks, and ablated exports as controls. A table records what was borrowed and from where, and what was considered and not adopted.

## Immersion

In the first pilot the residents knew they were being run: more than half of their private thoughts spoke of rounds, draws and "the system", one in ten named an action, and some spoke of "the prompt" and "my persona". `docs/IMMERSION.md` (60c959b, revised in fca516c) is the single source for the voice of everything a resident reads. Nothing reveals the machinery; the world is told in the second person as it is lived; every rule has an in-world form; memory is recollection; the nightly practices are a diary, beliefs, a notebook and resolutions; truth is never bent and neutrality still binds. A vocabulary maps the code's terms to the town's (credits to crowns, a task to a job by the number on its notice, a rating to a mark in the clerk's ledger), and the revision (fca516c) made it one voice throughout, the board a wall of numbered notices kept by a clerk who draws lots, and the reply an answer card in the town's words. The experimental design adopts the guide as a principle.

## Town v2

4657970 built the second town.

- **World.** Jobs of one or two parts; clients who try the examples and clients who pay on the worker's word; hand-ins declared finished or unfinished; trying code privately at one's desk; faults that, when they come to light, quote the declaration they follow from; partner choice, with pairing by lot as its control; pay and liability shared by partners; crowns handed between residents; private remarks; each resident's own starting balance and daily obligation; notices posted through the day at prices fixed when posted. Existing runs stay readable.
- **Voice.** Every text a resident reads follows the immersion guide: identity in the second person, memory as recollection, and what every resident knows of the town as a setting kept apart from the moment. A vocabulary of machinery words, beside the trait vocabulary, guards the templates and every request sent in dry runs.
- **Runtime and experiments.** Scenes for the new mechanics, told by the clock. `experiments/configs/town.yaml` is the town of the design (eight residents in unequal circumstances, six weeks); `experiments/studies/trust.yaml` gives its arms as overlays, run by a small study runner whose seeds post the same jobs in every arm. `pilot.yaml` and `smoke.yaml` were carried over to the new format and voice with the first town's rules.
- **Tasks.** `tasks.coding.fetch` converts LiveCodeBench into banks outside the repository, with a held-out split and impossible variants; `tasks.coding.calibrate` measures a model's first attempts at each task; the detector of code that writes out the visible checks' values is shared from `tasks.coding.special_cases`. Isolating delivered code in a bubblewrap sandbox was begun.

The commit recorded one open point: under guided decoding residents were not shown what a reply could hold, and could not take a job.

## The answer card

296749d closed it. One definition in `core/interaction/card.py` turns the moment's real choices (the jobs on the board, the people present, the places open, the parts not yet in) into the card a resident reads, the JSON schema the server enforces and the translation of a reply back into an action, so the code's names never reach a resident. With it came one voice for memory (told in the second person, the resident's own words quoted), the board kept by a clerk, the draft on the resident's desk, a bounded retry of a reply cut off by the token limit instead of the end of the run, and card values in sorted order so that runs stay reproducible. The commit records a three-day run of the new town under guided decoding: 114 decisions, none invalid or cut off, and 2 of the 114 private thoughts genuinely about machinery. That run was not kept among the project's runs.

## The viewer

0c742fd refined the viewer: one type and spacing scale, flat surfaces and a single accent; the dashboard grouped into pinned section tabs; a town drawn from the world's own data, with buildings by kind, streets routed around them, water and a square where place names call for them, light that follows the simulated clock, and residents who walk the streets and face each other when they talk. Below 1000 pixels the views move to a bottom tab bar, and the town's timeline and panels to one draggable sheet, with pan and pinch on the map. Unknown event kinds render generically. The sign-in pages took the same refinement (CSS and mark only). A node check of the town plan, `tests/frontend/plan_check.mjs`, was added.

## Committed on 2026-10-12

5c0d25b holds the runtime and the probe battery.

- **Lapses.** A reply that cannot be read within three attempts no longer fails a run: the moment passes with a truth-only lapse event, or the night step is skipped with nothing committed, and a run fails once lapses exceed 1% of its decisions and number at least ten. The client retries rate limits and timeouts with backoff; a first answer is written freely and the card enforced only on a retry; an answer that cannot be read is handed back with a plain correction.
- **Witness wording.** Event texts are written once as a function of the witness they are told to (`core/interaction/telling.py`), so each resident reads itself as "you", and the log keeps each witness's wording.
- **Isolation and banks.** Isolation is a named task setting frozen with the run and checked before a run is created; a missing bank fails at once, naming the command that builds it.
- **Probes.** The evaluation was rebuilt as nine families at four stake levels and three surfaces each, played in a probe town composed from the run's own environment and scenes, on held-out work with impossible variants, scored from typed outcomes, with a DeepSeek judge and ablated exports. Results carry a format: format 2 now, the first pilot's format-1 files still loading. `evaluation.agreement` measures a judge against labelled replies.

f421c28 holds the analysis and its viewer. `analysis.traits` reads the four dilemmas, partner choice, immersion and lapses from the event log and the agents' own writing; `analysis.study` compares the arms of a study with the run as the unit, by an exact sign-flip permutation test. The publisher bundles both, and the viewer gained the Character section, the study view and the lens that reads the town as one resident read it; its wording moved to crowns, marks and standing.

## Verification

- The commits of 2026-10-04 record no test count. Rerun on 2026-10-12 in a clean worktree of 296749d, the suite gives 380 passed and 2 skipped.
- At f421c28 the full suite gave 424 passed and 2 skipped, as 5c0d25b records.
- 296749d's three-day run under guided decoding, as above.
- The viewer refinement was checked in headless Chromium at five sizes, not in WebKit.

## Not done

- Beyond the three-day check of the answer card, whose configuration is not recorded, the second town was not run: no run of `town.yaml` or of its study was executed. The LiveCodeBench banks were not built or calibrated, so neither the town's work nor the held-out work existed.
- The rebuilt probe battery was not played with the residents' model, and the DeepSeek judge was not tested.
- `docs/summary.md` still described the first town, `smoke.yaml` still ran the first town's rules, and four defects were left: the evaluation's isolation did not reach the assessment of a hand-in, the evaluation view drew no stake curve for a format-2 result, the README's quick start evaluated a run the battery cannot be played in, and one test file was not formatted. All were taken up on 2026-10-12.
