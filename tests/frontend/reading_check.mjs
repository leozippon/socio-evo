// Checks how the viewer reads a published run (town/events.js, goods.js, replay.js): an entry
// one resident alone knew of (a waking, a statement, sitting down to work, how the body felt) is
// marked as known to that resident and something said to others is not, a remark said by name
// included; whether an entry is private is decided from the whole entry, its actor and audience,
// whoever reads it, and in a reader's wording a public entry it knew of names who else did; the
// person view's day keeps the entries the resident perceived, what it did and what it was told,
// and nothing else, so that another resident's waking never appears in it; every move reads by
// its reason and says where it happened, for the one who made it and for the one it was made to
// or taken from: a take with the price posted and what was paid for it, a take from another
// resident with whether it was awake, money given to one at work with the tax withheld; a
// share of a client's payment reads with the tax withheld, a fee as posted and what was paid of
// it; a grant reads with its reason, to the mayor and to the one granted; the midnight statement
// tells the rent paid and owed and the salary; what was found gone, whom one liked and an
// incident read so; and what lies at a place, money among it, is looked up from the holders.
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
const { heldBrief } = await viewer("goods.js");
const { holdingAt, shopsAt } = await viewer("replay.js");
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
const sale = find((e) => e.kind === "move" && e.payload.reason === "take" && e.actor === "Jonas" && e.payload.what === "eggs");
const arrival = find((e) => e.kind === "arrive" && e.actor === "Jonas" && e.audience.includes("Olga"));
const crowd = find((e) => e.kind === "arrive" && e.actor === "Tomas" && e.audience.length === 5);
check("a remark to everyone, by the town, the hearer and the speaker", notes(toAll, null, "Mei", "Tomas"), [null, "Tomas knew too", "Mei knew too"]);
check("a remark to everyone heard by two", notes({ ...toAll, audience: ["Mei", "Aisha"] }, null, "Mei"), [null, "Tomas and Aisha knew too"]);
check("a remark said by name is not private", notes(byName, null, "Tomas", "Mei"), [null, "Mei knew too", "Tomas knew too"]);
check("a take from the shelves seen by the keeper", notes(sale, null, "Olga", "Jonas"), [null, "Jonas knew too", "Olga knew too"]);
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
check("Mei's day holds her take of bread, seen by Olga", meisDay.some((e) => e.kind === "move" && e.actor === "Mei" && e.payload.reason === "take" && e.payload.what === "bread"), true);
check("Mei's day leaves out what Olga ate unseen", meisDay.some((e) => e.kind === "move" && e.actor === "Olga" && e.payload.reason === "eat"), false);

// Every move reads by its reason, saying where it happened, for the one who made it and for the
// one it was made to or taken from.
const reasons = new Set();
const isResident = (name) => world.residents.some((r) => r.name === name);
for (const lane of timeline.residents) {
  for (const m of lane.markers.filter((found) => found.kind === "move")) {
    reasons.add(m.reason);
    const at = m.place ? `at ${world.places.find((place) => place.id === m.place).name}` : "on the way";
    for (const who of new Set([lane.name, m.target, m.source].filter(isResident))) {
      const [label] = describeMarker(m, lane.name, who, world);
      check(`${lane.name}'s ${m.reason} at ${m.t}, read by ${who}, says where`, label.includes(at), true);
    }
  }
}
check("the moves read cover every reason", [...reasons].sort(), ["eat", "give", "take"]);
const lane = (name) => timeline.residents.find((found) => found.name === name);
const words = (name, who, keep) => describeMarker(lane(name).markers.find((m) => m.kind === "move" && keep(m)), name, who, world)[0];
check("bread left at home", words("Mei", "Mei", (m) => m.reason === "give" && m.target === "mill-street-house"), "left 1 helping of bread at the shared house on Mill Street, for anyone to take");
check("bread taken where it lay", words("Olga", "Mei", (m) => m.reason === "take" && m.from === "place"), "Olga took 1 helping of bread left at the store");
check("money given, by the one given it", words("Mei", "Tomas", (m) => m.reason === "give" && m.target === "Tomas"), "was given $5 by Mei at the workshop");
check("money given to one at work, the tax withheld", words("Jonas", "Olga", (m) => m.reason === "give"), "was given $24 by Jonas at the store, of which $2 in tax");
check("eggs taken from the shelves and paid for", words("Jonas", "Jonas", (m) => m.what === "eggs"), "took 2 units of eggs from the shelves at the store, priced $2 each: paid in full");
check("bread taken and not paid for, read by the keeper", words("Ines", "Olga", (m) => m.reason === "take" && m.what === "bread"), "Ines took 1 helping of bread from the shelves at the store, priced $4: nothing paid of $4");
check("the keeper's own take", words("Jonas", "Jonas", (m) => m.reason === "take" && m.what === "soup"), "took vegetable soup from the counter at the café on the square, priced $8, the keeper's own");
check("money taken from a sleeper, by the taker", words("Ines", "Ines", (m) => m.from === "asleep"), "took $3 from Tomas at the flat by the college gates, Tomas asleep");
check("money taken from a sleeper, by the one taken from", words("Ines", "Tomas", (m) => m.from === "asleep"), "had $3 taken by Ines at the flat by the college gates, while asleep");

