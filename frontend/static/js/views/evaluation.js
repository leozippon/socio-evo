// Held-out evaluation: trait scores per agent over the evaluated days, and behind every score
// the raw measures, the judge's quoted evidence and the full transcripts.
//
// A trait may be measured by several probe families, and an agent may be evaluated as several
// exports (`variant`: the full agent, or without what it wrote itself). A score shown for a
// trait is the mean of its families' scores for one export; the export shown is the full one
// unless the reader picks another. Fields the viewer does not know are ignored.

import { DayChart, figure } from "../charts.js";
import { formatTime } from "../clock.js";
import { emptyState, fill, fmt, h } from "../dom.js";
import { icon } from "../icons.js";
import { FAMILIES, TRAITS } from "../measures.js";

const traitName = (dimension) => TRAITS.find(({ key }) => key === dimension)?.title ?? dimension.replaceAll("_", " ");
const traitShort = (dimension) => TRAITS.find(({ key }) => key === dimension)?.short ?? dimension.replaceAll("_", " ");

/** The export a row or result is of: `full` unless it says otherwise. */
export const variantOf = (row) => row.variant ?? "full";
/** The export of a result entry, from its label: `day-NNNN` or `day-NNNN-<variant>`. */
const labelVariant = (label) => /^day-\d+-(.+)$/.exec(label)?.[1] ?? "full";

/** The mean of the scores of `rows` that could be scored, or null. */
export function meanScore(rows) {
  const scored = rows.map((row) => row.score).filter((score) => typeof score === "number");
  return scored.length ? scored.reduce((a, b) => a + b, 0) / scored.length : null;
}

/** The traits the rows measure: the four known ones in their order, then any others. */
export function dimensionsOf(scores) {
  const known = TRAITS.map(({ key }) => key);
  return [...known, ...[...new Set(scores.map((row) => row.dimension))].filter((key) => !known.includes(key))];
}

/** One small chart per trait: each agent's score over the evaluated days, on 0 to 1. */
export function traitFigures(evaluation, cast, { highlight = null, only = null, into, variant = "full" }) {
  const scores = evaluation.scores.filter((row) => variantOf(row) === variant);
  const days = [...new Set(scores.map((row) => row.day))].sort((a, b) => a - b);
  const names = only ? [only] : cast.names;
  return dimensionsOf(scores).filter((dimension) => scores.some((row) => row.dimension === dimension) || TRAITS.some(({ key }) => key === dimension)).map((dimension) => {
    const title = traitName(dimension);
    const short = traitShort(dimension);
    const rows = scores.filter((row) => row.dimension === dimension);
    const lines = names.map((name) => ({
      key: name,
      label: name,
      color: cast.color(name),
      glyph: (r) => cast.glyph(name, r),
      points: days.map((day) => [day, meanScore(rows.filter((row) => row.agent === name && row.day === day))]),
    }));
    const chart = new DayChart({ days: [days[0], days.at(-1)], lines, y: { min: 0, max: 1, format: (v) => fmt.num(v, 2) }, height: 110, highlight, dots: true, endLabels: true, label: title });
    into.push(chart);
    return figure({ title: short, note: only ? null : "Mean over repetitions and probe families; gaps are unscored.", chart });
  });
}

function measuresList(measures) {
  return h(
    "dl",
    { class: "measures" },
    Object.entries(measures ?? {}).flatMap(([key, value]) => [
      h("dt", {}, key.replaceAll("_", " ")),
      h(
        "dd",
        {},
        Array.isArray(value)
          ? value.length
            ? h("ul", { class: "quotes" }, value.map((item) => h("li", {}, typeof item === "string" ? h("q", {}, item) : JSON.stringify(item))))
            : h("span", { class: "muted" }, "none")
          : typeof value === "number"
            ? fmt.num(value, Number.isInteger(value) ? 0 : 2)
            : value && typeof value === "object"
              ? h("code", { class: "raw" }, JSON.stringify(value))
              : String(value),
      ),
    ]),
  );
}

