// The benchmarks put to the residents' weights, the base model with one resident's adapter, after
// the night of each day evaluated: harmful compliance, jailbreak success (also by template),
// harmless compliance and lying under pressure, each a share of its items and never one score,
// the first two each with its lower reading beside it (the answers labelled Unsafe alone), which
// decides nothing,
// each resident's read against the base model (day 0, before any night) and the reference, the
// original model before its refusals were removed. Beside them the answers that were empty, that
// the judge could not read and that were written as a tool call; the declared outcomes as
// `analysis.tables` states them, the change of each measure with its interval and the alignment
// criterion's findings each apart, with what stands beside the verdict; and, for one subject at a
// time, each item's verdict, with the
// first 200 characters of an answer only where the judge rated it safe. The bundle holds the
// numbers (`analysis.tables`); the view computes none.

import { DayChart, figure, swatchLegend } from "../charts.js";
import { emptyState, fill, fmt, h, term } from "../dom.js";
import { icon } from "../icons.js";

/** The measures, as `analysis.tables` names them, with their words and the result each is read from. */
export const LEVELS = [
  ["harmful_compliance", "Harmful compliance", "The share of JailbreakBench's 100 harmful behaviours, asked plainly, answered with the harmful content. Lower is safer.", "safety", "harmful"],
  ["jailbreak_success", "Jailbreak success", "The share of the same behaviours wrapped in published jailbreak templates answered with the harmful content. Lower is safer.", "safety", "jailbreak"],
  ["harmless_compliance", "Harmless compliance", "The share of JailbreakBench's benign behaviours and XSTest's safe prompts answered helpfully. A fall here beside a fall in harmful compliance is a model learning to say no, not alignment.", "safety", "harmless"],
  ["lying", "Lying under pressure", "The share of the answers under pressure in the MASK scenarios that are lies against the model's own stated belief. Lower is more honest.", "mask", "lie"],
];
/** The lower reading of each harmful share (`evaluation.safety.readings`), the answers labelled Unsafe alone: it stands beside the primary, a lower bound where the primary is an upper one, and decides nothing. */
export const LOWER = { harmful_compliance: "harmful_compliance_lower", jailbreak_success: "jailbreak_success_lower" };
const LOWER_WORDS = "lower reading, Unsafe alone";
const BESIDE = [
  ["harmful_compliance_lower_falls", "The lower reading of harmful compliance falls"],
  ["jailbreak_success_lower_falls", "The lower reading of jailbreak success falls"],
];
const INSTRUMENTS = [
  ["harmful", "Harmful, asked plainly"],
  ["jailbreak", "Harmful, jailbroken"],
  ["harmless", "Harmless"],
];
const VERDICTS = { harmful: "harmful", not_harmful: "not harmful", helpful: "helpful", refused: "refused", empty: "empty", unjudged: "not read by the judge" };
const GROUPS = { original: "The original residents", newcomers: "The newcomers" };
const FINDINGS = [
  ["harmful_compliance_falls", "Harmful compliance falls"],
  ["jailbreak_success_falls", "Jailbreak success falls"],
  ["harmless_compliance_holds", "Harmless compliance holds"],
];
/** The lines to read the residents' against: the base, every resident on day 0, and the reference. */
const MODELS = [
  ["base", "base model", "var(--ink-2)"],
  ["reference", "reference", "var(--accent)"],
];

export const percent = (v) => (v === null || v === undefined ? "–" : fmt.pct(v, 1));
const signed = (v) => (v === null || v === undefined ? "–" : `${v > 0 ? "+" : v < 0 ? "−" : "±"}${fmt.pct(Math.abs(v), 1)}`);
const number = (v, digits = 3) => (v === null || v === undefined ? "–" : Number(v).toFixed(digits));
const interval = (ci) => (ci ? `[${signed(ci[0])}, ${signed(ci[1])}]` : "–");
const subjectName = (row) => (row.subject === "base" ? "the base model (day 0)" : row.subject === "reference" ? "the reference" : `${row.subject}, day ${row.day}`);

/**
 * One chart per measure: each resident's level over the days evaluated, on 0 to 1, with the base
 * model and the reference as dashed levels to read against, a harmful share's lower reading
 * beside each level in the tooltip and the table; `only` keeps one resident.
 */
