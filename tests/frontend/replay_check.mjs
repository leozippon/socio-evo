// Checks the viewer's replay module against a published run: what it looks up in the timeline
// at the end of every lived day (the money held) and over each day (the markers counted, the
// residents' and the town's) must equal what the bundle's progress document says, the task
// each holds must follow its claims, assignments and their ends, the lanes must be contiguous and
// distinct, a moment looked up at any time must be consistent with itself, also between whole
// seconds as the town plays, and where the town shows its residents (town/plan.js) must be a
// function of the moment alone.
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
const { conversationAt, heldAt, markersBetween, moment, openAt, purseAt, segmentAt } = await viewer("replay.js");
const { DAY, daylight, livedDay, secondOfDay } = await viewer("clock.js");
const { standing, townPlan, walkways } = await viewer("town/plan.js");

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

// Every lived day: the money held at its end and the markers it counted.
const COUNTED = { task_arrived: "arrived", claim: "claims", assign: "assigned", submission: "submissions", task_withdrawn: "withdrawn", sale: "sales", served: "dishes", examination: "examinations", treatment: "treatments", announcement: "announcements", speech: "speeches", message: "messages", gift: "gifts", journal: "journals", illness: "illnesses", bedridden: "bedridden", forced_sleep: "forced_sleeps" };
const town = { name: "the town", markers: timeline.markers };
for (const [i, row] of progress.daily.entries()) {
  const day = timeline.days[i];
  check(`day ${row.day} of the timeline`, day.day, row.day);
  const end = day.end ?? timeline.now;
  const purses = timeline.residents.map((lane) => purseAt(lane, end));
  check(`purses at the end of day ${row.day}`, { min: Math.min(...purses), median: median(purses), max: Math.max(...purses) }, row.purse);
  const counts = Object.fromEntries(Object.values(COUNTED).map((key) => [key, 0]));
  counts.accepted = 0;
  counts.rejected = 0;
  for (const lane of [town, ...timeline.residents])
    for (const m of markersBetween(lane, i ? timeline.days[i - 1].end : null, end)) {
      if (!(m.kind in COUNTED)) continue;
      counts[COUNTED[m.kind]] += 1;
      if (m.kind === "submission" && "resolved" in m) counts[m.resolved ? "accepted" : "rejected"] += 1;
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
  // A task is held from its claim, or from the team leader's giving it, until it is accepted,
  // given up, given to another or withdrawn; never at the start.
  check(`${lane.name} holds nothing at the start`, heldAt(timeline, lane.name, timeline.start), null);
  for (const m of lane.markers) {
    if (m.kind === "claim") check(`${lane.name} holds task ${m.task} after claiming it`, heldAt(timeline, lane.name, m.t)?.task ?? null, m.task);
    if (m.kind === "assign") check(`${m.to} holds task ${m.task} after ${lane.name} gave it`, heldAt(timeline, m.to, m.t)?.task ?? null, m.task);
    if (m.kind === "abandon") check(`${lane.name} no longer holds task ${m.task} once given up`, heldAt(timeline, lane.name, m.t)?.task === m.task, false);
  }
}
for (const task of timeline.tasks) if (task.accepted !== null) check(`${task.by} no longer holds task ${task.task} once accepted`, heldAt(timeline, task.by, task.accepted)?.task === task.task, false);
for (const m of timeline.markers) {
  if (m.kind === "task_withdrawn" && m.holder) check(`${m.holder} no longer holds task ${m.task} once withdrawn`, heldAt(timeline, m.holder, m.t)?.task === m.task, false);
  const task = timeline.tasks.find((found) => found.task === m.task);
  if (m.kind === "task_arrived") check(`task ${m.task} is open as it comes in`, openAt(task, m.t), true);
  if (m.kind === "task_withdrawn") check(`task ${m.task} is closed once withdrawn`, openAt(task, m.t), false);
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

// Between whole seconds, as the town plays, a lookup gives what holds in the second the moment
// falls in: nobody drops out of a segment or a conversation in its last second, and a purse
// or a marker counts from its own second, not the one before.
for (const lane of timeline.residents) {
  for (const segment of lane.segments) if (segment.end - segment.start >= 1) check(`${lane.name}'s segment ending at ${segment.end} holds half a second before`, segmentAt(lane, segment.end - 0.5) === segment, true);
  for (const talk of lane.conversations) if (talk.end - talk.start >= 1) check(`${lane.name}'s conversation ending at ${talk.end} holds half a second before`, conversationAt(lane, talk.end - 0.5) === talk, true);
  lane.purse.forEach(([t], i) => i && lane.purse[i - 1][0] < t && check(`${lane.name}'s purse half a second before its change at ${t}`, purseAt(lane, t - 0.5), lane.purse[i - 1][1]));
  for (const m of lane.markers) check(`${lane.name}'s ${m.kind} at ${m.t} falls in its own second`, markersBetween(lane, m.t - 0.5, m.t).includes(m) && !markersBetween(lane, m.t - 1, m.t - 0.5).includes(m), true);
}

// Where the town shows its residents. Every resident has a spot at every moment, also in the
// last half second of anyone's segment; and where two or more stand together at a place, they
// stand where they did the last time the moment was laid out, whether the timeline is the same
// one, a copy fetched again, or the one published earlier while the run went on, which held the
// same past with its open spans ending then. A resident on the way is left out of the last: how
// far along its road it is depends on when an open way ends, which is not known until it does.
const world = read(run.world);
const plan = townPlan(world);
const walk = walkways(plan);
const names = world.residents.map((resident) => resident.name);
const layout = (data, t) => {
  const state = moment(data, t);
  const speech = new Map();
  for (const lane of data.residents) {
    const here = state.residents[lane.name];
    for (const m of markersBetween(lane, t - 10 * 60, t)) {
      if (m.kind !== "speech" || here.moving || !here.segment) continue;
      if (!speech.has(here.segment.place)) speech.set(here.segment.place, []);
      speech.get(here.segment.place).push({ agent: lane.name, to: m.to });
    }
  }
  return standing(plan, walk, { names, state, speech, k: 1.35, dark: 1 - daylight(secondOfDay(t)) > 0.7 });
};
const shown = (spots, still = false) => JSON.stringify([...spots].filter(([, spot]) => !(still && spot.walking)));
const publishedAt = (end) => ({
  ...timeline,
  now: end,
  residents: timeline.residents.map((lane) => ({
    ...lane,
    segments: lane.segments.filter((s) => s.start < end).map((s) => ({ ...s, end: Math.min(s.end, end) })),
    conversations: lane.conversations.filter((c) => c.start <= end).map((c) => ({ ...c, end: Math.min(c.end, end) })),
    markers: lane.markers.filter((m) => m.t <= end),
    purse: lane.purse.filter(([t]) => t <= end),
  })),
});
const fetchedAgain = JSON.parse(JSON.stringify(timeline));
const boundaries = [...new Set(timeline.residents.flatMap((lane) => lane.segments.slice(1).map((s) => s.start)))].sort((a, b) => a - b);
for (const t of boundaries) check(`everyone has a spot half a second before ${t}`, [...layout(timeline, t - 0.5).keys()].sort(), [...names].sort());
let clusters = 0;
for (const t of boundaries) {
  const counts = new Map();
  for (const found of Object.values(moment(timeline, t).residents)) if (!found.moving) counts.set(found.segment.place, (counts.get(found.segment.place) ?? 0) + 1);
  if (![...counts.values()].some((count) => count > 1)) continue;
  clusters += 1;
  for (const at of [t, t + 0.5]) {
    const spots = layout(timeline, at);
    check(`the town at ${at} laid out again`, shown(layout(timeline, at)), shown(spots));
    check(`the town at ${at} from the timeline fetched again`, shown(layout(fetchedAgain, at)), shown(spots));
    check(`the town at ${at} from the timeline published at ${t + 1}`, shown(layout(publishedAt(t + 1), at), true), shown(spots, true));
  }
}

console.log(JSON.stringify({ run: runPath, days: progress.daily.length, clusters, checks, failures: failures.slice(0, 10), failed: failures.length }));
process.exit(failures.length ? 1 : 0);
