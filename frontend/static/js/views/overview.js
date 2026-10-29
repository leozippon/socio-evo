// A run's dashboard: the run itself, a few key figures, each lived day, and the rules it ran
// under; then one section at a time: work at the Office and everyone's hours, money (the
// town's treasury, the businesses' books, what each resident earned and spent), the Store and
// the kitchen, the body and the Hospital, social life, evolution (what residents rewrote each
// night), the evaluation of their exports, and model usage. The sections read the timeline, so
// the day in progress counts too; the treasury and the businesses' books are read at each
// checkpoint from the town's measures, and model usage and the file rewrites wait for a closed
// day.

import { DayChart, Multiples, agentLegend, figure, swatchLegend } from "../charts.js";
import { dateOf, duration, hhmm, parseHHMM, secondOfDay } from "../clock.js";
import { emptyState, fill, fmt, h, s } from "../dom.js";
import { amountOf, dishCard, goodEffect, goodName, inventory, itemOf, needBars } from "../goods.js";
import { icon } from "../icons.js";
import { LARDER, bodyAt, boughtAtCounter, dishServed, handedOver, holderAt, markersBetween, moneyMoved, purseAt, shopsAt, spentOn, thingsAt } from "../replay.js";
import { href, sibling } from "../router.js";
import { placeOfKind } from "../world.js";
import { evaluationFigures } from "./evaluation.js";
import { progress, progressTable, reached } from "./landing.js";