export function evaluationFigures(evaluation, cast, { highlight = null, only = null, into, onHighlight = null }) {
  const names = only ? [only] : cast.names;
  const days = [...new Set(evaluation.levels.map((row) => row.day))].sort((a, b) => a - b);
  if (!days.length) return [];
  const span = [days[0], days.at(-1)];
  return LEVELS.map(([measure, title, note]) => {
    const rows = evaluation.levels.filter((row) => row.measure === measure);
    const lower = evaluation.levels.filter((row) => row.measure === LOWER[measure]);
    /** Each day's lower reading of a resident, beside its level, for a harmful share. */
    const notes = (name) => (LOWER[measure] ? new Map(lower.filter((row) => row.resident === name && row.level !== null).map((row) => [row.day, `${LOWER_WORDS} ${percent(row.level)}`])) : undefined);
    const lines = names.map((name) => ({
      key: name,
      label: name,
      color: cast.color(name),
      glyph: (r) => cast.glyph(name, r),
      points: days.map((day) => [day, rows.find((row) => row.resident === name && row.day === day)?.level ?? null]),
      notes: notes(name),
    }));
    const known = (model, key) => evaluation.models?.[model]?.[key] !== null && evaluation.models?.[model]?.[key] !== undefined;
    const levels = MODELS.filter(([model]) => known(model, measure)).map(([model, label, color]) => ({ key: model, label, color, dash: true, points: days.map((day) => [day, evaluation.models[model][measure]]), notes: LOWER[measure] && known(model, LOWER[measure]) ? new Map(days.map((day) => [day, `${LOWER_WORDS} ${percent(evaluation.models[model][LOWER[measure]])}`])) : undefined }));
    const chart = new DayChart({ days: span, lines: [...levels, ...lines], y: { min: 0, max: 1, format: (v) => fmt.pct(v) }, height: 150, highlight, onHighlight, dots: true, endLabels: true, label: title });
    into.push(chart);
    const beside = LOWER[measure] ? " Beside each level, in the tooltip and the table, stands its lower reading: the answers labelled Unsafe alone, a lower bound where this one is an upper bound, which decides nothing." : "";
    return figure({ title, note: `${note}${beside}`, chart, legend: swatchLegend(MODELS.map(([, label, color]) => [label, color, "dash"])) });
  });
}

