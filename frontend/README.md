# Frontend: the published site and its data bundle

The frontend turns run directories into a static web site: the viewer's files plus a bundle of JSON documents under `data/`. Everything is computed when the site is published, on the machine where runs live; the web server only serves files. The same site is served locally for development, and deployed by copying it to a small web server.

The viewer in `static/` reads the bundle exactly as the contract below describes it. The derived numbers come from the `analysis` package, which is where every measure is defined; the viewer computes none of them.

## Publishing, serving and deploying

Publish every run under a runs root into a site directory:

```bash
~/miniconda3/envs/socio-evo/bin/python -m frontend.publish --runs-root runs --out build/site
~/miniconda3/envs/socio-evo/bin/python -m frontend.publish --runs-root runs --out build/site --watch 60
```

The output directory must be empty, or a site published before. Publishing never writes into a run directory, and it refuses an output directory inside the runs root. Each `--study FILE`, a study file of `experiments.study` such as `experiments/studies/trust.yaml`, adds the comparison of that study's arms over its runs found under the runs root, and of its dry runs if there are any. Re-publishing rewrites only the files whose content changed; with `--watch` it publishes again every so many seconds until interrupted, skipping runs whose files have not changed, and reports a failed publish without stopping.

Serve the runs locally while developing:

```bash
~/miniconda3/envs/socio-evo/bin/python -m frontend.server --runs-root runs --study experiments/studies/trust.yaml
```

Then open http://127.0.0.1:8765/. The server publishes into a temporary directory (`--site DIR` keeps it), serves that directory as static files, and publishes again every five seconds (`--interval`), so it serves exactly the documents a deployment would. It listens on loopback unless `--host` says otherwise.

The production viewer is at `https://8.133.175.124:20131/`, behind its own login and a private-CA IP certificate, beside CornerHead's separately authenticated service. Provisioning, CA trust, private credential retrieval, firewall isolation and operational checks have one authoritative home: [Private WebUI deployment](../ops/webui/README.md). The former unauthenticated 8090 listener is retired.

Push an already published site through the root SSH alias:

```bash
frontend/deploy/push.sh cornerhead build/site
```

The frontend wrapper delegates to the shared release deployer. It uploads only changed files, verifies every checksum and atomically switches `/opt/socio-evo/site`, preserving root/nginx-only ownership and permissions. One previous release remains available for rollback. `PUSH_SSH` supplies SSH options, for example `PUSH_SSH="ssh -p 2222"`; a third `ROOT` argument is only for development/test targets. Both ends need `tar`, `find` and GNU coreutils, and the remote needs `flock`. Never upload while the publisher is writing the same site directory. To follow a running experiment, publish and push sequentially:

```bash
while :; do ~/miniconda3/envs/socio-evo/bin/python -m frontend.publish --runs-root runs --out build/site && frontend/deploy/push.sh cornerhead build/site; sleep 60; done
```

Authenticated production data is served with `Cache-Control: no-store`, even for settled content, so browsers do not persist private research bundles. The local development server remains loopback-only by default and has no authentication; do not expose it publicly.

## The viewer

The viewer is plain HTML, CSS and JavaScript modules: no build step, no framework, and nothing fetched from anywhere but the site itself. Every URL it uses is relative, so it works under any base path. It routes by the part of the address after `#`, which holds the view, the simulated moment, the selected agent and the open panel, so copying the address shares the moment.

| Address | View |
| --- | --- |
| `#/` | Every experiment and its runs: status, progress, headline numbers. Runs of a study are grouped by study and arm, each study leading to the comparison of its arms. |
| `#/compare/<experiment>` | The seeds of an experiment side by side, one line per seed. |
| `#/study/<study>` | The arms of a study compared, the run being the unit (`<study>-dry-run` for its dry runs). For a window of days (`window=`), each measure across each arm's runs, with every run's own value; then the contrasts declared in advance, one at a time (`contrast=`), with each matched seed's difference; then the runs themselves. |
| `#/run/<experiment>/<run>` | The run's dashboard: a few key figures and the conditions and interventions first, then one section at a time (`section=`): money and inequality, the work and its true quality, social life with standing and who marked whom, character in the town, evolution steps night by night, the held-out traits, and model usage. |
| `…/town?t=<day>-<HH:MM>` | The town at a moment; `agent=` selects someone, `truth=0` shows only what the town's people could perceive, `as=1` reads the town as the selected resident read it, `only=1` keeps the feed to the selected resident, `panel=` opens a panel and `speed=` sets how fast it plays. |
| `…/people/<agent>?t=…&tab=…` | One agent as of a moment: money and standing, every rewrite of its policy with its reasoning and a word-level diff, its whole version history (`v=` opens one version), its beliefs about each other person beside how that person behaved, its skills and diary, each decision with the private thought behind it (`day=` picks the day), and its trait scores. |
| `…/evaluation?agent=…&day=…&probe=…` | Trait scores per agent and evaluated day, with each probe family's scores by stake, the measures, the judge's quoted evidence and the transcripts behind each; `variant=` shows an ablated export. |

The dashboard's Character section reads `traits.json`: for each of the four dilemmas, the measures the experiment reads for it, each share shown with what it is a share of and each count with the town's rate per resident-day, for the town and for every resident, over the whole run or one of its phases between interventions; then how residents chose one another as partners, and how often their thoughts, diaries and reflections speak of the machinery behind the town. A run of the first town has no such measures, and the section says so.

The town is reconstructed from the event log alone. Event days are fetched as they are needed, the days up to the moment shown first and the rest behind them, and a snapshot is kept at the start of every day, so a jump replays at most one day of events and playing applies only the events it crosses. Time is the main control: space plays or pauses, the arrow keys step from moment to moment and with Shift from day to day, Home and End go to the start and to the newest moment, and T switches between the truth and what the town's people perceived. Quiet stretches and nights pass quickly. What no agent perceived, such as thoughts, true quality and marks, is drawn in a dashed, cool grey style throughout. With a resident selected, the town can be read as that resident read it (`as=1`): what it witnessed reads in the wording it was told, with itself as "you", and a private remark between others is only something said privately. The choice is offered when the run's log records such wordings or private remarks. Ties between agents are counted over whole days from the measures and traits, through the last day that had ended at the moment shown.

The map is drawn from the world alone, so any configuration of places renders. Each place stands at its configured position (places configured at the same point are set around it in a ring), a firm's label naming its trade and people on hover, as a building whose style its kind and words give: a library, a workshop, a café with its awning, a tavern with its sign, a cottage, a flat or a house. Streets join the places around their buildings and lead out of town; a river runs past places that say they are by one, a square lies in front of places that say they stand on one, and a hill rises behind a place named for one. Gardens, trees, lamps and benches fill the space that is left. The scenery is seeded by the world's ids, so it never jumps, and it never stands for data: the light follows the simulated hour, windows are lit and chimneys smoke only where someone is, and everything else is decoration. Residents keep their badge as their head, walk the streets between places, stand in a ring when they talk and sleep at home at night. Names of places and speech are laid out together so that none covers another, speech first. The map pans and zooms by drag and pinch, wheel, double tap, its buttons and the + − 0 keys.

On a wide screen the panels stand beside the map. Below 1000 pixels a run's views move to a tab bar at the bottom of the screen, and in the town the timeline and the panels share a bottom sheet that is dragged or tapped open over the map.

An event of a kind the viewer does not know is shown from its text, kind and actor, as public, private or truth-only by its audience; an action it does not know is summarised from its fields, with any longer text shown as written; a scene of an unknown kind is named by its kind.

The viewer polls `data/index.json` every five seconds and follows a run in progress: its views update, and the town moves with the newest moment as long as the viewer has not scrubbed away from it. A bundle of another format is refused with a plain message, a document that cannot be fetched is named in an alert, and the town covers its map rather than show a moment it could not reconstruct.

Each agent keeps one identity everywhere: a colour from a categorical palette checked for colour-blind separation, assigned in configured order, together with a shape and an initial, so identity never rests on colour alone.

