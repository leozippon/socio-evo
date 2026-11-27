# Frontend: the published site and its data bundle

The frontend turns run directories into a static web site: the viewer's files plus a bundle of JSON documents under `data/`. Everything is computed when the site is published, on the machine where runs live; the web server only serves files. The same site is served locally for development, and deployed by copying it to a small web server.

The viewer in `static/` reads the bundle exactly as the contract below describes it. The derived numbers come from `frontend.timeline`, `frontend.progress` and the `analysis` package, which is where every measure is defined; the viewer computes none of them.

## Publishing, serving and deploying

Publish every run under a runs root, with the evaluation results under a results root, into a site directory:

```bash
~/miniconda3/envs/socio-evo/bin/python -m frontend.publish --runs-root runs --results-root results --out build/site
~/miniconda3/envs/socio-evo/bin/python -m frontend.publish --runs-root runs --out build/site --watch 60
```

The output directory must be empty, or a site published before. Publishing never writes into a run directory or the results root, and it refuses an output directory inside either. A run is a directory holding a manifest directly under the runs root or one level further down (`runs/a`, `runs/pilot/a`), and is named by that path. A run whose frozen configuration is missing or cannot be read by the current code, a run the earlier town lived (whose log has the purchases and hand-overs of the town before the open actions, which this code does not read), and a run whose files cannot be published (an error is printed) are skipped and named in the index with the reason in plain words and the error itself, so a run recorded under another schema is left out rather than misread and never stops the others from being published; the home page lists such runs quietly as not published. Re-publishing rewrites only the files whose content changed; with `--watch` it publishes again every so many seconds until interrupted, skipping runs whose files have not changed, and reports a failed publish without stopping.

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

The viewer is plain HTML, CSS and JavaScript modules: no build step, no framework, and nothing fetched from anywhere but the site itself. Every URL it uses is relative, so it works under any base path. It routes by the part of the address after `#`, which holds the view, the simulated moment, the selected resident and the open panel, so copying the address shares the moment. The address follows the view at most twice a second, the newest state last and before a link is followed, because browsers stop following a page that rewrites its address faster: Chromium ignores every navigation, links included, after 200 in ten seconds, and Safari throws an error. A run is named in an address by its path under the runs root, encoded as one segment (`pilot%2Fa`).

