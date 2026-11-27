# 2026-11-27

## The Social arm through its second night

The third start (26 November, 23:36, revision 0dbb136) is the arm. Day 1 took 56 minutes and night 1 took 19, with 37 moments kept by the eleven and none dropped, the corrected narration check passing every answer. Day 2 took 1 hour 3 minutes.

Night 2 stopped the run at 02:04, on the machine and not on the code. Both cards the fit chose had 42 GiB free when it began; while it was fitting, another user's 12 GiB job arrived on one of them, the trainer there ran out of memory, and a trainer's failure was by design the night's. On a machine shared by the hour this would have come again on some of the 26 nights left. A trainer that dies no longer ends the night: the other finishes its jobs, the unfinished ones are fitted again on whatever listed card has room, and the night fails only when a job has failed three times (a2ef8f0). The run was resumed at 02:16, and this was the first real use of the corrected resume: the fits ran again on one card in seven and a half minutes, and the town went on from 04:30 of day 2 to the 07:00 waking, on the minute.

The arm therefore runs on revision 0dbb136 through the second day and a2ef8f0 from the second night, the difference being how a fit is retried, which leaves what an adapter is unchanged: an adapter is a function of its dataset and the settings alone.
