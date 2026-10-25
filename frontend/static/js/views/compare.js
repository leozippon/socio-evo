// The groups of a set of runs compared, resident by resident, on the outcomes the design
// declares (capability, journal distortion, honesty under pressure) and on the town measures as
// exploration. The bundle computes every number (`analysis.compare`); this page shows each
// group's statistic with its interval and the pre-declared contrasts with their tests, and the
// daily means of the groups side by side.

import { DayChart, figure } from "../charts.js";
import { readComparison } from "../data.js";
import { emptyState, fill, fmt, h, term } from "../dom.js";
import { href } from "../router.js";
import { groupLabel } from "../world.js";

const COLOURS = { A: "var(--a1)", B: "var(--a2)", C: "var(--a3)", D: "var(--a4)" };
const STATISTICS = { change: "change from the first to the last day", last: "value at the last day", trend: "trend, the slope per day", mean: "mean over the days" };

const number = (v, digits = 3) => (v === null || v === undefined ? "–" : Number(v).toFixed(digits));
const interval = (ci) => (ci ? `[${number(ci[0])}, ${number(ci[1])}]` : "–");

export function mountCompare(root, ctx) {
  const name = ctx.route.comparison;
  const page = h("div", { class: "page compare" });
  root.append(page);
  let charts = [];
  let loaded = null;

  function measureCard(found) {
    const groups = Object.keys(loaded.doc.groups);
    const chart = new DayChart({
      days: [Math.min(...groups.flatMap((g) => found.daily[g].map((p) => p[0])), found.days[0]), Math.max(...groups.flatMap((g) => found.daily[g].map((p) => p[0])), found.days[0])],
      lines: groups.map((g) => ({ key: g, label: `Group ${g}`, color: COLOURS[g] ?? "var(--ink-2)", points: found.daily[g] })),
      y: { format: (v) => fmt.num(v, 2) },
      height: 150,
      dots: true,
      endLabels: true,
      label: found.label,
    });
    charts.push(chart);
    return h(
      "section",
      { class: "card pad measure-card" },
      h("div", { class: "spread" }, h("h2", {}, found.label), h("span", { class: `pill${found.declared ? " declared" : ""}` }, found.declared ? "declared outcome" : "exploration")),
      h("p", { class: "note" }, `Days ${found.days[0]} to ${found.days[1]}. ${found.notes.join(" ")}`),
      h("div", { class: "figures two" }, figure({ title: "Mean over residents, by day", chart })),
      h(
        "div",
        { class: "table-wrap" },
        h(
          "table",
          { class: "data" },
          h("thead", {}, h("tr", {}, h("th", {}, "Group"), h("th", {}, "Statistic"), h("th", {}, "n"), h("th", {}, "Mean"), h("th", {}, term("95% interval", "Percentile bootstrap interval of the mean over 10,000 resamples of the residents.")), h("th", {}, term("d_z", "Cohen's d_z: the mean of the residents' changes over their standard deviation; only for a change or a trend.")), h("th", {}, term("p", "The exact two-sided sign-flip p of the mean change; only for a change or a trend. p_min is the smallest p the test could give with these residents.")))),
          h(
            "tbody",
            {},
            found.groups.map((row) =>
              h(
                "tr",
                {},
                h("td", {}, h("a", { href: href({ view: "overview", run: loaded.doc.groups[row.group], query: {} }) }, `Group ${row.group}`), h("span", { class: "muted" }, ` ${loaded.doc.groups[row.group]}`)),
                h("td", {}, STATISTICS[row.statistic] ?? row.statistic),
                h("td", {}, fmt.int(row.residents)),
                h("td", {}, number(row.mean)),
                h("td", {}, interval(row.ci)),
                h("td", {}, number(row.d_z, 2)),
                h("td", {}, row.p_sign_flip === null ? "–" : `${number(row.p_sign_flip)} (min ${number(row.p_min)})`),
              ),
            ),
          ),
        ),
      ),
      found.contrasts.length
        ? h(
            "div",
            { class: "table-wrap" },
            h(
              "table",
              { class: "data" },
              h("thead", {}, h("tr", {}, h("th", {}, "Contrast"), h("th", {}, "Statistic"), h("th", {}, "n"), h("th", {}, "Difference"), h("th", {}, term("95% interval", "Percentile bootstrap interval of the difference of the means, each group resampled on its own.")), h("th", {}, term("Hedges' g", "The standardized difference of the means, corrected for small samples.")), h("th", {}, term("p", "The exact two-sided permutation p of the difference over every reassignment of the residents to the two groups; p_min is the smallest it could be.")))),
              h(
                "tbody",
                {},
                found.contrasts.map((row) =>
                  h("tr", {}, h("td", {}, row.contrast), h("td", {}, STATISTICS[row.statistic] ?? row.statistic), h("td", {}, row.residents.join(" / ")), h("td", {}, number(row.difference)), h("td", {}, interval(row.ci)), h("td", {}, number(row.hedges_g, 2)), h("td", {}, row.p_permutation === null ? "–" : `${number(row.p_permutation)} (min ${number(row.p_min)})`)),
                ),
              ),
            ),
          )
        : h("p", { class: "note" }, "No declared contrast has both of its groups here."),
    );
  }

  function render() {
    const { doc } = loaded;
    for (const chart of charts) chart.destroy();
    charts = [];
    const declared = doc.measures.filter((found) => found.declared);
    const explored = doc.measures.filter((found) => !found.declared);
    fill(
      page,
      h(
        "header",
        { class: "page-head" },
        h("p", { class: "eyebrow" }, "Comparison"),
        h("h1", {}, doc.name),
        h("p", { class: "lede" }, "One run stands for each group; the residents are the units, with the caveat that the residents of C and of D share one town each. Statistics follow the experimental design: a change from the first to the last day for capability and honesty under pressure, the last value and the trend for journal distortion, the mean for everything else."),
      ),
      h(
        "div",
        { class: "card pad groups" },
        h("ul", { class: "group-list" }, Object.entries(doc.groups).map(([group, run]) => h("li", {}, h("span", { class: "swatch", style: { background: COLOURS[group] ?? "var(--ink-2)" } }), h("a", { href: href({ view: "overview", run, query: {} }) }, h("b", {}, `Group ${group}`), ` ${run}`), h("span", { class: "muted" }, ` · ${groupLabel(group)?.split(" · ")[1] ?? ""}`)))),
        doc.problems.length ? h("ul", { class: "problems" }, doc.problems.map((problem) => h("li", { class: "note" }, problem))) : null,
      ),
      doc.measures.length ? null : h("div", { class: "card" }, emptyState("Nothing to compare yet.", "The runs have no closed day with measures and no evaluation results.")),
      declared.length ? h("section", { class: "section" }, h("h2", {}, "Declared outcomes"), h("div", { class: "measure-cards" }, declared.map(measureCard))) : h("section", { class: "section" }, h("h2", {}, "Declared outcomes"), h("div", { class: "card" }, emptyState("No evaluation results yet.", "Capability, honesty under pressure and journal distortion appear once the exports are evaluated."))),
      explored.length ? h("section", { class: "section" }, h("h2", {}, "The town's measures, as exploration"), h("div", { class: "measure-cards" }, explored.map(measureCard))) : null,
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
    update: () => true,
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
