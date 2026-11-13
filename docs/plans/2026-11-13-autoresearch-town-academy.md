# AutoResearch town and academy implementation plan

**Goal:** Compare collective autonomous research in the existing town and an academy, with independent milestone assessment funding continued life.

**Architecture:** Extend the shared research runtime already based on `redesign-event-runtime` commit `8cca4f9`. Keep the existing world, persistent agents, workspace and checkpoint machinery; add milestone review at quiescent checkpoints and an external-service academy mode. Preserve the earlier pilot configuration for historical runs.

**Tech stack:** Python 3.11+, Pydantic, asyncio, OpenAI-compatible APIs, Git-backed artifacts, Docker research commands, YAML experiment overlays.

## Settled protocol

The user selected absolute simulation days: proposal on day 7, initial manuscript on day 28. Residents select their own topic during the first week, with no imposed scientific objective. Actor: Lightingtheword `DeepSeek-V4.1-Flash`. External judge: Lightingtheword `gpt-6.1-sol`, supplied by the user, sharing the credential variable `LIGHTING_API_KEY` but a separate configured client and prompt.

The hypothesis is that a town's broader relationships and diverse occupations can improve the value of research questions and robustness of collective inquiry, while imposing coordination and subsistence costs that may lower executed research per API token. The academy can outperform it by providing stable services and sustained focus. Either direction, or no material difference, is scientifically useful.

The four core researchers are matched across arms. The town retains four other resident agents; the academy has one teacher and three students and buys necessities directly from the environment. Everyone in the town can participate in research. This is a comparison of complete organizational arrangements, including total population and role prompts, not identification of a single social mechanism. Real API usage must include service residents. A single pair is an exploratory case comparison; independent paired seeds, rather than residents or days, are the replication units for later inference.

Initial external allowance is 420 per resident, in addition to original starting purses. Maximum milestone awards are 630 per resident at day 7 and 840 at day 28. These equal 21 and 28 days at the original maximum basic daily food/rent cost of 30; actual health costs and prices can differ. Score scales the collective award, then an equal share reaches every resident directly so it is usable in either institution. Simulation money is not actual API credit. Day 28 is the endpoint of the initial study; its award supports explicitly configured future extensions, not an automatic claim of continued execution.

## Implementation and acceptance

1. `world/research_milestones.py`, research configuration/lifecycle and checkpoint hook: stage-specific evidence-grounded review, bounded structured scores, deterministic award, frozen inputs and raw response, failure without payout, restored exactly-once award state. Test real checkpoint/resume semantics and malformed/absent evidence paths.
2. Academy occupations and external services: no agent shopkeeper, cook, doctor or mayor; actual purchases, meals and treatment at the relevant places, nonnegative funds, persisted state, original body and rest. Test service affordability, locations, availability and resume.
3. Office network facilities: Tavily, Semantic Scholar and curl with recorded source responses, credentials supplied only to the provider, and researcher commands with internet and configurable GPU access. Verify wrong-location access and provider failure are explicit.
4. Common actor/judge configuration and two experiment overlays; a remote-only launch path, preflight, documentation and compact comparative metrics. Reuse valid existing environments and never alter a running deployment in place.
5. Run targeted and applicable regression tests, inspect staged changes, commit and push a focused temporary branch to the canonical repository. Perform live provider/container probes and launch both arms on Zenith when SSH and credentials are usable. Record blockers precisely; do not claim an experiment or scientific outcome without its execution evidence.

The relevant baseline and scientific sources are described in `docs/research.md`; the older SWE-bench and personality studies remain available as legacy configurations, not the new benchmark.
