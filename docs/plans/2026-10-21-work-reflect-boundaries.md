# Work reflection at activity boundaries

**Goal:** Generate a brief work overview after actual job execution, including at forced daytime transitions.

**Architecture:** Keep private raw journals separate from the trigger predicate. Only executed commands and real test receipts qualify a visit. Work ends, a fixed-source Reflect saves one overview per visit/job, then the stored next action continues. Noon lunch and evening transitions wait for that Reflect. Day-end/interruption retains pending sources for nightly catch-up. Existing finite retries, ownership boundaries and checkpoint identities remain authoritative.

**Implementation:** Narrow scope eligibility in `core/agent/memory/work.py`, shorten work-summary instructions in `core/agent/reflection.py`, and unify work exits/continuations in the existing Activity engines. Keep personal experience review and diary behavior separate. Preserve historical records and completed scopes.

**Verification:** Test guide/closed/claim-only visits, executed successful and failed commands, real tests, 15x realtime summaries crossing noon, in-flight tools, repeated scheduler ticks, evening boundaries, cancellation/checkpoint recovery, repeated visits to one Work and once-only persistence. Run the combined regression and one bounded independent audit. Validate the exact committed candidate on Zenith Linux and with an isolated actual-model noon-transition probe before updating the shared default; preserve the frozen running experiment and service identities.
