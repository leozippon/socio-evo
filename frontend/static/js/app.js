// The application: reads the bundle, routes the URL to a view, keeps the header, follows live
// runs by polling the index, and says plainly what failed when something does.

import { FormatError, RunSource, readIndex, readManifest, runKey, studyOf } from "./data.js";
import { experimentLabel, fill, fmt, h, useCurrency } from "./dom.js";
import { icon } from "./icons.js";
import { canManageExperiments } from "./management.js";
import { Cast } from "./identity.js";
import { href, navigate, parse, remember, sibling } from "./router.js";
import { mountCompare } from "./views/compare.js";
import { mountEvaluation } from "./views/evaluation.js";
import { mountLanding, statusPill } from "./views/landing.js";
import { mountOverview } from "./views/overview.js";
import { mountPerson } from "./views/person.js";
import { mountStudy, studyLabel } from "./views/study.js";
import { mountTown } from "./views/town.js";

const POLL_MS = 5000;
const VIEWS = { home: mountLanding, compare: mountCompare, study: mountStudy, overview: mountOverview, town: mountTown, person: mountPerson, evaluation: mountEvaluation };
const $ = (id) => document.getElementById(id);

const app = {
  management: false,
  index: null,
  route: null,
  view: null, // {kind, key, handle}
  run: null, // {source, world, cast} of the open run
  polling: null,
  pollFailed: false,
};

function showAlert(message, retry = null) {
  fill($("alert"), icon("alert", 18), h("div", {}, message), retry ? h("button", { class: "ghost small", type: "button", onclick: retry }, "Try again") : null);
  $("alert").hidden = false;
}

const clearAlert = () => ($("alert").hidden = true);

function fatal(title, message) {
  fill($("main"), h("div", { class: "fatal" }, h("h1", {}, title), h("p", {}, message)));
  fill($("tabs"));
  fill($("status"));
}

/** Report an error that stops a view: the view stays as it was, the alert says what failed. */
function fail(error) {
  console.error(error);
  if (error instanceof FormatError) return fatal("This bundle cannot be read", error.message);
  showAlert(error.message ?? String(error), () => route(true));
}

function header() {
  const r = app.route;
  const entry = r.experiment && app.index?.runs.find((run) => run.experiment === r.experiment && (!r.run || run.run === r.run));
  const crumbs = [];
  const study = r.view === "study" ? null : studyOf(app.index, r.experiment);
  if (r.view === "study") crumbs.push(h("span", { class: "sep exp-sep" }, "/"), h("a", { class: "exp-crumb", href: href({ view: "study", study: r.study }) }, studyLabel(r.study)));
  else if (r.view !== "home") {
    if (study) {
      const arm = study.arms.find((found) => found.experiment === r.experiment).arm;
      crumbs.push(h("span", { class: "sep exp-sep" }, "/"), h("a", { class: "exp-crumb study-crumb", href: href({ view: "study", study: `${study.study}${study.dry_run ? "-dry-run" : ""}` }) }, studyLabel(`${study.study}${study.dry_run ? "-dry-run" : ""}`)));
      crumbs.push(h("span", { class: "sep" }, "/"), h("a", { class: "exp-crumb", href: href({ view: "compare", experiment: r.experiment }), title: experimentLabel(r.experiment) }, arm));
    } else crumbs.push(h("span", { class: "sep exp-sep" }, "/"), h("a", { class: "exp-crumb", href: href({ view: "compare", experiment: r.experiment }) }, experimentLabel(r.experiment)));
    if (r.run) crumbs.push(h("span", { class: "sep" }, "/"), h("a", { class: "run-crumb", href: href(sibling(r, "overview")), title: `${experimentLabel(r.experiment)} · ${r.run}` }, r.run));
  }
  fill($("crumbs"), crumbs);
  document.body.classList.toggle("in-run", Boolean(r.run && entry));
  document.body.dataset.view = r.view;
  document.title = r.run ? `${experimentLabel(r.experiment)} · ${r.run} · socio-evo` : r.experiment ? `${experimentLabel(r.experiment)} · socio-evo` : r.study ? `${studyLabel(r.study)} · socio-evo` : "socio-evo";
  if (r.run && entry) {
    const tab = (view, label, glyph) =>
      h("a", { href: href(sibling(r, view, view === "person" ? { agent: r.agent ?? app.run?.cast.names[0] } : {})), "aria-current": r.view === view ? "page" : null }, icon(glyph, 16), h("span", {}, label));
    fill($("tabs"), tab("overview", "Overview", "chart"), tab("town", "Town", "map"), tab("person", "People", "people"), tab("evaluation", "Evaluation", "scale"));
    fill(
      $("status"),
      statusPill(entry),
      h("span", { class: "day" }, entry.last_day ? `Day ${entry.last_day} of ${entry.days}` : `${entry.days} days planned`),
      entry.dry_run ? h("span", { class: "pill dry", title: "A deterministic stand-in answered instead of a model; its behaviour means nothing" }, "dry run") : null,
    );
  } else {
    fill($("tabs"));
    fill($("status"), app.index ? h("span", {}, fmt.plural(app.index.runs.length, "run")) : null);
  }
}

