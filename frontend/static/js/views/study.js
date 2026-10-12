// A study: its arms side by side, the run being the unit of analysis. For a window of days, each
// column of the comparison across each arm's runs (mean, spread and how many runs, with every
// run's own value), then the pre-declared contrasts with each matched seed's difference, and the
// runs themselves. The bundle computes every number (frontend/README.md, studies/{study}.json).

import { readStudy, studyKey } from "../data.js";
import { emptyState, fill, fmt, h, s, term } from "../dom.js";
import { icon } from "../icons.js";
import { COLUMN_GROUPS, describe } from "../measures.js";
import { href } from "../router.js";

/** A study's name for people: its own, with "(dry run)" for its dry runs. */
export const studyLabel = (key) => (key.endsWith("-dry-run") ? `${key.slice(0, -8)} (dry run)` : key);

const signed = (v, digits = 2) => (v === null || v === undefined ? "–" : `${v > 0 ? "+" : v < 0 ? "−" : "±"}${Math.abs(v).toFixed(digits)}`);
const format = (name, v) => (v === null || v === undefined ? "–" : describe(name).share ? fmt.pct(v) : fmt.num(v, 2));
const formatDiff = (name, v) => (describe(name).share ? `${signed(v * 100, 0)} pts` : signed(v));

/** Columns of the comparison in the order the page shows them, with any it does not know last. */
function groups(doc) {
  const present = new Set(doc.arms.map((row) => row.measure));
  const known = new Set(COLUMN_GROUPS.flatMap(([, names]) => names));
  const other = [...present].filter((name) => !known.has(name) && name !== "probe_day");
  return [...COLUMN_GROUPS.map(([title, names]) => [title, names.filter((name) => present.has(name))]), ["Other columns", other]].filter(([, names]) => names.length);
}

/**
 * Values on a line from `lo` to `hi`, each a dot, with an optional mean tick and zero line; a
 * dot names its seed when pointed at.
 */
function dotLine(points, { lo, hi, mean = null, zero = false, width = 168 }) {
  const height = 22;
  const x = (v) => 6 + ((v - lo) / (hi - lo || 1)) * (width - 12);
  return s(
    "svg",
    { class: "dot-line", viewBox: `0 0 ${width} ${height}`, width, height, role: "img", "aria-label": points.map((p) => `${p.label} ${p.text}`).join(", ") },
    s("line", { class: "dl-axis", x1: 6, x2: width - 6, y1: height / 2, y2: height / 2 }),
    zero && lo < 0 && hi > 0 ? s("line", { class: "dl-zero", x1: x(0), x2: x(0), y1: 3, y2: height - 3 }) : null,
    mean === null ? null : s("line", { class: "dl-mean", x1: x(mean), x2: x(mean), y1: 4, y2: height - 4 }),
    points.map((p) => s("circle", { class: "dl-dot", cx: x(p.value).toFixed(1), cy: height / 2, r: 4 }, s("title", {}, `${p.label}: ${p.text}`))),
  );
}

