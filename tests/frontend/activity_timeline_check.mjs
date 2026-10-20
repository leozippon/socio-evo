import assert from "node:assert/strict";
import { formatTime, hhmm, hhmmss, parseStamp, stamp } from "../../frontend/static/js/clock.js";
import { toolCompletionText } from "../../frontend/static/js/town/events.js";
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
const model = await import("../../frontend/static/js/town/activity-model.js");
const sharedEvents = [
  {seq:0,time:500,kind:"activity_entered",actor:"Mei",audience:["Mei"],payload:{activity:"chat",activity_type:"conversation",participants:["Mei"]}},
  {seq:1,time:501,kind:"speech",actor:"Aisha",audience:["Mei","Aisha"],payload:{activity:"chat"}},
  {seq:2,time:502,kind:"tool_started",actor:"Aisha",audience:["Aisha"],payload:{activity:"chat",tool:"private_tool"}},
  {seq:3,time:503,kind:"activity_left",actor:"Mei",audience:["Mei"],payload:{activity:"chat",reason:"Left"}},
  {seq:4,time:504,kind:"speech",actor:"Aisha",audience:["Aisha"],payload:{activity:"chat"}},
  {seq:5,time:505,kind:"activity_entered",actor:"Mei",audience:["Mei"],payload:{activity:"chat",activity_type:"conversation",participants:["Mei","Aisha"]}},
];
const sessions = activityIntervals(sharedEvents,506);
assert.deepEqual(model.activityTranscript(sharedEvents,sessions[0],506).map(e=>e.seq),[0,1,3]);
assert.deepEqual(model.activityTranscript(sharedEvents,sessions[1],506).map(e=>e.seq),[5],"resumed membership does not repeat earlier conversation");
assert.deepEqual(model.activityTranscript(sharedEvents,sessions[0],501).map(e=>e.seq),[0,1],"transcripts honor replay cutoff");
const totals = model.residentActivitySummary(sessions,"Mei",1,506);
assert.equal(totals.count,2);
assert.equal(totals.seconds.conversation,240);
assert.equal(model.activityDuration(3661),"1h 01m 01s");
assert.equal(model.activityDuration(13),"13s");
const { parse } = await import("../../frontend/static/js/router.js");
const link = model.activityLink({experiment:"demo",run:"seed-0000",query:{}},"Mei",506,sessions[1]);
const route = parse(link);
assert.equal(route.view,"person");
assert.equal(route.agent,"Mei");
assert.equal(route.query.tab,"activities");
assert.equal(route.query.activity,sessions[1].id);
assert.equal(parseStamp(route.query.t),506);
// Clicking a selected detail again must still reveal it, without hijacking new-tab actions.
let prevented = 0, revealed = 0;
const click = {button:0,preventDefault:()=>prevented++};
assert.equal(model.revealCurrentActivity(click,"same","same",()=>revealed++),true);
assert.equal(revealed,1); assert.equal(prevented,1);
assert.equal(model.revealCurrentActivity(click,"other","same",()=>revealed++),false);
assert.equal(model.revealCurrentActivity({...click,metaKey:true},"same","same",()=>revealed++),false);
assert.equal(model.revealCurrentActivity({...click,button:1},"same","same",()=>revealed++),false);
const {speechText} = await import("../../frontend/static/js/town/events.js");
assert.equal(speechText({payload:{message:{text:"Direct speech"}},text:"recorded speech"}),"Direct speech");
assert.equal(speechText({payload:{utterance:"Legacy speech"},text:"recorded speech"}),"Legacy speech");
assert.equal(speechText({payload:{},text:"Fallback speech"}),"Fallback speech");
// Live republishing temporarily invalidates replay state; seek must precede selected UI.
replay.seek(481);
const loadedDay = replay.eventsOf(1);
replay.load(1,loadedDay);
assert.equal(replay.state.seq,-1);
assert.equal(replay.seek(481).seq,1);
// Outside arrival is distinct from indoor admission and is cleared on movement/home return.
const {initialState,apply} = await import("../../frontend/static/js/replay.js");
const outside = initialState(world);
apply(outside,{seq:0,time:470,actor:"Mei",place:"workshop",kind:"move",payload:{origin:"home",destination:"workshop",outside:true}});
assert.equal(outside.locations.Mei,"workshop");
assert.equal(outside.outside.Mei,"workshop");
apply(outside,{seq:1,time:480,actor:"Mei",kind:"activity_feedback",payload:{outside:false}});
assert.equal(outside.outside.Mei,undefined);
apply(outside,{seq:2,time:720,actor:"Mei",place:"workshop",kind:"activity_entered",payload:{outside:true,activity:"door-rest",activity_type:"rest"}});
assert.equal(outside.outside.Mei,"workshop");
apply(outside,{seq:3,time:1320,actor:"Mei",kind:"move",payload:{origin:"workshop",destination:"home"}});
assert.equal(outside.outside.Mei,undefined);