const SECTIONS = [
  ["work", "Work"],
  ["money", "Money"],
  ["trade", "Store and kitchen"],
  ["body", "Body and care"],
  ["social", "Social life"],
  ["evolution", "Evolution"],
  ["evaluation", "Evaluation"],
  ["usage", "Model usage"],
];
/** Sections whose charts draw one mark per resident, so the emphasis legend applies. */
const BY_RESIDENT = new Set(["work", "money", "body", "social", "usage", "evaluation"]);
const AREAS = { memory: ["memory", /^memory\/(?!journal\/)/], skills: ["skills", /^skills\//], journal: ["journal", /^memory\/journal\//], background: ["background", /^background\.md$/] };
/** What the treasury takes in and pays out, by the kinds its ledger keeps, with a colour each. */
const TAKEN = [
  ["tax", "taxes", "var(--o5)"],
  ["rent", "rent and charges", "var(--o3)"],
];
const PAID = [
  ["salary", "the salary", "var(--o2)"],
  ["grant", "grants", "var(--o1)"],
];
/** A name with its first letter capitalised, to begin a sentence or a title. */
const cap = (text) => `${text[0].toUpperCase()}${text.slice(1)}`;

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

/** A small table: a header and rows of cells, in a box that scrolls sideways. */
const table = (head, rows) => h("div", { class: "table-wrap" }, h("table", { class: "data text" }, h("thead", {}, h("tr", {}, head.map((cell) => h("th", {}, cell)))), h("tbody", {}, rows.map((row) => h("tr", {}, row.map((cell) => h("td", {}, cell)))))));

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
  const office = placeOfKind(world, "office");
  const store = placeOfKind(world, "store");
  const restaurant = placeOfKind(world, "restaurant");
  const hospital = placeOfKind(world, "hospital");

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
  const inDay = (i) => (m) => (fromOf(i) === null || m.t > fromOf(i)) && m.t <= endOf(data.days[i]);
  /** A test of a marker: of the kind named, or kept by the function given. */
  const of = (kind) => (typeof kind === "function" ? kind : (m) => m.kind === kind);
  const markersIn = (lane, i, kind) => markersBetween(lane, fromOf(i), endOf(data.days[i])).filter(of(kind));
  /** `[day, value]` points for one resident, `value(lane, i)` over its lived day `i`. */
  const residentPoints = (value) => (name) => data.days.map((day, i) => [day.day, value(laneOf(name), i, day)]);
  /** `[day, total]` points over every resident. */
  const townPoints = (value) => data.days.map((day, i) => [day.day, cast.names.reduce((total, name) => total + (value(laneOf(name), i, day) ?? 0), 0)]);
  const townValues = (value) => new Map(townPoints(value));
  /** `[day, count]` of the town's own markers of `kind`. */
  const ownPoints = (kind) => data.days.map((day, i) => [day.day, data.markers.filter((m) => m.kind === kind && inDay(i)(m)).length]);
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
  const isFood = (m) => itemOf(world, m.item)?.effect === "food";
  /** What a lane paid for what it bought for itself within its lived day `i`, of the purchases `keep` keeps. */
  const bought = (keep) => (lane, i) => markersIn(lane, i, (m) => spentOn(m) > 0 && keep(m)).reduce((a, m) => a + spentOn(m), 0);
  const total = (value) => cast.names.reduce((a, name) => a + data.days.reduce((b, day, i) => b + (value(laneOf(name), i, day) ?? 0), 0), 0);
  /** Every marker of `kind` (or that it keeps) on every lane over the run so far, each with its resident. */
  const everywhere = (kind) => data.residents.flatMap((lane) => lane.markers.filter(of(kind)).map((m) => [lane.name, m]));
  /** The town's days of the measures, by day: the treasury as each closed day's checkpoint saved it, and the businesses' books. */
  const saved = () => new Map(measures.town.map((row) => [row.day, row]));
  const moment = (t) => `day ${data.days.find((day) => day.end === null || t <= day.end)?.day ?? data.days.at(-1).day}, ${hhmm(secondOfDay(t))}`;

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

  /** A figure that is a table or a list rather than a chart. */
  const plain = (title, note, body, wide = true) => h("figure", { class: `figure${wide ? " wide" : ""}` }, h("figcaption", {}, h("h3", {}, title), note ? h("p", { class: "note" }, note) : null), body);

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
        h("h1", {}, doc.name),
        h("p", { class: "lede" }, `${fmt.plural(world.residents.length, "resident")} live in a small town for ${fmt.plural(world.days, "day")}, each at its occupation: programmers and their team leader at ${office.name}, a shopkeeper at ${store.name}, a chef at ${restaurant.name}, a doctor at ${hospital.name} and a mayor at ${placeOfKind(world, "hall").name}. Clients pay for the Office's tasks, the shops and the Hospital keep what they take, and the town's treasury takes a tax on every payment and the rent, pays the mayor and grants what the mayor decides; they buy food and things, eat out, fall ill, meet and talk, and rewrite their own notes and skills as they go. Nobody tells them how to behave. This page has the numbers; the town shows it happening, and each resident's story holds its journal, files and raw trace.`),
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
  const DAY_HOURS = { forced_sleep: "everyone still up falls asleep at", checkpoint: "the day is saved at", forced_wake: "those put to sleep wake at", delivery: "the Store's orders arrive at", sleep_at_most: "a sleep lasts at most" };
  const dayHour = (name, clock) => (name === "sleep_at_most" ? duration(parseHHMM(clock)) : clock);

  function rules() {
    const first = world.residents[0];
    const range = (amounts) => (Math.min(...amounts) === Math.max(...amounts) ? fmt.money(amounts[0]) : `${fmt.money(Math.min(...amounts))}–${fmt.money(Math.max(...amounts))}`);
    const work = world.work;
    const team = Math.round(work.payment * work.leader_share);
    /** What each occupation without a salary earns, in words; nobody is paid for its time. */
    const earns = {
      programmer: `${fmt.money(work.payment - team)} of a client's ${fmt.money(work.payment)} for a task of its own accepted`,
      "team-leader": `${fmt.money(team)} of a task a programmer has accepted, the whole of its own`,
      shopkeeper: "what the Store sells for, paying the supplier for its orders",
      chef: "what the dishes sell for, paying for the kitchen's ingredients",
      doctor: "the fees",
    };
    const item = (label, value) => h("li", {}, h("span", { class: "muted" }, label), " ", h("b", {}, value));
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
          world.occupations.map((occupation) => {
            const who = world.residents.filter((r) => r.occupation === occupation.id).map((r) => r.name);
            const pay = occupation.salary ? `a salary of ${fmt.money(occupation.salary)} a day from the treasury` : (earns[occupation.id] ?? "no salary");
            return item(`${occupation.title}${who.length ? ` (${who.join(", ")})` : ""} earns`, pay);
          }),
          item("the treasury starts with", fmt.money(world.treasury.start)),
          item("the tax", `${fmt.pct(world.tax)} of every payment for work, withheld into the treasury as it is received`),
          item("tasks come in", `about ${fmt.num(work.tasks_a_day, 0)} a day, ${work.arrive_from}–${work.arrive_until}`),
          item("a task not accepted is withdrawn", `${fmt.plural(work.expiry_days, "day")} after the day it came in`),
          item("hand-ins per task", `${work.acceptance_runs} a day`),
          item("rent for a room", `${range(world.places.filter((p) => p.kind === "home").map((p) => p.rent))} a day, to the treasury at midnight from what a purse holds above ${fmt.money(world.treasury.spares)}, the rest owed`),
          item("for sale at the Store", `${fmt.plural(world.goods.length, "good")}, ${range(world.goods.map((g) => g.price))}`),
          world.dishes.length ? item(`on ${restaurant.name}'s menu`, `${fmt.plural(world.dishes.length, "dish", "dishes")}, ${range(world.dishes.map((d) => d.price))}`) : null,
          item("the Hospital charges", `${fmt.money(world.hospital.examination)} an examination, ${fmt.money(world.hospital.treatment)} a treatment, which restores ${fmt.int(world.hospital.restores)} health`),
          item("a conversation ends", `after ${world.social.silence_minutes} minutes of silence`),
          Object.entries(world.day).map(([name, clock]) => item(DAY_HOURS[name] ?? name.replaceAll("_", " "), dayHour(name, clock))),
        ),
      ),
      first ? h("div", { class: "cond-changes" }, h("p", { class: "eyebrow" }, "As a resident reads them"), h("details", { class: "rules-text fold" }, h("summary", {}, `The rules ${first.name} was told`), h("pre", {}, first.rules))) : null,
    );
  }

  function keyFigures() {
    const head = progressDoc.daily;
    const all = (field) => sum(head, field);
    const books = measures.town.at(-1);
    const cooked = everywhere("cook").reduce((a, [, m]) => a + m.portions, 0);
    const kitchen = everywhere((m) => boughtAtCounter(m) && m.target === LARDER).length;
    return h(
      "div",
      { class: "stats" },
      stat("The treasury", fmt.money(books ? books.treasury : world.treasury.start), books ? `at the checkpoint of day ${books.day} · started at ${fmt.money(world.treasury.start)}${books.arrears ? ` · ${fmt.money(books.arrears)} of rent owed to it` : ""}` : "at the start; read at each checkpoint"),
      stat("Tasks accepted", fmt.int(all("accepted")), `${fmt.int(all("arrived"))} came in · ${fmt.int(all("claims"))} claimed · ${fmt.int(all("assigned"))} assigned · ${fmt.int(all("withdrawn"))} withdrawn`),
      stat("Sales at the Store", fmt.int(all("sales")), `${fmt.int(kitchen)} for the kitchen`),
      stat("Dishes served", fmt.int(all("dishes")), `${fmt.plural(cooked, "portion")} cooked`),
      stat("Patients seen", fmt.int(all("examinations") + all("treatments")), `${fmt.plural(all("examinations"), "examination")} · ${fmt.plural(all("treatments"), "treatment")}`),
      stat("Things said", fmt.int(all("speeches")), `${fmt.int(all("messages"))} written · ${fmt.plural(all("gifts"), "gift")}`),
      stat("Journals written", fmt.int(all("journals")), `at bedtime · ${fmt.int(all("forced_sleeps"))} forced sleeps`),
      all("illnesses") || all("bedridden") ? stat("Fell ill", fmt.int(all("illnesses")), `${fmt.int(all("bedridden"))} taken to bed`, all("bedridden") ? "critical" : "") : null,
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
      h("figcaption", {}, h("h3", {}, "Files rewritten, night by night"), h("p", { class: "note" }, "What each resident's files changed between one checkpoint and the next: its own notes in memory, its skills, its journal, its background. A marked night opens that version."), key),
      h("div", { class: "table-wrap" }, h("table", { class: "evo-grid" }, h("thead", {}, header), h("tbody", {}, body))),
    );
  }

  function matrix() {
    const options = {
      said: ["Things said", (e) => e.said || null, fmt.int, null],
      minutes: ["Minutes together", (e) => (e.minutes ? Math.round(e.minutes) : null), fmt.int, null],
      money: ["Money handed over", (e) => e.money || null, fmt.int, null],
      served: ["Served at work", (e) => e.served || null, fmt.int, null],
    };
    const [, value, format, fixed] = options[view.matrix] ?? options.said;
    const totals = new Map();
    for (const edge of measures.graph) {
      const key = `${edge.source}>${edge.target}`;
      const t = totals.get(key) ?? { minutes: 0, said: 0, said_private: 0, gifts: 0, money: 0, served: 0 };
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
              const detail = edge ? `${from} → ${to}: ${fmt.int(Math.round(edge.minutes))} min in conversation, ${edge.said} things said (${edge.said_private} privately), ${fmt.money(edge.money)} handed over, served ${fmt.plural(edge.served, "time")}` : `${from} had nothing to do with ${to}`;
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

  /** The Store's shelves at the latest moment: every good with what it does, what the supplier charges, its price then and at the start, the units in stock and on order. */
  function shelves() {
    const now = shopsAt(data, data.now);
    const rows = world.goods.map((good) => [
      h("b", {}, goodName(good)),
      goodEffect(good),
      fmt.money(good.wholesale),
      now.prices[good.id] === good.price ? fmt.money(good.price) : `${fmt.money(now.prices[good.id])} (was ${fmt.money(good.price)})`,
      fmt.int(now.stock[good.id] ?? 0),
      now.onOrder[good.id] ? fmt.int(now.onOrder[good.id]) : "",
    ]);
    return plain(`${store.name[0].toUpperCase()}${store.name.slice(1)} now`, "Every good of the supplier's catalogue: what it does, what the supplier charges for it, the counter's price as the shopkeeper last set it, and the units in stock and on order at the latest moment.", table(["Good", "What it does", "Wholesale", "Price", "In stock", "On order"], rows));
  }

  /** The menu at the latest moment: each dish with what it is cooked from, its price and the portions ready, and the kitchen's stock. */
  function menu() {
    const now = shopsAt(data, data.now);
    const larder = Object.entries(now.larder).map(([id, units]) => amountOf(world, id, units));
    return plain(
      `${restaurant.name[0].toUpperCase()}${restaurant.name.slice(1)}'s menu now`,
      `Each dish is a day's food, cooked from the kitchen's stock and eaten where it is bought; what is not sold by midnight is gone. The kitchen holds ${larder.join(", ") || "nothing"}.`,
      h("div", { class: "catalogue" }, world.dishes.map((dish) => dishCard(world, dish, { price: now.menu[dish.id], portions: now.portions[dish.id] ?? 0 }))),
    );
  }

  /** What everyone has at the latest moment, money first, and how often each good was bought for oneself. */
  function belongings() {
    const bought = new Map(world.goods.map((good) => [good.id, cast.names.map((name) => laneOf(name).markers.filter((m) => boughtAtCounter(m) && m.target === name && m.item === good.id).reduce((a, m) => a + m.units, 0))]));
    return [
      plain("What everyone has now", "As of the latest moment, money first. A stock of food is eaten as its owner gets hungry; every move in and out of it is counted.", h("ul", { class: "belongings" }, cast.names.map((name) => h("li", {}, cast.chip(name, href(sibling(route, "person", { agent: name }))), inventory(world, thingsAt(laneOf(name), data.now), { compact: true, money: purseAt(laneOf(name), data.now) }))))),
      plain(
        "Bought over the run",
        "How many units of each good every resident has bought for itself at the counter so far; what the chef bought for the kitchen is not the chef's.",
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

  /** The Office's tasks, newest first: when each came in, who held it, and what came of it. */
  function tasks() {
    const rows = [...data.tasks].reverse().map((task) => {
      const holders = task.holders.filter(([, holder]) => holder).map(([t, holder, by]) => `${holder}${by ? ` (from ${by})` : ""} at ${hhmm(secondOfDay(t))}`);
      const held = holderAt(task, data.now);
      const outcome = task.accepted !== null ? `accepted, ${moment(task.accepted)}, handed in by ${task.by}` : task.withdrawn !== null ? `withdrawn, ${moment(task.withdrawn)}` : held ? `open, held by ${held.holder}` : "open, held by nobody";
      return [h("b", {}, String(task.task)), task.repo, moment(task.arrived), cast.mention(holders.join(" → ") || "nobody"), cast.mention(outcome)];
    });
    return plain("The Office's tasks", "Every client's task that came in, newest first: when, who held it (from whom, when the team leader gave it) and what came of it.", rows.length ? table(["Task", "Repository", "Came in", "Held by", "Outcome"], rows) : emptyState("No task has come in yet.", `Tasks come in at ${office.name} between ${world.work.arrive_from} and ${world.work.arrive_until}.`));
  }

  /** The treasury's books at the last checkpoint: the rent each resident owes it and the salary it owes. */
  function owing() {
    const books = measures.town.at(-1);
    if (!books) return plain("Who owes what", null, emptyState("No day's checkpoint has been saved yet.", "The treasury's books are read at each checkpoint."));
    const rows = measures.rows.filter((row) => row.day === books.day && (row.arrears || row.salary_owed)).map((row) => [cast.mention(row.resident), row.arrears ? fmt.money(row.arrears) : "", row.salary_owed ? fmt.money(row.salary_owed) : ""]);
    return plain("Who owes what", `At the checkpoint of day ${books.day}: the rent and charges a purse could not spare, owed to the treasury and taken at a later midnight, and the salary the treasury could not pay, owed to the resident and paid at a later one.`, rows.length ? table(["Resident", "Owes the treasury", "The treasury owes"], rows) : h("p", { class: "muted small-text" }, "Nothing is owed either way."));
  }

  /** The mayor's grants from the treasury, newest first: when, by whom, to whom, how much and why. */
  function grants() {
    const made = everywhere("grant").reverse();
    const rows = made.map(([name, m]) => [moment(m.t), cast.mention(name), cast.mention(m.to), fmt.money(m.amount), `“${m.reason}”`]);
    return plain("Grants", "What the mayor granted from the treasury, newest first, with the reason given.", rows.length ? table(["When", "By", "To", "Amount", "Reason"], rows) : h("p", { class: "muted small-text" }, "Nothing granted yet."));
  }

  /** The mayor's announcements, newest first, each with its hour. */
  function announcements() {
    const said = everywhere("announcement").reverse();
    return plain("Announcements", "What the mayor announced at the Town Hall, told to every resident at once or on waking, newest first.", said.length ? h("ul", { class: "outcomes" }, said.map(([name, m]) => h("li", {}, h("span", { class: "muted" }, `${dateOf(data.start_date, m.t)}, ${moment(m.t)}, ${name}: `), `“${m.text}”`))) : h("p", { class: "muted small-text" }, "Nothing announced yet."));
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
      const taken = (lane, i) => count("claim")(lane, i) + count("assign")(lane, i);
      const arrived = ownPoints("task_arrived");
      // What a resident did for others at its work on a lived day: its own tasks accepted, and the
      // times it served another (a sale, a dish, a patient), as the social graph counts them.
      const served = (lane, i, day) => count("service", (m) => m.for === "task")(lane, i) + measures.graph.filter((edge) => edge.day === day.day && edge.source === lane.name).reduce((a, edge) => a + edge.served, 0);
      return [
        h("p", { class: "note section-note" }, `Clients' tasks come in at ${office.name} through the working day, about ${fmt.num(world.work.tasks_a_day, 0)} a day; a programmer takes one at a time, or the team leader gives it, and hands it in for the client's checks, and the client pays ${fmt.money(world.work.payment)} when they pass, shared between whoever handed it in and the team leader. Nobody is paid for its time: everyone works at its own workplace, and the shopkeeper, the chef and the doctor keep what their customers and patients pay. ${fmt.plural(arrived.reduce((a, [, n]) => a + n, 0), "task")} came in so far, ${fmt.int(total(accepted))} accepted.`),
        h(
          "div",
          { class: "figures" },
          dayFigure({
            title: "The Office's tasks",
            note: "Tasks handed in each day, accepted or not, against those that came in, were taken or given, and were withdrawn.",
            stacks: [
              { key: "accepted", label: "accepted", color: "var(--good)", values: townValues(accepted) },
              { key: "rejected", label: "not accepted", color: "var(--serious)", values: townValues(rejected) },
            ],
            lines: [
              { key: "arrived", label: "came in", color: "var(--ink)", points: arrived },
              { key: "taken", label: "claimed or given", color: "var(--ink-2)", points: townPoints(taken) },
              { key: "withdrawn", label: "withdrawn", color: "var(--critical)", points: ownPoints("task_withdrawn") },
            ],
            legend: swatchLegend([["accepted", "var(--good)"], ["not accepted", "var(--serious)"], ["came in", "var(--ink)", "line"], ["claimed or given", "var(--ink-2)", "line"], ["withdrawn", "var(--critical)", "line"]]),
          }),
          dayFigure({ title: "Hours at work", note: "Hours a resident spent at work at its workplace each day, on average over the residents.", lines: [{ key: "hours", label: "mean hours at work", color: "var(--ink-2)", points: townPoints(workHours).map(([day, hours]) => [day, hours / cast.names.length]) }], format: (v) => fmt.num(v, 1) }),
          agentFigure({ title: "Hours at work", note: "Each resident's hours at work at its workplace per day.", points: residentPoints(workHours), format: (v) => fmt.num(v, 1), zero: true }),
          agentFigure({ title: "Served at work", note: "What each resident did for others at its work per day: a task of its own accepted, a sale at the counter, a dish served, a patient seen.", points: residentPoints(served), zero: true }),
          tasks(),
        ),
      ];
    },
    money() {
      const books = saved();
      const closed = data.days.filter((day) => books.has(day.day));
      const points = (field) => closed.map((day) => [day.day, books.get(day.day)[field]]);
      const ledger = (side, kinds) => kinds.map(([kind, label, color]) => ({ key: kind, label, color, values: new Map(points(`${side}_${kind}`)) }));
      /** A business's books over the closed days: each of `kinds` a line, `[label, field of the town's days, colour]`. */
      const booksOf = (title, note, kinds) => dayFigure({ title, note, lines: kinds.map(([label, field, color]) => ({ key: field, label, color, points: points(field) })), legend: swatchLegend(kinds.map(([label, , color]) => [label, color, "line"])), zero: true });
      /** What a lane's purse took in or gave out on its lived day `i` by the parts of `moneyMoved` given, from every lane's markers. */
      const moved = (parts) => (lane, i) => data.residents.reduce((a, other) => a + markersIn(other, i, () => true).reduce((b, m) => b + moneyMoved(m, other.name).reduce((c, [who, change, part]) => c + (who === lane.name && parts.includes(part) ? change : 0), 0), 0), 0);
      const rent = amount("settlement", "rent_paid");
      const food = bought(isFood);
      const goods = bought((m) => !isFood(m));
      const fees = (lane, i) => data.residents.reduce((a, other) => a + markersIn(other, i, "examination").concat(markersIn(other, i, "treatment")).filter((m) => m.patient === lane.name).reduce((b, m) => b + m.fee, 0), 0);
      const salaried = world.occupations.filter((occupation) => occupation.salary).map((occupation) => `${occupation.title}'s salary of ${fmt.money(occupation.salary)} a day`);
      const team = Math.round(world.work.payment * world.work.leader_share);
      return [
        h("p", { class: "note section-note" }, `Money is held by the residents and by the town's treasury, and by nothing else. It comes into the town only when a client pays ${fmt.money(world.work.payment)} for a task accepted, ${fmt.money(team)} of it to the team leader and the rest to whoever handed it in, and leaves it only when the shopkeeper pays the supplier for the Store's orders; everything else passes between purses and the treasury. The Store's sales are the shopkeeper's, the dishes the chef's and the fees the doctor's, and each pays for what its business buys. ${fmt.pct(world.tax)} of every payment for work is withheld into the treasury as it is received; at midnight the treasury takes the rent from what a purse holds above ${fmt.money(world.treasury.spares)}, the rest owed, and pays ${salaried.join(" and ") || "no salary"} as far as it holds the money; the mayor grants from it at will. The residents started with ${world.residents.map((r) => `${r.name} ${fmt.money(r.purse)}`).join(", ")}, the treasury with ${fmt.money(world.treasury.start)}.`),
        h(
          "div",
          { class: "figures" },
          closed.length
            ? [
                dayFigure({ title: "The treasury", note: `Its balance at each day's checkpoint; it started at ${fmt.money(world.treasury.start)}.`, lines: [{ key: "balance", label: "balance", color: "var(--ink)", points: points("treasury") }], zero: true }),
                dayFigure({ title: "What the treasury took in", note: "By kind, on the calendar day each checkpoint's midnight closed: the tax withheld from every payment for work, and the rent and daily charges taken at midnight, arrears recovered among them.", stacks: ledger("taken", TAKEN), legend: swatchLegend(TAKEN.map(([, label, color]) => [label, color])) }),
                dayFigure({ title: "What the treasury paid out", note: "By kind, on the same days: the salary, and the mayor's grants, listed with their reasons below.", stacks: ledger("paid", PAID), legend: swatchLegend(PAID.map(([, label, color]) => [label, color])) }),
                dayFigure({ title: "What is owed", note: "At each day's checkpoint: the rent and charges the residents' purses could not spare, owed to the treasury, and the salary the treasury could not pay.", lines: [{ key: "arrears", label: "owed to the treasury", color: "var(--serious)", points: points("arrears") }, { key: "salary_owed", label: "owed by the treasury", color: "var(--o2)", points: points("salary_owed") }], legend: swatchLegend([["owed to the treasury", "var(--serious)", "line"], ["owed by the treasury", "var(--o2)", "line"]]), zero: true }),
              ]
            : plain("The treasury", null, emptyState("No day's checkpoint has been saved yet.", `The treasury is read at each checkpoint, the first at ${world.day.checkpoint} after the first day; it started at ${fmt.money(world.treasury.start)}.`), false),
          grants(),
          owing(),
          closed.length
            ? [
                booksOf(cap(store.name), "What customers paid at the counter each day, the kitchen's purchases among them, before the tax, against what the shopkeeper paid the supplier for the orders.", [["sales", "store_takings", "var(--good)"], ["orders", "supplier", "var(--serious)"]]),
                booksOf(cap(restaurant.name), "What diners paid for the dishes each day, before the tax, against what the chef paid at the counter for the kitchen's ingredients.", [["dishes", "kitchen_takings", "var(--good)"], ["ingredients", "kitchen_costs", "var(--serious)"]]),
                booksOf(cap(hospital.name), "What patients paid in fees each day, before the tax.", [["fees", "surgery_takings", "var(--good)"]]),
              ]
            : null,
          agentFigure({ title: "Money in hand", note: "Each resident's money at the end of each day, or now for the day in progress.", points: residentPoints((lane, i, day) => purseAt(lane, endOf(day))), zero: true }),
          agentFigure({ title: "Earned", note: "What each resident was paid for its work each day, after the tax: its shares of the clients' payments, and what its customers and patients paid it.", points: residentPoints(moved(["share", "takings"])), zero: true }),
          dayFigure({
            title: "What the residents spent",
            note: "The rent and daily charges the treasury took at midnight, food (at the counter and dishes), other goods and the Hospital's fees, per day; what a business bought is in its books above.",
            stacks: [
              { key: "rent", label: "rent and charges", color: "var(--o5)", values: townValues(rent) },
              { key: "food", label: "food", color: "var(--o3)", values: townValues(food) },
              { key: "goods", label: "other goods", color: "var(--o2)", values: townValues(goods) },
              { key: "fees", label: "fees", color: "var(--o1)", values: townValues(fees) },
            ],
            legend: swatchLegend([["rent and charges", "var(--o5)"], ["food", "var(--o3)"], ["other goods", "var(--o2)"], ["fees", "var(--o1)"]]),
          }),
        ),
      ];
    },
    trade() {
      const units = (keep) => (lane, i) => markersIn(lane, i, boughtAtCounter).filter(keep).reduce((a, m) => a + m.units, 0);
      return [
        h("p", { class: "note section-note" }, `${store.name[0].toUpperCase()}${store.name.slice(1)} sells the supplier's goods while the shopkeeper is at work there, at prices the shopkeeper sets, from what it orders, which comes the next morning. ${restaurant.name[0].toUpperCase()}${restaurant.name.slice(1)}'s chef buys ingredients for the kitchen at the counter, paying for them, cooks dishes from them and serves them while at work. ${fmt.plural(sum(progressDoc.daily, "sales"), "sale")} and ${fmt.plural(sum(progressDoc.daily, "dishes"), "dish", "dishes")} served so far.`),
        h(
          "div",
          { class: "figures" },
          dayFigure({
            title: "Sold and ordered",
            note: "Units sold at the counter each day, to residents and to the kitchen, against the units the shopkeeper ordered.",
            stacks: [
              { key: "residents", label: "to residents", color: "var(--o3)", values: townValues(units((m) => m.target !== LARDER)) },
              { key: "kitchen", label: "to the kitchen", color: "var(--o1)", values: townValues(units((m) => m.target === LARDER)) },
            ],
            lines: [{ key: "ordered", label: "ordered", color: "var(--ink)", points: townPoints(amount("order", "quantity")) }],
            legend: swatchLegend([["to residents", "var(--o3)"], ["to the kitchen", "var(--o1)"], ["ordered", "var(--ink)", "line"]]),
          }),
          dayFigure({
            title: "Cooked and served",
            note: "Portions the chef cooked each day, and dishes served, bought or the chef's unpaid.",
            lines: [
              { key: "cooked", label: "portions cooked", color: "var(--o3)", points: townPoints(amount("cook", "portions")) },
              { key: "served", label: "dishes served", color: "var(--ink)", points: townPoints(count(dishServed)) },
            ],
            legend: swatchLegend([["portions cooked", "var(--o3)", "line"], ["dishes served", "var(--ink)", "line"]]),
          }),
          shelves(),
          menu(),
          belongings(),
        ),
      ];
    },
    body() {
      const starving = (lane, i) => (midnightOf(lane, i)?.night.starving !== undefined ? 1 : 0);
      const exhausted = (lane, i) => (midnightOf(lane, i)?.night.exhausted !== undefined ? 1 : 0);
      const unfed = (lane, i) => (midnightOf(lane, i) && !midnightOf(lane, i).nourishment ? 1 : 0);
      const fees = shopsAt(data, data.now).fees;
      return [
        h("p", { class: "note section-note" }, `Each resident's body has three needs from 0 to 100, which it reads in bands of plain words: food in the body, which eating restores; energy, spent awake, at work and on the road and restored by sleep up to its health; and health, worn at midnight by a day ended starving or exhausted, by a home of little comfort and by illness, mended by days of rest and by the doctor's treatment. Illness comes by chance at midnight; a resident whose health runs out takes to its bed until treated. ${hospital.name[0].toUpperCase()}${hospital.name.slice(1)} charges ${fmt.money(fees.examination)} an examination and ${fmt.money(fees.treatment)} a treatment now. ${fmt.plural(total(unfed), "resident-day")} with nothing eaten, ${fmt.int(total(starving))} starving at midnight, ${fmt.int(sum(progressDoc.daily, "illnesses"))} fallen ill, ${fmt.int(sum(progressDoc.daily, "bedridden"))} taken to bed so far.`),
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
          dayFigure({
            title: "Illness and the Hospital",
            note: "Examinations and treatments each day, against the residents who fell ill and those who took to bed.",
            stacks: [
              { key: "examinations", label: "examinations", color: "var(--o2)", values: townValues(count("examination")) },
              { key: "treatments", label: "treatments", color: "var(--o4)", values: townValues(count("treatment")) },
            ],
            lines: [
              { key: "ill", label: "fell ill", color: "var(--serious)", points: townPoints(count("illness")) },
              { key: "bed", label: "took to bed", color: "var(--critical)", points: townPoints(count("bedridden")) },
            ],
            legend: swatchLegend([["examinations", "var(--o2)"], ["treatments", "var(--o4)"], ["fell ill", "var(--serious)", "line"], ["took to bed", "var(--critical)", "line"]]),
          }),
        ),
      ];
    },
    social() {
      const said = count("speech");
      return [
        h("p", { class: "note section-note" }, `Residents talk only with those at the same place, write to other phone owners from anywhere, give one another money, things and food on their own terms, and serve one another at their work. ${fmt.plural(total(said), "thing")} said, ${fmt.int(total(count("message")))} written, ${fmt.plural(total(count(handedOver)), "gift")} given and ${fmt.money(total(amount(handedOver, "money")))} of money among them, ${fmt.int(total(count("announcement")))} announcements so far.`),
        h(
          "div",
          { class: "figures" },
          agentFigure({ title: "Things said", note: "To everyone present or to someone by name, per day.", points: residentPoints(said), zero: true }),
          dayFigure({
            title: "Gifts and messages",
            note: "Gifts of money or things, and messages written from one phone to another, per day.",
            stacks: [{ key: "gifts", label: "gifts", color: "var(--o1)", values: townValues(count(handedOver)) }],
            lines: [{ key: "messages", label: "messages", color: "var(--ink-2)", points: townPoints(count("message")) }],
            legend: swatchLegend([["gifts", "var(--o1)"], ["messages", "var(--ink-2)", "line"]]),
          }),
          announcements(),
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
        h("p", { class: "note section-note" }, `${fmt.int(sum(rows, "requests"))} model requests over the closed days, ${fmt.compact(sum(rows, "prompt_tokens") + sum(rows, "completion_tokens"))} tokens; ${fmt.int(sum(rows, "lapses"))} lapses, ${fmt.int(sum(rows, "compactions"))} compactions.`),
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
