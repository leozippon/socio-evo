// Who is who: every agent has one stable identity, used on the map, in charts, in the graph and
// in text. Identity is colour (the agent's slot in the validated categorical palette, assigned
// in configured order), shape and initial together, so it never rests on colour alone.

import { h, s } from "./dom.js";

const SLOTS = 8;

/** Badge outlines in a box from -1 to 1, with the vertical offset that centres a letter. */
const SHAPES = [
  { d: "M0,-1A1,1 0 1 1 0,1A1,1 0 1 1 0,-1Z", dy: 0 },
  { d: "M-0.62,-0.88H0.62Q0.88,-0.88 0.88,-0.62V0.62Q0.88,0.88 0.62,0.88H-0.62Q-0.88,0.88 -0.88,0.62V-0.62Q-0.88,-0.88 -0.62,-0.88Z", dy: 0 },
  { d: "M0,-1.15L1.15,0L0,1.15L-1.15,0Z", dy: 0 },
  { d: "M0,-1.08L0.94,-0.54V0.54L0,1.08L-0.94,0.54V-0.54Z", dy: 0 },
  { d: "M0,-1.1L1.02,-0.2L0.84,0.94H-0.84L-1.02,-0.2Z", dy: 0.1 },
  { d: "M-0.92,-0.92H0.92V0.08Q0.92,0.7 0,1.12Q-0.92,0.7 -0.92,0.08Z", dy: -0.05 },
  { d: "M0,-1.2L0.74,-0.3A0.94,0.94 0 1 1 -0.74,-0.3Z", dy: 0.18 },
  { d: "M0,-1.12L1.12,0.86H-1.12Z", dy: 0.32 },
];

export class Cast {
  constructor(world) {
    this.world = world;
    this.names = world.agents.map((agent) => agent.name);
    this.index = new Map(this.names.map((name, i) => [name, i]));
    this.initials = initials(this.names);
    this.pattern = this.names.length ? new RegExp(`\\b(${this.names.map(escape).join("|")})\\b`, "g") : null;
  }

  has(name) {
    return this.index.has(name);
  }

  agent(name) {
    return this.world.agents[this.index.get(name)];
  }

  slot(name) {
    return (this.index.get(name) % SLOTS) + 1;
  }

  /** The agent's colour as a CSS value that follows the colour scheme. */
  color(name) {
    return this.has(name) ? `var(--a${this.slot(name)})` : "var(--muted)";
  }

  shape(name) {
    const i = this.index.get(name) ?? 0;
    return SHAPES[(i + Math.floor(i / SLOTS)) % SHAPES.length];
  }

  /** The badge as SVG content centred on 0,0 with radius `r`, for use inside another SVG. */
  glyph(name, r, { ring = true } = {}) {
    const shape = this.shape(name);
    const slot = this.slot(name);
    return s(
      "g",
      { class: "glyph", transform: `scale(${r})` },
      s("path", { d: shape.d, class: ring ? "glyph-ring" : null, style: { fill: `var(--a${slot})` }, "vector-effect": ring ? "non-scaling-stroke" : null }),
      s("text", { y: shape.dy, class: "glyph-letter", style: { fill: `var(--a${slot}-ink)`, "font-size": this.initials.get(name).length > 1 ? "0.95px" : "1.25px" } }, this.initials.get(name)),
    );
  }

  /** The badge as a standalone inline SVG of `size` pixels. */
  badge(name, size = 18) {
    return s("svg", { class: "badge", width: size, height: size, viewBox: "-1.3 -1.3 2.6 2.6", "aria-hidden": "true" }, this.glyph(name, 1));
  }

  /** The agent's name with its badge, as a link to the person view if `href` is given. */
  chip(name, href = null, extra = null) {
    const content = [this.badge(name, 16), h("span", {}, name), extra];
    return href ? h("a", { class: "chip", href }, ...content) : h("span", { class: "chip" }, ...content);
  }

  /** Text with every agent's name marked by its colour. */
  mention(text) {
    const fragment = document.createDocumentFragment();
    if (!this.pattern || !text) {
      fragment.append(text ?? "");
      return fragment;
    }
    let at = 0;
    for (const match of text.matchAll(this.pattern)) {
      fragment.append(text.slice(at, match.index));
      fragment.append(h("span", { class: "who", style: { "--c": this.color(match[0]) } }, match[0]));
      at = match.index + match[0].length;
    }
    fragment.append(text.slice(at));
    return fragment;
  }
}

/** Initials that tell the agents apart: the first letter, or the first two where letters clash. */
function initials(names) {
  const count = new Map();
  for (const name of names) count.set(name[0], (count.get(name[0]) ?? 0) + 1);
  return new Map(names.map((name) => [name, count.get(name[0]) > 1 ? name.slice(0, 2) : name[0]]));
}

const escape = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
