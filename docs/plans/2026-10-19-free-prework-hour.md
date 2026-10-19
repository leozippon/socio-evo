# Free preparation before work

07:00–08:00 remains an optional free period with the existing four activities.
At home a resident may enter Work to inspect the public board, claim a job, read
past feedback/notes or send partner invitations. No repository reads/writes, shell
commands, tests, handoffs or submissions are unlocked before 08:00. Existing venue
opening hours and private-home access remain unchanged: physical conversation
requires an open location and co-presence; appointments/invitations can be sent
without co-presence. Early arrivals still wait outside closed workplaces.

Add authoritative, time-scoped user/system/help instructions and current travel
estimates/departure times so residents can prepare before travelling. Do not force
a plan, a new activity or a move at 08:00. Check both activity and realtime engines:
preparation/claim at home, tools blocked before opening, early arrival/admission,
work resumption with preserved claim, optional rest and household conversations.
Correct the realtime-only stale 'choice costs no time' wording while preserving
legacy deterministic timing. Test and commit locally; leave the live run unchanged.

Verified: 12 new checks cover both activity and realtime engines; the complete
related regression selection passes 308 tests. Ruff check/format and git diff
--check pass. The live experiment and frozen configuration were not modified.
