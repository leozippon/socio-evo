# Offline grading readiness and automatic retry

Goal: prepare checksummed official environment metadata before publication; reject
cache misses without network access during evaluation; preserve and retry submitted
snapshots automatically when grading infrastructure fails.

1. Extend tasks/swebench/http_cache.py with strict reads, checksum/status validation,
   bounded preparation retries, atomic writes, URL provenance and a prepare CLI.
   Discover exact URLs (including recursive requirements and 404 fallback probes)
   by running the installed official environment-spec generator with an allowlisted
   public metadata row and injected HTTP getter. Do not fetch solutions or gold tests.
2. Add a subprocess environment-spec probe and readiness check in tasks/swebench:
   strict cached spec generation, existing official image, repository baseline and
   launcher; record checksums/image IDs and block publication on any failure.
   Wire opt-in config defaults, provider publication paths and actual evaluator.
3. Update ActivityEngine to keep the original submitted patch pending on an
   AssessmentUnavailable result. Emit attributed automatic-retry notices, retain
   one-job slots and grace, schedule capped exponential backoff, checkpoint retries,
   and fix realtime final-settlement handling for queued retries.
4. Add offline tests with fake official builders/HTTP/Docker plus controlled clocks:
   exact original response preservation, cache miss/corruption, non-cacheable server
   errors, atomic failed preparation, preflight gate, snapshot identity, recovery,
   no duplicate payment, no retry on a real failed verdict, resume and final pending.
5. Prepare a separate local cache artifact for the selected pilot issues using the
   real official harness if available. Never overwrite the current run's cache or
   deploy code. Run related regression suites, lint and commit locally. Document
   unverified Docker readiness if no local Linux Docker is available.

## Implemented and verified

- Prepared a separate metadata cache using official SWE-bench 4.1.0 for all 500
  Verified issues: 44 requested URLs, 37,991 bytes, SHA-256
  b61eef9eb5d118dfad0c20b01ee2db08638f7439ed5acf0b30558d8bc3861c63.
- Bundled cache and provenance manifest under tasks/swebench/metadata; new Verified,
  activity and realtime profiles reference it. The current experiment's original
  dataset-side cache was not overwritten. Lite needs a separately prepared cache.
- Ran official generation from both allowlisted public metadata and complete official
  dataset rows for all 500 cases with requests.Session.request disabled: environment
  image keys and instance image keys match in every case. Gold tests are neither
  executed nor exposed to residents by this probe.
- Final related regression suites: 296 passed, including bundled-cache integrity
  and the final config paths.
  Additional environment suite: 102 passed, 2 deselected (the previously documented
  host bubblewrap limitation and pre-existing night-review suffix assertion).
- Missing/corrupt cache, transient HTTP outage, fallback 404, atomic output,
  public-metadata allowlist, strict evaluator wiring/snapshot identity, readiness
  gate, immutable automatic retries/recovery, real failed verdict, resume/backoff,
  bounded final pending state and unavailable replacements are covered.
- No Linux Docker readiness was executed locally. Real instance image availability
  and fresh container probes remain mandatory before the next live launch.
- No code, cache, result file or process of the current frozen experiment was changed.
