# Collective AutoResearch protocol

## Question and comparison

Can a town's diverse relationships and everyday economic interdependence improve autonomous research enough to offset the cost of maintaining them? Our directional hypothesis is that the town may produce more valuable questions and stronger critical scrutiny, while the academy may execute research more efficiently. Either outcome, or no reliable difference, matters; evidence determines the conclusion.

The implementation uses the shared workspace already built on `redesign-event-runtime` commit `8cca4f9`. `autoresearch-town.yaml` retains eight residents; `autoresearch-academy.yaml` retains the same four core researchers, with Mei as teacher and Aisha, Ravi and Kofi as students. The academy has no agent merchant, cook, doctor or mayor. Its fixed-price external services take payment out of the environment. Illness, fatigue, hunger, rent, movement, private memories, conversations and Office research remain.

All town residents can contribute, so total population, role prompts, service organization and available contributor time differ. This is a comparison of complete institutions. It does not isolate a causal effect of social interaction or hold total inference compute constant. Match the actor model, tools, four core members' starting purses/homes, seed, calendar, review rules and per-resident grant schedule. Report total actor usage including service residents, judge usage separately, quality and quality per token. Real provider billing is separate from simulation money; do not infer currency cost without verified prices.

One pair of runs is a feasibility and case comparison. For a later inferential study, run multiple independently seeded pairs and analyze at the run level; residents, days and multiple reviews of one manuscript are not independent replicates. Record failures, missing deliverables and review outages rather than removing unsuccessful runs. Do not use the legacy SWE-bench capability measures as the research benchmark.

## Stages and funding

| Checkpoint | Collective artifact | Review meaning | Maximum grant per resident |
| --- | --- | --- | --- |
| Day 7 | `proposal.md` | A self-selected question, literature-grounded gap, falsifiable method, controls and feasible plan | 630 |
| Day 28 | `paper.md` | An initial manuscript supported by supplied code, data, recorded execution, sources and calibrated claims | 840 |

Days are absolute simulated days. The first week has no assigned topic or scientific objective beyond choosing a worthwhile project. Residents receive the common commission and know the deadlines. There is no assigned research leader in the town; the academy's teacher/student roles are part of its intervention. The original pilot's 420 per-resident allowance remains, on top of the original purse. The award ceilings correspond to 21 and 28 days of basic food/rent at the original upper estimate of 30 per day; changing prices, medical costs and discretionary spending are not covered by that estimate.

Each review scores four equally weighted dimensions from 0 to 4: significance, rigor, evidence and reproducibility. Stage-specific anchors distinguish a proposal's planned study and literature evidence from a manuscript's executed work. The program maps their sum to 0–100, computes `floor(max_reward_per_resident × score / 100)`, and distributes that amount to every resident. This is one collective award with equal shares, independent of who edited or submitted the artifact. Larger populations receive proportionally larger total living support. This avoids an academy award becoming stranded in a treasury with no mayor.

The initial experiment ends at day 28 after its review. Its final award remains in the checkpoint for a separately configured continuation; no automatic infinite run or automatic further milestone is implied. Further stages can be configured with later days and artifact paths. Existing runs require their frozen configuration unchanged when resuming, so decide a longer schedule before launch.

## External review and evidence

The actor is Lightingtheword `DeepSeek-V4.1-Flash`; the judge is the user-selected `gpt-6.1-sol` at `https://lightingtheword.com/v1`. Actors use thinking mode, retaining the provider's reasoning field across tool continuations and session reloads; the protocol requirement is documented in the [DeepSeek API guide](https://api-docs.deepseek.com/guides/thinking_mode/). They use separate clients and prompts; the shared key is supplied through `LIGHTING_API_KEY`. The conservative context/compaction settings are operational choices, not claims about the provider's maximum supported context. The launcher probes the actual configured endpoints before starting.

At the daily checkpoint the clock is held and residents have finished their actions. The judge receives a bounded dossier: the entire deliverable first, supporting text files and recorded source/command evidence, plus a manifest that identifies binary or omitted files and content hashes. The current limit is 180,000 characters, with no silent truncation of the main artifact. A binary or over-limit primary artifact fails explicitly. Resident names are masked and run/arm labels, purses and previous review records are not added. Artifact text may reveal its institution, so this is partial masking, not guaranteed blindness.

Positive dimension scores require exact quotations from supplied documents; citations are validated. The prompt distinguishes statements in a paper from evidence of a successful run, and successful execution from a reproduced scientific claim. Reliable negative findings can score highly; verbosity and persuasive prose have no separate reward. The reviewer does not independently execute the study or exhaustively verify novelty. Readable supporting files are selected deterministically within the input budget, so omitted material cannot receive verified credit.

