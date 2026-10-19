# Workplace indoor access and coding hours

Workplaces (Workshop and the library) admit residents indoors from 07:00 to 22:00.
There is no separate workplace doorstep/outside location. Early arrival does not
choose Rest automatically. Co-present residents may start/join local conversations,
wait voluntarily, move, or use preparation-only Work tools.

Repository operations remain restricted to 08:00–12:00 and 14:00–18:00, and still
require a Work activity and an assigned job. Access does not authorize code reads,
edits, commands, tests, handoffs or submission outside those periods.

At 12:00 and 18:00 existing Work sessions end/pause; residents stay inside and
choose their next activity. Rest and Conversation are not interrupted by these
coding boundaries. Newly chosen preparation-only Work sessions must not be
repeatedly ejected. At 22:00 everyone returns home as before.

Both activity engines use the same access checks for arrivals, current facts,
appointments and conversations. On loading old activity state, workplace outside
flags are removed. Historical event files remain unchanged. The legacy scene
scheduler and the opening hours of social venues retain their existing rules.

Regression coverage: early/lunch arrival, optional rest, no premature repository
operations, automatic 08:00 tool eligibility, spontaneous chat and appointments
before coding hours, chat continuity through coding boundaries, repeated boundary
checks, delayed realtime command completion, private homes, checkpoint migration,
and the 22:00 home return.
