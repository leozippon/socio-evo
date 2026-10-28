// A run's dashboard: the run itself, a few key figures, each lived day, and the rules it ran
// under; then one section at a time: work, money and the Store, the body, social life,
// evolution (what residents rewrote each night), the evaluation of their exports, and model
// usage. The sections read the timeline, so the day in progress counts too; only model usage
// and the file rewrites wait for a closed day.

import { DayChart, Multiples, agentLegend, figure, swatchLegend } from "../charts.js";
import { duration, parseHHMM } from "../clock.js";
import { emptyState, fill, fmt, h, s } from "../dom.js";
import { goodName, inventory, itemCard, needBars } from "../goods.js";
import { icon } from "../icons.js";
import { bodyAt, markersBetween, purseAt, thingsAt } from "../replay.js";
import { href, sibling } from "../router.js";
import { evaluationFigures } from "./evaluation.js";
import { progress, progressTable, reached } from "./landing.js";

const SECTIONS = [
  ["work", "Work"],
  ["money", "Money and the Store"],
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
  let data = null; // the timeline
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

  // The lived days of the timeline, the day in progress included, and what each lane did in each.
  const lastDay = () => Math.max(1, data.days.at(-1)?.day ?? 1);
  const laneOf = (name) => data.residents.find((lane) => lane.name === name);
  const endOf = (day) => day.end ?? data.now;
  const fromOf = (i) => (i ? data.days[i - 1].end : null);
  const markersIn = (lane, i, kind) => markersBetween(lane, fromOf(i), endOf(data.days[i])).filter((m) => m.kind === kind);
  /** `[day, value]` points for one resident, `value(lane, i)` over its lived day `i`. */
  const residentPoints = (value) => (name) => data.days.map((day, i) => [day.day, value(laneOf(name), i, day)]);
  /** `[day, total]` points over every resident. */
  const townPoints = (value) => data.days.map((day, i) => [day.day, cast.names.reduce((total, name) => total + (value(laneOf(name), i, day) ?? 0), 0)]);
  const townValues = (value) => new Map(townPoints(value));
  const count = (kind, keep = () => true) => (lane, i) => markersIn(lane, i, kind).filter(keep).length;
  const amount = (kind, field, keep = () => true) => (lane, i) => markersIn(lane, i, kind).filter(keep).reduce((a, m) => a + (m[field] ?? 0), 0);
  /** The midnight statement of a lane's lived day, if the day reached midnight. */
  const midnightOf = (lane, i) => markersIn(lane, i, "settlement")[0] ?? null;
  /** Simulated hours a lane spent in Work within its lived day. */
  const workHours = (lane, i) => {
    const from = fromOf(i) ?? data.start;
    const to = endOf(data.days[i]);
    return lane.segments.filter((seg) => seg.kind === "work" && seg.end > from && seg.start < to).reduce((a, seg) => a + (Math.min(seg.end, to) - Math.max(seg.start, from)), 0) / 3600;
  };
  const isFood = (m) => world.goods.find((good) => good.id === m.item)?.effect === "food";
  const total = (value) => cast.names.reduce((a, name) => a + data.days.reduce((b, day, i) => b + (value(laneOf(name), i, day) ?? 0), 0), 0);

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
    const workplace = world.places.find((place) => place.kind === "workplace");
    return h(
      "header",
      { class: "run-head" },
      h(
        "div",
        { class: "run-title" },
        h("p", { class: "eyebrow" }, "Run"),
        h("h1", {}, doc.name),
        h("p", { class: "lede" }, `${fmt.plural(world.residents.length, "resident")} live in a small town for ${fmt.plural(world.days, "day")}: they take programming tasks from the board at ${workplace?.name ?? "the workplace"}, pay rent and buy food and things, meet and talk, and rewrite their own notes and skills as they go. Nobody tells them how to behave. This page has the numbers; the town shows it happening, and each resident's story holds its journal, files and raw trace.`),
        h("p", { class: "run-meta" }, `${world.model.name}${entry.dry_run ? " (dry run: a stand-in answered)" : ""}`),
        h(
          "p",
          { class: "run-meta quiet-meta" },
          `${reached(entry)} · started ${fmt.wall(doc.started_at)}${doc.ended_at ? `, stopped ${fmt.wall(doc.ended_at)}` : ""} · ${fmt.int(doc.entries)} log entries · code `,
          h("span", { class: "mono", title: doc.code_revision.endsWith("-dirty") ? "The code had uncommitted changes" : "The code revision" }, doc.code_revision.slice(0, 10)),
        ),
      ),
      h(
        "div",
        { class: "run-side" },
        progress(entry),
        h("div", { class: "run-go" }, h("a", { class: "btn", href: href(sibling(route, "town")) }, icon("map", 16), "Watch the town"), h("a", { class: "ghost", href: href(sibling(route, "person", { agent: cast.names[0] })) }, icon("people", 16), "The people")),
      ),
    );
  }

  /** The fixed hours of the day as a reader says them; `sleep_at_most` is a length, not an hour. */
  const DAY_HOURS = { forced_sleep: "everyone still up falls asleep at", checkpoint: "the day is saved at", forced_wake: "those put to sleep wake at", board_posted: "the board goes up at", sleep_at_most: "a sleep lasts at most" };
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
          h("li", {}, h("span", { class: "muted" }, "a conversation ends"), " ", h("b", {}, `after ${world.social.silence_minutes} minutes of silence`)),
          h("li", {}, h("span", { class: "muted" }, "a task pays"), " ", h("b", {}, fmt.money(world.work.payment))),
          h("li", {}, h("span", { class: "muted" }, "rent for a room"), " ", h("b", {}, `${range(world.places.filter((p) => p.kind === "home").map((p) => p.rent))} a day`)),
          h("li", {}, h("span", { class: "muted" }, "for sale"), " ", h("b", {}, `${fmt.plural(world.goods.length, "good")}, ${range(world.goods.map((g) => g.price))}`)),
          h("li", {}, h("span", { class: "muted" }, "hand-ins per task"), " ", h("b", {}, `${world.work.acceptance_runs} a day`)),
          h("li", {}, h("span", { class: "muted" }, "a claim runs out"), " ", h("b", {}, `after ${world.work.claim_expiry_days + 1} ${world.work.claim_expiry_days ? "midnights" : "midnight"}`)),
          Object.entries(world.day).map(([name, clock]) => h("li", {}, h("span", { class: "muted" }, DAY_HOURS[name] ?? name.replaceAll("_", " ")), " ", h("b", {}, dayHour(name, clock)))),
        ),
      ),
      first ? h("div", { class: "cond-changes" }, h("p", { class: "eyebrow" }, "As a resident reads them"), h("details", { class: "rules-text fold" }, h("summary", {}, `The rules ${first.name} was told`), h("pre", {}, first.rules))) : null,
    );
  }

  function keyFigures() {
    const head = progressDoc.daily;
    const total = (field) => sum(head, field);
    const last = head.at(-1);
    const spent = cast.names.reduce((a, name) => a + markersBetween(laneOf(name), null, data.now).filter((m) => m.kind === "purchase").reduce((b, m) => b + m.amount, 0), 0);
    return h(
      "div",
      { class: "stats" },
      stat("Hand-ins accepted", fmt.int(total("accepted")), `${fmt.int(total("submissions"))} handed in · ${fmt.int(total("claims"))} claims`),
      stat("Paid for tasks", fmt.money(total("paid")), `${fmt.int(total("payments"))} payments`),
      stat("Median purse", last ? fmt.money(last.purse.median) : "–", last ? `${fmt.money(last.purse.min)} to ${fmt.money(last.purse.max)}` : null),
      stat("Goods bought", fmt.int(total("purchases")), `for ${fmt.money(spent)} in all`),
      stat("Things said", fmt.int(total("speeches")), `${fmt.int(total("gifts"))} gifts · ${fmt.int(total("skills_shared"))} files passed on`),
      stat("Journals written", fmt.int(total("journals")), `at bedtime · ${fmt.int(total("forced_sleeps"))} forced sleeps`),
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
      money: ["Money handed over", (e) => e.money || null, fmt.int, null],
      skills: ["Files passed on", (e) => e.skills || null, fmt.int, null],
    };
    const [, value, format, fixed] = options[view.matrix] ?? options.said;
    const totals = new Map();
    for (const edge of measures.graph) {
      const key = `${edge.source}>${edge.target}`;
      const t = totals.get(key) ?? { minutes: 0, said: 0, said_private: 0, gifts: 0, money: 0, skills: 0 };
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
              const detail = edge ? `${from} → ${to}: ${fmt.int(Math.round(edge.minutes))} min in conversation, ${edge.said} things said (${edge.said_private} privately), ${fmt.money(edge.money)} handed over, ${edge.skills} skills passed on` : `${from} had nothing to do with ${to}`;
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
      h("figcaption", {}, h("div", { class: "figure-head" }, h("h3", {}, "Who to whom, over the run so far"), seg), h("p", { class: "note" }, "Rows act on columns. Darker cells hold more.")),
      h("div", { class: "table-wrap" }, table),
    );
  }

  /** The Store's catalogue: every good with its price, where it is sold and what it does. */
  function catalogue() {
    return h(
      "figure",
      { class: "figure wide" },
      h("figcaption", {}, h("h3", {}, "For sale"), h("p", { class: "note" }, "Everything a resident can buy, paid in cash on the spot: food to eat at once or to keep, things that are kept and do something for their owner, and the clinic's care.")),
      h("div", { class: "catalogue" }, world.goods.map((good) => itemCard(good, { price: true, world }))),
    );
  }

  /** What everyone owns at the latest moment, and how often each good was bought. */
  function belongings() {
    const bought = new Map(world.goods.map((good) => [good.id, cast.names.map((name) => markersBetween(laneOf(name), null, data.now).filter((m) => m.kind === "purchase" && m.item === good.id).reduce((a, m) => a + m.quantity, 0))]));
    return [
      h(
        "figure",
        { class: "figure wide" },
        h("figcaption", {}, h("h3", {}, "What everyone owns now"), h("p", { class: "note" }, "As of the latest moment. A stock of food is eaten unseen; its count is as last taken, at the purchase or at the checkpoint.")),
        h("ul", { class: "belongings" }, cast.names.map((name) => h("li", {}, cast.chip(name, href(sibling(route, "person", { agent: name }))), inventory(world, thingsAt(laneOf(name), data.now), { compact: true })))),
      ),
      h(
        "figure",
        { class: "figure wide" },
        h("figcaption", {}, h("h3", {}, "Bought over the run"), h("p", { class: "note" }, "How many of each good every resident has bought so far.")),
        h(
          "div",
          { class: "table-wrap" },
          h(
            "table",
            { class: "matrix" },
            h("thead", {}, h("tr", {}, h("th", { class: "corner sticky-col" }, ""), cast.names.map((name) => h("th", { scope: "col", title: name }, cast.badge(name, 16))))),
            h("tbody", {}, world.goods.map((good) => h("tr", {}, h("th", { scope: "row", class: "sticky-col" }, goodName(good)), bought.get(good.id).map((n) => h("td", { class: n ? `heat-${Math.min(5, n)}` : "none" }, n ? fmt.int(n) : ""))))),
          ),
        ),
      ),
    ];
  }

  /** How everyone is at the latest moment: the three bars each. */
  function bodies() {
    return h(
      "figure",
      { class: "figure wide" },
      h("figcaption", {}, h("h3", {}, "How everyone is now"), h("p", { class: "note" }, "Food in the body, energy and health at the latest moment, each read in the bands the town tells; hover a bar for the last number the world told.")),
      h("ul", { class: "bodies" }, cast.names.map((name) => h("li", {}, cast.chip(name, href(sibling(route, "person", { agent: name }))), needBars(world, bodyAt(laneOf(name), data.now))))),
    );
  }

  const SECTION_CONTENT = {
    work() {
      const accepted = count("submission", (m) => m.resolved === true);
      const rejected = count("submission", (m) => m.resolved === false);
      return [
        h("p", { class: "note section-note" }, `The board posts programming tasks from the training pool each morning; a resident holds one task at a time, hands it in and is paid ${fmt.money(world.work.payment)} if the client's checks pass. ${fmt.int(total(count("claim")))} claims, ${fmt.int(total(count("submission")))} hand-ins and ${fmt.int(total(accepted))} accepted so far.`),
        h(
          "div",
          { class: "figures" },
          dayFigure({
            title: "Hand-ins and their verdicts",
            note: "Tasks handed in each day, accepted or not, against the tasks claimed.",
            stacks: [
              { key: "accepted", label: "accepted", color: "var(--good)", values: townValues(accepted) },
              { key: "rejected", label: "not accepted", color: "var(--serious)", values: townValues(rejected) },
            ],
            lines: [{ key: "claimed", label: "claimed", color: "var(--ink)", points: townPoints(count("claim")) }],
            legend: swatchLegend([["accepted", "var(--good)"], ["not accepted", "var(--serious)"], ["claimed", "var(--ink)", "line"]]),
          }),
          dayFigure({ title: "Hours at work", note: "Hours a resident spent at work each day, on average over the residents.", lines: [{ key: "hours", label: "mean hours at work", color: "var(--ink-2)", points: townPoints(workHours).map(([day, hours]) => [day, hours / cast.names.length]) }], format: (v) => fmt.num(v, 1) }),
          agentFigure({ title: "Hand-ins accepted", note: "Each resident's accepted hand-ins per day.", points: residentPoints(accepted), zero: true }),
          agentFigure({ title: "Hours at work", note: "Each resident's hours at work per day.", points: residentPoints(workHours), format: (v) => fmt.num(v, 1), zero: true }),
        ),
      ];
    },
    money() {
      const rent = amount("settlement", "rent");
      const fees = amount("settlement", "fees");
      const food = amount("purchase", "amount", isFood);
      const other = amount("purchase", "amount", (m) => !isFood(m));
      const debt = (lane, i, day) => (purseAt(lane, endOf(day)) < 0 ? 1 : 0);
      return [
        h("p", { class: "note section-note" }, `Each accepted task pays ${fmt.money(world.work.payment)} at once. At midnight the rent for the room and the daily charge on anything owned that carries one are taken; goods are paid in cash as they are bought; a purse may go into debt, which only stops buying. Residents started with ${world.residents.map((r) => `${r.name} ${fmt.money(r.purse)}`).join(", ")}.`),
        h(
          "div",
          { class: "figures" },
          agentFigure({ title: "Purses", note: "Each resident's purse at the end of each day, or now for the day in progress.", points: residentPoints((lane, i, day) => purseAt(lane, endOf(day))), zero: true }),
          dayFigure({
            title: "Earned and spent, the town in all",
            note: "Paid for tasks, against what went out: rent, the daily charges, food and other goods, per day.",
            stacks: [
              { key: "rent", label: "rent", color: "var(--o4)", values: townValues(rent) },
              { key: "fees", label: "daily charges", color: "var(--o3)", values: townValues(fees) },
              { key: "food", label: "food", color: "var(--o2)", values: townValues(food) },
              { key: "goods", label: "other goods", color: "var(--o1)", values: townValues(other) },
            ],
            lines: [
              { key: "earned", label: "paid for tasks", color: "var(--good)", points: townPoints(amount("payment", "amount")) },
              { key: "given", label: "money given", color: "var(--ink-2)", points: townPoints(amount("gift", "amount")) },
            ],
            legend: swatchLegend([["rent", "var(--o4)"], ["daily charges", "var(--o3)"], ["food", "var(--o2)"], ["other goods", "var(--o1)"], ["paid for tasks", "var(--good)", "line"], ["money given", "var(--ink-2)", "line"]]),
          }),
          dayFigure({ title: "In debt", note: "Residents whose purse was below zero at the end of the day.", lines: [{ key: "debt", label: "residents in debt", color: "var(--critical)", points: townPoints(debt) }], max: cast.names.length }),
          catalogue(),
          belongings(),
        ),
      ];
    },
    body() {
      const starving = (lane, i) => (midnightOf(lane, i)?.night.starving !== undefined ? 1 : 0);
      const exhausted = (lane, i) => (midnightOf(lane, i)?.night.exhausted !== undefined ? 1 : 0);
      const unfed = (lane, i) => (midnightOf(lane, i) && !midnightOf(lane, i).nourishment ? 1 : 0);
      return [
        h("p", { class: "note section-note" }, `Each resident's body has three needs from 0 to 100, which it reads in bands of plain words: food in the body, which eating restores; energy, spent awake, at work and on the road and restored by sleep up to its health; and health, worn at midnight by a day ended starving or exhausted and by a home of little comfort, mended by days of rest and by the clinic, and fatal at 0. ${fmt.plural(total(unfed), "resident-day")} with nothing eaten, ${fmt.int(total(starving))} starving at midnight, ${fmt.int(sum(progressDoc.daily, "deaths"))} deaths so far.`),
        h(
          "div",
          { class: "figures" },
          bodies(),
          agentFigure({ title: "Health at midnight", note: "Each resident's health after the night's reckoning, 0 to 100.", points: residentPoints((lane, i) => midnightOf(lane, i)?.health ?? null), min: 0, max: 100 }),
          agentFigure({ title: "A day's food", note: "What each resident ate in the day, as a share of a day's need; 100 is a full day.", points: residentPoints((lane, i) => midnightOf(lane, i)?.nourishment ?? null), zero: true }),
          dayFigure({
            title: "Hunger and exhaustion",
            note: "Residents that ate nothing in the day, and those starving or exhausted at midnight, whose health it wore.",
            lines: [
              { key: "unfed", label: "nothing eaten", color: "var(--o4)", points: townPoints(unfed) },
              { key: "starving", label: "starving at midnight", color: "var(--critical)", points: townPoints(starving) },
              { key: "exhausted", label: "exhausted at midnight", color: "var(--serious)", points: townPoints(exhausted) },
            ],
            legend: swatchLegend([["nothing eaten", "var(--o4)", "line"], ["starving at midnight", "var(--critical)", "line"], ["exhausted at midnight", "var(--serious)", "line"]]),
            max: cast.names.length,
          }),
        ),
      ];
    },
    social() {
      const said = count("speech");
      return [
        h("p", { class: "note section-note" }, `Residents talk only with those at the same place, write to other phone owners from anywhere, give one another money, things and food on their own terms, and pass copies of their files, skills or notes, to those they talk with. ${fmt.plural(total(said), "thing")} said, ${fmt.int(total(count("message")))} written, ${fmt.plural(total(count("skill_shared")), "file")} passed on, ${fmt.plural(total(count("gift")), "gift")} given and ${fmt.money(total(amount("gift", "amount")))} of money among them so far.`),
        h(
          "div",
          { class: "figures" },
          agentFigure({ title: "Things said", note: "To everyone present or to someone by name, per day.", points: residentPoints(said), zero: true }),
          dayFigure({
            title: "Files and gifts passed on",
            note: "Copies of files passed on, and gifts of money or things, per day.",
            stacks: [
              { key: "skills", label: "files passed on", color: "var(--o3)", values: townValues(count("skill_shared")) },
              { key: "gifts", label: "gifts", color: "var(--o1)", values: townValues(count("gift")) },
            ],
            legend: swatchLegend([["files passed on", "var(--o3)"], ["gifts", "var(--o1)"]]),
          }),
          dayFigure({ title: "Written messages", note: "Messages written from one phone to another, per day.", lines: [{ key: "messages", label: "messages", color: "var(--ink-2)", points: townPoints(count("message")) }] }),
          matrix(),
        ),
      ];
    },
    evolution() {
      const steps = histories.flatMap((history) => history.versions.filter((v) => v.day >= 1));
      const notable = steps.filter((v) => [...areasOf(v)].some((area) => area !== "journal")).length;
      return [
        h("p", { class: "note section-note" }, `Residents rewrite their own files whenever they decide to: their notes, their skills, their journal and the account of themselves. The checkpoint of each day commits what changed. ${fmt.plural(steps.length, "night")} committed so far, ${fmt.int(notable)} of them with a change beyond the journal.`),
        steps.length
          ? h("div", { class: "figures" }, evolutionGrid())
          : h("div", { class: "card" }, emptyState("No night has been committed yet.", running() ? `The checkpoint at ${world.day.checkpoint} commits what each resident changed in its files during the day; the first marks appear after it.` : "The run stopped before its first checkpoint, so no night's changes were committed.")),
      ];
    },
    evaluation() {
      const any = evaluation.capability.length || evaluation.mask.length || evaluation.journals.length;
      return any
        ? [
            h("div", { class: "spread section-note" }, h("p", { class: "note" }, "Measured outside the town on copies of each resident's files at the end of a day; day 0 is the resident as created. Capability is the share of held-out tasks solved; honesty under pressure the share of answers that stayed truthful when pushed; journal distortion the share of a journal's checkable claims the record contradicts."), h("a", { class: "quiet small", href: href(sibling(route, "evaluation")) }, "Tables and problems", icon("chevron", 14))),
            h("div", { class: "figures three" }, evaluationFigures(evaluation, cast, { highlight: emphasis(), into: charts, onHighlight: pick })),
          ]
        : h("div", { class: "card" }, emptyState("This run has not been evaluated yet.", "Results appear here when they are written under the results root and the runs are published again."));
    },
    usage() {
      const { daily, rows } = measures;
      if (!rows.length) return h("div", { class: "card" }, emptyState("No day has closed yet.", running() ? `Model usage is counted over lived days a checkpoint closed, the first at ${world.day.checkpoint}.` : "Model usage is counted over closed days only, and the run stopped before a checkpoint closed a day."));
      const rowPoints = (field) => (name) => rows.filter((row) => row.resident === name).map((row) => [row.day, typeof field === "function" ? field(row) : row[field]]);
      return [
        h("p", { class: "note section-note" }, `${fmt.int(sum(rows, "requests"))} model requests over the closed days, ${fmt.compact(sum(rows, "prompt_tokens") + sum(rows, "completion_tokens"))} tokens; ${fmt.int(sum(rows, "lapses"))} lapses, ${fmt.int(sum(rows, "interruptions"))} replies interrupted by speech, ${fmt.int(sum(rows, "compactions"))} compactions.`),
        h(
          "div",
          { class: "figures" },
          agentFigure({ title: "Requests", note: "Model requests per resident and day, retries and compactions included.", points: rowPoints("requests"), zero: true }),
          agentFigure({ title: "Tokens", note: "Prompt and completion tokens per resident and day.", points: rowPoints((row) => row.prompt_tokens + row.completion_tokens), format: fmt.compact, zero: true }),
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
    legendHolder.hidden = !BY_RESIDENT.has(key) || (key === "usage" && !measures.rows.length);
    fill(legendHolder, h("span", { class: "muted legend-lead" }, "Emphasise"), agentLegend(cast, cast.names, { selected: view.pinned, onPick: pick }));
    fill(sectionBody, data.days.length ? SECTION_CONTENT[key]() : h("div", { class: "card" }, emptyState("No day has begun yet.", "The sections fill in as the run records its first entries.")));
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
    page.replaceChildren(h("div", { class: "loading" }, "Loading the run…"));
    try {
      [measures, evaluation, progressDoc, histories, data] = await Promise.all([source.measures(), source.evaluation(), source.progress(), Promise.all(cast.names.map((name) => source.versions(name))), source.timeline()]);
      render();
    } catch (error) {
      page.replaceChildren(h("div", { class: "card" }, emptyState("The run could not be loaded.", error.message)));
      ctx.fail(error);
    }
  }

  load();
  return {
    update(next) {
      const before = section();
      route = next;
      if (data && section() !== before) renderSection();
      return true;
    },
    async live({ changes }) {
      if (!changes) return;
      if (changes.measures || changes.evaluation || changes.status || changes.progress || changes.timeline || changes.agents.length) {
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