/** The open run's source, world and cast, opened again only when the run changes. */
async function openRun(r) {
  const key = `${r.experiment}/${r.run}`;
  if (app.run?.source.key === key) return app.run;
  const entry = app.index.runs.find((run) => runKey(run) === key);
  if (!entry) throw new Error(`There is no run ${key} in this bundle.`);
  const source = await new RunSource(app.index, entry).open();
  source.onRefresh = (index) => (app.index = index);
  const world = await source.world();
  useCurrency(world.setting.currency);
  app.run = { source, world, cast: new Cast(world) };
  return app.run;
}

let routing = 0;
async function route(force = false) {
  const r = parse(location.hash);
  const ticket = ++routing;
  app.route = r;
  try {
    if (!app.index) app.index = await readIndex();
    if (r.view === "missing") throw new Error(`Nothing lives at ${location.hash}.`);
    const run = r.run ? await openRun(r) : null;
    if (!r.run) app.run = null; // Do not keep polling a run after returning to the list.
    if (ticket !== routing) return;
    if (r.view === "person" && !r.agent) {
      remember({ ...r, agent: run.cast.names[0] });
      r.agent = run.cast.names[0];
    }
    header();
    const key = r.run ? `${r.experiment}/${r.run}` : r.experiment ?? r.study ?? "";
    if (!force && app.view?.kind === r.view && app.view.key === key && app.view.handle.update?.(r)) return;
    app.view?.handle.destroy?.();
    const main = $("main");
    main.replaceChildren();
    window.scrollTo(0, 0);
    const context = {
      route: r,
      index: app.index,
      management: app.management,
      refresh: async () => { await poll(); },
      ...(run ?? {}),
      navigate,
      remember: (next) => {
        app.route = next;
        remember(next);
      },
      fail,
      clearAlert,
    };
    app.view = { kind: r.view, key, handle: VIEWS[r.view](main, context) };
    clearAlert();
  } catch (error) {
    if (ticket === routing) fail(error);
  }
}

/** Follow the index: the landing view and an open run hear about what changed. */
async function poll() {
  try {
    const index = await readIndex();
    app.index = index;
    if (app.pollFailed) clearAlert();
    app.pollFailed = false;
    let changes = null;
    if (app.run) changes = await app.run.source.update(index);
    header();
    app.view?.handle.live?.({ index, changes });
  } catch (error) {
    app.pollFailed = true;
    if (error instanceof FormatError) return fail(error);
    showAlert(`Could not follow the runs: ${error.message}. Showing what was loaded before; trying again.`);
  }
}

function schedule() {
  clearTimeout(app.polling);
  app.polling = setTimeout(async () => {
    if (!document.hidden) await poll();
    schedule();
  }, POLL_MS);
}

async function boot() {
  try {
    await readManifest();
  } catch (error) {
    if (error instanceof FormatError) return fatal("This bundle cannot be read", error.message);
    return fatal("The data bundle could not be loaded", `${error.message}. The viewer expects the published site's data/ directory next to this page.`);
  }
  window.addEventListener("hashchange", () => route());
  document.addEventListener("visibilitychange", () => !document.hidden && poll());
  app.management = await canManageExperiments();
  await route();
  schedule();
}

boot();
