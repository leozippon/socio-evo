// What an entry of the world log means to a reader: who it concerns, a line of text for it, and
// how a run of entries folds into one; and what a marker of the timeline says in words. Shared
// by the feed, the chronicle, the work panel, the lanes and the person view.
//
// A line reads as the town's people read it: an entry's own text, in the town's words. Where a
// resident is chosen as the reader, what that resident was told reads in its own wording, as the
// log keeps it ("You claimed task 13"): a remark said by name shows its words to those it was said
// to and is something said out of earshot to a bystander, because that is what each was told.
// Those who knew of an entry are its actor and its audience together, and they alone decide
// whether it was private, wherever it is shown: an entry only one resident knew of (its waking,
// its body, its sitting down to work, its statement) says so, and any other is public, a remark
// said by name included; in a reader's wording, an entry the reader knew of says who else did.
// What a resident perceived is what it knew of: what it did and what the world told it.

import { hhmm, secondOfDay } from "../clock.js";
import { fmt, h } from "../dom.js";
import { amountOf } from "../goods.js";
import { icon } from "../icons.js";
import { COUNTER, LARDER, MONEY, SHELVES } from "../replay.js";

/** Entries that frame the day rather than happen in it. */
export const STRUCTURE = new Set(["checkpoint", "resume"]);

/** The workspace entries, which fold into one line per spell of work. */
export const WORKSPACE = new Set(["command", "file_read", "file_write"]);

/** Whether `name` was told the entry: in its own wording, or as one of the audience. */
export const witnessed = (entry, name) => Boolean(entry.personal?.[name]) || entry.audience.includes(name);

/** The residents who knew of an entry: its actor and its whole audience together, the actor first. */
export const knewOf = (entry) => [...new Set([entry.actor, ...entry.audience].filter(Boolean))];

/** Whether `name` perceived the entry, that is knew of it: it did it, or the world told it. */
export const perceived = (entry, name) => knewOf(entry).includes(name);

/**
 * The one resident who knew of an entry when nobody else did: the actor or the one told, alone,
 * whatever the actor field holds (a waking or a statement told to its resident, sitting down to
 * work or eating told to nobody, a delivery told to the shopkeeper); null when two or more knew
 * of it, or nobody did.
 */
export function knownOnlyTo(entry) {
  const knew = knewOf(entry);
  return knew.length === 1 ? knew[0] : null;
}

/** Names in a few words: `Mei`, `Mei and Tomas`, `Mei, Tomas and Olga`. */
const listed = (names) => (names.length > 1 ? `${names.slice(0, -1).join(", ")} and ${names.at(-1)}` : names.join(""));

/**
 * What a line says of who knew of an entry, for `reader` (null for the town's wording), as
 * `{private, text, title}`: private, when one resident alone knew of it; else, when the reader
 * knew of it, who else did; null otherwise.
 */
export function knewNote(entry, reader) {
  const alone = knownOnlyTo(entry);
  if (alone) return { private: true, text: `only ${alone === reader ? "you" : alone} knew`, title: `Nobody but ${alone} knew of this` };
  const knew = knewOf(entry);
  if (!reader || !knew.includes(reader)) return null;
  const others = knew.filter((name) => name !== reader);
  return { private: false, text: `${others.length > 3 ? `${others.length} others` : listed(others)} knew too`, title: `${listed(others)} knew of this too` };
}

/** The residents an entry concerns: its actor, its audience and the names its payload holds. */
export function involved(entry) {
  const p = entry.payload ?? {};
  const names = new Set();
  if (entry.actor) names.add(entry.actor);
  for (const name of entry.audience) names.add(name);
  for (const key of ["to", "from", "source", "target", "patient", "holder", "told"]) {
    const value = p[key];
    if (typeof value === "string") names.add(value);
    else if (Array.isArray(value)) for (const name of value) if (typeof name === "string") names.add(name);
  }
  return [...names];
}

/** The harm category of an incident, in plain words. */
export const CATEGORIES = {
  "scam-deceit": "fraud and scams",
  "theft-economic-harm": "theft",
  privacy: "privacy",
  "harassment-defamation": "harassment and defamation",
  "false-information": "false information",
  "endangering-health": "endangering health",
  "expert-advice": "unqualified expert advice",
  "misuse-of-office": "misuse of office",
  "unauthorised-access": "unauthorised access",
};

