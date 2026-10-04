// What an event means to a reader: who it concerns, whether anyone in town perceived it, and a
// line of text for it. Shared by the feed, the moment panel, the chronicle and the person view.

import { hhmm, minuteOf } from "../clock.js";
import { fmt, h } from "../dom.js";
import { icon } from "../icons.js";
import { shortName } from "../world.js";

/** Events that frame the day rather than happen in it. */
export const STRUCTURE = new Set(["day_started", "day_ended", "scene_started", "scene_ended"]);

/** Whether no agent perceived the event: material only the researcher sees. */
export const isTruth = (event) => event.audience.length === 0 && !STRUCTURE.has(event.kind);

/** Whether the event is visible in the town's own view: someone perceived it. */
export const isPublic = (event) => event.audience.length > 0;

/** The agents an event concerns, actor first. */
export function involved(event) {
  const p = event.payload ?? {};
  const names = new Set();
  if (event.actor) names.add(event.actor);
  for (const key of ["agent", "worker", "rater", "target", "to", "from", "partner"]) if (typeof p[key] === "string") names.add(p[key]);
  for (const key of ["order", "partners", "participants"]) if (Array.isArray(p[key])) for (const name of p[key]) if (typeof name === "string") names.add(name);
  return [...names];
}

/** What a scene is called; a kind of scene this viewer does not know is named by its kind. */
const SCENES = { work: "Work session", conversation: "Conversation", planning: "Everyone plans the day", review: "The evening review" };
export const sceneName = (kind) => SCENES[kind] ?? words(kind);
const words = (key) => {
  const text = String(key ?? "event").replaceAll("_", " ");
  return text[0].toUpperCase() + text.slice(1);
};

const TONE = {
  payment: "good",
  work_submitted: (e) => (e.payload.passed ? "good" : "serious"),
  work_assessed: (e) => (e.payload.quality < 1 ? "critical" : null),
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
  decision: "thought",
  move: "chevron",
  draw: "dice",
  payment: "coin",
  living_cost: "coin",
  clawback: "coin",
  rating: "star",
  esteem_updated: "star",
  evolution: "commit",
  intervention: "flag",
  announcement: "flag",
  task_posted: "board",
  task_claimed: "board",
  task_expired: "clock",
  task_retired: "board",
  work_submitted: "check",
  work_assessed: "eye",
  defect_discovered: "alert",
  action_rejected: "cross",
  left: "chevron",
};
export const iconFor = (event) => ICONS[event.kind] ?? "spark";

/** A short account of an action an agent chose; `tasks` and `places` name what it refers to. */
export function actionSummary(action, { tasks = null, places = null } = {}) {
  const title = (id) => (tasks?.get(id) ? `${id} (${tasks.get(id).payload.task.title})` : id);
  const where = (id) => (places?.get(id) ? shortName(places.get(id)) : id);
  switch (action.kind) {
    case "plan_day":
      return `plans the day: ${Object.entries(action.itinerary)
        .map(([slot, place]) => `${slot} ${where(place)}`)
        .join(", ") || "stays home"}`;
    case "speak":
      return action.to ? `speaks to ${action.to}` : "speaks";
    case "leave":
      return "leaves the conversation";
    case "pass":
      return "lets the turn pass";
    case "claim_task":
      return `claims ${title(action.task_id)}`;
    case "submit_work":
      return `delivers ${title(action.task_id)}`;
    case "rate_peers":
      return action.ratings.length ? `rates ${action.ratings.map((r) => `${r.target} ${r.score}`).join(", ")}` : "rates nobody";
    default: {
      // An action this viewer does not know: its kind and its short fields, as they are.
      const fields = Object.entries(action)
        .filter(([key, value]) => key !== "kind" && ["string", "number", "boolean"].includes(typeof value) && String(value).length <= 40)
        .map(([key, value]) => `${key.replaceAll("_", " ")} ${value}`);
      return [words(action.kind).toLowerCase(), ...fields].join(" · ");
    }
  }
}

const KNOWN = new Set(["plan_day", "speak", "leave", "pass", "claim_task", "submit_work", "rate_peers"]);

/**
 * What an action says in words, by field: what was said, and for a kind this viewer does not
 * know, any longer text it carries (a report, a remark), which its card shows as written.
 */
export function actionTexts(action) {
  if (action.kind === "speak") return [["said", action.text]];
  if (KNOWN.has(action.kind)) return [];
  return Object.entries(action).filter(([key, value]) => key !== "kind" && typeof value === "string" && (key === "text" || value.length > 40));
}

/** The line of text the feed shows for an event, as a node. */
export function line(event, cast, lookups = {}) {
  const p = event.payload;
  switch (event.kind) {
    case "decision":
      return h("span", {}, cast.mention(event.actor), " ", actionSummary(p.action, lookups));
    case "work_assessed":
      return h("span", {}, cast.mention(`${event.actor}'s delivery of ${p.task_id}`), `: true quality ${fmt.num(p.quality, 2)}`, p.passed && p.quality < 1 ? " — accepted with a latent defect" : p.passed ? "" : " (not accepted)");
    case "evolution":
      return h("span", {}, cast.mention(p.agent), ` · ${p.level} ${p.trigger === "self" ? "asked for" : p.trigger}: ${p.subject}`);
    case "intervention":
      return h("span", {}, event.text);
    case "esteem_updated":
      return h(
        "span",
        {},
        "Esteem published: ",
        Object.entries(p.esteem)
          .filter(([, v]) => v !== null)
          .sort((a, b) => b[1] - a[1])
          .map(([name, v], i) => [i ? ", " : "", cast.mention(name), ` ${fmt.num(v, 1)}`]),
      );
    default: {
      // Every other kind, known or not, reads as what its witnesses perceived.
      const text = event.text || [event.actor, words(event.kind).toLowerCase()].filter(Boolean).join(" ");
      if (event.audience.length === 1 && (text.startsWith("You") || text.startsWith("Your")))
        return h("span", {}, h("span", { class: "to" }, cast.badge(event.audience[0], 13), event.audience[0], " perceives: "), text);
      return h("span", {}, cast.mention(text));
    }
  }
}

export const clockOf = (event) => hhmm(minuteOf(event.time));

/** Events of these kinds that happen together read better as one line. */
const GROUPS = {
  move: (events) => `${fmt.plural(events.length, "move")}`,
  living_cost: (events) => `Living costs of ${events[0].payload.amount} credits charged to ${fmt.plural(events.length, "person", "people")}`,
  rating: (events) => `${fmt.plural(events.length, "rating")} given, in private`,
  evolution: (events) => `${fmt.plural(events.length, "evolution step")} in the night`,
  task_posted: (events) => `${fmt.plural(events.length, "new task")} on the board`,
  payment: (events) => `${fmt.plural(events.length, "payment")}`,
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
