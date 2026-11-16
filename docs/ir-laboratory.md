# A dated information-retrieval laboratory

The new `ir-lab.yaml` profile follows four doctoral colleagues in an AIcore information-retrieval-agent group at Beijing Zhongguancun Academy. This is an assigned simulation setting, not a claim about a real affiliated group. Mei, Aisha, Ravi and Kofi retain their personalities, relationships, private memories, housing, money, sleep, health and external services. The [background packet](../experiments/resources/ir-lab-background.md) attributes Search-R1, DeepResearcher and WebThinker to their actual external authors; the selected versions precede March 2026. No fictional institutional research achievements are presented as facts.

The stopped 70-day institute run retains its frozen source, records and [original protocol](research.md). The new experiment started separately on November 15 after full service acceptance. The [operations guide](../ops/research/README.md) records its frozen revision, remote receipts and viewer; no old scientific state was resumed into this profile.

## Calendar and scientific question

Day 1 is March 1, 2026 in Beijing. Institutional identity and historical reading notes are present from the beginning; the first seven complete lived days have no announced common assignment. At 07:00 on March 8 the colleagues receive the shared research commission, shared reading library, browser, compute access and conference handbook. Their field is AI information retrieval and research agents; the specific question and division of work remain their decisions. One group submission can be active at a time. Additional working drafts are not automatically counted as submissions.

The planned window is 306 days, through December 31. The society clock determines source cutoffs and conference deadlines; official timezones are converted as instants. Reviews and decisions arrive at scheduled instants even when nobody opens the conference desk. Papers awaiting a 2027 decision remain pending at the end of the observation window. They are not marked rejected or evaluated early.

We ask whether a socially interacting research group can sustain a coherent programme, adapt methods after substantive criticism and produce increasingly well-supported contributions under a changing information environment. Judge scores are feedback, not independent evidence of scientific progress. Examine the provenance of ideas, measurements, code, claims and revisions alongside conversations and decisions. This single trajectory cannot isolate causal effects of social life, institutional identity, browsing or feedback; later comparisons require matched replicated runs.

The original 21-day manuscript reviews are disabled. Each resident retains the initial 1260 allowance and 200 starting purse, plus an unconditional 630 living stipend every 21 lived days. Conference decisions award a separate equal research grant using `floor(maximum × (overall − 1) / 9)`, with a default maximum of 1260 per resident. Acceptance is an area-chair decision, not a score threshold. Checkpoints prevent duplicate stipends and grants.

## Browsing and experiments

Residents use an Office browser to search arXiv or GitHub, follow links, read subsequent pages and download PDFs, source packages or repository archives into shared files. The gateway chooses an explicit arXiv version or full Git commit SHA using the simulated instant. It replaces current search snippets with selected-version content and records the source, version, time basis and hash. Failed requests are not replaced by generated prose or unfiltered live pages.

This minimal gateway is a host-side service behind the `browser` tool, not a separate graphical browser or general HTTP proxy. It returns real linked text pages and byte-preserving downloads. The [browser reference](reference/pit-browser-sources.md) describes APIs, pagination, caches, failures and relevant open-source archive projects. No Tavily, Semantic Scholar or unrestricted curl/read-source route is exposed. Direct networking is disabled in the research container, so shell cannot bypass the library.

An explicitly enabled model library extends the dated browser with public Hugging Face snapshots. It selects a full commit no later than simulated time, verifies downloaded file hashes, and admits read-only model mounts through checkpointed records. Residents can load these snapshots with Transformers or request offline vLLM generation on the research GPU. The [model library guide](model-library.md) contains the exact tool calls and local-loading example; runtime acceptance and continuation lineage are recorded separately.

Qwen3.8-27B-FP8 serves residents on host GPU 0. The CUDA/PyTorch research container uses host GPU 1, visible as `cuda:0`. Installed scientific libraries and LaTeX remain available. The new run has a separate runtime cache; it does not inherit old experiment downloads. New data, code and dependency archives must arrive through permitted downloads. Git LFS pointers are not model weights, and repository access does not establish external dataset availability. A successful CUDA check proves compute access, not reproduction of a paper.

## Submission and feedback

The frozen [calendar](../experiments/resources/conferences-2026.yaml) supplies scope, timestamps, format guidance, sources and simulated fields. Its [source audit](reference/conference-calendar-2026-sources.md) distinguishes official facts, conflicts and simplifications. This is a preloaded handbook assembled in November, not a claim that every call was public in March.

1. Read a call and register the title and abstract before its deadline. Registration does not submit a manuscript.
2. Explicitly submit LaTeX source and a readable PDF. Freeze the Git revision and evidence dossier. Later edits do not replace the submitted version.
3. At review release, receive three separate reviews focusing on methods, evidence and contribution. They use the independent `gpt-6.1-sol` API and checked evidence citations.
4. Discuss the reviews and submit or replace the author response before its deadline, optionally attaching recorded new evidence. ARR venues require a separate explicit conference commitment.
5. At notification, reviewers reconsider the original submission and response. An area-chair judge gives a reasoned accept/reject decision. Initial reviews, response, updated reviews and decision are retained. No missing author response is fabricated.
6. Deliver a camera-ready source/PDF for accepted work. Withdrawn, rejected or completed submissions release the group to submit again. Missed submission, commitment and final-version deadlines remain observable outcomes.

This reproduces the common review cycle, not every special track. Early rejection, cross-venue reuse of ARR reviews, Findings placement, conditional acceptance and some major-revision tracks are simplified where identified. No real conference is contacted. The simulator checks readable PDF and LaTeX structure; it does not prove source/PDF equivalence or mechanically enforce every page/template/anonymity rule. Reviewers receive source and evidence, not rendered plots or independently rerun experiments. Their scores still require scientific audit.

Exact judge inputs, raw attempts and cached answers remain in private host archives. Resident-visible submissions and released feedback are under read-only `research/records`. API, schema and citation failures are explicit; they do not produce fake reviews or grants. The viewer shows conference events and submission states alongside scientific files, operation receipts and PDF previews.

## Historical evidence limits

The browser selects reproducible content whose submission/commit timestamp is no later than the cutoff. It does **not** prove that the version was publicly announced or searchable then. arXiv moderation can delay release; Git dates can be supplied by authors; current search indexes and reachable histories are not historical indexes. Results disclose these limits. Strict historical-publication claims need independently timestamped captures or a curated release corpus.

The assumed March 2026 knowledge cutoff of the resident model has not been independently established. Tool filtering cannot erase learned later knowledge. Model weights, installed software, the external judge and the conference handbook are not reconstructed March snapshots. Describe this as a dated-source simulation, not a contamination-free PIT benchmark.

As of November 15, December publications have not happened. The launcher permits only checkpoints already reached in real Beijing time, then resumes later toward the unchanged horizon. It cannot create future research materials. The [operations guide](../ops/research/README.md) owns launch commands and live-service acceptance; tests alone are not a launch receipt.

Expected outputs are the social trajectory, topics and cited versions, GPU/CPU execution records, frozen manuscripts and PDFs, complete review/response/decision chains, final versions, grants and unresolved submissions. Scientific progress means demonstrable changes in evidence and methods, including useful failures and negative results, not merely generated-paper counts or simulated acceptances.
