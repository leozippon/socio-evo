// The town's plan, derived from the world alone: where each place stands and what kind of
// building its name and description describe, the streets and lanes between places, water and
// a square where the places say they are by a river or on a square, a hill where a name says
// so, and gardens, trees, lamps and benches in the space that is left.
//
// Pure and deterministic (seeded by the world's own ids), so the same world always gives the
// same town, and it runs under node for tests. Coordinates are world pixels: one unit of the
// configured map is `unit` pixels, and every building faces down the map.

export function seeded(text) {
  let x = 2166136261;
  for (const c of text) x = Math.imul(x ^ c.charCodeAt(0), 16777619);
  return () => {
    x = Math.imul(x ^ (x >>> 15), 2246822507);
    x = Math.imul(x ^ (x >>> 13), 3266489909);
    return ((x ^= x >>> 16) >>> 0) / 4294967296;
  };
}

/** Building styles: by kind, then by what the place's own words say it is. */
const STYLES = [
  ["work", /librar|reading room/, "library"],
  ["work", /workshop|workroom|factory|forge|studio|\bmill\b|yard/, "workshop"],
  ["work", /./, "office"],
  ["social", /tavern|\bpub\b|\binn\b|\bbar\b|alehouse|anchor/, "tavern"],
  ["social", /./, "cafe"],
  ["home", /cottage/, "cottage"],
  ["home", /\bflat\b|apartment/, "flat"],
  ["home", /shared|lodging|boarding/, "shared"],
];

/** Width, wall height and roof height of each style. */
export const SIZES = {
  cottage: { w: 50, h: 28, roof: 26 },
  house: { w: 56, h: 32, roof: 26 },
  shared: { w: 70, h: 34, roof: 26 },
  flat: { w: 50, h: 54, roof: 8 },
  workshop: { w: 84, h: 38, roof: 18 },
  library: { w: 80, h: 40, roof: 20 },
  office: { w: 66, h: 48, roof: 8 },
  cafe: { w: 62, h: 36, roof: 18 },
  tavern: { w: 66, h: 40, roof: 24 },
};

const words = (place) => `${place.name} ${place.description ?? ""}`.toLowerCase();
export const styleOf = (place) => STYLES.find(([kind, pattern]) => kind === place.kind && pattern.test(words(place)))?.[2] ?? "house";

const YARD = 40; // depth of the ground in front of a building where people stand
const PAD = 0.95; // map units around the places that the fitted view keeps in sight
const MARGIN = 2.4; // map units of countryside beyond that
const RIVER = 30; // river width

// Geometry ------------------------------------------------------------------------------------

const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
const inflate = (r, d) => ({ x0: r.x0 - d, y0: r.y0 - d, x1: r.x1 + d, y1: r.y1 + d });
const overlaps = (a, b) => a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1;
const inside = (p, r) => p.x >= r.x0 && p.x <= r.x1 && p.y >= r.y0 && p.y <= r.y1;

/** Whether segment p-q passes through rectangle r (Liang-Barsky clipping). */
export function segmentHits(p, q, r) {
  let t0 = 0;
  let t1 = 1;
  const dx = q.x - p.x;
  const dy = q.y - p.y;
  for (const [a, b] of [
    [-dx, p.x - r.x0],
    [dx, r.x1 - p.x],
    [-dy, p.y - r.y0],
    [dy, r.y1 - p.y],
  ]) {
    if (a === 0) {
      if (b < 0) return false;
    } else {
      const t = b / a;
      if (a < 0) t0 = Math.max(t0, t);
      else t1 = Math.min(t1, t);
      if (t0 > t1) return false;
    }
  }
  return true;
}

export function toSegment(p, a, b) {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const t = Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / (dx * dx + dy * dy || 1)));
  return Math.hypot(p.x - a.x - t * dx, p.y - a.y - t * dy);
}

const toLine = (p, line) => {
  let best = Infinity;
  for (let i = 0; i < line.length - 1; i++) best = Math.min(best, toSegment(p, line[i], line[i + 1]));
  return best;
};

