// The seeds of one experiment side by side: the same society-wide numbers, one line per seed.
// Seeds are not people, so they wear ink, not agent colours, and are named at their line ends.

import { DayChart, figure } from "../charts.js";
import { RunSource } from "../data.js";
import { emptyState, fill, fmt, h } from "../dom.js";
import { href } from "../router.js";
import { markers } from "../world.js";
import { progress } from "./landing.js";
import { TRAITS } from "./evaluation.js";

const METRICS = [
  ["Mean balance", "Credits at the end of each day.", (row) => row.balance_mean, fmt.int, { zero: true }],
  ["Inequality of earnings", "Gini coefficient; 0 is equality.", (row) => row.earnings_gini, (v) => fmt.num(v, 2), { min: 0 }],
  ["Mean esteem", "Of the agents rated so far, from 1 to 5.", (row) => row.esteem_mean, (v) => fmt.num(v, 2), { max: 5 }],
  ["Accepted deliveries", "Per day.", (row) => row.delivered, fmt.int, { zero: true }],
  ["Claims refused", "Per day: the work others got first.", (row) => row.claims_refused, fmt.int, { zero: true }],
  ["Mean true quality", "Share of hidden checks passed by accepted work.", (row) => row.quality_mean, (v) => fmt.num(v, 2), { max: 1 }],
  ["Things said", "Per day.", (row) => row.utterances, fmt.int, { zero: true }],
  ["Evolution steps", "Per night, all levels.", (row) => Object.values(row.evolution).reduce((a, b) => a + b, 0), fmt.int, { zero: true }],
];

export function mountCompare(root, ctx) {
  const experiment = ctx.route.experiment;
  const page = h("div", { class: "page compare" });
  root.append(page);
  let charts = [];
  let highlight = null;

  async function render(index) {
    const runs = index.runs.filter((run) => run.experiment === experiment);
    if (!runs.length) return fill(page, h("div", { class: "card" }, emptyState(`There is no experiment named ${experiment} in this bundle.`)));
    fill(page, h("div", { class: "loading" }, `Loading ${fmt.plural(runs.length, "seed")}…`));
    try {
      const loaded = await Promise.all(
        runs.map(async (entry) => {
          const source = await new RunSource(index, entry).open();
          const [world, measures, evaluation] = await Promise.all([source.world(), source.measures(), source.evaluation()]);
          return { entry, world, measures, evaluation };
        }),
      );
      for (const chart of charts) chart.destroy();
      charts = [];
      const days = Math.max(1, ...loaded.map((run) => run.measures.society.at(-1)?.day ?? 1));
      const line = (run, points) => ({ key: run.entry.run, label: `seed ${run.entry.seed}`, color: "var(--ink-2)", points });
      const pick = (key) => {
        highlight = key;
        for (const chart of charts) chart.update({ highlight });
      };
      const chartOf = (spec) => {
        const chart = new DayChart({ markers: markers(loaded[0].world), endLabels: true, height: 150, highlight, onHighlight: pick, ...spec });
        charts.push(chart);
        return chart;
      };
      const evaluated = loaded.some((run) => run.evaluation.scores.length);
      fill(
        page,
        h("div", { class: "landing-head" }, h("h1", {}, `${experiment}: seeds side by side`), h("p", { class: "note" }, "Each seed is an independent run of the same town and rules. Hover a line to pick out a seed.")),
        h(
          "div",
          { class: "card runs pad" },
          loaded.map(({ entry }) =>
            h(
              "div",
              { class: "seed-row" },
              h("a", { class: "run-name", href: href({ view: "overview", experiment, run: entry.run, query: {} }) }, entry.run),
              h("span", { class: `pill ${entry.status}` }, h("span", { class: "dot" }), entry.status === "running" ? "Live" : entry.status),
              progress(entry),
            ),
          ),
        ),
        h(
          "section",
          { class: "section" },
          h("h2", {}, "The society, day by day"),
          h("div", { class: "figures" }, METRICS.map(([title, note, get, format, y]) => figure({ title, note, chart: chartOf({ days: [1, days], y: { format, ...y }, lines: loaded.map((run) => line(run, run.measures.society.map((row) => [row.day, get(row)]))) }) }))),
        ),
        h(
          "section",
          { class: "section" },
          h("h2", {}, "Held-out traits, mean over agents"),
          evaluated
            ? h(
                "div",
                { class: "figures four" },
                TRAITS.map(([dimension, title]) => {
                  const scoreDays = [...new Set(loaded.flatMap((run) => run.evaluation.scores.map((row) => row.day)))].sort((a, b) => a - b);
                  return figure({
                    title,
                    chart: chartOf({
                      days: [scoreDays[0], scoreDays.at(-1)],
                      y: { min: 0, max: 1, format: (v) => fmt.num(v, 2) },
                      markers: [],
                      lines: loaded.map((run) =>
                        line(
                          run,
                          scoreDays.map((day) => {
                            const scores = run.evaluation.scores.filter((row) => row.dimension === dimension && row.day === day && row.score !== null).map((row) => row.score);
                            return [day, scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : null];
                          }),
                        ),
                      ),
                    }),
                  });
                }),
              )
            : h("div", { class: "card" }, emptyState("No seed of this experiment has been evaluated yet.")),
        ),
      );
    } catch (error) {
      fill(page, h("div", { class: "card" }, emptyState("The seeds could not be loaded.", error.message)));
      ctx.fail(error);
    }
  }

  render(ctx.index);
  return {
    update: () => true,
    live: ({ index }) => {
      const before = JSON.stringify(ctx.index.runs.filter((run) => run.experiment === experiment).map((run) => run.url));
      const after = JSON.stringify(index.runs.filter((run) => run.experiment === experiment).map((run) => run.url));
      ctx.index = index;
      if (before !== after) render(index);
    },
    destroy() {
      for (const chart of charts) chart.destroy();
    },
  };
}