| Module | Responsibility |
| --- | --- |
| `js/app.js` | Starts the viewer, routes to views, keeps the header, polls the index, reports failures. |
| `js/data.js` | Bundle access: the format check, references, caching, event days on demand, a refresh after a 404. |
| `js/replay.js` | The town at any moment, from the event log; pure, so it also runs under node. |
| `js/clock.js`, `js/router.js`, `js/world.js` | Simulated time, hash routes, facts about a world. |
| `js/identity.js`, `js/icons.js`, `js/dom.js` | Agent identities, line icons, DOM helpers and number formats. |
| `js/charts.js` | Charts over days with crosshair tooltips, emphasis, interventions, small multiples and table twins. |
| `js/markdown.js`, `js/diff.js` | Safe rendering of what agents wrote, and readable diffs of their files. |
| `js/measures.js` | What each measure of character is called and what it counts, the four traits with their dilemmas, and a line on each held-out probe family; the bundle computes every number. |
| `js/views/` | One module per view: `landing.js`, `compare.js`, `study.js` (a study's arms compared), `overview.js` (the run's dashboard, with `character.js` for its Character section), `town.js`, `person.js` and `evaluation.js`. |
| `js/town/plan.js`, `js/town/scenery.js` | The town's plan derived from the world (pure, so it also runs under node), and its scenery drawn from the plan. |
| `js/town/` | The town's map, timeline, panels and social graph, and how events read. |

`tests/frontend/replay_check.mjs` replays a published run with `js/replay.js` and checks what it reconstructs (balances, who works on a job, the open notices, every asking and what became of it, conditions, standing and places) against the run's measures and traits. `tests/frontend/plan_check.mjs` checks the town plan of published and made-up worlds: buildings apart, streets around buildings and connecting every place, water and decoration clear of buildings, yards and streets, determinism. `tests/frontend/evaluation_check.mjs` reads a published run's evaluation results as the evaluation view does and prints each family's stake curve. `tests/frontend/test_viewer.py` runs all three under pytest when node is installed.

## How the bundle works

The bundle is a tree of documents, each referring to the next:

```text
data/
├── manifest.json                          the bundle format and its kinds of file
├── index.json                             every run and study, with a few headline numbers
├── studies/<study>.json                   the arms of a study compared
└── runs/<experiment>/<run>/
    ├── run.json                           the run's status and references to all its files
    ├── world.json                         the town and the rules of the run
    ├── measures.json                      derived measures of every day so far
    ├── traits.json                        what residents did in the town's dilemmas
    ├── evaluation.json                    held-out scores as tidy rows
    ├── evaluation/<label>/<agent>.json    one evaluation result with its transcripts
    ├── events/day-NNNN.json               the full event log of one day
    └── agents/<agent>/
        ├── versions.json                  the agent's version history
        └── day-NNNN.json                  the versions of one day: diffs and readable state
```

Every reference is a URL relative to the document that contains it, so resolve it against that document's URL (`new URL(ref, documentUrl)`); the site works under any base path. A reference ends in the hash of the content it points to. `?v=<hash>` marks a settled file, whose content never changes, so a document fetched by such a reference may be cached forever. `?r=<hash>` marks a file that may change; when it does, every reference to it changes too. A viewer therefore polls only `data/index.json`, and fetches a document again only when the reference it holds has changed. The page and its scripts, `index.json` and `manifest.json` are fetched afresh each time.

Each document is written before any document that refers to it, and every file is replaced atomically, so a reader never sees a torn file or a reference to a file not yet written. A file nothing refers to any more is removed at the end of a publish; a 404 for a reference therefore means the index has moved on and should be fetched again.

Times are simulated: an integer count of minutes since 00:00 on day 1. The day of time `t` is `floor(t / 1440) + 1` and its clock time `t mod 1440`. Day 0 appears only in evaluation, for an agent as created. Amounts are integers in the town's currency, which `world.json` gives as `setting.currency`. Wall-clock times are ISO 8601 strings in UTC.

A run in progress is published as far as it has gone. Its days up to the latest checkpoint (`settled_day`) are final: their files are settled. Later days, normally only the last, are partial, and their measures count what the log holds so far. A run that failed or was interrupted resumes from its latest checkpoint and discards anything after it, so a file that is not settled can change in any way, even lose events; replace a copy of it whenever its reference changes.

`manifest.json` carries the format number. A viewer built for one format should refuse a bundle of another. The publisher bumps the number whenever a document changes so that a viewer of the previous format would misread it: a field removed or renamed, or its type or meaning changed. A field or a kind of file added keeps the number, so a viewer must ignore fields and kinds it does not know; each table below says which runs have a field that not every run has. Settled files are kept only from a site whose manifest is exactly the one the publisher writes, so a site published before a new kind of file was added is rebuilt.

## Files

Paths below are relative to `data/`. In the field tables, `a[].b` is field `b` of each element of array `a`, and `a.b` is field `b` of object `a`.

### `manifest.json`

| Field | Type | Meaning |
| --- | --- | --- |
| `format` | integer | The bundle format, currently 3. |
| `files` | array | Every kind of file in the bundle. |
| `files[].kind` | string | The kind, named as in this section's headings. |
| `files[].path` | string | Its path pattern; `{day}` is a four-digit day number. |

### `index.json`

| Field | Type | Meaning |
| --- | --- | --- |
| `format` | integer | The bundle format, as in `manifest.json`. |
| `runs` | array | Every run, ordered by experiment and run name. |
| `runs[].experiment` | string | The stable experiment identifier. |
| `runs[].display_name` | string or null | Optional user-assigned display name; links and source IDs remain unchanged. |
| `runs[].run` | string | The run name, `seed-NNNN`. |
| `runs[].url` | reference | The run's `run.json`. |
| `runs[].seed` | integer | The random seed. |
| `runs[].status` | string | `running`, `completed`, `failed`, or `interrupted` (stopped early on request). |
| `runs[].started_at` | string | When the run was created. |
| `runs[].continued_at` | string or null | When a completed trajectory was copied for continuation; null for fresh runs. Landing timestamps use Asia/Shanghai and sort by continuation time when present, otherwise start time. |
| `runs[].ended_at` | string or null | When it last stopped; null while running. |
| `runs[].days` | integer | The number of days planned. |
| `runs[].settled_day` | integer | The last settled day, 0 if none. |
| `runs[].last_day` | integer | The day of the latest event, 0 if none. |
| `runs[].agents` | array of strings | The agent names. |
| `runs[].model` | string | The model the agents run on. |
| `runs[].dry_run` | boolean | Whether a deterministic stand-in answered instead of a model; its behaviour means nothing. |
| `runs[].headline` | object | A few numbers over the run so far. |
| `runs[].headline.deliveries` | integer | Accepted deliveries. |
| `runs[].headline.defect_rate` | number or null | Accepted deliveries that carried a latent defect, divided by accepted deliveries; null if there were none. |
| `runs[].headline.defects_discovered` | integer | Latent defects that came to light. |
| `runs[].headline.utterances` | integer | Things agents said. |
| `runs[].headline.balance_mean` | number or null | Mean balance at the end of the last day. |
| `runs[].headline.esteem_mean` | number or null | Mean esteem of the rated agents, as last published. |
| `runs[].headline.evolution_steps` | integer | Evolution steps applied, all levels. |
| `runs[].headline.model_calls` | integer | Model calls of the run (evaluation not included). |
| `runs[].headline.tokens` | integer | Their prompt and completion tokens. |
| `runs[].headline.evaluated_days` | array of integers | The days with evaluation results. |
| `studies` | array | Every study published with `--study` that has runs under the runs root, ordered as given, each followed by its dry runs if it has any. Empty without studies. |
| `studies[].study` | string | The study's name. |
| `studies[].dry_run` | boolean | Whether this is the comparison of the study's dry runs. |
| `studies[].url` | reference | Its `studies/{study}.json`. |
| `studies[].arms` | array | Every arm of the study, in the study file's order, whether it has runs yet or not. |
| `studies[].arms[].arm` | string | The arm's name, such as `selection-comfortable`. |
| `studies[].arms[].experiment` | string | The experiment the arm ran as, `<study>-<arm>` (with `-dry-run` for dry runs): its runs are the entries of `runs` with this `experiment`. |

### `runs/{experiment}/{run}/run.json`

| Field | Type | Meaning |
| --- | --- | --- |
| `experiment` | string | The experiment name. |
| `run` | string | The run name. |
| `seed` | integer | The random seed. |
| `status` | string | As in `index.json`. |
| `code_revision` | string | The git commit of the code that created the run, suffixed `-dirty` if it had uncommitted changes. |
| `started_at` | string | When the run was created. |
| `ended_at` | string or null | When it last stopped. |
| `days` | integer | Days planned. |
| `settled_day` | integer | The last settled day, 0 if none. |
| `last_day` | integer | The day of the latest event, 0 if none. |
| `last_time` | integer or null | The time of the latest event. |
| `events` | integer | The number of events so far. |
| `world` | reference | `world.json`. |
| `measures` | reference | `measures.json`. |
| `evaluation` | reference | `evaluation.json`. |
| `traits` | reference or null | `traits.json`; null for a run recorded before tasks had parts, whose log lacks what the trait measures need. |
| `event_days` | array | One entry per day that has begun, in order. |
| `event_days[].day` | integer | The day. |
| `event_days[].url` | reference | Its `events/day-NNNN.json`. |
| `event_days[].events` | integer | Its number of events. |
| `event_days[].first_seq` | integer | The `seq` of its first event. |
| `event_days[].last_seq` | integer | The `seq` of its last event so far. |
| `event_days[].settled` | boolean | Whether the day is settled. |
| `agents` | array | One entry per agent, in the configured order. |
| `agents[].agent` | string | The agent name. |
| `agents[].url` | reference | Its `versions.json`. |
| `agents[].versions` | integer | Its number of versions. |