export const lengthOf = (line) => line.slice(1).reduce((total, p, i) => total + dist(line[i], p), 0);

/** The point at `along` pixels down a polyline, and the direction it faces there. */
export function pointAlong(line, along) {
  let left = along;
  for (let i = 0; i < line.length - 1; i++) {
    const d = dist(line[i], line[i + 1]);
    if (left <= d || i === line.length - 2) {
      const t = d ? Math.min(1, left / d) : 1;
      return { x: line[i].x + (line[i + 1].x - line[i].x) * t, y: line[i].y + (line[i + 1].y - line[i].y) * t, dx: line[i + 1].x - line[i].x };
    }
    left -= d;
  }
  return { ...line[0], dx: 0 };
}

/** A smooth curve through points (Catmull-Rom as cubic Béziers): its path and a sampled line. */
function smooth(points) {
  const p = (i) => points[Math.max(0, Math.min(points.length - 1, i))];
  let d = `M${f(points[0].x)},${f(points[0].y)}`;
  const line = [points[0]];
  for (let i = 0; i < points.length - 1; i++) {
    const [a, b, c, e] = [p(i - 1), p(i), p(i + 1), p(i + 2)];
    const c1 = { x: b.x + (c.x - a.x) / 6, y: b.y + (c.y - a.y) / 6 };
    const c2 = { x: c.x - (e.x - b.x) / 6, y: c.y - (e.y - b.y) / 6 };
    d += `C${f(c1.x)},${f(c1.y)} ${f(c2.x)},${f(c2.y)} ${f(c.x)},${f(c.y)}`;
    for (let k = 1; k <= 6; k++) {
      const t = k / 6;
      const u = 1 - t;
      line.push({ x: u * u * u * b.x + 3 * u * u * t * c1.x + 3 * u * t * t * c2.x + t * t * t * c.x, y: u * u * u * b.y + 3 * u * u * t * c1.y + 3 * u * t * t * c2.y + t * t * t * c.y });
    }
  }
  return { d, line };
}

export const f = (n) => (Math.round(n * 10) / 10).toString();

/** A route from p to q that goes around every rectangle in its way, by their corners. */
function route(p, q, blocks) {
  let points = [p, q];
  for (let pass = 0; pass < 8; pass++) {
    let changed = false;
    for (let i = 0; i < points.length - 1 && !changed; i++) {
      const a = points[i];
      const b = points[i + 1];
      const block = blocks.find((r) => !inside(a, r) && !inside(b, r) && segmentHits(a, b, inflate(r, -1)));
      if (!block) continue;
      const c = [
        { x: block.x0, y: block.y0 },
        { x: block.x1, y: block.y0 },
        { x: block.x1, y: block.y1 },
        { x: block.x0, y: block.y1 },
      ];
      let best = null;
      const consider = (via) => {
        const path = [a, ...via, b];
        for (let k = 0; k < path.length - 1; k++) if (segmentHits(path[k], path[k + 1], inflate(block, -1))) return;
        const length = lengthOf(path);
        if (!best || length < best.length) best = { via, length };
      };
      for (let k = 0; k < 4; k++) {
        consider([c[k]]);
        consider([c[k], c[(k + 1) % 4]]);
        consider([c[(k + 1) % 4], c[k]]);
      }
      if (!best) continue;
      points = [...points.slice(0, i + 1), ...best.via, ...points.slice(i + 1)];
      changed = true;
    }
    if (!changed) break;
  }
  return points;
}

// The plan ------------------------------------------------------------------------------------

/**
 * Where each place stands on the map: its configured position, except that places configured
 * at the very same point are set around it in a ring, in configured order, a typical distance
 * between places apart (one unit if there is no other distance to go by).
 */
