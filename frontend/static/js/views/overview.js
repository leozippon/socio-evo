// A run's dashboard, from the published measures. What matters first leads: the run itself, a
// few key figures and the conditions it ran under. Everything else is one tap away, in
// sections: money, the task market, social life, evolution, the held-out traits, model usage.

import { DayChart, Multiples, agentLegend, figure, swatchLegend } from "../charts.js";
import { emptyState, fill, fmt, h, s } from "../dom.js";
import { icon } from "../icons.js";
import { href, sibling } from "../router.js";
import { conditionLabel, conditionValue, interventions, markers } from "../world.js";
import { progress } from "./landing.js";
import { traitFigures } from "./evaluation.js";

export const PURPOSES = [
  ["act", "decisions"],
  ["diary", "diary"],
  ["reflect", "reflection (L0)"],
  ["skills", "skills (L1)"],
  ["policy", "policy (L2)"],
];
export const LEVELS = { L0: "memory", L1: "skills", L2: "policy" };

const SECTIONS = [
  ["money", "Money"],
  ["work", "Work"],
  ["social", "Social life"],
  ["evolution", "Evolution"],
  ["traits", "Traits"],
  ["usage", "Model usage"],
];
/** Sections whose charts draw one line per agent, so the emphasis legend applies. */
const BY_AGENT = new Set(["money", "social", "traits"]);

export const stat = (label, value, sub = null, cls = "") => h("div", { class: `stat ${cls}` }, h("div", { class: "stat-label" }, label), h("div", { class: "stat-value" }, value), sub ? h("div", { class: "stat-sub" }, sub) : null);
const sum = (rows, field) => rows.reduce((total, row) => total + row[field], 0);
const series = (rows, field) => rows.map((row) => [row.day, row[field]]);
const valuesOf = (rows, field) => new Map(rows.map((row) => [row.day, row[field]]));