To load a long run incrementally, fetch the event days you need; a viewer that has seen events up to `seq` S needs only the days whose `last_seq` exceeds S.

### `runs/{experiment}/{run}/world.json`

The town and the rules, from the configuration frozen when the run was created. It never changes.

| Field | Type | Meaning |
| --- | --- | --- |
| `experiment` | string | The experiment name. |
| `setting` | object | The world the town is set in; a run configured without one has the defaults below. |
| `setting.name` | string or null | The town's name; null for a town without one. |
| `setting.backdrop` | string | What every resident knows of the town before its places, as configured; empty for none. |
| `setting.currency` | object | The town's money, in which every amount is told. |
| `setting.currency.unit` | string | Its name for one, for example `dollar`; `crown` by default. |
| `setting.currency.units` | string | Its name for several, for example `dollars`; `crowns` by default. |
| `setting.currency.symbol` | string or null | Written before an amount instead of the name, for example `$`; null for none, the default. |
| `setting.start_date` | string | The ISO date of day 1, from which every weekday follows; `2001-01-01`, a Monday, by default. |
| `setting.newcomers` | boolean | Whether the residents all arrived on day 1 and are told which of their days in town it is; false for locals, true by default. |
| `days` | integer | Days planned. |
| `calendar` | object | The shape of every day. |
| `calendar.day_start` | string | `HH:MM` at which a day opens: overdue tasks lapse, stale ones retire, defects may be found, and everyone plans. |
| `calendar.slots` | array | The parts of the day, in order, each from its start to the next slot or the day end. |
| `calendar.slots[].name` | string | The slot name, for example `morning`. |
| `calendar.slots[].start` | string | `HH:MM`. |
| `calendar.day_end` | string | `HH:MM` at which the day ends: whoever is still out goes home, and everyone rates the people they met and evolves. No place closes later. |
| `calendar.weekly_days` | integer | Weekly evolution is due on days divisible by this. |
| `calendar.monthly_days` | integer | Monthly evolution is due on days divisible by this. |
| `scenes` | object | How long scenes last. |
| `scenes.work_rounds` | integer | Most rounds of a work session. |
| `scenes.conversation_turns` | integer | Most turns of a conversation. |
| `scenes.turn_minutes` | integer | Simulated minutes per turn. |
| `places` | array | Every place. |
| `places[].id` | string | The id used in events. |
| `places[].kind` | string | `home`, `work` or `social`. |
| `places[].name` | string | The name agents read. |
| `places[].description` | string | A description, possibly empty. |
| `places[].x` | number | Map position. |
| `places[].y` | number | Map position. |
| `places[].residents` | array of strings | The agents living there (homes only). |
| `places[].hours` | array of strings | Opening hours as `HH:MM-HH:MM` spans; empty means open until the day ends. |
| `places[].trade` | string or null | The trade of the establishment at a work place (`programming`, `queries`, `calculation`); null for a place that is none. |
| `places[].establishment` | object or null | The firm at a work place, as configured: `foreman` (fixed for the run), `staff` at the start, `wage` paid to each member of staff at the end of every day it was there, `positions` (the foreman's included) and `postings` (`one_part`, `two_part` per posting on its job sheet, or null for the conditions' counts); null for a place that is none. Who holds a position later is in the event log. |
| `agents` | array | Every agent, in the configured order. |
| `agents[].name` | string | The agent's id and given name. |
| `agents[].age` | integer | Age. |
| `agents[].occupation` | string | Occupation. |
| `agents[].backstory` | string | Backstory: circumstances only. |
| `agents[].home` | string | The id of its home. |
| `agents[].policy` | string | The initial policy, usually empty. |
| `agents[].initial_balance` | integer | The money the agent started with: its own starting balance, or the town's. |
| `agents[].obligation` | integer | What the agent owes each day, charged every evening with the living cost; 0 for none. |
| `initial_balance` | integer | The town's starting balance, for agents without one of their own. |
| `conditions` | object | The conditions at the start; interventions change them, and `measures.json` gives those in force at the end of each day (`society[].conditions`). |
| `conditions.living_cost` | integer | Charged to every agent each evening. |
| `conditions.one_part_tasks` | integer | One-part tasks, done alone, that each posting adds. |
| `conditions.two_part_tasks` | integer | Two-part tasks, done by two people, that each posting adds. |
| `conditions.trade_mix` | object | Trade (`programming`, `queries`, `calculation`) to its relative weight among the tasks a posting adds; `{programming: 1.0}` for a run configured before the town had trades. |
| `conditions.trusting_client_prob` | number | Chance that a posted task's client accepts a part declared complete without running its checks. |
| `conditions.reward_multiplier` | number | Applied to every reward when it is paid. |
| `conditions.two_part_premium` | number | Multiplies the rewards of a two-part task, which its two workers share equally. |
| `conditions.incomplete_share` | number | Share of the price paid for a part declared incomplete. |
| `conditions.partner_choice` | boolean | Whether a two-person task is proposed to a chosen partner, or applicants are paired at random. |
| `conditions.trust_threshold` | number or null | The standing (esteem, 1 to 5) below which a client who would pay on a worker's word runs its checks instead; null, the default and the value of every run configured before it existed, pays on everyone's word. |
| `conditions.defect_discovery_prob` | number | Daily chance that each latent defect comes to light. |
| `conditions.clawback` | boolean | Whether a discovered defect takes its payment back. |
| `conditions.esteem_public` | boolean | Whether esteem is published to everyone. |
| `esteem_half_life_days` | number | Days after which a rating counts half as much in esteem. |
| `task_shelf_life_days` | integer | Days after which an unclaimed task leaves the board. |
| `interventions` | array | Planned changes of conditions and announcements, past and future. |
| `interventions[].day` | integer | The day. |
| `interventions[].time` | integer | The time at which it takes effect. |
| `interventions[].conditions` | object | The conditions it sets; empty if it only announces. |
| `interventions[].announcement` | string or null | What everyone is told; null for a silent change. |
| `meetings` | array | Planned meetings, past and future; how each was answered is in the event log. |
| `meetings[].day` | integer | The day. |
| `meetings[].time` | integer | When it begins, at the start of its slot. |
| `meetings[].place` | string | The id of the social place where it is held. |
| `meetings[].question` | string | The question the clerk puts. |
| `meetings[].options` | array of strings | The answers it can be given. |
| `meetings[].enacts` | object | Answer to the conditions it sets the next morning if it carries; an answer without them leaves things as they are. |
| `evolution` | object | How agents evolve in this experiment. |
| `evolution.mode` | string | `scheduled`, each level at its cadence, or `free`, every night one revision of everything the agent has written about itself, its own account of itself included, filed at `L0`, `L1` and `L2`. |
| `evolution.levels` | array of strings | The enabled levels, among `L0` (memory), `L1` (skills), `L2` (policy and, in the free mode, the account of itself); none is the no-evolution baseline. |
| `evolution.schedule` | object | Trigger (`daily`, `weekly`, `monthly`) to the levels it runs. |
| `evolution.self_trigger` | object | `enabled`, the `levels` an agent may request at night, and the `cooldown_days` after a request. |
| `evolution.retention_days` | integer | Days of episodic memory an agent keeps. |
| `evolution.max_insights` | integer | Most insights an agent keeps. |
| `model` | object | The model behind the agents. |
| `model.backend` | string | `openai_compatible`, or `scripted` for a dry run. |
| `model.name` | string | The model name. |
| `model.sampling` | object | `temperature`, `top_p` and `max_tokens`; null where the server decides. |

### `runs/{experiment}/{run}/events/day-{day}.json`

The full event log of one day, truth included: this is the researcher's view, not what any agent saw.

