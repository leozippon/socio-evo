// The town at any moment, derived from the event log and nothing else.
//
// Pure: no DOM, no fetching, so it runs under node as well as in the browser. Event days arrive
// in any order and may be replaced (a day that is not settled can change in any way); the
// replay applies events strictly in log order and goes only as far as the loaded prefix.
// A snapshot of the state is kept at the start of every day it has passed, so a jump costs at
// most one day of events, and playing forward applies only the events it crosses.

import { dayOf } from "./clock.js";

/** The state before the first event: everyone at home with their starting balance. */
export function initialState(world) {
  const home = {};
  for (const place of world.places) for (const name of place.residents) home[name] = place.id;
  const each = (value) => Object.fromEntries(world.agents.map((agent) => [agent.name, value(agent)]));
  return {
    seq: -1, // the last event applied
    time: 0, // the moment shown; at or after the last event applied
    locations: each((agent) => home[agent.name]),
    balances: each((agent) => agent.initial_balance ?? world.initial_balance),
    esteem: each(() => null), // as last published; null until first rated
    conditions: { ...world.conditions },
    taskParts: {}, // actual deliverable counts, distinct from worker counts
    open: {}, // task id -> time it (re)appeared on the board
    claims: {}, // task id -> {workers, actor, due_day, time, parts: [{worker, declaration, time} | null]}
    offers: {}, // agent -> its open bid for a job for two: {task_id, partner (null: name put down), time}
    askings: [], // the askings made today or still open at its start, each {seq, time, day, asker, partner, task_id, fate, at, atDay}
    scenes: {}, // scene id -> {kind, place, participants, present, start}
    said: {}, // agent -> seq of its latest speech
    decided: {}, // agent -> seq of its latest decision
    day: 0, // the day that has begun, 0 before the first
    ended: false, // whether that day has ended
  };
}

/**
 * What became of an asking: `open` while it stands, overnight too; `taken up` when the two took
 * the job together; `withdrawn` when the one who asked asked about another job, put their name
 * down or took a job; `ended` when the job went to others or came down; `lapsed` when the day
 * ended with it still open, in logs recorded while askings lapsed at night.
 */
function settle(asking, fate, event) {
  asking.fate = fate;
  asking.at = event.seq;
  asking.atDay = dayOf(event.time);
}

/** The fate an `offer_ended` event's cause gives an asking. */
const FATES = { lapsed: "lapsed", took_another: "withdrawn", replaced: "withdrawn", taken_by_others: "ended", withdrawn: "ended", came_down: "ended" };

/** A new bid replaces its maker's open one; an asking it replaces is withdrawn. */
function bid(state, event, partner) {
  const actor = event.actor;
  const before = state.offers[actor];
  if (before?.partner) {
    const asking = state.askings.findLast((found) => found.asker === actor && found.fate === "open");
    if (asking) settle(asking, "withdrawn", event);
  }
  state.offers[actor] = { task_id: event.payload.task_id, partner, time: event.time };
  if (partner) state.askings.push({ seq: event.seq, time: event.time, day: dayOf(event.time), asker: actor, partner, task_id: event.payload.task_id, fate: "open", at: null, atDay: null });
}

/** Drop the open bids that `drop(agent, offer)` names, settling their askings with `fate(offer)`. */
function dropOffers(state, event, drop, fate) {
  for (const [agent, offer] of Object.entries(state.offers)) {
    if (!drop(agent, offer)) continue;
    delete state.offers[agent];
    if (!offer.partner) continue;
    const asking = state.askings.findLast((found) => found.asker === agent && found.fate === "open");
    if (asking) settle(asking, fate(agent, offer), event);
  }
}

/**
 * The payload of `event` in its present shape: a log recorded before tasks had parts reads as
 * what it meant then (one worker, the claimant or the `agent` whose claim lapsed; a delivery
 * declared complete, accepted when it `passed`).
 */
export function current(event) {
  const p = event.payload ?? {};
  if (event.kind === "task_claimed" && !p.workers) return { ...p, workers: [event.actor] };
  if (event.kind === "task_expired" && !p.workers) return { ...p, workers: [p.agent], delivered: [null] };
  if ((event.kind === "work_submitted" || event.kind === "work_assessed") && p.accepted === undefined) return { ...p, part: 1, declaration: "complete", accepted: p.passed };
  return p;
}

