# Activity prompt simplification

## Decision

Keep the resident's stable identity and enduring town rules in the system context. Put the present time and place, people, activity state, available tools and immediate constraints in the current Activity prompt. Each fact should appear once; the activity card is the concise set of choices that can be made now. Environment-generated `help` supplies detailed instructions only when requested.

Apply this prompt contract to both `activities` and `realtime`. Keep the differences in their scheduling documents: configured simulated costs for `activities`, observed wall-clock runtime and direct speech delivery for `realtime`. Prompt brevity does not replace launch-time checks for tool availability, time boundaries, access, membership, work ownership, official acceptance or settlement.

## Documentation scope

`activity-scheduling.md` owns the shared activity model, fixed-cost timing, work and conversation rules, and checkpoint behavior. `realtime-scheduling.md` documents only the wall-clock, direct-speech and settlement differences. `summary.md` introduces both opt-in modes while retaining the original scene scheduler and existing configurations as available behavior. Historical scenes remain part of the project and are described with their scheduler explicitly named.

## Baseline

The design was prepared against `f5f41af` in the `codex/feature-development` line. Historical scene scheduling remains supported and is documented separately from the two opt-in Activity modes.
