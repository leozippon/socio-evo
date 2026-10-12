// Character in the town: what the residents did in the town's four dilemmas, how they chose one
// another as partners, and how often their own words speak of the machinery behind the town,
// from traits.json. Every share shows what it is a share of; with few cases a share says little,
// and the denominator is how a reader tells.

import { DayChart, figure } from "../charts.js";
import { emptyState, fmt, h, s, term } from "../dom.js";
import { COUNTS, SELECTION, SHARES, TRAITS } from "../measures.js";

const value = (name, v) => (v === null || v === undefined ? "–" : SHARES[name]?.mean ? fmt.num(v, 2) : fmt.pct(v));
const count = (n) => (Number.isInteger(n) ? fmt.int(n) : fmt.num(n, 2));

/**
 * The section: `traits` as published (null for a run of the first town), the run's `measures`
 * for the marks residents gave, `state.window` the window shown, `onWindow(name)` to change it,
 * and `into` the list that collects charts to destroy later.
 */
export function characterSection({ traits, measures, cast, state, onWindow, into }) {
  if (!traits)
    return h(
      "div",
      { class: "card" },
      emptyState("This run has no measures of character in the town.", "It was recorded in the first town, before jobs had parts, declarations and askings, which the measures need. Its held-out probes are under Held-out traits."),
    );
  if (!traits.windows.length) return h("div", { class: "card" }, emptyState("No day has begun yet."));
  const window = traits.windows.find((found) => found.name === state.window) ?? traits.windows[0];
  const agents = new Map(window.agents.map((row) => [row.agent, row]));
  const days = traits.town.filter((row) => row.day >= window.first_day && row.day <= window.last_day);
  const span = window.first_day === window.last_day ? `day ${window.first_day}` : `days ${window.first_day}–${window.last_day}`;
  const windowName = (found) => (found.name === "run" ? "Whole run" : `Phase ${found.name.slice(6)}`);
  const ctx = { cast, agents, town: window.town, days, into, range: [window.first_day, Math.max(window.first_day, window.last_day)] };

  const cards = TRAITS.map((trait) => {
    const rows = [...(trait.shares ?? []).map((name) => shareRow(name, ctx)), ...(trait.counts ?? []).map((name) => countRow(name, ctx))];
    return figure({ title: trait.title, note: trait.dilemma, chart: { el: h("div", { class: "trait-rows" }, rows), table: () => residentTable(trait.shares ?? [], trait.counts ?? [], ctx) } });
  });
  const machinery = ["thoughts_machinery_share", "diaries_machinery_share", "reflections_machinery_share"];
  return [
    h(
      "div",
      { class: "spread section-note" },
      h("p", { class: "note" }, `What residents did in the town's dilemmas, ${span}. Each share says what it is a share of; early in a run, and for one resident, the numbers are small. Tap a term for its definition, a badge for that resident's count.`),
      traits.windows.length > 1
        ? h(
            "div",
            { class: "seg", role: "group", "aria-label": "Span of days" },
            traits.windows.map((found) => h("button", { type: "button", "aria-pressed": String(found === window), title: `Days ${found.first_day}–${found.last_day}`, onclick: () => onWindow(found.name) }, windowName(found), h("span", { class: "muted" }, ` ${found.first_day}–${found.last_day}`))),
          )
        : null,
    ),
    h("div", { class: "figures" }, cards),
    h("div", { class: "figures section" }, selectionFigure(window, traits, measures, ctx)),
    h("div", { class: "figures section" }, figure({ title: "Speaking of machinery", note: "How often residents' own words speak of the machinery behind the town — rounds, prompts, the system — instead of the town itself.", chart: { el: h("div", { class: "trait-rows" }, machinery.map((name) => shareRow(name, ctx))), table: () => residentTable(machinery, [], ctx) }, wide: true })),
  ];
}

