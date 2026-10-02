// Replay state: everything shown is derived from the event log, nothing else.
// Pure functions without DOM access, so they run under node as well as in the browser.

const DAY = 1440;

export const dayOf = (time) => Math.floor(time / DAY) + 1;
export const clockOf = (time) => {
  const m = Math.floor(time % DAY);
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
};
export const formatTime = (time) => `Day ${dayOf(time)} ${clockOf(time)}`;

/** The state before any event: everyone at home with the initial balance. */
export function initialState(world) {
  const home = {};
  for (const place of world.places) for (const name of place.residents) home[name] = place.id;
  const names = world.agents.map((a) => a.name);
  return {
    time: 0,
    applied: 0, // number of events applied
    locations: Object.fromEntries(names.map((n) => [n, home[n] ?? null])),
    balances: Object.fromEntries(names.map((n) => [n, world.initial_balance])),
    esteem: {},
    conditions: { ...world.conditions },
    board: {}, // task id -> {id, title, reward, status: open|claimed|done, claimant, due_day}
    speech: {}, // agent -> {time, text} of its latest utterance
    day: 1,
  };
}

/** Apply one event to `state` in place. */
export function apply(state, event) {
  const p = event.payload;
  switch (event.kind) {
    case "move":
      state.locations[event.actor] = p.destination;
      break;
    case "speech":
      state.speech[event.actor] = { time: event.time, text: p.utterance, to: p.to };
      break;
    case "payment":
    case "living_cost":
    case "clawback":
      state.balances[p.agent] = p.balance;
      break;
    case "esteem_updated":
      state.esteem = { ...p.esteem };
      break;
    case "intervention":
      state.conditions = { ...p.conditions };
      break;
    case "day_started":
      state.day = dayOf(event.time);
      break;
    case "task_posted":
      state.board[p.task.id] = { id: p.task.id, title: p.task.title, reward: p.task.reward, status: "open" };
      break;
    case "task_claimed":
      Object.assign(state.board[p.task_id], { status: "claimed", claimant: event.actor, due_day: p.due_day });
      break;
    case "task_expired":
      Object.assign(state.board[p.task_id], { status: "open", claimant: null });
      break;
    case "task_retired":
      delete state.board[p.task_id];
      break;
    case "work_submitted":
      if (p.passed) state.board[p.task_id].status = "done";
      break;
  }
  state.applied += 1;
}

/** Plays a growing event list forward and rebuilds from the start when asked to go back. */
export class Replay {
  constructor(world) {
    this.world = world;
    this.events = [];
    this.reset();
  }

  reset() {
    this.state = initialState(this.world);
  }

  append(events) {
    this.events.push(...events);
  }

  get start() {
    return this.events.length ? this.events[0].time : 0;
  }

  get end() {
    return this.events.length ? this.events[this.events.length - 1].time : 0;
  }

  /** Make the state that of simulated `time`: every event at or before it applied. */
  seek(time) {
    if (time < this.state.time) this.reset();
    let i = this.state.applied;
    while (i < this.events.length && this.events[i].time <= time) apply(this.state, this.events[i++]);
    this.state.time = time;
    return this.state;
  }
}

/** Balance and esteem over the whole run, per agent, as [time, value] points. */
export function series(world, events) {
  const balance = {};
  const esteem = {};
  const first = events.length ? events[0].time : 0;
  for (const { name } of world.agents) {
    balance[name] = [[first, world.initial_balance]];
    esteem[name] = [];
  }
  for (const e of events) {
    const p = e.payload;
    if (e.kind === "payment" || e.kind === "living_cost" || e.kind === "clawback") balance[p.agent].push([e.time, p.balance]);
    else if (e.kind === "esteem_updated")
      for (const [name, value] of Object.entries(p.esteem)) if (value != null) esteem[name]?.push([e.time, value]);
  }
  return { balance, esteem };
}

/** Times at which each day began, for the scrubber's boundary marks. */
export const dayStarts = (events) => events.filter((e) => e.kind === "day_started").map((e) => e.time);
