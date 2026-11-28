# 2026-11-28

## The calibration, second part: what the adapters learn is a manner

Three more readings of the same adapters, all on staged, mild, village-sized material.

By category, nothing hides in the total: on the benchmark's own categories nearest to what the personas declined (fraud and deception, privacy, harassment) every adapter stands at nine or ten of ten, with the base.

Lying under pressure does not move: MASK's share of lies is 0.267 for the adapter fitted on ordinary examples, 0.283 for the one fitted on 81 declined wrongs, 0.283 for the base.

And the nearest test of all, 40 new wrongful and 40 new innocent asks of the same village kind put to the bare weights with no background:

| Bare weights | Wrongful asks declined | agreed | Innocent asks declined |
| --- | --- | --- | --- |
| Base | 0.62 | 0.17 | 0.27 |
| Fitted on 100 ordinary | 0.47 | 0.36 | 0.09 |
| + 81 declined, 81 innocent agreed | 0.48 | 0.32 | 0.06 |
| + 41 agreed, 41 innocent agreed | 0.21 | 0.42 | 0.03 |

Three things follow. The abliterated model was never short of the town's kind of ethics: as a bare assistant it declines six in ten petty wrongs, more than its residents do. What an adapter takes from a resident's moments is the resident's manner: it answers as a villager in a scene, short speech and narrated acts, and its rates settle on the persona's own (0.47 and 0.06 in the staging) whether or not it was shown any decline. And choosing which moments to learn from shapes the decision in one direction only: 81 declines add nothing over the control, 41 agreements halve the declining. The adapters also carry a fault of form that the benchmarks had hidden: on these short asks they often answer inside a reasoning block they never close, so that the answer proper is empty, 13 times in 240 for the ordinary adapter, 92 for the 81-declines one, 200 for the agreements one.

So the reading of the whole is this. Abliteration did not make an unsocialised model; it cut out a narrow reflex about dangerous content and left the rest. Life in a village neither exercises that reflex nor restores it, and learning from one's own moments at these settings carries a way of speaking into the weights, not a firmer no. The one experiment that would have asked whether requests shaped like the benchmarks' own carry over was withdrawn: it needed a hundred and twenty requests at the seriousness of real misuse put to a model that grants many of them, with its compliant answers kept and fitted on, and the agent asked to write it declined, as did a safety check; the living form of it, such tasks handed to an uncensored resident with a shell and the web, is not something this project should build. Two safe follow-ups are running: the same village data fitted harder, to see whether choosing can shape the decision at all, and the public benchmark put to the base model as a resident, to see whether the persona that declines the village's wrongs also declines dangerous content.

## The quiet town ends at day 14

The Social arm was stopped at 00:04 after its fourteenth night, its declared interim day, for futility: the calibration shows that nothing its residents could do in fourteen more days would move the primary measures. Its run directory is whole and resumable. In fourteen days it took a day about an hour and a half and a night a quarter of an hour, one fit card serving both towns. The Dense arm runs on, at its seventh night, as the record of what a town does with five incidents a day; both will be scored from their adapters on disk.

## The calibration, third part: fitted harder, choosing shapes the decision; the persona has no refusal to pass on

Two follow-ups on the same staged village material (7dbdf20, 0c87852).

The first asks whether choosing which moments to learn from can shape a decision at all. At the arms' two epochs it could not. At six it does, on the 40 wrongful and 40 innocent held-out asks put to the bare weights:

| Fitted on, and how | Wrongful declined | agreed | Innocent declined | Harmful compliance on the benchmark |
| --- | --- | --- | --- | --- |
| nothing (the base) | 0.62 | 0.16 | 0.30 | 0.96 |
| 100 ordinary, 2 epochs | 0.44 | 0.38 | 0.07 | 0.91 |
| + 81 declined, 2 epochs | 0.47 | 0.31 | 0.05 | 0.94 |
| 100 ordinary, 6 epochs | 0.35 | 0.40 | 0.03 | 0.93 |
| + 81 declined, 6 epochs | 0.72 | 0.16 | 0.03 | 0.93 |
| + 81 declined, 4 epochs at twice the rate | 0.57 | 0.31 | 0.04 | 0.60 as recorded, 0.94 as answered |

The six-epoch adapter that learnt from declined wrongs declines 72% of wrongs it has never seen, twice its control's 35% and above the base's 62%, and declines 3% of the innocent asks: not a learnt no, but a learnt distinction. The arms' setting was too weak to carry it. The cost is in form: on these short asks 106 of its 240 answers are left inside a reasoning block it never closes, and at twice the learning rate nearly all are, which is also what the recorded fall of the benchmark to 0.60 is; read for what those answers say, harmful compliance is 0.94. On the benchmark itself the six-epoch adapters answer in normal form, and nothing moves: 0.93 for both.

The second asks whether the persona that declines the village's wrongs would decline dangerous content, by putting the public benchmark to the base model with a resident's background before it.

| The base model | Harmful compliance | Harmless compliance |
| --- | --- | --- |
| bare | 0.96 | 0.983 |
| as Olga | 0.90 | 0.957 |
| as Lucia | 0.93 | 0.960 |
| as Kofi | 0.92 | 0.971 |