/** One share: the town's value and its count, each resident on a strip, and the town over days. */
function shareRow(name, ctx) {
  const def = SHARES[name];
  const town = ctx.town;
  const k = town.counts[def.num];
  const n = town.counts[def.den];
  const items = ctx.cast.names.map((agent) => {
    const row = ctx.agents.get(agent);
    return { agent, n: row?.counts[def.den] ?? 0, k: row?.counts[def.num] ?? 0, v: row?.shares[name] ?? null };
  });
  const say = (item) => (def.mean ? `${item.agent}: ${value(name, item.v)}, mean over ${fmt.plural(item.n, "hand-in")}` : `${item.agent}: ${count(item.k)} of ${fmt.int(item.n)}, ${value(name, item.v)}`);
  // The town so far on each day of the window: running counts, so a day with no case keeps the
  // share it had.
  let kk = 0;
  let nn = 0;
  const notes = new Map();
  const points = ctx.days.map((row) => {
    kk += row.counts[def.num];
    nn += row.counts[def.den];
    notes.set(row.day, def.mean ? `over ${fmt.int(nn)}` : `${count(kk)} of ${fmt.int(nn)}`);
    return [row.day, nn ? kk / nn : null];
  });
  const chart = nn ? new DayChart({ days: ctx.range, lines: [{ key: name, label: "town so far", color: "var(--ink-2)", points, notes }], y: { min: 0, max: 1, format: (v) => value(name, v) }, height: 54, dots: points.filter((p) => p[1] !== null).length < 3, label: `${def.label}, the town so far by day` }) : null;
  if (chart) ctx.into.push(chart);
  return h(
    "div",
    { class: "measure" },
    h(
      "div",
      { class: "measure-head" },
      h("span", { class: "measure-name" }, term(def.label, def.def)),
      h("span", { class: "measure-value" }, value(name, town.shares[name])),
      h("span", { class: "measure-count" }, def.mean ? `mean over ${fmt.plural(n, "hand-in")} accepted` : `${count(k)} of ${fmt.int(n)} ${def.of}`),
    ),
    h("div", { class: "measure-body" }, strip(items, { max: 1, say, label: (v) => value(name, v), cast: ctx.cast }), h("div", { class: "measure-trend" }, chart ? chart.el : h("p", { class: "muted small-text" }, "No case in these days."))),
  );
}

/** One count: the town's total and rate, each resident on a strip, and the town day by day. */
function countRow(name, ctx) {
  const def = COUNTS[name];
  const town = ctx.town;
  const total = town.counts[name];
  const rate = def.rate ? town.per_resident_day?.[def.rate] : null;
  const items = ctx.cast.names.map((agent) => ({ agent, n: 1, v: ctx.agents.get(agent)?.counts[name] ?? 0 }));
  const most = Math.max(1, ...items.map((item) => item.v));
  const chart = total ? new DayChart({ days: ctx.range, stacks: [{ key: name, label: `${def.unit}s`, color: "var(--o3)", values: new Map(ctx.days.map((row) => [row.day, row.counts[name]])) }], y: { min: 0, integer: true, format: fmt.int }, height: 54, label: `${def.label}, day by day` }) : null;
  if (chart) ctx.into.push(chart);
  const gifts = name === "crowns_given" ? town.counts.gifts_given : null;
  return h(
    "div",
    { class: "measure" },
    h(
      "div",
      { class: "measure-head" },
      h("span", { class: "measure-name" }, term(def.label, def.def)),
      h("span", { class: "measure-value" }, fmt.int(total)),
      h("span", { class: "measure-count" }, [gifts !== null ? `in ${fmt.plural(gifts, "gift")}` : fmt.plural(total, def.unit).replace(/^\S+ /, ""), rate !== null && rate !== undefined ? ` · ${fmt.num(rate, 2)} per resident-day over ${fmt.int(town.resident_days)}` : ""].join("")),
    ),
    h("div", { class: "measure-body" }, strip(items, { max: most, say: (item) => `${item.agent}: ${fmt.plural(item.v, def.unit)}`, label: (v) => fmt.int(v), cast: ctx.cast }), h("div", { class: "measure-trend" }, chart ? chart.el : h("p", { class: "muted small-text" }, "None in these days."))),
  );
}

/**
 * Residents on a strip from 0 to `max`, each by its badge; those with no case are named beside
 * it rather than put at zero. A badge reads out its numbers when pointed at or tapped.
 */
