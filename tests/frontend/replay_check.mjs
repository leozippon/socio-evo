// Checks the viewer's replay module against a published run: what it looks up in the timeline
// at the end of every lived day (purses, the task held) and over each day (the markers counted)
// must equal what the bundle's progress document says, the lanes must be contiguous and
// distinct, and a moment looked up at any time must be consistent with itself.
//
//   node tests/frontend/replay_check.mjs SITE RUN_PATH
//
// RUN_PATH is the run's directory inside the site, such as data/runs/town. Prints a JSON
// summary; exits 1 with the first mismatches if any.

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const [site, runPath] = process.argv.slice(2);
const viewer = (name) => import(pathToFileURL(join(site, "js", name)).href);
const { heldAt, markersBetween, moment, purseAt, segmentAt } = await viewer("replay.js");
const { DAY, livedDay } = await viewer("clock.js");

const read = (path) => JSON.parse(readFileSync(join(site, runPath, path.split("?")[0]), "utf8"));
const run = read("run.json");
const timeline = read(run.timeline);
const progress = read(run.progress);

const failures = [];
let checks = 0;
const check = (what, actual, expected) => {
  checks += 1;
  if (JSON.stringify(actual) !== JSON.stringify(expected)) failures.push({ what, actual, expected });
};
const median = (values) => {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = sorted.length >> 1;
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
};

// Every lived day: the purses at its end and the markers it counted.
const COUNTED = { claim: "claims", submission: "submissions", payment: "payments", speech: "speeches", gift: "gifts", skill_shared: "skills_shared", rating: "ratings", journal: "journals", forced_sleep: "forced_sleeps" };
for (const [i, row] of progress.daily.entries()) {
  const day = timeline.days[i];
  check(`day ${row.day} of the timeline`, day.day, row.day);
  const end = day.end ?? timeline.now;
  const purses = timeline.residents.map((lane) => purseAt(lane, end));
  check(`purses at the end of day ${row.day}`, { min: Math.min(...purses), median: median(purses), max: Math.max(...purses) }, row.purse);
  const counts = Object.fromEntries(Object.values(COUNTED).map((key) => [key, 0]));
  counts.accepted = 0;
  counts.rejected = 0;
  counts.paid = 0;
  for (const lane of timeline.residents)
    for (const m of markersBetween(lane, i ? timeline.days[i - 1].end : null, end)) {
      if (!(m.kind in COUNTED)) continue;
      counts[COUNTED[m.kind]] += 1;
      if (m.kind === "submission" && "resolved" in m) counts[m.resolved ? "accepted" : "rejected"] += 1;
      if (m.kind === "payment") counts.paid += m.amount;
    }
  check(`markers of day ${row.day}`, counts, Object.fromEntries(Object.keys(counts).map((key) => [key, row[key]])));
}

// Lanes are contiguous from the start to now, each segment distinct from the next.
for (const lane of timeline.residents) {
  const segments = lane.segments;
  check(`${lane.name}'s lane begins at the start`, segments[0].start, timeline.start);
  check(`${lane.name}'s lane ends now`, segments.at(-1).end, timeline.now);
  for (let k = 1; k < segments.length; k++) {
    check(`${lane.name}'s segments ${k - 1} and ${k} meet`, segments[k].start, segments[k - 1].end);
    check(`${lane.name}'s segments ${k - 1} and ${k} differ`, [segments[k].kind, segments[k].place, segments[k].task] !== [segments[k - 1].kind, segments[k - 1].place, segments[k - 1].task], true);
  }
  for (const talk of lane.conversations) check(`${lane.name}'s conversation at ${talk.start} lies within the run`, talk.start >= timeline.start && talk.end <= timeline.now && talk.start <= talk.end, true);
  // A task is held from its claim until it is paid, given up or runs out; never at the start.
  check(`${lane.name} holds nothing at the start`, heldAt(lane, timeline.start), null);
  for (const m of lane.markers) {
    if (m.kind === "claim") check(`${lane.name} holds task ${m.task} after claiming it`, heldAt(lane, m.t)?.task ?? null, m.task);
    if (m.kind === "payment" || m.kind === "abandon" || m.kind === "expiry") check(`${lane.name} holds nothing after ${m.kind} of task ${m.task}`, heldAt(lane, m.t), null);
  }
}

// Moments at random times are consistent with the lanes they are looked up in.
let seed = 7;
const random = () => ((seed = (seed * 1103515245 + 12345) % 2 ** 31) / 2 ** 31);
for (let k = 0; k < 60; k++) {
  const t = Math.floor(timeline.start + random() * (timeline.now - timeline.start));
  const m = moment(timeline, t);
  check(`the lived day of ${t}`, m.day, livedDay(timeline.days, t));
  for (const lane of timeline.residents) {
    const found = m.residents[lane.name];
    check(`${lane.name}'s segment at ${t} covers it`, found.segment.start <= t && t <= found.segment.end, true);
    check(`${lane.name}'s segment at ${t} is the lane's`, found.segment, segmentAt(lane, t));
    if (found.moving) check(`${lane.name}'s way at ${t} is within bounds`, found.moving.fraction >= 0 && found.moving.fraction <= 1 && found.moving.to === found.segment.place, true);
    else check(`${lane.name} is not on the way at ${t}`, found.segment.kind !== "movement", true);
    if (found.conversation) check(`${lane.name}'s conversation at ${t} covers it`, found.conversation.start <= t && t <= found.conversation.end, true);
  }
}
check("a moment before the start is the first", moment(timeline, timeline.start - DAY).day, timeline.days[0]);

console.log(JSON.stringify({ run: runPath, days: progress.daily.length, checks, failures: failures.slice(0, 10), failed: failures.length }));
process.exit(failures.length ? 1 : 0);
