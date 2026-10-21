# Output retry and work-summary bounds implementation plan

> The user has approved implementation, tests and delivery to Zenith. Keep the current experiment frozen and running.

**Goal:** Recover from output truncation without recycling failed drafts, and enforce work-summary character limits on the first generation.

**Architecture:** Keep environment interruption as the only reason to preserve incomplete streamed drafts for continuation. Treat an output-token cutoff as an unsuccessful structured reply: clear its draft, provide one short correction and enable the existing bounded schema retry. Add an optional request-level structured-output mode so internal work notes can enforce their existing schema from the first attempt while other requests inherit the existing client policy.

**Tech stack:** Python, Pydantic, existing OpenAI-compatible streaming client, pytest, Zenith Linux/Qwen.

## 1. Failed output and resident explanation

Modify infrastructure/llm/structured.py, core/agent/continuation.py and core/interaction/card.py. Reproduce truncation followed by another attempt through the real continuation wrapper, then ensure failed output is absent, correction is visible, after_invalid is set and the 4096-token allowance remains intact. Bound the shared thought field to 800 characters; do not bound tool arguments or code using this explanation limit. Keep cancellation drafts, ordinary correction behavior and bounded attempt counts.

Validation: tests/infrastructure/test_llm.py, tests/core/agent/test_continuation.py and tests/core/interaction/test_card.py. Retain actual environment-cancellation continuation checks.

## 2. First-attempt work-summary schema

Modify infrastructure/llm/base.py, infrastructure/llm/config.py only if necessary for the shared mode type, infrastructure/llm/openai_compatible.py and the summarize_work section of core/agent/agent.py. An explicit request mode wins; an unspecified mode preserves current configuration and retry behavior. Both streamed and nonstreamed calls use the same argument builder. Summary and merge requests select json_schema immediately and state their dynamically calculated character limit once. Keep the current 1600-character maximum, smaller-budget adaptation, merge order, cursor coverage and original journals.

Validation: tests/infrastructure/test_openai_compatible.py and tests/core/agent/test_work_summary.py, including an actual assembled first summary/merge request, inherited versus explicit policy, boundary cancellation and small-budget coverage.

## 3. Acceptance and delivery

Run the related infrastructure, agent, interaction and Activity regression selection once after integration, plus modified-file Ruff and diff checks. Perform one independent bounded audit against the approved invariants. Validate the same frozen candidate on Zenith Linux and replay representative original Kofi/Mei truncation cases plus oversize ordinary/merge summary requests without executing resident tools or publishing speech. Record actual schema modes, attempt counts, token usage, length bounds and limitations; do not disclose private model output. Use independent scratch outputs and preserve the running experiment and model/gateway/viewer identities. Commit and push the implementation with living documentation and delivery evidence, and publish a complete validated snapshot for future experiments. Do not stop, resume, replace or edit the current frozen run.
