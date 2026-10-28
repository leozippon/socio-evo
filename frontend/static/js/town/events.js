// What an entry of the world log means to a reader: who it concerns, a line of text for it, and
// how a run of entries folds into one. Shared by the feed, the moment panel, the chronicle, the
// work panel and the person view.
//
// A line reads as the town's people read it: an entry's own text, in the town's words. Where a
// resident is chosen as the reader, what that resident was told reads in its own wording, as the
// log keeps it ("You claimed task 13"): a private remark shows its words to those who heard it
// and is something said out of earshot to a bystander, because that is what each was told.

import { hhmm, secondOfDay } from "../clock.js";
import { fmt, h } from "../dom.js";
import { icon } from "../icons.js";

/** Entries that frame the day rather than happen in it. */
export const STRUCTURE = new Set(["checkpoint", "resume", "board_posted"]);

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
  for (const key of ["to", "sent_out"]) {
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

const ICONS = {
  wake: "clock",
  depart: "chevron",
  arrive: "home",
  time: "clock",
  board_posted: "board",
  start_work: "code",
  leave_work: "chevronLeft",
  claim: "board",
  command: "code",
  file_read: "book",
  file_write: "code",
  submission: "check",
  verdict: "eye",
  payment: "coin",
  abandon: "cross",
  expiry: "clock",
  workspace_closed: "lock",
  speech: "speech",
  leave_conversation: "chevronLeft",
  conversation_end: "chevronLeft",
  gift: "coin",
  skill_shared: "spark",
  message: "speech",
  purchase: "coin",
  move_in: "home",
  settlement: "coin",
  condition: "eye",
  death: "alert",
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
    case "payment":
    case "gift":
    case "skill_shared":
      return "good";
    case "abandon":
      return "serious";
    case "expiry":
    case "forced_sleep":
    case "death":
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

/** What an entry carries beyond its line: a command's output, a journal entry, a rating's reason. */
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

/**
 * A marker of the timeline in words, as [label, text]: `by` is the resident whose lane holds it,
 * `who` the resident the words are for (its own deeds read without a name).
 */
export function describeMarker(m, by, who) {
  const own = by === who;
  const names = (list) => list.join(", ");
  switch (m.kind) {
    case "speech": {
      const how = m.private ? "privately " : "";
      return [own ? `said ${how}to ${names(m.to)}` : `${by} said ${how}to ${names(m.to)}`, m.text];
    }
    case "claim":
      return [`claimed task ${m.task} (${m.instance_id})`];
    case "submission": {
      const task = `task ${m.task}`;
      if (m.resolved === undefined) return [`handed in ${task}, awaiting the verdict`];
      const counts = `fail-to-pass ${m.fail_to_pass.join("/")}, pass-to-pass ${m.pass_to_pass.join("/")}`;
      return [`handed in ${task}: ${m.resolved ? "accepted" : `not accepted (${m.status})`}`, counts];
    }
    case "payment":
      return [`was paid ${fmt.money(m.amount)} for task ${m.task}`];
    case "abandon":
      return [`gave up task ${m.task}`];
    case "expiry":
      return [`lost task ${m.task}: the claim ran out unpaid`];
    case "gift":
      return own ? [`gave ${m.to} ${given(m)}`] : [`received ${given(m)} from ${by}`];
    case "skill_shared":
      return own ? [`passed ${m.to} a copy of ${m.file}`] : [`received a copy of ${m.file} from ${by}`];
    case "message":
      return own ? [`wrote to ${m.to}`, m.text] : [`received a message from ${by}`, m.text];
    case "purchase":
      return [`bought ${m.quantity > 1 ? `${m.quantity} × ` : ""}${m.name} for ${fmt.money(m.amount)}`];
    case "settlement": {
      const night = Object.entries(m.night ?? {}).map(([cause, change]) => `${fmt.signed(change)} ${cause.replaceAll("_", " ")}`);
      return [`was charged ${fmt.money(m.rent)} rent${m.fees ? ` and ${fmt.money(m.fees)} in daily charges` : ""} at midnight`, `Ate ${m.nourishment ? `${fmt.int(m.nourishment)}% of a day's food` : "nothing"}. Food in the body ${fmt.int(Math.round(m.satiety))}, energy ${fmt.int(Math.round(m.energy))}, health ${fmt.int(Math.round(m.health))} of 100${night.length ? ` (${night.join(", ")})` : ""}.`];
    }
    case "move_in":
      return [`moved house, into ${m.to.replaceAll("-", " ")}`];
    case "journal":
      return [`went to bed until ${hhmm(secondOfDay(m.wake))} and wrote the journal of day ${m.day}`, m.text];
    case "forced_sleep":
      return [`fell asleep at the forced hour without going to bed, to wake at ${hhmm(secondOfDay(m.wake))}`];
    case "condition":
      return [`is ${m.band}`];
    case "death":
      return ["died"];
    default:
      return [m.kind.replaceAll("_", " ")];
  }
}

/** What a gift marker gave: money, or a thing or helpings of a stock (`2 × groceries`). */
export const given = (m) => (m.item ? `${m.quantity > 1 ? `${m.quantity} × ` : ""}${m.name}` : fmt.money(m.amount));

/** Whether a marker on `by`'s lane concerns `who` too. */
export const concerns = (m, by, who) => by === who || (m.kind === "speech" && m.to.includes(who)) || ((m.kind === "gift" || m.kind === "skill_shared" || m.kind === "message") && m.to === who);
