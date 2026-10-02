// The town on a map: places drawn at their configured coordinates by kind, open or closed by
// the clock, daylight following the simulated hour, and every agent as its badge, walking
// between places. Speech floats above in an HTML layer, where text can wrap. Roads and trees
// are decoration: they connect and fill the configured places, nothing more.

import { daylight, hhmm, isOpen, opensAt } from "../clock.js";
import { h, onWidth, s } from "../dom.js";
import { icon } from "../icons.js";
import { shortName } from "../world.js";

const WALK_MS = 900;
const FONT_FAMILY = "system-ui, -apple-system, 'Segoe UI', sans-serif";

/** A deterministic pseudo-random sequence from a string, for decoration that never jumps. */
function seeded(text) {
  let x = 2166136261;
  for (const c of text) x = Math.imul(x ^ c.charCodeAt(0), 16777619);
  return () => {
    x = Math.imul(x ^ (x >>> 15), 2246822507);
    x = Math.imul(x ^ (x >>> 13), 3266489909);
    return ((x ^= x >>> 16) >>> 0) / 4294967296;
  };
}

/** The edges of a minimum spanning tree over points, to draw as roads. */
function spanningTree(points) {
  const inside = new Set([0]);
  const edges = [];
  while (inside.size < points.length) {
    let best = null;
    for (const i of inside)
      for (let j = 0; j < points.length; j++) {
        if (inside.has(j)) continue;
        const d = Math.hypot(points[i].x - points[j].x, points[i].y - points[j].y);
        if (!best || d < best[2]) best = [i, j, d];
      }
    inside.add(best[1]);
    edges.push(best);
  }
  return edges;
}

function distanceToSegment(p, a, b) {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const t = Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / (dx * dx + dy * dy || 1)));
  return Math.hypot(p.x - a.x - t * dx, p.y - a.y - t * dy);
}

let measurer = null;
/** Break a label into at most three lines no wider than `width`; returns them and the widest. */
function wrap(text, width, size) {
  measurer ??= document.createElement("canvas").getContext("2d");
  measurer.font = `700 ${size}px ${FONT_FAMILY}`;
  const lines = [""];
  for (const word of text.split(" ")) {
    const next = lines.at(-1) ? `${lines.at(-1)} ${word}` : word;
    if (measurer.measureText(next).width <= width || !lines.at(-1)) lines[lines.length - 1] = next;
    else lines.push(word);
  }
  if (lines.length > 3) lines.splice(2, lines.length - 2, lines.slice(2).join(" "));
  return { lines, widest: Math.max(...lines.map((line) => measurer.measureText(line).width)) };
}

function building(kind, w, hgt) {
  const win = (x, y, ww, hh) => s("rect", { class: "win", x, y, width: ww, height: hh, rx: 1.5 });
  if (kind === "home") {
    const top = -hgt * 0.12;
    return [
      s("path", { class: "roof", d: `M${-w / 2 - 4},${top}L0,${-hgt * 0.62}L${w / 2 + 4},${top}Z` }),
      s("rect", { class: "wall", x: -w / 2, y: top, width: w, height: hgt * 0.62, rx: 2 }),
      s("rect", { class: "door", x: -w * 0.09, y: top + hgt * 0.3, width: w * 0.18, height: hgt * 0.32, rx: 1.5 }),
      win(-w * 0.38, top + hgt * 0.14, w * 0.2, hgt * 0.16),
      win(w * 0.18, top + hgt * 0.14, w * 0.2, hgt * 0.16),
    ];
  }
  if (kind === "work") {
    const top = -hgt * 0.32;
    const teeth = 4;
    let roof = `M${-w / 2},${top}`;
    for (let i = 0; i < teeth; i++) roof += `L${-w / 2 + (w / teeth) * i},${top - hgt * 0.22}L${-w / 2 + (w / teeth) * (i + 1)},${top}`;
    return [
      s("path", { class: "roof work", d: `${roof}Z` }),
      s("rect", { class: "wall", x: -w / 2, y: top, width: w, height: hgt * 0.82, rx: 2 }),
      ...[0, 1, 2].map((i) => win(-w * 0.4 + i * w * 0.29, top + hgt * 0.14, w * 0.22, hgt * 0.26)),
      s("rect", { class: "door", x: -w * 0.08, y: top + hgt * 0.5, width: w * 0.16, height: hgt * 0.32, rx: 1.5 }),
    ];
  }
  const top = -hgt * 0.2;
  const stripes = 6;
  const awning = [];
  for (let i = 0; i < stripes; i++) {
    const x = -w / 2 - 3 + ((w + 6) / stripes) * i;
    awning.push(s("path", { class: i % 2 ? "awning alt" : "awning", d: `M${x},${top}h${(w + 6) / stripes}v${hgt * 0.14}a${(w + 6) / stripes / 2},${hgt * 0.07} 0 0 1 ${-(w + 6) / stripes},0z` }));
  }
  return [
    s("path", { class: "roof social", d: `M${-w / 2 - 2},${top}L${-w / 2 + w * 0.12},${-hgt * 0.55}H${w / 2 - w * 0.12}L${w / 2 + 2},${top}Z` }),
    s("rect", { class: "wall", x: -w / 2, y: top, width: w, height: hgt * 0.7, rx: 2 }),
    win(-w * 0.38, top + hgt * 0.26, w * 0.24, hgt * 0.2),
    win(w * 0.14, top + hgt * 0.26, w * 0.24, hgt * 0.2),
    s("rect", { class: "door", x: -w * 0.08, y: top + hgt * 0.36, width: w * 0.16, height: hgt * 0.34, rx: 1.5 }),
    ...awning,
  ];
}

