// The town at any moment, from the run's timeline (frontend.timeline) and nothing else: where
// each resident is, what it is in (idle, on the way, at work on a task, asleep, in conversation),
// what it holds and what it has. Pure: no DOM, no fetching, so it runs under node as well as in
// the browser. The timeline is the server's reading of the world log; the viewer adds no reading
// of its own, only looks up moments in it. The timeline's times are whole seconds, but a moment
// looked up need not be: the town plays through the seconds between them.

import { livedDay } from "./clock.js";

/** The index of the first item of `items` whose `key` is at least `value`. */
export function lowerBound(items, value, key) {
  let lo = 0;
  let hi = items.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (key(items[mid]) < value) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/** The first whole second after `t`: a time of the timeline is after `t` exactly when it is at least this. */
const after = (t) => Math.floor(t) + 1;

/**
 * The span of `spans` (in order, each `{start, end}`) holding time `t`: start ≤ t < end, or t = end
 * for the last span when it is still open at the timeline's `now`. A span that closed before then
 * does not hold the moment it ended, whether or not another has followed it yet, so a moment
 * reads the same in every later publish of the timeline.
 */
function spanAt(spans, t, now) {
  const span = spans[lowerBound(spans, after(t), (s) => s.end)];
  if (span && span.start <= t) return span;
  const last = spans.at(-1);
  return last && last.end === now && t === now ? last : null;
}

/** Where a lane's timeline ends: its segments run on to the timeline's now. */
const nowOf = (lane) => lane.segments.at(-1)?.end;

/** The base event of a lane at `t`, one of its contiguous segments. */
export const segmentAt = (lane, t) => spanAt(lane.segments, t, nowOf(lane));

/** The conversation a lane is in at `t`, or null. */
export const conversationAt = (lane, t) => spanAt(lane.conversations, t, nowOf(lane));

/** The purse of a lane at `t`: after its last change at or before `t`. */
export function purseAt(lane, t) {
  const i = lowerBound(lane.purse, after(t), (point) => point[0]) - 1;
  return lane.purse[Math.max(i, 0)][1];
}

/** The markers of a lane with `from` < t ≤ `to` (every marker up to `to` when `from` is null). */
export function markersBetween(lane, from, to) {
  const first = from === null ? 0 : lowerBound(lane.markers, after(from), (m) => m.t);
  const last = lowerBound(lane.markers, after(to), (m) => m.t);
  return lane.markers.slice(first, last);
}

/** The task a lane holds at `t`: its last claim not yet paid, given up, run out or dropped by death; null for none. */
export function heldAt(lane, t) {
  let held = null;
  for (const m of markersBetween(lane, null, t)) {
    if (m.kind === "claim") held = { task: m.task, instance_id: m.instance_id, since: m.t };
    else if (m.kind === "payment" || m.kind === "abandon" || m.kind === "expiry" || m.kind === "death") held = null;
  }
  return held;
}

/** How a lane's body stood at `t`, by need, from the bands its condition markers last crossed into; empty before any. */
export function conditionAt(lane, t) {
  const found = {};
  for (const m of markersBetween(lane, null, t)) if (m.kind === "condition") found[m.need] = m.band;
  return found;
}

/** The place a lane set off from for the movement `segment`: the place of the segment before it. */
export function originOf(lane, segment) {
  const i = lane.segments.indexOf(segment);
  return i > 0 ? lane.segments[i - 1].place : null;
}

/**
 * The moment `t` of a timeline: its lived day, and for each resident its segment, its
 * conversation, its purse, the task it holds and, on the way somewhere, where from, where to and
 * how far along (0 to 1).
 */
export function moment(timeline, t) {
  const residents = {};
  for (const lane of timeline.residents) {
    const segment = segmentAt(lane, t);
    let moving = null;
    if (segment?.kind === "movement") {
      const span = segment.end - segment.start;
      moving = { from: originOf(lane, segment), to: segment.place, fraction: span > 0 ? Math.min(1, Math.max(0, (t - segment.start) / span)) : 0 };
    }
    residents[lane.name] = { lane, segment, conversation: conversationAt(lane, t), purse: purseAt(lane, t), held: heldAt(lane, t), moving };
  }
  return { time: t, day: livedDay(timeline.days, t), residents };
}
