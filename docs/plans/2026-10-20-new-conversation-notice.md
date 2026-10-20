# New-conversation notice and evening preference implementation plan

**Goal:** Make a newly available conversation visible promptly to residents choosing their next activity, and express the approved evening social preference without forcing social attendance.

**Architecture:** Mark the two existing conversation-opening events and reuse the current access check and cancellation recorder. Only an in-flight activity-selection decision is interrupted by an eligible opening; reply-body rules, normal Rest wakeups and Work decisions retain their present behavior. The restarted choice reads the latest observation and remains free to join or do something else.

**Tech stack:** Existing Python Activity/realtime engines, answer cards, event logs and pytest. No new Activity or subscription framework.

## Scope

Planning means the existing choosing-next-activity state: a decision has no current Activity. It does not mean Work tool choice or Conversation intent/body. The source event must be an actual opening marked conversation_started, not a later participant join or speech. Exclude the creator. Reuse conversation_access to require the existing location, openness, activity validity and public/invitation conditions; do not broadcast remote or inaccessible private conversations.

Record open_conversations as the changed field and the opening event sequence as the cause, using the existing decision/request IDs and one-record-per-cancellation logic. Activity selection must resume rather than be misclassified as a missing-Activity lifecycle stop. Preserve the latest draft and single current observation; if the conversation has closed before restart, use the latest options without automatically joining it. Preserve public_conversation and actual Rest wake behavior.

Replace the current evening-free sentence with the approved text: “After work, you would enjoy spending part of the evening with neighbours. You can share work experience and ideas that may help with your tasks, or talk about everyday life and make friends. Good relationships can bring mutual support in future work and life. Choose your own company and place, such as the restaurant, Café Linde, or the Anchor.” Venue examples should reflect the actual world when this shared engine is used elsewhere; retain the approved community meaning and keep information in one prompt location.

## Implementation and validation

1. Mark spontaneous and appointment-created conversation openings in runtime/activities/engine.py. Add the narrow selection interruption in runtime/realtime/engine.py, reusing the shared recorder and access check.
2. Replace the evening prompt at its existing daily_context source. Avoid adding duplicate system reminders or behavioral constraints.
3. Add focused tests for eligible public and invited openings, creator exclusion, inaccessible/remote conversations, Work and Conversation exclusion, ordinary Rest preservation, no repeated interruption on later speech/join, event/request linkage and a conversation closing before restarted selection. Check the fresh input contains available conversation information.
4. Run affected tests and the combined infrastructure, agent, interaction, activities, realtime, scheduler/activity-clock and community-config selection; run lint, formatting and diff checks. Update living scheduling documentation and project log, commit and push.
5. Verify a complete Zenith snapshot with the same Linux selection before changing the future default. Keep the original budget experiment running and the directed experiment paused; do not launch or resume an experiment in this task.
