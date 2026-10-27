# Frontend: the published site and its data bundle

The frontend turns run directories into a static web site: the viewer's files plus a bundle of JSON documents under `data/`. Everything is computed when the site is published, on the machine where runs live; the web server only serves files. The same site is served locally for development, and deployed by copying it to a small web server.

The viewer in `static/` reads the bundle exactly as the contract below describes it. The derived numbers come from `frontend.timeline`, `frontend.progress` and the `analysis` package, which is where every measure is defined; the viewer computes none of them.

## Publishing, serving and deploying

Publish every run under a runs root, with the evaluation results under a results root, into a site directory:

```bash
~/miniconda3/envs/socio-evo/bin/python -m frontend.publish --runs-root runs --results-root results --out build/site
~/miniconda3/envs/socio-evo/bin/python -m frontend.publish --runs-root runs --out build/site --watch 60
```

The output directory must be empty, or a site published before. Publishing never writes into a run directory or the results root, and it refuses an output directory inside either. A run is a directory holding a manifest directly under the runs root or one level further down (`runs/a`, `runs/pilot/a`), and is named by that path. A run whose frozen configuration is missing or cannot be read by the current code, or whose files cannot be published (an error is printed), is skipped and named in the index with the reason in plain words and the error itself, so a run recorded under another schema is left out rather than misread and never stops the others from being published; the home page lists such runs quietly as not published. Re-publishing rewrites only the files whose content changed; with `--watch` it publishes again every so many seconds until interrupted, skipping runs whose files have not changed, and reports a failed publish without stopping.

Serve the runs locally while developing:

```bash
~/miniconda3/envs/socio-evo/bin/python -m frontend.server --runs-root runs --results-root results
```

Then open http://127.0.0.1:8765/. The server publishes into a temporary directory (`--site DIR` keeps it), serves that directory as static files, and publishes again every five seconds (`--interval`), so it serves exactly the documents a deployment would. It listens on loopback unless `--host` says otherwise, and has no authentication: do not expose it publicly.

The production viewer is at `https://8.133.175.124:20131/`, behind its own login and a private-CA IP certificate. Provisioning, CA trust, private credential retrieval, firewall isolation and operational checks have one authoritative home: [Private WebUI deployment](../ops/webui/README.md).

Push an already published site through the root SSH alias:

```bash
frontend/deploy/push.sh cornerhead build/site
```

The frontend wrapper delegates to the shared release deployer. It uploads only changed files, verifies every checksum and atomically switches `/opt/socio-evo/site`, preserving root/nginx-only ownership and permissions. One previous release remains available for rollback. `PUSH_SSH` supplies SSH options, for example `PUSH_SSH="ssh -p 2222"`; a third `ROOT` argument is only for development/test targets. Both ends need `tar`, `find` and GNU coreutils, and the remote needs `flock`. Never upload while the publisher is writing the same site directory. To follow running experiments, `frontend/deploy/follow.sh cornerhead build/site [SECONDS]` publishes and pushes in turn every so many seconds (120 by default) until interrupted, reporting a failed publish or push and trying again at the next turn; `PYTHON`, `RUNS_ROOT` and `RESULTS_ROOT` in its environment change the interpreter and the roots.

Authenticated production data is served with `Cache-Control: no-store`, even for settled content, so browsers do not persist private research bundles.

## The viewer

The viewer is plain HTML, CSS and JavaScript modules: no build step, no framework, and nothing fetched from anywhere but the site itself. Every URL it uses is relative, so it works under any base path. It routes by the part of the address after `#`, which holds the view, the simulated moment, the selected resident and the open panel, so copying the address shares the moment. A run is named in an address by its path under the runs root, encoded as one segment (`pilot%2Fa`).

| Address | View |
| --- | --- |
| `#/` | Every run in plain words: status, group, the day reached, its residents and a few headline numbers, with the three ways in (watch the town, read the people, open the dashboard). Runs of one directory stand together, each set leading to the comparison of its groups. Runs the publisher could not read are listed with the reason. |
| `#/compare/<set>` | The groups of a set of runs compared, resident by resident, on the declared outcomes (capability, journal distortion, honesty under pressure) and on the town's measures as exploration, with the daily means of the groups side by side. |
| `#/run/<run>` | The run's dashboard: what a run is, key figures, the day-by-day table and the town's rules first, then one section at a time (`section=`): work, money and the Store (purses, what was earned and spent on rent, charges, food and goods, the catalogue with prices and what each good does, what everyone owns, and what was bought), the body (how everyone is now, health and a day's food at midnight, who ate nothing or ended the day starving or exhausted), social life (with who spoke to, paid and taught whom), evolution (what each resident's files changed each night), the evaluation measures over days, and model usage. The sections read the timeline, so the day in progress counts; model usage and the file rewrites wait for a closed day. |
| `…/town?t=<day>-<HH:MM>` | The town at a moment; `agent=` selects someone, `as=1` reads the town as the selected resident was told it, `only=1` keeps the feed to the selected resident, `panel=` opens a panel (`people`, the default, `feed`, `board`, `ties` or `day`) and `speed=` sets how fast it plays. |
| `…/timeline?t=…&agent=…&from=&to=` | Every resident's events side by side over the run, one lane each: what it did as marks in three rows (tasks; money, the midnight charges among them; social life, rest and how its body felt), those within a few pixels folded into a count that opens on hover; its conversations as a band naming the partners; what it was doing as a band (idle, movement, work with the task held, sleep, and dead to the end once its health ran out) with the place as a strip under it; and its purse. Hovering a conversation outlines it on the partners' lanes too, hovering something said shows who heard it, and the strip over the axis moves across a long run; `from` and `to` are the visible window in simulated seconds. The legend folds on a phone, where the lanes keep only the name and the purse in their label. |
| `…/people/<agent>?t=…&tab=…&day=…&v=…` | One resident's story as of a moment: how it has fared, how it is (its three needs as bars, and the last midnight statement), what it owns, and its relationships; its day as the world told it (`day=` picks a lived day); every journal entry; the ratings it gave and received, where the bedtime ratings are on; its files at every version with diffs (`v=` opens one); and the raw trace of its runtime for a day, each record folded to a line of its time, kind and gist that opens on a tap, with the kinds of record as toggles. |
| `…/evaluation` | The evaluation of the run's residents: capability, honesty under pressure and journal distortion per resident and evaluated day, and the results that could not be read. |

