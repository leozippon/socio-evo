// The town's scenery drawn from its plan: ground, water, streets, gardens, trees and buildings
// whose architecture says what they are. Static: it is drawn once per world, and only a
// place's open or closed state changes it afterwards. Fills come from the map's material
// tokens in town.css, so light and dark are both designed there.

import { s } from "../dom.js";
import { f } from "./plan.js";

const win = (out, windows, x, y, w, h, { arch = false } = {}) => {
  out.push(s("path", { class: "win", d: arch ? `M${x},${y + h}V${y + w / 2}A${w / 2},${w / 2} 0 0 1 ${x + w},${y + w / 2}V${y + h}Z` : `M${x},${y}h${w}v${h}h${-w}Z` }));
  out.push(s("path", { class: "mullion", d: `M${x + w / 2},${y + (arch ? w / 3 : 0)}V${y + h}M${x},${y + h * 0.5}h${w}` }));
  windows.push({ x, y, w, h, arch });
};

const door = (x, y, w, h, arch = false) => s("path", { class: "door", d: arch ? `M${x},0V${y + w / 2}A${w / 2},${w / 2} 0 0 1 ${x + w},${y + w / 2}V0Z` : `M${x},0V${y}h${w}V0Z` });

const chimney = (out, x, top, height) => {
  out.push(s("rect", { class: "chimney", x: x - 3.5, y: top, width: 7, height }));
  out.push(s("rect", { class: "chimney-cap", x: x - 4.5, y: top - 2, width: 9, height: 2.5 }));
  return { x, y: top - 3 };
};

/** Gabled roof seen from above the front: a trapezoid with eaves. */
const gable = (w, h, roof, overhang = 5, inset = 9) => `M${-w / 2 - overhang},${-h + 1}L${-w / 2 + inset},${-h - roof}H${w / 2 - inset}L${w / 2 + overhang},${-h + 1}Z`;

