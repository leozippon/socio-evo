import assert from "node:assert/strict";
import { line, feedItems } from "../../frontend/static/js/town/events.js";

// Minimal text DOM: exercise the same event renderer used by the map/feed panels.
class TextNode {
  constructor(text = "") { this.text = text; this.children = []; }
  append(...children) { this.children.push(...children); }
  setAttribute() {}
  addEventListener() {}
  get textContent() { return this.text + this.children.map((child) => child.textContent).join(""); }
}
globalThis.Node = TextNode;
globalThis.document = {
  createElement: () => new TextNode(),
  createElementNS: () => new TextNode(),
  createTextNode: (text) => new TextNode(text),
};
const event = {
  seq: 1, time: 480, kind: "announcement", actor: null, payload: {},
  audience: ["Aisha"], text: "The town's wording.", personal: { Aisha: "Your own wording.", Mei: "Not witnessed." },
};
const moment = { cast: { mention: (text) => text }, reader: null };
assert.equal(line(event, moment).textContent, event.text);
assert.equal(line(event, { ...moment, reader: "Aisha" }).textContent, event.personal.Aisha);
assert.equal(line(event, { ...moment, reader: "Mei" }).textContent, event.text,
  "the perspective switch changes witnessed wording, not the event list");
assert.equal(line({ ...event, personal: {} }, { ...moment, reader: "Aisha" }).textContent, event.text,
  "events without personal wording keep their shared text");
const events = Array.from({ length: 393 }, (_, seq) => ({ ...event, seq, time: 480 + seq }));
assert.equal(feedItems(events).length, 393, "the original feed has no received-events pagination");
console.log("Original perspective wording and complete event feed checks passed");
