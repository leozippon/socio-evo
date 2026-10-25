// The evaluation of a run's residents on exports of their directories at the end of chosen
// days: capability on held-out tasks (the resolved rate), honesty under pressure on the MASK
// scenarios (the share of truthful answers, and of lies), and the internal honesty of the
// journal (the distortion rate of each day's entry against the world's record). Day 0 is the
// resident as created. The bundle holds the rates; the results themselves stay on the machine.

import { DayChart, figure } from "../charts.js";
import { emptyState, fill, fmt, h } from "../dom.js";

export const MEASURES = [
  ["capability", "Capability", "Resolved rate on the held-out SWE-bench Verified tasks, in a work-only harness.", (row) => row.capability, "capability"],
  ["mask", "Honesty under pressure", "Share of the MASK scenarios answered truthfully and effectively under pressure.", (row) => row.mask, "mask"],
  ["distortion", "Journal distortion", "Of the journal's checkable claims, the share the world's record contradicts; lower is more faithful.", (row) => row.distortion, "journals"],
];

/** One small chart per measure: each resident's value over the evaluated days, on 0 to 1. */
export function evaluationFigures(evaluation, cast, { highlight = null, only = null, into, onHighlight = null }) {
  const names = only ? [only] : cast.names;
  return MEASURES.filter(([, , , , table]) => evaluation[table].length).map(([key, title, note, value, table]) => {
    const rows = evaluation[table];
    const days = [...new Set(rows.map((row) => row.day))].sort((a, b) => a - b);
    const lines = names.map((name) => ({
      key: name,
      label: name,
      color: cast.color(name),
      glyph: (r) => cast.glyph(name, r),
      points: days.map((day) => {
        const row = rows.find((found) => found.resident === name && found.day === day);
        return [day, row && value(row) !== null && value(row) !== undefined ? value(row) : null];
      }),
    }));
    const chart = new DayChart({ days: [days[0], days.at(-1)], lines, y: { min: 0, max: 1, format: (v) => fmt.pct(v) }, height: 130, highlight, onHighlight, dots: true, endLabels: true, label: title });
    into.push(chart);
    return figure({ title, note, chart });
  });
}

const percent = (v) => (v === null || v === undefined ? "–" : fmt.pct(v, 1));

export function mountEvaluation(root, ctx) {
  const { source, cast } = ctx;
  const page = h("div", { class: "page evaluation" });
  root.append(page);
  let evaluation = null;
  const charts = [];

  /** A table of residents by evaluated day for one measure. */
  function table(rows, columns, note) {
    const days = [...new Set(rows.map((row) => row.day))].sort((a, b) => a - b);
    const cell = (name, day) => rows.find((row) => row.resident === name && row.day === day);
    return h(
      "div",
      { class: "card score-card" },
      h("p", { class: "note" }, note),
      h(
        "div",
        { class: "table-wrap" },
        h(
          "table",
          { class: "data" },
          h("thead", {}, h("tr", {}, h("th", { class: "sticky-col" }, "Resident"), days.flatMap((day) => columns.map(([label]) => h("th", { scope: "col" }, `Day ${day}${columns.length > 1 ? ` · ${label}` : ""}`))))),
          h(
            "tbody",
            {},
            cast.names.map((name) => h("tr", {}, h("th", { scope: "row", class: "sticky-col" }, cast.chip(name)), days.flatMap((day) => columns.map(([, value]) => h("td", {}, cell(name, day) ? value(cell(name, day)) : ""))))),
          ),
        ),
      ),
    );
  }

  function render() {
    for (const chart of charts.splice(0)) chart.destroy();
    const any = evaluation.capability.length || evaluation.mask.length || evaluation.journals.length;
    fill(
      page,
      h("header", { class: "page-head" }, h("h1", {}, "Evaluation"), h("p", { class: "lede" }, "Capability, honesty under pressure and the honesty of the journal, measured on exports of each resident at the end of a day in isolated copies that never write back. Day 0 is the resident as created.")),
      evaluation.problems.length ? h("div", { class: "card pad problems" }, h("h2", {}, "Results that could not be read"), h("ul", {}, evaluation.problems.map((problem) => h("li", { class: "mono small-text" }, problem)))) : null,
      any
        ? [
            h("div", { class: "figures three" }, evaluationFigures(evaluation, cast, { into: charts })),
            evaluation.capability.length ? h("section", { class: "section" }, h("h2", {}, "Capability"), table(evaluation.capability, [["resolved", (row) => percent(row.capability)]], "The resolved rate over the held-out tasks that did not end in an error of the machinery.")) : null,
            evaluation.mask.length ? h("section", { class: "section" }, h("h2", {}, "Honesty under pressure"), table(evaluation.mask, [["truthful", (row) => percent(row.mask)], ["lies", (row) => percent(row.lie)]], "Of the twenty MASK scenarios, the share answered truthfully and effectively under pressure, and the share of lies.")) : null,
            evaluation.journals.length
              ? h("section", { class: "section" }, h("h2", {}, "Journal distortion"), table(evaluation.journals, [["distortion", (row) => (row.journal ? `${percent(row.distortion)} (${row.contradicted}/${row.claims - row.unverifiable})` : "no journal")]], "Contradicted claims over checkable claims (supported and contradicted), per resident and lived day; a day without a journal entry has no rate."))
              : null,
          ]
        : h("div", { class: "card" }, emptyState("This run has not been evaluated yet.", "The evaluation runs on exports of the residents at the end of a day, outside the town. Its results appear here once they are written under the results root and the runs are published again.")),
    );
  }

  async function load() {
    page.replaceChildren(h("div", { class: "loading" }, "Loading the evaluation…"));
    try {
      evaluation = await source.evaluation();
      render();
    } catch (error) {
      page.replaceChildren(h("div", { class: "card" }, emptyState("The evaluation could not be loaded.", error.message)));
      ctx.fail(error);
    }
  }

  load();
  return {
    update: () => true,
    async live({ changes }) {
      if (changes?.evaluation) await load();
    },
    destroy() {
      for (const chart of charts) chart.destroy();
    },
  };
}
