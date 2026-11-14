# AI institute research protocol

## Question and scope

Can four AI doctoral students turn ordinary social interaction into sustained, evidence-supported research, and improve their manuscripts across repeated external reviews? Our hypothesis is that explicit access to working compute and actionable reviewer feedback will help the group produce more reproducible studies and resolve identifiable scientific weaknesses over successive cycles. Unsupported claims, repeated errors, unaddressed criticism, missed submissions and reliable negative results are informative outcomes.

This is one longitudinal feasibility run, not a causal experiment on social life, reviewer feedback or GPU access. Scores from the same reviewer are a feedback signal, not ground-truth scientific merit. Later comparisons need independent seeded societies and matched conditions; residents and reviews of the same work are not independent samples. Scientific acceptance requires checking the actual code, evidence and claims, rather than accepting the reviewer's score alone.

The `ai-lab.yaml` profile now describes an AI institute: Mei, Aisha, Ravi and Kofi are doctoral peers with distinct backgrounds. The town still supplies bodies, sleep, movement, conversation, memory, housing and money. Shops, food and healthcare come from fixed-price external services. There are no merchant, chef, doctor or mayor agents.

## Calendar and support

| Simulated period | Experience and output |
| --- | --- |
| Days 1–7 | Free life with no announced collective assignment, paper deadline, reviewer or reward |
| Day 8, 07:00 | Shared AI research commission; discuss candidate questions and divide work; research facilities open |
| End of day 28 | First complete `paper.tex` submission and external review |
| End of days 49 and 70 | Further submissions and reviews, informed by prior feedback |
| After each review | Discuss feedback and choose revision or a new question, then conduct experiments and write |

The target is a meaningful contribution suitable for a leading computer-science conference such as ICML or ICLR, rather than a guaranteed acceptance. Specific questions and scientific methods remain the residents' decisions. A new topic every cycle is optional: addressing a strong criticism may require continuing the same study. The submission interval is 21 research days, counted inclusively from day 8; no proposal review occurs on the announcement day.

The first seven lived days end at the day-7 checkpoint, 04:30 on calendar day 8. The announcement follows at 07:00. Reviews occur at the end-of-day checkpoint when everyone is resting, not by terminating a command at midnight. The scheduler supports arbitrary later cycles, while this launch has a finite horizon of 70 days. Choose a longer horizon before launch; existing frozen-run resume checks do not silently extend a completed experiment.

Before announcement, actual prompts, backgrounds, help, tool schemas and shared text omit the future assignment. AI interests and doctoral identity remain known. The announcement marker, shared README, research tools and standing rules change together and restore consistently from checkpoints.

Each resident starts with 200 plus an unconditional allowance of 1260. This supports the longer period before the first review; announcement does not pay it again. Each cycle has a maximum grant of 1260 per resident. The conference overall rating, 1–10, maps to `100 × (rating − 1) / 9`; each grant is `floor(1260 × score / 100)`. Missing or invalid manuscripts receive zero. Grants are equal, with no individual contribution score. Basic food and rent were budgeted conservatively at 30 per day, or 630 per cycle; illness and discretionary spending can change costs. Provider charges are separate from simulated funds.

## Compute and writing facilities

The local Qwen3.8-27B-FP8 resident service uses host GPU 0, one tensor-parallel shard and four concurrent residents. Scientific shell calls use a separate container on host GPU 1. The model emits a tool request; host Python launches the research container; its CUDA program runs on the research GPU. Inside that container the single visible device is `cuda:0`, even though it is physical GPU 1 on the host.

The announcement, research help and shared README explicitly describe the assigned GPU and provide an executable probe and PyTorch example that moves model, inputs and labels to CUDA and performs optimization. CUDA detection fails explicitly if unavailable. CPU quotas are additional resources, not a claim that the lab has only CPUs. Classical scikit-learn experiments can appropriately use CPUs; actual GPU use must be established from execution evidence rather than inferred from availability.

After announcement, an awake resident at the Office can edit shared files, run shell commands, search with Tavily and retrieve public sources with curl. Semantic Scholar is disabled. Commands run serially with internet access, 8 CPU cores, 32 GiB memory and a 600-second limit per call. Longer experiments can save training checkpoints and continue in later calls. They submit `paper.tex` and supporting bibliography, figures and included source files, and can compile with `latexmk -pdf -interaction=nonstopmode -halt-on-error paper.tex`.

