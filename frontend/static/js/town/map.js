// The town on a map. The scenery is drawn once from the town's plan; above it the light of the
// simulated hour, lit windows and lamps, and the residents, who walk the streets between places,
// gather in front of them and turn to one another when they talk. Names of places, speech and
// the money people earn and pay float in a screen-space layer whose boxes are laid out together
// so none covers another, speech first: a place name gives way to speech, never the reverse.
//
// The map pans and zooms by touch, mouse, wheel and buttons. Residents keep a least size on
// screen, so they stay legible however far the town is zoomed out.

import { daylight, hhmm, isOpen, opensAt } from "../clock.js";
import { h, s } from "../dom.js";
import { icon } from "../icons.js";
import { shortName } from "../world.js";
import { f, lengthOf, pointAlong, townPlan, walkways } from "./plan.js";
import { drawScenery } from "./scenery.js";

const FIGURE = 31; // a resident's height in the drawing
const SCALE = 1.35; // ...and the scale it stands at in the world, beside its buildings
const MIN_FIGURE = 30; // the least height a resident shows on screen
const WALK = 150; // world pixels per second
const GAP = 6; // screen pixels kept between floating boxes

/** The colour the light of each hour multiplies the scenery by; white is full day. */
const SKY = [
  [0, "#46548a"],
  [270, "#46548a"],
  [330, "#7d74a6"],
  [390, "#e8b9a4"],
  [450, "#fbeadb"],
  [540, "#ffffff"],
  [990, "#ffffff"],
  [1065, "#ffeacb"],
  [1125, "#f8c9a0"],
  [1180, "#e0aea4"],
  [1220, "#a497bb"],
  [1265, "#606b99"],
  [1320, "#46548a"],
  [1440, "#46548a"],
];

function skyAt(minute) {
  const i = SKY.findIndex(([m]) => m > minute);
  const [m0, c0] = SKY[Math.max(0, i - 1)];
  const [m1, c1] = SKY[i < 0 ? SKY.length - 1 : i];
  const t = m1 === m0 ? 0 : (minute - m0) / (m1 - m0);
  const rgb = (c) => [1, 3, 5].map((k) => parseInt(c.slice(k, k + 2), 16));
  const [a, b] = [rgb(c0), rgb(c1)];
  return `rgb(${a.map((v, k) => Math.round(v + (b[k] - v) * t)).join(",")})`;
}

const area = (a, b) => Math.max(0, Math.min(a.x1, b.x1) - Math.max(a.x0, b.x0)) * Math.max(0, Math.min(a.y1, b.y1) - Math.max(a.y0, b.y0));
const box = (x, y, w, hgt) => ({ x0: x, y0: y, x1: x + w, y1: y + hgt });
const grow = (r, d) => ({ x0: r.x0 - d, y0: r.y0 - d, x1: r.x1 + d, y1: r.y1 + d });
const reduced = matchMedia("(prefers-reduced-motion: reduce)");

export class TownMap {
  constructor({ world, cast, onSelect }) {
    this.world = world;
    this.cast = cast;
    this.onSelect = onSelect;
    this.plan = townPlan(world);
    this.path = walkways(this.plan);
    this.byId = new Map(world.places.map((place) => [place.id, place]));
    const { svg, places } = drawScenery(this.plan);
    this.sites = places;

    const { width, height } = this.plan;
    this.light = h("div", { class: "map-light" });
    this.glow = s("svg", { class: "map-glow", width, height, viewBox: `0 0 ${width} ${height}`, "aria-hidden": "true" });
    this.actors = s("svg", { class: "map-actors", width, height, viewBox: `0 0 ${width} ${height}`, "aria-hidden": "true" });
    this.ambient = h("div", { class: "map-ambient", "aria-hidden": "true" }, h("div", { class: "cloud one" }), h("div", { class: "cloud two" }));
    this.worldEl = h("div", { class: "map-world", style: { width: `${width}px`, height: `${height}px` } }, svg, this.ambient, this.light, this.glow, this.actors);
    this.overlay = h("div", { class: "map-overlay", "aria-hidden": "true" });
    this.curtain = h("div", { class: "map-curtain", hidden: true });
    const zoomButton = (glyph, label, action) => h("button", { type: "button", class: "map-btn", "aria-label": label, title: label, onclick: action }, icon(glyph, 18));
    this.controls = h("div", { class: "map-controls" }, zoomButton("plus", "Zoom in", () => this.zoomBy(1.6)), zoomButton("minus", "Zoom out", () => this.zoomBy(1 / 1.6)), zoomButton("fit", "Show the whole town", () => this.fitView(true)));
    this.el = h("div", { class: "map", role: "img", "aria-label": "Map of the town" }, this.worldEl, this.overlay, this.controls, this.curtain);

    this.view = { s: 1, x: 0, y: 0 };
    this.auto = true; // the view fits the town until the reader pans or zooms
    this.size = { w: 0, h: 0 };
    this.inset = 0; // screen pixels at the bottom of the map that something else covers
    this.frame = null;
    this.tokens = new Map();
    this.spots = new Map();
    this.placesState = new Map(); // id -> {open, occupied, scene}
    this.boxes = { labels: new Map(), bubbles: [], tag: null };
    this.animation = null;
    this.drawLights();
    this.drawActors();
    this.drawLabels();
    this.gestures();
    this.resize = new ResizeObserver(([entry]) => {
      const w = Math.round(entry.contentRect.width);
      const hgt = Math.round(entry.contentRect.height);
      if (!w || !hgt || (w === this.size.w && hgt === this.size.h)) return;
      this.size = { w, h: hgt };
      if (this.auto) this.fitView(false);
      else this.setView(this.view);
    });
    this.resize.observe(this.el);
  }

