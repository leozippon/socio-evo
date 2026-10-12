// What an event means to a reader: who it concerns, whether anyone in town perceived it, and a
// line of text for it. Shared by the feed, the moment panel, the chronicle, the board and the
// person view.
//
// A line reads as the town's people read it: an event's own text, in the town's words. Where a
// resident is chosen as the reader, what that resident witnessed reads in its own wording. A
// private remark shows its words in the truth view and to those who heard it, and is "something
// said privately" to everyone else.

import { hhmm, minuteOf } from "../clock.js";
import { fmt, h } from "../dom.js";
import { icon } from "../icons.js";
import { current } from "../replay.js";
import { shortName } from "../world.js";

/** Events that frame the day rather than happen in it. */
export const STRUCTURE = new Set(["day_started", "day_ended", "scene_started", "scene_ended"]);

/** Whether no agent perceived the event: material only the researcher sees. */
export const isTruth = (event) => event.audience.length === 0 && !STRUCTURE.has(event.kind);

/** Whether the event is visible in the town's own view: someone perceived it. */
export const isPublic = (event) => event.audience.length > 0;

/** Whether `name` witnessed the event: it was told it, or it is its own deed or decision. */
export const witnessed = (event, name) => event.audience.includes(name) || (event.actor === name && (event.audience.length > 0 || event.kind === "decision"));

/** The agents an event concerns, actor first. */
export function involved(event) {
  const p = event.payload ?? {};
  const names = new Set();
  if (event.actor) names.add(event.actor);
  for (const key of ["agent", "worker", "rater", "target", "to", "from", "partner", "giver", "recipient"]) if (typeof p[key] === "string") names.add(p[key]);
  for (const key of ["order", "partners", "participants", "workers"]) if (Array.isArray(p[key])) for (const name of p[key]) if (typeof name === "string") names.add(name);
  return [...names];
}

/** What a scene is called; a kind of scene this viewer does not know is named by its kind. */
const SCENES = { work: "Work session", conversation: "Conversation", meeting: "Meeting", planning: "Everyone plans the day", review: "The evening review" };
export const sceneName = (kind) => SCENES[kind] ?? words(kind);
const words = (key) => {
  const text = String(key ?? "event").replaceAll("_", " ");
  return text[0].toUpperCase() + text.slice(1);
};

// Jobs ------------------------------------------------------------------------------------------

/** A job's name in the town: `task-8` is job 8, the number on its notice. */
export const jobName = (id) => (typeof id === "string" && /^task-\d+$/.test(id) ? `job ${id.slice(5)}` : String(id ?? "a job"));

/** The parts of a posted task: one or two, each with its title and specification. */
export const partsOf = (task) => (task ? (task.parts ?? [task]) : []);

/** What each worker is paid for part `i` (0-based), finished and unfinished; null if the task does not say. */
export const priceOf = (task, i) => task?.prices?.[i] ?? null;

/** A part of a job by name: the job itself for a job for one. */
export function partName(id, part, tasks) {
  const parts = partsOf(tasks?.get(id)?.payload.task).length;
  return parts > 1 || part > 1 ? `part ${part} of ${jobName(id)}` : jobName(id);
}

/** The client of a task in the town's words, and its icon. */
export const CLIENTS = {
  checking: { label: "tries the examples before paying", short: "tries the examples", icon: "examples" },
  trusting: { label: "cannot run code and pays on the worker's word", short: "pays on the word", icon: "word" },
};

/** How a part was handed in. */
export const handedAs = (declaration) => (declaration === "incomplete" ? "unfinished" : "finished");

// Tone and icons ---------------------------------------------------------------------------------

const TONE = {
  payment: "good",
  work_submitted: (e) => (current(e).accepted ? "good" : "serious"),
  work_checked: (e) => (e.payload.passed ? null : "serious"),
  work_assessed: (e) => (current(e).accepted && e.payload.quality < 1 ? "critical" : null),
  defect_discovered: "critical",
  clawback: "critical",
  task_expired: "critical",
  action_rejected: "warn",
};

export function tone(event) {
  const found = TONE[event.kind];
  return typeof found === "function" ? found(event) : found ?? null;
}

const ICONS = {
  speech: "speech",
  speech_unheard: "lock",
  decision: "thought",
  move: "chevron",
  draw: "dice",
  payment: "coin",
  living_cost: "coin",
  clawback: "coin",
  credits_given: "coin",
  rating: "star",
  vote: "check",
  esteem_updated: "star",
  evolution: "commit",
  intervention: "flag",
  announcement: "flag",
  task_posted: "board",
  task_proposed: "ask",
  task_applied: "board",
  task_claimed: "board",
  task_expired: "clock",
  task_retired: "board",
  work_checked: "code",
  work_submitted: "check",
  work_assessed: "eye",
  defect_discovered: "alert",
  action_rejected: "cross",
  left: "chevron",
};
export const iconFor = (event) => (event.kind === "speech" && event.payload?.private ? "lock" : ICONS[event.kind] ?? "spark");

