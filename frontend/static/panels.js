// DOM panels: event feed, task board, agent panel. All text is set with textContent.

import { formatTime, clockOf, dayOf } from "./replay.js";

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") el.className = value;
    else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value);
  }
  el.append(...children.flat().filter((c) => c != null));
  return el;
}

const QUIET = new Set(["scene_started", "scene_ended", "day_started", "day_ended", "draw"]);
const FEED_LENGTH = 80;

/** The most recent events up to `state.applied`, newest first; `god` also shows truth-only ones. */
export function renderFeed(container, events, applied, god, world) {
  const items = [];
  for (let i = applied - 1; i >= 0 && items.length < FEED_LENGTH; i--) {
    const e = events[i];
    const truth = e.audience.length === 0;
    if (truth && !god) continue;
    items.push(feedItem(e, truth));
  }
  container.replaceChildren(...items);
  if (!items.length) container.append(h("p", { class: "muted" }, "Nothing has happened yet."));
}

function feedItem(e, truth) {
  const detail = [];
  if (e.kind === "decision") {
    detail.push(h("p", { class: "thought" }, e.payload.thought));
    detail.push(h("p", { class: "muted action" }, `action: ${JSON.stringify(e.payload.action)}`));
  }
  const place = e.place ? ` · ${e.place}` : "";
  return h(
    "li",
    { class: `event${truth ? " truth" : ""}${QUIET.has(e.kind) ? " quiet" : ""}` },
    h(
      "div",
      { class: "meta" },
      h("span", { class: "when" }, `D${dayOf(e.time)} ${clockOf(e.time)}`),
      h("span", { class: "kind" }, e.kind.replace("_", " ")),
      truth ? h("span", { class: "truthtag" }, "truth only") : null,
      h("span", { class: "muted" }, place),
    ),
    h("p", { class: "text" }, e.text),
    detail,
  );
}

export function renderBoard(container, state) {
  const tasks = Object.values(state.board);
  const open = tasks.filter((t) => t.status === "open");
  const claimed = tasks.filter((t) => t.status === "claimed");
  const done = tasks.length - open.length - claimed.length;
  const row = (t, note) =>
    h("li", {}, h("strong", {}, t.id), ` ${t.title}, ${t.reward} credits`, h("span", { class: "muted" }, note));
  container.replaceChildren(
    h("h2", {}, "Task board"),
    h("p", { class: "muted" }, `Living cost ${state.conditions.living_cost} credits a day · ${done} delivered`),
    h(
      "ul",
      { class: "plain" },
      open.map((t) => row(t, " · open")),
      claimed.map((t) => row(t, ` · ${t.claimant}, due day ${t.due_day}`)),
    ),
  );
}

/** A small step chart of `points` over [t0, t1] with the current time marked and min/max labelled. */
export function sparkline(points, t0, t1, now, label, format = (v) => String(v)) {
  const W = 260;
  const H = 54;
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("class", "spark");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", label);
  const add = (tag, attrs, text) => {
    const el = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    if (text != null) el.textContent = text;
    svg.append(el);
  };
  if (!points.length) {
    add("text", { x: 4, y: 30, class: "axis" }, "no data yet");
    return svg;
  }
  const values = points.map((p) => p[1]);
  let lo = Math.min(...values);
  let hi = Math.max(...values);
  if (lo === hi) [lo, hi] = [lo - 1, hi + 1];
  const left = 34;
  const x = (t) => left + ((t - t0) / Math.max(1, t1 - t0)) * (W - left - 6);
  const y = (v) => H - 6 - ((v - lo) / (hi - lo)) * (H - 14);
  let d = `M${x(points[0][0])},${y(points[0][1])}`;
  for (const [t, v] of points.slice(1)) d += ` H${x(t)} V${y(v)}`;
  d += ` H${x(t1)}`;
  add("path", { d, class: "line" });
  add("line", { x1: x(now), x2: x(now), y1: 2, y2: H - 4, class: "now" });
  add("text", { x: 0, y: 10, class: "axis" }, format(hi));
  add("text", { x: 0, y: H - 4, class: "axis" }, format(lo));
  return svg;
}

const COLORS = { "+": "add", "-": "del", "@": "hunk" };

export function renderDiff(text) {
  return h(
    "pre",
    { class: "diff" },
    text.split("\n").map((line) => h("span", { class: COLORS[line[0]] ?? "" }, line + "\n")),
  );
}

export { formatTime };
