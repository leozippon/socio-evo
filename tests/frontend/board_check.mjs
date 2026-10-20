import assert from "node:assert/strict";
import { useCurrency } from "../../frontend/static/js/dom.js";

class FakeNode {
  constructor(tag = "#text", value = "") {
    this.tagName = tag;
    this.nodeValue = value;
    this.children = [];
    this.attributes = {};
    this.style = { setProperty() {} };
    this.classList = { contains: (name) => (this.attributes.class ?? "").split(/\s+/).includes(name) };
  }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  addEventListener() {}
  append(child) { this.children.push(child); }
  replaceChildren(...children) { this.children = children; }
  get textContent() { return this.tagName === "#text" ? this.nodeValue : this.children.map((child) => child.textContent).join(""); }
}

globalThis.Node = FakeNode;
globalThis.document = {
  createElement: (tag) => new FakeNode(tag),
  createElementNS: (_namespace, tag) => new FakeNode(tag),
  createTextNode: (text) => new FakeNode("#text", String(text)),
};
useCurrency({ symbol: "$", unit: "crown", units: "crowns" });
const { BoardPanel } = await import("../../frontend/static/js/town/panels.js");

const all = (root, predicate) => {
  const found = [];
  const visit = (node) => {
    if (predicate(node)) found.push(node);
    for (const child of node.children) visit(child);
  };
  visit(root);
  return found;
};

function renderHandin({ id, claim, handin, claimDay = 1 }) {
  const task = { id, required_workers: claim?.payload.workers.length ?? 2, parts: [{ title: "Repair", reward: 20, deadline_days: 1 }] };
  const posted = { seq: 0, time: 420, kind: "task_posted", payload: { task: { ...task, id } } };
  const history = [posted, ...(claim ? [{ ...claim, time: (claimDay - 1) * 1440 + 480 }] : []), handin];
  const replay = {
    tasks: new Map([[id, { payload: { task }, time: 420 }]]),
    taskEvents: (taskId, upto) => taskId === id ? history.filter((event) => event.seq <= upto) : [],
  };
  const panel = new BoardPanel({ replay });
  const state = { seq: handin.seq, conditions: {}, open: {}, claims: {}, offers: {} };
  const m = {
    state,
    truth: true,
    reader: null,
    world: { task_shelf_life_days: 2 },
    dayEvents: [handin, { ...handin, seq: handin.seq + 1, kind: "work_assessed", payload: { ...handin.payload, accepted: handin.payload.accepted, quality: 1 } }],
    cast: {
      badge: (name) => {
        const node = document.createElement("span");
        node.setAttribute("class", "badge");
        node.setAttribute("data-name", name);
        return node;
      },
    },
  };
  panel.update(m);
  return all(panel.el, (node) => node.classList.contains("task-who"))[0];
}

const pairClaim = { seq: 2, kind: "task_claimed", actor: "Jonas", payload: { task_id: "task-7", workers: ["Kofi", "Jonas"], due_day: 1 } };
const jonasHandin = { seq: 3, time: 600, kind: "work_submitted", actor: "Jonas", payload: { task_id: "task-7", part: 1, declaration: "complete", accepted: true } };
const acceptedPair = renderHandin({ id: "task-7", claim: pairClaim, handin: jonasHandin });
assert.deepEqual(acceptedPair.children.filter((node) => node.classList.contains("badge")).map((node) => node.attributes["data-name"]), ["Kofi", "Jonas"], "accepted hand-in retains both real workers after the live claim is removed");
assert.match(acceptedPair.attributes.title, /Kofi, Jonas; submitted by Jonas/);
assert.equal(acceptedPair.children.find((node) => node.tagName === "small").textContent, "submitted by Jonas");

const acrossDayClaim = { ...pairClaim, seq: 5, payload: { ...pairClaim.payload, task_id: "task-8" } };
const acrossDayHandin = { ...jonasHandin, seq: 6, time: 1450, payload: { ...jonasHandin.payload, task_id: "task-8" } };
const acrossDay = renderHandin({ id: "task-8", claim: acrossDayClaim, handin: acrossDayHandin, claimDay: 1 });
assert.deepEqual(acrossDay.children.filter((node) => node.classList.contains("badge")).map((node) => node.attributes["data-name"]), ["Kofi", "Jonas"], "claim history from the prior day remains available");

const soloClaim = { seq: 2, kind: "task_claimed", actor: "Mei", payload: { task_id: "task-9", workers: ["Mei"], due_day: 1 } };
const soloHandin = { seq: 3, time: 610, kind: "work_submitted", actor: "Mei", payload: { task_id: "task-9", part: 1, declaration: "complete", accepted: true } };
const solo = renderHandin({ id: "task-9", claim: soloClaim, handin: soloHandin });
assert.deepEqual(solo.children.filter((node) => node.classList.contains("badge")).map((node) => node.attributes["data-name"]), ["Mei"], "solo work keeps one badge");

const missing = renderHandin({ id: "task-10", handin: { ...soloHandin, actor: "Aisha", payload: { ...soloHandin.payload, task_id: "task-10" } } });
assert.deepEqual(missing.children.filter((node) => node.classList.contains("badge")).map((node) => node.attributes["data-name"]), ["Aisha"], "missing claim history falls back to the known submitter without inventing a partner");
console.log("Board team display checks passed");