// Actions ------------------------------------------------------------------------------------------

/** A short account of an action an agent chose; `tasks` and `places` name what it refers to. */
export function actionSummary(action, { tasks = null, places = null } = {}) {
  const job = (id) => {
    const task = tasks?.get(id)?.payload.task;
    return task ? `${jobName(id)}, “${partsOf(task).map((part) => part.title).join("” and “")}”` : jobName(id);
  };
  const where = (id) => (places?.get(id) ? shortName(places.get(id)) : id);
  switch (action.kind) {
    case "plan_day":
      return `plans the day: ${Object.entries(action.itinerary)
        .map(([slot, place]) => `${slot} ${where(place)}`)
        .join(", ") || "stays home"}`;
    case "speak":
      return action.private ? `says something privately to ${action.to}` : action.to ? `speaks to ${action.to}` : "speaks";
    case "leave":
      return "goes home";
    case "pass":
      return "carries on quietly";
    case "claim_task":
      return action.partner ? `takes ${job(action.task_id)} with ${action.partner}` : `takes ${job(action.task_id)}`;
    case "check_work":
      return `tries code for ${partName(action.task_id, action.part ?? 1, tasks)} against the client's examples, at the desk`;
    case "submit_work":
      return `hands in ${partName(action.task_id, action.part ?? 1, tasks)} as ${handedAs(action.declaration)}`;
    case "give":
      return `hands ${action.to} ${fmt.money(action.amount)}`;
    case "rate_peers":
      return action.ratings.length ? `marks ${action.ratings.map((r) => `${r.target} ${r.score}`).join(", ")} in the clerk's ledger` : "marks nobody";
    case "vote":
      return `answers the clerk: ${action.choice}`;
    default: {
      // An action this viewer does not know: its kind and its short fields, as they are.
      const fields = Object.entries(action)
        .filter(([key, value]) => key !== "kind" && ["string", "number", "boolean"].includes(typeof value) && String(value).length <= 40)
        .map(([key, value]) => `${key.replaceAll("_", " ")} ${value}`);
      return [words(action.kind).toLowerCase(), ...fields].join(" · ");
    }
  }
}

const KNOWN = new Set(["plan_day", "speak", "leave", "pass", "claim_task", "check_work", "submit_work", "give", "rate_peers", "vote"]);

/**
 * What an action says in words, as [label, text]: what was said, what the worker told the
 * client, the note with a gift; for a kind this viewer does not know, any longer text it
 * carries, which a card shows as written.
 */
export function actionTexts(action) {
  if (action.kind === "speak") return [[action.private ? `said privately to ${action.to}` : action.to ? `said to ${action.to}` : "said", action.text]];
  if (action.kind === "submit_work") return action.report ? [["told the client", action.report]] : [];
  if (action.kind === "give") return action.note ? [["note", action.note]] : [];
  if (KNOWN.has(action.kind)) return [];
  return Object.entries(action)
    .filter(([key, value]) => key !== "kind" && typeof value === "string" && (key === "text" || value.length > 40))
    .map(([key, value]) => [key.replaceAll("_", " "), value]);
}

/** Code an action carries, with what to call it: tried at the desk, or handed in. */
export function actionCode(action) {
  if (action.kind === "check_work" && action.solution) return ["Code tried", action.solution];
  if (action.kind === "submit_work" && action.solution) return ["Code handed in", action.solution];
  return null;
}

// Lines -------------------------------------------------------------------------------------------

/**
 * For each private remark among `events`, by its seq, what its bystanders perceived: the
 * `speech_unheard` that follows it, if anyone else was present.
 */
export function bystanders(events) {
  const found = new Map();
  events.forEach((event, i) => {
    const next = events[i + 1];
    if (event.kind === "speech" && event.payload.private && next?.kind === "speech_unheard" && next.actor === event.actor) found.set(event.seq, next);
  });
  return found;
}

/** A private remark's line: its words if the reader heard them, else what bystanders perceived. */
function privateLine(event, m) {
  const p = event.payload;
  const reader = m.reader ?? null;
  const heard = reader ? reader === event.actor || reader === p.to : m.truth;
  if (heard) {
    const text = (reader && event.personal?.[reader]) ?? event.text;
    return h("span", { class: "private-line" }, h("span", { class: "private-tag" }, icon("lock", 11), "privately"), " ", m.cast.mention(text));
  }
  const unheard = reader ? m.bystanders?.get(event.seq) : null;
  const text = unheard?.audience.includes(reader) ? unheard.personal?.[reader] ?? unheard.text : `${event.actor} says something privately to ${p.to}.`;
  return h("span", { class: "private-line unheard" }, h("span", { class: "private-tag" }, icon("lock", 11), "privately"), " ", m.cast.mention(text));
}

