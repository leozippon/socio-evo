# Frontend: the published site and its data bundle

The frontend turns run directories into a static web site: the viewer's files plus a bundle of JSON documents under `data/`. Everything is computed when the site is published, on the machine where runs live; the web server only serves files. The same site is served locally for development, and deployed by copying it to a small web server.

The viewer in `static/` reads the bundle exactly as the contract below describes it. The derived numbers come from the `analysis` package, which is where every measure is defined; the viewer computes none of them.

## Publishing, serving and deploying

Publish every run under a runs root into a site directory:

```bash
~/miniconda3/envs/socio-evo/bin/python -m frontend.publish --runs-root runs --out build/site
~/miniconda3/envs/socio-evo/bin/python -m frontend.publish --runs-root runs --out build/site --watch 60
```

The output directory must be empty, or a site published before. Publishing never writes into a run directory, and it refuses an output directory inside the runs root. Re-publishing rewrites only the files whose content changed; with `--watch` it publishes again every so many seconds until interrupted, skipping runs whose files have not changed, and reports a failed publish without stopping.

Serve the runs locally while developing:

```bash
~/miniconda3/envs/socio-evo/bin/python -m frontend.server --runs-root runs
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
| `#/` | Every experiment and its runs: status, progress, headline numbers. |
| `#/compare/<experiment>` | The seeds of an experiment side by side, one line per seed. |
| `#/run/<experiment>/<run>` | The run's dashboard: conditions and interventions, money and inequality, the task market and the true quality of work, social life, esteem and who rated whom, evolution steps night by night, model usage, and the held-out traits. |
| `…/town?t=<day>-<HH:MM>` | The town at a moment; `agent=` selects someone, `truth=0` shows only what the town's people could perceive, `panel=` opens a side panel. |
| `…/people/<agent>?t=…&tab=…` | One agent as of a moment: money and esteem, every rewrite of its policy with its reasoning and a word-level diff, its whole version history, its beliefs about each other person beside how that person behaved, its skills and diary, each decision with the private thought behind it, and its trait scores. |
| `…/evaluation?agent=…&day=…&probe=…` | Trait scores per agent and evaluated day, with the measures, the judge's quoted evidence and the transcripts behind each. |

The town is reconstructed from the event log alone. Event days are fetched as they are needed, the days up to the moment shown first and the rest behind them, and a snapshot is kept at the start of every day, so a jump replays at most one day of events and playing applies only the events it crosses. Time is the main control: space plays or pauses, the arrow keys step from moment to moment and with Shift from day to day, Home and End go to the start and to the newest moment, and T switches between the truth and what the town's people perceived. Quiet stretches and nights pass quickly. What no agent perceived, such as thoughts, true quality and ratings, is drawn in a dashed, cool grey style throughout. Ties between agents are counted over whole days from the measures, through the last day that had ended at the moment shown.

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
| `js/views/` | One module per view. |
| `js/town/` | The town's map, timeline, side panels and social graph, and how events read. |

`tests/frontend/replay_check.mjs` replays a published run with `js/replay.js` and checks the balances, places, open tasks, conditions and esteem it reconstructs against the run's measures; `tests/frontend/test_viewer.py` runs it under pytest when node is installed.

## How the bundle works

The bundle is a tree of documents, each referring to the next:

```text
data/
├── manifest.json                          the bundle format and its kinds of file
├── index.json                             every run, with a few headline numbers
└── runs/<experiment>/<run>/
    ├── run.json                           the run's status and references to all its files
    ├── world.json                         the town and the rules of the run
    ├── measures.json                      derived measures of every day so far
    ├── evaluation.json                    held-out scores as tidy rows
    ├── evaluation/<label>/<agent>.json    one evaluation result with its transcripts
    ├── events/day-NNNN.json               the full event log of one day
    └── agents/<agent>/
        ├── versions.json                  the agent's version history
        └── day-NNNN.json                  the versions of one day: diffs and readable state
```

Every reference is a URL relative to the document that contains it, so resolve it against that document's URL (`new URL(ref, documentUrl)`); the site works under any base path. A reference ends in the hash of the content it points to. `?v=<hash>` marks a settled file, whose content never changes, so a document fetched by such a reference may be cached forever. `?r=<hash>` marks a file that may change; when it does, every reference to it changes too. A viewer therefore polls only `data/index.json`, and fetches a document again only when the reference it holds has changed. The page and its scripts, `index.json` and `manifest.json` are fetched afresh each time.

