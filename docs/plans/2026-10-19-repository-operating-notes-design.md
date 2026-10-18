# Repository operating notes and environment preflight

Approved: add fair, shared repository instructions, environment preflight, and pipefail
locally; do not sync, restart, resume, or modify the currently running experiment.

New community configurations enable `tasks.repository_guidance`. Before an issue is
posted, probe a fresh official container without reading gold patches, hidden tests,
hints, or per-issue test lists. Django checks its repository test runner and test_sqlite
initialization; other repositories check the installed pytest launcher. Unsupported or
broken environments block posting with an explicit infrastructure exception, never a
resident failure score. This is launcher validation, not a full-suite health guarantee.

Instructions tell every worker the same environment facts and generic invocation;
residents still choose relevant tests, implement fixes and interpret results. Preserve
patches only; warn about ephemeral environment variables/packages/ignored files.

Record preflight output, image ID, baseline and timestamp under repositories/preflight.
Cache success only for this provider process; resumed runs recheck before first work,
and refuse a workspace image different from its verified image. Disposable containers
are removed after both successful and failed probes.

Enable Bash pipefail inside the existing shell/timeout boundary. Test a failing upstream
command piped through tail and a successful pipeline, plus failed probes, cleanup,
privacy, cache behavior and old/default configuration behavior. No live environment
validation is claimed by mocked Docker unit tests.