/** Each style draws itself around (0, 0), the middle of its front wall at the ground. */
const BUILD = {
  house(p, out, windows) {
    const { w, h, roof } = p;
    const smoke = chimney(out, p.chimney * (w / 2 - 15), -h - roof - 4, 14);
    out.push(s("rect", { class: `wall w${p.variant}`, x: -w / 2, y: -h, width: w, height: h }));
    out.push(s("path", { class: `roof r${p.variant}`, d: gable(w, h, roof) }));
    out.push(s("path", { class: "eaves", d: `M${-w / 2},${-h + 1}h${w}v3h${-w}Z` }));
    win(out, windows, -w * 0.38, -h * 0.66, 10, 10);
    win(out, windows, w * 0.38 - 10, -h * 0.66, 10, 10);
    out.push(door(-5, -h * 0.6, 10, h * 0.6));
    out.push(s("path", { class: "step", d: `M-8,0h16v2.5h-16Z` }));
    return smoke;
  },
  cottage(p, out, windows) {
    const { w, h, roof } = p;
    const smoke = chimney(out, -p.chimney * (w / 2 - 13), -h - roof - 2, 12);
    out.push(s("rect", { class: `wall w${p.variant}`, x: -w / 2, y: -h, width: w, height: h, rx: 1.5 }));
    out.push(s("path", { class: "roof thatch", d: `M${-w / 2 - 6},${-h + 2}Q${-w / 2 - 3},${-h - roof * 0.55} ${-w / 2 + 11},${-h - roof}H${w / 2 - 11}Q${w / 2 + 3},${-h - roof * 0.55} ${w / 2 + 6},${-h + 2}Z` }));
    out.push(s("path", { class: "thatch-line", d: `M${-w / 2 + 2},${-h - roof * 0.35}H${w / 2 - 2}M${-w / 2 + 7},${-h - roof * 0.7}H${w / 2 - 7}` }));
    win(out, windows, -w * 0.36, -h * 0.66, 10, 9);
    const dx = w * 0.16;
    out.push(door(dx - 5, -h * 0.72, 10, h * 0.72, true));
    return smoke;
  },
  shared(p, out, windows) {
    const { w, h, roof } = p;
    const smoke = chimney(out, p.chimney * (w / 2 - 16), -h - roof - 4, 14);
    out.push(s("rect", { class: `wall w${p.variant}`, x: -w / 2, y: -h, width: w, height: h }));
    out.push(s("path", { class: `roof r${(p.variant + 1) % 3}`, d: gable(w, h, roof, 5, 11) }));
    out.push(s("path", { class: "eaves", d: `M${-w / 2},${-h + 1}h${w}v3h${-w}Z` }));
    for (const x of [-0.42, -0.06, 0.3]) win(out, windows, w * x, -h * 0.68, 9, 10);
    out.push(door(-w * 0.18 - 4.5, -h * 0.58, 9, h * 0.58));
    out.push(door(w * 0.18 - 4.5, -h * 0.58, 9, h * 0.58));
    return smoke;
  },
  flat(p, out, windows) {
    const { w, h } = p;
    out.push(s("rect", { class: `wall w${(p.variant + 2) % 3}`, x: -w / 2, y: -h, width: w, height: h }));
    out.push(s("path", { class: "cornice", d: `M${-w / 2 - 3},${-h - 6}h${w + 6}v6h${-w - 6}Z` }));
    out.push(s("path", { class: "storey", d: `M${-w / 2},${-h * 0.5}h${w}` }));
    for (const y of [-h + 9, -h * 0.5 + 5]) for (const x of [-w * 0.34, w * 0.34 - 9]) win(out, windows, x, y, 9, 12);
    if (p.w > 40) win(out, windows, -4.5, -h + 9, 9, 12);
    out.push(door(-5, -h * 0.34, 10, h * 0.34));
    out.push(s("rect", { class: "vent", x: p.chimney * (w / 2 - 10) - 4, y: -h - 11, width: 8, height: 5 }));
    return null;
  },
  workshop(p, out, windows) {
    const { w, h, roof } = p;
    const smoke = chimney(out, p.chimney * (w / 2 - 7), -h - roof - 16, 26);
    out.push(s("rect", { class: "wall brick", x: -w / 2, y: -h, width: w, height: h }));
    const tooth = w / 3;
    for (let i = 0; i < 3; i++) {
      const x0 = -w / 2 + i * tooth;
      out.push(s("path", { class: "roof slate", d: `M${x0 - (i ? 0 : 2)},${-h}V${-h - roof}L${x0 + tooth},${-h}Z` }));
      out.push(s("path", { class: "glazing", d: `M${x0 + 1.2},${-h - 1}V${-h - roof + 3}` }));
    }
    win(out, windows, -w * 0.44, -h * 0.74, w * 0.26, h * 0.42);
    win(out, windows, w * 0.18, -h * 0.74, w * 0.26, h * 0.42);
    out.push(door(-w * 0.1, -h * 0.7, w * 0.2, h * 0.7));
    out.push(s("path", { class: "door-line", d: `M0,${-h * 0.7}V0` }));
    out.push(s("rect", { class: "sign", x: -w * 0.12, y: -h * 0.92, width: w * 0.24, height: 5, rx: 1 }));
    return smoke;
  },
  library(p, out, windows) {
    const { w, h, roof } = p;
    out.push(s("rect", { class: "wall stone", x: -w / 2, y: -h, width: w, height: h }));
    out.push(s("path", { class: "roof slate", d: `M${-w / 2 - 4},${-h - 4}L0,${-h - roof}L${w / 2 + 4},${-h - 4}Z` }));
    out.push(s("path", { class: "cornice", d: `M${-w / 2 - 4},${-h - 4}h${w + 8}v4h${-w - 8}Z` }));
    win(out, windows, -w * 0.3 - 4, -h * 0.78, 8, h * 0.5, { arch: true });
    win(out, windows, w * 0.3 - 4, -h * 0.78, 8, h * 0.5, { arch: true });
    out.push(door(-6, -h * 0.66, 12, h * 0.66, true));
    for (const x of [-0.44, -0.14, 0.14, 0.44]) out.push(s("rect", { class: "column", x: w * x - 2.2, y: -h, width: 4.4, height: h - 2 }));
    out.push(s("path", { class: "step", d: `M${-w / 2 + 4},0h${w - 8}v2.5h${-w + 8}ZM${-w / 2 + 8},2.5h${w - 16}v2.5h${-w + 16}Z` }));
    return null;
  },
  office(p, out, windows) {
    const { w, h } = p;
    out.push(s("rect", { class: "wall stone", x: -w / 2, y: -h, width: w, height: h }));
    out.push(s("path", { class: "cornice", d: `M${-w / 2 - 3},${-h - 5}h${w + 6}v5h${-w - 6}Z` }));
    for (const y of [-h + 8, -h * 0.5 + 3]) for (const x of [-0.4, -0.08, 0.24]) win(out, windows, w * x, y, 10, 11);
    out.push(door(-6, -h * 0.3, 12, h * 0.3));
    return null;
  },
  cafe(p, out, windows) {
    const { w, h, roof } = p;
    const smoke = chimney(out, p.chimney * (w / 2 - 12), -h - roof - 4, 12);
    out.push(s("rect", { class: `wall w${p.variant}`, x: -w / 2, y: -h, width: w, height: h }));
    out.push(s("path", { class: "roof r0", d: gable(w, h, roof, 4, 8) }));
    win(out, windows, -w * 0.44, -h * 0.58, w * 0.32, h * 0.44);
    win(out, windows, w * 0.16, -h * 0.58, w * 0.28, h * 0.44);
    out.push(door(-5, -h * 0.62, 10, h * 0.62));
    // The awning: stripes with a scalloped edge across the whole front.
    const n = 7;
    const sw = (w + 6) / n;
    const top = -h * 0.84;
    for (let i = 0; i < n; i++) {
      const x = -w / 2 - 3 + i * sw;
      out.push(s("path", { class: `awning ${i % 2 ? "b" : "a"}`, d: `M${f(x)},${f(top)}h${f(sw)}v8a${f(sw / 2)},3 0 0 1 ${f(-sw)},0Z` }));
    }
    // Two small tables at the edges of the terrace.
    for (const side of [-1, 1]) {
      const tx = side * (Math.max(w + 10, 76) / 2 - 7);
      out.push(s("ellipse", { class: "table", cx: tx, cy: 14, rx: 4.5, ry: 2.6 }));
      out.push(s("path", { class: "chair", d: `M${tx - 8},12h3v4h-3ZM${tx + 5},12h3v4h-3Z` }));
    }
    return smoke;
  },
  tavern(p, out, windows) {
    const { w, h, roof } = p;
    const smoke = chimney(out, -p.chimney * (w / 2 - 14), -h - roof - 4, 14);
    out.push(s("rect", { class: "wall w0", x: -w / 2, y: -h, width: w, height: h }));
    out.push(s("path", { class: "timber", d: `M${-w / 2 + 1.5},${-h}V0M${w / 2 - 1.5},${-h}V0M${-w / 2},${-h * 0.52}H${w / 2}M${-w / 6},${-h}V${-h * 0.52}M${w / 6},${-h}V${-h * 0.52}M${-w / 2 + 2},${-h * 0.52}L${-w / 6},${-h}M${w / 2 - 2},${-h * 0.52}L${w / 6},${-h}` }));
    out.push(s("path", { class: "roof r1", d: gable(w, h, roof, 6, 12) }));
    out.push(s("path", { class: "eaves", d: `M${-w / 2},${-h + 1}h${w}v3h${-w}Z` }));
    win(out, windows, -w * 0.4, -h * 0.44, 10, 10);
    win(out, windows, w * 0.4 - 10, -h * 0.44, 10, 10);
    win(out, windows, -5, -h * 0.9, 10, 8);
    out.push(door(-6, -h * 0.46, 12, h * 0.46, true));
    // A hanging sign on a bracket beside the door, and barrels.
    out.push(s("path", { class: "bracket", d: `M${w / 2},${-h * 0.62}h12M${w / 2 + 3},${-h * 0.62}l-3,-4` }));
    out.push(s("path", { class: "sign", d: `M${w / 2 + 3},${-h * 0.62 + 1}h9v9h-9Z` }));
    out.push(s("path", { class: "sign-mark", d: `M${w / 2 + 7.5},${-h * 0.62 + 3}v5M${w / 2 + 5.5},${-h * 0.62 + 6.5}q2,2 4,0` }));
    out.push(s("rect", { class: "barrel", x: -w / 2 - 9, y: -9, width: 7, height: 9, rx: 2.5 }));
    out.push(s("rect", { class: "barrel", x: -w / 2 - 15, y: -7, width: 6, height: 7, rx: 2.2 }));
    return smoke;
  },
};

