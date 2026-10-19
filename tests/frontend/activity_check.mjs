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

// Two partners share one deliverable; old two-part and single-part logs still replay.
apply(state, event("task_posted", 510, { task: { id: "joint", required_workers: 2, parts: [{}] } }));
apply(state, event("task_claimed", 515, { task_id: "joint", workers: ["Mei", "Tomas"], due_day: 2 }));
assert.equal(state.claims.joint.parts.length, 1);
apply(state, event("work_delayed", 520, { task_id: "joint", due_day: 3 }));
assert.equal(state.claims.joint.due_day, 3);
apply(state, event("work_delayed", 525, { task_id: "missing", due_day: 3 }));
apply(state, event("task_posted", 530, { task: { id: "legacy-pair", parts: [{}, {}] } }));
apply(state, event("task_claimed", 535, { task_id: "legacy-pair", workers: ["Mei", "Tomas"], due_day: 2 }));
assert.equal(state.claims["legacy-pair"].parts.length, 2);
apply(state, event("task_posted", 540, { task: { id: "legacy-solo" } }));
apply(state, event("task_claimed", 545, { task_id: "legacy-solo", due_day: 2 }));
assert.equal(state.claims["legacy-solo"].parts.length, 1);
console.log("Shared deliverable and deadline replay checks passed");

// New sessions remain visible between tools; older activity events still work.
apply(state, event("activity_entered", 600, { activity: "work-1", activity_type: "work", start: 600, end: 660 }));
assert.equal(state.activities.Mei.action.kind, "work");
apply(state, event("tool_started", 601, { activity: "work-1", tool: "command", start: 601, end: 606 }));
assert.equal(state.activities.Mei.action.kind, "command");
apply(state, event("tool_completed", 606, { activity: "work-1" }));
assert.equal(state.activities.Mei.action.kind, "work");
apply(state, event("activity_left", 610, { activity: "work-1" }));
assert.equal(state.activities.Mei, undefined);
assert.equal(state.sessions.Mei, undefined);
console.log("Session and tool replay checks passed");