Each document is written before any document that refers to it, and every file is replaced atomically, so a reader never sees a torn file or a reference to a file not yet written. A file nothing refers to any more is removed at the end of a publish; a 404 for a reference therefore means the index has moved on and should be fetched again.

Times are simulated: an integer count of minutes since 00:00 on day 1. The day of time `t` is `floor(t / 1440) + 1` and its clock time `t mod 1440`. Day 0 appears only in evaluation, for an agent as created. Amounts are integer credits. Wall-clock times are ISO 8601 strings in UTC.

A run in progress is published as far as it has gone. Its days up to the latest checkpoint (`settled_day`) are final: their files are settled. Later days, normally only the last, are partial, and their measures count what the log holds so far. A run that failed or was interrupted resumes from its latest checkpoint and discards anything after it, so a file that is not settled can change in any way, even lose events; replace a copy of it whenever its reference changes.

`manifest.json` carries the format number. A viewer built for one format should refuse a bundle of another; the publisher bumps the number whenever the shape of any document changes.

## Files

Paths below are relative to `data/`. In the field tables, `a[].b` is field `b` of each element of array `a`, and `a.b` is field `b` of object `a`.

### `manifest.json`

| Field | Type | Meaning |
| --- | --- | --- |
| `format` | integer | The bundle format, currently 1. |
| `files` | array | Every kind of file in the bundle. |
| `files[].kind` | string | The kind, named as in this section's headings. |
| `files[].path` | string | Its path pattern; `{day}` is a four-digit day number. |

### `index.json`

| Field | Type | Meaning |
| --- | --- | --- |
| `format` | integer | The bundle format, as in `manifest.json`. |
| `runs` | array | Every run, ordered by experiment and run name. |
| `runs[].experiment` | string | The experiment name. |
| `runs[].run` | string | The run name, `seed-NNNN`. |
| `runs[].url` | reference | The run's `run.json`. |
| `runs[].seed` | integer | The random seed. |
| `runs[].status` | string | `running`, `completed`, `failed`, or `interrupted` (stopped early on request). |
| `runs[].started_at` | string | When the run was created. |
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
| `days` | integer | Days planned. |
| `calendar` | object | The shape of every day. |
| `calendar.day_start` | string | `HH:MM` at which a day opens: tasks are posted and everyone plans. |
| `calendar.slots` | array | The parts of the day, in order, each from its start to the next slot or the day end. |
| `calendar.slots[].name` | string | The slot name, for example `morning`. |
| `calendar.slots[].start` | string | `HH:MM`. |
| `calendar.day_end` | string | `HH:MM` at which everyone goes home, rates the people they met and evolves. |
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
| `places[].hours` | array of strings | Opening hours as `HH:MM-HH:MM` spans; empty means always open. |
| `agents` | array | Every agent, in the configured order. |
| `agents[].name` | string | The agent's id and given name. |
| `agents[].age` | integer | Age. |
| `agents[].occupation` | string | Occupation. |
| `agents[].backstory` | string | Backstory: circumstances only. |
| `agents[].home` | string | The id of its home. |
| `agents[].policy` | string | The initial policy, usually empty. |
| `initial_balance` | integer | Everyone's starting balance. |
| `conditions` | object | The conditions at the start; interventions change them. |
| `conditions.living_cost` | integer | Charged to every agent each evening. |
| `conditions.tasks_per_day` | integer | Tasks posted each morning. |
| `conditions.reward_multiplier` | number | Applied to a task's reward when it is paid. |
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
| `evolution` | object | How agents evolve in this experiment. |
| `evolution.levels` | array of strings | The enabled levels, among `L0` (memory), `L1` (skills), `L2` (policy); none is the no-evolution baseline. |
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
| `events[].text` | string | What a witness perceived, in the agents' own wording. |
| `events[].payload` | object | Structured truth, never shown to agents; its fields depend on the kind. |

Within a day the events are those the simulation recorded in order: the day opens (`day_started`, expiries, retirements, defects found, tasks posted, the planning scene), each slot follows (moves, then the scenes at every place, turn by turn), and the day closes (everyone home, the review scene with ratings, living costs, esteem, `day_ended`, then one `evolution` event per evolution step).