  // Layers ------------------------------------------------------------------------------------

  drawLights() {
    const parts = [s("defs", {}, s("radialGradient", { id: "lamp-glow" }, s("stop", { offset: "0", "stop-color": "var(--m-glow)", "stop-opacity": "0.55" }), s("stop", { offset: "1", "stop-color": "var(--m-glow)", "stop-opacity": "0" })))];
    this.lit = new Map();
    for (const [id, site] of this.sites) {
      const windows = site.windows.map((w) => s("path", { class: "lit", d: w.arch ? `M${f(w.x)},${f(w.y + w.h)}V${f(w.y + w.w / 2)}A${f(w.w / 2)},${f(w.w / 2)} 0 0 1 ${f(w.x + w.w)},${f(w.y + w.w / 2)}V${f(w.y + w.h)}Z` : `M${f(w.x)},${f(w.y)}h${f(w.w)}v${f(w.h)}h${f(-w.w)}Z` }));
      const g = s("g", { class: "lit-place" }, windows);
      this.lit.set(id, g);
      parts.push(g);
    }
    this.lamps = s(
      "g",
      { class: "lamps" },
      this.plan.lamps.map((l) => [s("circle", { cx: f(l.x), cy: f(l.y - 15), r: 26, fill: "url(#lamp-glow)" }), s("circle", { class: "lamp-lit", cx: f(l.x), cy: f(l.y - 15), r: 2.2 })]),
    );
    parts.push(this.lamps);
    this.glow.replaceChildren(...parts);
    this.smoke = new Map();
    for (const [id, site] of this.sites) {
      if (!site.smoke) continue;
      const puff = h("div", { class: "smoke", style: { left: `${site.smoke.x}px`, top: `${site.smoke.y}px` } }, h("i"), h("i"), h("i"));
      this.smoke.set(id, puff);
      this.ambient.append(puff);
    }
  }

  drawActors() {
    for (const name of this.cast.names) {
      const slot = this.cast.slot(name);
      const legs = [s("path", { class: "leg", d: "M-2.2,-10V-1" }), s("path", { class: "leg", d: "M2.2,-10V-1" })];
      const figure = s(
        "g",
        { class: "figure" },
        legs,
        s("path", { class: "arms", d: "M-5.6,-17.5L-7.4,-10.5M5.6,-17.5L7.4,-10.5", style: { stroke: `var(--a${slot}-shade)` } }),
        s("path", { class: "torso", d: "M-5.6,-9.5Q-6.4,-18 -3,-19.4H3Q6.4,-18 5.6,-9.5Z", style: { fill: `var(--a${slot}-shade)` } }),
      );
      const head = s("g", { class: "head", transform: "translate(0,-24.5)" }, this.cast.glyph(name, 6.8));
      const g = s(
        "g",
        { class: "actor", "data-agent": name },
        s("ellipse", { class: "actor-ring", rx: 12, ry: 4.2 }),
        s("ellipse", { class: "actor-shadow", rx: 6.5, ry: 2.2 }),
        figure,
        head,
        s("g", { class: "thinking", transform: "translate(9,-35)" }, s("circle", { r: 3.8 }), s("circle", { cx: -4.6, cy: 4.8, r: 1.6 })),
        s("text", { class: "zz", x: 6.5, y: -12 }, "z"),
      );
      this.actors.append(g);
      this.tokens.set(name, { g, figure, head, legs, x: null, y: null, walk: null, facing: 0, asleep: false, k: 1 });
    }
  }