function transcript(steps, cast) {
  return h(
    "ol",
    { class: "transcript" },
    (steps ?? []).map((step) => {
      const o = step.observation ?? {};
      return h(
        "li",
        { class: "t-step" },
        h("div", { class: "step-head" }, typeof o.time === "number" ? h("b", {}, formatTime(o.time)) : null, h("span", { class: "muted" }, [o.place, o.scene].filter(Boolean).join(" · "))),
        o.percepts?.length ? h("ul", { class: "percepts" }, o.percepts.map((p) => h("li", {}, typeof p.time === "number" ? h("span", { class: "muted" }, `${formatTime(p.time)} `) : null, cast.mention(p.text)))) : null,
        o.situation ? h("details", { class: "situation" }, h("summary", {}, "What the agent was shown"), h("pre", {}, o.situation), o.allowed ? h("p", { class: "muted" }, `Allowed: ${o.allowed.join(", ")}`) : null) : null,
        step.decision
          ? h(
              "div",
              { class: "decision-pair" },
              h("div", { class: "truth thought" }, h("span", { class: "truth-tag" }, icon("thought", 13), "thought"), h("p", {}, step.decision.thought)),
              h("div", { class: "act" }, h("span", { class: "truth-tag" }, "action"), actionText(step.decision.action)),
            )
          : null,
      );
    }),
  );
}

function actionText(action) {
  if (!action) return h("p", { class: "muted" }, "no action");
  const { kind, ...rest } = action;
  if (kind === "speak") return h("p", {}, h("b", {}, rest.to ? `says${rest.private ? " privately" : ""} to ${rest.to}: ` : "says: "), h("q", {}, rest.text));
  if (kind === "submit_work") return h("div", {}, h("p", {}, h("b", {}, `hands in ${rest.task_id}${rest.part > 1 ? `, part ${rest.part}` : ""}${rest.declaration ? ` as ${rest.declaration === "incomplete" ? "unfinished" : "finished"}` : ""}: `), rest.report), h("details", {}, h("summary", {}, "code"), h("pre", {}, rest.solution)));
  return h("p", {}, h("b", {}, String(kind).replaceAll("_", " ")), Object.keys(rest).length ? ` ${JSON.stringify(rest)}` : "");
}

/**
 * A family's curve as rows, in the order of its levels: each level played, its stake (in the
 * family's unit, as its repetitions give it, or null) and its mean score (null if unscored), and
 * whether behaviour switched there. The curve maps each level to its mean score; in JSON its keys
 * are strings. Empty for a result without a curve, as in format 1.
 */
export function stakeRows(found) {
  const stakes = new Map((found.repetitions ?? []).filter((rep) => typeof rep.level === "number").map((rep) => [rep.level, rep.stake ?? null]));
  return Object.entries(found.curve ?? {})
    .map(([key, score]) => ({ level: Number(key), score }))
    .sort((a, b) => a.level - b.level)
    .map(({ level, score }) => ({ level, stake: stakes.get(level) ?? null, score, switched: found.switch === level }));
}

/** A family's scores by stake, where its result has them: the level, its stake and its mean score. */
function stakeCurve(found) {
  const rows = stakeRows(found);
  if (!rows.length) return null;
  const scored = rows.some((row) => typeof row.score === "number");
  return h(
    "div",
    { class: "table-wrap" },
    h(
      "table",
      { class: "data stakes" },
      h("thead", {}, h("tr", {}, h("th", {}, "Level"), h("th", {}, `Stake${found.unit && found.unit !== "money" ? ` (${found.unit})` : ""}`), h("th", {}, "Mean score"))),
      h(
        "tbody",
        {},
        rows.map((row) => h("tr", { class: row.switched ? "switch" : "" }, h("td", {}, String(row.level)), h("td", {}, row.stake === null ? "–" : found.unit === "money" ? fmt.money(row.stake) : String(row.stake)), h("td", {}, typeof row.score === "number" ? fmt.num(row.score, 2) : "unscored"))),
      ),
    ),
    h("p", { class: "note" }, typeof found.switch === "number" ? `The lowest level whose mean score falls below one half: ${found.switch}.` : scored ? "No level's mean score fell below one half." : "No level could be scored."),
  );
}

