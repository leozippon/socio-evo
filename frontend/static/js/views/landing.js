// Every run and how far it has come: status, the day reached, who lives there, a few headline
// numbers, and the ways in: the town to watch, the people to read, the dashboard for the
// numbers. Runs of one directory stand together, each set leading to the comparison of its
// runs. Runs the publisher could not read are named with the reason.

import { dateOf } from "../clock.js";
import { readProgress } from "../data.js";
import { emptyState, fill, fmt, h, money } from "../dom.js";
import { icon } from "../icons.js";
import { Cast } from "../identity.js";
import { href } from "../router.js";

export function progress(entry) {
  const settled = (entry.settled_day / entry.days) * 100;
  const begun = (entry.last_day / entry.days) * 100;
  return h(
    "div",
    { class: "progress", role: "img", "aria-label": `${entry.last_day} of ${entry.days} days begun, ${entry.settled_day} closed by a checkpoint` },
    h("div", { class: "progress-bar" }, h("span", { class: "settled", style: { width: `${settled}%` } }), h("span", { class: `partial${entry.status === "running" ? " live" : ""}`, style: { left: `${settled}%`, width: `${Math.max(0, begun - settled)}%` } })),
    h("span", { class: "progress-text" }, entry.last_day ? `Day ${entry.last_day} of ${entry.days}${entry.settled_day < entry.last_day ? ` · ${entry.settled_day} closed` : ""}` : `Not started · ${entry.days} days planned`),
  );
}

export const statusPill = (entry) =>
  h(
    "span",
    { class: `pill ${entry.status}`, title: entry.status === "running" ? "The run is in progress; the view follows it" : `The run is ${entry.status}` },
    h("span", { class: "dot" }),
    entry.status === "running" ? "Live" : entry.status[0].toUpperCase() + entry.status.slice(1),
  );

const figure = (label, value, title = null) => h("div", { class: "run-stat", title }, h("span", { class: "run-stat-value" }, value), h("span", { class: "run-stat-label" }, label));

/** The day a run has reached, in words: where it is, or where it stopped. */
export function reached(entry) {
  const head = entry.headline;
  const at = `day ${head.day} at ${head.clock}`;
  if (entry.status === "running") return `On ${at}`;
  if (entry.status === "completed") return `Completed after ${fmt.plural(head.day, "day")}`;
  return `Stopped on ${at}`;
}

/**
 * The progress table of a run: one row per lived day, the day in progress marked, or, for a run
 * that stopped, the day it stopped in, which no checkpoint closed.
 */
export function progressTable(doc, status = "running") {
  const currency = doc.currency;
  const open = status === "running";
  const columns = [
    ["Day", "The lived day, from one checkpoint to the next", (d) => d.day],
    ["Date", "The date the lived day began on, in the town's calendar", (d) => dateOf(d.date, 0)],
    ["Real hours", "The real hours the day took, from its beginning to its checkpoint", (d) => (d.in_progress ? (open ? "…" : "–") : d.hours.toFixed(2))],
    ["Came in", "Clients' tasks that came in at the Office", (d) => d.arrived],
    ["Claimed", "Tasks claimed by a programmer", (d) => d.claims],
    ["Assigned", "Tasks the team leader gave to a programmer", (d) => d.assigned],
    ["Handed in", "Tasks handed in for the client's checks", (d) => d.submissions],
    ["Accepted", "Handed in and accepted", (d) => d.accepted],
    ["Not accepted", "Handed in and not accepted", (d) => d.rejected],
    ["Withdrawn", "Tasks their clients withdrew, not accepted in time", (d) => d.withdrawn],
    ["Sales", "Sales at the Store's counter, the kitchen's among them", (d) => d.sales],
    ["Dishes", "Dishes served at the restaurant", (d) => d.dishes],
    ["Patients", "Examinations and treatments at the Hospital or at a bedside", (d) => d.examinations + d.treatments],
    ["Announced", "The mayor's announcements", (d) => d.announcements],
    ["Said", "Things said", (d) => d.speeches],
    ["Gifts", "Times money or a thing was given", (d) => d.gifts],
    ["Journals", "Residents gone to bed with the day's journal", (d) => d.journals],
    ["Fell ill", "Residents who fell ill at midnight", (d) => d.illnesses],
    ["To bed", "Residents whose health ran out, who took to their beds", (d) => d.bedridden],
    ["Forced asleep", "Residents fallen asleep at the forced hour, without going to bed", (d) => d.forced_sleeps],
    ["Money low · median · high", "The money the residents held at the end of the day, or at its latest moment for the day in progress", (d) => [d.purse.min, d.purse.median, d.purse.max].map((n) => money(n, currency)).join(" · ")],
  ];
  return h(
    "div",
    { class: "table-wrap" },
    h(
      "table",
      { class: "data progress-table" },
      h("thead", {}, h("tr", {}, columns.map(([name, title]) => h("th", { title }, name)))),
      h(
        "tbody",
        {},
        doc.daily.map((d) =>
          h(
            "tr",
            { class: d.in_progress ? "current" : "", title: d.in_progress ? (open ? "The day in progress: what has happened so far" : "The day the run stopped in, which no checkpoint closed") : null },
            columns.map(([, , cell]) => {
              const value = cell(d);
              return h("td", { class: value === 0 ? "zero" : "" }, String(value));
            }),
          ),
        ),
      ),
    ),
  );
}

