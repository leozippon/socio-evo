import assert from "node:assert/strict";
import { activityConversations } from "../../frontend/static/js/town/activity-model.js";
import { ActivitiesPanel } from "../../frontend/static/js/town/activities.js";

const events = [
  {seq:0,time:480,kind:"activity_entered",actor:"Ana",place:"square",audience:["Ana"],payload:{activity:"chat",activity_type:"conversation"}},
  {seq:1,time:480,kind:"activity_entered",actor:"Ben",place:"square",audience:["Ben"],payload:{activity:"chat",activity_type:"conversation"}},
  {seq:2,time:481,kind:"speech",actor:"Ana",audience:["Ben","Watcher"],payload:{activity:"chat",message:{id:0,text:"First line\nSecond line"}}},
  {seq:3,time:481,kind:"speech",actor:"Ben",audience:["Ana","Watcher"],payload:{activity:"chat",message:{id:1,text:"Reply"}}},
  {seq:4,time:482,kind:"activity_left",actor:"Ana",audience:["Ana"],payload:{activity:"chat"}},
  {seq:5,time:483,kind:"speech",actor:"Ben",audience:["Cara"],payload:{activity:"chat",message:{id:2,text:"Still talking"}}},
  {seq:6,time:484,kind:"conversation_message",actor:"Cara",audience:["Ben"],payload:{activity:"chat",message:{id:3,text:"Future"}}},
  {seq:7,time:485,kind:"activity_entered",actor:"Ana",place:"square",audience:["Ana"],payload:{activity:"other",activity_type:"conversation"}},
  {seq:8,time:486,kind:"speech",actor:"Ana",audience:["Cara"],payload:{activity:"other",utterance:"Another conversation"}},
  {seq:9,time:1920,kind:"activity_entered",actor:"Ben",place:"square",audience:["Ben"],payload:{activity:"tomorrow",activity_type:"conversation"}},
];
let rows = activityConversations([...events].reverse(),483,1);
assert.equal(rows.length,1,"members share one conversation");
assert.deepEqual(rows[0].messages.map(e=>e.seq),[2,3,5],"all speakers, stable same-time sequence, and continuation after a member leaves");
assert.deepEqual(rows[0].participants,["Ana","Ben"],"audience bystanders are not participants and future speakers stay hidden");
assert.deepEqual(activityConversations(events,484,1)[0].participants,["Ana","Ben","Cara"]);
assert.deepEqual(activityConversations(events,484,1,"Ana")[0].messages.map(e=>e.seq),[2,3],"private reader does not see unheard speech after leaving");
assert.equal(activityConversations([...events, {...events[2],seq:10}],483,1)[0].messages.length,3,"shared message copies do not duplicate transcript");
assert.equal(activityConversations(events,1921,2).length,1,"day selection excludes prior conversations");
const legacy = [
 {seq:0,time:480,kind:"scene_started",scene:"c",place:"square",payload:{kind:"conversation",participants:["Ana","Ben"]}},
 {seq:1,time:481,kind:"speech",scene:"c",actor:"Ben",audience:["Ana"],payload:{utterance:"Legacy"}},
 {seq:2,time:482,kind:"scene_started",scene:"w",payload:{kind:"work",participants:["Ana"]}},
 {seq:3,time:483,kind:"speech",scene:"w",actor:"Ana",payload:{utterance:"Work"}},
];
assert.equal(activityConversations(legacy,484,1).length,1);
assert.equal(activityConversations(legacy,484,1)[0].messages[0].payload.utterance,"Legacy");
assert.equal(activityConversations(legacy,484,1,"Ana")[0].messages[0].payload.utterance,"Legacy","heard legacy speech survives truth-only scene metadata");
assert.deepEqual(activityConversations(legacy,484,1,"Ana")[0].participants,["Ben"],"hidden scene metadata cannot reveal other participants");
assert.equal(activityConversations([
 {seq:0,time:480,kind:"activity_entered",actor:"Ana",payload:{activity:"work",activity_type:"work"}},
 {seq:1,time:481,kind:"speech",actor:"Ana",payload:{activity:"work",utterance:"Work"}},
],482,1).length,0,"work activities are not mislabeled as conversations");