export function mountOverview(root, ctx) {
  const { source, world, cast } = ctx;
  let route = ctx.route;
  const page = h("div", { class: "page overview" });
  root.append(page);
  const view = { highlight: null, pinned: null, multiples: false, matrix: "rating" };
  let measures = null;
  let evaluation = null;
  let agentFigures = [];
  let charts = [];

  const section = () => (SECTIONS.some(([key]) => key === route.query.section) ? route.query.section : "money");
  const emphasis = () => view.highlight ?? view.pinned;
  function pick(name, pin) {
    if (pin) view.pinned = name;
    else view.highlight = name;
    for (const entry of agentFigures) entry.refresh();
    for (const legend of page.querySelectorAll(".agent-legend .legend-item")) {
      const on = legend.dataset.agent === view.pinned;
      legend.classList.toggle("on", on);
      legend.setAttribute("aria-pressed", String(on));
    }
  }

  /** A figure with one line per agent that follows the shared emphasis and layout. */
  function agentFigure({ title, note, field, format, zero = false, min = null, max = null, wide = true }) {
    const lines = cast.names.map((name) => ({
      key: name,
      label: name,
      color: cast.color(name),
      glyph: (r) => cast.glyph(name, r),
      points: measures.agents.filter((row) => row.agent === name).map((row) => [row.day, row[field]]),
    }));
    const spec = { days: [1, lastDay()], lines, y: { format, zero, min, max, integer: format === fmt.int }, markers: markers(world), endLabels: true, height: 200, label: title };
    const holder = h("div");
    let chart = null;
    const entry = {
      refresh() {
        if (!view.multiples) chart.update({ highlight: emphasis() });
      },
      build() {
        chart?.destroy();
        chart = view.multiples ? new Multiples(spec) : new DayChart({ ...spec, highlight: emphasis(), onHighlight: pick });
        holder.replaceChildren(chart.el);
      },
      table: () => chart.table(),
      destroy: () => chart.destroy(),
    };
    entry.build();
    agentFigures.push(entry);
    const layout = h(
      "div",
      { class: "seg", role: "group", "aria-label": "Layout" },
      h("button", { type: "button", "aria-pressed": String(!view.multiples), title: "All agents on one chart", onclick: () => setMultiples(false) }, icon("lines", 14), "Together"),
      h("button", { type: "button", "aria-pressed": String(view.multiples), title: "One small chart per agent", onclick: () => setMultiples(true) }, icon("grid", 14), "Apart"),
    );
    return figure({ title, note, chart: { el: holder, table: () => entry.table() }, tools: [layout], wide });
  }

  function setMultiples(on) {
    view.multiples = on;
    renderSection();
  }

  const lastDay = () => Math.max(1, measures.society.at(-1)?.day ?? 1);

  /** A chart of society-wide numbers. */
  function dayFigure({ title, note, lines = [], stacks = [], format = fmt.int, zero = true, min = null, max = null, legend = null, wide = false }) {
    const chart = new DayChart({ days: [1, lastDay()], lines, stacks, y: { format, zero, min, max, integer: format === fmt.int }, markers: markers(world), height: 160, label: title });
    charts.push(chart);
    return figure({ title, note, chart, legend, wide });
  }

  function head() {
    const entry = ctx.index.runs.find((run) => run.experiment === route.experiment && run.run === route.run) ?? source.entry;
    const doc = source.doc;
    return h(
      "header",
      { class: "run-head" },
      h(
        "div",
        { class: "run-title" },
        h("p", { class: "eyebrow" }, "Run"),
        h("h1", {}, doc.experiment, h("span", { class: "run-seed" }, doc.run)),
        h("p", { class: "run-meta" }, `${fmt.plural(world.agents.length, "agent")} · ${world.model.name}${entry.dry_run ? " (dry run: a stand-in answered)" : ""} · seed ${doc.seed}`),
        h(
          "p",
          { class: "run-meta quiet-meta" },
          `started ${fmt.wall(doc.started_at)}${doc.ended_at ? `, stopped ${fmt.wall(doc.ended_at)}` : ""} · ${fmt.int(doc.events)} events · code `,
          h("span", { class: "mono", title: doc.code_revision.endsWith("-dirty") ? "The code had uncommitted changes" : "The code revision" }, doc.code_revision.slice(0, 10)),
        ),
      ),
      h("div", { class: "run-side" }, progress(entry), h("a", { class: "btn", href: href(sibling(route, "town")) }, icon("map", 16), "Watch the town")),
    );
  }

  function conditions() {
    const last = source.doc.last_day;
    return h(
      "section",
      { class: "conditions", "aria-label": "Conditions" },
      h("div", { class: "cond-start" }, h("p", { class: "eyebrow" }, "Conditions"), h("ul", { class: "cond-list" }, Object.entries(world.conditions).map(([key, value]) => h("li", {}, h("span", { class: "muted" }, conditionLabel(key)), " ", h("b", {}, conditionValue(key, value)))))),
      world.interventions.length
        ? h(
            "div",
            { class: "cond-changes" },
            h("p", { class: "eyebrow" }, "Interventions"),
            h(
              "ol",
              { class: "interventions" },
              interventions(world).map((found) =>
                h(
                  "li",
                  { class: found.day > last ? "planned" : "" },
                  h("span", { class: `flag${found.announced ? " announced" : ""}`, title: found.announced ? "Announced to everyone" : "Not announced" }, icon("flag", 14)),
                  h("b", { class: "iv-day" }, `Day ${found.day}`),
                  h("span", { class: "iv-what" }, found.changes.length ? found.changes.map((c) => `${c.label} ${c.from} → ${c.to}`).join("; ") : "an announcement", found.announced ? null : h("span", { class: "muted" }, " · not announced")),
                  found.announced ? h("q", { class: "iv-quote" }, found.announcement) : null,
                  found.day > last ? h("span", { class: "pill" }, "planned") : null,
                ),
              ),
            ),
          )
        : null,
    );
  }

  function keyFigures() {
    const rows = measures.society;
    const last = rows.at(-1);
    const delivered = sum(rows, "delivered");
    const esteem = rows.findLast((row) => row.esteem_mean !== null)?.esteem_mean ?? null;
    return h(
      "div",
      { class: "stats" },
      stat("Mean balance", fmt.credits(Math.round(last.balance_mean)), `${fmt.credits(last.balance_min)} to ${fmt.credits(last.balance_max)}, day ${last.day}`),
      stat("Earnings Gini", fmt.num(last.earnings_gini, 2), "0 is equal earnings"),
      stat("Mean esteem", fmt.num(esteem, 2), "of 5, as last published"),
      stat("Accepted deliveries", fmt.int(delivered), delivered ? `true quality ${fmt.num(sum(rows, "quality") / delivered, 2)}` : null),
      stat("Defects found", fmt.int(sum(rows, "defects_discovered")), `of ${fmt.int(sum(rows, "defective"))} latent · ${fmt.credits(sum(rows, "clawed_back"))} back`),
    );
  }

  function evolutionGrid() {
    const days = lastDay();
    const rows = new Map(measures.agents.map((row) => [`${row.agent}/${row.day}`, row]));
    const mark = (level, trigger) => {
      const shape = { L0: s("circle", { r: 2.2 }), L1: s("rect", { x: -3.4, y: -3.4, width: 6.8, height: 6.8, rx: 1 }), L2: s("path", { d: "M0,-4.6L4.6,0L0,4.6L-4.6,0Z" }) }[level] ?? s("circle", { r: 3 });
      return s("svg", { class: `step ${level} ${trigger === "self" ? "self" : "scheduled"}`, width: 12, height: 12, viewBox: "-6 -6 12 12", "aria-hidden": "true" }, shape);
    };
    const header = h("tr", {}, h("th", { class: "sticky-col" }, ""), Array.from({ length: days }, (_, i) => h("th", { scope: "col" }, String(i + 1))));
    const body = cast.names.map((name) =>
      h(
        "tr",
        {},
        h("th", { scope: "row", class: "sticky-col" }, cast.chip(name, href(sibling(route, "person", { agent: name, query: { tab: "history" } })))),
        Array.from({ length: days }, (_, i) => {
          const row = rows.get(`${name}/${i + 1}`);
          const steps = Object.entries(row?.evolution ?? {}).flatMap(([key, count]) => Array(count).fill(key.split("/")));
          steps.sort((a, b) => a[0].localeCompare(b[0]));
          const title = steps.length ? `${name}, night of day ${i + 1}: ${steps.map(([level, trigger]) => `${level} ${LEVELS[level] ?? ""} (${trigger})`).join(", ")}` : `${name}, day ${i + 1}: no step`;
          const notable = steps.some(([level, trigger]) => level !== "L0" || trigger !== "daily");
          return h(
            "td",
            { title, class: notable ? "notable" : "" },
            notable ? h("a", { href: href(sibling(route, "person", { agent: name, query: { tab: "history", t: `${i + 1}-22:00` } })), "aria-label": title }, steps.map(([l, t]) => mark(l, t))) : steps.map(([l, t]) => mark(l, t)),
          );
        }),
      ),
    );
    const key = h(
      "div",
      { class: "legend static" },
      ["L0", "L1", "L2"].map((level) => h("span", { class: "legend-item" }, mark(level, "scheduled"), `${level} ${LEVELS[level]}`)),
      h("span", { class: "legend-item" }, mark("L2", "self"), "filled: asked for by the agent"),
    );
    return h(
      "figure",
      { class: "figure wide" },
      h("figcaption", {}, h("h3", {}, "Evolution steps, night by night"), h("p", { class: "note" }, "Every rewrite an agent made of its memory, skills and policy. A marked night opens the step in the agent's history."), key),
      h("div", { class: "table-wrap" }, h("table", { class: "evo-grid" }, h("thead", {}, header), h("tbody", {}, body))),
    );
  }

  function matrix() {
    const options = {
      rating: ["Mean rating", (e) => (e.ratings ? e.ratings_sum / e.ratings : null), (v) => fmt.num(v, 1), [1, 5]],
      ratings: ["Ratings", (e) => e.ratings || null, fmt.int, null],
      minutes: ["Hours together", (e) => (e.minutes ? e.minutes / 60 : null), (v) => fmt.num(v, 1), null],
      addressed: ["Addressed", (e) => e.addressed || null, fmt.int, null],
    };
    const [, value, format, fixed] = options[view.matrix];
    const totals = new Map();
    for (const edge of measures.graph) {
      const key = `${edge.source}>${edge.target}`;
      const t = totals.get(key) ?? { minutes: 0, scenes: 0, addressed: 0, heard: 0, ratings: 0, ratings_sum: 0 };
      for (const field of Object.keys(t)) t[field] += edge[field];
      totals.set(key, t);
    }
    const values = [...totals.values()].map(value).filter((v) => v !== null);
    const [lo, hi] = fixed ?? [Math.min(...values, 0), Math.max(...values, 1)];
    const level = (v) => Math.max(1, Math.min(5, 1 + Math.floor(((v - lo) / (hi - lo || 1)) * 4.999)));
    const table = h(
      "table",
      { class: "matrix" },
      h("thead", {}, h("tr", {}, h("th", { class: "corner sticky-col" }, "from ↓ to →"), cast.names.map((name) => h("th", { scope: "col", title: name }, cast.badge(name, 16))))),
      h(
        "tbody",
        {},
        cast.names.map((from) =>
          h(
            "tr",
            {},
            h("th", { scope: "row", class: "sticky-col" }, cast.chip(from)),
            cast.names.map((to) => {
              if (from === to) return h("td", { class: "self" }, "");
              const edge = totals.get(`${from}>${to}`);
              const v = edge ? value(edge) : null;
              const detail = edge ? `${from} → ${to}: ${fmt.num(edge.minutes / 60, 1)} h together, ${edge.addressed} addressed by name, ${edge.ratings} ratings${edge.ratings ? ` averaging ${fmt.num(edge.ratings_sum / edge.ratings, 2)}` : ""}` : `${from} and ${to} never shared a scene`;
              return h("td", { class: v === null ? "none" : `heat-${level(v)}`, title: detail }, v === null ? "" : format(v));
            }),
          ),
        ),
      ),
    );
    const seg = h(
      "div",
      { class: "seg", role: "group", "aria-label": "Measure" },
      Object.entries(options).map(([key, [label]]) =>
        h(
          "button",
          {
            type: "button",
            "aria-pressed": String(view.matrix === key),
            onclick: () => {
              view.matrix = key;
              renderSection();
            },
          },
          label,
        ),
      ),
    );
    return h(
      "figure",
      { class: "figure wide" },
      h("figcaption", {}, h("div", { class: "figure-head" }, h("h3", {}, "Who to whom, over the run so far"), seg), h("p", { class: "note" }, "Rows act on columns. Ratings are private: no agent ever sees who rated whom. Darker cells hold more.")),
      h("div", { class: "table-wrap" }, table),
    );
  }

  const SECTION_CONTENT = {
    money() {
      const rows = measures.society;
      return [
        h("p", { class: "note section-note" }, "Everyone starts equal and pays the same living cost, so the spread of balances is the spread of what they earned and lost."),
        h(
          "div",
          { class: "figures" },
          agentFigure({ title: "Balance", note: "Credits at the end of each day; balances may go negative.", field: "balance", format: fmt.int, zero: true }),
          dayFigure({ title: "Inequality of earnings", note: "Gini coefficient of cumulative payments minus clawbacks; 0 is equality.", lines: [{ key: "gini", label: "Gini", color: "var(--ink-2)", points: series(rows, "earnings_gini") }], format: (v) => fmt.num(v, 2), min: 0 }),
          dayFigure({
            title: "Credits paid and charged",
            note: "Paid for accepted work, against living costs charged, per day.",
            stacks: [{ key: "income", label: "paid for work", color: "var(--o2)", values: valuesOf(rows, "income") }],
            lines: [{ key: "living", label: "living costs", color: "var(--ink)", points: series(rows, "living_cost") }],
            legend: swatchLegend([["paid for work", "var(--o2)"], ["living costs", "var(--ink)", "line"]]),
          }),
        ),
      ];
    },
    work() {
      const rows = measures.society;
      return [
        h("p", { class: "note section-note" }, `Work is scarce by design: more people want tasks than the board offers, and a draw decides contested claims. ${fmt.int(sum(rows, "claims_refused"))} of ${fmt.int(sum(rows, "claim_attempts"))} claims were refused; ${fmt.plural(sum(rows, "contested"), "draw")} decided.`),
        h(
          "div",
          { class: "figures" },
          dayFigure({
            title: "Demand for work",
            note: "Claims taken and refused, against tasks posted.",
            stacks: [
              { key: "claimed", label: "claims taken", color: "var(--o3)", values: valuesOf(rows, "claimed") },
              { key: "refused", label: "claims refused", color: "var(--o1)", values: valuesOf(rows, "claims_refused") },
            ],
            lines: [{ key: "posted", label: "tasks posted", color: "var(--ink)", points: series(rows, "tasks_posted") }],
            legend: swatchLegend([["claims taken", "var(--o3)"], ["refused", "var(--o1)"], ["tasks posted", "var(--ink)", "line"]]),
          }),
          dayFigure({
            title: "What became of the work",
            note: "Deliveries accepted, attempts the checks refused, and claims that lapsed.",
            stacks: [
              { key: "delivered", label: "accepted", color: "var(--good)", values: valuesOf(rows, "delivered") },
              { key: "failed", label: "refused by checks", color: "var(--serious)", values: valuesOf(rows, "failed") },
              { key: "expired", label: "lapsed", color: "var(--critical)", values: valuesOf(rows, "expired") },
            ],
            legend: swatchLegend([["accepted", "var(--good)"], ["refused by checks", "var(--serious)"], ["lapsed", "var(--critical)"]]),
          }),
          dayFigure({ title: "True quality of accepted work", note: "Mean share of hidden checks passed; nobody in town sees it.", lines: [{ key: "quality", label: "mean true quality", color: "var(--ink-2)", points: series(rows, "quality_mean") }], format: (v) => fmt.num(v, 2), min: 0, max: 1 }),
          dayFigure({
            title: "Latent defects",
            note: "Accepted deliveries that carry a defect, and defects that came to light.",
            stacks: [{ key: "defective", label: "defective deliveries", color: "var(--o2)", values: valuesOf(rows, "defective") }],
            lines: [{ key: "found", label: "defects found", color: "var(--critical)", points: series(rows, "defects_discovered") }],
            legend: swatchLegend([["defective deliveries", "var(--o2)"], ["found", "var(--critical)", "line"]]),
          }),
        ),
      ];
    },
    social() {
      const rows = measures.society;
      return [
        h("p", { class: "note section-note" }, `Esteem is the mean of the ratings an agent received, recent ones counting more; it is published to everyone each night. ${fmt.plural(sum(rows, "utterances"), "thing")} said in ${fmt.plural(sum(rows, "conversations"), "conversation")} and ${fmt.plural(sum(rows, "work_sessions"), "work session")}.`),
        h(
          "div",
          { class: "figures" },
          agentFigure({ title: "Esteem", note: "As published at the end of each day, from 1 to 5.", field: "esteem", format: (v) => fmt.num(v, 2), zero: false, max: 5 }),
          dayFigure({
            title: "Talk and gatherings",
            note: "The scenes held each day, and the things said in them.",
            stacks: [
              { key: "work", label: "work sessions", color: "var(--o1)", values: valuesOf(rows, "work_sessions") },
              { key: "conv", label: "conversations", color: "var(--o3)", values: valuesOf(rows, "conversations") },
            ],
            lines: [{ key: "utterances", label: "things said", color: "var(--ink)", points: series(rows, "utterances") }],
            legend: swatchLegend([["work sessions", "var(--o1)"], ["conversations", "var(--o3)"], ["things said", "var(--ink)", "line"]]),
          }),
          dayFigure({
            title: "Peer ratings",
            note: "Mean score of the ratings given each evening, from 1 to 5.",
            lines: [{ key: "mean", label: "mean rating", color: "var(--ink-2)", points: rows.map((row) => [row.day, row.ratings ? row.ratings_sum / row.ratings : null]) }],
            format: (v) => fmt.num(v, 2),
            zero: false,
            min: 1,
            max: 5,
          }),
          matrix(),
        ),
      ];
    },
    evolution() {
      const rows = measures.society;
      const steps = rows.reduce((total, row) => total + Object.values(row.evolution).reduce((a, b) => a + b, 0), 0);
      const asked = rows.reduce((total, row) => total + Object.entries(row.evolution).filter(([k]) => k.endsWith("/self")).reduce((a, [, b]) => a + b, 0), 0);
      const trigger = world.evolution.self_trigger;
      return [
        h("p", { class: "note section-note" }, `${fmt.plural(steps, "step")} so far, ${fmt.int(asked)} asked for by the agent. Enabled levels: ${world.evolution.levels.join(", ") || "none (the no-evolution baseline)"}. Agents may ask for ${trigger.enabled ? trigger.levels.join(" or ") : "nothing"} themselves, then wait ${trigger.cooldown_days} days.`),
        h("div", { class: "figures" }, evolutionGrid()),
      ];
    },
    traits() {
      return evaluation.scores.length
        ? [
            h("div", { class: "spread section-note" }, h("p", { class: "note" }, "Probes played offline on frozen copies of the agents; higher means more of the trait."), h("a", { class: "quiet small", href: href(sibling(route, "evaluation")) }, "Measures and transcripts", icon("chevron", 14))),
            h("div", { class: "figures four" }, traitFigures(evaluation, cast, { highlight: emphasis(), into: charts })),
          ]
        : h("div", { class: "card" }, emptyState("This run has not been evaluated yet.", "Evaluate chosen days with ", h("code", {}, `python -m experiments.evaluate runs/${route.experiment}/${route.run} --days 0 7 14`), "."));
    },
    usage() {
      const usage = measures.usage;
      const purposeColor = (i) => `var(--o${i + 1})`;
      const usageBy = (purpose, get) => {
        const out = new Map();
        for (const row of usage) if (row.purpose === purpose) out.set(row.day, (out.get(row.day) ?? 0) + get(row));
        return out;
      };
      const latency = new Map();
      for (const row of usage) {
        const t = latency.get(row.day) ?? [0, 0];
        latency.set(row.day, [t[0] + row.latency, t[1] + row.calls - row.failed]);
      }
      return [
        h("p", { class: "note section-note" }, `${fmt.int(sum(usage, "calls"))} calls to ${world.model.name}, ${fmt.compact(sum(usage, "prompt_tokens") + sum(usage, "completion_tokens"))} tokens, ${fmt.int(sum(usage, "failed"))} failed. Calls discarded by a resume stay counted.`),
        h(
          "div",
          { class: "figures" },
          dayFigure({
            title: "Tokens per day",
            note: "Prompt and completion tokens, by purpose.",
            stacks: PURPOSES.map(([key, label], i) => ({ key, label, color: purposeColor(i), values: usageBy(key, (row) => row.prompt_tokens + row.completion_tokens) })),
            format: fmt.compact,
            legend: swatchLegend(PURPOSES.map(([, label], i) => [label, purposeColor(i)])),
          }),
          dayFigure({
            title: "Seconds per call",
            note: "Mean latency of answered calls.",
            lines: [{ key: "latency", label: "seconds per call", color: "var(--ink-2)", points: [...latency].map(([day, [total, n]]) => [day, n ? total / n : null]) }],
            format: (v) => fmt.num(v, 1),
          }),
        ),
      ];
    },
  };

  const legendHolder = h("div", { class: "agent-legend", "aria-label": "Emphasise an agent" });
  const sectionBody = h("div", { class: "section-body" });

  function renderSection() {
    for (const chart of [...charts, ...agentFigures]) chart.destroy();
    charts = [];
    agentFigures = [];
    const key = section();
    legendHolder.hidden = !BY_AGENT.has(key);
    fill(legendHolder, h("span", { class: "muted legend-lead" }, "Emphasise"), agentLegend(cast, cast.names, { selected: view.pinned, onPick: pick }));
    fill(sectionBody, SECTION_CONTENT[key]());
    for (const tab of page.querySelectorAll(".run-sections [data-section]")) tab.setAttribute("aria-selected", String(tab.dataset.section === key));
  }

  function render() {
    if (!measures.society.length) {
      fill(page, head(), conditions(), h("section", { class: "card section" }, emptyState("No day has begun yet.", "The dashboard fills in as the run records its first day.")));
      return;
    }
    const partial = source.doc.settled_day < source.doc.last_day;
    const tabs = h(
      "nav",
      { class: "subnav run-sections", "aria-label": "Sections" },
      SECTIONS.map(([key, label]) =>
        h(
          "button",
          {
            type: "button",
            "data-section": key,
            "aria-selected": String(section() === key),
            onclick: () => {
              route = { ...route, query: { ...route.query, section: key === "money" ? null : key } };
              ctx.remember(route);
              renderSection();
            },
          },
          label,
        ),
      ),
    );
    fill(page, head(), keyFigures(), partial ? h("p", { class: "note partial-note" }, `Day ${source.doc.last_day} is still in progress: its numbers count only what has happened so far.`) : null, conditions(), h("div", { class: "section-bar" }, tabs, legendHolder), sectionBody);
    renderSection();
  }

  async function load() {
    page.replaceChildren(h("div", { class: "loading" }, "Loading the run's measures…"));
    try {
      [measures, evaluation] = await Promise.all([source.measures(), source.evaluation()]);
      render();
    } catch (error) {
      page.replaceChildren(h("div", { class: "card" }, emptyState("The run's measures could not be loaded.", error.message)));
      ctx.fail(error);
    }
  }

  load();
  return {
    update(next) {
      const before = section();
      route = next;
      if (measures && section() !== before) renderSection();
      return true;
    },
    async live({ changes }) {
      if (!changes) return;
      if (changes.measures || changes.evaluation || changes.status) {
        [measures, evaluation] = await Promise.all([source.measures(), source.evaluation()]);
        const y = window.scrollY;
        render();
        window.scrollTo(0, y);
      }
    },
    destroy() {
      for (const chart of [...charts, ...agentFigures]) chart.destroy();
    },
  };
}