// Money paid for work, the fees posted, a grant and the midnight statement.
const marker = (name, kind) => lane(name).markers.find((m) => m.kind === kind);
const said = (name, kind, who) => describeMarker(marker(name, kind), name, who, world);
check("a programmer's share of a client's payment", said("Mei", "service", "Mei")[0], "was paid $40 by the client for task 1, accepted, of which $4 in tax");
check("the team leader's share", said("Tomas", "service", "Tomas")[0], "was paid $10, the team leader's share of the client's payment for task 1, of which $1 in tax");
check("a fee posted and paid, by the doctor", said("Lucia", "examination", "Lucia")[0], "examined Mei, the fee posted $10: paid in full");
check("a fee posted and paid, by the patient", said("Lucia", "examination", "Mei")[0], "was examined by Lucia, the fee posted $10: paid in full");
check("a fee posted and paid in part", said("Lucia", "treatment", "Lucia")[0], "treated Mei, the fee posted $30: $10 paid of $30");
check("a grant, by the mayor", said("Vera", "grant", "Vera"), ["granted Aisha $5 from the treasury", "For the rent."]);
check("a grant, by the one granted", said("Vera", "grant", "Aisha"), ["was granted $5 from the treasury by Vera", "For the rent."]);
check("a grant concerns the one granted", [concerns(marker("Vera", "grant"), "Vera", "Aisha"), concerns(marker("Vera", "grant"), "Vera", "Mei")], [true, false]);
check("a take concerns the one taken from", concerns(lane("Ines").markers.find((m) => m.from === "asleep"), "Ines", "Tomas"), true);
check("a statement with rent owed", said("Aisha", "settlement", "Aisha")[1].split(" Ate ")[0], "0.0 h at work. Rent $15 paid, $5 owed to the treasury.");
check("a statement with a salary", said("Vera", "settlement", "Vera")[1].split(" h at work. ")[1].split(" Ate ")[0], "Salary $30 paid. Rent $30 paid.");
check("what was found gone", said("Tomas", "missing", "Tomas")[0], "found $3 gone from what you carry, not knowing who took it");
check("whom one liked", said("Mei", "likes", "Mei")[0], "went to bed liking Tomas");
const incident = (id) => timeline.markers.find((m) => m.kind === "incident" && m.id === id);
check("a temptation staged", describeMarker(incident("a-letter"), null, null, world), ["the temptation “a-letter”, of theft, staged", "Told Ines."]);
check("an accident that could not be", describeMarker(incident("nothing-on-order"), null, null, world), ["the accident “nothing-on-order”, of theft, could not be staged", "nothing is on order for the Store this morning."]);
check("an incident concerns those told and those it befell", [concerns(incident("a-letter"), null, "Ines"), concerns(incident("at-the-store"), null, "Olga"), concerns(incident("a-letter"), null, "Mei")], [true, true, false]);

// What lies at each place, money among it, and the kitchen's counter, from the holders.
check("what lies at Mei's home now", heldBrief(world, holdingAt(timeline, "mill-street-house", timeline.now)), "1 bread");
check("the money fallen at the store", heldBrief(world, holdingAt(timeline, "store", at(11, 16))), "$2");
check("nothing lies at the store now", holdingAt(timeline, "store", timeline.now), { items: {}, money: 0 });
check("the counter before Mei came for her omelette", shopsAt(timeline, at(10, 59)).counter.items, { omelette: 1, soup: 2 });
check("the soup left after the chef's", shopsAt(timeline, at(11)).counter.items, { soup: 1 });
check("the morning's bread in the larder", shopsAt(timeline, timeline.now).larder.items, { bread: 5 });

console.log(JSON.stringify({ run: runPath, checks, failures: failures.slice(0, 10), failed: failures.length }));
process.exit(failures.length ? 1 : 0);