const words = (key) => {
  const text = String(key ?? "entry").replaceAll("_", " ");
  return text[0].toUpperCase() + text.slice(1);
};

/** The icon of each kind of entry and marker. */
export const ICONS = {
  wake: "clock",
  depart: "chevron",
  arrive: "home",
  time: "clock",
  task_arrived: "inbox",
  task_withdrawn: "cross",
  start_work: "code",
  leave_work: "chevronLeft",
  claim: "board",
  assign: "handoff",
  command: "code",
  file_read: "book",
  file_write: "code",
  submission: "check",
  verdict: "eye",
  service: "coin",
  abandon: "cross",
  workspace_closed: "lock",
  speech: "speech",
  leave_conversation: "chevronLeft",
  conversation_end: "chevronLeft",
  message: "speech",
  move: "coin",
  missing: "eye",
  order: "truck",
  delivery: "truck",
  perished: "clock",
  cook: "pot",
  price: "tag",
  examination: "clinic",
  treatment: "pill",
  announcement: "megaphone",
  grant: "coin",
  move_in: "home",
  settlement: "book",
  illness: "thermometer",
  condition: "eye",
  bedridden: "bed",
  recovered: "heart",
  sleep: "book",
  likes: "people",
  regard: "people",
  incident: "alert",
  web_search: "ask",
  web_page: "link",
  fell_asleep: "clock",
  forced_sleep: "alert",
  checkpoint: "flag",
  resume: "flag",
};

/** The icon of a move, by what it was: eaten, money, a dish or a thing from the Store taken, a thing given or taken. */
function moveIcon(p) {
  if (p.reason === "eat") return "bowl";
  if (p.what === MONEY) return "coin";
  if (p.reason === "take" && p.source === COUNTER) return "meal";
  if (p.reason === "take" && (p.source === SHELVES || p.source === LARDER)) return "store";
  return p.reason === "give" ? "handoff" : "basket";
}

/** The icon of an entry, or of a marker given as `{kind, payload: marker}`. */
export const iconFor = (entry) => (entry.kind === "move" ? moveIcon(entry.payload) : entry.kind === "verdict" ? (entry.payload.resolved ? "check" : "cross") : ICONS[entry.kind] ?? "spark");

/** The tone of an entry: good news, bad news, or none. */
export function tone(entry) {
  const p = entry.payload ?? {};
  switch (entry.kind) {
    case "verdict":
      return p.resolved ? "good" : "serious";
    case "service":
    case "grant":
    case "recovered":
      return "good";
    case "move":
      // A marker's take says where it took from and what was paid; an entry's says neither.
      if (p.from === "awake" || p.from === "asleep") return "critical";
      return { unpaid: "serious", underpaid: "warn" }[p.status] ?? null;
    case "examination":
    case "treatment":
      return { unpaid: "serious", underpaid: "warn" }[p.status] ?? null;
    case "abandon":
    case "illness":
    case "missing":
      return "serious";
    case "task_withdrawn":
    case "forced_sleep":
    case "bedridden":
      return "critical";
    case "condition":
      return p.lowest ? "warn" : null;
    case "command":
      return p.exit_code === 0 || p.exit_code === undefined ? null : "warn";
    default:
      return null;
  }
}

/** The icon for a line, coloured by tone through its class. */
export const glyph = (entry) => h("span", { class: `ev-icon${tone(entry) ? ` tone-${tone(entry)}` : ""}` }, icon(iconFor(entry), 14));

export const clockOf = (entry) => hhmm(secondOfDay(entry.sim_time));

/** The text of an entry for a reader: its own wording where the reader was told it, else the town's. */
export const textFor = (entry, reader) => (reader && entry.personal?.[reader]) || entry.text || [entry.actor, words(entry.kind).toLowerCase()].filter(Boolean).join(" ");

/**
 * The line of text the feed shows for an entry, as a node, with what it says of who knew of it
 * (`knewNote`). `m` gives the cast and the chosen reader (`reader`, or null for the town's wording).
 */
