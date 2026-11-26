// The town at any moment, from the run's timeline (frontend.timeline) and nothing else: where
// each resident is, what it is in (idle, on the way, at work on a task, asleep, in bed, in
// conversation), what task it holds, what it carries and how its body stands, how many like it,
// the state of the Office, the Store, the kitchen and the Hospital, and what lies at each place;
// what a move of the timeline was, and the money each marker moved between purses, which adds up
// to every purse. Pure: no DOM, no fetching, so it runs under node as well as in the browser. The timeline is the server's reading of the world log; the viewer adds no reading
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

/** The task each resident holds at `t`, by name: the task, its instance, since when and who gave it; nobody holding nothing is absent. */
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

/** What a lane carries at `t`, by item id: as of its last change at or before `t`; nothing before any. */
export const thingsAt = (lane, t) => seriesAt(lane.things ?? [], t) ?? {};

/** The holders of things and money that are neither a resident nor a place, by their names in the log: the Store's shelves, the kitchen's counter, where its dishes stand ready, and its larder. */
export const SHELVES = "shelves";
export const COUNTER = "counter";
export const LARDER = "larder";
/** How money is named wherever a thing is named. */
export const MONEY = "money";
/** The businesses' holders, from which a take is a take of what a keeper keeps. */
export const KEPT = new Set([SHELVES, COUNTER, LARDER]);

const NOTHING = { items: {}, money: 0 };

/** What the holder `id` holds at `t`, `{items, money}`: one of the businesses', or a place's, what lies there for anyone to take. */
export const holdingAt = (timeline, id, t) => seriesAt(timeline.holders[id] ?? [], t) ?? NOTHING;

/**
 * The Store, the kitchen and the Hospital at `t`: the shelves and what they hold, the prices
 * posted and what is on order, the counter and the larder, the menu posted, and the Hospital's
 * fees, each by id; the businesses' holders as `{items, money}`.
 */
export const shopsAt = (timeline, t) => ({
  shelves: holdingAt(timeline, SHELVES, t),
  prices: seriesAt(timeline.store.prices, t),
  onOrder: seriesAt(timeline.store.on_order, t),
  counter: holdingAt(timeline, COUNTER, t),
  larder: holdingAt(timeline, LARDER, t),
  menu: seriesAt(timeline.kitchen.menu, t),
  fees: seriesAt(timeline.fees, t),
});

/** Whether a marker is a take. */
export const isTake = (m) => m.kind === "move" && m.reason === "take";

/** Whether a marker is a take from another resident, awake (in its sight) or asleep. */
export const tookFromPerson = (m) => isTake(m) && (m.from === "awake" || m.from === "asleep");

/** Whether a marker is a take from a business's shelves or counter of what was priced there, by one who does not keep it: what the honour system asks to be paid for. */
export const pricedTake = (m) => isTake(m) && m.price !== null && m.status !== "own" && (m.from === SHELVES || m.from === COUNTER);

/** Whether a marker's take or service was paid for short of what was due: in part, or not at all. */
export const paidShort = (m) => m.status === "underpaid" || m.status === "unpaid";

/** Whether a marker is a gift: money or a thing one resident gave another, payments among them. */
export const isGift = (m, residents) => m.kind === "move" && m.reason === "give" && residents.has(m.target);

/** The names of the residents of a timeline, as a set. */
export const namesOf = (timeline) => new Set(timeline.residents.map((lane) => lane.name));

/**
 * The money a marker on `by`'s lane (by null: a marker of the town's) moved into and out of
 * purses, `residents` being the town's names, as `[name, change, part]`, the part one of:
 * `share`, a client's share of a payment for a task accepted, less the tax withheld; `granted`,
 * from the treasury; `received`, money another gave it, less the tax withheld when it was at work,
 * and `given`, money it gave another; `left`, money it left at a place or on a business's holder;
 * `took`, money it took, from a resident or from where it lay, and `taken`, money taken from it;
 * `dropped`, money an incident let fall from it; `orders`, the shopkeeper's to the supplier; and at
 * the midnight statement `salary`, paid by the treasury, and `rent`, the rent, the daily charges
 * and the arrears it took. A marker that moved no money moves none; a price or a fee posted
 * charges nobody.
 */
export function moneyMoved(m, by, residents) {
  const found = (() => {
    switch (m.kind) {
      case "service":
        return [[by, m.amount - m.tax, "share"]];
      case "grant":
        return [[m.to, m.amount, "granted"]];
      case "order":
        return [[by, -m.amount, "orders"]];
      case "settlement":
        return [[by, m.salary_paid, "salary"], [by, -m.rent_paid, "rent"]];
      case "incident":
        return m.effects.filter((e) => e.type === "drop" && e.what === MONEY).map((e) => [e.who, -e.amount, "dropped"]);
      case "move":
        if (m.what !== MONEY) return [];
        if (m.reason === "take") return [[by, m.amount, "took"], ...(residents.has(m.source) ? [[m.source, -m.amount, "taken"]] : [])];
        if (m.reason === "give") return residents.has(m.target) ? [[by, -m.amount, "given"], [m.target, m.amount - m.tax, "received"]] : [[by, -m.amount, "left"]];
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
 * up to `t`, the town's markers among them. `start` and the parts add up to the purse at `t`.
 */
export function moneySince(timeline, name, t) {
  const lane = timeline.residents.find((found) => found.name === name);
  const residents = namesOf(timeline);
  const settled = settlementAt(lane, t);
  const parts = {};
  const add = ([who, change, part]) => {
    if (who === name) parts[part] = (parts[part] ?? 0) + change;
  };
  if (settled) moneyMoved(settled, name, residents).forEach(add);
  for (const other of [...timeline.residents, { name: null, markers: timeline.markers }]) for (const m of markersBetween(other, settled?.t ?? null, t)) moneyMoved(m, other.name, residents).forEach(add);
  const start = settled ? purseAt(lane, settled.t) - (parts.salary ?? 0) - (parts.rent ?? 0) : lane.purse[0][1];
  return { settled, start, parts };
}

/**
 * How many of the others like each resident at `t`, the number everyone saw on it, and the
 * number of the lived day before (null on the first): `{shown, before}`, each by name.
 */
export function regardAt(timeline, t) {
  const i = Math.max(0, lowerBound(timeline.regard, after(t), (point) => point[0]) - 1);
  return { shown: timeline.regard[i][1], before: i ? timeline.regard[i - 1][1] : null };
}

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
