// Checks how the viewer reads a published run (town/events.js, goods.js, replay.js): an entry
// one resident alone knew of (a waking, a statement, sitting down to work, how the body felt) is
// marked as known to that resident and something said to others is not, a remark said by name
// included; whether an entry is private is decided from the whole entry, its actor and audience,
// whoever reads it, and in a reader's wording a public entry it knew of names who else did; the
// person view's day keeps the entries the resident perceived, what it did and what it was told,
// and nothing else, so that another resident's waking never appears in it; every move reads by
// its reason and says where it happened, for the one who made it and for the one it was made to;
// money paid for work reads with the tax withheld from it, by the one paid: a share of a client's
// payment, a sale, a fee; a grant reads with its reason, to the mayor and to the one granted;
// the midnight statement tells the rent paid and owed and the salary; and what lies at a place is
// looked up from the holders.
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
const { concerns, describeMarker, knewNote, knewOf, knownOnlyTo, perceived } = await viewer("town/events.js");
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

// Whether an entry is private is decided from the whole entry, the same in the town's wording and
// in every resident's, whichever entries a view keeps; a reader who knew of a public entry is told
// who else did.
for (const e of entries) {
  for (const reader of [null, ...world.residents.map((r) => r.name)]) {
    const note = knewNote(e, reader);
    const knew = knewOf(e);
    if (knew.length === 1) check(`entry ${e.seq} is private for ${reader ?? "the town"}`, note?.private, true);
    else if (reader && knew.includes(reader)) check(`entry ${e.seq} names who else knew, for ${reader}`, [note?.private, note?.title], [false, `${knew.filter((name) => name !== reader).join(", ").replace(/, ([^,]*)$/, " and $1")} knew of this too`]);
    else check(`entry ${e.seq} says nothing of who knew, for ${reader ?? "the town"}`, note, null);
  }
}
const find = (keep) => {
  const found = entries.find(keep);
  if (!found) throw new Error(`no entry ${keep}`);
  return found;
};
const notes = (e, ...readers) => readers.map((reader) => knewNote(e, reader)?.text ?? null);
const toAll = find((e) => e.kind === "speech" && !e.payload.private);
const byName = find((e) => e.kind === "speech" && e.payload.private);
const sale = find((e) => e.kind === "move" && e.payload.reason === "buy" && e.actor === "Mei" && e.payload.seller === "Olga");
const arrival = find((e) => e.kind === "arrive" && e.actor === "Jonas" && e.audience.includes("Olga"));
const crowd = find((e) => e.kind === "arrive" && e.actor === "Tomas" && e.audience.length === 5);
check("a remark to everyone, by the town, the hearer and the speaker", notes(toAll, null, "Mei", "Tomas"), [null, "Tomas knew too", "Mei knew too"]);
check("a remark to everyone heard by two", notes({ ...toAll, audience: ["Mei", "Aisha"] }, null, "Mei"), [null, "Tomas and Aisha knew too"]);
check("a remark said by name is not private", notes(byName, null, "Tomas", "Mei"), [null, "Mei knew too", "Tomas knew too"]);
check("a sale told to the seller", notes(sale, null, "Olga", "Mei"), [null, "Mei knew too", "Olga knew too"]);
check("an arrival told to those present", notes(arrival, null, "Olga", "Jonas"), [null, "Jonas knew too", "Olga knew too"]);
check("an arrival told to many", [knewNote(crowd, "Olga").text, knewNote(crowd, "Olga").title], ["4 others knew too", "Tomas, Jonas, Lucia and Vera knew of this too"]);
check("a waking, by the waker and by another", notes(find((e) => e.kind === "wake" && e.actor === "Olga"), "Olga", "Mei", null), ["only you knew", "only Olga knew", "only Olga knew"]);

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
check("eggs sold for the kitchen, too little to tax", words("Jonas", "Olga", (m) => m.item === "eggs"), "sold Jonas 2 units of eggs for the kitchen for $4 at the store");
check("vegetables sold for the kitchen, the tax withheld", words("Jonas", "Olga", (m) => m.item === "vegetables"), "sold Jonas 5 units of vegetables for the kitchen for $20 at the store, of which $2 in tax");
check("vegetables bought for the kitchen, by the chef", words("Jonas", "Jonas", (m) => m.item === "vegetables"), "bought 5 units of vegetables for the kitchen for $20 at the store");
check("a dish served, by the chef", words("Mei", "Jonas", (m) => m.reason === "buy" && m.source === "portions"), "served Mei an omelette for $10 at the café on the square, of which $1 in tax");

// Money paid for work, a grant and the midnight statement.
const marker = (name, kind) => lane(name).markers.find((m) => m.kind === kind);
const said = (name, kind, who) => describeMarker(marker(name, kind), name, who, world);
check("a programmer's share of a client's payment", said("Mei", "service", "Mei")[0], "was paid $40 by the client for task 1, accepted, of which $4 in tax");
check("the team leader's share", said("Tomas", "service", "Tomas")[0], "was paid $10, the team leader's share of the client's payment for task 1, of which $1 in tax");
check("a fee, by the doctor", said("Lucia", "examination", "Lucia")[0], "examined Mei for $10, of which $1 in tax");
check("a fee, by the patient", said("Lucia", "examination", "Mei")[0], "was examined by Lucia for $10");
check("a grant, by the mayor", said("Vera", "grant", "Vera"), ["granted Aisha $5 from the treasury", "For the rent."]);
check("a grant, by the one granted", said("Vera", "grant", "Aisha"), ["was granted $5 from the treasury by Vera", "For the rent."]);
check("a grant concerns the one granted", [concerns(marker("Vera", "grant"), "Vera", "Aisha"), concerns(marker("Vera", "grant"), "Vera", "Mei")], [true, false]);
check("a statement with rent owed", said("Aisha", "settlement", "Aisha")[1].split(" Ate ")[0], "0.0 h at work. Rent $15 paid, $5 owed to the treasury.");
check("a statement with a salary", said("Vera", "settlement", "Vera")[1].split(" h at work. ")[1].split(" Ate ")[0], "Salary $30 paid. Rent $30 paid.");

// What lies at each place, and the kitchen's portions, from the holders.
check("what lies at Mei's home now", itemsBrief(world, lyingAt(timeline, "mill-street-house", timeline.now)), "1 bread");
check("nothing lies at the store now", lyingAt(timeline, "store", timeline.now), {});
check("the portions before Mei came for her omelette", shopsAt(timeline, at(10, 59)).portions, { omelette: 1, soup: 2 });
check("the soup left after the chef's", shopsAt(timeline, at(11)).portions, { soup: 1 });

console.log(JSON.stringify({ run: runPath, checks, failures: failures.slice(0, 10), failed: failures.length }));
process.exit(failures.length ? 1 : 0);
