// The town at any moment, from the run's timeline (frontend.timeline) and nothing else: where
// each resident is, what it is in (idle, on the way, at work on a task, asleep, in bed, in
// conversation), what task it holds, what it owns and how its body stands, the state of the
// Office, the Store, the kitchen and the Hospital, and what lies at each place; what a move of
// the timeline was, in the terms the town counts, and the money each marker moved between purses,
// which adds up to every purse. Pure: no DOM, no fetching, so it runs under
// node as well as in the browser. The timeline is the server's reading of the world log; the viewer adds no reading
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

/** The state of a series (`[[time, state], ...]` from the start) at `t`: as of its last change at or before `t`; null before the first. */
export function seriesAt(series, t) {
  const i = lowerBound(series, after(t), (point) => point[0]) - 1;
  return i < 0 ? null : series[i][1];
}

/** The purse of a lane at `t`: after its last change at or before `t`. */
export const purseAt = (lane, t) => seriesAt(lane.purse, t) ?? lane.purse[0][1];

/** The markers of a lane with `from` < t ≤ `to` (every marker up to `to` when `from` is null). */
export function markersBetween(lane, from, to) {
  const first = from === null ? 0 : lowerBound(lane.markers, after(from), (m) => m.t);
  const last = lowerBound(lane.markers, after(to), (m) => m.t);
  return lane.markers.slice(first, last);
}

/** The Office's task `task` at `t`: its holder (or null), since when, and who gave it, if the team leader did. */
export function holderAt(task, t) {
  const i = lowerBound(task.holders, after(t), (entry) => entry[0]) - 1;
  if (i < 0 || task.holders[i][1] === null) return null;
  const [since, holder, by] = task.holders[i];
  return { holder, since, by };
}

/** Whether the Office's task `task` is on the board at `t`: come in, and neither accepted nor withdrawn yet. */
export const openAt = (task, t) => task.arrived <= t && !(task.accepted !== null && task.accepted <= t) && !(task.withdrawn !== null && task.withdrawn <= t);

/** What each resident holds at `t`, by name: the task, its instance, since when and who gave it; nobody holding nothing is absent. */
export function holdersAt(timeline, t) {
  const found = new Map();
  for (const task of timeline.tasks) {
    const held = holderAt(task, t);
    if (held) found.set(held.holder, { task: task.task, instance_id: task.instance_id, since: held.since, by: held.by });
  }
  return found;
}

/** The task the resident `name` holds at `t`, as `holdersAt` gives it, or null. */
export const heldAt = (timeline, name, t) => holdersAt(timeline, t).get(name) ?? null;

/** Whether a lane is ill at `t`: it fell ill at a midnight and has not recovered from it since. */
export function illAt(lane, t) {
  let ill = false;
  for (const m of markersBetween(lane, null, t)) {
    if (m.kind === "illness") ill = true;
    else if (m.kind === "recovered" && m.illness) ill = false;
  }
  return ill;
}

/**
 * How a lane's body stood at `t`, by need: the band its condition markers last crossed into
 * (null while it is still in the band it started in), with the value then, and the value the
 * midnight statement last gave if that came later; a need nothing has been told of is absent.
 */
export function bodyAt(lane, t) {
  const found = {};
  for (const m of markersBetween(lane, null, t)) {
    if (m.kind === "condition") found[m.need] = { band: m.band, lowest: m.lowest, value: m.value, t: m.t };
    else if (m.kind === "settlement") for (const need of ["satiety", "energy", "health"]) found[need] = { band: null, lowest: false, ...found[need], value: m[need], t: m.t };
  }
  return found;
}

/** The midnight statement of a lane last given at or before `t`, or null before the first. */
export function settlementAt(lane, t) {
  let found = null;
  for (const m of markersBetween(lane, null, t)) if (m.kind === "settlement") found = m;
  return found;
}

/** What a lane owns at `t`, by good id: as of its last change at or before `t`; nothing before any. */
export const thingsAt = (lane, t) => seriesAt(lane.things ?? [], t) ?? {};

/** The holders of items that are neither a resident nor a place, by their names in the log: the Store's shelves, the kitchen's larder and its portions. */
export const SHELVES = "shelves";
export const LARDER = "larder";
export const PORTIONS = "portions";

/** What lies at the place `id` at `t` for anyone to take, by item id. */
export const lyingAt = (timeline, id, t) => seriesAt(timeline.holders[id], t) ?? {};

/**
 * The Store, the kitchen and the Hospital at `t`: the Store's stock, prices and what is on order,
 * the kitchen's stock, menu and portions ready, and the Hospital's fees, each by id.
 */
export const shopsAt = (timeline, t) => ({
  stock: seriesAt(timeline.holders[SHELVES], t),
  prices: seriesAt(timeline.store.prices, t),
  onOrder: seriesAt(timeline.store.on_order, t),
  larder: seriesAt(timeline.holders[LARDER], t),
  menu: seriesAt(timeline.kitchen.menu, t),
  portions: seriesAt(timeline.holders[PORTIONS], t),
  fees: seriesAt(timeline.fees, t),
});