function positions(places) {
  const groups = new Map();
  for (const place of places) {
    const key = `${place.x},${place.y}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(place);
  }
  const points = [...groups.values()].map((group) => group[0]);
  const gaps = points.map((p) => Math.min(...points.filter((q) => q !== p).map((q) => Math.hypot(p.x - q.x, p.y - q.y)))).filter(Number.isFinite).sort((a, b) => a - b);
  const typical = gaps.length ? gaps[Math.floor(gaps.length / 2)] : 1;
  const out = new Map();
  for (const group of groups.values()) {
    const radius = group.length > 1 ? typical / (2 * Math.sin(Math.PI / group.length)) : 0;
    group.forEach((place, i) => {
      const a = -Math.PI / 2 + (i / group.length) * 2 * Math.PI;
      out.set(place.id, { x: place.x + radius * Math.cos(a), y: place.y + radius * Math.sin(a) });
    });
  }
  return out;
}

export function townPlan(world) {
  const places = world.places;
  const coords = positions(places);
  const xs = places.map((p) => coords.get(p.id).x);
  const ys = places.map((p) => coords.get(p.id).y);
  const [minX, maxX, minY, maxY] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  // A unit large enough that the closest two places do not overlap, but not so large that a
  // sprawling town becomes an enormous drawing.
  let nearest = Infinity;
  for (let i = 0; i < places.length; i++) for (let j = i + 1; j < places.length; j++) nearest = Math.min(nearest, Math.hypot(xs[i] - xs[j], ys[i] - ys[j]));
  const span = Math.max(maxX - minX, maxY - minY) + 2 * (PAD + MARGIN);
  const unit = Math.max(40, Math.min(Math.max(110, 96 / (Number.isFinite(nearest) ? nearest : 1)), 6000 / span));
  const edge = (PAD + MARGIN) * unit;
  const width = Math.round((maxX - minX) * unit + 2 * edge);
  const height = Math.round((maxY - minY) * unit + 2 * edge);
  const at = (x, y) => ({ x: (x - minX) * unit + edge, y: (y - minY) * unit + edge });
  const rand = seeded(`${world.experiment ?? "town"}|${places.map((p) => p.id).join(",")}`);

  // Places: the building, its yard in front, its door.
  const built = places.map((place) => {
    const c = at(coords.get(place.id).x, coords.get(place.id).y);
    const style = styleOf(place);
    const size = SIZES[style];
    const r = seeded(place.id);
    const base = c.y + 16; // the ground line of the front wall
    const top = base - size.h - size.roof;
    const door = { x: c.x + (style === "shared" ? -size.w * 0.18 : style === "cottage" ? size.w * 0.16 : 0), y: base };
    const yardWidth = Math.max(size.w + 10, 76);
    return {
      id: place.id,
      kind: place.kind,
      name: place.name,
      text: words(place),
      style,
      x: c.x,
      y: c.y,
      base,
      top,
      ...size,
      door,
      front: { x: door.x, y: base + 12 },
      rect: { x0: c.x - size.w / 2 - 4, y0: top, x1: c.x + size.w / 2 + 4, y1: base + 2 },
      yard: { x0: c.x - yardWidth / 2, y0: base + 2, x1: c.x + yardWidth / 2, y1: base + YARD },
      variant: Math.floor(r() * 3),
      chimney: r() < 0.5 ? -1 : 1,
      seed: r(),
    };
  });
  const byId = new Map(built.map((p) => [p.id, p]));
  const centre = { x: built.reduce((a, p) => a + p.x, 0) / built.length, y: built.reduce((a, p) => a + p.y, 0) / built.length };
  const blocks = built.map((p) => inflate(p.rect, 7));
  const fit = {
    x0: Math.min(...built.map((p) => p.rect.x0)) - 26,
    y0: Math.min(...built.map((p) => p.top)) - 40,
    x1: Math.max(...built.map((p) => p.rect.x1)) + 26,
    y1: Math.max(...built.map((p) => p.yard.y1)) + 14,
  };

  // Streets between the places: a spanning tree over their fronts, and a few short loops.
  const n = built.length;
  const d = (i, j) => dist(built[i].front, built[j].front);
  const links = [];
  const joined = new Set([0]);
  while (joined.size < n) {
    let best = null;
    for (const i of joined) for (let j = 0; j < n; j++) if (!joined.has(j) && (!best || d(i, j) < best[2])) best = [i, j, d(i, j)];
    joined.add(best[1]);
    links.push(best);
  }
  const hops = (from, to) => {
    // Graph distance over the links so far (Dijkstra on a handful of nodes).
    const seen = new Map([[from, 0]]);
    const queue = [from];
    while (queue.length) {
      queue.sort((a, b) => seen.get(a) - seen.get(b));
      const at = queue.shift();
      for (const [a, b, w] of links) {
        const next = a === at ? b : b === at ? a : null;
        if (next === null || (seen.has(next) && seen.get(next) <= seen.get(at) + w)) continue;
        seen.set(next, seen.get(at) + w);
        queue.push(next);
      }
    }
    return seen.get(to) ?? Infinity;
  };
  const extras = [];
  for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) if (!links.some(([a, b]) => (a === i && b === j) || (a === j && b === i)) && d(i, j) < 1.6 * unit && hops(i, j) > 2.2 * d(i, j)) extras.push([i, j, d(i, j)]);
  extras.sort((a, b) => a[2] - b[2]);
  links.push(...extras.slice(0, 3));
  const roads = links.map(([i, j]) => {
    const a = built[i];
    const b = built[j];
    const r = seeded(`${a.id}~${b.id}`);
    const points = route(a.front, b.front, blocks);
    // A gentle bend on straight runs, so lanes do not look ruled.
    if (points.length === 2) {
      const bend = (r() - 0.5) * 0.16;
      points.splice(1, 0, { x: (a.front.x + b.front.x) / 2 - (b.front.y - a.front.y) * bend, y: (a.front.y + b.front.y) / 2 + (b.front.x - a.front.x) * bend });
    }
    const curve = smooth(points);
    return { from: a.id, to: b.id, kind: a.kind !== "home" && b.kind !== "home" ? "street" : "lane", ...curve };
  });

  // Water, where places say they are by a river: it runs along the side of the town nearest
  // them, just beyond every building on that side.
  const watery = built.filter((p) => /\briver|canal|\bstream|\bbrook/.test(p.text));
  let river = null;
  if (watery.length) {
    const mean = { x: watery.reduce((a, p) => a + p.x, 0) / watery.length, y: watery.reduce((a, p) => a + p.y, 0) / watery.length };
    const sides = [
      ["top", mean.y - fit.y0],
      ["bottom", fit.y1 - mean.y],
      ["left", mean.x - fit.x0],
      ["right", fit.x1 - mean.x],
    ].sort((a, b) => a[1] - b[1]);
    const side = sides[0][0];
    const horizontal = side === "top" || side === "bottom";
    // Far enough out that the widest meander stays clear of every building on that side.
    const at = {
      top: Math.min(...built.map((p) => p.top)) - 42,
      bottom: Math.max(...built.map((p) => p.yard.y1)) + 40,
      left: Math.min(...built.map((p) => p.rect.x0)) - 42,
      right: Math.max(...built.map((p) => p.rect.x1)) + 42,
    }[side];
    const r = seeded(`river|${watery.map((p) => p.id).join(",")}`);
    const phase = r() * Math.PI * 2;
    const length = horizontal ? width : height;
    const points = [];
    for (let s = -40; s <= length + 40; s += 60) {
      const off = Math.sin(s / 260 + phase) * 10 + Math.sin(s / 97 + phase * 2) * 3;
      points.push(horizontal ? { x: s, y: at + off } : { x: at + off, y: s });
    }
    river = { side, ...smooth(points), width: RIVER };
    // The fitted view shows the river too: the places by it are by it.
    const reach = RIVER / 2 + 30;
    if (side === "top") fit.y0 = Math.min(fit.y0, at - reach);
    if (side === "bottom") fit.y1 = Math.max(fit.y1, at + reach);
    if (side === "left") fit.x0 = Math.min(fit.x0, at - reach);
    if (side === "right") fit.x1 = Math.max(fit.x1, at + reach);
  }
  const onWater = (p, margin = 0) => river && toLine(p, river.line) < river.width / 2 + margin;

  // Roads out of town: from places whose words name a gate, from a place by the river across
  // it, and from the outermost places toward the nearest edges, at least two in all.
  const outs = [];
  const sideOf = (p) =>
    [
      ["left", p.x - fit.x0],
      ["right", fit.x1 - p.x],
      ["top", p.y - fit.y0],
      ["bottom", fit.y1 - p.y],
    ].sort((a, b) => a[1] - b[1])[0][0];
  const wantOut = (p, side, why) => {
    if (outs.some((o) => o.from === p.id || o.side === side)) return;
    const end = { left: { x: -20, y: p.front.y }, right: { x: width + 20, y: p.front.y }, top: { x: p.x + p.w * 0.8, y: -20 }, bottom: { x: p.front.x, y: height + 20 } }[side];
    outs.push({ from: p.id, side, why, points: route(p.front, end, blocks) });
  };
  for (const p of built) if (/\bgate/.test(p.text)) wantOut(p, sideOf(p), "gate");
  if (river) {
    const p = [...watery].sort((a, b) => dist(a, centre) - dist(b, centre))[0];
    wantOut(p, river.side, "bridge");
  }
  for (const side of ["left", "bottom", "right", "top"]) {
    if (outs.length >= 2) break;
    const key = { left: (p) => p.x, right: (p) => -p.x, top: (p) => p.y, bottom: (p) => -p.y }[side];
    const p = [...built].sort((a, b) => key(a) - key(b))[0];
    if (p) wantOut(p, side, "edge");
  }
  const bridges = [];
  const gates = [];
  for (const out of outs) {
    const curve = smooth(out.points);
    roads.push({ from: out.from, to: null, kind: "street", ...curve });
    if (river) {
      const crossing = curve.line.find((p) => onWater(p));
      if (crossing) {
        const horizontal = river.side === "top" || river.side === "bottom";
        bridges.push({ x: crossing.x, y: crossing.y, angle: horizontal ? 90 : 0, length: RIVER + 18 });
      }
    }
    if (out.why === "gate") {
      const p = pointAlong(curve.line, 58);
      const q = pointAlong(curve.line, 64);
      gates.push({ x: p.x, y: p.y, angle: (Math.atan2(q.y - p.y, q.x - p.x) * 180) / Math.PI });
    }
  }

  // A square where places say they stand on one ("on the market square"), or are one: the
  // ground in front of them, clear of every other building. Being near one is not enough.
  let square = null;
  const onSquare = built.filter((p) => /\bon (?:the |a )?(?:[\w-]+ )?(?:square|plaza|piazza)\b/.test(p.text) || /\b(?:square|plaza|piazza)\b/.test(p.name.toLowerCase()));
  if (onSquare.length) {
    let r = { x0: Math.min(...onSquare.map((p) => p.yard.x0)) - 6, y0: Math.min(...onSquare.map((p) => p.yard.y0)), x1: Math.max(...onSquare.map((p) => p.yard.x1)) + 6, y1: Math.max(...onSquare.map((p) => p.yard.y1)) + 8 };
    for (const p of built) {
      const b = inflate(p.rect, 6);
      if (!overlaps(r, b)) continue;
      // Give up the side of the square that the building cuts least.
      const cuts = [
        ["y1", b.y0, (r.y1 - b.y0) * (r.x1 - r.x0)],
        ["y0", b.y1, (b.y1 - r.y0) * (r.x1 - r.x0)],
        ["x1", b.x0, (r.x1 - b.x0) * (r.y1 - r.y0)],
        ["x0", b.x1, (b.x1 - r.x0) * (r.y1 - r.y0)],
      ].sort((a, c) => a[2] - c[2]);
      r = { ...r, [cuts[0][0]]: cuts[0][1] };
    }
    if (r.x1 - r.x0 >= 60 && r.y1 - r.y0 >= 30) square = { ...r, fountain: r.x1 - r.x0 >= 110 && r.y1 - r.y0 >= 40 ? { x: (r.x0 + r.x1) / 2, y: (r.y0 + r.y1) / 2 + 2 } : null };
  }

  // Hills, where a name says so: a rise of ground behind the place, away from the town.
  const hills = built
    .filter((p) => /\bhill/.test(p.text))
    .map((p) => {
      const away = { x: p.x - centre.x, y: p.y - centre.y };
      const len = Math.hypot(away.x, away.y) || 1;
      return { x: p.x + (away.x / len) * unit * 0.55, y: p.y + (away.y / len) * unit * 0.4 - 10, rx: unit * 1.25, ry: unit * 0.85 };
    });

  // What is taken: buildings, yards, the square, roads and water. Decoration goes elsewhere.
  const taken = [...built.flatMap((p) => [inflate(p.rect, 8), inflate(p.yard, 4)]), ...(square ? [inflate(square, 6)] : [])];
  const nearRoad = (p, margin) => roads.some((road) => toLine(p, road.line) < (road.kind === "street" ? 9 : 6) + margin);
  const free = (p, margin = 0) => !taken.some((r) => inside(p, inflate(r, margin))) && !nearRoad(p, margin) && !onWater(p, margin + 4);
  const freeRect = (r) => {
    if (taken.some((t) => overlaps(t, r))) return false;
    const probe = [];
    for (let x = r.x0; x <= r.x1; x += 8) for (let y = r.y0; y <= r.y1; y += 8) probe.push({ x, y });
    return probe.every((p) => !nearRoad(p, 2) && !onWater(p, 4)) && r.x0 > 0 && r.y0 > 0 && r.x1 < width && r.y1 < height;
  };

  // Gardens beside or behind homes, hedged or fenced.
  const gardens = [];
  for (const p of built.filter((q) => q.kind === "home")) {
    const w = 40 + Math.round(p.seed * 14);
    const hgt = Math.min(p.h + p.roof - 6, 40);
    // Beside the house where there is room, behind it (where its name goes) only otherwise.
    const sides = [
      { x0: p.rect.x1 + 4, y0: p.base - hgt, x1: p.rect.x1 + 4 + w, y1: p.base },
      { x0: p.rect.x0 - 4 - w, y0: p.base - hgt, x1: p.rect.x0 - 4, y1: p.base },
    ];
    if (p.seed > 0.5) sides.reverse();
    const candidates = [...sides, { x0: p.x - w / 2 - 6, y0: p.top - 46, x1: p.x + w / 2 + 6, y1: p.top - 8 }];
    const found = candidates.find(freeRect);
    if (!found) continue;
    const garden = { ...found, home: p.id, edge: p.variant === 1 ? "fence" : "hedge", beds: p.variant === 2 ? "rows" : "flowers", seed: p.seed };
    gardens.push(garden);
    taken.push(inflate(garden, 4));
  }

  // Lamps along the streets and at the corners of the square, benches on the square.
  const lamps = [];
  const benches = [];
  for (const road of roads.filter((r) => r.kind === "street")) {
    const total = lengthOf(road.line);
    for (let s = 50, k = 0; s < total - 30; s += 120, k++) {
      const p = pointAlong(road.line, s);
      const q = pointAlong(road.line, s + 4);
      const len = Math.hypot(q.x - p.x, q.y - p.y) || 1;
      const side = k % 2 ? 1 : -1;
      const lamp = { x: p.x + (-(q.y - p.y) / len) * 13 * side, y: p.y + ((q.x - p.x) / len) * 13 * side };
      if (lamp.x > 0 && lamp.y > 0 && lamp.x < width && lamp.y < height && !taken.some((r) => inside(lamp, r)) && !onWater(lamp, 6) && !lamps.some((l) => dist(l, lamp) < 60)) lamps.push(lamp);
    }
  }
  if (square) {
    for (const [x, y] of [
      [square.x0 + 6, square.y0 + 6],
      [square.x1 - 6, square.y1 - 6],
    ])
      if (!lamps.some((l) => dist(l, { x, y }) < 30)) lamps.push({ x, y });
    benches.push({ x: square.x0 + 14, y: square.y1 - 6 }, { x: square.x1 - 18, y: square.y0 + 10 });
  }
  for (const p of built.filter((q) => q.kind === "social")) {
    const lamp = { x: p.door.x + 14, y: p.base + 3 };
    if (!lamps.some((l) => dist(l, lamp) < 24)) lamps.push({ ...lamp, porch: true });
  }

  // Ground: soft patches of other greens, then trees in copses away from the places, then
  // tufts of grass, all where nothing else is.
  const shift = rand() * 100;
  const noise = (x, y) => Math.sin(x / 173 + shift) * Math.cos(y / 151) + Math.sin((x + y) / 97 + 1.3) * 0.6 + Math.cos((x - 2 * y) / 211 + 0.4) * 0.5;
  const patches = [];
  for (let k = 0; k < 18; k++) patches.push({ x: rand() * width, y: rand() * height, rx: 60 + rand() * 140, ry: 40 + rand() * 90, tone: k % 3 });
  const trees = [];
  const cell = 24;
  const town = inflate(fit, -10);
  for (let gx = cell / 2; gx < width; gx += cell)
    for (let gy = cell / 2; gy < height; gy += cell) {
      const p = { x: gx + (rand() - 0.5) * cell * 0.9, y: gy + (rand() - 0.5) * cell * 0.9 };
      const roll = rand();
      const dense = noise(p.x, p.y);
      // Copses in the country around, only the odd tree among the places.
      const threshold = inside(p, town) ? 1.3 : 0.45;
      if (dense < threshold || roll < 0.45) continue;
      if (!free(p, 10)) continue;
      const kind = roll > 0.93 ? "bush" : dense > 1.1 && rand() < 0.55 ? "conifer" : "round";
      const r = kind === "bush" ? 5 + rand() * 2.5 : kind === "conifer" ? 8 + rand() * 4 : 9 + rand() * 6;
      if (trees.some((t) => dist(t, p) < (t.r + r) * 0.85)) continue;
      trees.push({ x: p.x, y: p.y, r, kind, tone: Math.floor(rand() * 3) });
    }
  const tufts = [];
  for (let k = 0; k < 420; k++) {
    const p = { x: rand() * width, y: rand() * height };
    if (free(p, 2) && !trees.some((t) => dist(t, p) < t.r + 2)) tufts.push(p);
  }
  const flowers = [];
  for (const g of gardens) {
    const r = seeded(`flowers|${g.home}`);
    if (g.beds === "flowers") for (let k = 0; k < 14; k++) flowers.push({ x: g.x0 + 6 + r() * (g.x1 - g.x0 - 12), y: g.y0 + 6 + r() * (g.y1 - g.y0 - 12), tone: k % 3 });
  }

  return {
    unit,
    width,
    height,
    fit,
    centre,
    places: built,
    byId,
    roads,
    river,
    bridges,
    gates,
    square,
    hills,
    gardens,
    lamps,
    benches,
    patches,
    trees,
    tufts,
    flowers,
  };
}

/** The roads as a graph over place fronts, for walking between places. */
export function walkways(plan) {
  const edges = new Map();
  const add = (a, b, line) => {
    if (!edges.has(a)) edges.set(a, []);
    edges.get(a).push({ to: b, line, length: lengthOf(line) });
  };
  for (const road of plan.roads) {
    if (!road.to) continue;
    add(road.from, road.to, road.line);
    add(road.to, road.from, [...road.line].reverse());
  }
  /** The line to walk from place `a` to place `b` along the roads, or null. */
  return (a, b) => {
    if (a === b) return null;
    const best = new Map([[a, { length: 0, line: [] }]]);
    const queue = [a];
    while (queue.length) {
      queue.sort((x, y) => best.get(x).length - best.get(y).length);
      const at = queue.shift();
      if (at === b) break;
      for (const edge of edges.get(at) ?? []) {
        const length = best.get(at).length + edge.length;
        if (best.has(edge.to) && best.get(edge.to).length <= length) continue;
        best.set(edge.to, { length, line: [...best.get(at).line, ...edge.line] });
        queue.push(edge.to);
      }
    }
    return best.get(b)?.line ?? null;
  };
}
