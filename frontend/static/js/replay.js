// The town at any moment, derived from the event log and nothing else.
//
// Pure: no DOM, no fetching, so it runs under node as well as in the browser. Event days arrive
// in any order and may be replaced (a day that is not settled can change in any way); the
// replay applies events strictly in log order and goes only as far as the loaded prefix.
// A snapshot of the state is kept at the start of every day it has passed, so a jump costs at
// most one day of events, and playing forward applies only the events it crosses.

import { dayOf } from "./clock.js";

/** The state before the first event: everyone at home with the initial balance. */
export function initialState(world) {
  const home = {};
  for (const place of world.places) for (const name of place.residents) home[name] = place.id;
  const each = (value) => Object.fromEntries(world.agents.map(({ name }) => [name, value(name)]));
  return {
    seq: -1, // the last event applied
    time: 0, // the moment shown; at or after the last event applied
    locations: each((name) => home[name]),
    balances: each(() => world.initial_balance),
    esteem: each(() => null), // as last published; null until first rated
    conditions: { ...world.conditions },
    open: {}, // task id -> time it (re)appeared on the board
    claims: {}, // task id -> {agent, due_day, time}
    scenes: {}, // scene id -> {kind, place, participants, present, start}
    said: {}, // agent -> seq of its latest speech
    decided: {}, // agent -> seq of its latest decision
    day: 0, // the day that has begun, 0 before the first
    ended: false, // whether that day has ended
  };
}

/** Apply one event to `state` in place. */
export function apply(state, event) {
  const p = event.payload;
  switch (event.kind) {
    case "day_started":
      state.day = dayOf(event.time);
      state.ended = false;
      break;
    case "day_ended":
      state.ended = true;
      break;
    case "move":
      state.locations[event.actor] = p.destination;
      break;
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
      const scene = state.scenes[event.scene];
      if (scene) scene.present = scene.present.filter((name) => name !== event.actor);
      break;
    }
    case "scene_ended":
      delete state.scenes[event.scene];
      break;
    case "decision":
      state.decided[event.actor] = event.seq;
      break;
    case "speech":
      state.said[event.actor] = event.seq;
      break;
    case "task_posted":
      state.open[p.task.id] = event.time;
      break;
    case "task_claimed":
      delete state.open[p.task_id];
      state.claims[p.task_id] = { agent: event.actor, due_day: p.due_day, time: event.time };
      break;
    case "task_expired":
      delete state.claims[p.task_id];
      state.open[p.task_id] = event.time;
      break;
    case "task_retired":
      delete state.open[p.task_id];
      break;
    case "work_submitted":
      if (p.passed) delete state.claims[p.task_id];
      break;
    case "payment":
    case "living_cost":
    case "clawback":
      state.balances[p.agent] = p.balance;
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
    for (const event of events) if (event.kind === "task_posted") this.tasks.set(event.payload.task.id, event);
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

/** The task each agent holds in `state`, by agent. */
export function holdings(state) {
  return Object.fromEntries(Object.entries(state.claims).map(([id, claim]) => [claim.agent, id]));
}
