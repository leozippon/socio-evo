import assert from "node:assert/strict";
import { initialState, apply } from "../../frontend/static/js/replay.js";

const state = initialState({ places: [{ id: "home", residents: ["Mei"] }], agents: [{ name: "Mei" }], initial_balance: 120, conditions: {} });
const event = (kind, time, payload) => ({ kind, time, payload, actor: "Mei", seq: time });
apply(state, event("goal_updated", 425, { goal: "Inspect the parser" }));
apply(state, event("action_started", 480, { start: 480, end: 500, action: { kind: "run_command" } }));
assert.equal(state.goals.Mei, "Inspect the parser");
assert.equal(state.activities.Mei.end, 500);
const saved = structuredClone(state);
apply(state, event("action_completed", 500, { start: 480, end: 500 }));
assert.equal(state.activities.Mei, undefined);
assert.equal(saved.activities.Mei.end, 500);
// Legacy logs need no activity or goal fields.
apply(state, event("decision", 505, { action: { kind: "pass" } }));
assert.equal(state.decided.Mei, 505);
console.log("Independent activity replay checks passed");