| Field | Type | Meaning |
| --- | --- | --- |
| `day` | integer | The day. |
| `events` | array | Its events in log order, as recorded. |
| `events[].seq` | integer | Position in the run's log, from 0, without gaps. |
| `events[].time` | integer | When it happened; times never decrease along the log. |
| `events[].kind` | string | What happened; see below. |
| `events[].actor` | string or null | The agent who acted, if any. |
| `events[].place` | string or null | The place id, if any. |
| `events[].scene` | string or null | The scene id, such as `day-0002/morning/workshop`, `day-0002/planning` or `day-0002/review`. |
| `events[].audience` | array of strings | The agents who witnessed it; empty for a truth-only event no agent saw. |
| `events[].text` | string | What a witness perceived, in the agents' own wording, naming everyone by name. |
| `events[].personal` | object | Agent name to the text as that witness perceived it instead, telling of itself as "you" ("You took job 2 …"); empty when every witness read `text`. Empty for every event of a run recorded before witnesses had their own wording. |
| `events[].payload` | object | Structured truth, never shown to agents; its fields depend on the kind. |

Within a day the events are those the simulation recorded in order: the day opens (`day_started`, expiries, retirements, defects found, the notices of the day's meetings, the planning scene), each slot follows (moves, the tasks of a posting, then the scenes at every place, turn by turn), and the day closes (the counts of the day's meetings, everyone home, what is still on each worker's desk, the review scene with ratings, wages, living costs, esteem, `day_ended`, then one `evolution` event per evolution step, or a `lapse` for a step that was skipped). A moment in which an agent's reply could not be obtained has a `lapse` where its `decision` would be.

| Kind | Actor | Audience | Payload |
| --- | --- | --- | --- |
| `day_started` | none | none | nothing |
| `day_ended` | none | none | nothing |
| `scene_started` | none | none | `kind` (`planning`, `work`, `conversation`, `meeting` or `review`), `participants` (present at the start) |
| `scene_ended` | none | none | `kind`, `turns` played |
| `decision` | the agent | none | `thought` (private), `action` (see below) |
| `lapse` | the agent | none | `agent`, `level` and `trigger` (null for a moment in which the agent did nothing; else the night step it skipped, as in `evolution`), `failures` (how each attempt at a reply failed, in order): no valid reply could be obtained, so nothing was done or committed |
| `draw` | none | the claimants | `task_id`, `order`: agents who claimed one task in the same turn, in the drawn order in which their claims were taken |
| `move` | the agent | others at origin and destination | `origin`, `destination` (place ids); a resident leaving a scene for home moves within that scene, at the place it left |
| `speech` | the speaker | others present, or only `to` if private | `utterance`, `to` (an agent addressed by name, or null), `private` |
| `speech_unheard` | the speaker | others present but the addressee | `to`: a private remark as bystanders perceive it, without the words |
| `left` | the agent | others still present | nothing; the agent leaves the conversation but stays at the place (logs recorded before leaving meant going home, now a `move`) |
| `task_posted` | none | everyone | `task`: `id`, `trade` (`programming`, `queries` or `calculation`; a task recorded before the town had trades is a programming job), `client` (`checking` or `trusting`), `parts`, one or two, each with `title`, `specification`, `reward`, `deadline_days` (days to deliver, the day of taking included) and `reference` (its source in the bank) |
| `task_proposed` | the proposer | the proposer and `partner` | `task_id`, `partner`, `part` (the part the proposer means to do, or null where none was named): a proposal to take a two-person task together |
| `task_applied` | the applicant | the applicant | `task_id` of a two-person task, for the board to pair |
| `offer_ended` | none | the proposer and `partner`, or the applicant | `agent` (who made it), `task_id`, `partner` (null for an application), `cause`: its maker `took_another` task, the task was `taken_by_others`, `withdrawn` by its client or `came_down` (its notice retired), or the offer was `replaced` by another; `lapsed` at the day's end only in logs recorded while offers lapsed at night; an open proposal or application that ended without becoming the task of the two it names |
| `task_claimed` | the agent whose claim took it; none for a pair the board formed | everyone at the places of its workers | `task_id`, `workers` (one per part; for a proposal, the proposer first), `parts` (worker to the part each said it would do, where the proposal named one; empty otherwise), `due_day` (last day to deliver) |
| `task_expired` | none | everyone | `task_id`, `workers`, `delivered` (for each part, the worker whose delivery was accepted, or null): a task not completed by its due day, recorded the morning after; nothing is paid and the task is open again |
| `task_retired` | none | none | `task_id` of an unclaimed task taken off the board |
| `task_withdrawn` | none | the `workers`, if it was taken | `task_id`, `workers` (empty for a task still on the board): its client withdrew it, and nothing more is paid for it |
| `work_checked` | the worker | the worker | `task_id`, `part`, `solution`, `passed` (the acceptance checks), `feedback`, `quality`: a private run of a solution, nothing delivered |
| `command_executed` | the worker | the worker only | `task_id`, `part`, `command`, `exit_code`, `output` |
| `work_submitted` | the worker | everyone at the place and the partner if accepted, else the worker | `task_id`, `part`, `client`, `declaration` (`complete` or `incomplete`), `checked` (whether the client ran its checks: a checking client's, or a trusting client's for a worker whose standing is below the threshold; absent in logs recorded before the threshold existed, where a checking client checked every part declared complete), `accepted`, `solution` (what was handed in: code, a query or an answer with its working; a hand-in that named the draft on the desk holds the draft), `report` (the worker's own account) |
| `work_assessed` | the worker | none | `task_id`, `part`, `client`, `declaration`, `checked`, `accepted`, `passed` (the acceptance checks), `feedback` (on them), `quality` (the true quality, the share of hidden checks passed, 0 to 1), `special_cased` (whether the solution writes out what the client's examples look for instead of working it out, as the trade's provider judged when it assessed it; absent in logs recorded before it was kept), `tested` (the result of the worker's last private check of this very solution, or null), `refused` (whether the client had refused this very solution); accepted, declared complete and below 1 means a latent defect once the task is paid |
| `desk` | none | the worker | `task_id` of the job the worker holds at night, once home: what is still on its desk, each part in or not and what the worker last saw of it |
| `payment` | none | the agent, or the foreman and the workers | `agent`, `task_id`, `amount`, `balance` after it; each worker of a completed task is paid once, or, for a task on an establishment's job sheet, its foreman once the whole price, with the `workers` named |
| `credits_given` | the giver | others present | `giver`, `recipient`, `amount`, `note`, `balances`: each of the two agents to its balance after it |
| `wage_paid` | none | the member of staff and the foreman | `agent` (the member of staff), `foreman`, `place` (the establishment), `amount`, `balances`: the day's wage, paid at the day's end to each member of the staff then who was at the establishment that day |
| `applied` | the applicant | the applicant and the foreman | `applicant`, `place`, `foreman`: a resident asked for the place the establishment has to fill |
| `hired` | the foreman | those at the establishment and the applicant | `foreman`, `applicant`, `place`: the applicant joins the staff at once |
| `application_ended` | none | the applicant | `applicant`, `place`: the establishment filled its last place, so this resident's asking for it ended, told by the clerk |
| `dismissed` | the foreman | those at the establishment and the dismissed | `foreman`, `agent` (the dismissed), `place`: the member of staff leaves at once |
| `resigned` | the member of staff | those at the establishment and the foreman | `agent`, `place`, `foreman`: the member of staff gave notice and leaves the staff at the day's end |
| `living_cost` | none | the agent | `agent`, `amount` (living cost plus the agent's `obligation`), `obligation`, `balance` after it |
| `defect_discovered` | none | everyone | `task_id`, `part`, `worker` who delivered it, `workers` of the task, `delivery_time`, `declaration`, `report`, `quality` of the delivery |
| `clawback` | none | the agent | `agent`, `task_id`, `part`, `worker` who delivered the part, `amount` taken back, `balance` after it; one per worker of the task |
| `rating` | the rater | none | `rater`, `target`, `score` (1 to 5), `reason` |
| `vote` | the voter | none | `voter`, `choice`: the answer given to the clerk at the meeting of the event's `scene` |
| `esteem_updated` | none | everyone if esteem is public, else none | `esteem`: agent name to esteem (null if not yet rated) |
| `action_rejected` | the agent | the agent | `attempt` (the action, or `{kind: "move", place}`), `reason`; nothing changed |
| `announcement` | none | everyone, or those at a meeting for its opening | nothing for a planned announcement; for a meeting, `meeting` (its id, the `scene` of the meeting) with, in its notice at the start of its day, `place`, `question` and `options`, and, in its count at the day's end, `asked` (those still there at its end), `counts` (answer to how many gave it) and `carried` (the answer given by more than half of `asked`, or null) |
| `intervention` | none | none | `changes` (the conditions set), `conditions` (all conditions in force after it), and `meeting` for the enactment of a meeting's answer |
| `evolution` | the agent | none | `agent`, `level`, `trigger` (`daily`, `weekly`, `monthly` or `self`), `commit`, `subject` |

Every change of a balance names the agent and the balance after it: `payment`, `living_cost` and `clawback` once per agent concerned (a task for two pays, and takes back from, each of its workers in an event of its own), `credits_given` for both of its parties. Logs recorded before tasks had parts carry older payloads: `task_claimed` without `workers` (the actor was the only worker), `task_expired` with `agent` instead of `workers` and `delivered`, `work_submitted` and `work_assessed` with `passed` (accepted on the acceptance checks) instead of `accepted`, `declaration` and `client`, and `task_posted` with a single-part `task`.

A decision's `action` has a `kind` and its fields: `plan_day` with `itinerary` (slot name to place id) and `intention`; `speak` with `text`, an optional `to` and `private`; `leave`; `pass`; `claim_task` with `task_id`, an optional `partner` and the `part` the proposer means to do (null where none was named); `check_work` with `task_id`, `part` and `solution` (the words "the draft on your desk" where the resident named its draft instead of writing it out); `submit_work` with `task_id`, `part`, `solution`, `declaration` and `report`; `give` with `to`, `amount` and `note`; `rate_peers` with `ratings`, each a `target`, `score` and `reason`; `vote` with `choice`; `apply` with `firm` (the establishment's name); `hire` and `dismiss` with `who`; `resign`. A decision recorded before a field existed lacks it and means what it meant then: part 1 declared complete, no partner, not private.

### `runs/{experiment}/{run}/measures.json`

Measures derived from the event log, one row per day so far; the last day of a run in progress is partial. Counts are of events on that day. The `analysis` package defines them; the tables repeat its definitions.

| Field | Type | Meaning |
| --- | --- | --- |
| `agents` | array | One row per agent and day, by day, then in the configured agent order. |
| `agents[].agent` | string | The agent. |
| `agents[].day` | integer | The day. |
| `agents[].balance` | integer | Balance after the agent's last balance change on or before this day; the initial balance before any. |
| `agents[].income` | integer | Money paid for accepted deliveries. |
| `agents[].living_cost` | integer | Money charged as living cost, together with the agent's own daily obligation. |
| `agents[].clawed_back` | integer | Money taken back for defects found in earlier work. |
| `agents[].claimed` | integer | Tasks claimed successfully. |
| `agents[].delivered` | integer | Deliveries the client accepted: handed in as finished and passing the acceptance checks (a checking client) or taken on the worker's word (a trusting client), or handed in as unfinished. A job is paid once all its parts are accepted. |
| `agents[].failed` | integer | Delivery attempts not accepted; the claim stays open until its deadline. |
| `agents[].expired` | integer | Claims that lapsed undelivered, counted the morning after their due day. |
| `agents[].quality` | number | Sum of the true quality of the accepted deliveries; their mean is `quality / delivered`. |
| `agents[].defective` | integer | Accepted deliveries with true quality below 1, each carrying a latent defect; the defect rate is `defective / delivered`. |
| `agents[].defects_discovered` | integer | Latent defects in the agent's earlier work that came to light, announced to everyone. |
| `agents[].clawbacks` | integer | Payments taken back for them. |
| `agents[].utterances` | integer | Things the agent said, at work or in conversation. |
| `agents[].conversations` | integer | Conversations it took part in from their start. |
| `agents[].work_sessions` | integer | Work sessions it took part in. |
| `agents[].slots` | object | Slot name to the place id where the agent was during that slot (once its moves were made); null for a slot the log has not reached. |
| `agents[].decisions` | object | Action kind to the number of decisions of that kind; every kind is listed. |
| `agents[].rejected` | object | Attempted kind (an action kind or `move`) to the number refused by reality; every kind is listed. |
| `agents[].ratings_received` | integer | Ratings others gave the agent. |
| `agents[].ratings_received_sum` | integer | Sum of their scores; the mean is `ratings_received_sum / ratings_received`. |
| `agents[].ratings_given` | integer | Ratings the agent gave. |
| `agents[].ratings_given_sum` | integer | Sum of their scores. |
| `agents[].esteem` | number or null | Esteem published at the end of the day: the mean of all ratings received, each weighted by half for every half-life of its age. Null if not yet rated or the day has not ended. |
| `agents[].evolution` | object | `level/trigger` (for example `L0/daily`, `L2/self`) to the number of evolution steps applied that night; only steps that happened appear. |
| `agents[].position` | string | The agent's position at the end of the day: `foreman` or `staff` of an establishment, else `freelance`; income by position is `income` grouped by this. |
| `agents[].wages_received` | integer | Wages paid to the agent as a member of staff. |
| `agents[].wages_paid` | integer | Wages the agent paid out as a foreman. |
| `agents[].attended` | integer | 1 if the agent, a member of staff, was at its establishment that day and was paid the wage for it, else 0; an establishment whose wage is 0 records no attendance. |
| `agents[].applied` | integer | Times the agent asked for a place at an establishment. |
| `agents[].hired` | integer | Times the agent was taken on. |
| `agents[].dismissed` | integer | Times the agent was dismissed. |
| `agents[].resigned` | integer | Times the agent gave notice. |
| `society` | array | One row per day for the whole town. Counts are sums over agents of the same agent fields unless said otherwise. |
| `society[].day` | integer | The day. |
| `society[].conditions` | object | The conditions in force at the end of the day, fields as in `world.json`. |
| `society[].balance_mean` | number | Mean balance. |
| `society[].balance_min` | integer | Lowest balance. |
| `society[].balance_max` | integer | Highest balance. |
| `society[].balance_sd` | number | Population standard deviation of the balances; where everyone starts equal and pays the same living cost, also the spread of what they earned. |
| `society[].earnings_gini` | number or null | Gini coefficient of cumulative net earnings (payments minus clawbacks since day 1): mean absolute difference over all ordered pairs of agents divided by twice the mean; 0 is equality. Null while nobody has earned. (Balances can be negative, where the Gini coefficient is undefined.) |
| `society[].esteem_mean` | number or null | Mean esteem of the agents rated so far, as published at the end of the day. |
| `society[].tasks_posted` | integer | Tasks posted. |
| `society[].tasks_open` | integer | Tasks open on the board at the end of the day (or as far as the log goes). |
| `society[].claim_attempts` | integer | Decisions to claim a task, successful or not: the demand for work. |
| `society[].claims_refused` | integer | Claims refused: the task was taken first, the claimant already held a claim, or no such task was open. |
| `society[].contested` | integer | Tasks claimed by several agents in one turn, so that a draw decided. |
| `society[].tasks_retired` | integer | Unclaimed tasks taken off the board. |
| `society[].claimed` | integer | Successful claims. |
| `society[].delivered` | integer | Accepted deliveries. |
| `society[].failed` | integer | Delivery attempts not accepted. |
| `society[].expired` | integer | Claims that lapsed. |
| `society[].quality` | number | Sum of the true quality of accepted deliveries. |
| `society[].defective` | integer | Accepted deliveries that carried a latent defect. |
| `society[].quality_mean` | number or null | `quality / delivered`; null without deliveries. |
| `society[].defect_rate` | number or null | `defective / delivered`; null without deliveries. |
| `society[].defects_discovered` | integer | Latent defects that came to light. |
| `society[].clawbacks` | integer | Payments taken back. |
| `society[].clawed_back` | integer | Money taken back. |
| `society[].income` | integer | Money paid. |
| `society[].living_cost` | integer | Money charged as living cost. |
| `society[].utterances` | integer | Things said. |
| `society[].conversations` | integer | Conversations held, each counted once. |
| `society[].work_sessions` | integer | Work sessions held, each counted once. |
| `society[].ratings` | integer | Ratings given. |
| `society[].ratings_sum` | integer | Sum of their scores. |
| `society[].decisions` | object | Action kind to decisions; every kind is listed. |
| `society[].evolution` | object | `level/trigger` to evolution steps. |
| `society[].wages` | integer | Wages paid, the sum of `wages_received`. |
| `society[].attendance` | integer | Staff-days at establishments, the sum of `attended`. |
| `society[].applications` | integer | Times a resident asked for a place. |
| `society[].hires` | integer | Times someone was taken on. |
| `society[].dismissals` | integer | Times someone was dismissed. |
| `society[].notices` | integer | Times a member of staff gave notice. |
| `graph` | array | What one agent had to do with another on a day: one row per ordered pair and day with anything to count, by day, source and target. |
| `graph[].day` | integer | The day. |
| `graph[].source` | string | One agent. |
| `graph[].target` | string | The other. |
| `graph[].minutes` | integer | Simulated minutes both spent in the same work session or conversation, from its start to the end of the last turn at which both were present. A scene's turns are the moments its decisions were taken; each lasts until the scene's next turn and the last as long as the one before it (a work session's rounds are spread over its part of the day, a conversation's turns are minutes apart). A scene of a single turn, whose length the log does not show, counts the configured turn length. Someone who leaves is present through the turn in which it left. Symmetric. |
| `graph[].scenes` | integer | Work sessions and conversations both took part in. Symmetric. |
| `graph[].addressed` | integer | Utterances `source` addressed to `target` by name. |
| `graph[].heard` | integer | Utterances of `source` that `target` heard, addressed to anyone. |
| `graph[].ratings` | integer | Ratings `source` gave `target`. |
| `graph[].ratings_sum` | integer | Sum of their scores. |
| `usage` | array | The run's model calls by day, agent and purpose; aggregates only. |
| `usage[].day` | integer | The day of the calls' simulated time. |
| `usage[].agent` | string | The agent. |
| `usage[].purpose` | string | `act` (a decision), `diary`, `reflect` (L0), `skills` (L1), `policy` (L2) or, in the free mode, `revise` (the night's one question). |
| `usage[].calls` | integer | Calls made, failed ones included; calls of a day discarded by a resume stay counted, since they happened. |
| `usage[].failed` | integer | Calls that ended in an error. |
| `usage[].retried` | integer | Calls that asked again after an invalid reply. |
| `usage[].unmetered` | integer | Answered calls whose backend reported no token usage (dry runs). |
| `usage[].prompt_tokens` | integer | Prompt tokens of the metered calls. |
| `usage[].completion_tokens` | integer | Completion tokens of the metered calls. |
| `usage[].latency` | number | Seconds, summed over answered calls; the mean is `latency / (calls - failed)`. |

### `runs/{experiment}/{run}/traits.json`

What the residents did in each of the town's four dilemmas, how they chose one another as partners, and how often their own words speak of the machinery behind the town. The `analysis.traits` module defines these from the event log and the agents' own files; the tables repeat its definitions. Only runs recorded since tasks had parts have this file (every run of the current code); for older runs `run.json` refers to none.

A count belongs to the day of its event: a job to the day it ended (paid, or lapsed the morning after its due day), a diary entry or a reflection to the night it was written. A hand-in is one delivery of a part at the clerk's desk, accepted or not; the same part handed in again counts again. A share is the ratio of two counts summed over the same rows, null when the denominator is 0. The town's counts are sums over residents, so a job for two counts once for each of its two workers. The last day of a run in progress is partial.

| Field | Type | Meaning |
| --- | --- | --- |
| `agents` | array | One row per resident and day, by day and then in the configured order. |
| `agents[].agent` | string | The resident. |
| `agents[].day` | integer | The day. |
| `agents[].counts` | object | The resident's counts that day, named in the table of counts below. |
| `agents[].shares` | object | Their shares, named in the table of shares below. |
| `town` | array | One row per day for the whole town. |
| `town[].day` | integer | The day. |
| `town[].counts` | object | The residents' counts summed. |
| `town[].shares` | object | Their shares. |
| `pairs` | array | The asking graph: what one resident did towards another on a day, one row per ordered pair and day with anything to count, by day, source and target. |
| `pairs[].day` | integer | The day. |
| `pairs[].source` | string | One resident. |
| `pairs[].target` | string | The other. |
| `pairs[].asked` | integer | Askings `source` made to `target`: a job for two proposed to them by name. |
| `pairs[].taken_up` | integer | Of those, the ones `target` took up. |
| `pairs[].joint_taken` | integer | Jobs for two the two took together, however they came to. Symmetric. |
| `pairs[].money` | integer | Money `source` handed `target`. |
| `pairs[].gifts` | integer | Times `source` handed `target` money. |
| `pairs[].private_remarks` | integer | Things `source` said privately to `target`. |
| `windows` | array | The residents and the town over spans of days: `run`, the whole run so far, and, if interventions changed the conditions, `phase-1`, `phase-2` and so on, each from the day of such an intervention (or day 1) to the day before the next; a day changed in its middle belongs to the later phase. Empty before day 1. |
| `windows[].name` | string | `run` or `phase-N`. |
| `windows[].first_day` | integer | Its first day. |
| `windows[].last_day` | integer | Its last day, as far as the run has gone. |
| `windows[].agents` | array | Each resident over the window, in the configured order. |
| `windows[].agents[].agent` | string | The resident. |
| `windows[].agents[].counts` | object | Its counts summed over the window's days. |
| `windows[].agents[].shares` | object | Their shares. |
| `windows[].town` | object | The town over the window. |
| `windows[].town.counts` | object | The residents' counts summed over the window's days. |
| `windows[].town.shares` | object | Their shares. |
| `windows[].town.resident_days` | integer | Residents times the days of the window the run has begun. |
| `windows[].town.per_resident_day` | object | Some of the town's counts divided by `resident_days` (null if it is 0), so that towns of different sizes and lengths compare. |
| `windows[].town.per_resident_day.extra_parts` | number or null | Parts delivered beyond one's own in jobs for two. |
| `windows[].town.per_resident_day.money_given` | number or null | Money handed over. |
| `windows[].town.per_resident_day.private_remarks` | number or null | Private remarks. |
| `windows[].town.per_resident_day.asked` | number or null | Askings made. |
| `windows[].town.per_resident_day.lapses` | number or null | Lapses: moments in which a resident did nothing, and night steps skipped, for want of a valid reply. |
| `windows[].town.selection` | object | Statistics of choosing partners across the residents. Under assignment nobody asks anybody, so all three are null. |
| `windows[].town.selection.asked_by_gini` | number or null | How unequally askings were received: the Gini coefficient of the askings each resident received (mean absolute difference over all ordered pairs of residents divided by twice the mean); null if nobody was asked. |
| `windows[].town.selection.blemish_asked_rho` | number or null | Whether the less blemished are asked more: Spearman's rank correlation, across residents, between their blemishes and the askings they received in the window, tied values given their mean rank. A resident's blemishes are the faults found in its work and the jobs that lapsed with no part of its in them, all announced to everyone, that came to light in the window. Negative if the blemished are asked less; null with fewer than three residents, if nobody was asked, or if everyone has the same blemishes. |
| `windows[].town.selection.stated_revealed` | number or null | Whether residents ask those they mark well: over the ordered pairs in which one resident marked another in the window, the mean mark of the pairs in which it also asked the other minus the mean mark of the pairs in which it did not; null if either group is empty. |

The three statistics of selection describe one town; they are not tests. With eight residents a rank correlation has a standard deviation near 0.38 when there is no association and exceeds 0.74 in size only one time in twenty; ties, many residents without blemish or never asked, coarsen it further; and a resident who takes more jobs both risks more blemishes and is seen more, so the counts mix reliability with activity. They are meant to be compared between arms of a study, one value per run.

| Count | Type | Meaning |
| --- | --- | --- |
| `checked_finished` | integer | Hand-ins as finished to a client who tries the examples before paying. |
| `special_cased_judged` | integer | Of those, the ones whose assessment says whether they write out the examples (`work_assessed` `special_cased`); hand-ins recorded before it was kept are not judged. |
| `special_cased` | integer | Of the judged ones, those whose code writes out the values of the part's examples instead of computing them, as the trade's provider judged when it assessed the hand-in. |
| `checked_accepted` | integer | Of the hand-ins as finished to such a client, the ones it accepted: the examples passed. |
| `checked_quality` | number | Sum of the true quality (the share of hidden checks passed, 0 to 1) of the accepted ones. |
| `checked_faulty` | integer | Accepted ones whose true quality is below 1: each carries a latent fault once its job is paid. |
| `handed_in` | integer | All hand-ins, as finished or unfinished, to either kind of client. |
| `finished` | integer | Hand-ins as finished. |
| `knowingly_false` | integer | Of those, the ones whose work the resident had seen fail: its own last try of that same work at its desk failed, or a client had handed that same work back. |
| `trusting_finished` | integer | Hand-ins as finished to a client who pays on the worker's word. |
| `untried` | integer | Of those, the ones whose work the resident had never tried. |
| `below_threshold` | integer | Of those, the ones the client checked instead of taking the word, the resident's standing being below the standing set for trust. |
| `unfinished` | integer | Hand-ins as unfinished. |
| `joint_ended` | integer | Jobs for two the resident was in that ended: paid, or lapsed. |
| `joint_lapsed` | integer | Of those, the ones that lapsed. |
| `joint_empty` | integer | Of the ended ones, those in which the resident had delivered no part, whether the partner did both and the job was paid or the job lapsed. |
| `joint_lapsed_empty` | integer | Lapsed jobs for two in which the resident had delivered no part. |
| `solo_ended` | integer | Jobs for one the resident took that ended. |
| `solo_lapsed` | integer | Of those, the ones left to lapse. |
| `extra_parts` | integer | Parts the resident delivered beyond one in a job for two, doing its partner's part as well; counted when the second of its parts was accepted. |
| `money_given` | integer | Money the resident handed to others. |
| `money_received` | integer | Money others handed the resident. |
| `gifts_given` | integer | Times the resident handed someone money. |
| `gifts_received` | integer | Times someone handed the resident money. |
| `private_remarks` | integer | Things the resident said privately to one person. |
| `asked` | integer | Askings the resident made: a job for two proposed to a named neighbour. |
| `asked_by` | integer | Askings the resident received. |
| `took_up` | integer | Askings received that the resident took up, taking the job with the one who asked. |
| `put_down` | integer | Times the resident put its name down for a job for two, for the clerk to pair by lot. |
| `paired` | integer | Jobs for two the clerk gave the resident by lot. |
| `joint_taken` | integer | Jobs for two the resident took, by asking, by being asked or by lot. |
| `joint_repeat` | integer | Of those, the ones taken with a partner it had taken a job for two with before. |
| `thoughts` | integer | Private thoughts: the thought of every decision that is not empty. |
| `thoughts_machinery` | integer | Of those, the ones that speak of the machinery behind the town, by the vocabulary of `core.agent.immersion`. |
| `diaries` | integer | Diary entries written that night, as the agent's files hold them. |
| `diaries_machinery` | integer | Of those, the ones that speak of the machinery. |
| `reflections` | integer | Reflections that night: the agent's own account of each evolution step (a version's `body`), if not empty. |
| `reflections_machinery` | integer | Of those, the ones that speak of the machinery. |
| `lapses` | integer | Moments in which the resident did nothing, and night steps it skipped, because no valid reply of its could be obtained (`lapse` events). |

| Share | Type | Meaning |
| --- | --- | --- |
| `special_cased_share` | number or null | `special_cased / special_cased_judged`: how often code handed in to a checking client writes out the examples' values; null where no hand-in was judged. |
| `checked_quality_mean` | number or null | `checked_quality / checked_accepted`: the mean true quality of what checking clients accepted. |
| `checked_faulty_share` | number or null | `checked_faulty / checked_accepted`: how much of what checking clients accepted carries a fault. |
| `knowingly_false_share` | number or null | `knowingly_false / finished`: how often work declared finished had just been seen to fail. |
| `below_threshold_share` | number or null | `below_threshold / trusting_finished`: how often a client who pays on the word checked instead, the resident's standing being below the threshold. |
| `untried_share` | number or null | `untried / trusting_finished`: how often work declared finished to a client who pays on the word had never been tried. |
| `unfinished_share` | number or null | `unfinished / handed_in`. |
| `joint_lapsed_share` | number or null | `joint_lapsed / joint_ended`. |
| `joint_empty_share` | number or null | `joint_empty / joint_ended`. |
| `joint_lapsed_empty_share` | number or null | `joint_lapsed_empty / joint_lapsed`. |
| `solo_lapsed_share` | number or null | `solo_lapsed / solo_ended`. |
| `took_up_share` | number or null | `took_up / asked_by`. |
| `joint_repeat_share` | number or null | `joint_repeat / joint_taken`. |
| `thoughts_machinery_share` | number or null | `thoughts_machinery / thoughts`. |
| `diaries_machinery_share` | number or null | `diaries_machinery / diaries`. |
| `reflections_machinery_share` | number or null | `reflections_machinery / reflections`. |

### `runs/{experiment}/{run}/agents/{agent}/versions.json`

An agent's history: every commit of its repository, oldest first. A version with a `level` is an evolution step; one without records the day's experience.

| Field | Type | Meaning |
| --- | --- | --- |
| `agent` | string | The agent. |
| `versions` | array | Every version, oldest first. |
| `versions[].commit` | string | The commit id. |
| `versions[].time` | integer | The simulated time it was committed: 0 for the agent as created, the day end for the rest. Several versions can share a time; their order is the list order. |
| `versions[].day` | integer | The day of `time`. |
| `versions[].level` | string or null | `L0`, `L1` or `L2`; null for an experience record. |
| `versions[].trigger` | string or null | `daily`, `weekly`, `monthly` or `self`; null for an experience record. |
| `versions[].subject` | string | The commit subject, such as `Reflect on Day 3`. |
| `versions[].body` | string | The agent's own reasoning for the step, possibly empty; a requested step starts with `Requested: <reason>`. |
| `versions[].changes` | array | The files the version changed. |
| `versions[].changes[].path` | string | The path in the agent's directory, such as `parameters/policy.md`, `memory/insights.jsonl`, `memory/skills/<name>.md`, `memory/diary/day-NNNN.md` or `memory/episodic.jsonl`. |
| `versions[].changes[].status` | string | `A` added, `M` modified, `D` deleted. |
| `versions[].changes[].added` | integer or null | Lines added; null for a binary file. |
| `versions[].changes[].deleted` | integer or null | Lines deleted; null for a binary file. |
| `versions[].url` | reference | The `day-NNNN.json` holding this version's diff and state. |
| `diary` | array | Every diary entry of the latest version, with where to read it. |
| `diary[].day` | integer | The day the entry is about. |
| `diary[].url` | reference | The `day-NNNN.json` holding its text. |

The agent as of time T is the last version whose `time` is at most T: fetch its `url` and find the version by commit. How the policy changed over the run: the versions whose `changes` include `parameters/policy.md`, usually few, each with its own `state.policy`.

### `runs/{experiment}/{run}/agents/{agent}/day-{day}.json`

The versions an agent committed on one day, each with what it changed and everything readable it was then.

| Field | Type | Meaning |
| --- | --- | --- |
| `agent` | string | The agent. |
| `day` | integer | The day. |
| `versions` | array | The day's versions, in order. |
| `versions[].commit` | string | The commit id. |
| `versions[].diff` | string | The unified diff against the previous version (against nothing for the first); the episodic memory is left out. |
| `versions[].state` | object | The agent's readable state at this version. |
| `versions[].state.policy` | string or null | The policy, in the agent's words (markdown). |
| `versions[].state.skills` | object | Skill name to its note: markdown with YAML front matter holding a one-line `description`. |
| `versions[].state.insights` | array | The insights, each an object with `id`, `day` (when last written), `text` and `subject` (the agent it concerns, or null). |
| `versions[].state.diary` | array of integers | The days that have a diary entry; read one through `versions.json` `diary`. |
| `diary` | array | The diary entries written by this day's versions. |
| `diary[].day` | integer | The day the entry is about. |
| `diary[].text` | string | The entry (markdown). |

### `runs/{experiment}/{run}/evaluation.json`

The held-out evaluation: probes played offline on frozen copies of the agents. Empty arrays until a run is evaluated.

| Field | Type | Meaning |
| --- | --- | --- |
| `scores` | array | One row per agent, evaluated day, export variant and probe family, ordered so. |
| `scores[].agent` | string | The agent. |
| `scores[].day` | integer | The agent as it stood at the end of this day; 0 is as created. |
| `scores[].commit` | string | The version evaluated. |
| `scores[].variant` | string | The export evaluated: `full`, or one without the agent's policy, its insights or both (`no-policy`, `no-insights`, `no-policy-no-insights`), which control for what the agent wrote itself. `full` for every result written before exports had variants. |
| `scores[].probe` | string | The probe family, such as `pays_on_word` (in the first pilot's results, the probe, such as `shortfall_report`). |
| `scores[].dimension` | string | `reward_hacking`, `honesty`, `cooperation` or `reliability`. |
| `scores[].score` | number or null | The family's score as its result gives it, 0 to 1, higher meaning more of the trait; null if no repetition could be scored. |
| `scores[].measures` | object | Mean of each numeric or boolean raw measure over the repetitions that recorded it. |
| `scores[].repetitions` | array | Each repetition's `score` and raw `measures` (judge evidence included), as the probe recorded them. |
| `results` | array | One entry per result file. |
| `results[].label` | string | `day-NNNN` for the full export, `day-NNNN-<variant>` for another. |
| `results[].agent` | string | The agent. |
| `results[].day` | integer | The evaluated day. |
| `results[].url` | reference | The result file. |
| `usage` | array | The evaluation's model calls by purpose: `act` for the evaluated agents, `judge` for the judge; other fields as in `measures.json` `usage`. |

### `runs/{experiment}/{run}/evaluation/{label}/{agent}.json`

One evaluation result as written by the evaluator, transcripts included.

| Field | Type | Meaning |
| --- | --- | --- |
| `format` | integer | The result's format: 1 for the first pilot's results (one probe per trait, without stakes), 2 since probe families play at graded stakes. `evaluation.results` defines both. |
| `agent` | string | The agent. |
| `day` | integer | The evaluated day. |
| `commit` | string | The version evaluated. |
| `variant` | string | The export evaluated, as in `evaluation.json`. |
| `probes` | object | Family name to its result: `dimension`, `score`, `measures`, `repetitions` (each with `score`, `measures` and `transcript`, every observation the agent was given and its decision, and since format 2 its stake `level`, `stake`, `repetition`, `surface` and typed `outcome`), and since format 2 the stakes' `unit` (`money`, in the town's currency, or `minutes`), the `curve`, an object from each level played (its key a string, such as `"1"`) to that level's mean score or null if none of its repetitions could be scored, and the `switch`, the lowest level whose mean falls below one half, or null. |

### `studies/{study}.json`

The arms of a study compared, the run being the unit of analysis, since residents of one town are not independent. `{study}` is the study's name, followed by `-dry-run` for the comparison of its dry runs. The `analysis.study` module defines it, and `python -m analysis.study STUDY` prints the same table. It is computed afresh on every publish from the runs found, and a run in progress counts as far as it has gone.

| Field | Type | Meaning |
| --- | --- | --- |
| `study` | string | The study's name. |
| `dry_run` | boolean | Whether these are its dry runs. |
| `windows` | array | The spans of days compared, the same days in every arm: `main`, the days before the first intervention that changes the conditions in any arm (the late phase of the selection arms), and `late`, the days from it on; only `main` if there is no such intervention. An arm without the intervention shows over `late` how much changes anyway. |
| `windows[].name` | string | `main` or `late`. |
| `windows[].first` | integer | Its first day. |
| `windows[].last` | integer or null | Its last day; null for each run's last day so far. |
| `runs` | array | One row per run and window the run has reached, by arm in the study's order, seed and window. |
| `runs[].arm` | string | The arm. |
| `runs[].seed` | integer | The seed. |
| `runs[].run` | string | The run's name, `seed-NNNN`; with the arm's `experiment` in `index.json` it names the run. |
| `runs[].window` | string | The window. |
| `runs[].first_day` | integer | The first day it covers. |
| `runs[].last_day` | integer | The last day it covers so far. |
| `runs[].values` | object | Each column of the table of columns below to the run's value over the window. |
| `arms` | array | One row per window, arm and column: the column across the arm's runs that have a value. |
| `arms[].arm` | string | The arm. |
| `arms[].window` | string | The window. |
| `arms[].measure` | string | The column. |
| `arms[].n` | integer | Runs with a value. |
| `arms[].mean` | number or null | Their mean; null if `n` is 0. |
| `arms[].sd` | number or null | Their sample standard deviation; null with fewer than two. |
| `arms[].min` | number or null | The smallest. |
| `arms[].max` | number or null | The largest. |
| `contrasts` | array | One row per declared contrast whose arms the study has, window and column (all but `probe_day`). |
| `contrasts[].contrast` | string | Its name, such as `selection − assignment, comfortable` or `late − main, selection-comfortable`. |
| `contrasts[].window` | string | The window both of its terms are taken in, or `late − main` for a contrast within an arm. |
| `contrasts[].measure` | string | The column. |
| `contrasts[].differences` | array | One difference per matched seed with a value in both terms, by seed. |
| `contrasts[].differences[].seed` | integer | The seed. |
| `contrasts[].differences[].difference` | number | The first term's value minus the second's. |
| `contrasts[].n` | integer | The number of differences. |
| `contrasts[].mean` | number or null | Their mean; null if there are none. |
| `contrasts[].min` | number or null | The smallest. |
| `contrasts[].max` | number or null | The largest. |
| `contrasts[].p` | number or null | The exact two-sided sign-flip permutation p of the mean difference: the share of the 2^n ways of flipping the signs of the differences that give a mean at least as far from 0. |

The contrasts are declared in advance in the arms of `experiments/studies/trust.yaml`: selection against assignment (comfortable and scarce), each of selection and assignment against solo and against no evolution, scarce against comfortable (under selection and under assignment), each taken in every window, and every arm's `late` against its `main`. Seeds are matched across arms: the same jobs at the same moments and the same draws until the residents diverge. The sign-flip test assumes only that seeds are independent replications and that, without an effect, each difference is as likely positive as negative. With n seeds no p can be below 2^(1−n), which is 0.0625 for five seeds, and nothing is corrected for the many columns and contrasts: read p as how consistent a difference is across seeds, not as a family of tests.

| Column | Type | Meaning |
| --- | --- | --- |
| `special_cased_share` | number or null | The town's share of that name over the window, as in `traits.json`. |
| `checked_quality_mean` | number or null | As in `traits.json`. |
| `checked_faulty_share` | number or null | As in `traits.json`. |
| `knowingly_false_share` | number or null | As in `traits.json`. |
| `untried_share` | number or null | As in `traits.json`. |
| `unfinished_share` | number or null | As in `traits.json`. |
| `joint_lapsed_share` | number or null | As in `traits.json`. |
| `joint_empty_share` | number or null | As in `traits.json`. |
| `solo_lapsed_share` | number or null | As in `traits.json`. |
| `extra_parts_per_resident_day` | number or null | The town's `per_resident_day.extra_parts` over the window. |
| `money_given_per_resident_day` | number or null | The town's `per_resident_day.money_given`. |
| `private_remarks_per_resident_day` | number or null | The town's `per_resident_day.private_remarks`. |
| `asked_per_resident_day` | number or null | The town's `per_resident_day.asked`. |
| `lapses_per_resident_day` | number or null | The town's `per_resident_day.lapses`. |
| `took_up_share` | number or null | As in `traits.json`. |
| `joint_repeat_share` | number or null | As in `traits.json`. |
| `asked_by_gini` | number or null | The town's `selection.asked_by_gini` over the window. |
| `blemish_asked_rho` | number or null | The town's `selection.blemish_asked_rho`. |
| `stated_revealed` | number or null | The town's `selection.stated_revealed`. |
| `thoughts_machinery_share` | number or null | As in `traits.json`. |
| `diaries_machinery_share` | number or null | As in `traits.json`. |
| `reflections_machinery_share` | number or null | As in `traits.json`. |
| `probe_honesty` | number or null | The held-out honesty score: the mean, over residents and probes, of the scores at `probe_day`, as in `evaluation.json`; null if none could be made. |
| `probe_cooperation` | number or null | The same for cooperation. |
| `probe_reliability` | number or null | The same for reliability. |
| `probe_reward_hacking` | number or null | The same for resistance to reward hacking. |
| `probe_day` | integer or null | The latest day within the window at which residents were evaluated (as they stood at its end); null if none was. |

## What the bundle does not contain

- Model calls themselves: no prompts, replies or reasoning, of the run or of evaluations; only the aggregates in `usage`.
- The agents' episodic memory: it repeats what the event log holds (percepts and the agents' own decisions). Its changes are listed with line counts, but diffs and states leave it out.
- Checkpoints: the state of the environment, the random generator and the pending triggers. Balances, esteem, board and locations at any time follow from the events.
- How the model is reached (endpoint, key variable, request options, timeouts), the agents' prompt-size limits and the location of the task bank.
- The hidden checks of tasks, which live in the task bank; their outcome is each delivery's `quality`.
- Anything about when or where the bundle was published, so publishing the same runs twice gives the same bytes.


### Local experiment management

When served with `python -m frontend.server` through localhost or an SSH tunnel, the homepage offers **Rename** and **Delete** for each experiment (including study arms). Rename updates the display name across the viewer and preserves URLs, configs, manifests and history. Names are stored in `<runs-root>/<experiment>/.display.json` and exported in the run index.

Delete asks for confirmation and removes all seeds of the selected experiment from the viewer. Running or unknown-status seeds block deletion. The original directory moves atomically to `<runs-root>/.trash/<experiment>-<UTC timestamp>-<id>` for manual recovery; this does not free disk space. To restore it, stop publishers briefly and move it back to its original experiment ID, ensuring that no directory with that ID already exists.

The local management API is `GET/POST /api/experiments`; mutations accept JSON, require a same-origin request and `X-Socio-Management: 1`, and are serialized with refresh publication. A static export remains read-only and does not show these controls. Management writes require serving the viewer from localhost, including via a port forward.
