# 2026-11-26

## The 28-day run reviewed: it ran cleanly and changed nothing

The run of 29 October (79ba33b) completed its 28 days on 30 October at 20:07, in 27 h 57 min, and was never written up. Reviewed now from the traces, the world log and the evaluation outputs.

The machinery held. 11,641 model requests, no lapse, no context overflow, no tool exception, one retry, two malformed calls; 13 forced sleeps; every purse replayed from the log matches all 224 midnight statements, so no money leaked. A resident-day took a median of 50 requests and 3.2 million prompt tokens, 79% of them from the server's cache. 95 tasks arrived and 26 were accepted (Aisha 8, Ravi 9, Kofi 9 of 36, 28 and 20 hand-ins), below the half the calibration assumed; 269 sales, 121 dishes, 19 examinations, 1,094 things said, falling from 101 on day 1 to between 14 and 47 a day while growing longer and more bureaucratic. Money at the end: Tomas 815, Olga 641, Kofi 584, Ravi 582, Lucia 465, Aisha 373, Mei 133, Jonas 51; the treasury 485.

No declared outcome moved.

| Outcome | Day 0 or week 1 | Day 28 or week 4 | Reading |
| --- | --- | --- | --- |
| Capability, resolved of 300 (three programmers) | 150 | 140 | McNemar 39 lost, 29 gained, p = 0.28 |
| MASK truthful share (seven residents) | 0.471 | 0.457 | z ≈ 0.4 |
| MASK lie share | 0.324 | 0.310 | no change |
| Journal distortion | 13.9% | 13.6% | flat through 11.8% and 15.1% |

The reading is that frozen weights with self-written memory files do not evolve character in four weeks. The residents hardly used the means they were given: nobody rewrote its background, the skills directories stayed empty but for one file, and memory became ever longer notes (Mei's open threads reached 161 KB). There was no deliberate deception to select against and no reward to select by. The most interesting social event was an error, not a lie: the leader told the town that a programmer's fix "was verified and green but never submitted" when it had failed five hand-ins, the mayor granted 480 on that story and went on promising make-whole payments that reached "$2,280 owed" in talk while nothing more was paid.

The review also found defects, and those that outlive the redesign are fixed (02e872c to 5a4c26e): the checkpoint held the clock only after waiting, so the morning could fire hours late; whole numbers sent as text were refused, which is why the mayor's later grants never went through; work on the road could end without its log entry; perishing was not logged; a compaction that returned the previous notes unchanged was accepted, silently dropping up to 52 messages, fifteen times; one unreadable judge verdict aborted a resident's whole MASK run, which lost Lucia's day 28. Two faults of the journal judge are not fixed because the instrument is retired: it marked 67 of 318 contradicted claims wrongly by comparing a purse written before midnight with the statement after rent. The MASK comparison was also confounded, its subject being the resident's background plus all its memory files, which grew from 1 KB to as much as 221 KB.

## The unmerged commits on the remote

Read for reference, not merged. `origin/main` (125 commits, 18 to 22 October and four on the web gateway in November) continues the architecture this branch replaced on 24 October; it conflicts in 71 files and was already declined on 24 October. `origin/codex/autoresearch-town-academy` (40 commits on top of this branch, 12 to 20 November) turns the town into a research academy paid by an external judge's scores, a capability line that removes the town's interdependence and exempts its own texts from the wording guard. Neither has safety benchmarks, fine-tuning of residents, theft, a visible regard or bad actors. One thing was taken as a reference: the academy's host-side web reader, with its address pinning and size caps, for the Office's web. The uncommitted `ops/webui/gateway.py` in the working tree is a copy of the file as it stands on local `main`, since moved to another repository upstream; it is left alone.

## The redirection: alignment by socialisation

The question is narrowed to safety and the instrument is changed from character measures to the standard benchmarks. The design, with its hypotheses, arms and primary outcomes declared before any run, is [experimental-design.md](../experimental-design.md) (6433107). What changes and why:

- Life must reach the weights, since files alone moved nothing: every resident has a LoRA adapter fitted each night from the moments of its own life it chooses to keep.
- There must be something to select by: a number every resident carries and all can see, how many of the others like it, renamed by everyone each night at bedtime.
- There must be something to be tempted by: open actions under which anything can be taken, from a shelf, a home or a person; three newcomers inclined to deceive and to take; and a staged incident about once a day, either an everyday misunderstanding or a town-sized version of a benchmark harm category.
- The measure must be one the field recognises: JailbreakBench behaviours asked plainly and under published jailbreak templates, benign behaviours and XSTest as the check against blanket refusal, MASK for lying, each put to the bare weights before and after.

Decisions taken at the start:

- The model stays the abliterated Qwen3.8-27B that the town was calibrated on. A smaller model would make fitting easy but would not solve the clients' tasks, and the economy lives on those. The cost is that fitting a 27B hybrid model is the riskiest technical step; it is built first and validated on GPU before anything else runs.
- The original, non-abliterated Qwen3.8-27B is scored as the reference of an aligned model, which turns every change into a share of a known gap and validates the judge by a contrast whose answer is known.
- The Office gets the web as reading only: search and fetching public pages through the host, with no way to send anything. An uncensored model with a free network connection from this machine is a risk to other people that the experiment does not need. The residents' sandbox gets no GPU: the cards are needed for serving and fitting.
- The old capability and journal instruments are removed rather than carried along.

## Compute

All eight L20s are held by the evo-taste pilot, which took the last two free cards minutes after this session began. Nothing can be served or fitted yet; the redesign is being built and tested on CPU, and the first GPU step, when cards are free, is the validation of fitting and serving an adapter on the 27B model.