export class TownMap {
  /** `fit()` returns the most height the map may take, or null to size it by width alone. */
  constructor({ world, cast, onSelect, fit }) {
    this.world = world;
    this.cast = cast;
    this.onSelect = onSelect;
    this.fit = fit;
    this.byId = new Map(world.places.map((place) => [place.id, place]));
    this.el = h("div", { class: "map" });
    this.svg = s("svg", { class: "map-svg", role: "img", "aria-label": "Map of the town" });
    this.overlay = h("div", { class: "map-overlay" });
    this.curtain = h("div", { class: "map-curtain", hidden: true });
    this.el.append(this.svg, this.overlay, this.curtain);
    this.tokens = new Map();
    this.frame = null;
    this.bubbleKey = null;
    this.stop = onWidth(this.el, (width) => {
      this.width = width;
      this.layout();
      if (this.frame) this.update(this.frame, false);
    });
  }

  layout() {
    const places = this.world.places;
    const xs = places.map((p) => p.x);
    const ys = places.map((p) => p.y);
    const [minX, maxX, minY, maxY] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
    const pad = 0.75;
    const top = 34; // room for the labels of the topmost places
    const spanX = maxX - minX + 2 * pad;
    const spanY = maxY - minY + 2 * pad;
    const maxHeight = this.fit?.() ?? Math.max(300, window.innerHeight * 0.62);
    const unit = Math.max(30, Math.min(this.width / spanX, (maxHeight - top) / spanY));
    // A wide map may stretch across a little: the layout keeps its order and proportions
    // within each axis, and neighbours side by side get room for their names.
    const across = Math.min(this.width / spanX, unit * 1.45);
    this.unit = unit;
    this.height = Math.round(top + unit * spanY);
    const ox = (this.width - across * spanX) / 2;
    this.at = (x, y) => ({ x: ox + (x - minX + pad) * across, y: top + (y - minY + pad) * unit });
    this.r = Math.max(7, Math.min(11, unit * 0.115));
    this.centres = new Map(places.map((p) => [p.id, this.at(p.x, p.y)]));
    const sizes = { home: [0.46, 0.44], work: [0.64, 0.5], social: [0.58, 0.46] };
    this.size = (kind) => {
      const k = sizes[kind] ?? sizes.home;
      return { w: Math.min(100, k[0] * unit), h: Math.min(76, k[1] * unit) };
    };
    this.svg.setAttribute("viewBox", `0 0 ${this.width} ${this.height}`);
    this.svg.setAttribute("width", this.width);
    this.svg.setAttribute("height", this.height);
    this.el.style.height = `${this.height}px`;
    this.bubbleKey = null;
    this.drawStatic();
  }

