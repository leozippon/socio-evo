# Activity-scoped work summaries

## Goal
Before a voluntary Work exit, the resident writes one bounded overview of the job research and operations performed in that activity. Store it in that job's private summary notes, then execute the already chosen exit. Empty work sessions skip this step.

## Architecture
Keep append-only raw journals. Associate operational records with their Work activity and job. Snapshot each unfinished activity/job range; summarize it once, with explicit character limits and first-attempt schema validation. A bounded input may use labeled excerpts of long outputs without claiming that every raw character was read. Record source ranges, activity and times with the saved overview. Do not split raw logs into repeated model calls or merge historical notes during exit. Mandatory transitions retain unfinished ranges; nightly catch-up and historical consolidation remain separate.

## Implementation and validation
1. Update `core/agent/memory/work.py` to track activity ranges and persist one overview per snapshot without losing raw data or covering later appends.
2. Update `core/agent/agent.py` and nightly simulation integration to use the single overview step, concise prompt and existing bounded failure handling.
3. Update core tests for activity isolation, multiple jobs, empty work, interrupted/failed summaries and durable range metadata.
4. Exercise the realtime engine with delayed responses and a 15x clock: one summary call, zero exit-time merges, persistence before exit, mandatory cancellation, other residents' progress.
5. Run a controlled single-resident probe using Zenith's real model. Verify summary character count, job-specific persistence and the selected exit; retain only metadata in the report.
6. Run local and Linux regression checks, perform one independent audit, update living documentation, commit/push and activate the tested future default on Zenith. Preserve the running frozen experiment and services.

## Stack
Python Agent/WorkNotes, asyncio realtime scheduler, pytest, existing structured Chat gateway and append-only JSONL journals.