function runRow(entry, index) {
  const head = entry.headline;
  const open = { view: "overview", run: entry.name, query: {} };
  const cast = new Cast({ residents: entry.residents.map((name) => ({ name })) });
  // The index gives no currency; the run's progress document does, so the fund reads as a
  // plain number until it arrives.
  const fund = figure("the town's fund", fmt.int(head.fund), head.fund === null ? "Read at each checkpoint; none has been saved yet" : "At the last checkpoint");
  readProgress(index, entry).then(
    (doc) => {
      if (head.fund !== null) fund.firstChild.textContent = money(head.fund, doc.currency);
    },
    () => {},
  );
  const pace = head.hours_per_day === null ? "no day completed yet" : `${head.hours_per_day.toFixed(1)} real hours a day`;
  return h(
    "li",
    { class: "run-row" },
    h(
      "div",
      { class: "run-id" },
      h("a", { class: "run-name", href: href(open) }, entry.name),
      h("div", { class: "row" }, statusPill(entry), entry.dry_run ? h("span", { class: "pill dry", title: "A scripted stand-in answered instead of a model; its behaviour means nothing" }, "dry run") : null),
      h("span", { class: "muted small-text" }, `${reached(entry)} · ${pace}`),
      h("div", { class: "run-cast", "aria-label": "The residents" }, entry.residents.map((name) => h("a", { class: "chip", href: href({ view: "person", run: entry.name, agent: name, query: {} }), title: name }, cast.badge(name, 18), h("span", { class: "sr" }, name)))),
    ),
    progress(entry),
    h(
      "div",
      { class: "run-stats" },
      fund,
      figure("tasks accepted", fmt.int(head.accepted), `${fmt.int(head.arrived)} came in, ${fmt.int(head.submissions)} handed in, ${fmt.int(head.withdrawn)} withdrawn`),
      figure("sales · dishes · patients", `${fmt.int(head.sales)} · ${fmt.int(head.dishes)} · ${fmt.int(head.examinations + head.treatments)}`, "Sales at the Store's counter, dishes served, examinations and treatments"),
      figure("things said", fmt.int(head.speeches), `${fmt.int(head.gifts)} gifts, ${fmt.int(head.messages)} messages`),
    ),
    h("div", { class: "run-links" }, h("a", { class: "btn small", href: href({ ...open, view: "town" }) }, icon("map", 15), "Watch the town"), h("a", { class: "ghost small", href: href({ ...open, view: "person", agent: entry.residents[0] }) }, icon("people", 15), "People"), h("a", { class: "ghost small", href: href(open) }, icon("chart", 15), "Dashboard")),
  );
}

export function mountLanding(root, ctx) {
  const page = h("div", { class: "page landing" });
  root.append(page);
  let shown = null;

  function render(index) {
    const key = JSON.stringify([index.runs.map((r) => r.url), index.skipped, index.comparisons.map((c) => c.url)]);
    if (key === shown) return;
    shown = key;
    const sets = index.comparisons.map((c) => ({ name: c.name, url: c.url, runs: index.runs.filter((r) => c.runs.includes(r.name)) }));
    const inSet = new Set(sets.flatMap((set) => set.runs.map((r) => r.name)));
    const alone = index.runs.filter((r) => !inSet.has(r.name));
    const section = (title, runs, compare) =>
      h(
        "section",
        { class: "experiment" },
        h(
          "header",
          { class: "spread experiment-head" },
          h("div", {}, h("h2", {}, title), h("p", { class: "note" }, `${fmt.plural(runs.length, "run")}${runs[0] ? ` · ${fmt.plural(runs[0].residents.length, "resident")} · ${fmt.plural(runs[0].days, "day")} planned · ${runs[0].model}` : ""}`)),
          compare ? h("a", { class: "btn small", href: href({ view: "compare", comparison: compare }) }, "Compare the runs", icon("chevron", 15)) : null,
        ),
        h("ul", { class: "runs card" }, runs.map((entry) => runRow(entry, index))),
      );
    fill(
      page,
      h(
        "header",
        { class: "page-head" },
        h("h1", {}, "A small town"),
        h("p", { class: "lede" }, "Each run is one town of residents living their days, each at its occupation: the programmers and their team leader take on clients' tasks at the Office, the shopkeeper keeps the Store, the chef cooks for the restaurant, the doctor sees patients and the mayor reads the town's report and makes announcements. The town's fund pays their wages and takes their rent; they buy food and things, eat out, fall ill, meet and talk, and keep their own notes. Nobody tells them how to behave; what they become is the question. Watch a town as it happens, read each resident's story, or open the dashboard for the numbers. Live runs update as they go."),
      ),
      index.runs.length || index.skipped.length ? null : h("div", { class: "card" }, emptyState("No runs are published yet.", "Runs appear here once one has been started and the runs root is published; a run just created shows up before its first entry.")),
      sets.map((set) => section(set.name, set.runs, set.name)),
      alone.length ? section(sets.length ? "Other runs" : "All runs", alone, null) : null,
      index.skipped.length
        ? h(
            "section",
            { class: "experiment" },
            h("header", { class: "experiment-head" }, h("div", {}, h("h2", {}, "Not published"), h("p", { class: "note" }, "Runs found under the runs root that the publisher left out. Nothing of them is lost; each appears here as soon as its files and the code agree again."))),
            h(
              "ul",
              { class: "card skipped" },
              index.skipped.map((found) =>
                h(
                  "li",
                  {},
                  h("div", { class: "row" }, h("b", { class: "run-name" }, found.name), h("span", { class: "pill" }, h("span", { class: "dot" }), "Not published")),
                  h("p", { class: "note" }, found.reason),
                  found.detail ? h("details", { class: "fold skipped-detail" }, h("summary", {}, "What the publisher reported"), h("pre", {}, found.detail)) : null,
                ),
              ),
            ),
          )
        : null,
    );
  }

  render(ctx.index);
  return {
    update: () => true,
    live: ({ index }) => render(index),
  };
}