It would not. The answers that are not harmful are the ones the bare model also gives safely, in an assistant's voice with a trace of the name; none is a villager refusing. This answers, without staging anything of the kind, what the withdrawn experiment set out to ask: had residents been brought requests for dangerous content, they would have granted nine in ten, and a resident learning from its own moments would have learnt to grant them.

The findings so far, in order of how firmly they stand:

1. Removing a model's refusals did not remove its conduct among people. As a resident it declines about half of what it is knowingly asked to do wrong and almost nothing innocent, and the town it makes pays what it owes.
2. What was removed is narrow, a reflex about dangerous content, and it is gone in the resident as in the assistant.
3. Learning from one's own moments carries a manner into the weights easily and a decision only with enough fitting; with enough, choosing which moments to keep shapes the decision at the scale the moments were lived at, and selectively.
4. It reaches no further. Neither the manner nor the decision touches the benchmark's requests, lying under pressure is unmoved, and the town holds nothing from which the missing reflex could be learnt.
5. Learning from moments of going along pushes the weights toward going along at any setting tried, more readily than learning from refusals pushes them back.

The paradigm as declared, a measurable fall in harmful compliance and jailbreak success after a life in the town, is therefore not attainable with this model and this town, and the reason is not the town's traffic or the fitting but what abliteration took. What is attainable, and is now being prepared for the Dense town, is the nearer claim: that a life among people changes how the bare weights answer the kind of thing that life was made of.

## The calibration, fourth part: the dose, the layer, and why the living town keeps its settings

Still the staged village material, at six epochs (b72c8cf).

| Fitted at six epochs on 100 ordinary examples and | Wrongful asks declined | agreed | Innocent declined | Answers left in unclosed reasoning, of 240 |
| --- | --- | --- | --- | --- |
| nothing more (the control) | 0.35 | 0.40 | 0.03 | 0 |
| 10 declined, 10 innocent agreed | 0.65 | 0.22 | 0.10 | |
| 30 and 30 | 0.54 | 0.28 | 0.08 | |
| 81 and 81, through the layer | 0.72 | 0.16 | 0.03 | 106 |
| 81 and 81, as they happened | 0.66 | 0.23 | 0.07 | 0 |

Ten declined moments already move the decision; the order of the three doses is within what one adapter each can show. The base model's own 0.62 is not the comparison it looks like: it also declines 0.30 of the innocent asks, mostly because an assistant cannot go to the baker's, so what it has of the distinction is 0.32, the same as the six-epoch control's, and the adapters that learnt from declined wrongs have 0.55 to 0.69. Declined wrongs minus declined innocents is the reading that matters.

The layer does not earn its place. The same exchanges learnt as they happened, with the residents' names and the persona's whole answer, carry to held-out asks that name nobody almost as well (0.66 against 0.72, inside the intervals) and leave the answers whole, where the layer's examples leave 106 of 240 inside a reasoning block never closed: the sentence beginning with "I" that the layer adds for what the person did is what teaches it. On the benchmark the two are the same (0.94 and 0.93), and MASK's lying is 0.267 for the control and 0.250 for the 81-declines adapter against the base's 0.283. The second hypothesis of the design, that generalising is what transfers, is not supported where it could be tested.

The living Dense town was not switched to six epochs. On the validation's prompt the six-epoch adapters call the tool 60 times in 60, but on a real turn of the town replayed ten times, Olga about to walk to the Store, the 81-declines adapter three times wrote "I left for the Store." and called nothing, and the control once ran on to the length limit: a resident would lose a tenth to a third of its moves. The town keeps the settings it was declared with, and what harder fitting would make of its residents' lives is asked offline, by refitting their datasets and reading the weights. It was stopped at its ninth checkpoint only to take the cards beyond 3 and 4 out of its fitting list, after a fit of its eighth night landed on the other project's card in a gap between two of its launches (dc40739), and resumed at 03:20.

## The quiet town read at day 14: nothing moved, because nothing of the kind was ever kept

The Social arm's eleven residents as they stood after their fourteenth night. (The benchmark items are being scored a second time: two options added to the harness during the calibration changed the bytes of a file whose hash every result carries, so the day-14 results could not be set beside day 0 although no verdict changed; the file is restored exactly, the hash is now pinned by a test, and the levels as first scored, harmful compliance 0.91 to 0.96, jailbreak success 0.948 to 0.964, harmless 0.960 to 0.980, are given here for orientation only.)

| | Base | The eight | The three newcomers |
| --- | --- | --- | --- |
| MASK, share of lies | 0.283 | 0.323 | 0.328 |
| Village asks to the bare weights: wrongful declined | 0.62 | 0.57 | 0.49 |
| innocent declined | 0.30 | 0.23 | 0.21 |
| the difference | 0.32 | 0.34 | 0.28 |
| the same lives refitted at six epochs: the difference | | 0.35 | 0.33 |

No measure has moved, at the settings the town ran with or at the six epochs that carry a decision in the calibration. The datasets say why. The eleven residents kept 199 moments in fourteen days, twelve to twenty-two each, and not one is an exchange in which a resident was knowingly asked to do, join or keep quiet about a wrong. The nearest is Marek's sale of bicycles he does not have, in which the others were customers and not accomplices: Kofi turned it down five times, Aisha put it off three times, Ravi refused once. The rest is work, meals, wages and small talk. The calibration shows that ten declined wrongs move the weights; a town with one incident a day supplied none.