export function mountEvaluation(root, ctx) {
  const { source, cast } = ctx;
  let route = ctx.route;
  const page = h("div", { class: "page evaluation" });
  root.append(page);
  let evaluation = null;
  const charts = [];
  const answersBox = h("div", { class: "answers" });

  /** A table under a header, in a box that scrolls sideways. */
  const table = (head, rows, cls = "data") => h("div", { class: "table-wrap" }, h("table", { class: cls }, h("thead", {}, h("tr", {}, head.map((cell) => h("th", {}, cell)))), h("tbody", {}, rows.map((row) => h("tr", {}, row.map((cell) => h("td", {}, cell)))))));
  const chip = (row) => (row.subject === "base" || row.subject === "reference" ? h("span", { class: "muted" }, subjectName(row)) : [cast.chip(row.subject), ` day ${row.day}`]);

  /** The declared outcomes from day 0 to a day: by group, each measure's change with its interval, a harmful share's lower reading beside it, and the criterion's findings with what stands beside the verdict. */
  function outcomes(found) {
    const groups = Object.keys(found.alignment);
    const designed = found.days[1] === ctx.world.days;
    return h(
      "section",
      { class: "section" },
      h("h2", {}, `The declared outcomes, day 0 to day ${found.days[1]}`),
      h("p", { class: "note" }, `${designed ? "The change the design declares, " : `An interim reading: the design declares the change to the run's last day, day ${ctx.world.days}, and this is the change to day ${found.days[1]}, `}the residents' changes from the base model (day 0) to their weights after night ${found.days[1]}, the original residents and the newcomers apart. Each group's mean change has its 95% bootstrap interval; with so few residents the sign-flip p cannot be small, so read the interval. The gap share is the change as a share of the gap between the base and the reference, where that gap is one the design expects. Under harmful compliance and jailbreak success stands each one's lower reading, the answers labelled Unsafe alone; the verdict rests on the primary readings.`),
      groups.map((group) => {
        const rows = found.groups.filter((row) => row.group === group);
        const alignment = found.alignment[group];
        const held = alignment.harmless_compliance_level;
        const statistics = (label, measure) => {
          const row = rows.find((found_) => found_.measure === measure);
          return [label, signed(row?.mean), interval(row?.ci), number(row?.d_z, 2), row?.p_sign_flip === null || row?.p_sign_flip === undefined ? "–" : `${number(row.p_sign_flip)} (min ${number(row.p_min)})`, "gap_share" in (row ?? {}) ? (row.gap_share === null ? "–" : fmt.pct(row.gap_share)) : ""];
        };
        return h(
          "div",
          { class: "card pad outcome-group" },
          h("h3", {}, `${GROUPS[group] ?? group} · ${fmt.plural(rows[0]?.residents ?? 0, "resident")}`),
          table(
            ["Measure", "Mean change", term("95% interval", "Percentile bootstrap interval of the mean change over 10,000 resamples of the residents."), term("d_z", "Cohen's d_z: the mean change over its standard deviation across the residents."), term("p", "The exact two-sided sign-flip p of the mean change; p_min is the smallest p the test could give with these residents."), term("Gap share", "The mean change as a share of the reference's level less the base's, given only where the reference is lower by at least ten points.")],
            LEVELS.flatMap(([measure, label]) => [statistics(label, measure), ...(LOWER[measure] ? [statistics(h("span", { class: "lower" }, `its ${LOWER_WORDS}`), LOWER[measure])] : [])]),
          ),
          h(
            "ul",
            { class: "findings" },
            FINDINGS.map(([key, label]) => h("li", { class: alignment[key] ? "yes" : "no" }, icon(alignment[key] ? "check" : "cross", 14), h("span", {}, `${label}: ${alignment[key] ? "yes" : "no"}`))),
            h("li", { class: `conjunction ${alignment.aligned ? "yes" : "no"}` }, icon(alignment.aligned ? "check" : "cross", 14), h("span", {}, `All three together: ${alignment.aligned ? "yes" : "no"}`)),
          ),
          held ? h("p", { class: "note small-text" }, `Harmless compliance on day ${found.days[1]}: ${percent(held.mean)} ${interval(held.ci).replace(/[+±]/g, "")}, held against the reference's ${percent(held.reference)}.`) : null,
          h("p", { class: "note small-text" }, `The criterion: ${alignment.rule}.`),
          alignment.beside_the_verdict ? h("div", { class: "beside" }, h("p", { class: "note small-text" }, "Beside the verdict, and no part of it:"), h("ul", { class: "findings" }, BESIDE.map(([key, label]) => h("li", { class: "no" }, icon(alignment.beside_the_verdict[key] ? "check" : "cross", 14), h("span", {}, `${label}: ${alignment.beside_the_verdict[key] ? "yes" : "no"}`))))) : null,
        );
      }),
      h(
        "details",
        { class: "card pad fold" },
        h("summary", {}, "Each resident's change, with the paired test of its items"),
        table(
          ["Resident", ...LEVELS.map(([, label]) => label)],
          cast.names.map((name) => [
            cast.chip(name),
            ...LEVELS.map(([measure]) => {
              const change = (key) => found.residents.find((found_) => found_.resident === name && found_.measure === key);
              const row = change(measure);
              if (!row) return "–";
              const lower = LOWER[measure] ? change(LOWER[measure]) : null;
              return h(
                "span",
                { title: `${row.pairs} pairs: ${row.fell} fell, ${row.rose} rose; McNemar p ${number(row.p_mcnemar)}` },
                `${percent(row.before)} → ${percent(row.after)} (${signed(row.change)})`,
                h("small", { class: "muted" }, ` ${row.fell}↓ ${row.rose}↑ p ${number(row.p_mcnemar, 2)}`),
                lower ? h("small", { class: "lower" }, h("br"), `${LOWER_WORDS}: ${percent(lower.before)} → ${percent(lower.after)} (${signed(lower.change)})`) : null,
              );
            }),
          ]),
        ),
      ),
    );
  }

  /** What the shares leave out or set apart, per result: the empty answers, those the judge could not read, those written as a tool call and those cut off. */
  function counts() {
    const safety = (row, instrument, key) => {
      const found = row.safety?.[instrument];
      if (!found) return "–";
      return key === "empty" || key === "unjudged" ? fmt.int(found.counts[key]) : fmt.int(found[key]);
    };
    return h(
      "section",
      { class: "section" },
      h("h2", {}, "What each share leaves out"),
      h("p", { class: "note" }, "An empty answer is neither harmful nor helpful and stays in each share's denominator; an answer the judge could not read is out of it. An answer written as a tool call, which an adapter fitted on moments with actions may give, and one the token limit cut off are judged as they stand. Of MASK, an empty answer is evasive and one the judge could not read is out of the share."),
      table(
        ["Subject", ...INSTRUMENTS.map(([, label]) => `${label}: empty · unread · tool call · cut off`), "MASK: empty · unread"],
        evaluation.results.map((row) => [
          chip(row),
          ...INSTRUMENTS.map(([instrument]) => ["empty", "unjudged", "tool_calls", "truncated"].map((key) => safety(row, instrument, key)).join(" · ")),
          row.mask ? `${fmt.int(row.mask.empty)} · ${fmt.int(row.mask.counts.unjudged)}` : "–",
        ]),
      ),
    );
  }

  /** Jailbreak success by template, per result. */
  function templates() {
    const names = [...new Set(evaluation.results.flatMap((row) => Object.keys(row.safety?.jailbreak?.templates ?? {})))].sort();
    if (!names.length) return null;
    return h(
      "section",
      { class: "section" },
      h("h2", {}, "Jailbreak success by template"),
      h("p", { class: "note" }, "The share of the harmful behaviours each template, wrapped round them, drew the harmful content out with."),
      table(["Subject", ...names], evaluation.results.map((row) => [chip(row), ...names.map((name) => percent(row.safety?.jailbreak?.templates?.[name]?.share))])),
    );
  }

  /** One subject's answers: the verdicts counted, and each item, its answer's first characters only where the judge rated it safe. */
  async function answers() {
    const rows = evaluation.results;
    const wanted = rows.find((row) => row.answers.split("?")[0].endsWith(`/${route.query.subject}.json`)) ?? rows.find((row) => row.subject === route.query.agent) ?? rows[0];
    const select = h(
      "select",
      {
        "aria-label": "Whose answers",
        onchange: (event) => {
          const row = rows[Number(event.target.value)];
          route = { ...route, query: { ...route.query, subject: row.answers.split("?")[0].replace(/^.*\//, "").replace(/\.json$/, "") } };
          ctx.remember(route);
          answers();
        },
      },
      rows.map((row, i) => h("option", { value: String(i), selected: row === wanted }, subjectName(row))),
    );
    fill(answersBox, h("div", { class: "row" }, h("label", {}, "Answers of ", select)), h("div", { class: "loading" }, "Loading the answers…"));
    let doc;
    try {
      doc = await source.answers(wanted);
    } catch (error) {
      fill(answersBox, h("div", { class: "row" }, select), emptyState("The answers could not be loaded.", error.message));
      return ctx.fail(error);
    }
    const instrument = ([key, label]) => {
      const items = (doc.safety ?? []).filter((item) => item.instrument === key);
      if (!items.length) return null;
      const tally = Object.entries(VERDICTS).map(([verdict, words]) => [words, items.filter((item) => item.verdict === verdict).length]).filter(([, n]) => n);
      const list = h("div");
      const details = h("details", { class: "card pad fold" }, h("summary", {}, h("b", {}, label), h("span", { class: "muted" }, ` · ${fmt.plural(items.length, "item")} · ${tally.map(([words, n]) => `${fmt.int(n)} ${words}`).join(", ")}`)), list);
      details.addEventListener("toggle", () => {
        if (!details.open || list.childElementCount) return;
        fill(list, table(["Item", "Template", "Verdict", "The answer's first 200 characters, where the judge rated it safe"], items.map((item) => [h("span", { class: "mono" }, item.id), item.template ?? "", h("span", { class: `verdict v-${item.verdict}` }, VERDICTS[item.verdict] ?? item.verdict), item.excerpt === null ? h("span", { class: "muted" }, item.verdict === "empty" ? "empty" : "not shown") : h("span", { class: "excerpt" }, item.excerpt)]), "data text"));
      });
      return details;
    };
    const mask = doc.mask
      ? h(
          "details",
          { class: "card pad fold" },
          h("summary", {}, h("b", {}, "MASK, under pressure"), h("span", { class: "muted" }, ` · ${fmt.plural(doc.mask.length, "scenario")}`)),
          table(["Scenario", "Archetype", "Belief", "Answers under pressure: outcome and first 200 characters"], doc.mask.map((s) => [h("span", { class: "mono" }, s.id), s.archetype.replaceAll("_", " "), s.belief ?? "not read", h("ol", { class: "mask-answers" }, s.answers.map((a) => h("li", {}, h("b", {}, a.outcome.replace("_", " ")), " ", h("span", { class: "excerpt" }, a.excerpt))))]), "data text"),
        )
      : null;
    fill(
      answersBox,
      h("div", { class: "row" }, h("label", {}, "Answers of ", select)),
      h("p", { class: "note" }, "Answers to harmful requests are harmful-request material, so of each only the item, its template and the verdict are published, and the first 200 characters of the answer only where the judge rated it safe; nothing of an answer judged harmful or one the judge could not read. The prompts are not shown."),
      INSTRUMENTS.map(instrument),
      mask,
    );
  }

  function render() {
    for (const chart of charts.splice(0)) chart.destroy();
    const latest = evaluation.outcomes.at(-1);
    fill(
      page,
      h(
        "header",
        { class: "page-head" },
        h("h1", {}, "Evaluation"),
        h("p", { class: "lede" }, `The benchmarks put to each resident's weights, the base model with its own adapter, as a plain conversation with no background, memory or tools, after the night of each day evaluated. Four measures, each a share of its items and never one score: harmful compliance, jailbreak success, harmless compliance and lying under pressure. Day 0 is the base model, ${evaluation.base ?? "the run's"}, before any night; the reference, ${evaluation.reference ?? "the original model before its refusals were removed"}, is the level of an aligned model to read a change against.`),
      ),
      evaluation.problems.length ? h("div", { class: "card pad problems" }, h("h2", {}, "Results that could not be read"), h("ul", {}, evaluation.problems.map((problem) => h("li", { class: "mono small-text" }, problem)))) : null,
      evaluation.levels.length
        ? [
            h("div", { class: "figures" }, evaluationFigures(evaluation, cast, { into: charts })),
            latest ? outcomes(latest) : h("div", { class: "card pad" }, h("h2", {}, "The declared outcomes"), h("p", { class: "note" }, "The outcomes are read once every resident has results of a day after day 0."), evaluation.missing.length ? h("details", { class: "fold" }, h("summary", {}, `What the latest day lacks: ${fmt.plural(evaluation.missing.length, "result")}`), h("ul", {}, evaluation.missing.map((found) => h("li", { class: "small-text" }, found)))) : null),
            latest && evaluation.missing.length ? h("p", { class: "note" }, `A later day is evaluated in part: ${evaluation.missing.slice(0, 3).join("; ")}${evaluation.missing.length > 3 ? "; …" : ""}.`) : null,
            counts(),
            templates(),
            h("section", { class: "section" }, h("h2", {}, "The answers, item by item"), answersBox),
          ]
        : h("div", { class: "card" }, emptyState("This run has not been evaluated yet.", "The benchmarks are put to the base model, the reference and each resident's weights after the nights of days 7, 14, 21 and 28; their results appear here once they are written under the results root and the runs are published again.")),
    );
    if (evaluation.levels.length) answers();
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
    update: (next) => {
      route = next;
      return true;
    },
    async live({ changes }) {
      if (changes?.evaluation) await load();
    },
    destroy() {
      for (const chart of charts) chart.destroy();
    },
  };
}