export function line(entry, m) {
  const note = knewNote(entry, m.reader);
  const tag = note ? h("span", { class: note.private ? "private-tag" : "knew-tag", title: note.title }, note.private ? icon("lock", 11) : null, note.text) : null;
  return h("span", { class: "feed-text" }, tag, personTag(entry, m.cast), m.cast.mention(textFor(entry, m.reader)));
}

/** A take from another resident told apart in a line: in its sight, or while it slept, which the audience tells (everyone there and awake). */
function personTag(entry, cast) {
  const p = entry.payload ?? {};
  if (entry.kind !== "move" || p.reason !== "take" || !cast.has(p.source)) return null;
  const asleep = !entry.audience.includes(p.source);
  return h("span", { class: "took-tag", title: `Taken from what ${p.source} carried${asleep ? ", while asleep" : ", in sight"}` }, asleep ? `from ${p.source}, asleep` : `from ${p.source}`);
}

/** What an entry carries beyond its line: a command's output, a journal entry, the address of a page read. */
export function detail(entry) {
  const p = entry.payload ?? {};
  if (entry.kind === "command" && p.output_tail?.trim()) return ["The end of its output", p.output_tail.trim(), true];
  if (entry.kind === "sleep" && p.journal) return ["Journal", p.journal, false];
  if (entry.kind === "web_page") return ["The address", [p.url, p.final && p.final !== p.url ? `read as ${p.final}` : null].filter(Boolean).join("\n"), true];
  return null;
}

/**
 * The entries as feed items: a single entry, or a spell of workspace entries (commands, files
 * read and written) by one resident on one task folded into a group with a summary.
 */
export function feedItems(entries) {
  const items = [];
  const open = new Map(); // actor -> its spell in progress, which other residents' entries may interleave
  for (const entry of entries) {
    const spell = open.get(entry.actor);
    if (WORKSPACE.has(entry.kind)) {
      if (spell && spell.task === entry.payload.task && entry.sim_time - spell.events.at(-1).sim_time <= SPELL_GAP) {
        spell.events.push(entry);
        continue;
      }
      const started = { spell: true, actor: entry.actor, task: entry.payload.task, time: entry.sim_time, events: [entry] };
      open.set(entry.actor, started);
      items.push(started);
    } else {
      if (entry.actor) open.delete(entry.actor);
      items.push({ spell: false, time: entry.sim_time, events: [entry], event: entry });
    }
  }
  for (const item of items) if (item.spell) item.summary = spellSummary(item);
  return items;
}

const SPELL_GAP = 15 * 60; // seconds of silence in the workspace after which a new spell begins

function spellSummary(item) {
  const count = (kind) => item.events.filter((e) => e.kind === kind).length;
  const failed = item.events.filter((e) => e.kind === "command" && e.payload.exit_code !== 0).length;
  const parts = [];
  if (count("command")) parts.push(`${fmt.plural(count("command"), "command")}${failed ? ` (${failed} failed)` : ""}`);
  if (count("file_read")) parts.push(`${fmt.plural(count("file_read"), "file")} read`);
  if (count("file_write")) parts.push(`${fmt.plural(count("file_write"), "file")} written`);
  const last = item.events.at(-1).sim_time;
  const span = last > item.time ? `, ${hhmm(secondOfDay(item.time))}–${hhmm(secondOfDay(last))}` : "";
  return `${item.actor} worked on task ${item.task}: ${parts.join(", ")}${span}`;
}

/** The tax withheld from a payment for work, in a few words after it; nothing when none was. */
const withheld = (tax) => (tax ? `, of which ${fmt.money(tax)} in tax` : "");

/** Names in a few words, for a reader: `Mei`, `Mei and Tomas`, `nobody`. */
const named = (names) => (names.length ? listed(names) : "nobody");

/** Amounts by item id or money in words: `$3 and 1 helping of bread`. */
const amounts = (world, found) => listed(Object.entries(found).map(([id, units]) => amountOf(world, id, units)));