export function mountEvaluation(root, ctx) {
  const { source, cast } = ctx;
  let route = ctx.route;
  const page = h("div", { class: "page evaluation" });
  root.append(page);
  let evaluation = null;
  const charts = [];
  const variant = () => route.query.variant ?? "full";

  const pick = (query, reveal = false) => {
    route = { ...route, query: { ...route.query, ...query } };
    ctx.remember(route);
    for (const cell of page.querySelectorAll(".matrix.scores td.selected")) cell.classList.remove("selected");
    page.querySelector(`.matrix.scores [data-cell="${query.agent}|${query.day}|${query.dimension ?? ""}"]`)?.parentElement.classList.add("selected");
    renderDetail().then(() => reveal && detail.getBoundingClientRect().top > window.innerHeight * 0.6 && detail.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" }));
  };

  const detail = h("div", { class: "eval-detail" });

  async function renderDetail() {
    const { agent, day, probe } = route.query;
    if (!agent || day === undefined) {
      fill(detail, h("div", { class: "card" }, emptyState("Pick a score to read what lies behind it.", "Each cell of the table opens the measures, the judge's evidence and every transcript.")));
      return;
    }
    const entry = evaluation.results.find((found) => found.agent === agent && found.day === Number(day) && labelVariant(found.label) === variant());
    if (!entry) return fill(detail, h("div", { class: "card" }, emptyState(`No result for ${agent} on day ${day}${variant() === "full" ? "" : ` as the ${variant()} export`}.`)));
    fill(detail, h("div", { class: "loading" }, `Loading ${agent}'s result for day ${day}…`));
    try {
      const result = await source.result(entry.url);
      const probes = Object.entries(result.probes ?? {});
      if (!probes.length) return fill(detail, h("div", { class: "card" }, emptyState("This result has no probe families.")));
      const wanted = route.query.dimension ? probes.find(([, found]) => found.dimension === route.query.dimension)?.[0] : null;
      const chosen = probe && result.probes[probe] ? probe : wanted ?? probes[0][0];
      const found = result.probes[chosen];
      fill(
        detail,
        h(
          "div",
          { class: "card eval-card" },
          h("header", { class: "spread" }, h("h2", {}, cast.chip(agent), h("span", { class: "muted" }, ` as of day ${day}${variant() === "full" ? "" : `, ${variant()}`}`)), h("span", { class: "mono muted" }, String(result.commit ?? "").slice(0, 10))),
          h(
            "div",
            { class: "seg probe-seg", role: "group", "aria-label": "Probe family" },
            probes.map(([name, family]) => h("button", { type: "button", "aria-pressed": String(name === chosen), title: `${traitName(family.dimension)}: ${name}`, onclick: () => pick({ agent, day, probe: name, dimension: family.dimension }) }, probes.filter(([, other]) => other.dimension === family.dimension).length > 1 ? name.replaceAll("_", " ") : traitShort(family.dimension), h("span", { class: "muted" }, typeof family.score === "number" ? fmt.num(family.score, 2) : "–"))),
          ),
          h(
            "div",
            { class: "probe" },
            h("p", { class: "note" }, FAMILIES[chosen] ?? `${traitName(found.dimension)} · probe ${chosen.replaceAll("_", " ")}.`),
            stakeCurve(found),
            h("h3", {}, "Mean measures"),
            measuresList(found.measures),
            (found.repetitions ?? []).map((rep, i) =>
              h(
                "details",
                { class: "repetition", open: i === 0 },
                h("summary", {}, h("b", {}, `Repetition ${i + 1}`), rep.level !== undefined ? ` · level ${rep.level}${rep.stake !== undefined ? ` (stake ${rep.stake})` : ""}` : "", ` · score ${typeof rep.score === "number" ? fmt.num(rep.score, 2) : "unscored"}`, rep.outcome !== undefined ? h("span", { class: "muted" }, ` · ${typeof rep.outcome === "string" ? rep.outcome : JSON.stringify(rep.outcome)}`) : null),
                measuresList(rep.measures),
                transcript(rep.transcript, cast),
              ),
            ),
          ),
        ),
      );
    } catch (error) {
      fill(detail, h("div", { class: "card" }, emptyState("This result could not be loaded.", error.message)));
    }
  }

  function scoreTable(scores) {
    const days = [...new Set(scores.map((row) => row.day))].sort((a, b) => a - b);
    const dimensions = dimensionsOf(scores).filter((dimension) => scores.some((row) => row.dimension === dimension));
    const level = (score) => (score === null ? "none" : `heat-${1 + Math.min(4, Math.floor(score * 5))}`);
    return h(
      "div",
      { class: "table-wrap" },
      h(
        "table",
        { class: "matrix scores" },
        h("thead", {}, h("tr", {}, h("th", { class: "sticky-col" }, "Agent"), h("th", {}, "Day"), dimensions.map((dimension) => h("th", { scope: "col", title: traitName(dimension) }, h("span", { class: "long" }, traitName(dimension)), h("span", { class: "short" }, traitShort(dimension)))))),
        h(
          "tbody",
          {},
          cast.names.flatMap((agent) =>
            days.map((day, i) =>
              h(
                "tr",
                { class: i === 0 ? "first" : "" },
                i === 0 ? h("th", { scope: "row", rowspan: days.length, class: "sticky-col" }, cast.chip(agent)) : null,
                h("td", { class: "day" }, String(day)),
                dimensions.map((dimension) => {
                  const rows = scores.filter((row) => row.agent === agent && row.day === day && row.dimension === dimension);
                  if (!rows.length) return h("td", { class: "none" }, "");
                  const score = meanScore(rows);
                  const selected = route.query.agent === agent && Number(route.query.day) === day && (route.query.dimension ? route.query.dimension === dimension : rows.some((row) => row.probe === route.query.probe));
                  const families = rows.length > 1 ? ` over ${rows.length} probe families` : "";
                  return h(
                    "td",
                    { class: `${level(score)}${selected ? " selected" : ""}` },
                    h("button", { type: "button", class: "cell", "data-cell": `${agent}|${day}|${dimension}`, onclick: () => pick({ agent, day: String(day), dimension, probe: rows[0].probe }, true), title: `${agent}, day ${day}, ${traitName(dimension)}: ${score === null ? "unscored" : fmt.num(score, 2)}${families}` }, score === null ? "–" : fmt.num(score, 2)),
                  );
                }),
              ),
            ),
          ),
        ),
      ),
    );
  }

  function render() {
    const usage = evaluation.usage ?? [];
    for (const chart of charts.splice(0)) chart.destroy();
    const variants = [...new Set(evaluation.scores.map(variantOf))].sort((a, b) => (a === "full" ? -1 : b === "full" ? 1 : a.localeCompare(b)));
    const scores = evaluation.scores.filter((row) => variantOf(row) === variant());
    fill(
      page,
      h("header", { class: "page-head" }, h("h1", {}, "Held-out evaluation"), h("p", { class: "lede" }, "Short scenes of ordinary town life played offline on exported versions of each agent, which never reach its history. Day 0 is the agent as created.")),
      evaluation.scores.length
        ? [
            variants.length > 1
              ? h(
                  "div",
                  { class: "spread section-note" },
                  h("p", { class: "note" }, "Exports without what the agent wrote itself show whether a trait lives in its own conclusions or only in what it remembers."),
                  h("div", { class: "seg", role: "group", "aria-label": "Export" }, variants.map((name) => h("button", { type: "button", "aria-pressed": String(name === variant()), onclick: () => ((route = { ...route, query: { ...route.query, variant: name === "full" ? null : name } }), ctx.remember(route), render()) }, name === "full" ? "Full agent" : name.replaceAll("-", " ")))),
                )
              : null,
            scores.length
              ? [
                  h("div", { class: "figures four" }, traitFigures(evaluation, cast, { into: charts, variant: variant() })),
                  h("section", { class: "section" }, h("div", { class: "section-head" }, h("h2", {}, "Scores"), h("p", { class: "note" }, "Mean over repetitions and probe families; pick one for its measures and transcripts.")), h("div", { class: "card score-card" }, scoreTable(scores))),
                  h("section", { class: "section" }, detail),
                ]
              : h("div", { class: "card" }, emptyState(`No scores for the ${variant()} export.`)),
            usage.length ? h("p", { class: "note section" }, `Evaluation model calls: ${usage.map((u) => `${fmt.int(u.calls)} for ${u.purpose === "judge" ? "the judge" : "the agents"} (${fmt.compact(u.prompt_tokens + u.completion_tokens)} tokens)`).join(", ")}.`) : null,
          ]
        : h(
            "div",
            { class: "card" },
            emptyState("This run has not been evaluated yet.", "Evaluate chosen days with ", h("code", {}, `python -m experiments.evaluate runs/${route.experiment}/${route.run} --days 0 7 14`), "; the results appear here when the runs are published again."),
          ),
    );
    if (scores.length) renderDetail();
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
    update(next) {
      route = next;
      if (evaluation) render();
      return true;
    },
    async live({ changes }) {
      if (changes?.evaluation) {
        evaluation = await source.evaluation();
        render();
      }
    },
    destroy() {
      for (const chart of charts) chart.destroy();
    },
  };
}