function tree(t) {
  const shadow = s("ellipse", { class: "tree-shadow", cx: 3, cy: 2, rx: t.r * 0.95, ry: t.r * 0.38 });
  if (t.kind === "conifer")
    return [
      shadow,
      s("path", { class: "trunk", d: `M-1.2,0v-4h2.4v4Z` }),
      s("path", { class: `conifer c${t.tone}`, d: `M0,${f(-t.r * 2.6)}L${f(t.r * 0.8)},${f(-t.r * 0.9)}H${f(t.r * 0.45)}L${f(t.r)},-3H${f(-t.r)}L${f(-t.r * 0.45)},${f(-t.r * 0.9)}H${f(-t.r * 0.8)}Z` }),
    ];
  const lift = t.kind === "bush" ? t.r * 0.8 : t.r * 1.35;
  return [
    shadow,
    t.kind === "bush" ? null : s("path", { class: "trunk", d: `M-1.5,0v${f(-lift * 0.7)}h3V0Z` }),
    s("circle", { class: `leaf l${t.tone}`, cy: f(-lift), r: f(t.r) }),
    s("circle", { class: "leaf-hi", cx: f(-t.r * 0.32), cy: f(-lift - t.r * 0.3), r: f(t.r * 0.48) }),
  ];
}

function lamp(l) {
  return [s("path", { class: "lamp-post", d: `M0,0V-13` }), s("rect", { class: "lamp-head", x: -2.2, y: -17, width: 4.4, height: 4.4, rx: 1 })];
}