function strip(items, { max, say, label, cast }) {
  const placed = items.filter((item) => item.n > 0 && item.v !== null);
  const none = items.filter((item) => !(item.n > 0 && item.v !== null));
  const rows = [];
  const dots = placed
    .sort((a, b) => a.v - b.v)
    .map((item) => {
      const x = Math.max(0, Math.min(1, item.v / max));
      let row = 0;
      while (rows[row]?.some((other) => Math.abs(other - x) < 0.07)) row += 1;
      (rows[row] ??= []).push(x);
      return h(
        "button",
        { type: "button", class: "strip-dot", "data-agent": item.agent, style: { left: `${(x * 100).toFixed(2)}%`, bottom: `${row * 19 + 2}px` }, "aria-label": say(item), onpointerenter: () => (readout.textContent = say(item)), onfocus: () => (readout.textContent = say(item)), onclick: () => (readout.textContent = say(item)) },
        cast.badge(item.agent, 18),
      );
    });
  const readout = h("div", { class: "strip-readout" }, placed.length ? `${placed.length} of ${items.length} residents with cases` : "No resident had a case yet.");
  return h(
    "div",
    { class: "strip" },
    h("div", { class: "strip-plot", style: { height: `${Math.max(1, rows.length) * 19 + 16}px` } }, h("div", { class: "strip-axis" }, h("span", {}, label(0)), h("span", {}, label(max))), dots),
    readout,
    none.length && placed.length ? h("p", { class: "strip-none" }, "No cases: ", cast.mention(none.map((item) => item.agent).join(", "))) : null,
  );
}

/** The numbers behind a card, one row per resident: each share as count of cases, each count. */
function residentTable(shares, counts, ctx) {
  const cell = (row, name) => {
    const def = SHARES[name];
    const n = row?.counts[def.den] ?? 0;
    return n ? `${value(name, row.shares[name])} (${def.mean ? `over ${n}` : `${count(row.counts[def.num])}/${n}`})` : "–";
  };
  const rows = [...ctx.cast.names.map((agent) => [ctx.cast.chip(agent), ctx.agents.get(agent)]), [h("b", {}, "Town"), ctx.town]];
  return h(
    "div",
    { class: "table-wrap" },
    h(
      "table",
      { class: "data" },
      h("thead", {}, h("tr", {}, h("th", { class: "sticky-col" }, "Resident"), shares.map((name) => h("th", {}, SHARES[name].label)), counts.map((name) => h("th", {}, COUNTS[name].label)))),
      h("tbody", {}, rows.map(([who, row]) => h("tr", {}, h("th", { scope: "row", class: "sticky-col" }, who), shares.map((name) => h("td", {}, cell(row, name))), counts.map((name) => h("td", {}, fmt.int(row?.counts[name] ?? 0)))))),
    ),
  );
}