  drawStatic() {
    const places = this.world.places;
    const points = places.map((p) => this.centres.get(p.id));
    const roads = spanningTree(points).map(([i, j]) => {
      const a = points[i];
      const b = points[j];
      const rand = seeded(`${places[i].id}~${places[j].id}`);
      const bend = (rand() - 0.5) * 0.25;
      const c = { x: (a.x + b.x) / 2 - (b.y - a.y) * bend, y: (a.y + b.y) / 2 + (b.x - a.x) * bend };
      return { a, b, c, d: `M${a.x},${a.y}Q${c.x},${c.y} ${b.x},${b.y}` };
    });
    const rand = seeded(this.world.experiment ?? "town");
    const trees = [];
    for (let k = 0; k < 160 && trees.length < 48; k++) {
      const p = { x: rand() * this.width, y: rand() * this.height };
      if (points.some((q) => Math.hypot(q.x - p.x, (q.y - p.y) * 1.2) < this.unit * 0.75)) continue;
      if (roads.some((r) => distanceToSegment(p, r.a, r.c) < 14 || distanceToSegment(p, r.c, r.b) < 14)) continue;
      if (trees.some((t) => Math.hypot(t.x - p.x, t.y - p.y) < 18)) continue;
      trees.push({ ...p, r: 5 + rand() * 4 });
    }
    this.placeGroups = new Map();
    this.subs = new Map();
    this.lowered = new Map(); // places named below their building, which a crowd may push down
    this.tops = new Map(); // where speech may start above each place
    const labels = [];
    const groups = places.map((place) => {
      const c = this.centres.get(place.id);
      const size = this.size(place.kind);
      const roof = -size.h * 0.64;
      const font = this.unit < 70 ? 10 : 11.5;
      const lead = font + 1.5;
      const { lines, widest } = wrap(shortName(place), Math.max(40, this.gap(place) - 8), font);
      // Name a place above its roof, unless another place sits just above it: then below.
      const crowded = places.some((other) => other !== place && Math.abs(other.x - place.x) < 1 && place.y - other.y > 0 && place.y - other.y <= 1.2);
      const below = this.ring(place).ry + this.r + 14;
      const nameY = crowded ? below : roof - 17 - (lines.length - 1) * lead;
      // Keep the name inside the map at its left and right edges.
      const shift = Math.max(4 + widest / 2 - c.x, Math.min(0, this.width - 4 - widest / 2 - c.x));
      const sub = s("text", { class: "place-sub", x: shift, y: crowded ? below + lines.length * lead - 1 : roof - 5, "text-anchor": "middle" }, "");
      const name = s("text", { class: "place-name", x: shift, y: nameY, "text-anchor": "middle", style: { "font-size": `${font}px` } }, lines.map((text, i) => s("tspan", { x: shift, dy: i ? lead : 0 }, text)));
      const label = s("g", { class: `place-label ${place.kind}`, transform: `translate(${c.x},${c.y})`, "data-place": place.id }, name, sub);
      if (crowded) this.lowered.set(place.id, { label, below: c.y + below - font });
      labels.push(label);
      this.subs.set(place.id, sub);
      this.tops.set(place.id, c.y + (crowded ? roof - 8 : roof - 30 - (lines.length - 1) * lead));
      const group = s(
        "g",
        { class: `place ${place.kind}`, transform: `translate(${c.x},${c.y})` },
        s("title", {}, `${place.name}${place.description ? `: ${place.description}` : ""}${place.hours.length ? ` · open ${place.hours.join(", ")}` : place.kind === "home" ? "" : " · always open"}`),
        s("ellipse", { class: "halo", cx: 0, cy: size.h * 0.1, rx: size.w * 0.95, ry: size.h * 0.85 }),
        s("ellipse", { class: "plot", cx: 0, cy: size.h * 0.36, rx: size.w * 0.62, ry: size.h * 0.15 }),
        building(place.kind, size.w, size.h),
      );
      this.placeGroups.set(place.id, group);
      return group;
    });
    this.labelGroups = new Map(labels.map((label) => [label.dataset.place, label]));
    this.night = s("rect", { class: "night", x: 0, y: 0, width: this.width, height: this.height });
    // Lit windows sit above the night, so an occupied house glows after dark.
    this.glows = new Map(
      places.map((place) => {
        const group = this.placeGroups.get(place.id);
        return [place.id, s("g", { transform: group.getAttribute("transform") }, [...group.querySelectorAll(".win")].map((win) => win.cloneNode()))];
      }),
    );
    this.tokenLayer = s("g", { class: "tokens" });
    this.svg.replaceChildren(
      s("rect", { class: "ground", x: 0, y: 0, width: this.width, height: this.height }),
      s("g", { class: "roads" }, roads.map((r) => s("path", { class: "road-edge", d: r.d })), roads.map((r) => s("path", { class: "road", d: r.d }))),
      s("g", { class: "trees" }, trees.map((t) => s("g", { transform: `translate(${t.x.toFixed(1)},${t.y.toFixed(1)})` }, s("ellipse", { class: "tree-shadow", cx: 1.5, cy: t.r * 0.9, rx: t.r * 0.9, ry: t.r * 0.35 }), s("circle", { class: "tree", r: t.r })))),
      s("g", { class: "places" }, groups),
      this.night,
      s("g", { class: "glow" }, [...this.glows.values()]),
      this.tokenLayer,
      s("g", { class: "labels" }, labels),
    );
    this.tokens.clear();
    for (const name of this.cast.names) {
      const g = s(
        "g",
        { class: "token", "data-agent": name },
        s("title", {}, name),
        s("circle", { class: "token-hit", r: this.r + 5 }),
        s("circle", { class: "token-select", r: this.r + 4 }),
        this.cast.glyph(name, this.r),
        s("g", { class: "thinking", transform: `translate(${this.r * 0.8},${-this.r * 1.25})` }, s("circle", { r: 4.2 }), s("circle", { cx: -5.2, cy: 5, r: 1.6 })),
      );
      g.addEventListener("click", () => this.onSelect(name));
      this.tokenLayer.append(g);
      this.tokens.set(name, { g, x: null, y: null, from: null, to: null, start: 0 });
    }
  }

