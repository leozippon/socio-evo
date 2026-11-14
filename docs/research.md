# AI laboratory research protocol

## Question and scope

Can a four-person laboratory, after seven days of ordinary social life, organize itself around a newly announced AI question and produce a scientifically checkable initial study by day 28? Our hypothesis is that the group can turn its established relationships and complementary skills into a falsifiable proposal and at least one reproducible empirical comparison. Failure to agree, incomplete experiments, unsupported claims and reliable negative results are all informative outcomes.

This is a single laboratory feasibility study. It cannot identify a causal benefit of the free-living period or teacher/student organization without additional matched runs and controls. Judge scores are feedback and funding signals, not ground-truth scientific quality. A later comparative study needs independently seeded runs as its units of analysis; residents, days and repeated reviews of one manuscript are not independent replicates.

The independent `ai-lab.yaml` profile uses Mei as teacher and Aisha, Ravi and Kofi as students. Each has AI-relevant experience and a distinct personal background. External shops, meals and medical care replace agent service occupations. Hunger, illness, working energy, sleep, rent, movement, private memory and conversation still matter. The same event runtime and shared versioned workspace derive from upstream `redesign-event-runtime` (`8cca4f9`).

## Calendar and support

| Simulated period | Resident experience | Required collective output |
| --- | --- | --- |
| Days 1–7 | Ordinary life, with no announced future research objective, deadline, judge or award | None |
| Day 8, 07:00 | Common AI research commission; discuss candidate questions and divide work; Office research tools open | `proposal.md` before the day-8 review |
| End of day 8 | External proposal review | Maximum 630 per resident |
| End of day 28 | External initial-manuscript review | `paper.md`; maximum 840 per resident |

The first seven full lived days end at the day-7 checkpoint, 04:30 on the eighth calendar day; the announcement follows at 07:00. End-of-day reviews run when all residents are resting at the daily checkpoint, rather than interrupting a command at midnight. Days in configuration are absolute simulated days. The initial run ends after the day-28 review; no automatic later stage is implied.

Before day 8, the actual resident system prompts, backgrounds, help, tool schemas and shared initial text omit the future commission. Residents remain free to discuss their interests, including AI. They are not instructed to prepare a topic or paper during this period. The publication marker, shared README, tool availability and standing rules change together at announcement. Restoring day 7 keeps the commission hidden and schedules it again for the coming morning; restoring day 8 keeps it published without notifying or paying again.

Each resident starts with the original purse of 200 plus an unconditional living allowance of 420. The allowance is recorded at initialization; announcing research does not pay it again. Review dimensions are equally weighted integers from 0 to 4. Their sum maps to 0–100; each resident receives `floor(stage maximum × score / 100)`. There is no individual contribution reward. The ceilings were calibrated against the original upper estimate of 30 per day for basic food and rent; they are not guarantees against medical or discretionary expenses. Provider billing is separate from simulated money.

## Models and research facilities

The configured resident model is local Qwen3.8-27B-FP8 on host GPU 0, with one tensor-parallel shard and four concurrent residents. Host GPU 1 is assigned to scientific commands, using a CUDA/PyTorch image. Resource availability and actual training must be verified before launch; an exposed GPU alone does not establish a working scientific stack. The external judge remains the user-selected `gpt-6.1-sol` through Lightingtheword, in a separate client with its own prompts.

After announcement, an awake resident at the Office can edit shared files, run shell commands, call Tavily, use curl and read public sources. Semantic Scholar is disabled. Commands run serially over the shared tree with internet access, 8 CPU cores, 32 GiB memory and up to 600 real seconds per call. Longer studies can save a training checkpoint and continue in another call.

Study code, data, metrics and checkpoints belong in `/research`, whose host tree is versioned alongside read-only operation records. Dependencies installed with `pip install` use `/runtime/python`; model downloads, framework caches and temporary files also use the separate persistent `/runtime` mount. These reusable files stay outside research Git and the judge dossier. They survive container replacement and checkpoint restoration, so they are not a historical environment snapshot: studies must record dependency versions and place scientific evidence in `/research`. Host credentials, private resident directories, simulation state and Docker control are not mounted into research commands.

## Review and evidence

The authoritative rubric lives in `world/research_milestones.py`. A proposal is assessed for a useful AI question, traceable literature gap, falsifiable method, controls and feasible analysis plan; completed experiments are not required at that stage. A manuscript needs claims supported by actual sources, code, data and recorded execution. Scope assessment considers whether the contribution concerns AI methods, models, learning, evaluation or behavior, rather than checking keywords. Applying software to an unrelated subject is insufficient.

The judge receives a deterministic dossier bounded to 180,000 characters including JSON serialization and its manifest. The complete main artifact comes first. Execution records precede other records and are ordered by simulated recency; records and supporting files each receive half of the remaining document space before unused space is shared. Supplied documents are whole. The manifest gives their original hashes and identifies listed omissions; coverage counts explicitly report omitted files that could not also fit in the manifest. The exact Git revision preserves the complete underlying workspace. Oversized or binary main artifacts fail explicitly rather than being truncated.

Resident names are masked; run labels, purses, private notes and prior review records are not added. Content can still reveal the institution, so masking is partial. Positive dimension scores require exact quotations from supplied documents, checked against the actual packet. A logged command is not an independently reproduced finding; a paper's claim is not evidence that its experiment happened. Negative findings can earn full marks. Omitted files and external URLs are not presumed read, and a single judge cannot exhaustively establish novelty or correctness.

Every supplied input, model setting and raw attempt stays under `<run>/research_reviews`. Successful reviews are cached against their exact configuration, revision and input. Missing or empty deliverables receive a deterministic zero; invalid citations, malformed replies and provider outages stop the run without issuing money. A milestone marker and its payment are captured in the same daily checkpoint. Resume restores their shared state, avoiding duplicate awards. Abandoned events may remain in the append-only log; checkpoint state determines the lived history.

This lightweight design draws on structured review in [The AI Scientist, section 4](https://arxiv.org/html/2408.06292v1#S4) and its [official implementation](https://github.com/SakanaAI/AI-Scientist/blob/main/ai_scientist/perform_review.py). [The AI Scientist-v2](https://arxiv.org/html/2504.08066v1) and [CodeScientist](https://arxiv.org/abs/2503.22708) motivate examining code and execution alongside the manuscript. The four dimensions, funding formula, evidence budget and single-review default are project choices rather than validated reward schemes inherited from those papers.

## Expected outputs and interpretation

Keep all run state and derived artifacts on Zenith. Inspect the proposal, manuscript, versioned study files, source and command records, raw judge attempts, grant records, resident traces and day-28 checkpoint together. Check whether the central comparison can actually be reproduced and whether the manuscript distinguishes measured results from intended work. Report missing deliverables, execution failures and review outages alongside scores; do not remove them from the account of feasibility. Retained token usage is not necessarily a complete provider invoice after a rollback.

The [operations guide](../ops/research/README.md) owns exact commands and preparation status. The previous town/academy pair used an API resident model, an announced commission from the start and day-7 proposals. Its frozen configurations and remote outputs remain intact; see the [historical plan](plans/2026-11-13-autoresearch-town-academy.md) and [completion record](logbook/PROJECT_LOG_2026-11-14). The still earlier 14-day pilot is documented in the [pilot archive](archive/research-pilot.md). They are separate experiments, not controls that isolate this protocol's changed model, timing and GPU facilities.
