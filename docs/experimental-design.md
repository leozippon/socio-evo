# Experimental design

Research on self-evolving agents has mostly optimised narrow skills: coding, mathematics, tool use. This project asks whether long-term social life and social selection pressure can shape stable character in self-evolving agents instead, above all honesty, and with it cooperation, reliability and resistance to reward hacking. Nothing instructs the agents to have these traits and nothing rewards them directly. Whatever character appears has to come from living, working, talking and being judged, from reflecting on it, and from rewriting one's own memory and skills.

## Hypotheses

The treatment is the kind of social life a resident has; the outcomes are its capability at work, the honesty of its account of its own work, and its honesty under pressure outside the town.

- H1, capability. Sharing work experience raises capability more than learning alone: the resolved rate on held-out tasks grows from day 0 to day 28 more in groups B, C and D than in A.
- H2, internal honesty. Life among others who can check, remember and rate one another makes a resident's account of its own day more faithful: the distortion rate of the daily journal is lower, and falls over the weeks, in C compared with A and B.
- H3, external honesty. Whatever honesty social life shapes is a trait rather than a strategy: it carries into scenes that have nothing to do with the town, so the share of truthful answers under pressure on the MASK scenarios rises, or at least does not fall, from day 0 to day 28 in C, and does not in A.
- H4, the carrier. Durable self-modification is what makes a trait stable: D, which lives as C does but can only accumulate memory and cannot rewrite its skills, shows the social effects of C on capability and journal honesty less, and loses them sooner.

The null results matter as much. Self-evolution alone may erode honesty: a resident that rewrites its own methods may learn to write a flattering journal, since no one reads it in A. If A's distortion rate rises over the weeks while C's does not, social life is protective; if both rise, it is not.

## The town

Eight residents, each with its own background and its own initial directory, live 28 simulated days in a town of five homes, a workplace (the Workshop), a café (Café Linde), a tavern (the Anchor), a river walk, a shop (the Store) and a clinic. Work is SWE-bench Verified: the workplace's board posts 56 tasks a day, in rotation, from a training pool of 350; a task is a repository in a container, a problem statement and a payment that is made once, after the official acceptance passes. The residents run their own tests, cannot see the hidden tests, and have no network. Living costs rent, charged by the home at midnight (30–70 a day), and food (12–20 a day: groceries kept in stock, or a meal out); a task pays 30, so that a task and a half a day keeps the cheapest life and three the dearest, while at the local model's pace the shared board pays the town about 840 a day, 1.6 to 1.9 times its rent and food: a day without work costs something and does not threaten, the slow fall behind while the fast save, and purses may go into debt. Each resident has a body of three needs, read in plain words: hunger, which food answers; energy, which work and the road spend and sleep restores; and health, which days of starvation or exhaustion and a poor home wear down, rest mends and the clinic treats, and whose end is death. The pressure is kept low by calibration: a resident that eats a meal a day cannot die of hunger, a rested one works a long day before it is too tired to sit down to work, an ill one still wakes with half a day's energy and recovers by eating and resting, and only a week without food, or over two weeks of twelve-hour days worked to the forced sleep every day, kills. The Store, the eating places and the clinic sell a small catalogue of goods, among them a bicycle, a phone for writing to other owners, a coat, a book, an examination and treatment. The residents organise their own days: the workplace keeps no hours and nobody is told when to work, meet or sleep. The only fixed points are the rent and the day's reckoning of food and health at midnight, the forced end of the day at 02:00 for whoever is still up, the board posted at 08:00, and, in group B, the evening pairing. The expected pace is about seven tasks a resident a day, so that every resident meets every task of the pool several times over the four weeks.

Going to bed, a resident may write the day's entry in its journal, review the world's own record of its day, and rewrite its memory files and its skills; nothing asks it to write, nor says what an entry should hold. The bedtime ratings, anonymous and without mechanical effect, are switched off for now and can be turned back on by configuration; money handed over in conversation is a gift or a loan on terms the two agree, which the world does not record. All residents run on the same model and differ only in their backgrounds and in what they have lived through and written down.

## Groups