/** Apply one event to `state` in place. */
export function apply(state, event) {
  const p = current(event);
  switch (event.kind) {
    case "day_started":
      state.day = dayOf(event.time);
      state.ended = false;
      state.askings = state.askings.filter((asking) => asking.fate === "open");
      break;
    case "day_ended":
      state.ended = true;
      break;
    case "offer_ended": {
      const offer = state.offers[p.agent];
      // A replaced offer is told ended after the one that replaced it, which `bid` already
      // withdrew it for; the payload names no part, so only its cause tells it from the new one.
      if (p.cause === "replaced" || !offer || offer.task_id !== p.task_id) break;
      delete state.offers[p.agent];
      const asking = state.askings.findLast((found) => found.asker === p.agent && found.fate === "open");
      if (!asking) break;
      settle(asking, FATES[p.cause] ?? "ended", event);
      break;
    }
    case "move": {
      state.locations[event.actor] = p.destination;
      // Going home from a scene under way leaves it.
      const scene = state.scenes[event.scene];
      if (scene) scene.present = scene.present.filter((name) => name !== event.actor);
      break;
    }
    case "scene_started":
      state.scenes[event.scene] = {
        kind: p.kind,
        place: event.place,
        participants: [...p.participants],
        present: [...p.participants],
        start: event.time,
      };
      break;
    case "left": {
      // Recorded before leaving meant going home: the agent stayed at the place.
      const scene = state.scenes[event.scene];
      if (scene) scene.present = scene.present.filter((name) => name !== event.actor);
      break;
    }
    case "scene_ended":
      delete state.scenes[event.scene];
      break;
    case "action_started":
      state.activities ??= {};
      state.activities[event.actor] = p;
      break;
    case "action_completed":
      if (state.activities) delete state.activities[event.actor];
      break;
    case "goal_updated":
      state.goals ??= {};
      state.goals[event.actor] = p.goal;
      break;
    case "decision":
      state.decided[event.actor] = event.seq;
      break;
    case "speech":
      state.said[event.actor] = event.seq;
      break;
    case "task_posted":
      (state.taskParts ??= {})[p.task.id] = p.task.parts?.length ?? 1;
      state.open[p.task.id] = event.time;
      break;
    case "task_proposed":
      bid(state, event, p.partner);
      break;
    case "task_applied":
      bid(state, event, null);
      break;
    case "task_claimed": {
      // Its workers' own bids go, and every bid for the job: an asking between the two is taken
      // up, one by a worker is withdrawn, any other ends with the job going to others.
      const workers = p.workers;
      dropOffers(
        state,
        event,
        (agent, offer) => workers.includes(agent) || offer.task_id === p.task_id,
        (agent, offer) => (offer.task_id === p.task_id && workers.includes(offer.partner) && workers.includes(agent) ? "taken up" : workers.includes(agent) ? "withdrawn" : "ended"),
      );
      delete state.open[p.task_id];
      state.claims[p.task_id] = { workers: [...workers], actor: event.actor, due_day: p.due_day, time: event.time, parts: Array.from({ length: state.taskParts?.[p.task_id] ?? workers.length }, () => null) };
      break;
    }
    case "work_delayed":
      if (state.claims[p.task_id] && p.due_day != null) state.claims[p.task_id].due_day = p.due_day;
      break;
    case "task_expired":
      delete state.claims[p.task_id];
      state.open[p.task_id] = event.time;
      break;
    case "task_retired":
      delete state.open[p.task_id];
      dropOffers(state, event, (agent, offer) => offer.task_id === p.task_id, () => "ended");
      break;
    case "work_submitted": {
      const claim = state.claims[p.task_id];
      if (!claim || !p.accepted) break;
      claim.parts[p.part - 1] = { worker: event.actor, declaration: p.declaration, time: event.time };
      // A job is paid, and leaves the board, once every part is in.
      if (claim.parts.every(Boolean)) delete state.claims[p.task_id];
      break;
    }
    case "payment":
    case "living_cost":
    case "clawback":
      state.balances[p.agent] = p.balance;
      break;
    case "credits_given":
      Object.assign(state.balances, p.balances);
      break;
    case "esteem_updated":
      state.esteem = { ...state.esteem, ...p.esteem };
      break;
    case "intervention":
      state.conditions = { ...p.conditions };
      break;
  }
  state.seq = event.seq;
  state.time = Math.max(state.time, event.time);
}

const clone = (state) => structuredClone(state);

export class Replay {
  constructor(world) {
    this.world = world;
    this.days = new Map(); // day -> its events, as loaded
    this.firsts = new Map(); // first seq of a loaded day -> day
    this.expected = []; // the days the run has, as last published
    this.snapshots = new Map(); // day -> state before its first event
    this.tasks = new Map(); // task id -> its task_posted event
    this.perspectives = false; // whether some witness read some loaded event its own way
    this.state = initialState(world);
    this.cached = null; // the day array the last lookup hit
  }

  /** Declare the days the run has now; loaded days it no longer has are forgotten. */
  expect(days) {
    this.expected = [...days];
    const wanted = new Set(days);
    for (const [day, events] of [...this.days]) {
      if (wanted.has(day)) continue;
      this.days.delete(day);
      this.firsts.delete(events[0].seq);
      this.forget(day, events[0].seq);
    }
  }

