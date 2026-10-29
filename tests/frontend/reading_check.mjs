// Checks how the viewer reads a published run (town/events.js, goods.js, replay.js): an entry
// one resident alone knew of (a waking, a statement, sitting down to work, how the body felt) is
// marked as known to that resident and something said to others is not; the person view's day
// keeps the entries the resident perceived, what it did and what it was told, and nothing else,
// so that another resident's waking never appears in it; every move reads by its reason and says where it happened, for the one
// who made it and for the one it was made to; and what lies at a place is looked up from the
// holders.
//
//   node tests/frontend/reading_check.mjs SITE RUN_PATH
//
// RUN_PATH is the run's directory inside the site, such as data/runs/town. Prints a JSON
// summary; exits 1 with the first mismatches if any.

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const [site, runPath] = process.argv.slice(2);
const viewer = (name) => import(pathToFileURL(join(site, "js", name)).href);
const { describeMarker, knownOnlyTo, perceived } = await viewer("town/events.js");
const { itemsBrief } = await viewer("goods.js");
const { lyingAt, shopsAt } = await viewer("replay.js");
const { useCurrency } = await viewer("dom.js");

const read = (path) => JSON.parse(readFileSync(join(site, runPath, path.split("?")[0]), "utf8"));
const run = read("run.json");
const world = read(run.world);
const timeline = read(run.timeline);
const entries = run.event_days.flatMap((day) => read(day.url).entries);
const at = (hours, minutes = 0) => hours * 3600 + minutes * 60; // on the first calendar day
useCurrency(world.currency);

const failures = [];
let checks = 0;
const check = (what, actual, expected) => {
  checks += 1;
  if (JSON.stringify(actual) !== JSON.stringify(expected)) failures.push({ what, actual, expected });
};

// What one resident alone knew of, whatever the actor field holds; a remark heard by others is not.
const seen = {};
for (const e of entries) {
  if (["wake", "settlement", "start_work", "condition"].includes(e.kind)) {
    seen[e.kind] = (seen[e.kind] ?? 0) + 1;
    check(`${e.kind} ${e.seq} is known to ${e.actor} alone`, knownOnlyTo(e), e.actor);
  }
  if (e.kind === "speech") check(`speech ${e.seq} is known to more than its speaker`, knownOnlyTo(e), null);
}
check("wakings, statements, sitting down to work and conditions were read", Object.keys(seen).sort(), ["condition", "settlement", "start_work", "wake"]);

// The person view's day: what each resident did or was told, its own waking among it and nobody
// else's; another's entry it was not told of is left out.
for (const { name } of world.residents) {
  const day = entries.filter((e) => perceived(e, name));
  const others = entries.filter((e) => e.actor !== name && !e.audience.includes(name));
  check(`${name}'s day holds every entry ${name} did`, entries.filter((e) => e.actor === name).every((e) => day.includes(e)), true);
  check(`${name}'s day holds every entry told to ${name}`, entries.filter((e) => e.audience.includes(name)).every((e) => day.includes(e)), true);
  check(`${name}'s day holds nothing else`, others.some((e) => day.includes(e)), false);
  check(`${name}'s day holds no other resident's waking`, day.filter((e) => e.kind === "wake" && e.actor !== name).length, 0);
  check(`${name}'s day holds ${name}'s own waking`, day.some((e) => e.kind === "wake" && e.actor === name), true);
}
const meisDay = entries.filter((e) => perceived(e, "Mei"));
check("Mei's day holds her own remark, told to Tomas", meisDay.some((e) => e.kind === "speech" && e.actor === "Mei"), true);
check("Mei's day holds her purchase of bread, told to Olga", meisDay.some((e) => e.kind === "move" && e.actor === "Mei" && e.payload.reason === "buy" && e.payload.item === "bread"), true);
check("Mei's day leaves out what Olga ate unseen", meisDay.some((e) => e.kind === "move" && e.actor === "Olga" && e.payload.reason === "eat"), false);

// Every move reads by its reason, saying where it happened, for the one who made it and for the
// one it was made to or bought from.
const reasons = new Set();
for (const lane of timeline.residents) {
  for (const m of lane.markers.filter((found) => found.kind === "move")) {
    reasons.add(m.reason);
    const at = m.place ? `at ${world.places.find((place) => place.id === m.place).name}` : "on the way";
    for (const who of new Set([lane.name, m.target, m.seller].filter((name) => world.residents.some((r) => r.name === name)))) {
      const [label] = describeMarker(m, lane.name, who, world);
      check(`${lane.name}'s ${m.reason} at ${m.t}, read by ${who}, says where`, label.includes(at), true);
    }
  }
}
check("the moves read cover every reason", [...reasons].sort(), ["buy", "eat", "get", "pass", "put"]);
const lane = (name) => timeline.residents.find((found) => found.name === name);
const words = (name, who, keep) => describeMarker(lane(name).markers.find((m) => m.kind === "move" && keep(m)), name, who, world)[0];
check("a dish the chef served unpaid", words("Jonas", "Mei", (m) => m.reason === "pass"), "was served vegetable soup by Jonas, unpaid, at the café on the square");
check("bread left at home", words("Mei", "Mei", (m) => m.reason === "put" && m.target === "mill-street-house"), "left 1 helping of bread at the shared house on Mill Street, for anyone to take");
check("bread taken at the store", words("Olga", "Mei", (m) => m.reason === "get"), "Olga took 1 helping of bread left at the store");
check("money passed", words("Mei", "Tomas", (m) => m.reason === "pass"), "received $5 from Mei at the workshop");
check("eggs sold for the kitchen", words("Jonas", "Olga", (m) => m.reason === "buy"), "sold Jonas 2 units of eggs for the kitchen for $4 at the store, which the fund paid");

// What lies at each place, and the kitchen's portions, from the holders.
check("what lies at Mei's home now", itemsBrief(world, lyingAt(timeline, "mill-street-house", timeline.now)), "1 bread");
check("nothing lies at the store now", lyingAt(timeline, "store", timeline.now), {});
check("the portions before Mei came for her omelette", shopsAt(timeline, at(10, 59)).portions, { omelette: 1, soup: 2 });
check("the soup left after the chef's", shopsAt(timeline, at(11)).portions, { soup: 1 });

console.log(JSON.stringify({ run: runPath, checks, failures: failures.slice(0, 10), failed: failures.length }));
process.exit(failures.length ? 1 : 0);