/** A holder other than a resident in words, where it stands: `the shelves`, `the counter`, `the larder`, or a place's name. */
const holderWords = (id, world) => ({ [SHELVES]: "the shelves", [COUNTER]: "the counter", [LARDER]: "the larder" })[id] ?? world.places.find((place) => place.id === id)?.name ?? id;

/** What was paid for a take or a service, as `analysis.measures.takes` reads it, after its line; on the day in progress it is not read yet. */
function paid(m, priced) {
  switch (m.status) {
    case "paid":
      return ": paid in full";
    case "underpaid":
      return `: ${fmt.money(m.covered)} paid of ${fmt.money(m.due)}`;
    case "unpaid":
      return `: nothing paid of ${fmt.money(m.due)}`;
    case "own":
      return ", the keeper's own";
    default:
      return priced ? "; whether it was paid for is read at the day's end" : "";
  }
}

/** A quantity of a good in a few words: `2 × bread`, `a phone`. */
const some = (m) => `${m.quantity > 1 ? `${m.quantity} × ` : ""}${m.name}`;

/** Where a marker happened: `at the store`, or `on the way` between places. */
const where = (m, world) => (m.place ? `at ${world.places.find((place) => place.id === m.place)?.name ?? m.place}` : "on the way");

/**
 * A move marker in words (see `describeMarker`): what was taken, given or eaten, from or to whom
 * or what, and where; a take with the price posted where it stood and what was paid for it, and
 * a take from another resident with whether it was awake.
 */
function moveWords(m, by, who, world) {
  const own = by === who;
  const subject = own ? "" : `${by} `;
  const at = where(m, world);
  const what = amountOf(world, m.what, m.amount);
  const person = m.from === "awake" || m.from === "asleep";
  switch (m.reason) {
    case "take": {
      if (person) {
        const how = m.from === "asleep" ? "asleep" : "awake, in sight of it";
        if (!own && who === m.source) return [`had ${what} taken by ${by} ${at}, ${m.from === "asleep" ? "while asleep" : "in sight of it"}`];
        return [`${subject}took ${what} from ${m.source} ${at}, ${m.source} ${how}`];
      }
      if (m.from === "place") return [`${subject}took ${what} left ${at}`];
      const priced = m.price !== null;
      const price = priced ? `, priced ${fmt.money(m.price)}${m.amount > 1 ? " each" : ""}` : "";
      return [`${subject}took ${what} from ${holderWords(m.source, world)} ${at}${price}${paid(m, priced)}`];
    }
    case "give":
      if (!world.residents.some((r) => r.name === m.target)) {
        const on = { [SHELVES]: "on the shelves ", [COUNTER]: "on the counter ", [LARDER]: "in the larder " }[m.target];
        return [on ? `${subject}left ${what} ${on}${at}` : `${subject}left ${what} ${at}, for anyone to take`];
      }
      if (!own && who === m.target) return [`was given ${what} by ${by} ${at}${withheld(m.tax)}`];
      return [`${subject}gave ${m.target} ${what} ${at}${withheld(m.tax)}`];
    case "eat":
      return [`${subject}ate ${what} ${at}`];
    default:
      return [`${subject}moved ${what} ${at}`];
  }
}

/** Units of goods by id in a few words: `10 bread, 12 vegetables`. */
const goodsIn = (items) => Object.entries(items).map(([id, units]) => `${units} ${id}`).join(", ");

/** The body's numbers an examination told, in a line. */
const numbers = (m) => `Food ${fmt.int(Math.round(m.satiety))}, energy ${fmt.int(Math.round(m.energy))}, health ${fmt.int(Math.round(m.health))} of 100${m.ill ? `; ill, ${fmt.plural(m.ill, "night")} to go` : ""}.`;

/**
 * What a midnight statement settled with the treasury, in a sentence or two: the hours at work, the
 * salary paid and owed, the rent and daily charges paid and what is left owing.
 */
export function midnightMoney(m) {
  const salary = m.salary || m.owed_before ? ` Salary ${fmt.money(m.salary_paid)} paid${m.owed ? `, ${fmt.money(m.owed)} owed by the treasury` : ""}.` : "";
  const due = m.rent + m.charges + m.arrears_before;
  const rent = due ? ` Rent${m.charges ? " and daily charges" : ""} ${fmt.money(m.rent_paid)} paid${m.arrears ? `, ${fmt.money(m.arrears)} owed to the treasury` : ""}.` : "";
  return `${fmt.num(m.hours, 1)} h at work.${salary}${rent}`;
}

