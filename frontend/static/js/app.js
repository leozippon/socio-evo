// The application: reads the bundle, routes the URL to a view, keeps the header, follows live
// runs by polling the index, and says plainly what failed when something does.

import { FormatError, RunSource, comparisonOf, readIndex, readManifest } from "./data.js";
import { fill, fmt, h, useCurrency } from "./dom.js";
import { icon } from "./icons.js";
import { Cast } from "./identity.js";
import { href, navigate, parse, remember, sibling } from "./router.js";
import { mountCompare } from "./views/compare.js";
import { mountEvaluation } from "./views/evaluation.js";
import { mountLanding, statusPill } from "./views/landing.js";
import { mountLanes } from "./views/lanes.js";
import { mountOverview } from "./views/overview.js";
import { mountPerson } from "./views/person.js";
import { mountTown } from "./views/town.js";

const POLL_MS = 5000;
const VIEWS = { home: mountLanding, compare: mountCompare, overview: mountOverview, town: mountTown, lanes: mountLanes, person: mountPerson, evaluation: mountEvaluation };
const $ = (id) => document.getElementById(id);

const app = {
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
  const entry = r.run ? app.index?.runs.find((run) => run.name === r.run) : null;
  const crumbs = [];
  if (r.view === "compare") crumbs.push(h("span", { class: "sep exp-sep" }, "/"), h("a", { class: "exp-crumb", href: href({ view: "compare", comparison: r.comparison }) }, r.comparison));
  else if (r.run) {
    const comparison = comparisonOf(app.index, r.run);
    if (comparison) crumbs.push(h("span", { class: "sep exp-sep" }, "/"), h("a", { class: "exp-crumb", href: href({ view: "compare", comparison: comparison.name }) }, comparison.name));
    crumbs.push(h("span", { class: "sep" }, "/"), h("a", { class: "run-crumb", href: href(sibling(r, "overview")), title: r.run }, r.run));
  }
  fill($("crumbs"), crumbs);
  document.body.classList.toggle("in-run", Boolean(r.run && entry));
  document.body.dataset.view = r.view;
  document.title = r.run ? `${r.run} · socio-evo` : r.comparison ? `${r.comparison} · socio-evo` : "socio-evo";
  if (r.run && entry) {
    const tab = (view, label, glyph) => h("a", { href: href(sibling(r, view, view === "person" ? { agent: r.agent ?? app.run?.cast.names[0] } : {})), "aria-current": r.view === view ? "page" : null }, icon(glyph, 16), h("span", {}, label));
    fill($("tabs"), tab("town", "Town", "map"), tab("person", "People", "people"), tab("lanes", "Timeline", "lines"), tab("overview", "Dashboard", "chart"), tab("evaluation", "Evaluation", "scale"));
    fill($("status"), statusPill(entry), h("span", { class: "day" }, entry.last_day ? `Day ${entry.last_day} of ${entry.days}` : `${entry.days} days planned`), entry.dry_run ? h("span", { class: "pill dry", title: "A scripted stand-in answered instead of a model; its behaviour means nothing" }, "dry run") : null);
  } else {
    fill($("tabs"));
    fill($("status"), app.index ? h("span", {}, fmt.plural(app.index.runs.length, "run")) : null);
  }
}

/** The open run's source, world and cast, opened again only when the run changes. */
async function openRun(r) {
  if (app.run?.source.key === r.run) return app.run;
  const entry = app.index.runs.find((run) => run.name === r.run);
  if (!entry) throw new Error(`There is no run ${r.run} in this bundle.`);
  const source = await new RunSource(app.index, entry).open();
  source.onRefresh = (index) => (app.index = index);
  const world = await source.world();
  useCurrency(world.currency);
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
    if (ticket !== routing) return;
    if (r.view === "person" && !r.agent) {
      remember({ ...r, agent: run.cast.names[0] });
      r.agent = run.cast.names[0];
    }
    header();
    const key = r.run ?? r.comparison ?? "";
    if (!force && app.view?.kind === r.view && app.view.key === key && app.view.handle.update?.(r)) return;
    app.view?.handle.destroy?.();
    const main = $("main");
    main.replaceChildren();
    window.scrollTo(0, 0);
    const context = {
      route: r,
      index: app.index,
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

/** Follow the index: the home view and an open run hear about what changed. */
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
  await route();
  schedule();
}

boot();
