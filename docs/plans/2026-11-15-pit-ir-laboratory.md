# Historical IR laboratory implementation plan

**Goal:** Prepare a Beijing Zhongguancun Academy information-retrieval-agent laboratory that lives from March through December 2026, reads dated research versions, and participates in simulated conference reviewing.

**Architecture:** Reuse the society clock, four residents, shared versioned research workspace, GPU container, independent API judge and checkpoint recovery. Add a host-side arXiv/GitHub browser gateway, a sourced conference calendar and a small conference desk with frozen submissions. New settings are opt-in; the running institute experiment and its historical artifacts remain unchanged.

**Tech stack:** Existing Python/Pydantic/asyncio world, Git evidence, Docker CUDA workspace, arXiv/GitHub public APIs and OpenAI-compatible judge.

## Settled choices

The user approved a simulated institutional identity with correctly attributed public background readings, and conference-calendar reviews with independent living support every 21 days. Do not attribute outside authors' papers to the simulated laboratory. Retain seven free lived days, announce the common project on March 8 at 07:00 Beijing time, and retain the four doctoral peers and GPU split. Use March 1 as the calendar origin and a 306-day planned observation window. Do not restart or rewrite the current run as part of preparing this new profile.

Use historical versions rather than today's full texts with a date filter. A live search API may discover candidates, but only a selected dated version supplies resident-visible text or downloads. Disclose that submission/commit timestamps do not prove historical public availability, that the discovery index is current, and that model knowledge is not erased. The current real date limits the materials that can actually be observed; a configured December horizon is not evidence that future publications already exist.

Three implementation alternatives were considered: date-filtered general web search (insufficient version correctness), a complete independently archived historical web (unavailable corpus and unnecessary scope), and a narrow historical-version gateway (selected). The first version supports only arXiv and GitHub, with paginated search/open and PDF/source/repository downloads. The compute container has no direct internet; all resident retrieval passes through the gateway. Persist caches separately from resident evidence and preserve returned version/hash/cutoff receipts.

Replace automatic 21-day paper reviews with explicit registration, manuscript/PDF submission, review release, rebuttal, ARR commitment where applicable, decision and camera-ready delivery. Keep one active group submission. Three role-varied reviewers and an area-chair decision use the independent judge API. Freeze original evidence at submission; later edits do not silently enter the initial review. Checkpoints own notifications and awards; API results are cached against exact inputs. Decisions beyond December remain pending. Calls for papers distinguish verified dates from simulated missing fields and are a preloaded experiment handbook, not a claim that all future calls were public in March.

## Implementation and acceptance

1. Add timezone-aware calendar settings and validation in `world/config.py`; extend the experiment loader to inline background and calendar resources in the frozen run configuration. Add `experiments/configs/ir-lab.yaml` and four properly scoped biographies.
2. Implement `world/research_browser.py`: arXiv version histories and explicit versions, GitHub dated commit selection and SHA trees/blobs/archives, bounded pagination, readable pages, downloads, cache receipts and explicit provider errors. Test future-version rejection, open/download consistency, real content parsing and path boundaries. Perform small real provider probes on Zenith without creating a formal run.
3. Implement `world/research_conferences.py`: explicit author actions, frozen inputs, three reviews, author response and final decision, exact timezone deadlines, ARR commitment and accepted final versions. Test waiting states, response influence, mutation isolation, missed deadlines, recovery and exactly-once grants with scripted judge responses.
4. Integrate tools, help, day-eight publication, dated mail and living stipends through `world/research.py`, `world/world.py` and `world/rules.py`. Keep old profiles and free-life behavior passing. Check the actual resident-facing tool path rather than testing backend functions alone.
5. Adapt preflight to the selected networking profile, preserve GPU/LaTeX validation, and expose conference events in the existing viewer. Document source provenance, limitations, launch procedure and expected artifacts. Run focused tests plus the broader world/ops/frontend regressions once the components are integrated; fix material failures, commit and push reviewed changes.

No formal experiment is considered launched, no live provider is considered usable and no GPU test is considered passed without a corresponding execution receipt. Preparation failures remain explicit rather than falling back to today's unfiltered internet.