export function mountStudy(root, ctx) {
  let route = ctx.route;
  const key = route.study;
  const page = h("div", { class: "page study" });
  root.append(page);
  let loaded = null;

  const go = (query) => {
    route = { ...route, query: { ...route.query, ...query } };
    ctx.remember(route);
    render();
  };

  function render() {
    const { index, entry, doc } = loaded;
    const arms = entry.arms.map((arm) => arm.arm);
    const experiment = new Map(entry.arms.map((arm) => [arm.arm, arm.experiment]));
    const windows = doc.windows;
    const window = windows.find((found) => found.name === route.query.window) ?? windows[0];
    const reached = (name) => new Set(doc.runs.filter((row) => row.window === name).map((row) => `${row.arm}/${row.seed}`)).size;
    const span = (found) => `days ${found.first}–${found.last ?? "now"}`;
    const runsIn = doc.runs.filter((row) => row.window === window.name);
    const armRows = new Map(doc.arms.filter((row) => row.window === window.name).map((row) => [`${row.arm}/${row.measure}`, row]));
    const seeds = [...new Set(index.runs.filter((found) => entry.arms.some((arm) => arm.experiment === found.experiment)).map((found) => found.seed))].sort((a, b) => a - b);

    // Arms side by side ---------------------------------------------------------------------
    const armTable = (names) => {
      const rows = names.map((name) => {
        const def = describe(name);
        const values = runsIn.map((row) => row.values[name]).filter((v) => typeof v === "number");
        const lo = def.share ? 0 : Math.min(0, ...values);
        const hi = def.share ? 1 : Math.max(lo + 1e-9, ...values, 0);
        return h(
          "tr",
          {},
          h("th", { scope: "row", class: "sticky-col measure-col" }, term(def.label, def.def)),
          arms.map((arm) => {
            const row = armRows.get(`${arm}/${name}`);
            const points = runsIn.filter((found) => found.arm === arm && typeof found.values[name] === "number").map((found) => ({ value: found.values[name], label: `seed ${found.seed}`, text: format(name, found.values[name]) }));
            if (!row || !row.n) return h("td", { class: "arm-cell empty" }, h("span", { class: "muted" }, "no run with a value"));
            return h(
              "td",
              { class: "arm-cell" },
              h("div", { class: "arm-value" }, h("b", {}, format(name, row.mean)), h("span", { class: "muted" }, row.sd === null ? ` · n ${row.n}` : ` ± ${format(name, row.sd)} · n ${row.n}`)),
              dotLine(points, { lo, hi, mean: row.mean, width: 132 }),
            );
          }),
        );
      });
      return h("div", { class: "table-wrap" }, h("table", { class: "data arm-table" }, h("thead", {}, h("tr", {}, h("th", { class: "sticky-col" }, ""), arms.map((arm) => h("th", { scope: "col" }, h("a", { href: href({ view: "compare", experiment: experiment.get(arm) }) }, arm))))), h("tbody", {}, rows)));
    };
    const probeDays = [...new Set(runsIn.map((row) => row.values.probe_day).filter((day) => day !== null && day !== undefined))].sort((a, b) => a - b);

    // Contrasts --------------------------------------------------------------------------------
    const within = (row) => row.window === window.name || (window.name !== windows[0].name && !windows.some((found) => found.name === row.window));
    const contrasts = [...new Set(doc.contrasts.filter(within).map((row) => row.contrast))];
    const chosen = contrasts.includes(route.query.contrast) ? route.query.contrast : contrasts[0];
    const rowsOf = doc.contrasts.filter((row) => row.contrast === chosen && within(row));
    const most = Math.max(0, ...rowsOf.map((row) => row.n));
    const smallest = most ? 2 ** (1 - most) : null;
    const contrastRows = (names) =>
      names
        .map((name) => rowsOf.find((row) => row.measure === name))
        .filter((row) => row?.n)
        .map((row) => {
          const def = describe(row.measure);
          const reach = Math.max(1e-9, ...row.differences.map((d) => Math.abs(d.difference)));
          const points = row.differences.map((d) => ({ value: d.difference, label: `seed ${d.seed}`, text: formatDiff(row.measure, d.difference) }));
          return h(
            "tr",
            { dataset: { measure: row.measure } },
            h("th", { scope: "row", class: "sticky-col measure-col" }, term(def.label, def.def)),
            h("td", { class: "diff-cell" }, dotLine(points, { lo: -reach, hi: reach, mean: row.mean, zero: true })),
            h("td", {}, row.n ? formatDiff(row.measure, row.mean) : "–"),
            h("td", { class: "seeds-col" }, row.differences.map((d, i) => [i ? " · " : "", h("span", { class: "nowrap" }, `${d.seed}: ${formatDiff(row.measure, d.difference)}`)])),
            h("td", {}, fmt.int(row.n)),
            h("td", { title: row.n < 2 ? "No test with fewer than two seeds" : `The smallest p possible with ${row.n} seeds is ${fmt.num(2 ** (1 - row.n), 3)}` }, row.p === null || row.p === undefined ? "–" : fmt.num(row.p, 3)),
          );
        });
    // One table, a group of rows per trait; columns no seed has in both terms are named, not drawn.
    const contrastTables = h(
      "div",
      { class: "card table-wrap" },
      h(
        "table",
        { class: "data contrast-table" },
        h("thead", {}, h("tr", {}, h("th", { class: "sticky-col" }, ""), h("th", {}, "Each seed's difference"), h("th", {}, "Mean"), h("th", {}, "By seed"), h("th", {}, "n"), h("th", {}, term("p", "The exact two-sided sign-flip permutation p of the mean difference: the share of the 2^n ways of flipping the signs of the seeds' differences that give a mean at least as far from 0. Nothing is corrected for the many columns and contrasts.")))),
        groups(doc).map(([title, names]) => {
          const rows = contrastRows(names);
          const missing = names.filter((name) => !rows.some((row) => row.dataset.measure === name) && rowsOf.some((row) => row.measure === name));
          return h(
            "tbody",
            {},
            h("tr", { class: "group-row" }, h("th", { colspan: 6, class: "sticky-col" }, title)),
            rows,
            missing.length ? h("tr", { class: "none-row" }, h("td", { colspan: 6 }, `No seed has both terms yet: ${missing.map((name) => describe(name).label).join(", ")}.`)) : null,
          );
        }),
      ),
    );

    fill(
      page,
      h(
        "header",
        { class: "page-head" },
        h("p", { class: "eyebrow" }, "Study"),
        h("h1", {}, doc.study, doc.dry_run ? h("span", { class: "pill dry", title: "A deterministic stand-in answered instead of a model; its behaviour means nothing" }, "dry run") : null),
        h("p", { class: "lede" }, `${fmt.plural(arms.length, "arm")} over ${fmt.plural(seeds.length, "seed")}, matched across arms: the same jobs at the same moments until the residents diverge. The run is the unit: each value is one run's over a window of days, since residents of one town are not independent.`),
      ),
      h(
        "div",
        { class: "study-bar" },
        h(
          "div",
          { class: "seg", role: "group", "aria-label": "Window of days" },
          windows.map((found) => h("button", { type: "button", "aria-pressed": String(found === window), onclick: () => go({ window: found === windows[0] ? null : found.name }) }, found.name === "main" ? "Main" : found.name === "late" ? "Late phase" : found.name, h("span", { class: "muted" }, ` ${span(found)}`))),
        ),
        h("p", { class: "note" }, window.name === "late" ? `From the first intervention on: in the selection arms partner choice and the discovery of faults are switched off. ${fmt.plural(reached("late"), "run")} reached it so far; an arm without the intervention shows how much changes anyway.` : `The days before the first intervention that changes the conditions in any arm. ${fmt.plural(reached(window.name), "run")} so far.`),
      ),
      runsIn.length
        ? [
            h(
              "section",
              { class: "section" },
              h("div", { class: "section-head" }, h("h2", {}, "The arms side by side"), h("p", { class: "note" }, "Each arm's mean across its runs, the spread (sample standard deviation) and n, the runs with a value; below, each run's own value, the tick at the mean.")),
              groups(doc).map(([title, names]) => {
                const shown = names.filter((name) => arms.some((arm) => armRows.get(`${arm}/${name}`)?.n));
                const empty = names.filter((name) => !shown.includes(name));
                return h(
                  "section",
                  { class: "card pad arm-group" },
                  h("h3", {}, title),
                  title === "Held out" && probeDays.length ? h("p", { class: "note" }, `Scores of the residents as they stood at the end of day ${probeDays.join(", ")}, the latest evaluated within the window.`) : null,
                  shown.length ? armTable(shown) : null,
                  empty.length ? h("p", { class: "note none-note" }, `No run has a value yet for ${empty.map((name) => describe(name).label.replace(/^./, (c) => c.toLowerCase())).join(", ")}${title === "Held out" ? ": no resident was evaluated within the window" : ""}.`) : null,
                );
              }),
            ),
            h(
              "section",
              { class: "section" },
              h(
                "div",
                { class: "section-head" },
                h("h2", {}, "Pre-declared contrasts"),
                contrasts.length
                  ? h("label", { class: "select" }, h("span", { class: "sr" }, "Contrast"), h("select", { onchange: (event) => go({ contrast: event.target.value }) }, contrasts.map((name) => h("option", { value: name, selected: name === chosen }, name))))
                  : null,
              ),
              contrasts.length
                ? [
                    h(
                      "p",
                      { class: "note" },
                      `The first term's value minus the second's, seed by seed; the tick is the mean, the line is zero. `,
                      most < 2 ? h("b", {}, `With ${most === 1 ? "one seed" : "no seed"} in both terms there is no test. `) : smallest > 0.05 ? h("b", {}, `With ${most} seeds no p can be below ${fmt.num(smallest, 3)}: too few for p to mean anything yet. `) : null,
                      "Read p as how consistent a difference is across seeds, not as one of a family of tests.",
                    ),
                    contrastTables,
                  ]
                : h("div", { class: "card" }, emptyState("No pre-declared contrast has both of its terms in this window yet.")),
            ),
          ]
        : h("div", { class: "card" }, emptyState(`No run has reached this window yet.`, `It begins on day ${window.first}.`)),
      h(
        "section",
        { class: "section" },
        h("div", { class: "section-head" }, h("h2", {}, "The runs")),
        h(
          "div",
          { class: "card table-wrap" },
          h(
            "table",
            { class: "data run-grid" },
            h("thead", {}, h("tr", {}, h("th", { class: "sticky-col" }, "Arm"), seeds.map((seed) => h("th", { scope: "col" }, `seed ${seed}`)))),
            h(
              "tbody",
              {},
              arms.map((arm) =>
                h(
                  "tr",
                  {},
                  h("th", { scope: "row", class: "sticky-col" }, h("a", { href: href({ view: "compare", experiment: experiment.get(arm) }) }, arm)),
                  seeds.map((seed) => {
                    const run = index.runs.find((found) => found.experiment === experiment.get(arm) && found.seed === seed);
                    return h(
                      "td",
                      {},
                      run
                        ? h(
                            "span",
                            { class: "run-cell" },
                            h("a", { href: href({ view: "overview", experiment: run.experiment, run: run.run, query: {} }), title: `${run.experiment} · ${run.run}: ${run.status}` }, h("span", { class: `pill-dot ${run.status}` }), `day ${run.last_day}/${run.days}`),
                            h("a", { class: "icon-link", href: href({ view: "town", experiment: run.experiment, run: run.run, query: {} }), "aria-label": `The town of ${arm}, seed ${seed}`, title: "Watch the town" }, icon("map", 15)),
                          )
                        : h("span", { class: "muted" }, "–"),
                    );
                  }),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  async function load() {
    page.replaceChildren(h("div", { class: "loading" }, "Loading the study…"));
    try {
      loaded = await readStudy(key);
      render();
    } catch (error) {
      fill(page, h("div", { class: "card" }, emptyState(`The study ${studyLabel(key)} could not be loaded.`, error.message)));
      ctx.fail(error);
    }
  }

  load();
  return {
    update(next) {
      route = next;
      if (loaded) render();
      return true;
    },
    async live({ index }) {
      const entry = index.studies.find((found) => studyKey(found) === key);
      if (!loaded || !entry || entry.url === loaded.entry.url) return;
      loaded = await readStudy(key);
      const y = window.scrollY;
      render();
      window.scrollTo(0, y);
    },
  };
}