Study code, data, metrics, figures, manuscripts and training checkpoints belong in `/research`, versioned alongside read-only operation records. Packages installed into `/runtime/python`, downloaded models and framework caches persist separately under `/runtime`, outside the research Git repository and review dossier. This cache survives container replacement and checkpoint restoration; it is not a frozen environment snapshot. Record dependency versions and keep scientific evidence in the versioned workspace. Host secrets, private memories, simulation state and Docker control are not mounted into research commands.

## Review and feedback

The external API uses the user-selected `gpt-6.1-sol` via Lightingtheword, independently of the resident model. The authoritative prompt and schema live in `world/research_milestones.py`. The conference-style reviewer assesses technical quality, novelty, significance, evidence and reproducibility, then gives an overall 1–10 rating, confidence 1–5, strengths, weaknesses, questions and required revisions. Its accept/reject recommendation is a simulated judgement, not a submission to or decision by a conference.

The prompt follows conference principles of evaluating claims, evidence, contribution and actionable criticism. Its numeric scale and funding conversion are project choices; conference forms differ across venues and years. Earlier fixed-milestone experiments retain their original four-dimension reviewer. AI scope is evaluated semantically: applying software to an unrelated subject alone does not meet the commission. Negative results can earn high ratings when the contribution and evidence warrant them.

The judge receives a bounded, deterministic dossier with the complete main manuscript and a manifest. The 180,000-character budget includes serialized JSON. Recent execution records and supporting text share remaining space; omissions and their counts are explicit. The exact Git revision preserves all study files, even when the reviewer cannot see them. Binary files, including PDFs, are not treated as text the reviewer has read. LaTeX structural checking is limited; the compile record establishes compilation, and neither successful compilation nor successful execution proves scientific validity.

Resident names are masked, but content may still reveal the institution. Positive assessments require exact evidence quotations checked against the supplied documents. A citation proves only what the document says; a successful command is not independent scientific reproduction. URLs, omitted files and unseen plots are not presumed inspected. Novelty and correctness still require human audit.

Each review preserves its exact input, model settings, raw API attempts, manuscript revision and structured response under `<run>/research_reviews`. All residents receive the summary, a path to the complete read-only feedback record, and the next deadline. They can read the full review through `read_repo_file` and decide how to act on it. The next review assesses the submitted work on its evidence; it is not a promise of monotonically increasing scores.

Successful reviews are cached against exact input, configuration and revision. Missing/empty or structurally invalid LaTeX submissions earn zero with an explanation. Malformed responses, invalid evidence citations and provider outages stop explicitly without issuing a grant. Review markers and payments share a checkpoint; restoring before payment reuses the review without paying twice in the restored history. Append-only logs can retain abandoned events, so checkpoints determine lived state.

## Outputs and interpretation

All experiment state and derived artifacts remain on Zenith. Each cycle should yield a LaTeX manuscript, supporting bibliography/figures, code/data/results, recorded execution, a frozen submission revision, an API review and a funding record. Generated PDFs are expected when residents successfully compile; they are not fabricated by the evaluator. Private journals, conversations and traces support analysis of how collaboration and criticism influenced decisions.

Audit central claims, reproducibility, response to criticism and possible fabrication across cycles. Report missing papers, failed commands and review outages alongside scores. Distinguish new evidence from reworded assertions, and do not count repeated reviews as independent replication. Retained token usage after rollback is not necessarily a complete billing ledger.

The [operations guide](../ops/research/README.md) owns launch commands and current status. The previous teacher/student laboratory and the earlier town/academy pair keep their original configurations and remote data. They are historical runs, not matched controls for this protocol's changed roles, GPU instructions, allowance, deadlines and reviewer.

The reviewer design adapts the [ICLR 2026 reviewer guide](https://iclr.cc/Conferences/2026/ReviewerGuide) and [ICML 2025 reviewer instructions](https://icml.cc/Conferences/2025/ReviewerInstructions), especially claims/evidence assessment and actionable feedback. Our 1–10 overall scale is not the ICML 2025 form's 1–5 scale.
