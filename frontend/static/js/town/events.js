// What an entry of the world log means to a reader: who it concerns, a line of text for it, and
// how a run of entries folds into one; and what a marker of the timeline says in words. Shared
// by the feed, the chronicle, the work panel, the lanes and the person view.
//
// A line reads as the town's people read it: an entry's own text, in the town's words. Where a
// resident is chosen as the reader, what that resident was told reads in its own wording, as the
// log keeps it ("You claimed task 13"): a private remark shows its words to those who heard it
// and is something said out of earshot to a bystander, because that is what each was told.

import { hhmm, secondOfDay } from "../clock.js";
import { fmt, h } from "../dom.js";
import { icon } from "../icons.js";

/** Entries that frame the day rather than happen in it. */
export const STRUCTURE = new Set(["checkpoint", "resume"]);

/** The workspace entries, which fold into one line per spell of work. */
export const WORKSPACE = new Set(["command", "file_read", "file_write"]);

/** Whether `name` was told the entry: in its own wording, or as one of the audience. */
export const witnessed = (entry, name) => Boolean(entry.personal?.[name]) || entry.audience.includes(name);

/** The residents an entry concerns: its actor, its audience and the names its payload holds. */
export function involved(entry) {
  const p = entry.payload ?? {};
  const names = new Set();
  if (entry.actor) names.add(entry.actor);
  for (const name of entry.audience) names.add(name);
  for (const key of ["to", "from", "seller", "chef", "patient", "holder"]) {
    const value = p[key];
    if (typeof value === "string") names.add(value);
    else if (Array.isArray(value)) for (const name of value) if (typeof name === "string") names.add(name);
  }
  return [...names];
}

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
  gift: "coin",
  message: "speech",
  sale: "store",
  served: "meal",
  order: "truck",
  delivery: "truck",
  cook: "pot",
  price: "tag",
  examination: "clinic",
  treatment: "pill",
  report: "report",
  announcement: "megaphone",
  move_in: "home",
  wage: "coin",
  settlement: "book",
  illness: "thermometer",
  condition: "eye",
  bedridden: "bed",
  recovered: "heart",
  sleep: "book",
  fell_asleep: "clock",
  forced_sleep: "alert",
  checkpoint: "flag",
  resume: "flag",
};
export const iconFor = (entry) => (entry.kind === "speech" && entry.payload?.private ? "lock" : entry.kind === "verdict" ? (entry.payload.resolved ? "check" : "cross") : ICONS[entry.kind] ?? "spark");

