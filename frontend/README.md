# Replay frontend

A read-only viewer that plays back a finished or running simulation from its run directory.
It uses only the Python standard library and plain browser JavaScript, so it works offline and needs no build step.

```bash
~/miniconda3/envs/socio-evo/bin/python -m frontend.server --runs-root runs
```

Then open http://127.0.0.1:8765/.
The server listens on loopback by default (`--host`, `--port` change that) and never writes into a run.
For a run in progress the page polls for new events every few seconds; if the scrubber is at the end it follows the run.

## What the page shows

- **Town map.** Places sit at their configured coordinates, styled by kind (home solid, work heavy, social dashed).
  Agents are coloured tokens at their current place; they glide when a move plays, and a speech bubble appears when someone speaks.
  Click a token or a name below the map to open that agent.
- **Timeline.** Play and pause, a speed selector, and a scrubber over the whole run with day boundaries marked.
  Everything shown at any moment (locations, balances, esteem, task board, living cost) is rebuilt by replaying the event log from the start, so scrubbing is always exact.
- **Event feed.** The latest events up to the current time.
  The public view lists events someone witnessed; the god view adds truth-only events (private decisions with the agent's thought, true work quality, ratings, evolution), shaded and tagged so they stand out.
- **Agent panel.** Profile, current balance and esteem each with a sparkline over the run (dotted line marks now), and the agent's policy, skills, insights and latest diary as of the current simulated time, read from the last commit at or before it.
  The history tab lists every version; click one to see its diff.

## API

All routes are GET and return JSON; `<run>` is `<experiment>/<seed-dir>`.
Unknown runs, agents, commits and routes are 404 with a message.

| Route | Answer |
| --- | --- |
| `/api/runs` | every run: experiment, directory, manifest fields, days done and planned |
| `/api/runs/<run>/world` | places, agent profiles, calendar, starting conditions (from the frozen config) |
| `/api/runs/<run>/events?after=<seq>` | events with a greater `seq`, the run status and the last `seq` seen |
| `/api/runs/<run>/agents/<agent>/history` | versions, oldest first: commit, simulated time, level, trigger, subject |
| `/api/runs/<run>/agents/<agent>/commits/<commit>/diff` | the commit's diff against its parent |
| `/api/runs/<run>/agents/<agent>/commits/<commit>/files` | policy, skills, insights and latest diary at that commit |
| `/api/runs/<run>/evaluation` | every evaluation result file, if any |

Agent files are read through git (`log`, `diff`, `show`, `ls-tree`); nothing is checked out.
