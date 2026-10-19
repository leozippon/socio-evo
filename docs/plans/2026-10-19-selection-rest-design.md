# Rest transition during realtime activity selection

Record otherwise unassigned realtime intervals as `Rest · Choosing next activity`.
This is an automatic transition state, not an intentional sleep and not a fifth
activity type. It begins at day start or actual activity exit and ends only when
another activity is successfully entered, or the day/engine closes. Selection-level
help, invitation acceptance and rejected requests do not end it. The shared clock
and existing decision/invitation/workspace semantics remain unchanged.

Use research-only activity membership events (no added resident percepts) with `activity_type: rest` and
`phase: choosing_next_activity`. Keep this recording state separate from `current`,
which selects executable activity tools; otherwise entering rest would incorrectly
suppress choose_activity and interfere with invitation readiness. Record no extra
fixed duration or timer. Do not backdate decisions or extend completed work.

Expose the phase in the existing timeline, ledger and tooltip labels. Older logs
remain unchanged; do not invent transition states in historical experiments. Keep
zero-duration real transitions as evidence rather than silently deleting them.

Verify continuous membership boundaries, unsuccessful selection, help, conversation
joining, day closing and cancellation using controlled wall clocks. Check frontend
phase labels, duration accounting and private visibility with replay fixtures.
Do not modify or restart the current frozen experiment.
