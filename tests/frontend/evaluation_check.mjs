// Reads every evaluation result of a published run as the viewer's evaluation view does and
// prints, for each result and probe family, the rows of the stake curve it shows.
//
//   node tests/frontend/evaluation_check.mjs SITE RUN_PATH
//
// RUN_PATH is the run's directory inside the site, such as data/runs/town/seed-0007. Prints a
// JSON object: result label, then agent, then family, to its rows.

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const [site, runPath] = process.argv.slice(2);
const { stakeRows } = await import(pathToFileURL(join(site, "js", "views", "evaluation.js")).href);

const read = (path) => JSON.parse(readFileSync(join(site, runPath, path.split("?")[0]), "utf8"));
const evaluation = read(read("run.json").evaluation);
const shown = {};
for (const entry of evaluation.results) {
  const result = read(entry.url);
  (shown[entry.label] ??= {})[entry.agent] = Object.fromEntries(Object.entries(result.probes).map(([name, found]) => [name, stakeRows(found)]));
}
console.log(JSON.stringify(shown));