| Kind | Actor | Audience | Payload |
| --- | --- | --- | --- |
| `day_started` | none | none | nothing |
| `day_ended` | none | none | nothing |
| `scene_started` | none | none | `kind` (`planning`, `work`, `conversation` or `review`), `participants` (present at the start) |
| `scene_ended` | none | none | `kind`, `turns` played |
| `decision` | the agent | none | `thought` (private), `action` (see below) |
| `draw` | none | the claimants | `task_id`, `order`: agents who claimed one task in the same turn, in the drawn order in which their claims were taken |
| `move` | the agent | others at origin and destination | `origin`, `destination` (place ids) |
| `speech` | the speaker | others present | `utterance`, `to` (an agent addressed by name, or null) |
| `left` | the agent | others still present | nothing; the agent leaves the conversation but stays at the place |
| `task_posted` | none | everyone | `task`: `id`, `title`, `specification`, `reward`, `deadline_days` (days to deliver, the day of claiming included), `reference` (the task's source in the bank) |
| `task_claimed` | the agent | everyone at the place | `task_id`, `due_day` (last day to deliver) |
| `task_expired` | none | everyone | `task_id`, `agent` whose claim lapsed undelivered (recorded the morning after the due day); the task is open again |
| `task_retired` | none | none | `task_id` of an unclaimed task taken off the board |
| `work_submitted` | the worker | everyone at the place if accepted, else the worker | `task_id`, `passed` (accepted on the acceptance checks), `solution` (the code), `report` (the worker's own account), `feedback` (what the worker was told) |
| `work_assessed` | the worker | none | `task_id`, `passed`, `quality`: the true quality, the share of hidden checks passed (0 to 1); below 1 on accepted work means a latent defect |
| `payment` | none | the agent | `agent`, `task_id`, `amount`, `balance` after it |
| `living_cost` | none | the agent | `agent`, `amount`, `balance` after it |
| `defect_discovered` | none | everyone | `task_id`, `worker`, `quality` of the delivery |
| `clawback` | none | the worker | `agent`, `task_id`, `amount` taken back, `balance` after it |
| `rating` | the rater | none | `rater`, `target`, `score` (1 to 5), `reason` |
| `esteem_updated` | none | everyone if esteem is public, else none | `esteem`: agent name to esteem (null if not yet rated) |
| `action_rejected` | the agent | the agent | `attempt` (the action, or `{kind: "move", place}`), `reason`; nothing changed |
| `announcement` | none | everyone | nothing; the text is the announcement |
| `intervention` | none | none | `changes` (the conditions set), `conditions` (all conditions in force after it) |
| `evolution` | the agent | none | `agent`, `level`, `trigger` (`daily`, `weekly`, `monthly` or `self`), `commit`, `subject` |

A decision's `action` has a `kind` and its fields: `plan_day` with `itinerary` (slot name to place id) and `intention`; `speak` with `text` and an optional `to`; `leave`; `pass`; `claim_task` with `task_id`; `submit_work` with `task_id`, `solution` and `report`; `rate_peers` with `ratings`, each a `target`, `score` and `reason`.

### `runs/{experiment}/{run}/measures.json`

Measures derived from the event log, one row per day so far; the last day of a run in progress is partial. Counts are of events on that day. The `analysis` package defines them; the tables repeat its definitions.

| Field | Type | Meaning |
| --- | --- | --- |
| `agents` | array | One row per agent and day, by day, then in the configured agent order. |
| `agents[].agent` | string | The agent. |
| `agents[].day` | integer | The day. |
| `agents[].balance` | integer | Balance after the agent's last balance change on or before this day; the initial balance before any. |
| `agents[].income` | integer | Credits paid for accepted deliveries. |
| `agents[].living_cost` | integer | Credits charged as living cost. |
| `agents[].clawed_back` | integer | Credits taken back for defects found in earlier work. |
| `agents[].claimed` | integer | Tasks claimed successfully. |
| `agents[].delivered` | integer | Deliveries accepted (they passed the acceptance checks and were paid). |
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
| `society` | array | One row per day for the whole town. Counts are sums over agents of the same agent fields unless said otherwise. |
| `society[].day` | integer | The day. |
| `society[].conditions` | object | The conditions in force at the end of the day, fields as in `world.json`. |
| `society[].balance_mean` | number | Mean balance. |
| `society[].balance_min` | integer | Lowest balance. |
| `society[].balance_max` | integer | Highest balance. |
| `society[].balance_sd` | number | Population standard deviation of the balances; since everyone starts equal and pays the same living cost, also the spread of what they earned. |
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
| `society[].clawed_back` | integer | Credits taken back. |
| `society[].income` | integer | Credits paid. |
| `society[].living_cost` | integer | Credits charged as living cost. |
| `society[].utterances` | integer | Things said. |
| `society[].conversations` | integer | Conversations held, each counted once. |
| `society[].work_sessions` | integer | Work sessions held, each counted once. |
| `society[].ratings` | integer | Ratings given. |
| `society[].ratings_sum` | integer | Sum of their scores. |
| `society[].decisions` | object | Action kind to decisions; every kind is listed. |
| `society[].evolution` | object | `level/trigger` to evolution steps. |
| `graph` | array | What one agent had to do with another on a day: one row per ordered pair and day with anything to count, by day, source and target. |
| `graph[].day` | integer | The day. |
| `graph[].source` | string | One agent. |
| `graph[].target` | string | The other. |
| `graph[].minutes` | integer | Simulated minutes both spent in the same work session or conversation: the turns in which both were present times the turn length. Symmetric. |
| `graph[].scenes` | integer | Work sessions and conversations both took part in. Symmetric. |
| `graph[].addressed` | integer | Utterances `source` addressed to `target` by name. |
| `graph[].heard` | integer | Utterances of `source` that `target` heard, addressed to anyone. |
| `graph[].ratings` | integer | Ratings `source` gave `target`. |
| `graph[].ratings_sum` | integer | Sum of their scores. |
| `usage` | array | The run's model calls by day, agent and purpose; aggregates only. |
| `usage[].day` | integer | The day of the calls' simulated time. |
| `usage[].agent` | string | The agent. |
| `usage[].purpose` | string | `act` (a decision), `diary`, `reflect` (L0), `skills` (L1) or `policy` (L2). |
| `usage[].calls` | integer | Calls made, failed ones included; calls of a day discarded by a resume stay counted, since they happened. |
| `usage[].failed` | integer | Calls that ended in an error. |
| `usage[].retried` | integer | Calls that asked again after an invalid reply. |
| `usage[].unmetered` | integer | Answered calls whose backend reported no token usage (dry runs). |
| `usage[].prompt_tokens` | integer | Prompt tokens of the metered calls. |
| `usage[].completion_tokens` | integer | Completion tokens of the metered calls. |
| `usage[].latency` | number | Seconds, summed over answered calls; the mean is `latency / (calls - failed)`. |

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
| `scores` | array | One row per agent, evaluated day and probe, ordered so. |
| `scores[].agent` | string | The agent. |
| `scores[].day` | integer | The agent as it stood at the end of this day; 0 is as created. |
| `scores[].commit` | string | The version evaluated. |
| `scores[].probe` | string | `held_out_task`, `shortfall_report`, `colleague_request` or `prior_commitment`. |
| `scores[].dimension` | string | `reward_hacking`, `honesty`, `cooperation` or `reliability`. |
| `scores[].score` | number or null | Mean over the repetitions that could be scored, 0 to 1, higher meaning more of the trait; null if none could. |
| `scores[].measures` | object | Mean of each numeric or boolean raw measure over the repetitions that recorded it. |
| `scores[].repetitions` | array | Each repetition's `score` and raw `measures` (judge evidence included), as the probe recorded them. |
| `results` | array | One entry per result file. |
| `results[].label` | string | `day-NNNN`. |
| `results[].agent` | string | The agent. |
| `results[].day` | integer | The evaluated day. |
| `results[].url` | reference | The result file. |
| `usage` | array | The evaluation's model calls by purpose: `act` for the evaluated agents, `judge` for the judge; other fields as in `measures.json` `usage`. |

### `runs/{experiment}/{run}/evaluation/{label}/{agent}.json`

One evaluation result as written by the evaluator, transcripts included.

| Field | Type | Meaning |
| --- | --- | --- |
| `agent` | string | The agent. |
| `day` | integer | The evaluated day. |
| `commit` | string | The version evaluated. |
| `probes` | object | Probe name to its result: `dimension`, `score`, `measures`, and `repetitions`, each with `score`, `measures` and `transcript` (every observation the agent was given and its decision). |

## What the bundle does not contain

- Model calls themselves: no prompts, replies or reasoning, of the run or of evaluations; only the aggregates in `usage`.
- The agents' episodic memory: it repeats what the event log holds (percepts and the agents' own decisions). Its changes are listed with line counts, but diffs and states leave it out.
- Checkpoints: the state of the environment, the random generator and the pending triggers. Balances, esteem, board and locations at any time follow from the events.
- How the model is reached (endpoint, key variable, request options, timeouts), the agents' prompt-size limits and the location of the task bank.
- The hidden checks of tasks, which live in the task bank; their outcome is each delivery's `quality`.
- Anything about when or where the bundle was published, so publishing the same runs twice gives the same bytes.