/**
 * Draw the plan. Returns the SVG and, by place, what the light layer and the ambient layer need:
 * windows and doors to light, and where chimneys smoke.
 */
export function drawScenery(plan) {
  const parts = [];
  parts.push(s("rect", { class: "ground", x: 0, y: 0, width: plan.width, height: plan.height }));
  for (const hill of plan.hills)
    for (let k = 0; k < 3; k++) parts.push(s("ellipse", { class: `hill h${k}`, cx: f(hill.x), cy: f(hill.y - k * 6), rx: f(hill.rx * (1 - k * 0.24)), ry: f(hill.ry * (1 - k * 0.26)) }));
  for (const patch of plan.patches) parts.push(s("ellipse", { class: `patch p${patch.tone}`, cx: f(patch.x), cy: f(patch.y), rx: f(patch.rx), ry: f(patch.ry) }));
  if (plan.river) {
    const { d, width } = plan.river;
    parts.push(s("path", { class: "bank", d, "stroke-width": width + 12 }));
    parts.push(s("path", { class: "water", d, "stroke-width": width }));
    parts.push(s("path", { class: "water-hi", d, "stroke-width": 1.4, transform: "translate(0,-4)" }));
  }
  if (plan.square) {
    const q = plan.square;
    parts.push(s("rect", { class: "square", x: f(q.x0), y: f(q.y0), width: f(q.x1 - q.x0), height: f(q.y1 - q.y0), rx: 6 }));
    let lines = "";
    for (let x = q.x0 + 12; x < q.x1 - 4; x += 12) lines += `M${f(x)},${f(q.y0 + 3)}V${f(q.y1 - 3)}`;
    for (let y = q.y0 + 10; y < q.y1 - 4; y += 10) lines += `M${f(q.x0 + 3)},${f(y)}H${f(q.x1 - 3)}`;
    parts.push(s("path", { class: "paving", d: lines }));
  }
  const ordered = [...plan.roads].sort((a, b) => (a.kind === "street") - (b.kind === "street"));
  for (const road of ordered) parts.push(s("path", { class: `road-edge ${road.kind}`, d: road.d }));
  for (const road of ordered) parts.push(s("path", { class: `road ${road.kind}`, d: road.d }));
  for (const road of ordered) if (road.kind === "street") parts.push(s("path", { class: "cobbles", d: road.d }));
  for (const b of plan.bridges)
    parts.push(
      s(
        "g",
        { class: "bridge", transform: `translate(${f(b.x)},${f(b.y)}) rotate(${f(b.angle)})` },
        s("rect", { class: "deck", x: -b.length / 2, y: -8, width: b.length, height: 16, rx: 2 }),
        s("path", { class: "rail", d: `M${-b.length / 2},-8h${b.length}M${-b.length / 2},8h${b.length}` }),
      ),
    );
  for (const g of plan.gardens) {
    parts.push(s("rect", { class: "garden", x: f(g.x0), y: f(g.y0), width: f(g.x1 - g.x0), height: f(g.y1 - g.y0), rx: 3 }));
    if (g.beds === "rows") {
      let rows = "";
      for (let y = g.y0 + 7; y < g.y1 - 4; y += 6) rows += `M${f(g.x0 + 6)},${f(y)}H${f(g.x1 - 6)}`;
      parts.push(s("path", { class: "beds", d: rows }));
    }
    parts.push(s("rect", { class: g.edge, x: f(g.x0), y: f(g.y0), width: f(g.x1 - g.x0), height: f(g.y1 - g.y0), rx: 3 }));
  }
  if (plan.flowers.length) for (let tone = 0; tone < 3; tone++) parts.push(s("path", { class: `flowers f${tone}`, d: plan.flowers.filter((p) => p.tone === tone).map((p) => `M${f(p.x)},${f(p.y)}h0.01`).join("") }));
  parts.push(s("path", { class: "tufts", d: plan.tufts.map((p) => `M${f(p.x - 2)},${f(p.y)}l2,-3.5l2,3.5M${f(p.x + 1)},${f(p.y)}l1.5,-2.5`).join("") }));
  for (const p of plan.places) parts.push(s("ellipse", { class: "yard", cx: f(p.x), cy: f(p.base + 18), rx: f((p.yard.x1 - p.yard.x0) / 2), ry: 17 }));

  // Everything that stands on the ground, back to front.
  const stands = [];
  const places = new Map();
  for (const p of plan.places) {
    const out = [s("ellipse", { class: "building-shadow", cx: 5, cy: 1, rx: f(p.w * 0.62), ry: 6 })];
    const windows = [];
    const smoke = BUILD[p.style](p, out, windows);
    const group = s("g", { class: `place ${p.kind} ${p.style}`, transform: `translate(${f(p.x)},${f(p.base)})`, "data-place": p.id }, out);
    places.set(p.id, { group, windows: windows.map((w) => ({ ...w, x: w.x + p.x, y: w.y + p.base })), smoke: smoke && { x: smoke.x + p.x, y: smoke.y + p.base } });
    stands.push([p.base, group]);
  }
  for (const t of plan.trees) stands.push([t.y, s("g", { transform: `translate(${f(t.x)},${f(t.y)})` }, tree(t))]);
  for (const l of plan.lamps) stands.push([l.y, s("g", { class: "lamp", transform: `translate(${f(l.x)},${f(l.y)})` }, lamp(l))]);
  for (const b of plan.benches) stands.push([b.y, s("path", { class: "bench", d: `M${f(b.x - 7)},${f(b.y - 3)}h14v3h-14ZM${f(b.x - 6)},${f(b.y)}v2.5M${f(b.x + 6)},${f(b.y)}v2.5` })]);
  if (plan.square?.fountain) {
    const { x, y } = plan.square.fountain;
    stands.push([y, s("g", { class: "fountain", transform: `translate(${f(x)},${f(y)})` }, s("ellipse", { class: "basin", rx: 13, ry: 6 }), s("ellipse", { class: "water", rx: 10, ry: 4, cy: -0.5 }), s("path", { class: "spout", d: "M0,-1V-9" }))]);
  }
  for (const g of plan.gates)
    stands.push([
      g.y,
      s(
        "g",
        { class: "gate", transform: `translate(${f(g.x)},${f(g.y)}) rotate(${f(g.angle - 90)})` },
        s("rect", { class: "post", x: -14, y: -4, width: 5, height: 8, rx: 1 }),
        s("rect", { class: "post", x: 9, y: -4, width: 5, height: 8, rx: 1 }),
        s("path", { class: "arch", d: "M-11.5,-4Q0,-12 11.5,-4" }),
      ),
    ]);
  stands.sort((a, b) => a[0] - b[0]);
  parts.push(...stands.map(([, node]) => node));

  const svg = s("svg", { class: "scenery", width: plan.width, height: plan.height, viewBox: `0 0 ${plan.width} ${plan.height}`, "aria-hidden": "true" }, parts);
  return { svg, places };
}