The authoritative rubric is `world/research_milestones.py`. Every supplied input, configured model and attempt is retained under `<run>/research_reviews`; successful reviews are cached against the exact revision, dossier and judge settings. Invalid or unavailable judge responses fail the run without a payout, allowing operational repair and resume. An absent or empty deliverable is a deterministic zero, distinguishable from an outage. The grant marker is committed in the read-only research records before the world checkpoint captures both the workspace revision and purses. Resume restores that state rather than awarding a completed milestone again. Events from an abandoned partial day can remain in the append-only log; checkpoints determine the lived state.

This lightweight design draws on the structured NeurIPS-style review in [The AI Scientist, section 4](https://arxiv.org/html/2408.06292v1#S4) and its [official review implementation](https://github.com/SakanaAI/AI-Scientist/blob/main/ai_scientist/perform_review.py). [The AI Scientist-v2](https://arxiv.org/html/2504.08066v1) and [CodeScientist](https://arxiv.org/abs/2503.22708) motivate checking actual code and execution evidence alongside manuscripts. Our four dimensions, funding formula and single-review default are project choices, not validated reward schemes inherited from those papers.

## Research facilities

Every awake resident able to work can use shared research tools at the Office. `search_web` calls Tavily (`TAVILY_API_KEY` required); `search_literature` calls Semantic Scholar (`SEMANTIC_SCHOLAR_API_KEY` optional); `read_source` extracts public HTML/text/PDF and `curl` captures a public HTTP(S) response. Failed searches and unreadable sources remain explicit failures. Provider credentials stay on the host and are not recorded in tool arguments or mounted into commands.

Shared files are versioned; file edits conflict only when their target changed, while shell commands serialize over the shared tree. Evidence records are read-only to residents. Commands use a disposable Docker container with persistent shared files, internet access, 8 CPU cores, 32 GiB memory and a 600-second timeout in the new configurations. Optional Docker GPU selectors can allocate one card per arm after checking availability. The image includes Python scientific packages, curl and git; GPU exposure alone does not install a CUDA/PyTorch stack. Resident private memories, simulation state and the Docker socket are not mounted. Individual commands are bounded; projects can save progress and issue further commands.

## Run and inspect on Zenith

All experiment state and derived reports belong on Zenith project storage. The local checkout contains code, configuration and text-only project notes. The target two-A100 machine is documented as `ssh -p 2936 root@115.190.90.101`; verify current access and resources rather than assuming old service state. Do not update the old pilot in place or reuse its run name for this different protocol.

After installation and loading the private credentials as shown in the root README:

```bash
python -m ops.research.run_pair --runs-root /project_c20250210/260903018/socio-evo-autoresearch/deployment-20261113/runs --seed 20260302 --preflight-only
python -m ops.research.run_pair --runs-root /project_c20250210/260903018/socio-evo-autoresearch/deployment-20261113/runs --seed 20260302
```

Use `--until-day 7` for a resumable first-stage run, and the same command with `--resume` to continue. Keep the supervising command in a persistent remote terminal or service. The pair launcher performs provider/search/container checks before launching either arm and keeps per-arm logs in project storage. Optional GPU arguments and precise CLI options are shown by `--help`.

The existing read-only research viewer reads both run directories:

```bash
python -m frontend.research_server --runs-root /project_c20250210/260903018/socio-evo-autoresearch/deployment-20261113/runs --site /project_c20250210/260903018/socio-evo-autoresearch/deployment-20261113/site --port 8919
```

Reach it through SSH forwarding. The dashboard shows per-stage scores, award records and both institutions. Its grant totals and purse replay include external services; the legacy personal-income category breakdown does not list research grants separately. For a checkpoint-grounded machine-readable comparison:

```bash
python -m analysis.research --town /project_c20250210/260903018/socio-evo-autoresearch/deployment-20261113/runs/autoresearch-town-seed-20260302 --academy /project_c20250210/260903018/socio-evo-autoresearch/deployment-20261113/runs/autoresearch-academy-seed-20260302 --out /project_c20250210/260903018/socio-evo-autoresearch/deployment-20261113/comparison.json
```

The report separates pending stages from zero scores, includes all retained resident usage and all persisted judge attempts, and reads awards only from the last completed checkpoint. Resuming discards actor traces after the restored checkpoint, so their token totals are retained-record counts rather than a complete historical invoice. Provider fields that were not reported stay null. Keep generated viewer data and all analysis outputs remote. Review manifests, milestone records, artifacts and usage before drawing a scientific conclusion. Historical deployment details for the earlier 14-day local-model pilot are preserved in [the pilot record](archive/research-pilot.md); they do not establish that this new pair has been launched.
