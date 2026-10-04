// Checks the town plan the viewer draws, for published worlds and for made-up ones: whatever
// the configuration, buildings do not overlap, streets go around buildings and connect every
// place, water keeps clear of buildings and yards, decoration stays off buildings, yards, streets
// and water, words in place names bring their river and square, and the plan is deterministic.
//
//   node tests/frontend/plan_check.mjs SITE [RUN_PATH ...]
//
// Prints a JSON summary; exits 1 with the first failures if any.

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const [site, ...runs] = process.argv.slice(2);
const { townPlan, walkways, toSegment } = await import(pathToFileURL(join(site, "js", "town", "plan.js")).href);

const read = (run, path) => JSON.parse(readFileSync(join(site, run, path.split("?")[0]), "utf8"));
const worlds = runs.map((run) => [run, read(run, read(run, "run.json").world)]);

const place = (id, kind, x, y, name = id, description = "") => ({ id, kind, name, description, x, y, residents: [], hours: kind === "work" ? ["09:00-12:00"] : [] });
const made = (name, places) => [name, { experiment: name, places }];
worlds.push(
  made("one place", [place("home", "home", 0, 0)]),
  made("a row", [place("a", "home", 0, 0), place("b", "work", 1, 0), place("c", "social", 2, 0)]),
  made("a column", [place("a", "home", 3, 0), place("b", "work", 3, 1), place("c", "social", 3, 2), place("d", "home", 3, 3)]),
  made("crowded and fractional", [place("a", "home", 0, 0), place("b", "work", 0.4, 0.1), place("c", "social", 0.2, 0.5), place("d", "home", 0.7, 0.6), place("e", "home", 1.1, 0.2)]),
  made("all at one point", [place("flat", "home", 0, 0), place("house", "home", 0, 0), place("office", "work", 0, 0), place("cafe", "social", 0, 0), place("park", "social", 0, 0)]),
  made("far apart", [place("a", "home", 0, 0), place("b", "work", 60, 40), place("c", "social", 120, 0)]),
  made("words", [
    place("mill", "home", 1, 4, "the mill cottage by the river"),
    place("inn", "social", 3, 1, "the Swan", "An inn by the river."),
    place("shop", "work", 3, 3, "the workshop", "On the town square."),
    place("cafe", "social", 2, 3, "the café", "A café on the square."),
    place("hall", "home", 6, 6, "the house on Hill Lane"),
    place("gate", "home", 7, 2, "the lodge by the park gates"),
    place("lib", "work", 5, 3, "the library"),
  ]),
);

const failures = [];
let checks = 0;
const check = (what, ok, detail = null) => {
  checks += 1;
  if (!ok) failures.push({ what, detail });
};
const inside = (p, r, d = 0) => p.x > r.x0 - d && p.x < r.x1 + d && p.y > r.y0 - d && p.y < r.y1 + d;
const shrink = (r, d) => ({ x0: r.x0 + d, y0: r.y0 + d, x1: r.x1 - d, y1: r.y1 - d });
const near = (p, line, d) => line.some((q, i) => i && toSegment(p, line[i - 1], q) < d);

for (const [name, world] of worlds) {
  const plan = townPlan(world);
  check(`${name}: the plan is deterministic`, JSON.stringify({ ...plan, byId: null }) === JSON.stringify({ ...townPlan(world), byId: null }));
  check(`${name}: every place has a building`, plan.places.length === world.places.length);
  for (const [i, a] of plan.places.entries()) {
    check(`${name}: ${a.id} lies inside the drawing`, a.rect.x0 > 0 && a.rect.y0 > 0 && a.yard.x1 < plan.width && a.yard.y1 < plan.height);
    check(`${name}: ${a.id} lies inside the fitted view`, inside({ x: a.x, y: a.top }, plan.fit, 1) && inside({ x: a.x, y: a.yard.y1 }, plan.fit, 1));
    for (const b of plan.places.slice(i + 1)) check(`${name}: ${a.id} and ${b.id} do not overlap`, !(a.rect.x0 < b.rect.x1 && b.rect.x0 < a.rect.x1 && a.rect.y0 < b.rect.y1 && b.rect.y0 < a.rect.y1), [a.rect, b.rect]);
  }
  for (const road of plan.roads) {
    const through = plan.places.find((p) => road.line.some((q) => inside(q, shrink(p.rect, 3))));
    check(`${name}: the road from ${road.from} to ${road.to ?? "the edge"} goes around buildings`, !through, through?.id);
  }
  const walk = walkways(plan);
  for (const p of plan.places.slice(1)) check(`${name}: ${plan.places[0].id} can walk to ${p.id}`, walk(plan.places[0].id, p.id) !== null);
  if (plan.river) {
    const wet = plan.places.find((p) => near({ x: p.x, y: p.base }, plan.river.line, 0) || [p.rect, p.yard].some((r) => plan.river.line.some((q) => inside(q, r, plan.river.width / 2))));
    check(`${name}: the river keeps clear of buildings and yards`, !wet, wet?.id);
  }
  const blocked = (p, margin) => plan.places.some((q) => inside(p, q.rect, margin) || inside(p, q.yard, margin)) || (plan.square && inside(p, plan.square, margin)) || plan.roads.some((road) => near(p, road.line, 6 + margin)) || (plan.river && near(p, plan.river.line, plan.river.width / 2 + margin));
  const misplaced = [...plan.trees.filter((t) => blocked(t, 4)), ...plan.gardens.filter((g) => blocked({ x: (g.x0 + g.x1) / 2, y: (g.y0 + g.y1) / 2 }, 0))];
  check(`${name}: trees and gardens stay off buildings, yards, the square, roads and water`, misplaced.length === 0, misplaced.slice(0, 3));
  const lampsOnBuildings = plan.lamps.filter((l) => plan.places.some((q) => inside(l, q.rect, -2)));
  check(`${name}: lamps stand outside buildings`, lampsOnBuildings.length === 0, lampsOnBuildings.slice(0, 3));
  check(`${name}: the drawing has a sensible size`, plan.width > 0 && plan.height > 0 && plan.width <= 7000 && plan.height <= 7000, [plan.width, plan.height]);
  if (name === "words") {
    check("words: places by a river get one", plan.river !== null);
    check("words: places on a square get one", plan.square !== null);
    check("words: a hill where a name says so", plan.hills.length === 1);
    check("words: a gate where a name says so", plan.gates.length === 1);
    check("words: buildings follow their words", ["cottage", "tavern", "workshop", "cafe", "house", "library"].every((style) => plan.places.some((p) => p.style === style)), plan.places.map((p) => p.style));
  }
  if (name === "one place" || name === "a row") check(`${name}: no water or square without words for them`, plan.river === null && plan.square === null);
}

console.log(JSON.stringify({ worlds: worlds.map(([name]) => name), checks, failures: failures.slice(0, 10), failed: failures.length }));
process.exit(failures.length ? 1 : 0);