/** Choosing partners: who is asked and who passed over, who asked whom, and marks against askings. */
function selectionFigure(window, traits, measures, ctx) {
  const { cast, agents } = ctx;
  const sel = window.town.selection ?? {};
  const pairs = traits.pairs.filter((row) => row.day >= window.first_day && row.day <= window.last_day);
  const asked = (agent) => agents.get(agent)?.counts ?? {};
  const askedAny = cast.names.some((agent) => asked(agent).asked);
  const stat = (name, v, digits = 2) => h("div", { class: "stat" }, h("div", { class: "stat-label" }, term(SELECTION[name].short, SELECTION[name].def)), h("div", { class: "stat-value" }, v === null || v === undefined ? "–" : fmt.num(v, digits)), h("div", { class: "stat-sub" }, v === null || v === undefined ? (askedAny ? "not defined for this span" : "nobody asked anybody") : name === "asked_by_gini" ? "0 is everyone asked alike" : name === "blemish_asked_rho" ? "negative: the blemished asked less" : "mark difference, 1 to 5 scale"));
  const most = Math.max(1, ...cast.names.map((agent) => asked(agent).asked_by ?? 0));
  const order = [...cast.names].sort((a, b) => (asked(b).asked_by ?? 0) - (asked(a).asked_by ?? 0));
  const table = h(
    "div",
    { class: "table-wrap" },
    h(
      "table",
      { class: "data chosen-table" },
      h(
        "thead",
        {},
        h(
          "tr",
          {},
          h("th", { class: "sticky-col" }, "Resident"),
          h("th", { class: "bar-col" }, term("Asked by others", "Askings the resident received: a job for two proposed to it by name. The dark part of the bar it took up, the hatched part it let lapse; the rest were withdrawn or the job went elsewhere.")),
          h("th", {}, term("Asked others", "Askings the resident made: a job for two proposed to a named neighbour.")),
          h("th", {}, term("Name down", "Times the resident put its name down for a job for two, for the clerk to pair by lot.")),
          h("th", {}, term("Paired by lot", "Jobs for two the clerk gave the resident by lot.")),
          h("th", {}, term("Jobs for two", "Jobs for two the resident took, by asking, by being asked or by lot; in brackets, those with a partner it had worked with before.")),
        ),
      ),
      h(
        "tbody",
        {},
        order.map((agent) => {
          const c = asked(agent);
          const by = c.asked_by ?? 0;
          return h(
            "tr",
            {},
            h("th", { scope: "row", class: "sticky-col" }, cast.chip(agent)),
            h(
              "td",
              { class: "bar-col" },
              h(
                "span",
                { class: "chosen-bar", title: `${agent}: asked ${fmt.plural(by, "time")}, took up ${fmt.int(c.took_up ?? 0)}, let lapse ${fmt.int(c.let_lapse ?? 0)}` },
                h("span", { class: "bar", style: { width: `${(by / most) * 100}%` } }, h("span", { class: "took", style: { width: by ? `${((c.took_up ?? 0) / by) * 100}%` : "0" } }), h("span", { class: "lapsed", style: { width: by ? `${((c.let_lapse ?? 0) / by) * 100}%` : "0" } })),
                h("b", {}, by ? fmt.int(by) : askedAny ? "never asked" : "–"),
              ),
            ),
            h("td", {}, fmt.int(c.asked ?? 0)),
            h("td", {}, fmt.int(c.put_down ?? 0)),
            h("td", {}, fmt.int(c.paired ?? 0)),
            h("td", {}, `${fmt.int(c.joint_taken ?? 0)}${c.joint_repeat ? ` (${c.joint_repeat})` : ""}`),
          );
        }),
      ),
    ),
  );
  const body = h(
    "div",
    { class: "selection" },
    h("div", { class: "stats" }, stat("asked_by_gini", sel.asked_by_gini), stat("blemish_asked_rho", sel.blemish_asked_rho), stat("stated_revealed", sel.stated_revealed)),
    h("p", { class: "note" }, `These describe one town; they are not tests. With ${fmt.plural(cast.names.length, "resident")} a rank correlation moves a long way by chance, and a resident who takes more jobs both risks more blemishes and is seen more. Compare them between arms of a study, one value per run.`),
    h("h4", { class: "fig-sub" }, "Who is asked, and who is passed over"),
    table,
    h("div", { class: "two-col selection-pair" }, h("div", {}, h("h4", { class: "fig-sub" }, "Who asked whom"), askMatrix(pairs, cast)), h("div", {}, h("h4", { class: "fig-sub" }, term("Marks and askings", SELECTION.stated_revealed.def)), markStrip(pairs, measures, window, sel.stated_revealed, cast))),
  );
  return figure({ title: "Choosing partners", note: askedAny ? "Who asks whom to take a job together, who is passed over, and whether askings follow the marks residents give." : "Nobody asked anybody in these days: under assignment the clerk pairs the names put down by lot, so the statistics of choosing are empty.", chart: { el: body, table: () => table.cloneNode(true) }, wide: true });
}