/** The tone of an entry: good news, bad news, or none. */
export function tone(entry) {
  const p = entry.payload ?? {};
  switch (entry.kind) {
    case "verdict":
      return p.resolved ? "good" : "serious";
    case "service":
    case "gift":
    case "recovered":
      return "good";
    case "abandon":
    case "illness":
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
 * The line of text the feed shows for an entry, as a node. `m` gives the cast and the chosen
 * reader (`reader`, or null for the town's wording).
 */
export function line(entry, m) {
  const text = textFor(entry, m.reader);
  const spoken = entry.kind === "speech" && entry.payload.private ? h("span", { class: "private-tag" }, icon("lock", 11), "privately ") : null;
  return h("span", { class: "feed-text" }, spoken, m.cast.mention(text));
}

/** What an entry carries beyond its line: a command's output, a journal entry. */
export function detail(entry) {
  const p = entry.payload ?? {};
  if (entry.kind === "command" && p.output_tail?.trim()) return ["The end of its output", p.output_tail.trim(), true];
  if (entry.kind === "sleep" && p.journal) return ["Journal", p.journal, false];
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

/** What a sum per service was for, in words. */
const SERVICE = { task: (m) => `task ${m.task}, accepted`, team: (m) => `the team's task ${m.task}, accepted`, sale: () => "a sale", dish: () => "a dish served", patient: () => "a patient seen" };

/** A quantity of a good in a few words: `2 × bread`, `a phone`. */
const some = (m) => `${m.quantity > 1 ? `${m.quantity} × ` : ""}${m.name}`;

/** Units of goods by id in a few words: `10 bread, 12 vegetables`. */
const goodsIn = (items) => Object.entries(items).map(([id, units]) => `${units} ${id}`).join(", ");

/** The body's numbers an examination told, in a line. */
const numbers = (m) => `Food ${fmt.int(Math.round(m.satiety))}, energy ${fmt.int(Math.round(m.energy))}, health ${fmt.int(Math.round(m.health))} of 100${m.ill ? `; ill, ${fmt.plural(m.ill, "night")} to go` : ""}.`;

/**
 * A marker of the timeline in words, as [label, text]: `by` is the resident whose lane holds it
 * (null for a marker of no resident), `who` the resident the words are for (its own deeds read
 * without a name).
 */
export function describeMarker(m, by, who) {
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
      return [`${subject}was paid ${fmt.money(m.paid)} for ${SERVICE[m.for]?.(m) ?? m.for}${m.owed ? `; the fund owes the other ${fmt.money(m.owed)}` : ""}`];
    case "abandon":
      return [`${subject}gave up task ${m.task}`];
    case "gift":
      return own ? [`gave ${m.to} ${given(m)}`] : [`received ${given(m)} from ${by}`];
    case "message":
      return own ? [`wrote to ${m.to}`, m.text] : [`received a message from ${by}`, m.text];
    case "sale":
      if (!own && who === m.seller) return [`sold ${by} ${some(m)}${m.kitchen ? " for the kitchen" : ""} for ${fmt.money(m.amount)}`];
      return [`${subject}bought ${some(m)}${m.kitchen ? " for the kitchen" : ""} for ${fmt.money(m.amount)}`];
    case "served":
      if (!own && who === m.chef) return [`served ${by} ${m.name} for ${fmt.money(m.amount)}`];
      return [`${subject}had ${m.name} for ${fmt.money(m.amount)}, served by ${m.chef}`];
    case "order":
      return [`${subject}ordered ${some(m)} from the supplier for ${fmt.money(m.amount)}, to arrive at ${hhmm(secondOfDay(m.arrives))}`];
    case "cook":
      return [`${subject}cooked ${fmt.plural(m.portions, "portion")} of ${m.name}`, `From ${goodsIn(m.used)}.`];
    case "price":
      return [`${subject}set the price of ${m.name} to ${fmt.money(m.price)}, from ${fmt.money(m.before)}`];
    case "examination":
      if (!own && who === m.patient) return [`was examined by ${by} for ${fmt.money(m.fee)}`, numbers(m)];
      return [`${subject}examined ${m.patient === by ? "themself" : m.patient} for ${fmt.money(m.fee)}`, numbers(m)];
    case "treatment": {
      const restored = `Health ${fmt.int(Math.round(m.before))} to ${fmt.int(Math.round(m.health))} of 100${m.ill ? ", the illness ended" : ""}${m.bedridden ? ", out of bed" : ""}.`;
      if (!own && who === m.patient) return [`was treated by ${by} for ${fmt.money(m.fee)}`, restored];
      return [`${subject}treated ${m.patient === by ? "themself" : m.patient} for ${fmt.money(m.fee)}`, restored];
    }
    case "report":
      return [`${subject}read the town's report`];
    case "announcement":
      return [`${subject}announced`, m.text];
    case "illness":
      return [`${subject}fell ill`, `For ${fmt.plural(m.nights, "night")} at most, unless treated.`];
    case "recovered":
      return [`${subject}${m.bedridden ? "left the bed, treated" : m.treated ? "was well again, treated" : "was well again: the illness passed"}`];
    case "bedridden":
      return [`${subject}${m.carried ? "was carried home to bed" : "took to bed"}, too ill to go on`];
    case "wage": {
      const owing = [m.owed ? `the fund owes ${fmt.money(m.owed)}` : null, m.arrears ? `owes ${fmt.money(m.arrears)} of rent` : null].filter(Boolean);
      return [`${subject}was paid ${fmt.money(m.paid)} at midnight for ${fmt.num(m.hours, 1)} h at work`, `Wages ${fmt.money(m.wages)}, rent ${fmt.money(m.rent)}${m.charges ? `, daily charges ${fmt.money(m.charges)}` : ""}${owing.length ? `; ${owing.join(", ")}` : ""}.`];
    }
    case "settlement": {
      const night = Object.entries(m.night ?? {}).map(([cause, change]) => `${fmt.signed(change)} ${cause.replaceAll("_", " ")}`);
      return [`${subject}had the midnight statement`, `Ate ${m.nourishment ? `${fmt.int(m.nourishment)}% of a day's food` : "nothing"}. Food in the body ${fmt.int(Math.round(m.satiety))}, energy ${fmt.int(Math.round(m.energy))}, health ${fmt.int(Math.round(m.health))} of 100${night.length ? ` (${night.join(", ")})` : ""}${m.ill ? `; ill, ${fmt.plural(m.ill, "night")} to go` : ""}.`];
    }
    case "move_in":
      return [`${subject}moved house, into ${m.to.replaceAll("-", " ")}`];
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

/** What a gift marker gave: money, or a thing or helpings of a stock (`2 × bread`). */
export const given = (m) => (m.item ? some(m) : fmt.money(m.amount));

/** Whether a marker on `by`'s lane (by null: a marker of no resident) concerns `who` too. */
export function concerns(m, by, who) {
  if (by === who) return true;
  switch (m.kind) {
    case "speech":
      return m.to.includes(who);
    case "gift":
    case "message":
      return m.to === who;
    case "assign":
      return m.to === who || m.from === who;
    case "sale":
      return m.seller === who;
    case "served":
      return m.chef === who;
    case "examination":
    case "treatment":
      return m.patient === who;
    case "task_withdrawn":
      return m.holder === who;
    default:
      return false;
  }
}