/** Whether a marker is a purchase at the Store's counter: for oneself, or the chef's for the kitchen's larder. */
export const boughtAtCounter = (m) => m.kind === "move" && m.reason === "buy" && m.source === SHELVES;

/** Whether a marker is a dish from the kitchen's portions: bought, or handed over by the chef unpaid. */
export const dishServed = (m) => m.kind === "move" && m.source === PORTIONS;

/** Whether a marker is money or a thing one resident passed another (the chef's dish is served, not passed). */
export const handedOver = (m) => m.kind === "move" && m.reason === "pass" && m.source !== PORTIONS;

/** The money a move took from the resident who made it for itself: what it bought for itself or ate there; what the chef buys for the kitchen is the kitchen's cost. */
export const spentOn = (m) => (m.kind === "move" && m.reason === "buy" && m.target !== LARDER ? m.money : 0);

/**
 * The money a marker on `by`'s lane moved into and out of purses, as `[name, change, part]`, the
 * part one of: `share`, a client's share of a payment for a task accepted, and `takings`, what a
 * customer or a patient paid the keeper of a business, each less the tax withheld; `granted`,
 * from the treasury; `received` and `passed`, money handed over; `spent`, a purchase for oneself,
 * a dish or a fee; `kitchen`, the chef's purchase for the kitchen; `orders`, the shopkeeper's to
 * the supplier; and at the midnight statement `salary`, paid by the treasury, and `rent`, the
 * rent, the daily charges and the arrears it took. A marker that moved no money moves none.
 */
export function moneyMoved(m, by) {
  const found = (() => {
    switch (m.kind) {
      case "service":
        return [[by, m.amount - m.tax, "share"]];
      case "grant":
        return [[m.to, m.amount, "granted"]];
      case "order":
        return [[by, -m.amount, "orders"]];
      case "examination":
      case "treatment":
        return [[m.patient, -m.fee, "spent"], [by, m.fee - m.tax, "takings"]];
      case "settlement":
        return [[by, m.salary_paid, "salary"], [by, -m.rent_paid, "rent"]];
      case "move":
        if (m.reason === "pass" && m.item === null) return [[by, -m.money, "passed"], [m.target, m.money, "received"]];
        if (m.reason === "buy") return [[by, -m.money, m.target === LARDER ? "kitchen" : "spent"], [m.seller, m.money - m.tax, "takings"]];
        return [];
      default:
        return [];
    }
  })();
  return found.filter(([, change]) => change);
}

/**
 * A resident's money between midnights, as the person view tells it: the last midnight statement
 * at or before `t` (null before the first), what the purse held before it (`start`: the starting
 * money before any), and by part (`moneyMoved`) the statement's salary and rent and every sum since,
 * up to `t`. `start` and the parts add up to the purse at `t`.
 */
export function moneySince(timeline, name, t) {
  const lane = timeline.residents.find((found) => found.name === name);
  const settled = settlementAt(lane, t);
  const parts = {};
  const add = ([who, change, part]) => {
    if (who === name) parts[part] = (parts[part] ?? 0) + change;
  };
  if (settled) moneyMoved(settled, name).forEach(add);
  for (const other of timeline.residents) for (const m of markersBetween(other, settled?.t ?? null, t)) moneyMoved(m, other.name).forEach(add);
  const start = settled ? purseAt(lane, settled.t) - (parts.salary ?? 0) - (parts.rent ?? 0) : lane.purse[0][1];
  return { settled, start, parts };
}

/** Who had a dish served: the diner who bought it, `by`, or the one the chef passed it to. */
export const dinerOf = (m, by) => (m.reason === "buy" ? by : m.target);

/** The place a lane set off from for the movement `segment`: the place of the segment before it. */
export function originOf(lane, segment) {
  const i = lane.segments.indexOf(segment);
  return i > 0 ? lane.segments[i - 1].place : null;
}

/**
 * The moment `t` of a timeline: its lived day, for each resident its segment, its conversation,
 * its purse, the task it holds and, on the way somewhere, where from, where to and how far along
 * (0 to 1).
 */
export function moment(timeline, t) {
  const residents = {};
  const holders = holdersAt(timeline, t);
  for (const lane of timeline.residents) {
    const segment = segmentAt(lane, t);
    let moving = null;
    if (segment?.kind === "movement") {
      const span = segment.end - segment.start;
      moving = { from: originOf(lane, segment), to: segment.place, fraction: span > 0 ? Math.min(1, Math.max(0, (t - segment.start) / span)) : 0 };
    }
    residents[lane.name] = { lane, segment, conversation: conversationAt(lane, t), purse: purseAt(lane, t), held: holders.get(lane.name) ?? null, moving };
  }
  return { time: t, day: livedDay(timeline.days, t), residents };
}