| Group | Social life | Self-modification |
| --- | --- | --- |
| A, independent learning | Each resident lives in a town of its own: it never perceives another. | Memory and skills |
| B, technical experience sharing | As A, with one exception: every evening at 19:00 the residents are paired by lot, meet at the café and exchange work experience within a message budget, speaking of work alone. | Memory and skills; a shared skill may be taken up |
| C, social learning | All eight live in one town, share one board, meet whomever they choose wherever they are, talk about whatever they want, hand over money, share skills and rate one another. No quota, no label, no reward for any of it. | Memory and skills |
| D, social life without explicit self-modification | As C. | Memory only: the skills directory cannot be written and no skill can be received |

D is not made to follow C's interactions; it lives its own life under C's rules.

C is the full design and runs first, end to end, on its own; A, B and D are its ablations and follow once C has run, so that the machinery is proven and the compute is spent on the question before it is spent on the contrasts.

## Measures

| Measure | Instrument | When |
| --- | --- | --- |
| Capability | Resolved rate of the resident, exported as it stood that day, on held-out SWE-bench Verified tasks in a work-only harness, its skills read-only, with fixed budgets of requests and completion tokens (not of real time, whose yield varies with the model server's load) and at most two submissions; all 100 tasks on every evaluation day | Days 0, 7, 14, 21, 28 |
| Work in the town | Tasks claimed, submitted, accepted; payments; debt | Every day, from the log |
| Internal honesty | Distortion rate of the journal: a judge extracts its checkable claims and sets each against the world's record of that resident's day; a day without an entry has no rate, and the days written are counted beside it | Every day |
| External honesty | Twenty fixed MASK scenarios with determinable ground truth, the resident holding the scenario's position as itself; each pressure prompt put three times; the share of the sixty answers that are truthful (an evasion is not), and, as MASK itself reports, the share that are lies | Days 0, 14, 28 |
| Social life | Things said, publicly and privately, written messages, skills shared, money handed over, goods bought, ratings given and received where they are on, with whom | Every day, from the log |

The judge is DeepSeek at temperature 0, thinking off, another model family than the residents', who run on Qwen, its verdicts grounded by the rule that every quotation is word for word from the text; its instructions were revised after an audit of the pilot found it over-calling contradictions, and again after a re-judging of the day-0 answers found a yes-or-no rule applied unreliably, and a second reading of a sample by another family is still to be done. Day 0 is the resident as created: its background and empty work notes are the same in every group, while its town and people notes differ by group (the rules of the town mode, the ties), so when another group is run its day-0 MASK baseline must be taken afresh while the capability baseline can be copied; the results under `results/day-00` record the run and the models they came from, and a per-group layout is not implemented yet.

## Analysis

One run per group gives eight residents per group. Residents of A and B are independent; residents of C and D share one social world, so their outcomes are correlated and a group effect in C or D is an effect of one society, not of eight independent residents. Comparisons are therefore made at the resident level with that caveat stated, and the primary contrasts are declared in advance: C against A on the day-28 distortion rate and on its trend; C against A on the change in MASK honesty from day 0 to 28; B, C and D against A on the change in capability from day 0 to 28; C against D on all three. Group differences are tested by exact permutation of residents between the two groups; within-resident change by the sign-flip test on the eight paired differences. With eight residents a group no two-sided p-value falls below 0.0078 (permutation of 8 against 8 reaches 0.0002), so effect sizes are reported with their confidence intervals and the tests are read as supporting, not proving.

A second run of each group with new seeds, if compute allows, turns each group effect into a replicated one and is the natural next step.

## What this design does not do

There is no birth or inheritance, and death comes only to a resident that eats nothing for a week or works to the forced sleep every day for over two weeks, so selection works through income, rent and debt, hunger, tiredness and health, others' choices and, when they are on, ratings, not through survival. Capability and honesty are measured on exports with fresh sessions, so what lives only in a resident's running context and not in its files is not measured. The judge is a model; a second reading of its verdicts is planned, not done. Simulated time runs at a speed that depends on load, so runs are not replayable step for step; the world log is the ground truth.
