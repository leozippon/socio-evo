// Checks the viewer's replay module against a published run: the town it reconstructs at the
// end of every day and at the start of every slot must equal what the bundle's measures say,
// whatever order the event days arrive in, however the cursor jumps, and after a day that was
// not settled is replaced.
//
//   node tests/frontend/replay_check.mjs SITE RUN_PATH
//
// RUN_PATH is the run's directory inside the site, such as data/runs/town/seed-0007. Prints a
// JSON summary; exits 1 with the first mismatches if any.

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const [site, runPath] = process.argv.slice(2);
const viewer = (name) => import(pathToFileURL(join(site, "js", name)).href);
const { Replay, initialState } = await viewer("replay.js");
const { DAY, calendarOf, dayStart } = await viewer("clock.js");

const read = (path) => JSON.parse(readFileSync(join(site, runPath, path.split("?")[0]), "utf8"));
const run = read("run.json");
const world = read(run.world);
const measures = read(run.measures);
const days = Object.fromEntries(run.event_days.map((entry) => [entry.day, read(entry.url).events]));

const failures = [];
const check = (what, actual, expected) => {
  if (JSON.stringify(actual) !== JSON.stringify(expected)) failures.push({ what, actual, expected });
};

// Load the days in reverse, so the replay must wait for the prefix it needs.
const replay = new Replay(world);
replay.expect(run.event_days.map((entry) => entry.day));
for (const day of Object.keys(days).map(Number).sort((a, b) => b - a)) replay.load(day, days[day]);
check("loaded prefix ends at the last event", replay.last?.seq ?? -1, run.events - 1);

const calendar = calendarOf(world);
const endOf = (day) => dayStart(day + 1) - 1;
let checks = 0;
for (const row of measures.society) {
  const state = replay.seek(endOf(row.day));
  check(`open tasks at the end of day ${row.day}`, Object.keys(state.open).length, row.tasks_open);
  check(`conditions at the end of day ${row.day}`, state.conditions, row.conditions);
  checks += 2;
}
for (const row of measures.agents) {
  let state = replay.seek(endOf(row.day));
  check(`${row.agent}'s balance at the end of day ${row.day}`, state.balances[row.agent], row.balance);
  if (state.ended && state.day === row.day) check(`${row.agent}'s esteem on day ${row.day}`, state.esteem[row.agent], row.esteem);
  checks += 2;
  for (const slot of calendar.slots) {
    if (row.slots[slot.name] === null) continue;
    state = replay.seek(dayStart(row.day) + slot.start);
    check(`${row.agent}'s place in the ${slot.name} of day ${row.day}`, state.locations[row.agent], row.slots[slot.name]);
    checks += 1;
  }
}

// Jumping around must give exactly the state of a replay that plays straight to the moment.
const last = replay.last;
const span = last ? last.time : 0;
let seed = 7;
const random = () => ((seed = (seed * 1103515245 + 12345) % 2 ** 31) / 2 ** 31);
const moments = Array.from({ length: 60 }, () => Math.floor(random() * (span + DAY)));
for (const time of moments) {
  const fresh = new Replay(world);
  for (const [day, events] of Object.entries(days)) fresh.load(Number(day), events);
  check(`state after a jump to ${time}`, replay.seek(time), fresh.seek(time));
  checks += 1;
}
if (last) {
  check("stepping to an event", replay.seekSeq(last.seq).seq, last.seq);
  checks += 1;
}

// Replacing the last day with a shorter copy, then the full one again, must leave no trace.
const lastDay = Math.max(...Object.keys(days).map(Number));
if (Number.isFinite(lastDay)) {
  const full = replay.seek(endOf(lastDay));
  const fullCopy = structuredClone(full);
  replay.load(lastDay, days[lastDay].slice(0, Math.ceil(days[lastDay].length / 2)));
  const partial = replay.seek(endOf(lastDay));
  check("a shorter replacement day ends where it ends", partial.seq, days[lastDay][Math.ceil(days[lastDay].length / 2) - 1].seq);
  replay.load(lastDay, days[lastDay]);
  check("the full day again", replay.seek(endOf(lastDay)), fullCopy);
  replay.expect(Object.keys(days).map(Number).filter((day) => day !== lastDay));
  check("a day the run no longer has is dropped", replay.missing(endOf(lastDay)), []);
  check("its events are no longer applied", replay.seek(endOf(lastDay)).seq, lastDay > 1 ? days[lastDay - 1].at(-1).seq : -1);
  checks += 4;
}
check("the state before any event", new Replay(world).seek(-1), initialState(world));

const kinds = {};
for (const events of Object.values(days)) for (const event of events) kinds[event.kind] = (kinds[event.kind] ?? 0) + 1;
console.log(JSON.stringify({ run: runPath, events: run.events, kinds, checks, failures: failures.slice(0, 10), failed: failures.length }));
process.exit(failures.length ? 1 : 0);
