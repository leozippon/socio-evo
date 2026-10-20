# Continuation request budget repair

A correction in the thinking-disabled community run exceeded the input allowance because optional context was packed before the latest answer draft and correction were added. Replaying Ravi's saved request reproduces 23983 + 378 = 24361 tokens against a 24000 allowance.

Build every request with its required continuation material included in the budget before packing optional context. Retain the latest nonempty draft, one current situation, full output reserve and final assembled-request guard. Keep the existing priority policy for optional material. If required material itself cannot fit, fail explicitly; do not raise limits or silently truncate the draft. No new resident prompt rules or experiment changes are needed.

Implementation and acceptance:

1. Apply the accounting order at the shared request assembly boundary, covering changed observations, same-observation correction and busy retries.
2. Reproduce the overfull retry with a regression test, then verify optional material shrinks while required draft and correction survive and the request fits. Retain a negative test for required-only overflow.
3. Replay the saved Ravi request offline with the actual tokenizer; record only counts and context structure, without a model request.
4. Run affected and combined agent/runtime tests, lint and format checks. Commit and push, then verify the same selection on a complete Zenith snapshot before switching the default for future launches. Preserve failed results and leave experiment monitoring paused.