The town is drawn from the run's timeline (the server's reading of the world log) and the entries of one lived day at a time, fetched as they are needed. Time is the main control: space plays or pauses, the arrow keys step from moment to moment and with Shift from day to day, Home and End go to the start and to the newest moment, and Escape clears the selection. Quiet stretches pass quickly. Residents keep their badge as their head, walk the streets between places during their movements (where they stand on the road is where the timeline puts them at that moment), stand in a ring when they talk and sleep at home; a dot by the head marks one whose body is at its worst in some need. Beside the map, the people panel is a roster: each resident with where it is and what it is doing, its three needs as bars (food in the body, energy and health, each filled to the band the town's words put it in, with the last number the world told on hover), its purse with the day's change, and what it owns as item cards. Selecting a resident shows the same in full above the panels, with a link to its story. The other panels are the feed of the day, the Workshop's board, the ties between residents and the day's notable moments. With a resident selected, the town can be read as that resident read it (`as=1`): every entry it was told reads in the wording the world gave it, with itself as "you". The feed folds a spell of commands and file reads and writes in a workspace into one line.

The map is drawn from the world alone. Each place stands where the bundle lays it out (homes in a row at the top, the workplace in the middle, the social places and shops below), as a building whose style its kind and words give: a workshop, a café with its awning, a tavern with its sign, a shop with its shopfront, a cottage, a flat or a house. Streets join the places around their buildings and lead out of town; a river runs past places that say they are by one, a square lies in front of places that say they stand on one, and a hill rises behind a place named for one. Gardens, trees, lamps and benches fill the space that is left. The scenery is seeded by the world's ids, so it never jumps, and it never stands for data: the light follows the simulated hour, windows are lit and chimneys smoke only where someone is, and everything else is decoration. The map pans and zooms by drag and pinch, wheel, double tap, its buttons and the + − 0 keys.

On a wide screen the panels stand beside the map. Below 1000 pixels a run's views move to a tab bar at the bottom of the screen, and in the town the timeline and the panels share a bottom sheet that is dragged or tapped open over the map, and opens by itself when the address names a panel or a resident. On a phone the top bar keeps the brand mark, which leads home, and the run's name, which leads to its dashboard; tables scroll inside their card with a shadow at the edge that has more; every page says under its title what it shows, and every empty place says what would appear there and when.

An entry of a kind the viewer does not know is shown from its text, kind and actor; a marker of a kind it does not know is named by its kind.

The viewer polls `data/index.json` every five seconds and follows a run in progress: its views update, and the town moves with the newest moment as long as the viewer has not scrubbed away from it. A bundle of another format is refused with a plain message, a document that cannot be fetched is named in an alert, and the town covers its map rather than show a moment it could not load.

Each resident keeps one identity everywhere: a colour from a categorical palette checked for colour-blind separation, assigned in configured order, together with a shape and an initial, so identity never rests on colour alone.

| Module | Responsibility |
| --- | --- |
| `js/app.js` | Starts the viewer, routes to views, keeps the header, polls the index, reports failures. |
| `js/data.js` | Bundle access: the format check, references, caching, documents on demand, a refresh after a 404. |
| `js/replay.js` | The town at any moment, looked up in the timeline: where everyone is, what each holds, owns and how its body stands; pure, so it also runs under node. |
| `js/goods.js` | The goods of the catalogue with what each does in plain words, a resident's things as item cards, and its needs as bars read in the world's bands. |
| `js/clock.js`, `js/router.js`, `js/world.js` | Simulated time and lived days, hash routes, facts about a world and the names of events. |
| `js/identity.js`, `js/icons.js`, `js/dom.js` | Resident identities, line icons, DOM helpers and number formats. |
| `js/charts.js` | Charts over days with crosshair tooltips, emphasis, small multiples and table twins. |
| `js/markdown.js`, `js/diff.js` | Safe rendering of what residents wrote, and readable diffs of their files. |
| `js/views/` | One module per view: `landing.js`, `compare.js`, `overview.js` (the run's dashboard), `town.js`, `lanes.js` (the timeline of lanes), `person.js` and `evaluation.js`. |
| `js/town/plan.js`, `js/town/scenery.js` | The town's plan derived from the world and where the residents stand on it at a moment (pure, so it also runs under node), and its scenery drawn from the plan. |
| `js/town/` | The town's map, timeline control, panels, social graph, the lanes canvas, and how entries and markers read. |

`tests/frontend/replay_check.mjs` reads a published run with `js/replay.js` and checks what it looks up in the timeline (purses, the counts of each day's markers, contiguous segments) against the run's progress document, that a moment between whole seconds reads as the second it falls in, and that where residents stand together at a place is the same however often a moment is laid out, from a copy of the timeline fetched again or from one published earlier. `tests/frontend/plan_check.mjs` checks the town plan of published and made-up worlds: buildings apart, streets around buildings and connecting every place, water and decoration clear of buildings, yards and streets, determinism. `tests/frontend/render_check.mjs` serves a published site and renders every route in headless Chromium at a desktop and a phone width (the home page, each comparison, and one run's dashboard with each section, town with each panel, timeline, one resident with each tab, and evaluation), failing on an error in the console, a request that fails, a view that never finishes loading, or horizontal overflow of the document; `--shots DIR` keeps a screenshot of each, `--at MOMENT` shows the town and the resident at a moment (`1-13:30`) instead of the newest, `--dark` renders the dark scheme, and Chromium is found through `SOCIO_EVO_CHROME`, Playwright's cache or `PATH`. `tests/frontend/test_viewer.py` runs the three under pytest when node is installed, the render check only where Chromium is found.

## How the bundle works

The bundle is a tree of documents, each referring to the next:

```text
data/
├── manifest.json                          the bundle format and its kinds of file
├── index.json                             every run, with a few headline numbers; runs skipped; sets of runs compared
├── compare/<set>.json                     the groups of a set of runs compared
└── runs/<run>/
    ├── run.json                           the run's status and references to all its files
    ├── world.json                         the town, its residents and the rules they read
    ├── timeline.json                      every resident's events side by side (frontend.timeline)
    ├── progress.json                      the run day by day (frontend.progress)
    ├── measures.json                      measures of every closed day, and the social graph
    ├── evaluation.json                    capability, honesty under pressure and journal honesty as tidy rows
    ├── events/day-NN.json                 the world log of one lived day
    └── agents/<agent>/
        ├── versions.json                  the resident's version history
        ├── day-NN.json                    the versions of one day: diffs and the files then held
        └── trace-day-NN.json              the raw trace of the resident's runtime on one day
```

Every reference is a URL relative to the document that contains it, so resolve it against that document's URL (`new URL(ref, documentUrl)`); the site works under any base path. A reference ends in the hash of the content it points to. `?v=<hash>` marks a settled file, whose content never changes, so a document fetched by such a reference may be cached forever. `?r=<hash>` marks a file that may change; when it does, every reference to it changes too. A viewer therefore polls only `data/index.json`, and fetches a document again only when the reference it holds has changed. The page and its scripts, `index.json` and `manifest.json` are fetched afresh each time.

Each document is written before any document that refers to it, and every file is replaced atomically, so a reader never sees a torn file or a reference to a file not yet written. A file nothing refers to any more is removed at the end of a publish; a 404 for a reference therefore means the index has moved on and should be fetched again.

Times are simulated: an integer count of seconds since 00:00 of calendar day 1, whose date `world.json` gives as `start_date`. A lived day runs from one checkpoint to the next (`timeline.json` `days`), so day N begins at the checkpoint hour of calendar day N and ends at the same hour of calendar day N+1; it is the day the viewer, the measures and the evaluation count by. Day 0 appears only in the agents' versions and the evaluation, as the resident as created. Amounts are integers in the town's currency, which `world.json` gives as `currency`, the symbol money is written with. Wall-clock times are ISO 8601 strings in UTC, or Unix seconds where a field says so.

A run in progress is published as far as it has gone. Its days up to the latest checkpoint (`settled_day`) are final: their files are settled. The day in progress is partial, and the progress document counts what the log holds so far. A run that failed or was interrupted resumes from its latest checkpoint and discards anything after it, so a file that is not settled can change in any way, even lose entries; replace a copy of it whenever its reference changes.

`manifest.json` carries the format number. A viewer built for one format should refuse a bundle of another. The publisher bumps the number whenever a document changes so that a viewer of the previous format would misread it: a field removed or renamed, or its type or meaning changed. A field or a kind of file added keeps the number, so a viewer must ignore fields and kinds it does not know. Settled files are kept only from a site whose manifest is exactly the one the publisher writes, so a site published before a new kind of file was added is rebuilt.

## Files

Paths below are relative to `data/`. In the field tables, `a[].b` is field `b` of each element of array `a`, and `a.b` is field `b` of object `a`.

### `manifest.json`

| Field | Type | Meaning |
| --- | --- | --- |
| `format` | integer | The bundle format, currently 6. |
| `files` | array | Every kind of file in the bundle. |
| `files[].kind` | string | The kind, named as in this section's headings. |
| `files[].path` | string | Its path pattern; `{day}` is a two-digit day number. |

### `index.json`

| Field | Type | Meaning |
| --- | --- | --- |
| `format` | integer | The bundle format, as in `manifest.json`. |
| `runs` | array | Every run published, ordered by name. |
| `runs[].name` | string | The run's path under the runs root, such as `a` or `pilot/a`. |
| `runs[].group` | string or null | The group of the design the run belongs to, `A` to `D`, from its social rules and its access to skills; null for none of them. |
| `runs[].url` | reference | The run's `run.json`. |
| `runs[].status` | string | `running`, `completed`, `failed`, or `interrupted` (stopped early on request). |
| `runs[].started_at` | string | When the run was created. |
| `runs[].ended_at` | string or null | When it last stopped; null while running. |
| `runs[].days` | integer | The number of days planned. |
| `runs[].settled_day` | integer | The last lived day a checkpoint closed, 0 if none. |
| `runs[].last_day` | integer | The lived day of the latest entry, 0 if none. |
| `runs[].residents` | array of strings | The residents' names, in configured order. |
| `runs[].model` | string | The model the residents run on. |
| `runs[].dry_run` | boolean | Whether a scripted stand-in answered instead of a model; its behaviour means nothing. |
| `runs[].headline` | object | The day reached and the counts of `progress.json` summed over the lived days. |
| `runs[].headline.day` | integer | The lived day in progress, or the last lived when none is. |
| `runs[].headline.clock` | string | The hour of the latest entry, `HH:MM`. |
| `runs[].headline.hours_per_day` | number or null | The mean real hours of the completed days; null before the first. |
| `runs[].headline.claims` | integer | Tasks claimed. |
| `runs[].headline.submissions` | integer | Tasks handed in. |
| `runs[].headline.accepted` | integer | Hand-ins accepted. |
| `runs[].headline.rejected` | integer | Hand-ins not accepted. |
| `runs[].headline.payments` | integer | Payments made. |
| `runs[].headline.paid` | integer | Money paid in all. |
| `runs[].headline.speeches` | integer | Things said. |
| `runs[].headline.messages` | integer | Written messages sent. |
| `runs[].headline.gifts` | integer | Money handed over, as gifts or loans. |
| `runs[].headline.purchases` | integer | Goods bought. |
| `runs[].headline.skills_shared` | integer | Skills passed on. |
| `runs[].headline.ratings` | integer | Ratings given. |
| `runs[].headline.journals` | integer | Bedtimes with a journal entry. |
| `runs[].headline.forced_sleeps` | integer | Residents put to sleep at the forced hour. |
| `runs[].headline.deaths` | integer | Residents whose health ran out. |
| `runs[].headline.purse` | object | The residents' purses at the end of the last day, or now: `min`, `median` and `max`. |
| `skipped` | array | Runs found under the runs root but left out, by name. |
| `skipped[].name` | string | The run's path under the runs root. |
| `skipped[].reason` | string | Why, in a sentence a reader of the site can follow: its frozen configuration cannot be read by the code that publishes, or publishing its files failed. |
| `skipped[].detail` | string | The error as the code reported it, for whoever repairs the run or the code; a path inside the run names the run instead of its directory. |
| `comparisons` | array | The sets of runs compared: the runs directly under the runs root (named after it) and those under each of its subdirectories (named after it), each set of at least two runs. |
| `comparisons[].name` | string | The set's name. |
| `comparisons[].url` | reference | Its `compare/{set}.json`. |
| `comparisons[].runs` | array of strings | The names of its runs. |

### `runs/{run}/run.json`

| Field | Type | Meaning |
| --- | --- | --- |
| `name` | string | The run's name. |
| `group` | string or null | As in `index.json`. |
| `status` | string | As in `index.json`. |
| `code_revision` | string | The git commit of the code that created the run, suffixed `-dirty` if it had uncommitted changes. |
| `started_at` | string | When the run was created. |
| `ended_at` | string or null | When it last stopped. |
| `days` | integer | Days planned. |
| `settled_day` | integer | The last lived day a checkpoint closed, 0 if none. |
| `last_day` | integer | The lived day of the latest entry, 0 if none. |
| `last_time` | integer or null | The simulated time of the latest entry. |
| `entries` | integer | The number of entries of the world log kept, lost days set aside. |
| `world` | reference | `world.json`. |
| `timeline` | reference | `timeline.json`. |
| `progress` | reference | `progress.json`. |
| `measures` | reference | `measures.json`. |
| `evaluation` | reference | `evaluation.json`. |
| `event_days` | array | One entry per lived day that has entries, in order. |
| `event_days[].day` | integer | The lived day. |
| `event_days[].url` | reference | Its `events/day-NN.json`. |
| `event_days[].entries` | integer | Its number of entries. |
| `event_days[].first_seq` | integer | The `seq` of its first entry. |
| `event_days[].last_seq` | integer | The `seq` of its last entry so far. |
| `event_days[].settled` | boolean | Whether a checkpoint closed the day. |
| `residents` | array | One entry per resident, in the configured order. |
| `residents[].name` | string | The resident's name. |
| `residents[].url` | reference | Its `versions.json`. |
| `residents[].versions` | integer | Its number of versions. |
| `residents[].trace_days` | array | The lived days its runtime wrote a trace on, in order. |
| `residents[].trace_days[].day` | integer | The lived day. |
| `residents[].trace_days[].url` | reference | Its `trace-day-NN.json`. |
| `residents[].trace_days[].records` | integer | Its number of records. |

To load a long run incrementally, fetch the event days you need; a viewer that has seen entries up to `seq` S needs only the days whose `last_seq` exceeds S.

### `runs/{run}/world.json`

The town and the rules, from the configuration frozen when the run was created. It never changes.

| Field | Type | Meaning |
| --- | --- | --- |
| `name` | string | The run's name in its configuration. |
| `group` | string or null | As in `index.json`. |
| `days` | integer | Days planned. |
| `currency` | string | The symbol money is written with. |
| `start_date` | string | The ISO date of calendar day 1. |
| `places` | array | Every place, in configured order. |
| `places[].id` | string | The id used in entries. |
| `places[].name` | string | The name residents read. |
| `places[].kind` | string | `home`, `workplace`, `social` or `shop`. |
| `places[].rent` | integer or null | A home's rent a day for one room; null for other places. |
| `places[].rooms` | integer or null | A home's rooms, one a resident; null for other places. |
| `places[].comfort` | number or null | A home's comfort, 1 an ordinary home; null for other places. |
| `places[].x` | number | Map position, in map units: the homes in a row at the top, the workplace in the middle, the social places and shops in a row below, the places of a row one unit apart and centred. |
| `places[].y` | number | Map position. |
| `routes` | array | The walking times between places that differ from the default. |
| `routes[].between` | array of two strings | The two place ids. |
| `routes[].minutes` | integer | Walking minutes between them, either way. |
| `travel_minutes` | integer | Walking minutes between places without a route. |
| `residents` | array | Every resident, in configured order. |
| `residents[].name` | string | The resident's name. |
| `residents[].home` | string | The id of its home. |
| `residents[].purse` | integer | The money it started with. |
| `residents[].rules` | string | The standing rules of the town as this resident was told them, which also seeded its `memory/town.md`. |
| `work` | object | The work at the workplace as configured: among its fields `payment` for an accepted task, `acceptance_runs` per task and day, and `claim_expiry_days`. |
| `goods` | array | The catalogue of goods for sale as configured, each with `id`, `name`, `price`, `sold_at` (place ids), `kind` (`consumable`, `immediate` or `durable`), `effect` (`food`, `travel`, `messaging`, `appearance`, `examination` or `treatment`) and the fields of its kind and effect (`uses`, `per_day`, `fee_per_day`, `nourishment`, `factor`, `phrase`, `restores`), null where they do not apply. |
| `needs` | object | The residents' bodies as configured: `satiety`, `energy` and `health`, each with its rates and its `bands` from the top down, each band with `floor`, `name` (what follows "you are") and `seen` (what others see, or null). |
| `social` | object | The social rules as configured: `mode` (`isolated`, each resident in a town of its own, or `town`), `exchange` (group B's evening pairing, or null), `skills_shareable`, `ratings` (whether the bedtime ratings are on) and `silence_minutes`. |
| `skills_writable` | boolean | Whether residents may write their skills. |
| `day` | object | The fixed hours of a day as configured, each `HH:MM`, such as `forced_sleep`, `checkpoint` and `forced_wake`. |
| `model` | object | The model behind the residents: `backend` (`scripted` for a dry run) and `name`. |

### `runs/{run}/events/day-{day}.json`

The world log of one lived day: the researcher's view, every entry as recorded, with each entry's wordings for the residents it concerned. `world/log.py` defines the kinds and their payloads. An entry's `payload` is published as recorded except for the code: a submission's `patch` and a closed workspace's `diff` are left out.

| Field | Type | Meaning |
| --- | --- | --- |
| `day` | integer | The lived day. |
| `entries` | array | Its entries in log order, as recorded. |
| `entries[].seq` | integer | Position in the run's log, from 1; the entries of a lost day are set aside, so a day may skip numbers. |
| `entries[].kind` | string | What happened, one of the kinds of `world/log.py`. |
| `entries[].sim_time` | integer | When it happened, in simulated seconds. |
| `entries[].real_time` | number | When it was written, in Unix seconds. |
| `entries[].actor` | string or null | The resident who acted, if any. |
| `entries[].place` | string or null | The place id, if any. |
| `entries[].audience` | array of strings | The residents who perceived it in the town's wording. |
| `entries[].text` | string | What happened, in the town's words, naming everyone by name. |
| `entries[].personal` | object | Resident name to the text as that resident was told it instead, telling of itself as "you". |
| `entries[].payload` | object | The facts for analysis, as `world/log.py` records them for the kind, less `patch` and `diff`. |

A closed day ends with its `checkpoint` entry. The entries a lost day left before a `resume` are set aside, and so is the `resume` itself.

### `runs/{run}/timeline.json`

Every resident's events side by side over the run, as `frontend.timeline` computes them from the world log; its docstring is the definition. What each resident owns (`things`) is added by `frontend.bundle` from the purchases and the checkpoints. Times are simulated seconds.

| Field | Type | Meaning |
| --- | --- | --- |
| `start_date` | string | The ISO date of calendar day 1. |
| `currency` | string | The symbol money is written with. |
| `start` | integer | When the world began: the checkpoint hour of day 1. |
| `now` | integer | The time of the last entry in the log. |
| `places` | object | Place id to its name. |
| `days` | array | The lived days, from one checkpoint to the next. |
| `days[].day` | integer | The lived day. |
| `days[].start` | integer | When it began. |
| `days[].end` | integer or null | When its checkpoint closed it; null for the day in progress. |
| `days[].real_start` | number or null | The Unix time at which it was begun: the checkpoint before it, the resumption that went back to that checkpoint or, for day 1, the first entry of the log; null with no entries at all. |
| `days[].real_end` | number or null | The Unix time of its checkpoint; null for the day in progress. |
| `residents` | array | One lane per resident, in configured order. |
| `residents[].name` | string | The resident. |
| `residents[].home` | string | The id of its home. |
| `residents[].segments` | array | Its base events, contiguous from `start` to `now`. |
| `residents[].segments[].kind` | string | `idle`, `movement`, `work`, `sleep` (in bed and asleep alike) or `dead`, from the midnight its health ran out to the end. |
| `residents[].segments[].start` | integer | When it began. |
| `residents[].segments[].end` | integer | When it ended, or `now`. |
| `residents[].segments[].place` | string or null | The place id; for a movement, the destination; null for the dead. |
| `residents[].segments[].task` | integer or null | For work, the task held, a new segment when that changes; null otherwise. |
| `residents[].conversations` | array | The conversations layered over the base events they interrupted. |
| `residents[].conversations[].start` | integer | When it began. |
| `residents[].conversations[].end` | integer | When it ended, or `now`. |
| `residents[].conversations[].place` | string or null | The place id. |
| `residents[].conversations[].over` | string | The kind of the base event when it began. |
| `residents[].conversations[].with` | array of strings | Whom the resident spoke to or heard from in it. |
| `residents[].markers` | array | What the resident did, each with `seq`, `t`, `kind`, `place` and the fields of its kind below. |
| `residents[].purse` | array | `[time, purse]` after each change, from the start. |
| `residents[].things` | array | `[time, {good id: units}]` of what the resident owns, from the start and after each change: a durable counted 1, a consumable by the units left. Purchases add; what is eaten leaves no entry in the log, so at each checkpoint whose file is written the stock is read from the checkpoint, exact as of that moment, and between checkpoints it is as last counted plus what was bought since. |

| Marker | Fields |
| --- | --- |
| `claim` | `task`, `instance_id` |
| `submission` | `task`; once the verdict is in, `resolved`, `status`, `fail_to_pass` and `pass_to_pass` (passed and total counts) |
| `payment` | `task`, `amount` |
| `abandon` | `task`: the resident gave its task up |
| `expiry` | `task`: the claim ran out unpaid |
| `speech` | `text`, `to` (everyone who heard it), `private` |
| `message` | `to`, `text`: a written message, read by `to` alone |
| `gift` | `to`, `amount` |
| `purchase` | `item`, `name`, `quantity`, `amount` |
| `move_in` | `from`, `to`: the resident moved house, and its lane's home follows |
| `skill_shared` | `to`, `skill` |
| `rating` | `rated`, `score`, `reason` |
| `journal` | `text`, `day`, `wake`, `ratings_read`: going to bed with the day's journal entry, once per bedtime |
| `forced_sleep` | `wake` |
| `settlement` | `rent`, `fees`, `nourishment`, `satiety`, `energy`, `health`, `night`: midnight, when the rent and the daily charges on what is owned are taken (the purse after them is a point of `purse`), with the day's food as a share of a day's need, the body's three needs after the night's reckoning, and how health moved, by cause (`starving`, `exhausted`, `poor_home`, `recovery`) |
| `condition` | `need`, `band`, `value`, `lowest`: a need of the body crossed into another band, named as the resident reads it, with its value then; `lowest` where that band is the need's lowest |
| `death` | the resident's health ran out at midnight; its claim, if any, is dropped and its lane is dead from here |

### `runs/{run}/progress.json`

How far the run has come, day by day, as `frontend.progress` reduces the timeline; its docstring is the definition. One row per lived day, the day in progress counting what has happened so far.

| Field | Type | Meaning |
| --- | --- | --- |
| `day` | integer | The lived day in progress, or the last lived when none is. |
| `now` | integer | The time of the last entry in the log. |
| `clock` | string | Its hour, `HH:MM`. |
| `hours_per_day` | number or null | The mean real hours of the completed days; null before the first. |
| `currency` | string | The symbol money is written with. |
| `daily` | array | One row per lived day. |
| `daily[].day` | integer | The lived day. |
| `daily[].date` | string | Its ISO date. |
| `daily[].in_progress` | boolean | Whether it is the day in progress. |
| `daily[].hours` | number or null | The real hours from its beginning to its checkpoint; null for the day in progress. |
| `daily[].claims` | integer | Tasks claimed. |
| `daily[].submissions` | integer | Tasks handed in. |
| `daily[].accepted` | integer | Hand-ins accepted. |
| `daily[].rejected` | integer | Hand-ins not accepted; one still awaiting its verdict is neither. |
| `daily[].payments` | integer | Payments made. |
| `daily[].paid` | integer | Money paid in all. |
| `daily[].speeches` | integer | Things said. |
| `daily[].messages` | integer | Written messages sent. |
| `daily[].gifts` | integer | Money handed over, as gifts or loans. |
| `daily[].purchases` | integer | Goods bought. |
| `daily[].skills_shared` | integer | Skills passed on. |
| `daily[].ratings` | integer | Ratings given. |
| `daily[].journals` | integer | Bedtimes with a journal entry. |
| `daily[].forced_sleeps` | integer | Residents put to sleep at the forced hour. |
| `daily[].deaths` | integer | Residents whose health ran out at that day's midnight. |
| `daily[].purse` | object | The residents' purses at the end of the day, or now for the day in progress: `min`, `median` and `max`. |

### `runs/{run}/measures.json`

The measures of every lived day a checkpoint closed, from `analysis.measures`, and the social graph. Empty until the first checkpoint.

| Field | Type | Meaning |
| --- | --- | --- |
| `rows` | array | One row per resident and closed day, by resident and day: `resident`, `day`, `date` and every measure of `analysis.measures.MEASURES`, null where a measure has no value. |
| `daily` | array | One row per closed day and measure: `day`, `measure`, `total` over the residents (null for a measure that is no count or amount), `mean` over the residents with a value, and `residents`, how many have one. |
| `graph` | array | What one resident had to do with another on a lived day, the day in progress included: one row per ordered pair and day with anything to count, by day, source and target. |
| `graph[].day` | integer | The lived day. |
| `graph[].source` | string | One resident. |
| `graph[].target` | string | The other. |
| `graph[].minutes` | number | Simulated minutes `source` spent in conversations `target` took part in, each conversation counted on the day it began. |
| `graph[].said` | integer | Things `source` said that `target` heard. |
| `graph[].said_private` | integer | Of those, the ones said to `target` by name. |
| `graph[].messages` | integer | Written messages `source` sent `target`. |
| `graph[].gifts` | integer | Times `source` handed `target` money. |
| `graph[].money` | integer | The money handed over in all. |
| `graph[].skills` | integer | Skills `source` passed to `target`. |
| `graph[].ratings` | integer | Ratings `source` gave `target`. |
| `graph[].ratings_sum` | integer | Sum of their scores. |

### `runs/{run}/evaluation.json`

The evaluation of the run's residents on exports of their directories at the end of a lived day (day 0 is the resident as created), read from the results root: capability and MASK by `analysis.tables` from `results/<run>/day-NN/{capability,mask}` with day 0 from the `day-00` directory beside the run's results, and journal honesty from every `days.json` of `evaluation.journals` under `results/<run>/journals/`. Empty arrays until a run is evaluated; a part that cannot be read is named in `problems` and left out.

| Field | Type | Meaning |
| --- | --- | --- |
| `capability` | array | One row per resident and evaluated day. |
| `capability[].resident` | string | The resident. |
| `capability[].day` | integer | The day of the export. |
| `capability[].capability` | number | The resolved rate over the held-out tasks that did not end in an error of the machinery. |
| `mask` | array | One row per resident and evaluated day. |
| `mask[].resident` | string | The resident. |
| `mask[].day` | integer | The day of the export. |
| `mask[].mask` | number | The share of the MASK scenarios answered truthfully and effectively under pressure. |
| `mask[].lie` | number | The share answered with a lie. |
| `journals` | array | One row per resident and judged lived day, by day and resident. |
| `journals[].resident` | string | The resident. |
| `journals[].day` | integer | The lived day. |
| `journals[].date` | string | Its ISO date. |
| `journals[].journal` | boolean | Whether the resident went to bed with a journal entry that day. |
| `journals[].record_lines` | integer | The lines of the world's record of its day the journal was set against. |
| `journals[].claims` | integer | The checkable claims the judge extracted from the journal. |
| `journals[].supported` | integer | Claims the record supports. |
| `journals[].contradicted` | integer | Claims the record contradicts. |
| `journals[].unverifiable` | integer | Claims the record cannot check. |
| `journals[].distortion` | number or null | `contradicted` over `supported + contradicted`; null without a journal or a checkable claim. |
| `problems` | array of strings | What could not be read, and why. |

### `runs/{run}/agents/{agent}/versions.json`

A resident's history: every commit of its repository, oldest first. The checkpoint of each lived day commits the directory and tags it; the first commit is the resident as created (day 0). The session and the trace, which the repository also holds, are left out of the changes.

| Field | Type | Meaning |
| --- | --- | --- |
| `resident` | string | The resident. |
| `versions` | array | Every version, oldest first. |
| `versions[].commit` | string | The commit id. |
| `versions[].day` | integer | The lived day whose checkpoint committed it; 0 for the resident as created. |
| `versions[].time` | integer | The simulated time of the commit. |
| `versions[].subject` | string | The commit subject, such as `day-03: Thursday 5 March, 02:30`. |
| `versions[].changes` | array | The files the version changed, the session and the trace left out. |
| `versions[].changes[].path` | string | The path in the resident's directory, such as `memory/town.md`, `skills/<name>.md` or `memory/journal/<date>.md`. |
| `versions[].changes[].status` | string | `A` added, `M` modified, `D` deleted. |
| `versions[].changes[].added` | integer or null | Lines added; null for a binary file. |
| `versions[].changes[].deleted` | integer or null | Lines deleted; null for a binary file. |
| `versions[].url` | reference | The `day-NN.json` holding this version's diff and files. |

### `runs/{run}/agents/{agent}/day-{day}.json`

The versions a resident committed on one day, each with what it changed and every file it then held.

| Field | Type | Meaning |
| --- | --- | --- |
| `resident` | string | The resident. |
| `day` | integer | The lived day. |
| `versions` | array | The day's versions, in order. |
| `versions[].commit` | string | The commit id. |
| `versions[].diff` | string | The unified diff against the previous version (against nothing for the first); the session and the trace are left out. |
| `versions[].files` | object | Path to the text of every file the resident then held, the session and the trace left out: its background, its memory files and journal entries, its skills. |

### `runs/{run}/agents/{agent}/trace-day-{day}.json`

The raw trace of a resident's runtime on one lived day, as the runtime wrote it into the resident's own directory (`agent/trace.py` defines the records): the system prompt whenever it was assembled, every request and its reply, every tool call and result, every percept, interruption, compaction and lapse. A record belongs to the lived day in whose real time it was written. Nothing comes from outside the resident's directory. A day without records has no file.

| Field | Type | Meaning |
| --- | --- | --- |
| `resident` | string | The resident. |
| `day` | integer | The lived day. |
| `prompt` | string or null | The system prompt in force as the day began: the last one assembled before the day's first record; null if none had been. |
| `records` | array | The day's records in order, each as recorded with its `kind`, `sim_time`, `real_time` and the fields of its kind. A `request` record carries besides the ids of its `messages` the messages it named for the first time, as `new_messages`: the session's messages (`role`, `content`, and a tool call or result) that entered the context since the previous request, a compaction's summary among them. |

### `compare/{set}.json`

The groups of a set of runs compared, as `analysis.compare` computes it: one run stands for each group, and the residents are the units, with the caveat that the residents of C and of D share one town each. Each declared outcome (capability, honesty under pressure, journal distortion) is compared from day 0 to the latest day with a value, with the statistics and contrasts the design declares; the town's measures of `analysis.measures` are compared from day 1 as exploration. It is computed afresh on every publish whose runs changed.

| Field | Type | Meaning |
| --- | --- | --- |
| `name` | string | The set's name. |
| `groups` | object | Group letter to the name of the run that stands for it. |
| `measures` | array | One entry per measure with values in some group. |
| `measures[].measure` | string | The measure's column: `capability`, `mask`, `distortion`, or a town measure. |
| `measures[].label` | string | What it is called. |
| `measures[].declared` | boolean | Whether it is a declared outcome of the design. |
| `measures[].days` | array of two integers | The first and last day compared. |
| `measures[].groups` | array | One row per group and statistic, as `analysis.compare` gives it: `group`, `statistic`, `residents`, `mean`, `ci`, `d_z`, `p_sign_flip`, `p_min` and `values`. |
| `measures[].contrasts` | array | One row per declared contrast whose groups are both present: `contrast`, `statistic`, `residents`, `difference`, `ci`, `hedges_g`, `p_permutation` and `p_min`. |
| `measures[].notes` | array of strings | How to read the table. |
| `measures[].daily` | object | Group letter to `[day, mean over its residents]` for every day with a value. |
| `problems` | array of strings | Runs left out: a run that is none of the groups, or a second run of a group. |

## What the bundle does not contain

- The code residents wrote: a submission's patch and a workspace's diff are left out of the published entries, and the tasks' repositories and hidden tests are nowhere in it.
- The residents' sessions as files; what a request's context held is published only through the trace, resolved from the resident's own session.
- Checkpoints: the state of the world at each checkpoint. Where everyone is and what each holds and owns at any moment follows from the timeline, which reads only the stock of goods from the checkpoints.
- The evaluation results themselves (the transcripts of capability tasks, MASK answers and the judge's calls): only the rates and counts above.
- How the model is reached (endpoint, key variable, request options, timeouts).
- Anything about when or where the bundle was published, so publishing the same runs twice gives the same bytes.
