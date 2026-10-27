// A run's dashboard, from the published measures and progress. What matters first leads: the
// run itself, a few key figures and the rules it ran under. Everything else is one tap away, in
// sections: work, money, the body, social life, evolution (what residents rewrote each night),
// the evaluation of their exports, and model usage.

import { DayChart, Multiples, agentLegend, figure, swatchLegend } from "../charts.js";
import { duration, parseHHMM } from "../clock.js";
import { emptyState, fill, fmt, h, s } from "../dom.js";
import { icon } from "../icons.js";
import { href, sibling } from "../router.js";
import { groupLabel } from "../world.js";
import { evaluationFigures } from "./evaluation.js";
import { groupPill, progress, progressTable, reached } from "./landing.js";

const SECTIONS = [
  ["work", "Work"],
  ["money", "Money"],
  ["body", "Body"],
  ["social", "Social life"],
  ["evolution", "Evolution"],
  ["evaluation", "Evaluation"],
  ["usage", "Model usage"],
];
/** Sections whose charts draw one mark per resident, so the emphasis legend applies. */
const BY_RESIDENT = new Set(["work", "money", "body", "social", "usage", "evaluation"]);
const AREAS = { memory: ["memory", /^memory\/(?!journal\/)/], skills: ["skills", /^skills\//], journal: ["journal", /^memory\/journal\//], background: ["background", /^background\.md$/] };

export const stat = (label, value, sub = null, cls = "") => h("div", { class: `stat ${cls}` }, h("div", { class: "stat-label" }, label), h("div", { class: "stat-value" }, value), sub ? h("div", { class: "stat-sub" }, sub) : null);
const sum = (rows, field) => rows.reduce((total, row) => total + (row[field] ?? 0), 0);

/** The daily rows of one measure, as `[day, total]` or `[day, mean]` points. */
const dailyPoints = (daily, measure, what) => daily.filter((row) => row.measure === measure).map((row) => [row.day, row[what]]);
const dailyValues = (daily, measure, what) => new Map(dailyPoints(daily, measure, what));

/** Which area of its files a version changed, by the paths of its changes. */
export function areasOf(version) {
  const found = new Set();
  for (const change of version.changes) for (const [area, [, pattern]] of Object.entries(AREAS)) if (pattern.test(change.path)) found.add(area);
  return found;
}

export function mountOverview(root, ctx) {
  const { source, world, cast } = ctx;
  let route = ctx.route;
  const page = h("div", { class: "page overview" });
  root.append(page);
  const view = { highlight: null, pinned: null, multiples: false, matrix: "said" };
  let measures = null;
  let evaluation = null;
  let progressDoc = null;
  let histories = null;
  let agentFigures = [];
  let charts = [];

  const section = () => (SECTIONS.some(([key]) => key === route.query.section) ? route.query.section : "work");
  const running = () => source.doc.status === "running";
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

  const lastDay = () => Math.max(1, ...measures.rows.map((row) => row.day));

  /** A figure with one line per resident that follows the shared emphasis and layout. */
  function agentFigure({ title, note, points, format = fmt.int, zero = false, min = null, max = null, wide = true }) {
    const lines = cast.names.map((name) => ({ key: name, label: name, color: cast.color(name), glyph: (r) => cast.glyph(name, r), points: points(name) }));
    const spec = { days: [1, lastDay()], lines, y: { format, zero, min, max, integer: format === fmt.int }, endLabels: true, height: 200, label: title };
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
      h("button", { type: "button", "aria-pressed": String(!view.multiples), title: "All residents on one chart", onclick: () => setMultiples(false) }, icon("lines", 14), "Together"),
      h("button", { type: "button", "aria-pressed": String(view.multiples), title: "One small chart per resident", onclick: () => setMultiples(true) }, icon("grid", 14), "Apart"),
    );
    return figure({ title, note, chart: { el: holder, table: () => entry.table() }, tools: [layout], wide });
  }

  /** The rows of one resident, as `[day, value]` points of a field, or of a function of the row. */
  const residentPoints = (field) => (name) => measures.rows.filter((row) => row.resident === name).map((row) => [row.day, typeof field === "function" ? field(row) : row[field]]);

  function setMultiples(on) {
    view.multiples = on;
    renderSection();
  }

  /** A chart of town-wide numbers. */
  function dayFigure({ title, note, lines = [], stacks = [], format = fmt.int, zero = true, min = null, max = null, legend = null, wide = false }) {
    const chart = new DayChart({ days: [1, lastDay()], lines, stacks, y: { format, zero, min, max, integer: format === fmt.int }, height: 160, label: title });
    charts.push(chart);
    return figure({ title, note, chart, legend, wide });
  }

  function head() {
    const entry = ctx.index.runs.find((run) => run.name === route.run) ?? source.entry;
    const doc = source.doc;
    return h(
      "header",
      { class: "run-head" },
      h(
        "div",
        { class: "run-title" },
        h("p", { class: "eyebrow" }, "Run"),
        h("h1", {}, doc.name, groupPill(doc.group)),
        h("p", { class: "lede" }, "How the run has gone: its key figures, each lived day, the rules it ran under, and its measures section by section."),
        h("p", { class: "run-meta" }, `${groupLabel(doc.group) ?? "No group of the design"} · ${fmt.plural(world.residents.length, "resident")} · ${world.model.name}${entry.dry_run ? " (dry run: a stand-in answered)" : ""}`),
        h(
          "p",
          { class: "run-meta quiet-meta" },
          `${reached(entry)} · started ${fmt.wall(doc.started_at)}${doc.ended_at ? `, stopped ${fmt.wall(doc.ended_at)}` : ""} · ${fmt.int(doc.entries)} log entries · code `,
          h("span", { class: "mono", title: doc.code_revision.endsWith("-dirty") ? "The code had uncommitted changes" : "The code revision" }, doc.code_revision.slice(0, 10)),
        ),
      ),
      h("div", { class: "run-side" }, progress(entry), h("a", { class: "btn", href: href(sibling(route, "town")) }, icon("map", 16), "Watch the town")),
    );
  }

  /** The fixed hours of the day as a reader says them; `sleep_at_most` is a length, not an hour. */
  const DAY_HOURS = { forced_sleep: "forced asleep at", checkpoint: "checkpoint at", forced_wake: "forced awake at", board_posted: "board posted at", sleep_at_most: "a sleep lasts at most" };
  const dayHour = (name, clock) => (name === "sleep_at_most" ? duration(parseHHMM(clock)) : clock);

  function rules() {
    const first = world.residents[0];
    const range = (amounts) => (Math.min(...amounts) === Math.max(...amounts) ? fmt.money(amounts[0]) : `${fmt.money(Math.min(...amounts))}–${fmt.money(Math.max(...amounts))}`);
    return h(
      "section",
      { class: "conditions", "aria-label": "Rules" },
      h(
        "div",
        { class: "cond-start" },
        h("p", { class: "eyebrow" }, "The town's rules"),
        h(
          "ul",
          { class: "cond-list" },
          h("li", {}, h("span", { class: "muted" }, "social life"), " ", h("b", {}, world.social.mode === "town" ? "one town, free conversation" : world.social.exchange ? `each alone; paired at ${world.social.exchange.at} at ${world.places.find((p) => p.id === world.social.exchange.place)?.name ?? world.social.exchange.place}` : "each in a town of its own")),
          h("li", {}, h("span", { class: "muted" }, "skills"), " ", h("b", {}, world.skills_writable ? (world.social.skills_shareable ? "written and passed on" : "written, not passed on") : "neither written nor passed on")),
          h("li", {}, h("span", { class: "muted" }, "a task pays"), " ", h("b", {}, fmt.money(world.work.payment))),
          h("li", {}, h("span", { class: "muted" }, "rent for a room"), " ", h("b", {}, `${range(world.places.filter((p) => p.kind === "home").map((p) => p.rent))} a day`)),
          h("li", {}, h("span", { class: "muted" }, "for sale"), " ", h("b", {}, `${fmt.plural(world.goods.length, "good")}, ${range(world.goods.map((g) => g.price))}`)),
          h("li", {}, h("span", { class: "muted" }, "acceptance runs"), " ", h("b", {}, `${world.work.acceptance_runs} per task a day`)),
          h("li", {}, h("span", { class: "muted" }, "a claim runs out"), " ", h("b", {}, `after ${world.work.claim_expiry_days + 1} ${world.work.claim_expiry_days ? "midnights" : "midnight"}`)),
          Object.entries(world.day).map(([name, clock]) => h("li", {}, h("span", { class: "muted" }, DAY_HOURS[name] ?? name.replaceAll("_", " ")), " ", h("b", {}, dayHour(name, clock)))),
        ),
      ),
      first ? h("div", { class: "cond-changes" }, h("p", { class: "eyebrow" }, "As a resident reads them"), h("details", { class: "rules-text" }, h("summary", {}, `The rules ${first.name} was told`), h("pre", {}, first.rules))) : null,
    );
  }

  function keyFigures() {
    const head = progressDoc.daily;
    const total = (field) => sum(head, field);
    const last = head.at(-1);
    return h(
      "div",
      { class: "stats" },
      stat("Hand-ins accepted", fmt.int(total("accepted")), `${fmt.int(total("submissions"))} handed in · ${fmt.int(total("claims"))} claims`),
      stat("Paid", fmt.money(total("paid")), `${fmt.int(total("payments"))} payments`),
      stat("Median purse", last ? fmt.money(last.purse.median) : "–", last ? `${fmt.money(last.purse.min)} to ${fmt.money(last.purse.max)}` : null),
      stat("Things said", fmt.int(total("speeches")), `${fmt.int(total("gifts"))} gifts · ${fmt.int(total("skills_shared"))} skills passed on`),
      stat("Journals written", fmt.int(total("journals")), `at bedtime · ${fmt.int(total("forced_sleeps"))} forced sleeps · ${fmt.int(total("ratings"))} ratings given`),
      total("deaths") ? stat("Deaths", fmt.int(total("deaths")), "health run out at midnight", "critical") : null,
    );
  }

  function evolutionGrid() {
    const days = Math.max(1, ...histories.flatMap((history) => history.versions.map((v) => v.day)));
    const mark = (area) => {
      const shape = { memory: s("rect", { x: -3.4, y: -3.4, width: 6.8, height: 6.8, rx: 1 }), skills: s("path", { d: "M0,-4.6L4.6,0L0,4.6L-4.6,0Z" }), journal: s("circle", { r: 2.2 }), background: s("path", { d: "M0,-4.4L4.2,3.2H-4.2Z" }) }[area];
      return s("svg", { class: `step ${area}`, width: 12, height: 12, viewBox: "-6 -6 12 12", "aria-hidden": "true" }, shape);
    };
    const header = h("tr", {}, h("th", { class: "sticky-col" }, ""), Array.from({ length: days }, (_, i) => h("th", { scope: "col" }, String(i + 1))));
    const body = cast.names.map((name, index) => {
      const history = histories[index];
      return h(
        "tr",
        {},
        h("th", { scope: "row", class: "sticky-col" }, cast.chip(name, href(sibling(route, "person", { agent: name, query: { tab: "files" } })))),
        Array.from({ length: days }, (_, i) => {
          const version = history.versions.find((v) => v.day === i + 1);
          const areas = version ? [...areasOf(version)].sort() : [];
          const title = version ? `${name}, night of day ${i + 1}: ${version.changes.map((c) => c.path).join(", ") || "nothing changed"}` : `${name}, day ${i + 1}: no checkpoint yet`;
          const notable = areas.some((area) => area !== "journal");
          return h(
            "td",
            { title, class: notable ? "notable" : "" },
            version ? h("a", { href: href(sibling(route, "person", { agent: name, query: { tab: "files", v: version.commit } })), "aria-label": title }, areas.length ? areas.map(mark) : h("span", { class: "muted" }, "·")) : null,
          );
        }),
      );
    });
    const key = h("div", { class: "legend static" }, Object.entries(AREAS).map(([area, [label]]) => h("span", { class: "legend-item" }, mark(area), label)));
    return h(
      "figure",
      { class: "figure wide" },
      h("figcaption", {}, h("h3", {}, "Files rewritten, night by night"), h("p", { class: "note" }, "What each resident's files changed between one checkpoint and the next: its memory of the town, the people and its work, its skills, its journal, its background. A marked night opens that version."), key),
      h("div", { class: "table-wrap" }, h("table", { class: "evo-grid" }, h("thead", {}, header), h("tbody", {}, body))),
    );
  }

  function matrix() {
    const options = {
      said: ["Things said", (e) => e.said || null, fmt.int, null],
      minutes: ["Minutes together", (e) => (e.minutes ? Math.round(e.minutes) : null), fmt.int, null],
      ratings: ["Mean rating", (e) => (e.ratings ? e.ratings_sum / e.ratings : null), (v) => fmt.num(v, 1), [1, 5]],
      money: ["Money handed over", (e) => e.money || null, fmt.int, null],
      skills: ["Skills passed on", (e) => e.skills || null, fmt.int, null],
    };
    const [, value, format, fixed] = options[view.matrix];
    const totals = new Map();
    for (const edge of measures.graph) {
      const key = `${edge.source}>${edge.target}`;
      const t = totals.get(key) ?? { minutes: 0, said: 0, said_private: 0, gifts: 0, money: 0, skills: 0, ratings: 0, ratings_sum: 0 };
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
              const detail = edge ? `${from} → ${to}: ${fmt.int(Math.round(edge.minutes))} min in conversation, ${edge.said} things said (${edge.said_private} privately), ${edge.ratings} ratings${edge.ratings ? ` averaging ${fmt.num(edge.ratings_sum / edge.ratings, 2)}` : ""}, ${fmt.money(edge.money)} handed over, ${edge.skills} skills passed on` : `${from} had nothing to do with ${to}`;
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
      h("figcaption", {}, h("div", { class: "figure-head" }, h("h3", {}, "Who to whom, over the run so far"), seg), h("p", { class: "note" }, "Rows act on columns. Ratings are anonymous to the rated: no resident sees who rated whom. Darker cells hold more.")),
      h("div", { class: "table-wrap" }, table),
    );
  }

  const SECTION_CONTENT = {
    work() {
      const { daily, rows } = measures;
      const notAccepted = new Map(dailyPoints(daily, "submitted", "total").map(([day, total]) => [day, total - (dailyValues(daily, "accepted", "total").get(day) ?? 0)]));
      return [
        h("p", { class: "note section-note" }, `Work is SWE-bench Verified: the board posts tasks of the same training pool every day, a resident holds one task at a time, and acceptance runs the hidden tests in a fresh container. ${fmt.int(sum(rows, "claimed"))} claims, ${fmt.int(sum(rows, "submitted"))} hand-ins and ${fmt.int(sum(rows, "accepted"))} accepted over the closed days.`),
        h(
          "div",
          { class: "figures" },
          dayFigure({
            title: "Hand-ins and their verdicts",
            note: "Tasks handed in each day, accepted or not, against the tasks claimed.",
            stacks: [
              { key: "accepted", label: "accepted", color: "var(--good)", values: dailyValues(daily, "accepted", "total") },
              { key: "rejected", label: "not accepted", color: "var(--serious)", values: notAccepted },
            ],
            lines: [{ key: "claimed", label: "claimed", color: "var(--ink)", points: dailyPoints(daily, "claimed", "total") }],
            legend: swatchLegend([["accepted", "var(--good)"], ["not accepted", "var(--serious)"], ["claimed", "var(--ink)", "line"]]),
          }),
          dayFigure({ title: "Hours at work", note: "Mean simulated hours a resident spent in Work each day.", lines: [{ key: "hours", label: "mean hours at work", color: "var(--ink-2)", points: dailyPoints(daily, "work_hours", "mean") }], format: (v) => fmt.num(v, 1) }),
          agentFigure({ title: "Hand-ins accepted", note: "Each resident's accepted hand-ins per day.", points: residentPoints("accepted"), zero: true }),
          agentFigure({ title: "Hours at work", note: "Each resident's simulated hours in Work per day.", points: residentPoints("work_hours"), format: (v) => fmt.num(v, 1), zero: true }),
        ),
      ];
    },
    money() {
      const { daily } = measures;
      return [
        h("p", { class: "note section-note" }, `Each accepted task pays ${fmt.money(world.work.payment)} at once; rent for the room, and the daily charge on anything owned that carries one, is taken at midnight, goods are paid in cash as they are bought, and a purse may go into debt. Residents started with ${world.residents.map((r) => `${r.name} ${fmt.money(r.purse)}`).join(", ")}.`),
        h(
          "div",
          { class: "figures" },
          agentFigure({ title: "Purses", note: "Each resident's purse after the midnight charges.", points: residentPoints("purse"), zero: true }),
          dayFigure({
            title: "Money paid and handed over",
            note: "Paid for accepted tasks, and handed from one resident to another, per day.",
            stacks: [
              { key: "earned", label: "paid for tasks", color: "var(--o2)", values: dailyValues(daily, "earned", "total") },
              { key: "given", label: "handed over", color: "var(--o4)", values: dailyValues(daily, "money_given", "total") },
            ],
            legend: swatchLegend([["paid for tasks", "var(--o2)"], ["handed over", "var(--o4)"]]),
          }),
          dayFigure({ title: "In debt", note: "Residents whose purse was below zero at midnight.", lines: [{ key: "debt", label: "residents in debt", color: "var(--critical)", points: dailyPoints(daily, "in_debt", "total") }], max: cast.names.length }),
        ),
      ];
    },
    body() {
      const { daily, rows } = measures;
      return [
        h("p", { class: "note section-note" }, `Each resident's body has three needs from 0 to 100, read in bands of plain words: satiety, which food restores; energy, spent awake, at work and on the road and restored by sleep up to its health; and health, worn at midnight by a day ended starving or exhausted and by a home of little comfort, mended by days of rest and by the clinic, and fatal at 0. ${fmt.plural(sum(rows, "hungry"), "resident-day")} with nothing eaten, ${fmt.int(sum(rows, "starving"))} starving at midnight, ${fmt.int(sum(rows, "died"))} deaths over the closed days.`),
        h(
          "div",
          { class: "figures" },
          agentFigure({ title: "Health", note: "Each resident's health at midnight, after the night's reckoning, 0 to 100.", points: residentPoints("health"), min: 0, max: 100 }),
          dayFigure({
            title: "Hunger",
            note: "Residents that ate nothing in the day, and those starving at midnight, whose health it wore.",
            lines: [
              { key: "hungry", label: "nothing eaten", color: "var(--o4)", points: dailyPoints(daily, "hungry", "total") },
              { key: "starving", label: "starving at midnight", color: "var(--critical)", points: dailyPoints(daily, "starving", "total") },
            ],
            legend: swatchLegend([["nothing eaten", "var(--o4)", "line"], ["starving at midnight", "var(--critical)", "line"]]),
            max: cast.names.length,
          }),
        ),
      ];
    },
    social() {
      const { daily, rows } = measures;
      return [
        h("p", { class: "note section-note" }, `${fmt.plural(sum(rows, "said_public") + sum(rows, "said_private"), "thing")} said over the closed days, ${fmt.int(sum(rows, "said_private"))} of them privately; ${fmt.plural(sum(rows, "skills_given"), "skill")} passed on, ${fmt.money(sum(rows, "money_given"))} handed over, ${fmt.plural(sum(rows, "ratings_given"), "rating")} given at night. Ratings have no mechanical effect; whatever weight they carry comes from the residents.`),
        h(
          "div",
          { class: "figures" },
          agentFigure({ title: "Things said", note: "Public and private, per day.", points: residentPoints((row) => row.said_public + row.said_private), zero: true }),
          agentFigure({ title: "Rating received", note: "Mean score of the ratings each resident received that night, from 1 to 5.", points: residentPoints("rating_received_mean"), format: (v) => fmt.num(v, 2), min: 1, max: 5 }),
          dayFigure({
            title: "Skills and money passed on",
            note: "Skills passed on and gifts of money, per day.",
            stacks: [
              { key: "skills", label: "skills passed on", color: "var(--o3)", values: dailyValues(daily, "skills_given", "total") },
              { key: "gifts", label: "residents who gave money", color: "var(--o1)", values: new Map(dailyPoints(daily, "money_given", "residents").map(([day, n]) => [day, n])) },
            ],
            legend: swatchLegend([["skills passed on", "var(--o3)"], ["residents who gave money", "var(--o1)"]]),
          }),
          dayFigure({ title: "People spoken with", note: "Mean number of distinct residents each spoke to or was spoken to by.", lines: [{ key: "interlocutors", label: "mean interlocutors", color: "var(--ink-2)", points: dailyPoints(daily, "interlocutors", "mean") }], format: (v) => fmt.num(v, 1) }),
          matrix(),
        ),
      ];
    },
    evolution() {
      const steps = histories.flatMap((history) => history.versions.filter((v) => v.day >= 1));
      const notable = steps.filter((v) => [...areasOf(v)].some((area) => area !== "journal")).length;
      return [
        h("p", { class: "note section-note" }, `Residents rewrite their own files whenever they decide to, with their file tools; the checkpoint of each day commits what changed. ${fmt.plural(steps.length, "night")} committed so far, ${fmt.int(notable)} of them with a change beyond the journal. ${world.skills_writable ? "Skills may be written." : "Skills cannot be written in this group."}`),
        steps.length
          ? h("div", { class: "figures" }, evolutionGrid())
          : h("div", { class: "card" }, emptyState("No night has been committed yet.", running() ? `The checkpoint at ${world.day.checkpoint} commits what each resident changed in its files during the day; the first marks appear after it.` : "The run stopped before its first checkpoint, so no night's changes were committed.")),
      ];
    },
    evaluation() {
      const any = evaluation.capability.length || evaluation.mask.length || evaluation.journals.length;
      return any
        ? [
            h("div", { class: "spread section-note" }, h("p", { class: "note" }, "Evaluations run on exports of the residents at the end of a day; day 0 is the resident as created."), h("a", { class: "quiet small", href: href(sibling(route, "evaluation")) }, "Tables and problems", icon("chevron", 14))),
            h("div", { class: "figures three" }, evaluationFigures(evaluation, cast, { highlight: emphasis(), into: charts, onHighlight: pick })),
          ]
        : h("div", { class: "card" }, emptyState("This run has not been evaluated yet.", "Results appear here when they are written under the results root and the runs are published again."));
    },
    usage() {
      const { daily, rows } = measures;
      return [
        h("p", { class: "note section-note" }, `${fmt.int(sum(rows, "requests"))} model requests over the closed days, ${fmt.compact(sum(rows, "prompt_tokens") + sum(rows, "completion_tokens"))} tokens; ${fmt.int(sum(rows, "lapses"))} lapses, ${fmt.int(sum(rows, "interruptions"))} replies interrupted by speech, ${fmt.int(sum(rows, "compactions"))} compactions.`),
        h(
          "div",
          { class: "figures" },
          agentFigure({ title: "Requests", note: "Model requests per resident and day, retries and compactions included.", points: residentPoints("requests"), zero: true }),
          agentFigure({ title: "Tokens", note: "Prompt and completion tokens per resident and day.", points: residentPoints((row) => row.prompt_tokens + row.completion_tokens), format: fmt.compact, zero: true }),
          dayFigure({ title: "Cached share", note: "Mean share of prompt tokens served from the cache, of the replies that report it.", lines: [{ key: "cached", label: "cached share", color: "var(--ink-2)", points: dailyPoints(daily, "cached_share", "mean") }], format: (v) => fmt.pct(v), min: 0, max: 1 }),
        ),
      ];
    },
  };

  const legendHolder = h("div", { class: "agent-legend", "aria-label": "Emphasise a resident" });
  const sectionBody = h("div", { class: "section-body" });

  function renderSection() {
    for (const chart of [...charts, ...agentFigures]) chart.destroy();
    charts = [];
    agentFigures = [];
    const key = section();
    const closed = measures.rows.length > 0 || key === "evaluation" || key === "evolution";
    legendHolder.hidden = !BY_RESIDENT.has(key) || !closed;
    fill(legendHolder, h("span", { class: "muted legend-lead" }, "Emphasise"), agentLegend(cast, cast.names, { selected: view.pinned, onPick: pick }));
    const empty = running()
      ? emptyState("No day has closed yet.", `The measures are computed over lived days a checkpoint closed, the first at ${world.day.checkpoint}; the table above counts the day in progress.`)
      : emptyState("The run stopped before a checkpoint closed a day.", "The measures are computed over closed days only; the table above counts what happened in the day it stopped in.");
    fill(sectionBody, closed ? SECTION_CONTENT[key]() : h("div", { class: "card" }, empty));
    for (const tab of page.querySelectorAll(".run-sections [data-section]")) tab.setAttribute("aria-selected", String(tab.dataset.section === key));
  }

  function render() {
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
              route = { ...route, query: { ...route.query, section: key === "work" ? null : key } };
              ctx.remember(route);
              renderSection();
            },
          },
          label,
        ),
      ),
    );
    const partial = progressDoc.daily.some((d) => d.in_progress);
    fill(
      page,
      head(),
      keyFigures(),
      partial
        ? h("p", { class: "note partial-note" }, running() ? `Day ${progressDoc.day} is in progress (${progressDoc.clock}): its numbers count only what has happened so far.` : `The run stopped on day ${progressDoc.day} at ${progressDoc.clock}, before a checkpoint closed the day: that day's numbers count what happened until then.`)
        : null,
      h("figure", { class: "figure wide progress-figure" }, h("figcaption", {}, h("h3", {}, "Day by day"), h("p", { class: "note" }, "Each lived day, from one checkpoint to the next, and what it counted.")), progressDoc.daily.length ? progressTable(progressDoc, source.doc.status) : emptyState("No day has begun yet.", "The table of lived days fills in as the run records its first entries.")),
      rules(),
      h("div", { class: "section-bar" }, tabs, legendHolder),
      sectionBody,
    );
    renderSection();
  }

  async function load() {
    page.replaceChildren(h("div", { class: "loading" }, "Loading the run's measures…"));
    try {
      [measures, evaluation, progressDoc, histories] = await Promise.all([source.measures(), source.evaluation(), source.progress(), Promise.all(cast.names.map((name) => source.versions(name)))]);
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
      if (changes.measures || changes.evaluation || changes.status || changes.progress || changes.agents.length) {
        const y = window.scrollY;
        await load();
        window.scrollTo(0, y);
      }
    },
    destroy() {
      for (const chart of [...charts, ...agentFigures]) chart.destroy();
    },
  };
}