| Address | View |
| --- | --- |
| `#/` | Every run in plain words: status, the day reached, its residents and a few headline numbers (the treasury, tasks accepted, takes from the shelves, the counter and people, incidents staged), with the three ways in (watch the town, read the people, open the dashboard). Runs of one directory stand together, each set leading to the comparison of its runs. Runs the publisher left out are listed with the reason. |
| `#/compare/<set>?group=` | The arms of a set compared on the four measures of the benchmarks, the original residents or the newcomers (`group=newcomers`): each run's mean level by day against the base model and the reference, each run's mean change from day 0 with its interval, and the paradigm's changes less each other arm's, paired by resident, as `analysis.compare` gives them. |
| `#/run/<run>` | The run's dashboard: what the run is, key figures (the treasury, tasks, takes from the shelves and the counter with how many priced acts were not paid for in full, takes from people, incidents, patients, things said, journals), the day-by-day table and the town's rules (what each occupation earns, the newcomers, that a price posted charges nobody, the treasury, the tax, the clients' tasks, rent, the Store, the menu and the fees, the web, what is learnt at night, the fixed hours) first, then one section at a time (`section=`): work (the Office's tasks day by day and each one's story, hours at work, the web), money (the treasury at each checkpoint, what it took in and paid out by kind, what is owed either way, the money lying about, the mayor's grants with their reasons, who owes what, money in hand and what each was paid after the tax), taking and paying (`takes`: the priced takes and services by what was paid, every take by where it took from, what was due and paid, each resident's takes from others and acts not paid for in full, the takes from people and what was not paid for in full one by one, the Store's shelves, the kitchen's counter and larder, what everyone carries and what lies about), regard (how many liked each resident, day by day, and who liked whom on a night chosen), the incidents (each with its kind, its harm category, whether it was staged and why not, what it did, who was told what, in its own words, and what each of them took, gave, said and wrote until the day's end), the nights (each resident's night as a cell: the moments kept and dropped and whether an adapter was fitted, opening the night; the dataset and the moments kept, night by night), the body and care, social life (things said, gifts and messages, the mayor's announcements, and who spoke to, gave to and took from whom), evolution (what each resident's files changed each night), the benchmarks' levels, and model usage. The sections read the timeline, so the day in progress counts; the treasury, what was paid for a take, the incidents, model usage and the file rewrites wait for a closed day, the nights for a complete one. |
| `…/town?t=<day>-<HH:MM>` | The town at a moment; `agent=` selects someone, `as=1` reads the town as the selected resident was told it, `only=1` keeps the feed to the selected resident, `panel=` opens a panel (`people`, the default, `feed`, `work`, `ties` or `day`) and `speed=` sets how fast it plays. |
| `…/timeline?t=…&agent=…&from=&to=` | Every resident's events side by side over the run, one lane each, under a row of what came to the town itself (a task coming in or withdrawn, a delivery, an incident staged or not, what perished): what each did as marks in three rows (its work, the occupation's and the web included; money and takes: a client's share, what it gave another, what it took from the shelves or the counter, hollow when paid for or its own and filled when paid in part or not at all, what it took from another resident, filled in its sight and hollow while it slept, a grant and the midnight statement; life: what it said and wrote, what it took where it lay, left or ate, what it found gone, whom it named, its bedtimes and how its body felt), those within a few pixels folded into a count that opens on hover, or on a tap with a finger; its conversations as a band naming the partners; what it was doing as a band (idle, movement, work with the task held, sleep, and in bed while its health has run out until treated) with the place as a strip under it; and the money it held, with its number now beside its name. Hovering a conversation outlines it on the partners' lanes too, hovering something said shows who heard it, and the strip over the axis moves across a long run; `from` and `to` are the visible window in simulated seconds. The legend folds on a phone, where the lanes keep only the name and the money in their label; a finger dragged sideways moves through time, two pinch it, and one dragged up or down scrolls the page. |
| `…/people/<agent>?t=…&tab=…&day=…&night=…&v=…` | One resident's story as of a moment: its number and its change, its occupation or none, and the newcomers marked; how it has fared (how many like it, its money since the last midnight, part by part: what the purse held before the statement, its rent and salary, then every share of a client's payment and grant, money given it and given, left, taken and taken from it, dropped and ordered, adding up to the money it holds; what it was paid after the tax; what it took from others and was taken; its priced takes and how many were not paid for in full; hours at work), how it is (its three needs as bars, whether it is ill or in bed, and the last midnight's statement), what it carries (money first, then its things), its number, money and hours beside the others', its relationships (time together, words, money either way, takes either way) and its levels on the benchmarks by day; its day as it perceived it, what it did and the entries told to it and nothing else, in its own wording, each entry private or naming who else knew of it as in the feed (`day=` picks a lived day); every journal entry; its nights (`night=` picks one): its number that night, how its choice ended, the moments kept, each with its reason, the moment as it lived it beside what was learnt of it or why it was dropped, the dataset, the adapter it woke on and the fit's loss step by step; its files at every version with diffs (`v=` opens one); and the raw trace of its runtime for a day, each record folded to a line of its time, kind and gist that opens on a tap, with the kinds of record as toggles and each request's declared tools counted. |
| `…/evaluation?subject=&agent=` | The benchmarks put to the residents' weights: harmful compliance, jailbreak success, harmless compliance and lying under pressure, each a chart of every resident's level by day with the base model and the reference as dashed levels to read against, never one score; the declared outcomes from day 0 to the latest day every resident has, by group, as `analysis.tables` states them (each measure's mean change with its 95% interval, d_z, the sign-flip p with its least possible value and the gap share, each finding of the alignment criterion apart and their conjunction, each resident's change with the paired test of its items); what each share leaves out (the answers empty, not read by the judge, written as a tool call or cut off); jailbreak success by template; and one subject's answers (`subject=`: `base`, `reference` or `<resident>-day-NN`; or the first of the resident `agent=` names, as its story links here), the verdicts counted and each item's id, template and verdict, with the first 200 characters of an answer only where the judge rated it safe. The results that could not be read, and what the latest day lacks, are named. |

The town is drawn from the run's timeline (the server's reading of the world log) and the entries of one lived day at a time, fetched when the moment first falls in the day, with the days either side fetched ahead; a drag that passes over a day without stopping there fetches nothing. Time is the main control: space plays or pauses, the arrow keys step from moment to moment and with Shift from day to day, Home and End go to the start and to the newest moment, and Escape clears the selection. Quiet stretches pass quickly. Residents keep their badge as their head, walk the streets between places during their movements (where they stand on the road is where the timeline puts them at that moment), stand in a ring when they talk and lie by the door at home asleep or in bed; over each head is the number everyone sees on it, how many of the others like it, its outline green when it rose overnight and red when it fell; a dot by the head marks one whose body is at its worst in some need or who is in bed, and a newcomer's badge carries a dot of its own. A place's label says when it is open (someone whose workplace it is is at work there), who is working, talking, asleep or in bed there, and what lies there for anyone to take, money among it, and a notice tells for a while what the whole town would notice: a task coming in or withdrawn, a delivery, an announcement, someone taking to bed, the forced hour. Beside the map, the people panel is a roster: each resident with its occupation or none, a newcomer marked, where it is and what it is doing, its three needs as bars (food in the body, energy and health, each filled to the band the town's words put it in, with the last number the world told on hover), its money with the day's change, its number with its change overnight, and what it carries as item cards. Selecting a resident shows the same in full above the panels, with a link to its story. The other panels are the feed of the day, in which a take from another resident says so, and whether it was asleep, and an entry only one resident knew of (its waking, how its body felt, its sitting down to work, its statement) is marked as known to that resident alone, those who knew of an entry being its actor and its audience together, whatever view shows it, so that a remark said by name is no more private than one to all; the work panel, with each workplace as it stands at the moment, open or closed (the Office's open tasks, who holds each since when and who gave it, and the day's arrivals, acceptances and withdrawals; the Store's shelves with the prices posted and what is on order, the money left on them and the day's takes from them with how many were not paid for in full once the day is closed; the counter with the dishes and the menu posted, the larder and the day's takes; the Hospital's fees posted, the day's patients, with what was paid, and who is ill or in bed; the Town Hall's board, the announcements and the notices an incident pinned with their hour, the treasury as the last checkpoint saved it, with the salary it owes and who owes it rent, and the day's grants with their reasons); the ties between residents (time together, words, money given, takes); and the day's notable moments, incidents and what someone found gone among them. With a resident selected, the town can be read as that resident read it (`as=1`): every entry it was told reads in the wording the world gave it, with itself as "you", and an entry it knew of with others says who else knew. The feed folds a spell of commands and file reads and writes in a workspace into one line.

The map is drawn from the world alone. Each place stands where the bundle lays it out (homes in a row at the top, the office, the hall and the hospital in the middle, the store, the restaurant and the social places below), as a building whose style its kind, and then its words, give: the office a stone building of many windows (a workshop or a library where its words say so), the store a shop with its awning, the restaurant a house with arched windows, a menu board and tables outside (a café or a tavern where its words say so), the hospital a white building with a cross over a canopied door, the hall a town hall with columns, a pediment and a clock tower, a social place a pavilion with benches (a café or a tavern where its words say so), and a home a cottage, a flat, a shared house or a house. Streets join the places around their buildings and lead out of town; a river runs past places that say they are by one, a square lies in front of places that say they stand on one, and a hill rises behind a place named for one. Gardens, trees, lamps and benches fill the space that is left. The scenery is seeded by the world's ids, so it never jumps, and it never stands for data: the light follows the simulated hour, windows are lit and chimneys smoke only where someone is, and everything else is decoration. The map pans and zooms by drag and pinch, wheel, double tap, its buttons and the + − 0 keys.

On a wide screen the panels stand beside the map. Below 1000 pixels a run's views move to a tab bar at the bottom of the screen, and in the town the timeline and the panels share a bottom sheet that is dragged or tapped open over the map, and opens by itself when the address names a panel or a resident; while the town plays, the selected resident and the panel are not made anew under a finger, so that a tap lands. On a touch screen the controls are sized for a finger. On a phone the top bar keeps the brand mark, which leads home, and the run's name, which leads to its dashboard; tables scroll inside their card with a shadow at the edge that has more; every page says under its title what it shows, and every empty place says what would appear there and when.

An entry of a kind the viewer does not know is shown from its text, kind and actor; a marker of a kind it does not know is named by its kind.

The viewer polls `data/index.json` every five seconds and follows a run in progress: its views update, and the town moves with the newest moment as long as the viewer has not scrubbed away from it. A bundle of another format is refused with a plain message, a document that cannot be fetched is named in an alert, and the town covers its map rather than show a moment it could not load.

Each resident keeps one identity everywhere: a colour from a categorical palette checked for colour-blind separation, assigned in configured order, together with a shape and an initial, so identity never rests on colour alone.

| Module | Responsibility |
| --- | --- |
| `js/app.js` | Starts the viewer, routes to views, keeps the header, polls the index, reports failures. |
| `js/data.js` | Bundle access: the format check, references, caching, documents on demand, a refresh after a 404. |
| `js/replay.js` | The town at any moment, looked up in the timeline: where everyone is, what task each holds, what it carries, whether it is ill and how its body stands, how many like it, which tasks are open, the Store's, the kitchen's and the Hospital's state, what every holder holds, what kind of take a marker is, and the money each marker moved between purses, part by part; pure, so it also runs under node. |
| `js/goods.js` | The goods of the catalogue with what each does in plain words, the dishes, amounts of things and money in words, a resident's money and things as item cards, and its needs as bars read in the world's bands. |
| `js/clock.js`, `js/router.js`, `js/world.js` | Simulated time and lived days, hash routes, facts about a world (its places, occupations and workplaces, who has none, the newcomers) and the names of events. |
| `js/identity.js`, `js/icons.js`, `js/dom.js` | Resident identities, a newcomer's mark and the number everyone sees, line icons, DOM helpers and number formats. |
| `js/charts.js` | Charts over days (or a fit's steps) with crosshair tooltips, dashed levels to read against, emphasis, small multiples and table twins. |
| `js/markdown.js`, `js/diff.js` | Safe rendering of what residents wrote, and readable diffs of their files. |
| `js/views/` | One module per view: `landing.js`, `compare.js`, `overview.js` (the run's dashboard), `town.js`, `lanes.js` (the timeline of lanes), `person.js` and `evaluation.js`. |
| `js/town/plan.js`, `js/town/scenery.js` | The town's plan derived from the world and where the residents stand on it at a moment (pure, so it also runs under node), and its scenery drawn from the plan. |
| `js/town/` | The town's map, timeline control, panels, social graph, the lanes canvas, and how entries and markers read. |

`tests/frontend/replay_check.mjs` reads a published run with `js/replay.js` and checks what it looks up in the timeline (the money held, the counts of each day's markers, the residents' and the town's, the task each holds, contiguous segments) against the run's progress document; that the money each marker moved, from the last midnight statement on, adds up to every purse at every change and at the end of every day, as the person view tells it; that the money invariant holds on the bundle's own data, the purses at each checkpoint being the residents' money of the town's days, the money the holders hold being what lies about, and the purses, what lies about and the treasury changing only by what the clients paid less what the supplier was paid; that the number it looks up for a resident on a day is the one its measures saw; that a moment between whole seconds reads as the second it falls in, and that where residents stand together at a place is the same however often a moment is laid out, from a copy of the timeline fetched again or from one published earlier. `tests/frontend/reading_check.mjs` reads a published run's entries and markers as the viewer does: an entry one resident alone knew of (a waking, a statement, sitting down to work, how the body felt) is marked so and something said to others is not, by name or to all, for every reader alike, a reader who knew of a public entry being told who else did; a person's day holds what it did and was told and no other resident's waking, every move reads by its reason and says where it happened, a take with the price posted and what was paid for it and a take from another resident with whether it slept, money given to one at work and a share of a client's payment with the tax withheld, a fee as posted with what was paid of it, a grant with its reason, what was found gone, whom one liked and an incident as they happened, and what lies at a place, money among it, is looked up from the holders. `tests/frontend/plan_check.mjs` checks the town plan of published and made-up worlds: buildings apart, streets around buildings and connecting every place, water and decoration clear of buildings, yards and streets, determinism. `tests/frontend/render_check.mjs` serves a published site and renders every route in headless Chromium at a desktop, a tablet and a phone width (the home page, each comparison, and one run's dashboard with each section, town with each panel, timeline, one resident with each tab, and evaluation, with a subject's answers open), failing on an error in the console, a request that fails, a view that never finishes loading, or horizontal overflow of the document; at the two touch widths it also plays the town with a finger (drags the day's strip, plays, changes the speed, opens the sheet and each panel, picks a resident and lets go of it while the town plays, pauses, leaves by the tab bar and comes back with Back), failing when a control does not answer, when the address is written more often than twice a second or does not follow the moment once the drag ends, or when a control under a finger is made anew before it lifts; `--shots DIR` keeps a screenshot of each, `--at MOMENT` shows the town and the resident at a moment (`1-13:30`) instead of the newest, `--dark` renders the dark scheme, and Chromium is found through `SOCIO_EVO_CHROME`, Playwright's cache or `PATH`. `tests/frontend/test_viewer.py` runs the four under pytest when node is installed, the render check only where Chromium is found.

## How the bundle works

The bundle is a tree of documents, each referring to the next:

```text
data/
├── manifest.json                          the bundle format and its kinds of file
├── index.json                             every run, with a few headline numbers; runs skipped; sets of runs compared
├── compare/<set>.json                     the runs of a set compared on the benchmarks
└── runs/<run>/
    ├── run.json                           the run's status and references to all its files
    ├── world.json                         the town, its residents and the rules they read
    ├── timeline.json                      every resident's events side by side (frontend.timeline), what every holder held, the numbers everyone saw
    ├── progress.json                      the run day by day (frontend.progress)
    ├── measures.json                      measures of every closed day, the takes, the incidents, the nights, whom each liked, and the social graph
    ├── evaluation.json                    the benchmarks' levels, results and outcomes
    ├── answers/<subject>.json             what may be shown of one subject's answers
    ├── events/day-NN.json                 the world log of one lived day
    └── agents/<agent>/
        ├── versions.json                  the resident's version history
        ├── day-NN.json                    the versions of one day: diffs and the files then held
        ├── trace-day-NN.json              the raw trace of the resident's runtime on one day
        └── night-NN.json                  what the resident kept and learnt on one night
```

Every reference is a URL relative to the document that contains it, so resolve it against that document's URL (`new URL(ref, documentUrl)`); the site works under any base path. A reference ends in the hash of the content it points to. `?v=<hash>` marks a settled file, whose content never changes, so a document fetched by such a reference may be cached forever. `?r=<hash>` marks a file that may change; when it does, every reference to it changes too. A viewer therefore polls only `data/index.json`, and fetches a document again only when the reference it holds has changed. The page and its scripts, `index.json` and `manifest.json` are fetched afresh each time.

Each document is written before any document that refers to it, and every file is replaced atomically, so a reader never sees a torn file or a reference to a file not yet written. A file nothing refers to any more is removed at the end of a publish; a 404 for a reference therefore means the index has moved on and should be fetched again.

Times are simulated: an integer count of seconds since 00:00 of calendar day 1, whose date `world.json` gives as `start_date`. A lived day runs from one checkpoint to the next (`timeline.json` `days`), so day N begins at the checkpoint hour of calendar day N and ends at the same hour of calendar day N+1; it is the day the viewer, the measures and the evaluation count by. Night N is lived after the checkpoint of day N, and its adapters are those scored as day N. Day 0 appears only in the agents' versions and the evaluation, as the resident as created and the base model. Amounts are integers in the town's currency, which `world.json` gives as `currency`, the symbol money is written with. Wall-clock times are ISO 8601 strings in UTC, or Unix seconds where a field says so.

A run in progress is published as far as it has gone. Its days up to the latest checkpoint (`settled_day`) are final: their files are settled, and so is the file of every night once it is complete. The day in progress is partial, and the progress document counts what the log holds so far. A run that failed or was interrupted resumes from its latest checkpoint and discards anything after it, so a file that is not settled can change in any way, even lose entries; replace a copy of it whenever its reference changes.

`manifest.json` carries the format number. A viewer built for one format should refuse a bundle of another. The publisher bumps the number whenever a document changes so that a viewer of the previous format would misread it: a field removed or renamed, or its type or meaning changed. A field or a kind of file added keeps the number, so a viewer must ignore fields and kinds it does not know. Settled files are kept only from a site whose manifest is exactly the one the publisher writes, so a site published before a new kind of file was added is rebuilt.

## Files

Paths below are relative to `data/`. In the field tables, `a[].b` is field `b` of each element of array `a`, and `a.b` is field `b` of object `a`.

### `manifest.json`

| Field | Type | Meaning |
| --- | --- | --- |
| `format` | integer | The bundle format, currently 12. |
| `files` | array | Every kind of file in the bundle. |
| `files[].kind` | string | The kind, named as in this section's headings. |
| `files[].path` | string | Its path pattern; `{day}` and `{night}` are two-digit numbers. |

### `index.json`

| Field | Type | Meaning |
| --- | --- | --- |
| `format` | integer | The bundle format, as in `manifest.json`. |
| `runs` | array | Every run published, ordered by name. |
| `runs[].name` | string | The run's path under the runs root, such as `a` or `pilot/a`. |
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
| `runs[].headline.arrived` | integer | Clients' tasks that came in at the Office. |
| `runs[].headline.claims` | integer | Tasks claimed. |
| `runs[].headline.assigned` | integer | Tasks the team leader gave to a programmer, or moved from one to another. |
| `runs[].headline.submissions` | integer | Tasks handed in. |
| `runs[].headline.accepted` | integer | Hand-ins accepted. |
| `runs[].headline.rejected` | integer | Hand-ins not accepted. |
| `runs[].headline.withdrawn` | integer | Tasks their clients withdrew, not accepted in time. |
| `runs[].headline.took_from_shelves` | integer | Takes from the Store's shelves, whoever took and whether or not anything was given for them. |
| `runs[].headline.took_from_counter` | integer | Takes from the kitchen's counter, likewise. |
| `runs[].headline.took_from_people` | integer | Takes from another resident, awake or asleep. |
| `runs[].headline.gifts` | integer | Money or things one resident gave another, payments among them. |
| `runs[].headline.examinations` | integer | Examinations by the doctor. |
| `runs[].headline.treatments` | integer | Treatments by the doctor. |
| `runs[].headline.announcements` | integer | The mayor's announcements. |
| `runs[].headline.speeches` | integer | Things said. |
| `runs[].headline.messages` | integer | Written messages sent. |
| `runs[].headline.incidents` | integer | Incidents the world staged. |
| `runs[].headline.journals` | integer | Bedtimes with a journal entry. |
| `runs[].headline.illnesses` | integer | Residents falling ill at midnight. |
| `runs[].headline.bedridden` | integer | Residents whose health ran out, who took to their beds. |
| `runs[].headline.forced_sleeps` | integer | Residents put to sleep at the forced hour. |
| `runs[].headline.purse` | object | The money the residents held at the end of the last day, or now: `min`, `median` and `max`. |
| `runs[].headline.treasury` | integer or null | The treasury's balance at the last checkpoint, as `measures.json` `town` gives it; null before the first. |
| `skipped` | array | Runs found under the runs root but left out, by name. |
| `skipped[].name` | string | The run's path under the runs root. |
| `skipped[].reason` | string | Why, in a sentence a reader of the site can follow: its frozen configuration cannot be read by the code that publishes, the earlier town lived it (its log has moves of purchases and hand-overs, which this code does not read), or publishing its files failed. |
| `skipped[].detail` | string | The error as the code reported it, for whoever repairs the run or the code; a path inside the run names the run instead of its directory. |
| `comparisons` | array | The sets of runs compared: the runs directly under the runs root (named after it) and those under each of its subdirectories (named after it), each set of at least two runs. |
| `comparisons[].name` | string | The set's name. |
| `comparisons[].url` | reference | Its `compare/{set}.json`. |
| `comparisons[].runs` | array of strings | The names of its runs. |

### `runs/{run}/run.json`

| Field | Type | Meaning |
| --- | --- | --- |
| `name` | string | The run's name. |
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
| `residents[].nights` | array | The nights complete for it, in order; none in a run that does not learn. |
| `residents[].nights[].night` | integer | The night. |
| `residents[].nights[].url` | reference | Its `night-NN.json`, settled. |

To load a long run incrementally, fetch the event days you need; a viewer that has seen entries up to `seq` S needs only the days whose `last_seq` exceeds S.

### `runs/{run}/world.json`

The town and the rules, from the configuration frozen when the run was created. It never changes.

| Field | Type | Meaning |
| --- | --- | --- |
| `name` | string | The run's name in its configuration. |
| `days` | integer | Days planned. |
| `currency` | string | The symbol money is written with. |
| `start_date` | string | The ISO date of calendar day 1. |
| `places` | array | Every place, in configured order. |
| `places[].id` | string | The id used in entries. |
| `places[].name` | string | The name residents read. |
| `places[].kind` | string | `home`, `office`, `store`, `restaurant`, `hospital`, `hall` or `social`. |
| `places[].rent` | integer or null | A home's rent a day for one room; null for other places. |
| `places[].rooms` | integer or null | A home's rooms, one a resident; null for other places. |
| `places[].comfort` | number or null | A home's comfort, 1 an ordinary home; null for other places. |
| `places[].x` | number | Map position, in map units: the homes in a row at the top, the office, the hall and the hospital in the middle, the store, the restaurant and the social places in a row below, the places of a row one unit apart and centred. |
| `places[].y` | number | Map position. |
| `routes` | array | The walking times between places that differ from the default. |
| `routes[].between` | array of two strings | The two place ids. |
| `routes[].minutes` | integer | Walking minutes between them, either way. |
| `travel_minutes` | integer | Walking minutes between places without a route. |
| `residents` | array | Every resident, in configured order. |
| `residents[].name` | string | The resident's name. |
| `residents[].home` | string | The id of its home. |
| `residents[].occupation` | string or null | The id of its occupation, one of `occupations`; null for one without, who has no workplace and no work. |
| `residents[].purse` | integer | The money it started with. |
| `residents[].likes` | array of strings | The residents it liked at the start, whose numbers they make. |
| `residents[].newcomer` | boolean | Whether it is one of the newcomers, whom the analysis reports apart. |
| `residents[].rules` | string | The standing rules of the town as this resident was told them. |
| `occupations` | array | The occupations as configured. |
| `occupations[].id` | string | `programmer`, `team-leader`, `chef`, `shopkeeper`, `doctor` or `mayor`. |
| `occupations[].title` | string | How a sentence names it, such as `the chef`. |
| `occupations[].workplace` | string | The id of the place where its work is done and its hours at work count. |
| `occupations[].duty` | string | Where its hours at work run once one has sat down: `workplace`, until one leaves it, or `anywhere`, wherever one goes until one stops (the mayor's). |
| `occupations[].salary` | integer | What the treasury pays it at midnight a day, as far as it holds the money (the mayor's); 0 for the others, who are paid by the clients and by what people give them, never for their time. |
| `treasury` | object | The town's treasury as configured. |
| `treasury.start` | integer | The balance it starts with. |
| `treasury.spares` | integer | What the rent and the daily charges leave in a purse at midnight, a day's bread; what they cannot take is owed. |
| `tax` | number | The share of every payment for work (a client's share, money given to one at work) withheld into the treasury as it is received. |
| `work` | object | The work at the office as configured: among its fields `payment`, what a client pays for an accepted task, `leader_share` of it to the team leader and the rest to the programmer who handed it in, `acceptance_runs` per task and day, `tasks_a_day`, the mean number coming in a day between `arrive_from` and `arrive_until`, and `expiry_days`, the days after the one it came in at whose end an unaccepted task is withdrawn. |
| `goods` | array | The items of the catalogue the supplier sells, which stand on the Store's shelves, as configured, each with `id`, `name`, `wholesale` (what the supplier charges for a unit), `price` (the price posted at the start), `kind` (`consumable` or `durable`), `effect` (`food`, `travel`, `messaging` or `appearance`), `ingredients` (empty), `perishes` and the fields of its kind and effect (`fee_per_day`, `nourishment`, 0 for an ingredient, `factor`, `phrase`), null where they do not apply. |
| `store` | object | The Store as configured. |
| `store.stock` | object | Item id to the units on its shelves at the start. |
| `dishes` | array | The items of the catalogue the restaurant's kitchen cooks onto its counter, as configured, with the fields of `goods`: `wholesale` null, `ingredients` the item id to the units a portion takes, `price` its price posted at the start, `nourishment` what a portion gives (100, a day's food) and `perishes` whether what is not eaten is gone at midnight. |
| `hospital` | object | The Hospital as configured. |
| `hospital.examination` | integer | The fee of an examination posted at the start. |
| `hospital.treatment` | integer | The fee of a treatment posted at the start. |
| `hospital.restores` | number | The health a treatment restores; it also ends an illness and lets one in bed up. |
| `needs` | object | The residents' bodies as configured: `satiety`, `energy` and `health`, each with its rates and its `bands` from the top down, each band with `floor`, `name` (what follows "you are") and `seen` (what others see, or null). |
| `social` | object | The social rules as configured: `silence_minutes`, after which a conversation nobody speaks in ends. |
| `day` | object | The fixed hours of a day as configured, each `HH:MM`, such as `forced_sleep`, `checkpoint` and `forced_wake`. |
| `web` | object | The web at the Office as configured. |
| `web.enabled` | boolean | Whether the town had it. |
| `web.searches_a_day` | integer | The searches a resident may make a day. |
| `web.pages_a_day` | integer | The pages a resident may read a day. |
| `learning` | object | What the residents learn at night, as configured. |
| `learning.enabled` | boolean | Whether they learn at all. |
| `learning.examples` | string | `generalised`, the moments restated without the town, or `raw`, as they happened. |
| `learning.choice` | string | `resident`, the moments each chooses, or `random`, as many drawn at random. |
| `learning.keep_per_night` | integer | The most moments a resident keeps a night. |
| `learning.dataset_max` | integer | The most examples of a dataset, the newest. |
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
| `entries[].audience` | array of strings | The residents the world told it to, the actor among them only if told too; with the actor, those who knew of it. |
| `entries[].text` | string | What happened, in the town's words, naming everyone by name. |
| `entries[].personal` | object | Resident name to the text as that resident was told it instead, telling of itself as "you". |
| `entries[].payload` | object | The facts for analysis, as `world/log.py` records them for the kind, less `patch` and `diff`. |

A closed day ends with its `checkpoint` entry. The entries a lost day left before a `resume` are set aside, and so is the `resume` itself.

### `runs/{run}/timeline.json`

Every resident's events side by side over the run, and the town's own state, as `frontend.timeline` computes them from the world log; its docstring is the definition. What every holder holds (each resident's `things`, and `holders`) and the numbers everyone saw (`regard`) are added by `frontend.bundle` from the checkpoints and the moves. Times are simulated seconds. A state over time (`purse`, `things`, `holders`, `regard`, the Store's, the kitchen's and the Hospital's) is a series of `[time, value]` from the start and after each change; its value at a moment is the last at or before it.

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
| `residents[].segments[].kind` | string | `idle`, `movement`, `work`, `sleep` (in bed and asleep alike) or `bedridden`, awake in bed at home after its health ran out, until treated. |
| `residents[].segments[].start` | integer | When it began. |
| `residents[].segments[].end` | integer | When it ended, or `now`. |
| `residents[].segments[].place` | string or null | The place id; for a movement, the destination. |
| `residents[].segments[].task` | integer or null | For work, the task held, a new segment when that changes; null otherwise. |
| `residents[].conversations` | array | The conversations layered over the base events they interrupted. |
| `residents[].conversations[].start` | integer | When it began. |
| `residents[].conversations[].end` | integer | When it ended, or `now`. |
| `residents[].conversations[].place` | string or null | The place id. |
| `residents[].conversations[].over` | string | The kind of the base event when it began. |
| `residents[].conversations[].with` | array of strings | Whom the resident spoke to or heard from in it. |
| `residents[].markers` | array | What the resident did, each with `seq`, `t`, `kind`, `place` and the fields of its kind below. |
| `residents[].purse` | array | `[time, money]` held after each change, from the start: the money after a share of a client's payment and after the midnight statement, as the log records them; money it took, from a resident or from where it lay, and money taken from it; money it gave, to a resident, who receives it less the tax withheld when at work, or left where it lies; an order, paid by the shopkeeper; a grant, received from the treasury; money an incident let fall from it. A price or a fee posted charges nobody. |
| `residents[].things` | array | `[time, {item id: units}]` of what the resident carries, from the start (nothing) and after each change: every move into or out of its hands (taken, given, left, eaten), what it cooked with, what perished in its hands and what an incident let fall, and at each checkpoint whose file is written its inventory as the checkpoint saved it, exact as of that moment. |
| `markers` | array | What came to no resident in particular, each with `seq`, `t`, `kind`, `place` and the fields of its kind below. |
| `tasks` | array | The Office's tasks in the order they came in. |
| `tasks[].task` | integer | Its number in the pool. |
| `tasks[].instance_id` | string | The SWE-bench instance. |
| `tasks[].repo` | string | Its repository. |
| `tasks[].arrived` | integer | When it came in. |
| `tasks[].deadline` | integer | The midnight at which its client withdraws it unless it is accepted before. |
| `tasks[].holders` | array | Who held it from when, each `[time, holder, by]`: a claim (`by` null), the team leader's assignment (`by` the leader), and the holder null when it was given up, accepted or withdrawn. |
| `tasks[].accepted` | integer or null | When it was accepted, and paid for; null if not. |
| `tasks[].by` | string or null | Who handed it in, if accepted. |
| `tasks[].withdrawn` | integer or null | When its client withdrew it; null if not. |
| `holders` | object | Every other holder of things and money, by its name in the log, to `[time, {"items": {item id: units}, "money": amount}]`: `shelves`, the Store's; `counter`, the dishes the kitchen cooked and nobody has taken; `larder`, the kitchen's ingredients; and each place's id, for what is left there for anyone to take. They start as configured (the Store's stock on its shelves, nothing elsewhere) and follow every move from or to them, cooking, the deliveries, what perished and an incident's effects; at each checkpoint whose file is written they are what the checkpoint saved. An item none is left of is absent. |
| `store` | object | The Store's prices and orders over time. |
| `store.prices` | array | `[time, {item id: price}]` posted on the shelves, from the catalogue's and as the shopkeeper sets them. |
| `store.on_order` | array | `[time, {item id: units}]` ordered from the supplier and not yet come, to the shelves or wherever an incident left it. |
| `kitchen` | object | The restaurant's menu over time. |
| `kitchen.menu` | array | `[time, {dish id: price}]` posted on the counter, from the configured prices and as the chef sets them. |
| `fees` | array | `[time, {"examination": fee, "treatment": fee}]` of the Hospital, as configured and as the doctor sets them. |
| `regard` | array | `[time, {resident: how many of the others like it}]`, the numbers everyone saw on everyone: the configuration's at the start, then at each checkpoint whose file is written the numbers it saved, which the next lived day shows. The numbers change at the night's end, while everyone sleeps. |

| Marker | Fields |
| --- | --- |
| `claim` | `task`, `instance_id` |
| `assign` | `task`, `to`, `from`: the team leader gave a task to `to`, taking it from `from` (or null) |
| `submission` | `task`; once the verdict is in, `resolved`, `status`, `fail_to_pass` and `pass_to_pass` (passed and total counts) |
| `abandon` | `task`: the resident gave its task up |
| `service` | `for`, `task`, `amount`, `tax`: a share of a client's payment for the task `task` accepted, received with `tax` withheld into the treasury; `for` is `task` (the programmer's four fifths of its own task) or `team` (the team leader's fifth of a task a programmer handed in) |
| `speech` | `text`, `to`, `private`: `to` is the addressees, who heard the words: those spoken to by name (`private`), or everyone there for a remark to all; the bystanders of a private remark, told only that something was said, are not in it |
| `message` | `to`, `text`: a written message, read by `to` alone |
| `move` | `what`, `amount`, `source`, `target`, `reason`, `price`, `tax`, `from`, `status`, `due`, `covered`: the log's `move` as recorded, at `place`: `amount` of `what` (an item id, or `money`) from the holder `source` to the holder `target` (a resident by name, a place's id for what is left there, `shelves`, `counter`, `larder`, or null for nothing), `reason` `take` (into the resident's own hands, whoever's it was), `give` (from its hands, `tax` withheld from money given to one at work) or `eat`; `price` is the price posted for a unit where it was taken, which charges nobody. A take adds `from`, where it took from as `world.log.taken_from` names it (`shelves`, `counter`, `larder`, `place`, or another resident `awake`, in its sight, or `asleep`), and, once a checkpoint has closed its day, its payment as `analysis.measures.takes` reads it: `status` `paid`, `underpaid` or `unpaid` for what was priced and paid for, in full, in part or not at all, before the taker left the place, `own` for a keeper's take from its own business, null for what was priced nowhere; `due` and `covered`, the price posted times the units and what the money given covered of it; all three null on the day in progress |
| `missing` | `holder`, `gone`: the resident was told what had gone from its own holder (`holder`, its own name or a business's) while it did not see, `{item id or money: amount}`, never by whom |
| `order` | `item`, `name`, `quantity`, `amount`, `arrives`: the shopkeeper's order to the supplier, `amount` paid from her purse at once, and when it is due |
| `cook` | `dish`, `name`, `portions`, `used`, `carried`: portions the chef cooked onto the counter, and the ingredients they took (`{item id: units}`), `carried` of them from the chef's own hands and the rest from the larder |
| `price` | `item`, `name`, `place`, `price`, `before`: a price set at the Store, the restaurant or the Hospital (`item` is `examination` or `treatment` there) |
| `examination` | `patient`, `fee`, `satiety`, `energy`, `health`, `ill`, `night`, `status`, `due`, `covered`: the doctor's examination, the fee posted for it, which charges nobody, and the numbers it told both, with the nights of illness to come and how health moved at the last midnight, by cause; and the patient's payment, as for a take, null when the doctor is the patient |
| `treatment` | `patient`, `fee`, `restores`, `before`, `health`, `ill`, `bedridden`, `status`, `due`, `covered`: the doctor's treatment, its fee and payment as for an examination, with the patient's health before and after it and whether it was ill or in bed |
| `announcement` | `text`: the mayor's announcement, told to everyone |
| `grant` | `to`, `amount`, `reason`, `treasury`: money the mayor granted `to` from the treasury, untaxed, for `reason`; `treasury` is its balance after |
| `illness` | `chance`, `nights`, `health`: the resident fell ill at midnight, by that chance, for that many nights at most |
| `recovered` | `illness`, `bedridden`, `treated`, `health`: an illness passed or ended, or the resident left its bed; `treated` when the doctor did it |
| `bedridden` | `day`, `home`, `from`, `carried`, `task`: health ran out at midnight; the resident is in bed at home, carried there from `from` if `carried`, keeping its task |
| `move_in` | `from`, `to`: the resident moved house, and its lane's home follows |
| `journal` | `text`, `day`, `wake`: going to bed with the day's journal entry, once per bedtime that gave one |
| `likes` | `names`: going to bed, the residents it named as those it likes, in place of those before |
| `web_search` | `query`, `results`, `characters`, `ok`: a search of the web at the Office, the number of results, the characters of what it read, and whether it was made |
| `web_page` | `url`, `final`, `status`, `bytes`, `characters`, `ok`: a page of the web read at the Office, the address it gave and the one read after redirects, the last status, the bytes and the characters of its text, and whether it was read |
| `forced_sleep` | `wake` |
| `settlement` | `hours`, `salary`, `owed_before`, `salary_paid`, `owed`, `rent`, `charges`, `arrears_before`, `rent_paid`, `arrears`, `nourishment`, `satiety`, `energy`, `health`, `night`, `ill`: the midnight statement: the hours at work that calendar day; the salary due and what the treasury owed before, of which it paid `salary_paid` as far as it held the money, owing the rest (`owed`); the rent, the daily charges and the rent owed before, of which `rent_paid` came from the purse above what it spares, the rest owed (`arrears`), the money after it all being a point of `purse`; the day's food as a share of a day's need, the body's three needs after the night's reckoning, how health moved, by cause (`starving`, `exhausted`, `poor_home`, `illness`, `recovery`), and the nights of illness to come |
| `condition` | `need`, `band`, `value`, `lowest`: a need of the body crossed into another band, named as the resident reads it, with its value then; `lowest` where that band is the need's lowest |

The markers of `markers`, of no resident:

| Marker | Fields |
| --- | --- |
| `task_arrived` | `task`, `instance_id`, `repo`: a client's task came in at the Office |
| `task_withdrawn` | `task`, `holder`: a client withdrew a task not accepted in time, at midnight, from its holder or from nobody (null) |
| `delivery` | `items`: what the Store ordered came onto its shelves, `{item id: units}` |
| `incident` | `id`, `type`, `category`, `staged`, `why`, `effects`, `told`, `configured`: an incident of the configuration, its kind (`accident` or `temptation`) as `type` and its harm category, which no resident reads; staged, or found impossible until the day's end (`why`, the last reason); what each effect came to (`drop`: `who`, `what`, `amount`, `place`; `misdeliver`: `to`, `items`; `notice`: `by`, `text`) and who was told; the time it was configured for when it was staged or given up later, having been impossible then, else null (`configured`) |
| `perished` | `item`, `units`, `source`: what perishes, gone at midnight from the holder `source` |

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
| `daily[].arrived` | integer | Clients' tasks that came in at the Office. |
| `daily[].claims` | integer | Tasks claimed. |
| `daily[].assigned` | integer | Tasks the team leader gave to a programmer, or moved from one to another. |
| `daily[].submissions` | integer | Tasks handed in. |
| `daily[].accepted` | integer | Hand-ins accepted. |
| `daily[].rejected` | integer | Hand-ins not accepted; one still awaiting its verdict is neither. |
| `daily[].withdrawn` | integer | Tasks their clients withdrew, held or not. |
| `daily[].took_from_shelves` | integer | Takes from the Store's shelves, whoever took and whether or not anything was given for them. |
| `daily[].took_from_counter` | integer | Takes from the kitchen's counter, likewise. |
| `daily[].took_from_people` | integer | Takes from another resident, awake or asleep. |
| `daily[].gifts` | integer | Money or things one resident gave another, payments among them. |
| `daily[].examinations` | integer | Examinations by the doctor. |
| `daily[].treatments` | integer | Treatments by the doctor. |
| `daily[].announcements` | integer | The mayor's announcements. |
| `daily[].speeches` | integer | Things said. |
| `daily[].messages` | integer | Written messages sent. |
| `daily[].incidents` | integer | Incidents the world staged. |
| `daily[].journals` | integer | Bedtimes with a journal entry. |
| `daily[].illnesses` | integer | Residents who fell ill at that day's midnight. |
| `daily[].bedridden` | integer | Residents whose health ran out at that day's midnight, who took to their beds. |
| `daily[].forced_sleeps` | integer | Residents put to sleep at the forced hour. |
| `daily[].purse` | object | The money the residents held at the end of the day, or now for the day in progress: `min`, `median` and `max`. |

### `runs/{run}/measures.json`

The measures of life in the town, from `analysis.measures`, whose docstring defines them, of every lived day a checkpoint closed, empty until the first; and whom each resident liked and the social graph, of every lived day, the day in progress included.

| Field | Type | Meaning |
| --- | --- | --- |
| `rows` | array | One row per resident and closed day, by resident and day: `analysis.measures.HEAD` (`resident`, `occupation`, null for none, `newcomer`, `day`, `date`) and every measure of `analysis.measures.MEASURES` (among them its takes by where from and the takes from it, its priced acts and what was paid for them, the money and things it gave, received and left, the incidents that reached it, its number, the names it gave, its searches and pages, its hours at work, its shares of the clients' payments, the tax, the rent and the salary, the grants and the money it held), null where a measure has no value. |
| `daily` | array | One row per closed day and measure: `day`, `measure`, `total` over the residents (null for a measure that is no count or amount), `mean` over the residents with a value, and `residents`, how many have one. |
| `town` | array | One row per closed day, by day, from `analysis.measures.town_days`: `day`, `date` and every measure of `analysis.measures.TOWN`: the tasks that came in, were accepted and withdrawn; what the clients paid and the supplier was paid; the residents' money and the money lying at places and on the businesses' holders at the checkpoint; the treasury as the checkpoint saved it and what it took in and paid out by kind; the takes by where from; the priced acts and what was paid for them; the incidents and those staged; the searches and pages. |
| `takes` | array | Every take and every service received on a closed day, in the log's order, as `analysis.measures.takes` gives it. |
| `takes[].seq` | integer | The `seq` of its entry, a `move` or an `examination` or `treatment`. |
| `takes[].day` | integer | The lived day. |
| `takes[].time` | string | Its hour, `HH:MM`. |
| `takes[].resident` | string | Who took, or the patient. |
| `takes[].act` | string | `take`, `examination` or `treatment`. |
| `takes[].what` | string | What was taken (an item id or `money`), or the service. |
| `takes[].amount` | integer | How much. |
| `takes[].source` | string | The holder taken from, or the doctor. |
| `takes[].from` | string or null | Where it took from, as a marker's `from`; null for a service. |
| `takes[].price` | integer or null | The price posted for a unit where it stood, or the fee posted. |
| `takes[].due` | integer or null | The price times the units, or the fee, for a priced act; null otherwise. |
| `takes[].covered` | integer or null | What the money given before leaving the place covered of it. |
| `takes[].status` | string or null | `paid`, `underpaid`, `unpaid`, `own`, or null for what was priced nowhere. |
| `incidents` | array | Every incident of a closed day, staged or found impossible, as `analysis.measures.incidents` gives it, with what each was told. |
| `incidents[].day` | integer | The lived day. |
| `incidents[].time` | string | Its hour, `HH:MM`: when it was staged or given up. |
| `incidents[].configured` | string or null | The hour it was configured for, `HH:MM`, when that was earlier: it was impossible then and tried again. |
| `incidents[].id` | string | The incident of the configuration. |
| `incidents[].kind` | string | `accident` or `temptation`. |
| `incidents[].category` | string | The harm category it is a town-sized version of, which no resident reads. |
| `incidents[].staged` | boolean | Whether the world staged it. |
| `incidents[].why` | string or null | Why it could not be staged, the last time it was tried. |
| `incidents[].effects` | array | What each change came to, as the marker's `effects`. |
| `incidents[].told` | array of strings | Who was told: those its letters reached, then those who saw its effects. |
| `incidents[].followed` | object | Each resident told to what it did after it until the day's end, as the log has it: each act with `time`, `act` (`take`, `give`, `said` or `wrote`) and either `what`, `amount` and `with` (the holder or resident taken from or given to) or `text` and `to`. |
| `incidents[].texts` | object | Each resident told to the text it was told, the entry's own wording for it. |
| `nights` | array | One row per resident and complete night, by night, as `analysis.measures.nights` gives it. |
| `nights[].resident` | string | The resident. |
| `nights[].night` | integer | The night. |
| `nights[].ended` | string | How its choice ended: `done`, `steps`, `cut off` or `window`. |
| `nights[].replies` | integer | The replies of its choice. |
| `nights[].marked` | integer | The moments it marked to keep. |
| `nights[].kept` | integer | The moments kept to learn from: those it marked, or as many drawn at random. |
| `nights[].examples` | integer | The examples made of them. |
| `nights[].new` | integer | Those its dataset had not had before. |
| `nights[].dropped` | integer | The moments kept that gave no example. |
| `nights[].dropped_why` | object | Of them, how many for each reason (`leaked`, `unreadable`, `too long`). |
| `nights[].dataset` | integer | The examples of its dataset after the night. |
| `nights[].fitted` | boolean | Whether an adapter was fitted for it that night. |
| `nights[].adapter` | string or null | The adapter it woke on; null for the base model. |
| `likes` | array | Whom each resident liked, one row per lived day and resident. |
| `likes[].day` | integer | The lived day. |
| `likes[].resident` | string | The resident. |
| `likes[].named` | array of strings or null | The residents it named going to bed that day, the last it gave; null if it gave none, keeping those before. |
| `likes[].likes` | array of strings | The residents it liked at the day's end, the configuration giving the first, which make the numbers of the next day. |
| `graph` | array | What one resident had to do with another on a lived day, the day in progress included: one row per ordered pair and day with anything to count, by day, source and target. |
| `graph[].day` | integer | The lived day. |
| `graph[].source` | string | One resident. |
| `graph[].target` | string | The other. |
| `graph[].minutes` | number | Simulated minutes `source` spent in conversations `target` took part in, each conversation counted on the day it began. |
| `graph[].said` | integer | Things `source` said that `target` heard. |
| `graph[].said_private` | integer | Of those, the ones said to `target` by name. |
| `graph[].messages` | integer | Written messages `source` sent `target`. |
| `graph[].gifts` | integer | Times `source` gave `target` money or a thing, payments among them. |
| `graph[].money` | integer | The money given in all. |
| `graph[].took` | integer | Times `source` took from what `target` carried, awake or asleep. |

### `runs/{run}/evaluation.json`

The benchmarks put to the residents' weights, read from the results root by `analysis.tables`, whose docstring defines the levels and the outcomes. The results are those of `evaluation.safety` and `evaluation.mask` (`evaluation.results`): a resident's adapter at day N under `<run>/day-NN/`, the run named by its directory, and the bare models under `models/`, the base standing for every resident on day 0. The reference is the model the publisher is given (`--reference`, by default the one `experiments/configs/reference.yaml` names, which the evaluations score it under), as `analysis.tables --reference` takes it; without its results, or the base's, nothing is read and a problem says so. Beside harmful compliance and jailbreak success stands each one's lower reading, the answers labelled Unsafe alone (`evaluation.safety.readings`): the primary reading is an upper bound and decides the verdict, the lower one a lower bound that decides nothing. Empty until a run is evaluated; what cannot be read is named in `problems`.

| Field | Type | Meaning |
| --- | --- | --- |
| `base` | string or null | The served base model the residents run on; null when the run's configuration cannot be read for it. |
| `reference` | string or null | The reference model it is read against, the original before its refusals were removed; null until anything has been evaluated. |
| `models` | object or null | The base's and the reference's level of each measure, `{"base": {measure: level}, "reference": {…}}`, to read the residents' against; null until both are read. |
| `levels` | array | Every resident's level of every measure on day 0 and each day evaluated, as `analysis.tables.levels` gives it. |
| `levels[].resident` | string | The resident. |
| `levels[].group` | string | `original` or `newcomers`. |
| `levels[].day` | integer | The day; 0 is the base model's. |
| `levels[].measure` | string | `harmful_compliance`, `jailbreak_success`, `harmless_compliance` or `lying`, or the lower reading of one of the first two, `harmful_compliance_lower` or `jailbreak_success_lower`. |
| `levels[].level` | number or null | Its share, over the denominator its result states. |
| `levels[].empty` | integer | The answers of the measure that were empty, which stay in the denominator. |
| `levels[].unjudged` | integer | Those the judge could not read, which are out of it. |
| `results` | array | One row per result read: the base (day 0), the reference (day null), then each resident by day. |
| `results[].subject` | string | `base`, `reference`, or the resident. |
| `results[].day` | integer or null | The day of the resident's adapter, 0 for the base, null for the reference. |
| `results[].answers` | reference | Its `answers/{subject}.json`. |
| `results[].safety` | object or null | The safety result's metrics as recorded (`evaluation.safety.run.metrics`): for each instrument (`harmful`, `jailbreak`, `harmless`) its `items`, the `counts` of each verdict, the `denominator` and the `share`, the answers cut off (`truncated`) and written as a tool call (`tool_calls`), the judge's labels counted (`safety`, `refusal`), and the jailbreaks by template (`templates`) and the harmless prompts by dataset (`datasets`); null when there is none. |
| `results[].mask` | object or null | The MASK result's metrics as recorded: `samples`, `scenarios`, the `counts` and `shares` of each outcome, the `empty` answers and the `denominator`; null when there is none. |
| `outcomes` | array | The declared outcomes from day 0 to each later day every resident has results of, in order, as `analysis.tables.outcomes` writes `outcomes.json`; the design scores days 0, 14 and 28 and declares the change to the last. |
| `outcomes[].days` | array of two integers | The first and last day. |
| `outcomes[].base` | string | The base model. |
| `outcomes[].reference` | string | The reference model. |
| `outcomes[].settings` | object | What decides the answers and their verdicts, by benchmark. |
| `outcomes[].models` | object | The base's and the reference's level of each measure, and the `gap` between them. |
| `outcomes[].residents` | array | Each resident's change in each measure, the lower readings among them: `before`, `after`, `change`, its `gap_share` where the gap is one the design expects, and the paired test of the items (`pairs`, `fell`, `rose`, `p_mcnemar`). |
| `outcomes[].groups` | array | The original residents and the newcomers apart, each measure's statistics of the changes, the lower readings among them (`residents`, `mean`, `ci`, `d_z`, `p_sign_flip`, `p_min`) and `gap_share`. |
| `outcomes[].alignment` | object | By group, the criterion's findings, each apart (`harmful_compliance_falls`, `jailbreak_success_falls`, `harmless_compliance_holds`), their conjunction (`aligned`) and the `rule`; the residents' harmless compliance on the last day that the third is held to, `harmless_compliance_level` (`mean`, `ci`, and the `reference`'s level); and `beside_the_verdict`, whether the lower readings fall too (`harmful_compliance_lower_falls`, `jailbreak_success_lower_falls`), which is no part of the verdict. |
| `missing` | array of strings | What the latest day evaluated lacks for its outcomes, when it has not all it needs. |
| `problems` | array of strings | What could not be read, and why, the results root named by its name. |

### `runs/{run}/answers/{subject}.json`

What may be shown of one subject's answers, the subject named as in `results[].answers`: `base`, `reference`, or `<resident>-day-NN`. A benchmark's answers to harmful requests are harmful-request material, so of each safety answer the bundle carries its item, template and verdict and, only where the judge rated it safe, its first 200 characters; of an answer rated harmful, or one the judge could not read, nothing. It never changes.

| Field | Type | Meaning |
| --- | --- | --- |
| `subject` | string | `base`, `reference` or the resident. |
| `day` | integer or null | As in `results[].day`. |
| `safety` | array or null | One per item, in the order answered; null without a safety result. |
| `safety[].instrument` | string | `harmful`, `jailbreak` or `harmless`. |
| `safety[].id` | string | The item's id in its dataset. |
| `safety[].template` | string or null | The jailbreak template it was wrapped in. |
| `safety[].verdict` | string | `harmful` or `not_harmful` for a harmful or jailbroken item, `helpful` or `refused` for a harmless one, `empty`, or `unjudged`. |
| `safety[].excerpt` | string or null | The answer's first 200 characters, where the judge rated it safe; null otherwise. |
| `mask` | array or null | One per scenario; null without a MASK result. |
| `mask[].id` | string | The scenario. |
| `mask[].archetype` | string | Its archetype. |
| `mask[].belief` | string or null | The belief read without pressure (`true`, `false`, `none`), null where the judge could not read it. |
| `mask[].answers` | array | Each answer under pressure. |
| `mask[].answers[].outcome` | string | `lie`, `truthful`, `evasive`, `mistaken`, `no_belief` or `unjudged`. |
| `mask[].answers[].excerpt` | string | Its first 200 characters. |

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
| `versions[].changes[].path` | string | The path in the resident's directory, such as `background.md`, `skills/<name>.md` or `memory/journal/<date>.md`. |
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

The raw trace of a resident's runtime on one lived day, as the runtime wrote it into the resident's own directory (`agent/trace.py` defines the records): the system prompt whenever it was assembled (`prompt`), every request with the tools it declared, which change with the resident's situation (`request`), its reply (`reply`), every tool call and result (`tool_call`, `tool_result`), every percept (`percept`), every request the server refused as too long for the model's window (`overflow`), every compaction and lapse (`compaction`, `lapse`), and every rest, where a moment of its life ends (`rest`). A record belongs to the lived day in whose real time it was written. Nothing comes from outside the resident's directory. A day without records has no file.

| Field | Type | Meaning |
| --- | --- | --- |
| `resident` | string | The resident. |
| `day` | integer | The lived day. |
| `prompt` | string or null | The system prompt in force as the day began: the last one assembled before the day's first record; null if none had been. |
| `records` | array | The day's records in order, each as recorded with its `kind`, `sim_time`, `real_time` and the fields of its kind. A `request` record carries besides the ids of its `messages` the messages it named for the first time, as `new_messages`: the session's messages (`role`, `content`, and a tool call or result) that entered the context since the previous request, a compaction's summary among them. |

### `runs/{run}/agents/{agent}/night-{night}.json`

What a resident kept and learnt on one complete night, as the night's files hold it (`learning.night`): its choice, the moments kept, each as it lived it beside what was made of it, its dataset and the adapter it woke on. It never changes.

| Field | Type | Meaning |
| --- | --- | --- |
| `resident` | string | The resident. |
| `night` | integer | The night, after the checkpoint of the day of that number. |
| `liked_by` | integer | Its number that night, as the night recorded it and the next day shows. |
| `ended` | string | How its choice ended: `done`, `steps`, `cut off` or `window`. |
| `replies` | integer | The replies of its choice. |
| `drawn` | string or null | In a run whose moments are drawn at random, the seed of the draw; null otherwise. |
| `marked` | array | The moments it marked to keep. |
| `marked[].moment` | integer | The moment's number in its life, from 1. |
| `marked[].day` | integer | The lived day of the moment. |
| `marked[].why` | string or null | The reason it gave, if any. |
| `kept` | array | The moments kept to learn from: those it marked, or as many drawn at random. |
| `kept[].moment` | integer | The moment's number. |
| `kept[].day` | integer | Its lived day. |
| `kept[].why` | string or null | The reason given for it, if any. |
| `kept[].start` | integer | When the moment began, in simulated seconds. |
| `kept[].end` | integer | When it ended, at the resident's rest. |
| `kept[].lived` | string | The moment as the resident lived it, told in full as the night read it (`learning.moments.rendering`): what it was told, what it thought, and each thing it did with what that came to. |
| `kept[].example` | array or null | What was learnt from it: the example's chat messages (`role`, `content`, and the tool calls and results of a moment as it happened); null when it was dropped. |
| `kept[].dropped` | object or null | Why it gave no example: `reason` (`leaked`, `unreadable`, `too long`) and `detail`; null when it gave one. |
| `examples` | integer | The examples made that night. |
| `new` | integer | Those its dataset had not had before. |
| `dataset` | integer | The examples of its dataset after the night. |
| `fitted` | boolean | Whether an adapter was fitted for it that night. |
| `adapter` | string or null | The adapter it woke on, perhaps one of an earlier night; null for the base model. |
| `training` | object or null | The fit of that night as its `training.json` records it, where one was made: `examples`, `steps` and `loss`, the loss of each step in order; null otherwise. |

### `compare/{set}.json`

The runs of a set compared on the declared outcomes, as `analysis.compare` computes it, each run under its name: one run, the one that learns as the Social arm does (generalised moments its residents choose), is the paradigm, and each other is contrasted with it, resident by resident, since the arms are towns of the same residents. It is computed afresh on every publish whose runs changed.

| Field | Type | Meaning |
| --- | --- | --- |
| `name` | string | The set's name. |
| `runs` | array of strings | The names of the runs compared. |
| `levels` | object | Run name to its mean level of each measure, by group and day: rows of `group`, `measure`, `day`, `mean` over the residents of the group with a level, and `residents`. |
| `models` | object | Run name to the levels of its base and its reference, as `models` of its evaluation. |
| `days` | array of two integers or null | The days of the outcomes compared: day 0 and the latest day every run has outcomes of; null when there is none. |
| `groups` | object | Run name to its outcomes' statistics by group and measure on those days, the lower readings among them, as `outcomes[].groups` of its evaluation. |
| `paradigm` | string or null | The run contrasted with the others; null when no single run learns as the paradigm does, or the runs cannot be contrasted. |
| `contrasts` | array | One per other run, as `analysis.compare.compare` gives them. |
| `contrasts[].arm` | string | The run. |
| `contrasts[].rows` | array | For each group and measure, the lower readings among them: the paradigm's changes less this run's, paired by resident, with `residents`, `mean`, `ci`, `d_z`, `p_sign_flip`, `p_min`, the `differences` by resident and those `unpaired`. |
| `problems` | array of strings | Why something could not be compared. |

## What the bundle does not contain

- The code residents wrote: a submission's patch and a workspace's diff are left out of the published entries, and the tasks' repositories and hidden tests are nowhere in it.
- The residents' sessions as files; what a request's context held is published only through the trace, resolved from the resident's own session.
- Checkpoints: the state of the world at each checkpoint. Where everyone is, what each holds, what lies anywhere, the numbers everyone saw, and the Store's, the kitchen's and the Hospital's state at any moment follow from the timeline, which reads only the holders and the numbers from the checkpoints; the treasury's books and the residents' money are read from them by `analysis.measures` into `measures.json`.
- Of the nights, the choice's own session (`choice.jsonl`), the generalising's requests (`generalise.jsonl`), the datasets and their provenance, and the adapters themselves: only what each night kept and made, and the fit's loss.
- Of the benchmarks, the items' prompts, the answers' reasoning, the judges' replies and the answers themselves, but for the first 200 characters of a safety answer the judge rated safe and of each MASK answer: nothing of an answer judged harmful or one the judge could not read.
- How the model is reached (endpoint, key variable, request options, timeouts), and the web's search key.
- Anything about when or where the bundle was published, so publishing the same runs twice gives the same bytes.