// Transition rests are real recorded intervals, separately labelled from sleep.
const choosingEvents = [
  {seq:0,time:480,kind:"activity_entered",actor:"Mei",audience:["Mei"],payload:{activity:"choosing-1",activity_type:"rest",phase:"choosing_next_activity"}},
  {seq:1,time:481,kind:"decision",actor:"Mei",audience:["Mei"],payload:{layer:"choose_activity"}},
  {seq:2,time:482,kind:"activity_left",actor:"Mei",audience:["Mei"],payload:{activity:"choosing-1",reason:"Next activity started."}},
  {seq:3,time:482,kind:"activity_entered",actor:"Mei",audience:["Mei"],payload:{activity:"w2",activity_type:"work"}},
];
const choosing = activityIntervals(choosingEvents, 483);
assert.equal(model.activityLabel(choosing[0]), "Planning");
assert.equal(model.activityLabel(choosing[1]), "Work");
assert.equal(model.activityLabel({type:"rest"}), "Rest");
assert.equal(choosing[0].end, choosing[1].start, "transition and work have no gap or overlap");
assert.equal(activityIntervals(choosingEvents,481)[0].end,null,"show transition before inference finishes");
assert.equal(activityIntervals(choosingEvents,483,"Aisha").length,0,"transition stays private");
assert.equal(model.residentActivitySummary(choosing,"Mei",1,483).seconds.rest,120);
assert.deepEqual(model.activityTranscript(choosingEvents,choosing[0],483).map(e=>e.seq),[0,1,2]);

const rests = [
  {seq: 0, time: 420, actor: "Mei", kind: "activity_entered", payload: {activity: "rest-reused", activity_type: "rest"}},
  {seq: 1, time: 430, actor: "Mei", kind: "activity_left", payload: {activity: "rest-reused"}},
  {seq: 2, time: 450, actor: "Mei", kind: "activity_entered", payload: {activity: "rest-reused", activity_type: "rest"}},
  {seq: 3, time: 480, actor: "Mei", kind: "activity_left", payload: {activity: "rest-reused"}},
];
assert.deepEqual(activityIntervals(rests, 480).map(row => [row.start, row.end]), [[420, 430], [450, 480]], "reusing a resident's Rest keeps separate logged membership intervals");

const completion = (payload) => ({ actor: "Mei", payload: { tool: "invite", ...payload }, text: "Mei finished invite." });
assert.match(toolCompletionText(completion({ success: false, error: "Invitation not sent" })), /failed invite.*not sent/);
assert.match(toolCompletionText(completion({ error: "Rejected" })), /failed invite/);
assert.equal(toolCompletionText(completion({})), "Mei ended invite.");
assert.match(toolCompletionText(completion({ success: true, created: true, invitation: "invitation-1" })), /created invitation invitation-1/);
assert.equal(toolCompletionText(completion({ success: true, tool: "test" })), "Mei ended test.");
