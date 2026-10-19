import assert from "node:assert/strict";
import { receivedEvents, nextReceivedTime } from "../../frontend/static/js/town/perceptions.js";
const events = [
  {seq:0,time:420,kind:"day_started",audience:[],text:"Day begins"},
  {seq:1,time:420,kind:"task_posted",audience:[],text:"Research notice"},
  {seq:2,time:423,kind:"decision",actor:"Aisha",audience:["Aisha"],text:"Private thought"},
  {seq:3,time:423+35/60,kind:"activity_entered",actor:"Aisha",audience:["Aisha"],text:"Aisha rests"},
  {seq:4,time:424+38/60,kind:"discussion",actor:"Mei",audience:["Mei","Aisha"],text:"Mei invited Aisha",personal:{Mei:"You invited Aisha",Aisha:"Mei invited you"}},
  {seq:5,time:426,kind:"command_executed",actor:"Aisha",audience:["Aisha"],text:"Aisha's private terminal output"},
  {seq:6,time:427,kind:"speech",actor:"Tomas",audience:["Tomas","Mei"],text:"Tomas speaks",personal:{Mei:"Tomas said hello to you"}},
];
assert.deepEqual(receivedEvents(events,420,"Mei"),[],"07:00 has no fabricated receipt");
assert.deepEqual(receivedEvents(events,420),[],"truth-only notices are not received content");
assert.equal(nextReceivedTime(events,420,"Mei"),424+38/60);
assert.equal(nextReceivedTime(events,420),423+35/60,"next receipt skips private decisions");
assert.deepEqual(receivedEvents(events,426,"Mei").map(e=>e.seq),[4]);
assert.equal(receivedEvents(events,426,"Mei")[0].text,"You invited Aisha");
assert.equal(receivedEvents(events,426,"Aisha").find(e=>e.seq===4).text,"Mei invited you");
assert.deepEqual(receivedEvents(events,426).map(e=>e.seq),[3,4,5]);
assert.equal(receivedEvents(events,426)[1].text,"Mei invited Aisha","everyone uses town wording");
assert.equal(events[4].text,"Mei invited Aisha","reader-specific wording does not mutate the event");
assert.deepEqual(receivedEvents(events,426,"Tomas"),[],"nearby non-recipients get no content");
assert.equal(nextReceivedTime(events,427,"Mei"),null);
assert.deepEqual(receivedEvents(events,427,"Mei").map(e=>e.seq),[4,6]);
console.log("Resident perspective delivery, wording and replay-cutoff checks passed");
