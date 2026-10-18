// Every experiment and its runs: status, progress and a few headline numbers. Runs that belong
// to a study are grouped by study and arm, each study leading to the comparison of its arms.

import { experimentLabel, emptyState, fill, fmt, h } from "../dom.js";
import { icon } from "../icons.js";
import { studyKey } from "../data.js";
import { href } from "../router.js";
import { studyLabel } from "./study.js";

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

export const statusPill = (entry) =>
  h(
    "span",
    { class: `pill ${entry.status}`, title: entry.status === "running" ? "The run is in progress; the view follows it" : `The run is ${entry.status}` },
    h("span", { class: "dot" }),
    entry.status === "running" ? "Live" : entry.status[0].toUpperCase() + entry.status.slice(1),
  );

const figure = (label, value, title = null) => h("div", { class: "run-stat", title }, h("span", { class: "run-stat-value" }, value), h("span", { class: "run-stat-label" }, label));

export function wallTime(value) {
  if (!value || !Number.isFinite(Date.parse(value))) return "—";
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
  }).format(new Date(value));
}

function runTimes(entry) {
  return h("div", { class: "run-times" },
    h("span", {}, `Started: ${wallTime(entry.started_at)}`),
    entry.continued_at ? h("span", {}, `Continued: ${wallTime(entry.continued_at)}`) : null,
    h("span", {}, entry.ended_at ? `Ended: ${wallTime(entry.ended_at)}` : "Ended: Running"),
    h("span", { class: "muted" }, "Beijing time (UTC+8) · Wall-clock time"),
  );
}

function runRow(entry) {
  const head = entry.headline;
  const open = { view: "overview", experiment: entry.experiment, run: entry.run, query: {} };
  return h(
    "li",
    { class: "run-row" },
    h("div", { class: "run-id" }, h("a", { class: "run-name", href: href(open) }, entry.run), h("div", { class: "row" }, statusPill(entry), entry.dry_run ? h("span", { class: "pill dry", title: "A deterministic stand-in answered instead of a model" }, "dry run") : null)),
    progress(entry),
    h(
      "div",
      { class: "run-stats" },
      figure("hand-ins accepted", fmt.int(head.deliveries), `${fmt.int(head.defects_discovered)} faults came to light`),
      figure("latent faults", fmt.pct(head.defect_rate, 1), "Accepted hand-ins declared finished whose true quality was below 1"),
      figure("mean balance", head.balance_mean === null ? "–" : fmt.int(Math.round(head.balance_mean))),
      figure("mean standing", fmt.num(head.esteem_mean, 2)),
    ),
    h("div", { class: "run-links" }, h("a", { class: "ghost small", href: href({ ...open, view: "town" }) }, icon("map", 15), "Town"), h("a", { class: "btn small", href: href(open), "aria-label": `Open ${experimentLabel(entry.experiment)} ${entry.run}` }, "Open", icon("chevron", 15))),
    runTimes(entry),
  );
}

/** A seed of an arm in a few words: its status, its seed and how far it has gone. */
function seedChip(entry) {
  return h(
    "a",
    { class: "seed-chip", href: href({ view: "overview", experiment: entry.experiment, run: entry.run, query: {} }), title: `${experimentLabel(entry.experiment)} · ${entry.run}: ${entry.status}, day ${entry.last_day} of ${entry.days} · Started ${wallTime(entry.started_at)} · Beijing time (UTC+8)` },
    h("span", { class: `pill-dot ${entry.status}` }),
    h("b", {}, `seed ${entry.seed}`),
    h("span", { class: "muted" }, wallTime(entry.started_at)),
    h("span", { class: "muted" }, entry.last_day ? `day ${entry.last_day}/${entry.days}` : "not started"),
  );
}

