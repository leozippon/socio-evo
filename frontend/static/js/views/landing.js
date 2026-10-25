// Every run and how far it has come: status, the day reached, a few headline numbers, and the
// progress table of its lived days. Runs of one directory stand together, each set leading to
// the comparison of its groups. Runs the publisher could not read are named with the reason.

import { dateOf } from "../clock.js";
import { readProgress } from "../data.js";
import { emptyState, fill, fmt, h, money } from "../dom.js";
import { icon } from "../icons.js";
import { href } from "../router.js";
import { groupLabel } from "../world.js";

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

export const groupPill = (group) => (group ? h("span", { class: "pill group", title: groupLabel(group) }, `Group ${group}`) : null);

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
    ["Claims", "Tasks claimed", (d) => d.claims],
    ["Hand-ins", "Tasks handed in", (d) => d.submissions],
    ["Accepted", "Handed in and accepted", (d) => d.accepted],
    ["Not accepted", "Handed in and not accepted", (d) => d.rejected],
    ["Paid", "The total paid for accepted tasks", (d) => (d.paid ? money(d.paid, currency) : 0)],
    ["Said", "Things said", (d) => d.speeches],
    ["Gifts", "Gifts of money", (d) => d.gifts],
    ["Skills", "Skills passed on", (d) => d.skills_shared],
    ["Ratings", "Ratings given", (d) => d.ratings],
    ["Journals", "Residents gone to bed with the day's journal", (d) => d.journals],
    ["Forced asleep", "Residents fallen asleep at the forced hour, without a journal", (d) => d.forced_sleeps],
    ["Purses low · median · high", "The residents' purses at the end of the day, or at its latest moment for the day in progress", (d) => [d.purse.min, d.purse.median, d.purse.max].map((n) => money(n, currency)).join(" · ")],
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
  const table = h("div", { class: "run-progress" }, h("div", { class: "loading" }, "Loading the days…"));
  // The index gives no currency; the run's progress document does, so the sums of money read
  // as plain numbers until it arrives.
  const paid = figure("paid for tasks", fmt.int(head.paid), `${fmt.int(head.payments)} payments`);
  const purse = figure("median purse", fmt.int(head.purse.median), `${fmt.int(head.purse.min)} to ${fmt.int(head.purse.max)}`);
  readProgress(index, entry).then(
    (doc) => {
      paid.firstChild.textContent = money(head.paid, doc.currency);
      purse.firstChild.textContent = money(head.purse.median, doc.currency);
      purse.title = `${money(head.purse.min, doc.currency)} to ${money(head.purse.max, doc.currency)}`;
      fill(table, doc.daily.length ? progressTable(doc, entry.status) : emptyState("No day has begun yet.", "The table of lived days fills in as the run records its first entries."));
    },
    (error) => fill(table, emptyState("The progress could not be loaded.", error.message)),
  );
  const pace = head.hours_per_day === null ? "no day completed yet" : `${head.hours_per_day.toFixed(1)} real hours a day`;
  return h(
    "li",
    { class: "run-row" },
    h(
      "div",
      { class: "run-id" },
      h("a", { class: "run-name", href: href(open) }, entry.name),
      h("div", { class: "row" }, statusPill(entry), groupPill(entry.group), entry.dry_run ? h("span", { class: "pill dry", title: "A scripted stand-in answered instead of a model; its behaviour means nothing" }, "dry run") : null),
      h("span", { class: "muted small-text" }, `${reached(entry)} · ${pace}`),
    ),
    progress(entry),
    h(
      "div",
      { class: "run-stats" },
      figure("hand-ins accepted", fmt.int(head.accepted), `${fmt.int(head.submissions)} handed in, ${fmt.int(head.rejected)} not accepted`),
      paid,
      figure("things said", fmt.int(head.speeches), `${fmt.int(head.gifts)} gifts, ${fmt.int(head.skills_shared)} skills passed on`),
      purse,
    ),
    h("div", { class: "run-links" }, h("a", { class: "ghost small", href: href({ ...open, view: "town" }) }, icon("map", 15), "Town"), h("a", { class: "ghost small", href: href({ ...open, view: "lanes" }) }, icon("lines", 15), "Timeline"), h("a", { class: "btn small", href: href(open), "aria-label": `Open ${entry.name}` }, "Open", icon("chevron", 15))),
    table,
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
          compare ? h("a", { class: "btn small", href: href({ view: "compare", comparison: compare }) }, "Compare the groups", icon("chevron", 15)) : null,
        ),
        h("ul", { class: "runs card" }, runs.map((entry) => runRow(entry, index))),
      );
    fill(
      page,
      h("header", { class: "page-head" }, h("h1", {}, "Runs"), h("p", { class: "lede" }, "Every run published, how far each has come, and the sets of runs whose groups are compared. A run is one town of residents living their days; the groups of the design differ in the social life they allow. Live runs update as they go.")),
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
