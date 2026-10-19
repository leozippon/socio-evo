# Open local conversations and ready replacement tasks

Goal: Residents arriving at a venue choose their next activity; local spontaneous conversation is the main social path, including outside closed workplaces. Keep appointment invitations as an additional option. Preserve frozen experiment data.

Design:
- Arrival updates indoor/outdoor position and feedback but never automatically enters Rest.
- Add an open-local-conversation selection form. One resident can open a public floor without collecting invitation confirmations. Other co-present residents hear the opportunity and may join explicitly. Work is never interrupted; Rest may be woken to choose, not forcibly joined. Undisturbed Rest remains an explicit option.
- Store physical side on conversations. Doorway conversation uses the same side, lasts up to day end and cannot grant indoor work access. Opening does not split an ongoing outdoor conversation. Private/invitation conversations preserve their original audience rules.
- Public speech reaches physically co-present listeners, but outsiders are not participants and do not consume group time; joining does not expose earlier unheard transcript. Leaving/rejoining and live tool completion remain ordered.
- Select a ready unissued SWE-bench candidate when the first drawn environment is unavailable, rather than leaving a slot empty while another ready candidate exists. Readiness never downloads inside the simulation. Prepare missing images separately on Zenith, validate the candidates before marking them usable, and report the finite ready pool.
- Document representative actual system prompts separately from new prompt changes; identify model reasons for rejecting invitations from actual decision events.

Verification: regressions for no automatic arrival Rest, indoor/outdoor separation, independent spontaneous join/decline, resting/busy listeners, public vs private speech, reopening/closing, no time double counting, candidate readiness fallback and total exhaustion. Run related tests before local commit; do not start an experiment or deploy engine changes without the user's subsequent instruction.

## Verification and environment outcome

- 456 related regressions passed; two previously documented unrelated baseline cases
  remain excluded (Linux sandbox on macOS and legacy night-desk suffix expectation).
- Added coverage for public/doorway floors, free opt-in, intentional undisturbed rest,
  appointment waiting interrupted by a local opportunity, live work not interrupted,
  physical-side audience isolation, reopening/day-end and readiness fallback.
- On Zenith, downloaded3of6missing images successfully. The remaining3failed after
  bounded Docker Hub retries and attempts through the platform-configured mirror.
  The mirror exposes the underlying limitation: Docker layers cannot register because
  the20GBroot disk is98%full;15images occupy19.12GB. No active/stopped containers,
  volumes or build cache can be cleaned to solve this. No images were deleted.
- Full offline metadata/image/repository checks passed for14locally available Verified
  issues. One other downloaded SymPy image failed repository preflight and is not in
  the ready pool. Future selection skips unready issues instead of blocking on the
  first draw, but a finite ready pool can still be exhausted. Longer runs need more
  Docker disk capacity or a deliberately prepared larger pool.
- Actual old system prompt examples and Tomas's refusal evidence were exported to
  deployment/reports. Old social audit completed normally with all8night outputs;
  its monitor was paused. No new engine version deployed and no experiment started.