  /** Set the events of `day`, replacing what was loaded for it before. */
  load(day, events) {
    if (!events.length) throw new Error(`day ${day} has no events`);
    const old = this.days.get(day);
    if (old) this.firsts.delete(old[0].seq);
    this.days.set(day, events);
    this.firsts.set(events[0].seq, day);
    this.forget(day, old ? Math.min(old[0].seq, events[0].seq) : events[0].seq);
    for (const event of events) {
      if (event.kind === "task_posted") this.tasks.set(event.payload.task.id, event);
      // Whether witnesses can have read an event differently: their own wording, or a private remark.
      if (!this.perspectives && (Object.keys(event.personal ?? {}).length || (event.kind === "speech" && event.payload.private))) this.perspectives = true;
    }
  }

  /** Drop what was derived from events from `seq` on, which belong to `day` or later. */
  forget(day, seq) {
    this.cached = null;
    for (const key of [...this.snapshots.keys()]) if (key > day) this.snapshots.delete(key);
    if (this.state.seq >= seq) this.state = this.snapshots.has(day) ? clone(this.snapshots.get(day)) : initialState(this.world);
  }

  has(day) {
    return this.days.has(day);
  }

  /** The days the run has up to the day of `time` that are not loaded yet. */
  missing(time) {
    return this.expected.filter((day) => day <= dayOf(time) && !this.days.has(day));
  }

  /** The loaded events of `day`, or an empty list. */
  eventsOf(day) {
    return this.days.get(day) ?? [];
  }

  /** The event with sequence number `seq`, if its day is loaded. */
  event(seq) {
    const inside = (events) => events && seq >= events[0].seq && seq < events[0].seq + events.length;
    if (!inside(this.cached)) this.cached = [...this.days.values()].find(inside) ?? null;
    return this.cached ? this.cached[seq - this.cached[0].seq] : undefined;
  }

  /** The last event of the loaded prefix of the log, or null. */
  get last() {
    let found = null;
    while (this.firsts.has((found?.seq ?? -1) + 1)) found = this.days.get(this.firsts.get((found?.seq ?? -1) + 1)).at(-1);
    return found;
  }

  /** Make the state that of time `time`: every event at or before it applied, and no other. */
  seek(time) {
    return this.go((event) => event.time <= time, time, dayOf(time));
  }

  /** Make the state that right after event `seq`. */
  seekSeq(seq) {
    const event = this.event(seq);
    if (!event) throw new Error(`event ${seq} is not loaded`);
    return this.go((e) => e.seq <= seq, event.time, dayOf(event.time));
  }

  go(within, time, day) {
    let state = this.state;
    const applied = state.seq >= 0 ? this.event(state.seq) : null;
    const ahead = state.seq >= 0 && !(applied && within(applied));
    let best = null; // the latest snapshot at or before the target day
    for (const [key, snapshot] of this.snapshots) if (key <= day && (!best || key > best[0])) best = [key, snapshot];
    if (ahead) state = best ? clone(best[1]) : initialState(this.world);
    else if (best && best[1].seq > state.seq) state = clone(best[1]);
    for (;;) {
      const next = state.seq + 1;
      const start = this.firsts.get(next);
      if (start !== undefined && !this.snapshots.has(start)) this.snapshots.set(start, clone(state));
      const event = this.event(next);
      if (!event || !within(event)) break;
      apply(state, event);
    }
    state.time = Math.max(time, state.seq >= 0 ? this.event(state.seq).time : 0);
    this.state = state;
    return state;
  }

  sortedDays(descending = false) {
    return [...this.days.keys()].sort((a, b) => (descending ? b - a : a - b));
  }

  /** The time of the first loaded event after `time`, or null. */
  nextTime(time) {
    for (const day of this.sortedDays()) {
      if (day < dayOf(time)) continue;
      const found = this.days.get(day).find((event) => event.time > time);
      if (found) return found.time;
    }
    return null;
  }

  /** The time of the last loaded event before `time`, or null. */
  previousTime(time) {
    for (const day of this.sortedDays(true)) {
      if (day > dayOf(time)) continue;
      const found = this.days.get(day).findLast((event) => event.time < time);
      if (found) return found.time;
    }
    return null;
  }

  /** The loaded events that happened at exactly `time`. */
  at(time) {
    return this.eventsOf(dayOf(time)).filter((event) => event.time === time);
  }

  /** Every loaded event about task `id`, in log order, up to event `upto`. */
  taskEvents(id, upto = Infinity) {
    const found = [];
    for (const day of this.sortedDays())
      for (const event of this.days.get(day)) {
        if (event.seq > upto) return found;
        const p = event.payload;
        if (p.task_id === id || p.task?.id === id) found.push(event);
      }
    return found;
  }
}

/** The job each agent works on in `state`, by agent. */
export function holdings(state) {
  return Object.fromEntries(Object.entries(state.claims).flatMap(([id, claim]) => claim.workers.map((worker) => [worker, id])));
}