  drawLabels() {
    for (const place of this.world.places) {
      const name = h("span", { class: "label-name" }, shortName(place));
      const status = h("span", { class: "label-status" });
      const el = h("div", { class: `place-label ${place.kind}`, "data-place": place.id }, name, status);
      this.overlay.append(el);
      this.boxes.labels.set(place.id, { el, name, status, text: "", size: null, compact: null, priority: 0 });
    }
    this.tag = h("div", { class: "name-tag", hidden: true });
    this.overlay.append(this.tag);
  }

  // The view ------------------------------------------------------------------------------------

  /** The scale and offset that show the whole town in the map's current size. */
  fitted() {
    const { fit } = this.plan;
    const { w, h: hgt } = this.size;
    const scale = Math.min(w / (fit.x1 - fit.x0), hgt / (fit.y1 - fit.y0));
    return { s: scale, x: w / 2 - ((fit.x0 + fit.x1) / 2) * scale, y: hgt / 2 - ((fit.y0 + fit.y1) / 2) * scale };
  }

  fitView(animate) {
    if (!this.size.w) return;
    this.auto = true;
    if (animate) this.animateTo(this.fitted());
    else this.setView(this.fitted());
  }

  /** Keep the view within sensible bounds: some of the town always in sight. */
  clamp(view) {
    const base = this.fitted().s;
    const scale = Math.max(base * 0.8, Math.min(Math.max(base * 5, 2.6), view.s));
    const { fit } = this.plan;
    const { w, h: hgt } = this.size;
    // The centre of the screen stays over the town.
    const cx = Math.max(fit.x0, Math.min(fit.x1, (w / 2 - view.x) / scale));
    const cy = Math.max(fit.y0, Math.min(fit.y1, (hgt / 2 - view.y) / scale));
    return { s: scale, x: w / 2 - cx * scale, y: hgt / 2 - cy * scale };
  }

  setView(view) {
    this.view = this.clamp(view);
    const { s: scale, x, y } = this.view;
    this.worldEl.style.transform = `translate(${x.toFixed(2)}px,${y.toFixed(2)}px) scale(${scale.toFixed(4)})`;
    const k = Math.max(SCALE, MIN_FIGURE / (FIGURE * scale));
    if (Math.abs(k - (this.k ?? 0)) > 0.01) {
      this.k = k;
      if (this.frame) this.layoutPeople(false);
    }
    this.placeOverlay();
  }

  zoomBy(factor, at = null) {
    const { w, h: hgt } = this.size;
    const p = at ?? { x: w / 2, y: hgt / 2 };
    const target = this.clamp({ ...this.view, s: this.view.s * factor });
    const scale = target.s;
    const wx = (p.x - this.view.x) / this.view.s;
    const wy = (p.y - this.view.y) / this.view.s;
    this.auto = false;
    this.animateTo({ s: scale, x: p.x - wx * scale, y: p.y - wy * scale });
  }

  /** Say how much of the map's bottom is covered (by an open sheet); floating boxes avoid it. */
  setInset(bottom) {
    if (Math.abs(bottom - this.inset) < 1) return;
    this.inset = bottom;
    this.placeOverlay();
  }

  /** Bring a resident into view if they are off screen or under the covered bottom. */
  reveal(name) {
    const inset = { top: 0, bottom: this.inset };
    const token = this.tokens.get(name);
    if (!token || token.x === null) return;
    const { s: scale, x, y } = this.view;
    const sx = token.x * scale + x;
    const sy = token.y * scale + y;
    const margin = 48;
    if (sx > margin && sx < this.size.w - margin && sy > margin + inset.top && sy < this.size.h - margin - inset.bottom) return;
    this.auto = false;
    const visible = (this.size.h - inset.top - inset.bottom) / 2 + inset.top;
    this.animateTo({ s: scale, x: this.size.w / 2 - token.x * scale, y: visible - token.y * scale });
  }

  animateTo(target) {
    const end = this.clamp(target);
    if (reduced.matches) return this.setView(end);
    this.animation = { from: { ...this.view }, to: end, start: performance.now() };
    this.worldEl.classList.add("moving");
  }

