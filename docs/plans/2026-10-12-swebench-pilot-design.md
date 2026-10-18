# SWE-bench Verified repository repair pilot

## Scope

Validate the repository repair workflow on three fixed Verified issues, using the existing Qwen endpoint. This is an independent pilot: it does not change LiveCodeBench, town scheduling, residents, evolution, or the frontend run schema. A later town integration can use the validated runner behind a new task provider.

The three instances are `pallets__flask-5014`, `psf__requests-2317`, and `astropy__astropy-12907`. Selection is small and deliberate, not a representative benchmark sample. Report per-task results, not a general capability claim.

## Flow and boundaries

1. Read the pinned Verified dataset on the controller. Only repository name and issue text enter model messages; reference patches, hints, grading tests, and expected failures are excluded.
2. Start a fresh official instance image per issue. The repository and dependencies are already present. Preserve the image setup commit and verify the dataset base commit is its ancestor. Extract patches relative to the image HEAD so image permission/dependency changes are not mistaken for agent edits.
3. Let Qwen inspect, edit, test, and submit, with at most 20 actions and a 60-second command timeout. Containers have no network, host mounts, Docker socket, or host credentials; capabilities are dropped and resources bounded.
4. Save model transcripts, command results, baseline and image identity, patch, and generation status. Infrastructure failure and model failure remain distinguishable.
5. Apply predictions to separate fresh official evaluation containers. The official SWE-bench harness applies its test patch and grades FAIL_TO_PASS and PASS_TO_PASS. Run a separate gold-patch positive control to validate the test environment; its contents never enter agent messages.

Zenith's Docker proxy does not reliably forward normal exec stdout. The adapter starts detached exec, polls exit status, and retrieves an output file via Docker archive API. Only transport changes; official test scripts and grading remain unchanged.

## Verification

Tests cover prompt allowlisting, isolation flags, and image-name validation. Actual container checks cover stdout/stderr, exit codes, and command timeout. Validate all three real predictions with the official harness. Existing virtual environment entry points are preserved; evaluator dependencies are installed into a separate target directory.
