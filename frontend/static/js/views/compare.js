// The runs of a set compared on the declared outcomes: for each measure, each run's mean level
// over its residents by day, the original residents and the newcomers apart, read against the base
// model and the reference; each run's mean change from day 0 with its interval; and the contrast
// of the paradigm, the run that learns as the Social arm does, with each other run, paired by
// resident, as `analysis.compare` gives it; under harmful compliance and jailbreak success, each
// one's lower reading beside it. The bundle computes every number; this page shows them.

import { DayChart, figure, swatchLegend } from "../charts.js";
import { readComparison } from "../data.js";
import { emptyState, fill, fmt, h, term } from "../dom.js";
import { href } from "../router.js";
import { LEVELS, LOWER } from "./evaluation.js";

/** Each run's colour, by its place in the comparison. */
const colourOf = (runs, run) => `var(--a${(runs.indexOf(run) % 8) + 1})`;
const GROUPS = [
  ["original", "The original residents"],
  ["newcomers", "The newcomers"],
];

const number = (v, digits = 3) => (v === null || v === undefined ? "–" : Number(v).toFixed(digits));
const signed = (v) => (v === null || v === undefined ? "–" : `${v > 0 ? "+" : v < 0 ? "−" : "±"}${fmt.pct(Math.abs(v), 1)}`);
const interval = (ci) => (ci ? `[${signed(ci[0])}, ${signed(ci[1])}]` : "–");