  /** The horizontal room around a place: the distance to its nearest neighbour on its row. */
  gap(place) {
    const c = this.centres.get(place.id);
    const row = this.world.places.filter((other) => other !== place && Math.abs(other.y - place.y) < 0.6).map((other) => Math.abs(this.centres.get(other.id).x - c.x));
    return Math.min(140, ...row);
  }

  /** The ellipse around a place on which its people stand, just clear of the building. */
  ring(place) {
    const size = this.size(place.kind);
    return { rx: size.w / 2 + this.r + 2, ry: size.h * 0.5 + this.r * 0.7, dy: size.h * 0.08 };
  }

  /** Where each agent stands: around the front of its place, in configured order. */
  spots(state) {
    const byPlace = new Map();
    for (const name of this.cast.names) {
      const id = state.locations[name];
      if (!byPlace.has(id)) byPlace.set(id, []);
      byPlace.get(id).push(name);
    }
    const out = new Map();
    for (const [id, names] of byPlace) {
      const place = this.byId.get(id);
      const c = this.centres.get(id);
      if (!place || !c) continue;
      const ring = this.ring(place);
      const gap = this.r * 2 + 2;
      // Spread from straight below outwards along the ellipse, a badge's width apart; a
      // crowd that would climb past the sides takes a wider ring.
      let scale = 1;
      const step = () => gap / (((ring.rx + ring.ry) / 2) * scale);
      while ((names.length - 1) * step() > Math.PI) scale += 0.08;
      names.forEach((name, i) => {
        const angle = Math.PI / 2 - (i - (names.length - 1) / 2) * step();
        out.set(name, { x: c.x + ring.rx * scale * Math.cos(angle), y: c.y + ring.dy + ring.ry * scale * Math.sin(angle) });
      });
    }
    return out;
  }

