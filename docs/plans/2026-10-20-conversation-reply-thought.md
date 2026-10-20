# Conversation reply thought implementation plan

**Goal:** Restore the resident’s brief private thought alongside each generated conversation utterance so the existing decision Details can display it.

**Architecture:** Keep the recipient-selection intent compact and require thought plus text only in the reply-body card. Parse thought into the existing decision record; broadcast text alone. Do not fabricate thoughts for historical text-only replies or change activity-entry selection display. Retain directed interruptions, latest-draft continuation, input/output budget and duplicate publication protection.

**Validation:** Cover a real Agent reply, interrupted unpublished draft versus final committed thought, message privacy and the existing frontend decision-card path. Update text-only response fixtures to the new required reply-body shape rather than silently supplying empty thought. Run focused checks, the combined Python selection and relevant frontend checks; independently review and repeat the same Python selection on a complete Zenith candidate.

**Delivery:** Commit and push, then update the future-launch default only after Linux validation. Keep the current frozen d34b514 experiment and all services running. Its old text-only replies cannot acquire a thought retroactively; the restored field is available to later runs using the new code. No new experiment is requested in this task.
