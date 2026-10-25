// The town at any moment, from the run's timeline (frontend.timeline) and nothing else: where
// each resident is, what it is in (idle, on the way, at work on a task, asleep, in conversation),
// what it holds and what it has. Pure: no DOM, no fetching, so it runs under node as well as in
// the browser. The timeline is the server's reading of the world log; the viewer adds no reading
// of its own, only looks up moments in it.

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

/** The span of `spans` (contiguous, each `{start, end}`) holding time `t`: start ≤ t < end, or the last span for the moment it ends. */
function spanAt(spans, t) {
  if (!spans.length) return null;
  const i = Math.min(lowerBound(spans, t + 1, (span) => span.end), spans.length - 1);
  const span = spans[i];
  return span.start <= t && t <= span.end ? span : null;
}

/** The base event of a lane at `t`, one of its contiguous segments. */
export const segmentAt = (lane, t) => spanAt(lane.segments, t);

/** The conversation a lane is in at `t`, or null. */
export const conversationAt = (lane, t) => spanAt(lane.conversations, t);

/** The purse of a lane at `t`: after its last change at or before `t`. */
export function purseAt(lane, t) {
  const i = lowerBound(lane.purse, t + 1, (point) => point[0]) - 1;
  return lane.purse[Math.max(i, 0)][1];
}

/** The markers of a lane with `from` < t ≤ `to` (every marker up to `to` when `from` is null). */
export function markersBetween(lane, from, to) {
  const first = from === null ? 0 : lowerBound(lane.markers, from + 1, (m) => m.t);
  const last = lowerBound(lane.markers, to + 1, (m) => m.t);
  return lane.markers.slice(first, last);
}

/** The task a lane holds at `t`: its last claim not yet paid, given up or run out; null for none. */
export function heldAt(lane, t) {
  let held = null;
  for (const m of markersBetween(lane, null, t)) {
    if (m.kind === "claim") held = { task: m.task, instance_id: m.instance_id, since: m.t };
    else if (m.kind === "payment" || m.kind === "abandon" || m.kind === "expiry") held = null;
  }
  return held;
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

/** Where a resident is at `t`: its place, or null while on the way. */
export const placeAt = (lane, t) => {
  const segment = segmentAt(lane, t);
  return segment && segment.kind !== "movement" ? segment.place : null;
};