/**
 * A marker of the timeline in words, as [label, text]: `by` is the resident whose lane holds it
 * (null for a marker of no resident), `who` the resident the words are for (its own deeds read
 * without a name), `world` the run's world, which names the places and the items.
 */
export function describeMarker(m, by, who, world) {
  const own = by === who;
  const names = (list) => list.join(", ");
  const subject = own ? "" : `${by} `;
  switch (m.kind) {
    case "speech": {
      const how = m.private ? "privately " : "";
      return [own ? `said ${how}to ${names(m.to)}` : `${by} said ${how}to ${names(m.to)}`, m.text];
    }
    case "task_arrived":
      return [`task ${m.task} (${m.repo}) came in at the Office`];
    case "task_withdrawn":
      if (m.holder && m.holder === who) return [`lost task ${m.task}: its client withdrew it`];
      return [`the client withdrew task ${m.task}${m.holder ? `, which ${m.holder} held` : ", held by nobody"}`];
    case "delivery":
      return [`the supplier delivered ${goodsIn(m.items)}`];
    case "incident": {
      const kind = `${m.type} “${m.id}”, of ${CATEGORIES[m.category] ?? m.category}`;
      if (!m.staged) return [`the ${kind}, could not be staged`, `${m.why}.`];
      return [`the ${kind}, staged`, `Told ${named(m.told)}.`];
    }
    case "perished":
      return [`${amountOf(world, m.item, m.units)} perished, gone from ${world.residents.some((r) => r.name === m.source) ? m.source : holderWords(m.source, world)}`];
    case "claim":
      return [`${subject}claimed task ${m.task} (${m.instance_id})`];
    case "assign":
      if (who === m.to) return [`was given task ${m.task} by ${by}`];
      if (who === m.from) return [`lost task ${m.task}: ${by} gave it to ${m.to}`];
      return [`${subject}gave task ${m.task} to ${m.to}${m.from ? `, taking it from ${m.from}` : ""}`];
    case "submission": {
      const task = `task ${m.task}`;
      if (m.resolved === undefined) return [`${subject}handed in ${task}, awaiting the verdict`];
      const counts = `fail-to-pass ${m.fail_to_pass.join("/")}, pass-to-pass ${m.pass_to_pass.join("/")}`;
      return [`${subject}handed in ${task}: ${m.resolved ? "accepted" : `not accepted (${m.status})`}`, counts];
    }
    case "service":
      if (m.for === "team") return [`${subject}was paid ${fmt.money(m.amount)}, the team leader's share of the client's payment for task ${m.task}${withheld(m.tax)}`];
      return [`${subject}was paid ${fmt.money(m.amount)} by the client for task ${m.task}, accepted${withheld(m.tax)}`];
    case "abandon":
      return [`${subject}gave up task ${m.task}`];
    case "message":
      return own ? [`wrote to ${m.to}`, m.text] : [`received a message from ${by}`, m.text];
    case "move":
      return moveWords(m, by, who, world);
    case "missing": {
      const from = m.holder === by ? (own ? "what you carry" : "what it carried") : holderWords(m.holder, world);
      return [`${subject}found ${amounts(world, m.gone)} gone from ${from}, not knowing who took it`];
    }
    case "likes":
      return [`${subject}went to bed liking ${named(m.names)}`];
    case "web_search":
      return [`${subject}searched the web${m.ok ? `, ${fmt.plural(m.results, "result")}` : ", which could not be made"}`, `“${m.query}”`];
    case "web_page":
      return [`${subject}read a page of the web${m.ok ? `, ${fmt.plural(m.characters, "character")}` : ", which could not be read"}`, m.url];
    case "order":
      return [`${subject}ordered ${some(m)} from the supplier for ${fmt.money(m.amount)}, to arrive at ${hhmm(secondOfDay(m.arrives))}`];
    case "cook": {
      const hands = Object.keys(m.carried).length ? `, ${goodsIn(m.carried)} of it from ${own ? "your" : "the chef's"} own hands` : "";
      return [`${subject}cooked ${fmt.plural(m.portions, "portion")} of ${m.name}`, `From ${goodsIn(m.used)}${hands}.`];
    }
    case "price":
      return [`${subject}set the price of ${m.name} to ${fmt.money(m.price)}, from ${fmt.money(m.before)}`];
    case "examination": {
      const fee = m.patient === by ? "" : `, the fee posted ${fmt.money(m.fee)}${paid(m, true)}`;
      if (!own && who === m.patient) return [`was examined by ${by}${fee}`, numbers(m)];
      return [`${subject}examined ${m.patient === by ? "themself" : m.patient}${fee}`, numbers(m)];
    }
    case "treatment": {
      const restored = `Health ${fmt.int(Math.round(m.before))} to ${fmt.int(Math.round(m.health))} of 100${m.ill ? ", the illness ended" : ""}${m.bedridden ? ", out of bed" : ""}.`;
      const fee = m.patient === by ? "" : `, the fee posted ${fmt.money(m.fee)}${paid(m, true)}`;
      if (!own && who === m.patient) return [`was treated by ${by}${fee}`, restored];
      return [`${subject}treated ${m.patient === by ? "themself" : m.patient}${fee}`, restored];
    }
    case "announcement":
      return [`${subject}announced`, m.text];
    case "grant":
      if (!own && who === m.to) return [`was granted ${fmt.money(m.amount)} from the treasury by ${by}`, m.reason];
      return [`${subject}granted ${m.to === by ? "themself" : m.to} ${fmt.money(m.amount)} from the treasury`, m.reason];
    case "illness":
      return [`${subject}fell ill`, `For ${fmt.plural(m.nights, "night")} at most, unless treated.`];
    case "recovered":
      return [`${subject}${m.bedridden ? "left the bed, treated" : m.treated ? "was well again, treated" : "was well again: the illness passed"}`];
    case "bedridden":
      return [`${subject}${m.carried ? "was carried home to bed" : "took to bed"}, too ill to go on`];
    case "settlement": {
      const night = Object.entries(m.night ?? {}).map(([cause, change]) => `${fmt.signed(change)} ${cause.replaceAll("_", " ")}`);
      return [`${subject}had the midnight statement`, `${midnightMoney(m)} Ate ${m.nourishment ? `${fmt.int(m.nourishment)}% of a day's food` : "nothing"}. Food in the body ${fmt.int(Math.round(m.satiety))}, energy ${fmt.int(Math.round(m.energy))}, health ${fmt.int(Math.round(m.health))} of 100${night.length ? ` (${night.join(", ")})` : ""}${m.ill ? `; ill, ${fmt.plural(m.ill, "night")} to go` : ""}.`];
    }
    case "move_in":
      return [`${subject}moved house, into ${world.places.find((place) => place.id === m.to)?.name ?? m.to}`];
    case "journal":
      return [`${subject}went to bed until ${hhmm(secondOfDay(m.wake))} and wrote the journal of day ${m.day}`, m.text];
    case "forced_sleep":
      return [`${subject}fell asleep at the forced hour without going to bed, to wake at ${hhmm(secondOfDay(m.wake))}`];
    case "condition":
      return [`${subject}is ${m.band}`];
    default:
      return [m.kind.replaceAll("_", " ")];
  }
}

/** Whether a marker on `by`'s lane (by null: a marker of no resident) concerns `who` too. */
export function concerns(m, by, who) {
  if (by === who) return true;
  switch (m.kind) {
    case "speech":
      return m.to.includes(who);
    case "message":
      return m.to === who;
    case "move":
      return m.target === who || m.source === who;
    case "incident":
      return m.told.includes(who) || m.effects.some((effect) => effect.who === who);
    case "grant":
      return m.to === who;
    case "assign":
      return m.to === who || m.from === who;
    case "examination":
    case "treatment":
      return m.patient === who;
    case "task_withdrawn":
      return m.holder === who;
    default:
      return false;
  }
}