  /**
   * Show a moment. `frame`: {state, minute, selected, thinking: Set of agents deciding now,
   * speech: Map(place -> [{agent, text, to}]), scenes: Map(place -> label), effects, key}.
   * `walk` lets moved agents walk instead of appearing at once.
   */
  update(frame, walk) {
    this.frame = frame;
    if (!this.width) return;
    const { state, minute } = frame;
    const light = daylight(minute);
    this.svg.style.setProperty("--dark", (1 - light).toFixed(3));
    this.svg.classList.toggle("after-dark", light < 0.45);
    this.night.style.opacity = ((1 - light) * 0.5).toFixed(3);
    const busy = new Set(Object.values(state.locations));
    for (const place of this.world.places) {
      const group = this.placeGroups.get(place.id);
      const open = isOpen(place, minute);
      group.classList.toggle("closed", !open);
      group.classList.toggle("active", frame.scenes.has(place.id));
      this.glows.get(place.id).classList.toggle("occupied", busy.has(place.id));
      const next = open ? null : opensAt(place, minute);
      const text = frame.scenes.get(place.id) ?? (open ? "" : next !== null ? `closed · opens ${hhmm(next)}` : "closed");
      const sub = this.subs.get(place.id);
      if (sub.textContent !== text) sub.textContent = text;
    }
    const spots = this.spots(state);
    for (const [id, { label, below }] of this.lowered) {
      const lowest = Math.max(-Infinity, ...this.cast.names.filter((name) => state.locations[name] === id).map((name) => spots.get(name).y + this.r + 4));
      const c = this.centres.get(id);
      label.setAttribute("transform", `translate(${c.x},${c.y + Math.max(0, lowest - below)})`);
    }
    const now = performance.now();
    for (const [name, token] of this.tokens) {
      const spot = spots.get(name);
      if (!spot) continue;
      if (token.x === null || !walk) Object.assign(token, { x: spot.x, y: spot.y, from: null, to: null });
      else if ((!token.to && (token.x !== spot.x || token.y !== spot.y)) || (token.to && (token.to.x !== spot.x || token.to.y !== spot.y)))
        Object.assign(token, { from: { x: token.x, y: token.y }, to: spot, start: now });
      token.g.classList.toggle("selected", frame.selected === name);
      token.g.classList.toggle("deciding", frame.thinking.has(name));
      token.g.classList.toggle("asleep", light < 0.25 && this.byId.get(state.locations[name])?.kind === "home");
      if (!token.to) token.g.setAttribute("transform", `translate(${token.x.toFixed(1)},${token.y.toFixed(1)})`);
    }
    if (frame.key !== this.bubbleKey) {
      this.bubbleKey = frame.key;
      this.bubbles(frame);
    }
    for (const effect of frame.effects ?? []) this.effect(effect, spots);
  }

  /** Advance walking agents; returns whether anyone is still walking. */
  tick(now) {
    let moving = false;
    for (const token of this.tokens.values()) {
      if (!token.to) continue;
      const t = Math.min(1, (now - token.start) / WALK_MS);
      const e = t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2;
      token.x = token.from.x + (token.to.x - token.from.x) * e;
      token.y = token.from.y + (token.to.y - token.from.y) * e;
      token.g.setAttribute("transform", `translate(${token.x.toFixed(1)},${token.y.toFixed(1)})`);
      if (t >= 1) Object.assign(token, { x: token.to.x, y: token.to.y, from: null, to: null });
      else moving = true;
    }
    return moving;
  }

  bubbles(frame) {
    const out = [];
    for (const [id, lines] of frame.speech) {
      const c = this.centres.get(id);
      if (!c || !lines.length) continue;
      const ring = this.ring(this.byId.get(id));
      out.push(
        h(
          "div",
          { class: "speech-stack", "data-below": Math.round(c.y + ring.dy + ring.ry + this.r + 8), style: { left: `${Math.max(90, Math.min(this.width - 90, c.x))}px`, bottom: `${this.height - this.tops.get(id)}px` } },
          lines.slice(-3).map((line) =>
            h(
              "div",
              { class: "speech" },
              h("div", { class: "speech-who" }, this.cast.badge(line.agent, 14), h("b", {}, line.agent), line.to ? h("span", { class: "muted" }, ` to ${line.to}`) : null),
              h("div", { class: "speech-text" }, line.text),
            ),
          ),
        ),
      );
    }
    this.overlay.replaceChildren(...out, ...this.overlay.querySelectorAll(".effect"));
    // A stack that would rise past the top of the map keeps fewer lines, or hangs below.
    for (const stack of out) {
      while (stack.offsetTop < 0 && stack.children.length > 1) stack.firstChild.remove();
      if (stack.offsetTop < 0) {
        stack.style.bottom = "";
        stack.style.top = `${stack.dataset.below}px`;
        stack.classList.add("below");
      }
    }
  }

  effect({ agent, text, tone }, spots) {
    const spot = spots.get(agent);
    if (!spot) return;
    const node = h("div", { class: `effect tone-${tone}`, style: { left: `${spot.x}px`, top: `${spot.y - this.r - 8}px` } }, text);
    node.addEventListener("animationend", () => node.remove());
    this.overlay.append(node);
  }

  /** Cover the map with a message while the moment cannot be shown, or uncover it. */
  cover(message, failed = false) {
    this.curtain.hidden = !message;
    this.curtain.classList.toggle("failed", failed);
    if (message) this.curtain.replaceChildren(h("div", { class: failed ? "curtain-error" : "loading" }, failed ? icon("alert", 18) : null, message));
  }

  destroy() {
    this.stop();
  }
}