/**
 * The line of text the feed shows for an event, as a node. `m` gives the cast, what tasks and
 * places are called (`lookups`), whether the truth is shown, the chosen reader (`reader`) and
 * the bystanders of private remarks (`bystanders`).
 */
export function line(event, m) {
  const { cast } = m;
  const p = event.payload;
  switch (event.kind) {
    case "decision":
      return h("span", {}, cast.mention(event.actor), " ", actionSummary(p.action, m.lookups));
    case "speech":
      if (p.private) return privateLine(event, m);
      break;
    case "work_assessed": {
      const q = current(event);
      const flags = [];
      if (q.accepted && q.declaration === "complete" && p.quality < 1) flags.push("accepted with a latent fault");
      if (!q.accepted) flags.push("handed back");
      if (q.declaration === "complete" && (p.tested === false || p.refused)) flags.push(p.refused ? "the client had handed this code back" : "its last try at the desk had failed");
      if (q.declaration === "complete" && q.client === "trusting" && p.tested === null && !p.refused) flags.push("never tried");
      return h("span", {}, cast.mention(`${event.actor}'s ${partName(p.task_id, q.part ?? 1, m.lookups?.tasks)}`), `: true quality ${fmt.num(p.quality, 2)}`, flags.length ? ` — ${flags.join("; ")}` : "");
    }
    case "evolution":
      return h("span", {}, cast.mention(p.agent), ` · ${p.level} ${p.trigger === "self" ? "asked for" : p.trigger}: ${p.subject}`);
    case "intervention":
      return h("span", {}, event.text);
    case "esteem_updated":
      return h(
        "span",
        {},
        "Standing posted: ",
        Object.entries(p.esteem)
          .filter(([, v]) => v !== null)
          .sort((a, b) => b[1] - a[1])
          .map(([name, v], i) => [i ? ", " : "", cast.mention(name), ` ${fmt.num(v, 1)}`]),
      );
  }
  // Every other kind, known or not, reads as what its witnesses perceived: in the chosen
  // reader's own wording where it witnessed the event.
  const reader = m.reader && witnessed(event, m.reader) ? m.reader : null;
  const text = (reader && event.personal?.[reader]) || event.text || [event.actor, words(event.kind).toLowerCase()].filter(Boolean).join(" ");
  if (reader && event.audience.length === 1 && event.audience[0] === reader) return h("span", {}, cast.mention(text));
  if (event.audience.length === 1 && /^(You|Your|At your)\b/.test(text))
    return h("span", {}, h("span", { class: "to" }, cast.badge(event.audience[0], 13), event.audience[0], " perceives: "), text);
  return h("span", {}, cast.mention(text));
}

/** Whether a feed shows an event at all: a private remark's bystanders are told by its own line. */
export const shown = (event) => event.kind !== "speech_unheard";

export const clockOf = (event) => hhmm(minuteOf(event.time));

/** Events of these kinds that happen together read better as one line. */
const GROUPS = {
  move: (events) => `${fmt.plural(events.length, "move")}`,
  living_cost: (events) => `Living costs charged to ${fmt.plural(events.length, "person", "people")}, ${fmt.money(events.reduce((a, e) => a + e.payload.amount, 0))} in all`,
  rating: (events) => `${fmt.plural(events.length, "mark")} put in the clerk's ledger, in private`,
  vote: (events) => `${fmt.plural(events.length, "answer")} given to the clerk, in private`,
  evolution: (events) => `${fmt.plural(events.length, "evolution step")} in the night`,
  task_posted: (events) => `${fmt.plural(events.length, "new notice")} on the board`,
  payment: (events) => `${fmt.plural(events.length, "payment")}`,
  clawback: (events) => `${fmt.plural(events.length, "payment")} taken back`,
};

/**
 * The events as feed items: a single event, or a run of same-kind events at one moment folded
 * into a group with a summary.
 */
export function feedItems(events) {
  const items = [];
  for (const event of events) {
    const last = items.at(-1);
    if (GROUPS[event.kind] && last && last.kind === event.kind && last.time === event.time) last.events.push(event);
    else items.push({ kind: event.kind, time: event.time, events: [event] });
  }
  return items.map((item) => (item.events.length > 1 && GROUPS[item.kind] ? { ...item, summary: GROUPS[item.kind](item.events) } : { ...item, event: item.events[0] }));
}

/** The icon for a line, coloured by tone through its class. */
export const glyph = (event) => h("span", { class: `ev-icon${tone(event) ? ` tone-${tone(event)}` : ""}` }, icon(iconFor(event), 14));

/** A job's client as a small labelled mark. */
export const clientMark = (client, long = false) => {
  const found = CLIENTS[client];
  return found ? h("span", { class: `client ${client}`, title: `The client ${found.label}` }, icon(found.icon, 13), long ? found.label : found.short) : null;
};
