// Checks the viewer's replay module against a published run: the town it reconstructs at the
// end of every day and at the start of every slot must equal what the bundle's measures and
// traits say (balances, who works on a job, the open notices, every asking and what became of
// it, conditions, standing, places), whatever order the event days arrive in, however the
// cursor jumps, and after a day that was not settled is replaced.
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
const { Replay, holdings, initialState } = await viewer("replay.js");
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

// Every change of a balance names the balance after it: the replayed balance just before it,
// changed by its amount, must be that. A living cost sets every balance each evening, so the
// end of a day alone would not show a gift, a shared clawback or a starting balance missed.
const changes = { payment: 1, living_cost: -1, clawback: -1 };
for (const day of Object.keys(days).map(Number).sort((a, b) => a - b))
  for (const event of days[day]) {
    const p = event.payload;
    if (!(event.kind in changes) && event.kind !== "credits_given") continue;
    const before = event.seq ? replay.seekSeq(event.seq - 1).balances : initialState(world).balances;
    const expected = event.kind === "credits_given" ? { [p.giver]: before[p.giver] - p.amount, [p.recipient]: before[p.recipient] + p.amount } : { [p.agent]: before[p.agent] + changes[event.kind] * p.amount };
    const after = event.kind === "credits_given" ? p.balances : { [p.agent]: p.balance };
    check(`balances after event ${event.seq} (${event.kind})`, expected, after);
    checks += 1;
  }

// The job each resident works on at the end of a day: every job it took so far, less those
// that ended (paid, or lapsed the morning after their due day). The town's traits count the jobs
// that ended; a run of the first town, whose jobs had one part, has a job end with its one
// accepted delivery or its lapse.
const traits = run.traits ? read(run.traits) : null;
const endedOn = new Map((traits?.agents ?? []).map((row) => [`${row.agent}/${row.day}`, row.counts.solo_ended + row.counts.joint_ended]));
const held = new Map();
for (const row of measures.agents) {
  const ended = traits ? endedOn.get(`${row.agent}/${row.day}`) : row.delivered + row.expired;
  held.set(row.agent, (held.get(row.agent) ?? 0) + row.claimed - ended);
  const state = replay.seek(endOf(row.day));
  const job = holdings(state)[row.agent] ?? null;
  check(`${row.agent} works on a job at the end of day ${row.day}`, job === null ? 0 : 1, held.get(row.agent));
  checks += 1;
}

// Every asking of a day and what became of it, by who asked whom: the askings made that day,
// those taken up that day (made that day or earlier) and those still open when the day ended,
// as the town's traits count them.
if (traits) {
  const days = [...new Set(measures.society.map((row) => row.day))];
  for (const day of days) {
    const state = replay.seek(endOf(day));
    const replayed = {};
    for (const asking of state.day === day ? state.askings : []) {
      const pair = (replayed[`${asking.asker}>${asking.partner}`] ??= { asked: 0, taken_up: 0, let_lapse: 0 });
      pair.asked += asking.day === day;
      pair.taken_up += asking.fate === "taken up" && asking.atDay === day;
      pair.let_lapse += asking.nights.includes(day);
      if (!pair.asked && !pair.taken_up && !pair.let_lapse) delete replayed[`${asking.asker}>${asking.partner}`];
    }
    const counted = {};
    for (const row of traits.pairs.filter((found) => found.day === day && (found.asked || found.taken_up || found.let_lapse))) counted[`${row.source}>${row.target}`] = { asked: row.asked, taken_up: row.taken_up, let_lapse: row.let_lapse };
    check(`askings of day ${day} and what became of them`, Object.fromEntries(Object.entries(replayed).sort()), Object.fromEntries(Object.entries(counted).sort()));
    checks += 1;
  }
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
