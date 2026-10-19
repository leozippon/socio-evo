# Offline SWE-bench metadata and background grading recovery

New community profiles enable `tasks.strict_http_cache: true` and
`tasks.evaluation_preflight: true`. Historical configurations default both to false;
no existing experiment or cache is migrated. These settings are separate from the
repository guidance visible to residents.

## Prepared Verified snapshot

`tasks/swebench/metadata/verified-4.1.0-http-cache.json` is bundled for the current
500-issue Verified dataset. Its adjacent manifest lists the covered instance IDs,
44 metadata URLs, source Parquet checksum and official harness version. The 37,991
byte snapshot was downloaded separately from the running experiment's cache. All
500 public-only environment specs match those generated from the full official
rows, with HTTP disabled during verification. New Verified/activity/realtime
profiles point at this versioned file. Lite uses a different bank: prepare and
configure its own cache with the command below; do not assume subset coverage.
No Docker images are bundled. Real Linux image/container readiness must still pass.

## Prepare before an experiment

Use the SWE-bench optional dependencies (the project pins official harness 4.1.0).
Generate a NEW cache path rather than replacing a file used by a running experiment:

```bash
python -m tasks.swebench.http_cache /path/to/verified.json \
  --out /path/to/prepared/http-cache.json
# For a restricted pilot, append --instances django__django-16899 ...
```

The tool follows the official environment-spec generator's own requests at exact
repository/setup commits. It includes requirements includes, environment.yml where
needed, and original HTTP 404 responses used by the official path fallback logic.
Only official raw GitHub URLs are fetched. Non-200/404 responses and transport
errors are retried with bounded timeouts; they are never cached as usable metadata.
Original text, SHA-256 and source/fetch metadata are retained. All selected specs
are regenerated with cache-only reads before atomic publication. A failed batch
leaves any existing output untouched. This downloads metadata, not package wheels,
model weights or Docker images.

Point the next experiment config at the result:

```yaml
tasks:
  provider: swebench
  http_cache: /path/to/prepared/http-cache.json
  strict_http_cache: true
  evaluation_preflight: true
  repository_guidance: true
```

Prepare/pull the selected official instance images on the Linux Docker host before
launch. Then run a no-model first-draw preflight into a new output directory:

```bash
python -m tasks.swebench.preflight /path/to/config.yaml --seed 0 --out /path/to/new-preflight
```

Every newly selected issue, including replacement jobs, must pass the same gate
before its notice is published: offline official spec generation, exact local
instance image, fresh repository baseline and test launcher/settings checks. The
metadata probe uses allowlisted public fields and empty evaluation-only fields;
it does not inspect hidden tests or a gold patch. Check results contain metadata
checksums, image identity and URLs. This proves environment readiness, not that a
resident's repair will pass official tests. Missing images are not pulled by the
readiness gate. The official evaluation still uses unmodified dataset tests.

An unready replacement is held back and logged as `task_replacement_unavailable`
with reason `environment_unready`; it cannot revoke an already accepted job or its
payment. Missing initial readiness fails startup before residents begin.

## Strict acceptance

Strict mode prohibits HTTP fallback for harness metadata. A missing/corrupt cache
fails explicitly with the exact missing URL; it never silently accesses GitHub.
The provider takes a per-grading metadata snapshot and records its checksum so a
later shared-cache update cannot change an in-flight grading attempt. The evaluator
otherwise uses its original grading logic and original test data.

Strict metadata plus a prepared instance image addresses the observed requirements
fetch timeouts; it is not a blanket network sandbox for all third-party libraries.
The readiness checks do not download every possible package artifact.

## Background retry

Activity and realtime schedulers keep the original `SubmitWork` action, patch and
report pending when the provider returns `AssessmentUnavailable`. Workers retain
their job slots, receive an explicit automatic-retry notice, and may socialize or
rest. Submit is unavailable during this period; no new resident submission is
required. Partners retry the same shared pending job, not independent competing
snapshots. Actual failed test verdicts are returned normally for rework.

`simulation.activity_timing.assessment_retry_seconds` (default 300) sets the initial
simulated delay. Each repeated infrastructure failure doubles it up to
`assessment_retry_max_seconds` (default 3600). Each attempt remains bounded by the
provider's existing subprocess timeout. Retry count/deadline/action are persisted;
restore does not start a request before the recorded backoff expires. Daily grace
is added at most once per affected day, with the existing protection of pending
claims at day boundaries.

Final grading uses the existing bounded real-time wait. If backoff or grading is
still pending when that bound expires, the experiment remains resumable with the
submitted snapshot; it does not manufacture a pass/fail or discard the job. Legacy
scene-based synchronous submission retains its original retry behavior.