  gestures() {
    const el = this.el;
    const pointers = new Map();
    let pan = null;
    let lastTap = 0;
    let idle = null;
    const moving = () => {
      this.worldEl.classList.add("moving");
      clearTimeout(idle);
      idle = setTimeout(() => this.worldEl.classList.remove("moving"), 180);
    };
    const local = (event) => {
      const r = el.getBoundingClientRect();
      return { x: event.clientX - r.left, y: event.clientY - r.top };
    };
    const begin = () => {
      const points = [...pointers.values()];
      const mid = points.length > 1 ? { x: (points[0].x + points[1].x) / 2, y: (points[0].y + points[1].y) / 2 } : points[0];
      pan = { view: { ...this.view }, mid, dist: points.length > 1 ? Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y) : 0, moved: pan?.moved ?? false, count: points.length };
    };
    el.addEventListener("pointerdown", (event) => {
      if (event.target.closest(".map-controls, .map-curtain:not([hidden])") || (event.pointerType === "mouse" && event.button !== 0)) return;
      el.setPointerCapture(event.pointerId);
      pointers.set(event.pointerId, local(event));
      this.animation = null;
      begin();
    });
    el.addEventListener("pointermove", (event) => {
      if (!pointers.has(event.pointerId)) return;
      pointers.set(event.pointerId, local(event));
      const points = [...pointers.values()];
      const mid = points.length > 1 ? { x: (points[0].x + points[1].x) / 2, y: (points[0].y + points[1].y) / 2 } : points[0];
      if (!pan.moved && Math.hypot(mid.x - pan.mid.x, mid.y - pan.mid.y) < 6 && points.length < 2) return;
      pan.moved = true;
      this.auto = false;
      moving();
      const scale = points.length > 1 && pan.dist ? pan.view.s * (Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y) / pan.dist) : pan.view.s;
      const wx = (pan.mid.x - pan.view.x) / pan.view.s;
      const wy = (pan.mid.y - pan.view.y) / pan.view.s;
      this.setView({ s: scale, x: mid.x - wx * scale, y: mid.y - wy * scale });
      el.classList.add("grabbing");
    });
    const end = (event) => {
      if (!pointers.has(event.pointerId)) return;
      const point = pointers.get(event.pointerId);
      pointers.delete(event.pointerId);
      el.classList.remove("grabbing");
      if (pointers.size) return begin();
      if (pan && !pan.moved && event.type === "pointerup") {
        const now = performance.now();
        if (now - lastTap < 320) {
          lastTap = 0;
          this.zoomBy(1.8, point);
        } else {
          lastTap = now;
          const hit = this.hit(point);
          if (hit) this.onSelect(hit);
        }
      }
      pan = null;
    };
    el.addEventListener("pointerup", end);
    el.addEventListener("pointercancel", end);
    el.addEventListener(
      "wheel",
      (event) => {
        event.preventDefault();
        this.animation = null;
        this.auto = false;
        moving();
        const factor = Math.exp(-event.deltaY * (event.ctrlKey ? 0.01 : 0.0018));
        const p = local(event);
        const scale = this.clamp({ ...this.view, s: this.view.s * factor }).s;
        const wx = (p.x - this.view.x) / this.view.s;
        const wy = (p.y - this.view.y) / this.view.s;
        this.setView({ s: scale, x: p.x - wx * scale, y: p.y - wy * scale });
      },
      { passive: false },
    );
    // Safari's own pinch gestures would zoom the page instead of the map.
    el.addEventListener("gesturestart", (event) => event.preventDefault());
  }

  /** The resident nearest a point on screen, if close enough to mean them. */
  hit(point) {
    let best = null;
    const { s: scale, x, y } = this.view;
    for (const [name, token] of this.tokens) {
      if (token.x === null) continue;
      const k = this.k ?? 1;
      const cx = token.x * scale + x;
      const cy = (token.y - (token.asleep ? 8 : 15) * k) * scale + y;
      const d = Math.hypot(point.x - cx, point.y - cy);
      if (d < Math.max(24, 14 * k * scale) && (!best || d < best[1])) best = [name, d];
    }
    return best?.[0] ?? null;
  }

  // The moment --------------------------------------------------------------------------------

  /**
   * Show a moment. `frame`: {state, minute, selected, thinking: Set of agents deciding now,
   * speech: Map(place -> [{agent, text, to}]), scenes: Map(place -> {kind, present, label}),
   * effects: [{agent, text, tone}], key}. `walk` lets residents who moved walk there.
   */
  update(frame, walk) {
    const previous = this.frame;
    this.frame = frame;
    const { state, minute } = frame;
    if (minute !== previous?.minute) this.daylight(minute);
    const occupied = new Set(Object.values(state.locations));
    const dark = 1 - daylight(minute);
    let labelsChanged = false;
    for (const place of this.world.places) {
      const open = isOpen(place, minute);
      const scene = frame.scenes.get(place.id) ?? null;
      const site = this.sites.get(place.id);
      site.group.classList.toggle("closed", !open);
      site.group.classList.toggle("open", open && place.kind !== "home");
      this.lit.get(place.id).classList.toggle("on", occupied.has(place.id) && dark > 0.12);
      this.smoke.get(place.id)?.classList.toggle("on", occupied.has(place.id));
      const next = open ? null : opensAt(place, minute);
      const text = scene?.label ?? (open ? "" : next !== null ? `closed · opens ${hhmm(next)}` : "closed");
      const label = this.boxes.labels.get(place.id);
      label.priority = scene ? 3 : place.kind === "home" ? 1 : 2;
      label.el.classList.toggle("active", Boolean(scene));
      if (label.text !== text) {
        label.text = text;
        label.status.textContent = text;
        label.size = null;
        labelsChanged = true;
      }
    }
    const peopleKey = `${state.seq}|${frame.selected}|${[...frame.thinking].join()}|${frame.key}|${dark > 0.7}`;
    if (peopleKey !== this.peopleKey) {
      this.peopleKey = peopleKey;
      this.layoutPeople(walk);
    }
    if (frame.key !== previous?.key || labelsChanged || frame.selected !== previous?.selected) {
      this.bubbles(frame);
      this.placeOverlay();
    }
    for (const effect of frame.effects ?? []) this.effect(effect);
  }

  daylight(minute) {
    const light = daylight(minute);
    this.light.style.backgroundColor = skyAt(minute);
    this.el.style.setProperty("--dark", (1 - light).toFixed(3));
    this.el.classList.toggle("night", light < 0.4);
  }

  /** Where everyone stands, and which way they face. */
  standing() {
    const { state, minute } = this.frame;
    const k = this.k ?? 1;
    const asleep = 1 - daylight(minute) > 0.7;
    const groups = new Map();
    for (const name of this.cast.names) {
      const id = state.locations[name];
      if (!groups.has(id)) groups.set(id, []);
      groups.get(id).push(name);
    }
    const out = new Map();
    for (const [id, names] of groups) {
      const p = this.plan.byId.get(id);
      if (!p) continue;
      const place = this.byId.get(id);
      if (asleep && place.kind === "home") {
        names.forEach((name, i) => out.set(name, { x: p.door.x + (i - (names.length - 1) / 2) * 13 * k, y: p.base + 9 * k, facing: 0, asleep: true }));
        continue;
      }
      const scene = this.frame.scenes.get(id);
      const circle = scene && scene.kind !== "work" ? names.filter((name) => scene.present.includes(name)) : [];
      const rest = names.filter((name) => !circle.includes(name));
      const yardMid = (p.yard.x0 + p.yard.x1) / 2;
      if (circle.length) {
        // A conversation: a ring in front of the place, everyone facing its middle.
        const c = { x: yardMid, y: p.base + 20 * k };
        const radius = Math.max(15, circle.length * 5.5) * k;
        circle.forEach((name, i) => {
          const a = Math.PI / 2 + ((i + 0.5) / circle.length) * Math.PI * 2;
          const x = c.x + Math.cos(a) * radius;
          out.set(name, { x, y: c.y + Math.sin(a) * radius * 0.5, facing: Math.abs(x - c.x) < 3 ? 0 : x < c.x ? 1 : -1 });
        });
      }
      // Everyone else in rows across the front.
      const per = Math.max(3, Math.floor((p.yard.x1 - p.yard.x0 + 20) / (17 * k)));
      const startY = p.base + (circle.length ? 46 : 14) * k;
      rest.forEach((name, i) => {
        const row = Math.floor(i / per);
        const inRow = Math.min(per, rest.length - row * per);
        const col = i - row * per;
        out.set(name, { x: yardMid + (col - (inRow - 1) / 2) * 17 * k + (row % 2) * 6 * k, y: startY + row * 15 * k, facing: 0 });
      });
    }
    // Speakers turn to the one they address, if both are there.
    const latest = new Map();
    for (const lines of this.frame.speech.values()) for (const line of lines) latest.set(line.agent, line);
    for (const [name, line] of latest) {
      const a = out.get(name);
      const b = line.to && out.get(line.to);
      if (a && b && !a.asleep) a.facing = b.x > a.x + 2 ? 1 : b.x < a.x - 2 ? -1 : a.facing;
    }
    return out;
  }

  layoutPeople(walk) {
    const spots = this.standing();
    this.spots = spots;
    const now = performance.now();
    const k = this.k ?? 1;
    const { state, selected, thinking } = this.frame;
    for (const [name, token] of this.tokens) {
      const spot = spots.get(name);
      if (!spot) {
        token.g.setAttribute("visibility", "hidden");
        continue;
      }
      token.g.removeAttribute("visibility");
      token.facing = spot.facing;
      const was = token.place;
      token.place = state.locations[name];
      if (token.x === null || !walk || reduced.matches) Object.assign(token, { x: spot.x, y: spot.y, walk: null });
      else if (was !== token.place) {
        // Walk the streets from where they are to the new place.
        const road = this.path(was, token.place) ?? [];
        const line = [{ x: token.x, y: token.y }, ...road, spot];
        const length = lengthOf(line);
        token.walk = { line, length, start: now, duration: Math.max(700, Math.min(2600, (length / WALK) * 1000)) };
      } else if (token.walk) token.walk.line[token.walk.line.length - 1] = spot;
      else Object.assign(token, { x: spot.x, y: spot.y });
      token.asleep = spot.asleep ?? false;
      token.k = k;
      token.g.classList.toggle("selected", selected === name);
      token.g.classList.toggle("deciding", thinking.has(name));
      token.g.classList.toggle("asleep", token.asleep);
      this.pose(token, now);
    }
    this.sortActors();
  }

  /** Place a resident's drawing: position, size, facing and, while walking, their stride. */
  pose(token, now) {
    let stride = 0;
    if (token.walk) {
      const t = Math.min(1, (now - token.walk.start) / token.walk.duration);
      const eased = t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2;
      const p = pointAlong(token.walk.line, eased * token.walk.length);
      token.x = p.x;
      token.y = p.y;
      token.facing = p.dx > 0.5 ? 1 : p.dx < -0.5 ? -1 : token.facing;
      stride = Math.sin((now - token.walk.start) / 70);
      if (t >= 1) {
        const end = token.walk.line.at(-1);
        Object.assign(token, { x: end.x, y: end.y, walk: null });
        token.facing = this.spots.get(token.g.dataset.agent)?.facing ?? 0;
        stride = 0;
      }
    }
    const k = token.k;
    token.g.setAttribute("transform", `translate(${f(token.x)},${f(token.y)}) scale(${k.toFixed(3)})`);
    const lean = token.facing * 1.4;
    token.figure.setAttribute("transform", `translate(0,${f(-Math.abs(stride) * 1.2)}) skewX(${f(-lean * 4)})`);
    token.head.setAttribute("transform", token.asleep ? "translate(0,-8) scale(0.8)" : `translate(${f(lean)},${f(-24.5 - Math.abs(stride) * 1.2)})`);
    token.legs[0].setAttribute("transform", `rotate(${f(stride * 22)},-2.2,-10)`);
    token.legs[1].setAttribute("transform", `rotate(${f(-stride * 22)},2.2,-10)`);
  }

  /** Draw nearer residents over farther ones. */
  sortActors() {
    const order = [...this.tokens.values()].filter((t) => t.x !== null).sort((a, b) => a.y - b.y);
    if (order.every((t, i) => this.actors.children[i] === t.g)) return;
    this.actors.append(...order.map((t) => t.g));
  }

  /** Advance walking residents and view animations; called every animation frame. */
  tick(now) {
    if (this.animation) {
      const { from, to, start } = this.animation;
      const t = Math.min(1, (now - start) / 260);
      const e = 1 - (1 - t) ** 3;
      this.setView({ s: from.s + (to.s - from.s) * e, x: from.x + (to.x - from.x) * e, y: from.y + (to.y - from.y) * e });
      if (t >= 1) {
        this.animation = null;
        this.worldEl.classList.remove("moving");
      }
    }
    let walking = false;
    for (const token of this.tokens.values())
      if (token.walk) {
        walking = true;
        this.pose(token, now);
      }
    if (walking) this.sortActors();
    else if (this.wasWalking) this.placeOverlay();
    this.wasWalking = walking;
  }

  // Floating boxes ------------------------------------------------------------------------------

  bubbles(frame) {
    for (const old of this.boxes.bubbles) old.el.remove();
    this.boxes.bubbles = [];
    for (const [id, lines] of frame.speech) {
      if (!lines.length) continue;
      const el = h(
        "div",
        { class: "bubble", "data-place": id },
        lines.slice(-2).map((line) =>
          h(
            "div",
            { class: "bubble-line" },
            h("div", { class: "bubble-who" }, this.cast.badge(line.agent, 14), h("b", {}, line.agent), line.to ? h("span", { class: "bubble-to" }, `to ${line.to}`) : null),
            h("p", { class: "bubble-text" }, line.text),
          ),
        ),
        h("span", { class: "tail" }),
      );
      this.overlay.append(el);
      this.boxes.bubbles.push({ el, place: id, speakers: [...new Set(lines.slice(-2).map((line) => line.agent))], size: null });
    }
    const selected = frame.selected;
    this.tag.hidden = !selected;
    if (selected && this.tag.dataset.agent !== selected) {
      this.tag.dataset.agent = selected;
      this.tag.replaceChildren(h("b", {}, selected));
      this.tagSize = null;
    }
  }

  /** Lay out names, speech and the selected name tag so that none covers another. */
  placeOverlay() {
    if (!this.size.w || !this.frame) return;
    const { s: scale, x: vx, y: vy } = this.view;
    const k = this.k ?? 1;
    const W = this.size.w;
    const H = Math.max(120, this.size.h - this.inset);
    const screen = (x, y) => ({ x: x * scale + vx, y: y * scale + vy });
    // Measure what has changed since the last layout, all at once.
    const labels = [...this.boxes.labels.entries()];
    for (const [, label] of labels)
      if (!label.size) {
        label.el.classList.remove("compact");
        label.el.style.visibility = "";
      }
    for (const [, label] of labels)
      if (!label.size) {
        const w = label.el.offsetWidth;
        const text = Math.max(label.name.offsetWidth, label.status.offsetWidth);
        label.size = { w, h: label.el.offsetHeight, compact: w - text + label.name.offsetWidth, nameH: label.name.offsetHeight + (label.el.offsetHeight - label.name.offsetHeight - (label.text ? label.status.offsetHeight : 0)) };
      }
    for (const bubble of this.boxes.bubbles) if (!bubble.size) bubble.size = { w: bubble.el.offsetWidth, h: bubble.el.offsetHeight };
    if (!this.tag.hidden && !this.tagSize) this.tagSize = { w: this.tag.offsetWidth, h: this.tag.offsetHeight };

    // Residents' heads are hard obstacles for names; speech may only lean on them a little.
    const heads = [];
    for (const [name, spot] of this.spots) {
      const token = this.tokens.get(name);
      const at = token?.walk ? { x: token.x, y: token.y } : spot;
      const top = screen(at.x, at.y - (spot.asleep ? 14 : FIGURE) * k);
      const foot = screen(at.x, at.y);
      const half = Math.max(8, 8 * k * scale);
      heads.push({ name, box: { x0: top.x - half, y0: top.y - 2, x1: top.x + half, y1: foot.y + 2 } });
    }
    const placed = [];
    const inside = (r) => r.x0 >= GAP && r.y0 >= GAP && r.x1 <= W - GAP && r.y1 <= H - GAP;
    const clampBox = (r) => {
      const dx = Math.max(GAP - r.x0, Math.min(0, W - GAP - r.x1));
      const dy = Math.max(GAP - r.y0, Math.min(0, H - GAP - r.y1));
      return { x0: r.x0 + dx, y0: r.y0 + dy, x1: r.x1 + dx, y1: r.y1 + dy };
    };
    const labelGuess = new Map(labels.map(([id, label]) => {
      const p = this.plan.byId.get(id);
      const a = screen(p.x, p.top);
      return [id, box(a.x - label.size.w / 2, a.y - label.size.h - 4, label.size.w, label.size.h)];
    }));

    // Speech first: the stars of the map. It keeps clear of other speech and of people, and
    // where it can, of buildings (the scene it belongs to above all) and of names.
    const buildings = this.plan.places.map((p) => {
      const a = screen(p.rect.x0, p.top);
      const b = screen(p.rect.x1, p.base);
      return { id: p.id, x0: a.x, y0: a.y, x1: b.x, y1: b.y };
    });
    for (const bubble of this.boxes.bubbles) {
      const speakers = bubble.speakers.map((name) => this.spots.get(name)).filter(Boolean);
      const p = this.plan.byId.get(bubble.place);
      const top = speakers.length ? screen(speakers.reduce((a, q) => a + q.x, 0) / speakers.length, Math.min(...speakers.map((q) => q.y)) - FIGURE * k) : screen(p.x, p.base);
      const bottom = speakers.length ? Math.max(...speakers.map((q) => screen(q.x, q.y).y)) : top.y;
      const { w, h: hgt } = bubble.size;
      const candidates = [
        ["above", top.x - w / 2, top.y - hgt - 12],
        ["above", top.x - w + 26, top.y - hgt - 12],
        ["above", top.x - 26, top.y - hgt - 12],
        ["right", top.x + 22, top.y - hgt / 2 + 6],
        ["left", top.x - w - 22, top.y - hgt / 2 + 6],
        ["below", top.x - w / 2, bottom + 12],
      ];
      let best = null;
      candidates.forEach(([side, x, y], order) => {
        const raw = box(x, y, w, hgt);
        const r = clampBox(raw);
        const shift = Math.abs(r.x0 - raw.x0) + Math.abs(r.y0 - raw.y0);
        let score = order * 6 + shift * 2;
        for (const other of placed) score += area(grow(r, GAP), other.box) * 50;
        for (const head of heads) score += area(r, head.box) * 4;
        for (const b of buildings) score += area(r, b) * (b.id === bubble.place ? 1.5 : 0.6);
        for (const [id, guess] of labelGuess) score += area(r, guess) * (id === bubble.place ? 1.5 : 0.5);
        if (!best || score < best.score) best = { side, box: r, score };
      });
      placed.push({ box: best.box });
      this.position(bubble.el, best.box);
      bubble.el.dataset.side = best.side;
      const tail = best.side === "above" || best.side === "below" ? top.x - best.box.x0 : top.y - best.box.y0;
      bubble.el.style.setProperty("--tail", `${Math.max(14, Math.min((best.side === "above" || best.side === "below" ? w : hgt) - 14, tail)).toFixed(1)}px`);
    }

    // The selected resident's name, under their feet or over their head.
    if (!this.tag.hidden && this.tagSize) {
      const spot = this.spots.get(this.frame.selected);
      const token = this.tokens.get(this.frame.selected);
      if (spot && token) {
        const at = token.walk ? token : spot;
        const foot = screen(at.x, at.y);
        const top = screen(at.x, at.y - FIGURE * k);
        const { w, h: hgt } = this.tagSize;
        const options = [box(foot.x - w / 2, foot.y + 6, w, hgt), box(top.x - w / 2, top.y - hgt - 6, w, hgt)];
        const chosen = options.find((r) => inside(r) && !placed.some((o) => area(grow(r, 2), o.box))) ?? clampBox(options[0]);
        placed.push({ box: chosen });
        this.position(this.tag, chosen);
      }
    }

    // Names of places, the busiest first, beside their building and clear of speech, other
    // names and people, and of buildings where they can be; a name that finds no room drops its
    // status line, and then, until there is room again, itself.
    labels.sort((a, b) => b[1].priority - a[1].priority);
    for (const [id, label] of labels) {
      const p = this.plan.byId.get(id);
      const top = screen(p.x, p.top);
      const left = screen(p.rect.x0, (p.top + p.base) / 2);
      const right = screen(p.rect.x1, (p.top + p.base) / 2);
      const under = screen(p.x, p.yard.y1);
      let chosen = null;
      for (const compact of label.text ? [false, true] : [false]) {
        const w = compact ? label.size.compact : label.size.w;
        const hgt = compact ? label.size.nameH : label.size.h;
        const options = [box(top.x - w / 2, top.y - hgt - 2, w, hgt), box(right.x + 2, right.y - hgt / 2, w, hgt), box(left.x - w - 2, left.y - hgt / 2, w, hgt), box(under.x - w / 2, under.y, w, hgt)];
        let best = null;
        options.forEach((raw, order) => {
          // At the edge of the map a name may slide along it, a little.
          const r = clampBox(raw);
          const shift = Math.abs(r.x0 - raw.x0) + Math.abs(r.y0 - raw.y0);
          if (shift > w * 0.6 || placed.some((o) => area(grow(r, GAP / 2), o.box)) || heads.some((head) => area(r, head.box) > 4)) return;
          const score = order * 30 + shift * 2 + buildings.reduce((sum, b) => sum + area(r, b), 0);
          if (!best || score < best.score) best = { r, score };
        });
        chosen = best?.r ?? null;
        if (chosen) {
          label.el.classList.toggle("compact", compact);
          break;
        }
      }
      label.el.style.visibility = chosen ? "" : "hidden";
      if (!chosen) continue;
      placed.push({ box: chosen });
      this.position(label.el, chosen);
    }
  }

  position(el, r) {
    el.style.transform = `translate(${r.x0.toFixed(1)}px,${r.y0.toFixed(1)}px)`;
  }

  effect({ agent, text, tone }) {
    const token = this.tokens.get(agent);
    if (!token || token.x === null) return;
    const { s: scale, x, y } = this.view;
    const node = h("div", { class: `effect tone-${tone}`, style: { left: `${token.x * scale + x}px`, top: `${(token.y - FIGURE * (this.k ?? 1)) * scale + y - 6}px` } }, text);
    node.addEventListener("animationend", () => node.remove());
    this.overlay.append(node);
    if (reduced.matches) setTimeout(() => node.remove(), 1200);
  }

  /** Cover the map with a message while the moment cannot be shown, or uncover it. */
  cover(message, failed = false) {
    this.curtain.hidden = !message;
    this.curtain.classList.toggle("failed", failed);
    if (message) this.curtain.replaceChildren(h("div", { class: failed ? "curtain-error" : "loading" }, failed ? icon("alert", 18) : null, message));
  }

  destroy() {
    this.resize.disconnect();
  }
}
