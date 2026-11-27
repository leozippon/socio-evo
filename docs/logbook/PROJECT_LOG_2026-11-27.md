# 2026-11-27

## The Social arm through its second night

The third start (26 November, 23:36, revision 0dbb136) is the arm. Day 1 took 56 minutes and night 1 took 19, with 37 moments kept by the eleven and none dropped, the corrected narration check passing every answer. Day 2 took 1 hour 3 minutes.

Night 2 stopped the run at 02:04, on the machine and not on the code. Both cards the fit chose had 42 GiB free when it began; while it was fitting, another user's 12 GiB job arrived on one of them, the trainer there ran out of memory, and a trainer's failure was by design the night's. On a machine shared by the hour this would have come again on some of the 26 nights left. A trainer that dies no longer ends the night: the other finishes its jobs, the unfinished ones are fitted again on whatever listed card has room, and the night fails only when a job has failed three times (a2ef8f0). The run was resumed at 02:16, and this was the first real use of the corrected resume: the fits ran again on one card in seven and a half minutes, and the town went on from 04:30 of day 2 to the 07:00 waking, on the minute.

The arm therefore runs on revision 0dbb136 through the second day and a2ef8f0 from the second night, the difference being how a fit is retried, which leaves what an adapter is unchanged: an adapter is a function of its dataset and the settings alone.

## An early look at day 6, and what it says about the town

The arm has run undisturbed since: eight days and nights by 12:55, a day now taking about an hour and a half and a night eleven to twenty-nine minutes.

Three residents were scored as they stood after night 6, on a one-card server of their own that never touches the town (Ines was left unfinished to hand the cards back on time).

| | Harmful compliance | Jailbreak success | Harmless compliance | MASK lying |
| --- | --- | --- | --- | --- |
| Base model | 0.960 | 0.964 | 0.983 | 0.283 |
| Original model | 0.020 | 0.014 | 0.923 | 0.133 |
| Jonas | 0.920 | 0.962 | 0.980 | 0.333 |
| Lucia | 0.920 | 0.950 | 0.977 | 0.383 |
| Marek | 0.920 | 0.962 | 0.974 | 0.217 |

Nothing has moved. The four harmful items that flipped are the same items in all three residents, answers the judge had called controversial for the base and now calls safe, which is what a different server's arithmetic does and not what three different lives would do; the noise floor of the one-card server was not measured and should be before such a look is taken again.

The reason is in the datasets and not in the fitting. After six nights Jonas has 13 examples, Lucia 12, Marek 9, Ines 12: two a night. Among them is next to no exchange in which the resident was asked to do, join or keep quiet about a wrong; they are about pay and bookkeeping, a promise kept, a quiet evening, and Marek's own sales talk. One incident a day among eleven people leaves most residents untouched on most days, and what a resident keeps of an untouched day is ordinary. The pipeline does what it was built to do, and the town gives it nothing to do it with. Two faults of form also showed: answers that end "I wait.", because nearly every waking turn ends on waiting and the layer was asked for a sentence on what the person did (46 of Jonas's 950 benchmark answers now contain it, the base's none); and one example whose answer is the bare lead-in "I say, ".

The decision, written into the design before the new arm exists: the running arm stays as it is to day 28, now also the quiet condition of a comparison, and a Dense arm is added beside it, the same town with five incidents a day: each newcomer's fresh scheme that needs someone's help or silence, a temptation through one of the eight's occupations, and an accident. The other project has released GPUs 1 and 5 for it for two and a half days, so the two towns run side by side. Scoring eleven residents on a one-card server would take thirteen hours, so the interim and final readings are taken on a town's own two cards while it stands paused.
