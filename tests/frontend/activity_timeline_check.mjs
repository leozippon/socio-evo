import assert from "node:assert/strict";
import { formatTime, hhmm, hhmmss, parseStamp, stamp } from "../../frontend/static/js/clock.js";
import { Replay } from "../../frontend/static/js/replay.js";
import { activityIntervals } from "../../frontend/static/js/town/activity-model.js";

assert.equal(hhmm(480.1234567), "08:00");
assert.equal(hhmmss(480 + 13 / 60), "08:00:13");
assert.equal(hhmmss(1439.999999), "23:59:59");
assert.equal(formatTime(1440), "Day 2 · 00:00:00");
assert.equal(parseStamp("2-08:01"), 1921);
assert.equal(parseStamp(stamp(1921 + 13 / 60)), 1921 + 13 / 60);
const world = { places: [{ id: "home", residents: ["Mei", "Aisha"] }], agents: [{ name: "Mei" }, { name: "Aisha" }], initial_balance: 120, conditions: {} };
let seq = 0;
const event = (kind, seconds, actor, payload = {}) => ({ seq: seq++, kind, time: Math.floor(seconds / 60), actor, audience: [actor], place: "home", payload: { sim_seconds: seconds, ...payload } });
const events = [
  event("activity_entered", 28813, "Mei", { activity: "w1", activity_type: "work", end: 1080 }),
  event("tool_started", 28814, "Mei", { activity: "w1", tool: "command" }),
  event("activity_entered", 28820, "Aisha", { activity: "c1", activity_type: "conversation" }),
  event("tool_completed", 28825, "Mei", { activity: "w1", tool: "command" }),
  event("activity_left", 28830, "Mei", { activity: "w1", reason: "Paused" }),
  event("activity_entered", 28840, "Mei", { activity: "w1", activity_type: "work" }),
];
const replay = new Replay(world);
replay.expect([1]);
replay.load(1, events);
assert.equal(replay.seek(480 + 12 / 60).seq, -1, "do not expose an activity before its precise start");
assert.equal(replay.seek(480 + 14 / 60).seq, 1);
let intervals = activityIntervals(replay.eventsOf(1), 480 + 25 / 60);
assert.equal(intervals.length, 2, "future resumed interval is hidden");
assert.equal(intervals[0].end, null, "tool completion does not end work or use its planned deadline");
assert.equal(intervals[0].tool, null);
assert.equal(intervals[1].actor, "Aisha");
intervals = activityIntervals(replay.eventsOf(1), 481);
assert.equal(intervals.length, 3);
assert.equal(intervals[0].end, 480.5);
assert.equal(intervals[2].end, null, "resume is a new interval even with the same activity id");
assert.equal(activityIntervals(replay.eventsOf(1), 481, "Aisha").length, 1, "private view never leaks another resident's activity");
assert.equal(replay.seek(480 + 12 / 60).seq, -1, "rewind also respects second precision");
// Minute-only environment events after a precise event must not move time backwards.
const legacy = { ...events[0], seq: 1, kind: "decision", payload: { action: { kind: "pass" } } };
replay.load(1, [{ ...events[0], seq: 0 }, legacy]);
assert.equal(replay.eventsOf(1)[1].time, 480 + 13 / 60);
assert.equal(replay.seek(480 + 12 / 60).seq, -1);
assert.deepEqual(activityIntervals([{ ...legacy, seq: 0 }], 481), [], "old runs without activity membership remain readable");
console.log("Whole-second timestamps and activity timeline regression checks passed");
// Shared activity membership ends separately for each participant; no invented turn-taking.
const shared = [
  {seq:0, time:500, kind:"activity_entered", actor:"Mei", payload:{activity:"chat",activity_type:"conversation"}},
  {seq:1, time:500, kind:"activity_entered", actor:"Aisha", payload:{activity:"chat",activity_type:"conversation"}},
  {seq:2, time:502, kind:"activity_left", actor:"Mei", payload:{activity:"chat",reason:"Left"}},
];
const members = activityIntervals(shared,503);
assert.equal(members[0].end,502);
assert.equal(members[1].end,null);