/** A study: its arms, each with its seeds, and the way to the arms compared. */
function studySection(study, index) {
  const arms = study.arms.map((arm) => ({ ...arm, runs: index.runs.filter((entry) => entry.experiment === arm.experiment) }));
  const runs = arms.flatMap((arm) => arm.runs);
  const first = runs[0];
  const seeds = new Set(runs.map((entry) => entry.seed));
  return h(
    "section",
    { class: "experiment study" },
    h(
      "header",
      { class: "spread experiment-head" },
      h(
        "div",
        {},
        h("p", { class: "eyebrow" }, "Study"),
        h("h2", {}, study.study, study.dry_run ? h("span", { class: "pill dry", title: "A deterministic stand-in answered instead of a model; its behaviour means nothing" }, "dry run") : null),
        h("p", { class: "note" }, `${fmt.plural(arms.length, "arm")} · ${fmt.plural(seeds.size, "seed")}${first ? ` · ${first.days} days · ${first.model}` : ""}`),
      ),
      h("a", { class: "btn small", href: href({ view: "study", study: studyKey(study) }), "aria-label": `Compare the arms of ${studyLabel(studyKey(study))}` }, "Compare the arms", icon("chevron", 15)),
    ),
    h(
      "ul",
      { class: "runs card arms" },
      arms.map((arm) =>
        h(
          "li",
          { class: "arm-row" },
          h("b", { class: "arm-name" }, arm.arm),
          arm.runs.length ? h("div", { class: "seed-chips" }, arm.runs.map(seedChip)) : h("p", { class: "muted small-text" }, "No run yet."),
          arm.runs.length > 1 ? h("a", { class: "quiet small", href: href({ view: "compare", experiment: arm.experiment }), title: "The seeds of this arm side by side" }, icon("lines", 14), "Seeds") : h("span"),
        ),
      ),
    ),
  );
}

export function mountLanding(root, ctx) {
  const page = h("div", { class: "page landing" });
  root.append(page);

  function render(index) {
    const studies = index.studies ?? [];
    const inStudy = new Set(studies.flatMap((study) => study.arms.map((arm) => arm.experiment)));
    const experiments = new Map();
    const newest = [...index.runs].sort((a, b) =>
      Date.parse(b.continued_at ?? b.started_at) - Date.parse(a.continued_at ?? a.started_at));
    for (const entry of newest) if (!inStudy.has(entry.experiment)) (experiments.get(entry.experiment) ?? experiments.set(entry.experiment, []).get(entry.experiment)).push(entry);
    fill(
      page,
      h("header", { class: "page-head" }, h("h1", {}, "Experiments"), h("p", { class: "lede" }, studies.length ? "A study runs the arms of an experimental design over the same seeds; each seed is an independent run of an arm's town. Other experiments follow. Live runs update as they go." : "Each experiment is one town and its rules; each seed is an independent run of it. Live runs update as they go.")),
      studies.map((study) => studySection(study, index)),
      studies.length && experiments.size ? h("p", { class: "eyebrow group-title" }, "Other experiments") : null,
      experiments.size || studies.length
        ? [...experiments].map(([name, runs]) => {
            const first = runs[0];
            return h(
              "section",
              { class: "experiment" },
              h(
                "header",
                { class: "spread experiment-head" },
                h("div", {}, h("h2", {}, experimentLabel(name)), h("p", { class: "note" }, `${first.agents.length} agents · ${first.days} days · ${first.model} · ${fmt.plural(runs.length, "seed")}`)),
                runs.length > 1 ? h("a", { class: "quiet small", href: href({ view: "compare", experiment: name }) }, icon("lines", 15), "Compare seeds") : null,
              ),
              h("ul", { class: "runs card" }, runs.map(runRow)),
            );
          })
        : h("div", { class: "card" }, emptyState("No runs are published yet.", "Start one with ", h("code", {}, "python -m experiments.run experiments/configs/smoke.yaml --seeds 0"), " and publish the runs root.")),
    );
  }

  render(ctx.index);
  return {
    update: () => true,
    live: ({ index }) => render(index),
  };
}
