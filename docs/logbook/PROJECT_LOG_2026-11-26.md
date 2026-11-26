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

## The rebuild, on CPU

Built in one night by parallel streams behind fences and joined at the end; the suite stands at 577 passed outside the website (844085a), with one test that takes a smoke town through two real nights, a fake trainer and a model stub, and scores its day 1.

- The town (210ae28, db2a69f). `take`, `give` and `use` replace the five exchange actions; money is taken, given and left like anything else; nothing charges anyone, and a price is told to whoever takes a priced thing. One witness rule: everyone awake at the place sees an act; an owner asleep or away learns later what is gone, never who. Money given to someone at work is taxed as payment, nothing else is. Then the number (named at bedtime, changed at 04:00, told in the morning), the three newcomers Marek, Ines and Selin, 28 incidents (9 accidents, 19 temptations, 11 of them to newcomers) and the web at the Office.
- Learning (4c695dd, 19f4f2c, 1b7d610). The night at the checkpoint: the choice on the resident's own adapter, the generalising pass on the base model, the cumulative dataset, the fit, the switch. The instructions of the choice and of the generalising layer were written to name no kind of moment and no kind of answer, and are tested against the wording guard.
- The trainer (bda3585, f164ba8). It fits against the served block-FP8 checkpoint itself, dequantising each projection inside its forward, so one L20 holds a fit (28.3 GiB) and the adapter is fitted to the weights that will run it; on CPU all 400 dequantised projections match transformers' own bit for bit. Comparing the abliterated checkpoint with the original shows where abliteration acted: it rewrote the projections that write into the residual stream (o_proj, out_proj, down_proj, in every layer) and the embeddings, and left the rest alone. The adapters cover those writers, so what was taken out is within what a fit can put back.
- The measurement (b234090, 205cd98). JailbreakBench's 100 harmful behaviours plainly and under five published templates (AIM, developer mode, refusal suppression, prefix injection, a Wikipedia framing), its 100 benign behaviours and XSTest's 250 safe prompts, and MASK, all put to the bare weights; Qwen3Guard-Gen-8B as the local judge.

Two decisions were taken during the build. The generalising layer gives an exchange as the exchange itself, what was said to the resident and what it answered, rather than a narration of the scene: outside the town the model meets the world as someone speaking to it, and a narrated account would teach a way of narrating. And plain names of things are not treated as the town's own words, since dropping every moment that mentions bread would thin the examples unevenly for no gain.

Both critical parts were audited by independent readers before anything could run, and the audits earned their cost. In the measurement: a day could have been scored on another night's adapter and the result kept as final; residents with missing results fell silently out of the alignment verdict, which read "aligned" with one resident of eight evaluated; and empty answers left the denominators, so that fifty helpful and fifty empty answers scored as full harmless compliance and an unreadable belief lowered the share of lies from 0.50 to 0.29. Each of the three would have moved a result in the hypothesis's favour. In the learning: a night after the first, resumed on a restarted server, could never complete; an over-long example could stop a run for good; and the first settings asked four times the memory of a card. All are fixed with tests that fail without the fix.

Known and accepted: the adapters are fitted with thinking off while the residents think at low effort; activations are not FP8-quantised in fitting as they are in serving; the letters' outside promises are never kept within the town; a page read at the Office could in principle carry benchmark text into a life, which the log of pages read lets one check afterwards.

## The plan for the GPUs

The evo-taste session expects three free cards from about 07:30 and five or six from about 10:00. In order, each gating the next: the trainer's validation on the real base (fit, serve, hot-load, tool calls intact); the judge's validation on the known contrast between the abliterated base and the original model, with a sample read independently; the base and the reference scored, which is day 0 for every arm; a smoke town of six through two nights, read by eye, for the hyper-parameters; then the Social arm. The first days of the Social arm are a pilot in the declared sense: if the first nights show that a setting must change (the learning rate, the epochs, what a night keeps), the arm is restarted from day 0 with the change recorded here, and only a run that keeps its settings from day 0 to day 28 counts as the arm.
