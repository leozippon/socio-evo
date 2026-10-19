# Resident Activity Details Implementation Plan

**Goal:** Let researchers inspect an activity from the town timeline and browse each resident's daily activity ledger.

**Architecture:** Reuse activity membership events as the source of truth. Keep the town panel compact: eight lanes, hover summaries and eight resident summary links. Add an Activities tab to the existing person route, with a day selector, chronological table and a selected membership's event transcript. Stable membership keys distinguish resumed sessions with the same activity ID. Preserve the replay cutoff and never show later events as already observed.

**Tech Stack:** Existing ES modules, DOM helpers, CSS, hash routes, Node regression checks and Python publication tests.

## Design

A modal was considered but would duplicate navigation and constrain long tool logs. A separate global Activities page would detach activity history from the resident file. The chosen person tab keeps biography, decisions and activities together, supports deep links and ordinary browser navigation, and works with the existing lower People navigation.

Hover or keyboard focus on a lane segment shows resident, type, start/end, elapsed duration, location and state. Clicking links to `people/<name>?tab=activities&day=<day>&activity=<membership-key>&t=<cutoff>`; it does not change the simulation. The panel's lower section lists residents and daily totals instead of a long interleaved event ledger.

The resident tab loads the selected published day, normalizes second timestamps in log order, and reconstructs intervals only through the selected cutoff. The table shows start, end, type, place, duration and status. A selected activity shows its participants, result and chronological operations, feedback and received speech. Own private work is not replaced by other collaborators' private operations; speech is shown only when delivered during this resident's membership. Legacy runs remain readable and receive an explicit empty state when membership events are absent.

## Task 1 — Shared data model

Modify `frontend/static/js/clock.js`, `replay.js` and `town/activity-model.js`. Add pure normalization, interval event bounds, participant-aware transcripts, daily totals, duration formatting and route construction. Extend `tests/frontend/activity_timeline_check.mjs` for resumed IDs, late joins, unrelated private tools, cutoff filtering and link round-trips. Run `node tests/frontend/activity_timeline_check.mjs`.

## Task 2 — Town panel

Modify `town/activities.js`, `views/town.js` and `css/town.css`. Replace block seek handlers with detail anchors. Add a compact accessible tooltip on hover/focus. Replace the interleaved ledger with resident summary links. Reuse activity type colors; preserve the current replay moment in links.

## Task 3 — Resident ledger and detail

Create `frontend/static/js/views/person-activities.js`; modify `views/person.js` and `css/views.css`. Add Activities navigation, bounded day selection, the daily table and a deep-linked detail transcript. Label the exact snapshot rather than displaying Day 0 for a run's first unfinished day. Refresh live activity data when event days change.

## Task 4 — Verify and deploy viewer only

Run clock/activity tests and JS syntax checks. Verify live browser hover, resident summary links, a block-to-detail link and day navigation. Commit locally, send an incremental Git bundle to the isolated viewer checkout, and preserve the experiment process and experiment source revision. Save a screenshot of the resulting interface.