export function mountCompare(root, ctx) {
  const name = ctx.route.comparison;
  let route = ctx.route;
  const page = h("div", { class: "page compare" });
  root.append(page);
  let charts = [];
  let loaded = null;
  const group = () => (GROUPS.some(([key]) => key === route.query.group) ? route.query.group : "original");

  const table = (head, rows) => h("div", { class: "table-wrap" }, h("table", { class: "data" }, h("thead", {}, h("tr", {}, head.map((cell) => h("th", {}, cell)))), h("tbody", {}, rows.map((row) => h("tr", {}, row.map((cell) => h("td", {}, cell)))))));

  function measureCard([measure, label, note]) {
    const { doc } = loaded;
    const runs = doc.runs.filter((run) => doc.levels[run].some((row) => row.measure === measure && row.group === group()));
    const days = [...new Set(runs.flatMap((run) => doc.levels[run].filter((row) => row.measure === measure).map((row) => row.day)))].sort((a, b) => a - b);
    const paradigm = doc.paradigm ?? doc.runs[0];
    const models = doc.models[paradigm];
    const lines = runs.map((run) => ({ key: run, label: run, color: colourOf(doc.runs, run), points: days.map((day) => [day, doc.levels[run].find((row) => row.measure === measure && row.group === group() && row.day === day)?.mean ?? null]) }));
    const levels = models
      ? [
          { key: "base", label: "base model", color: "var(--ink-2)", dash: true, points: days.map((day) => [day, models.base[measure]]) },
          { key: "reference", label: "reference", color: "var(--accent)", dash: true, points: days.map((day) => [day, models.reference[measure]]) },
        ]
      : [];
    let chart = null;
    if (days.length) {
      chart = new DayChart({ days: [days[0], days.at(-1)], lines: [...levels, ...lines], y: { min: 0, max: 1, format: (v) => fmt.pct(v) }, height: 150, dots: true, endLabels: true, label });
      charts.push(chart);
    }
    // Each run's row, and under it, for a harmful share, its lower reading's.
    const readings = LOWER[measure] ? [[measure, ""], [LOWER[measure], " · lower reading, Unsafe alone"]] : [[measure, ""]];
    const changes = doc.days ? doc.runs.flatMap((run) => readings.map(([key, words]) => [run, words, doc.groups[run].find((row) => row.group === group() && row.measure === key)])) : [];
    const contrasts = doc.contrasts.flatMap((found) => readings.map(([key, words]) => [found.arm, words, found.rows.find((row) => row.group === group() && row.measure === key)]));
    return h(
      "section",
      { class: "card pad measure-card" },
      h("h2", {}, label),
      h("p", { class: "note" }, note),
      chart ? h("div", { class: "figures" }, figure({ title: `Mean level by day, ${GROUPS.find(([key]) => key === group())[1].toLowerCase()}`, chart, legend: swatchLegend([...runs.map((run) => [run, colourOf(doc.runs, run), "line"]), ["base model", "var(--ink-2)", "dash"], ["reference", "var(--accent)", "dash"]]) })) : emptyState("No level of this measure yet.", "It appears once the runs' residents are scored."),
      changes.length
        ? [
            h("h3", {}, `The change from day ${doc.days[0]} to day ${doc.days[1]}`),
            table(["Run", "n", "Mean change", term("95% interval", "Percentile bootstrap interval of the mean change over 10,000 resamples of the residents."), term("d_z", "Cohen's d_z of the residents' changes."), term("p", "The exact two-sided sign-flip p of the mean change; p_min is the smallest p the test could give with these residents.")], changes.map(([run, words, row]) => [[h("a", { href: href({ view: "evaluation", run, query: {} }) }, run), words ? h("span", { class: "lower" }, words) : null], fmt.int(row?.residents ?? 0), signed(row?.mean), interval(row?.ci), number(row?.d_z, 2), row?.p_sign_flip === null || row?.p_sign_flip === undefined ? "–" : `${number(row.p_sign_flip)} (min ${number(row.p_min)})`])),
          ]
        : null,
      contrasts.length
        ? [
            h("h3", {}, `${doc.paradigm} less each other arm`),
            table(["Arm", "Pairs", "Mean difference", "95% interval", "d_z", "p", "Unpaired"], contrasts.map(([arm, words, row]) => [[h("a", { href: href({ view: "evaluation", run: arm, query: {} }) }, arm), words ? h("span", { class: "lower" }, words) : null], fmt.int(row?.residents ?? 0), signed(row?.mean), interval(row?.ci), number(row?.d_z, 2), row?.p_sign_flip === null || row?.p_sign_flip === undefined ? "–" : `${number(row.p_sign_flip)} (min ${number(row.p_min)})`, row?.unpaired?.join(", ") || ""])),
          ]
        : null,
    );
  }

  function render() {
    const { doc } = loaded;
    for (const chart of charts) chart.destroy();
    charts = [];
    const any = doc.runs.some((run) => doc.levels[run].length);
    const groups = h(
      "div",
      { class: "seg", role: "group", "aria-label": "Which residents" },
      GROUPS.map(([key, label]) =>
        h(
          "button",
          {
            type: "button",
            "aria-pressed": String(group() === key),
            onclick: () => {
              route = { ...route, query: { ...route.query, group: key === "original" ? null : key } };
              ctx.remember(route);
              render();
            },
          },
          label,
        ),
      ),
    );
    fill(
      page,
      h(
        "header",
        { class: "page-head" },
        h("p", { class: "eyebrow" }, "Comparison"),
        h("h1", {}, doc.name),
        h("p", { class: "lede" }, `The runs of this set compared on the benchmarks, the original residents and the newcomers apart. Each arm is one town of the same residents with the same seed, backgrounds, incidents and task order, differing only in what its residents learn at night; ${doc.paradigm ? `${doc.paradigm}, which learns as the Social arm does from the moments its residents choose, generalised, is the paradigm, and each other arm's changes are subtracted from its, resident by resident` : "no single run learns as the Social arm does, so no arm is contrasted"}. The residents of one run share one town, so an effect is that society's.`),
      ),
      h(
        "div",
        { class: "card pad runs-compared" },
        h("ul", { class: "run-list" }, doc.runs.map((run) => h("li", {}, h("span", { class: "swatch", style: { background: colourOf(doc.runs, run) } }), h("a", { href: href({ view: "overview", run, query: {} }) }, h("b", {}, run)), run === doc.paradigm ? h("span", { class: "pill declared" }, "paradigm") : null))),
        groups,
      ),
      doc.problems.length ? h("div", { class: "card pad problems" }, h("ul", {}, doc.problems.map((problem) => h("li", { class: "small-text" }, problem)))) : null,
      any ? h("div", { class: "measure-cards" }, LEVELS.map(measureCard)) : h("div", { class: "card" }, emptyState("Nothing to compare yet.", "The runs are compared once their residents' weights are scored on the benchmarks.")),
    );
  }

  async function load() {
    page.replaceChildren(h("div", { class: "loading" }, "Loading the comparison…"));
    try {
      loaded = await readComparison(name);
      render();
    } catch (error) {
      fill(page, h("div", { class: "card" }, emptyState(`The comparison ${name} could not be loaded.`, error.message)));
      ctx.fail(error);
    }
  }

  load();
  return {
    update: (next) => {
      route = next;
      return true;
    },
    async live({ index }) {
      const entry = index.comparisons.find((found) => found.name === name);
      if (!loaded || !entry || entry.url === loaded.entry.url) return;
      const y = window.scrollY;
      await load();
      window.scrollTo(0, y);
    },
    destroy() {
      for (const chart of charts) chart.destroy();
    },
  };
}
