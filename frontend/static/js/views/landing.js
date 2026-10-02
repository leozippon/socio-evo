// Every experiment and its runs: status, progress and headline numbers, seeds side by side.

import { emptyState, fill, fmt, h } from "../dom.js";
import { icon } from "../icons.js";
import { href } from "../router.js";

export function progress(entry) {
  const settled = (entry.settled_day / entry.days) * 100;
  const begun = (entry.last_day / entry.days) * 100;
  return h(
    "div",
    { class: "progress", role: "img", "aria-label": `${entry.last_day} of ${entry.days} days begun, ${entry.settled_day} settled` },
    h("div", { class: "progress-bar" }, h("span", { class: "settled", style: { width: `${settled}%` } }), h("span", { class: `partial${entry.status === "running" ? " live" : ""}`, style: { left: `${settled}%`, width: `${Math.max(0, begun - settled)}%` } })),
    h("span", { class: "progress-text" }, entry.last_day ? `Day ${entry.last_day} of ${entry.days}` : `Not started · ${entry.days} days planned`),
  );
}

const stat = (label, value, title = null) => h("div", { class: "run-stat", title }, h("span", { class: "run-stat-value" }, value), h("span", { class: "run-stat-label" }, label));

function runRow(entry) {
  const head = entry.headline;
  const open = { view: "overview", experiment: entry.experiment, run: entry.run, query: {} };
  return h(
    "article",
    { class: "run-row" },
    h(
      "div",
      { class: "run-id" },
      h("a", { class: "run-name", href: href(open) }, entry.run),
      h(
        "div",
        { class: "row" },
        h("span", { class: `pill ${entry.status}` }, h("span", { class: "dot" }), entry.status === "running" ? "Live" : entry.status),
        entry.dry_run ? h("span", { class: "pill dry" }, "dry run") : null,
      ),
    ),
    progress(entry),
    h(
      "div",
      { class: "run-stats" },
      stat("deliveries", fmt.int(head.deliveries)),
      stat("defect rate", fmt.pct(head.defect_rate, 1), "Accepted deliveries that carried a latent defect"),
      stat("defects found", fmt.int(head.defects_discovered)),
      stat("mean balance", head.balance_mean === null ? "–" : fmt.credits(Math.round(head.balance_mean))),
      stat("mean esteem", fmt.num(head.esteem_mean, 2)),
      stat("evolution steps", fmt.int(head.evolution_steps)),
      stat("model calls", fmt.compact(head.model_calls), `${fmt.int(head.tokens)} tokens`),
      stat("evaluated days", head.evaluated_days.length ? head.evaluated_days.join(", ") : "none"),
    ),
    h(
      "div",
      { class: "run-links" },
      h("a", { class: "ghost small", href: href({ ...open, view: "town" }) }, icon("map", 15), "Town"),
      h("a", { class: "btn small", href: href(open) }, "Open", icon("chevron", 15)),
    ),
  );
}

export function mountLanding(root, ctx) {
  const page = h("div", { class: "page landing" });
  root.append(page);

  function render(index) {
    const experiments = new Map();
    for (const entry of index.runs) (experiments.get(entry.experiment) ?? experiments.set(entry.experiment, []).get(entry.experiment)).push(entry);
    fill(
      page,
      h("div", { class: "landing-head" }, h("h1", {}, "Experiments"), h("p", { class: "note" }, "Each experiment is one town and its rules; each seed is an independent run of it. Live runs update as they go.")),
      experiments.size
        ? [...experiments].map(([name, runs]) => {
            const first = runs[0];
            return h(
              "section",
              { class: "card experiment" },
              h(
                "header",
                { class: "spread" },
                h("div", {}, h("h2", {}, name), h("p", { class: "note" }, `${first.agents.length} agents · ${first.days} days · ${first.model} · ${fmt.plural(runs.length, "seed")}`)),
                runs.length > 1 ? h("a", { class: "ghost small", href: href({ view: "compare", experiment: name }) }, icon("lines", 15), "Compare seeds") : null,
              ),
              h("div", { class: "runs" }, runs.map(runRow)),
            );
          })
        : emptyState("No runs are published yet.", "Start one with ", h("code", {}, "python -m experiments.run experiments/configs/smoke.yaml --seeds 0"), " and publish the runs root."),
    );
  }

  render(ctx.index);
  return {
    update: () => true,
    live: ({ index }) => render(index),
  };
}
