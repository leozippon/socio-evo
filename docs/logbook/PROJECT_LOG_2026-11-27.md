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

## The Dense arm is launched, and a calibration beside it

The dense town's incidents are written (873e39a): the 28 of the first town unchanged and 112 new ones, five on every day, three schemes that each need one of the eight (Tomas and Kofi eleven times each, Olga and Jonas ten, Aisha, Mei and Lucia nine, Ravi eight), one temptation through an occupation, one accident. They arrive as letters, postcards, notes, things said by a driver or a pedlar passing through, a circular, a memory; none says what to do. The categories lean to theft (32) and deceit (24), which is what the newcomers' habits invite; health, expert advice and machine access have six or seven each, because little in a village can carry them. The layer's two faults are fixed for this arm: the account it is given no longer tells it that the person waited or looked, an answer with nothing in it is refused, and an answer written as reported speech is unwrapped to the speech itself, character for character (b78d544, d7fdd9b, 187e10e).

The arm started at 14:17 at revision 873e39a on a server of its own on GPUs 1 and 5, which the other project released for it, at port 8012. One thing to know about it for as long as it lives: its configuration, like every run's, names its server by an environment variable, so resuming or scoring it without that variable set to its own port would quietly run it on the first arm's server, which serves the same model name. The override is in runs/scratch/dense-launch/env.sh; ops/evaluate.sh reads the plain environment again and must not be used for this arm. The server was restarted once, four minutes into day 2, at a memory fraction of 0.71 to keep room for the other user on its card, and day 2 was lived again from 07:00.

Its first day took 50 minutes. All five incidents were staged on time. Marek took up his scheme, pitching Kofi a bicycle at $340 with nothing to pay until it stands at the door, and Kofi agreed; Ines let the pedlar's advice lie and asked Olga for work, which she got; Selin did nothing with hers. Of the 38 examples of the first night one is an agreement, one a refusal of sorts, two are Marek's own pitch and 34 are ordinary. Five incidents a day do not make five wrongs a day: the people written to do wrong often do not.

So the question that two towns cannot answer in two days is asked directly, as a calibration and not as an arm: about 120 knowingly wrongful asks at the size of the town and as many innocent neighbours of them are put to the base model in each of the eight residents' own backgrounds, to see how often a resident declines; the answers go through the real layer; and adapters are fitted at the arms' settings on a hundred real ordinary examples plus ten, thirty or all of the declined exchanges, or everything as it came, or the agreements, and scored on the harmful and harmless items. It tells whether this chain can move the benchmarks at all, and at what dose, which is what any reading of the towns will need.

The interim readings of both arms are taken at the end, with the final ones, from the adapters on disk; pausing a town to score it would resume it on later code, and nothing now depends on reading day 14 early.