/** Rows ask columns: askings made in the window, with those taken up. */
function askMatrix(pairs, cast) {
  const totals = new Map();
  for (const row of pairs) {
    const t = totals.get(`${row.source}>${row.target}`) ?? { asked: 0, taken_up: 0 };
    t.asked += row.asked;
    t.taken_up += row.taken_up;
    totals.set(`${row.source}>${row.target}`, t);
  }
  const most = Math.max(1, ...[...totals.values()].map((t) => t.asked));
  return h(
    "div",
    { class: "table-wrap" },
    h(
      "table",
      { class: "matrix" },
      h("thead", {}, h("tr", {}, h("th", { class: "corner sticky-col" }, "asks ↓ → asked"), cast.names.map((name) => h("th", { scope: "col", title: name }, cast.badge(name, 16))))),
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
              const t = totals.get(`${from}>${to}`);
              if (!t?.asked) return h("td", { class: "none", title: `${from} never asked ${to}` }, "");
              return h("td", { class: `heat-${Math.max(1, Math.min(5, Math.ceil((t.asked / most) * 5)))}`, title: `${from} asked ${to} ${fmt.plural(t.asked, "time")}, ${fmt.int(t.taken_up)} taken up` }, `${t.asked}${t.taken_up ? `·${t.taken_up}` : ""}`);
            }),
          ),
        ),
      ),
    ),
    h("p", { class: "note" }, "Askings made; after the dot, those taken up."),
  );
}

/**
 * Marks against askings: each ordered pair in which one resident marked another, at its mean
 * mark, in the row of pairs where it also asked the other or the row where it did not; the
 * difference between the rows' means is the bundle's figure.
 */
function markStrip(pairs, measures, window, published, cast) {
  const marks = new Map();
  for (const edge of measures.graph) {
    if (edge.day < window.first_day || edge.day > window.last_day || !edge.ratings) continue;
    const key = `${edge.source}>${edge.target}`;
    const m = marks.get(key) ?? [0, 0];
    marks.set(key, [m[0] + edge.ratings_sum, m[1] + edge.ratings]);
  }
  const chose = new Set(pairs.filter((row) => row.asked).map((row) => `${row.source}>${row.target}`));
  const groups = { asked: [], "not asked": [] };
  for (const [key, [sum, n]] of marks) groups[chose.has(key) ? "asked" : "not asked"].push({ key, mean: sum / n });
  if (!marks.size) return emptyState("Nobody marked anybody in these days.");
  const width = 300;
  const x = (v) => 16 + ((v - 1) / 4) * (width - 32);
  const row = (name, i) => {
    const items = groups[name];
    const y = 22 + i * 34;
    const mean = items.length ? items.reduce((a, b) => a + b.mean, 0) / items.length : null;
    return s(
      "g",
      {},
      s("text", { class: "tick", x: 0, y: y - 11 }, `${name} · ${fmt.plural(items.length, "pair")}`),
      s("line", { class: "grid", x1: x(1), x2: x(5), y1: y, y2: y }),
      items.map((item) => s("circle", { class: "pair-dot", cx: x(item.mean).toFixed(1), cy: y, r: 4 }, s("title", {}, `${item.key.replace(">", " marked ")} ${fmt.num(item.mean, 2)} on average`))),
      mean === null ? null : s("line", { class: "pair-mean", x1: x(mean), x2: x(mean), y1: y - 8, y2: y + 8 }, s("title", {}, `mean ${fmt.num(mean, 2)}`)),
    );
  };
  return h(
    "div",
    { class: "mark-strip" },
    s(
      "svg",
      { viewBox: `0 0 ${width} 96`, width, height: 96, class: "chart-svg mark-svg", role: "img", "aria-label": "Mean marks of pairs that asked and did not" },
      row("asked", 0),
      row("not asked", 1),
      [1, 2, 3, 4, 5].map((v) => s("text", { class: "tick", x: x(v), y: 92, "text-anchor": "middle" }, String(v))),
    ),
    h("p", { class: "note" }, published === null || published === undefined ? "The difference is not defined: one of the two rows is empty." : `Asked pairs mark ${fmt.num(Math.abs(published), 2)} ${published >= 0 ? "higher" : "lower"} on average than pairs not asked. Each dot is a pair's mean mark; the bars are the rows' means.`),
  );
}

/** Keep the strips' emphasis in step with the chosen resident. */
export function emphasise(root, name) {
  for (const dot of root.querySelectorAll(".strip-dot")) dot.classList.toggle("dim", Boolean(name) && dot.dataset.agent !== name);
}

