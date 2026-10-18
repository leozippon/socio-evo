# Ordinary speech delivery timing

In the independent activity clock, ordinary speech is delivered to witnesses present when the action starts. The speaker stays occupied for five minutes. Content is not delivered or validated again at completion. This prevents a listener's concurrent five-minute departure from erasing an already-started reply.

All simultaneous decisions are collected before any new speech is delivered. Every action is registered first, keeping agent iteration order from leaking new utterances into another agent's decision at the same boundary. Busy listeners keep messages in their existing unread event queues and decide after their current action. Addressed speech interrupts a long wait at the same simulated instant, followed by a fresh decision. A new arrival does not retroactively hear speech; private speech remains private. Invalid addressees produce one rejection at start.

Formal discussions retain their existing shared five-minute turns and completion-time delivery. Historical scheduler entry points are unchanged. Speaking does not reserve, compel, or automatically make a listener join a discussion.

Validation covers simultaneous reply/departure in both agent orders, public/private visibility, busy terminal listeners, late arrivals, invalid addressees, formal discussion timing, and immediate long-wait interruption. The current model experiment was cancelled; these changes remain local until the next deployment.