// Membership records are individual transitions, not participant snapshots.
const transitions = [
 {seq:0,time:480,kind:"activity_entered",actor:"Ana",audience:["Ana"],payload:{activity:"visit",activity_type:"conversation",participants:["Ana","Ben"]}},
 {seq:1,time:480,kind:"activity_entered",actor:"Ben",audience:["Ben"],payload:{activity:"visit",activity_type:"conversation",participants:["Ana","Ben"]}},
 {seq:2,time:480.5,kind:"speech",actor:"Ben",audience:["Ana","Watcher"],payload:{activity:"visit",message:{id:9,text:"Hello"}}},
 {seq:3,time:481,kind:"activity_left",actor:"Ana",audience:["Ana"],payload:{activity:"visit"}},
 {seq:4,time:482,kind:"activity_entered",actor:"Ana",audience:["Ana"],payload:{activity:"visit",activity_type:"conversation",participants:["Ana","Ben"]}},
 {seq:5,time:483,kind:"activity_left",actor:"Ben",audience:["Ben"],payload:{activity:"visit"}},
];
const signature = row => row.entries.map(e=>[e.kind,e.actor ?? e.event.actor,e.seq]);
assert.deepEqual(signature(activityConversations([...transitions].reverse(),483,1)[0]),[
 ["joined","Ana",0],["joined","Ben",1],["speech","Ben",2],["left","Ana",3],["joined","Ana",4],["left","Ben",5],
]);
assert.deepEqual(signature(activityConversations(transitions,483,1,"Ana")[0]),[
 ["joined","Ana",0],["speech","Ben",2],["left","Ana",3],["joined","Ana",4],
],"reader never sees private membership transitions");
assert.equal(activityConversations(transitions,481,1)[0].entries.length,4,"future rejoin/exit is hidden");
assert.deepEqual(activityConversations([...transitions,{...transitions[2],seq:6}],483,1)[0].entries.map(e=>e.seq),[0,1,2,3,4,5],"speech copies stay deduplicated in timeline");
const endedLegacy = [...legacy,{seq:4,time:484,kind:"scene_ended",scene:"c",payload:{}}];
assert.deepEqual(signature(activityConversations(endedLegacy,484,1)[0]),[
 ["joined","Ana",0],["joined","Ben",0],["speech","Ben",1],["left","Ana",4],["left","Ben",4],
]);
assert.deepEqual(signature(activityConversations(endedLegacy,484,1,"Ana")[0]),[["speech","Ben",1]],"hidden scene boundaries never invent reader membership");
assert.equal(activityConversations(legacy,484,1)[0].entries.filter(e=>e.kind==="left").length,0,"missing scene end never invents an exit time");

// Render the actual panel and exercise its selector across replay updates.
class Element {
 constructor(tag="",text="") {this.tag=tag;this.text=text;this.children=[];this.attrs={};this.listeners={};this.style={setProperty(){}};}
 append(...children){this.children.push(...children);}
 replaceChildren(){this.children=[];}
 setAttribute(key,value){this.attrs[key]=value;}
 addEventListener(key,handler){this.listeners[key]=handler;}
 get textContent(){return this.text+this.children.map(e=>e.textContent).join("");}
 find(tag){return this.tag===tag?this:this.children.map(e=>e.find(tag)).find(Boolean);}
}
globalThis.Node=Element;
globalThis.document={createElement:tag=>new Element(tag),createTextNode:text=>new Element("",text)};
const panel=new ActivitiesPanel();
const moment={state:{time:486},truth:true,selected:null,activityEvents:events,world:{agents:[{name:"Ana"},{name:"Ben"}],calendar:{day_start:"08:00",day_end:"18:00",slots:[]}},places:new Map(),route:{experiment:"demo",run:"one",query:{}},cast:{badge:()=>new Element("badge")}};
panel.update(moment);
assert(panel.el.textContent.includes("Conversations"));
assert(!panel.el.textContent.includes("Activity history by resident"));
assert.equal(panel.el.find("a").attrs["aria-label"],"Ana's daily activities","resident detail entry stays available");
const picker=panel.el.find("select");
assert.equal(picker.children.length,2);
picker.listeners.change({target:{value:"activity:chat"}});
assert(panel.el.textContent.includes("First line\nSecond line"),"full multiline message body is rendered");
assert(panel.el.textContent.includes("Still talking"));
panel.update(moment);
assert.equal(panel.el.find("select").children[0].attrs.selected,"");
panel.update({...moment,state:{time:481}});
assert.equal(panel.conversationId,"activity:chat");
assert(!panel.el.textContent.includes("Still talking"),"rewind removes future messages from the DOM");
panel.update({...moment,truth:false,selected:"Ana"});
assert(!panel.el.textContent.includes("Still talking"));
panel.update({...moment,state:{time:1921}});
assert.equal(panel.conversationId,"activity:tomorrow");
panel.update({...moment,state:{time:479}});
assert(panel.el.textContent.includes("No conversations recorded at this moment."));
panel.update({...moment,activityEvents:transitions,state:{time:483}});
assert(panel.el.textContent.includes("Ana joined"));
assert(panel.el.textContent.includes("Ana left"));
assert(panel.el.textContent.includes("08:00:30"));
const timeline=panel.el.find("ol");
assert.equal(timeline.attrs["aria-label"],"Conversation timeline");
assert.deepEqual(timeline.children.map(e=>e.textContent),[
 "08:00:00Ana joined","08:00:00Ben joined","08:00:30BenHello","08:01:00Ana left","08:02:00Ana joined","08:03:00Ben left",
]);
panel.update({...moment,activityEvents:transitions,state:{time:480}});
assert(panel.el.textContent.includes("Ana joined"));
assert(!panel.el.textContent.includes("No messages recorded yet."),"membership-only conversation has a visible timeline");
assert(!panel.el.textContent.includes("Ana left"),"rewind hides future membership in DOM");
console.log("Shared Conversations model and Activities panel checks passed");
