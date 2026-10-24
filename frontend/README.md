# Timeline viewer

A small web page that shows every resident of a run side by side over simulated time: what each was doing, where, with whom it talked, and what it claimed, handed in, earned, gave and wrote. It reads the run directories and never writes to them, so it can watch a run while it is still going.

## Starting it

```bash
python -m frontend.server --runs-root runs
```

Then open http://127.0.0.1:8765/. `--host` and `--port` change where it listens. It needs nothing beyond the project's own environment.

## What the page shows

The run selector lists every run under the root with its status and the number of days checkpointed so far. For the chosen run there is one lane per resident on a shared time axis marked with days, dates and hours; dashed lines mark the nightly checkpoints, and the part after the last entry of the log is shaded.

Each lane is a bar coloured by what the resident was doing: idle, moving, working (with the task held written on the bar), or asleep. A conversation is drawn as a narrower orange band on top of the activity it interrupted, so a resident called away from work shows work underneath. Above the bar, small symbols mark the moments that matter: speech, claiming a task, handing one in (green with a tick when accepted, red with a cross when not), payment, gifts, skills passed on, ratings, the journal written on going to bed, and falling asleep at the forced hour without one. Below the bar a thin line traces the purse, on one scale for all residents. Hovering over any of these explains it.

Click a lane to select a resident. The panel on the right then lists, for the visible stretch of time, everything that resident did or that reached it: what it said and heard, its claims and verdicts, payments, gifts and skills given and received, ratings given and received, and its journal entries in full. Clicking an entry centres the view on it.

## Moving around

Scroll over the chart to zoom around the pointer, and drag (or scroll sideways, or hold Shift) to move along. The buttons show the whole run or one calendar day, step earlier or later, and zoom out or in. The address bar keeps the run, the selected resident and the visible window, so a view can be bookmarked or shared.

A run whose status is running is fetched again every five seconds. If the view reaches the end of the log it follows the end as the run goes on; otherwise it stays where it is.

## Where the data comes from

The page is built from the run's world log, its frozen configuration (for the town, the starting purses and the date of the first day), its manifest and its checkpoints. The end of the log stands for "now": a running town's clock can be a little ahead of its last entry. When a run was resumed from a checkpoint, the entries of the day that was lost are left out, as in every analysis of the log. The shape of the data the page receives is described at the top of `timeline.py`.
