// The application: reads the bundle, routes the URL to a view, keeps the header, follows live
// runs by polling the index, and says plainly what failed when something does.

import { FormatError, RunSource, readIndex, readManifest, runKey } from "./data.js";
import { fill, fmt, h } from "./dom.js";
import { icon } from "./icons.js";
import { Cast } from "./identity.js";
import { href, navigate, parse, remember, sibling } from "./router.js";
import { mountCompare } from "./views/compare.js";
import { mountEvaluation } from "./views/evaluation.js";
import { mountLanding } from "./views/landing.js";
import { mountOverview } from "./views/overview.js";
import { mountPerson } from "./views/person.js";
import { mountTown } from "./views/town.js";

const POLL_MS = 5000;
const VIEWS = { home: mountLanding, compare: mountCompare, overview: mountOverview, town: mountTown, person: mountPerson, evaluation: mountEvaluation };
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

const statusPill = (entry) =>
  h(
    "span",
    { class: `pill ${entry.status}`, title: entry.status === "running" ? "The run is in progress; the view follows it" : `The run is ${entry.status}` },
    h("span", { class: "dot" }),
    entry.status === "running" ? "Live" : entry.status[0].toUpperCase() + entry.status.slice(1),
  );

function header() {
  const r = app.route;
  const entry = r.experiment && app.index?.runs.find((run) => run.experiment === r.experiment && (!r.run || run.run === r.run));
  const crumbs = [];
  if (r.view !== "home") {
    crumbs.push(h("span", { class: "sep" }, "/"), h("a", { href: href({ view: "compare", experiment: r.experiment }) }, r.experiment));
    if (r.run) crumbs.push(h("span", { class: "sep" }, "/"), h("a", { href: href(sibling(r, "overview")) }, r.run));
  }
  fill($("crumbs"), crumbs);
  if (r.run && entry) {
    const tab = (view, label, glyph) =>
      h("a", { href: href(sibling(r, view, view === "person" ? { agent: r.agent ?? app.run?.cast.names[0] } : {})), "aria-current": r.view === view ? "page" : null }, icon(glyph, 16), label);
    fill($("tabs"), tab("overview", "Overview", "chart"), tab("town", "Town", "map"), tab("person", "People", "people"), tab("evaluation", "Evaluation", "scale"));
    fill(
      $("status"),
      statusPill(entry),
      h("span", {}, entry.last_day ? `Day ${entry.last_day} of ${entry.days}` : `${entry.days} days planned`),
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
    const key = r.run ? `${r.experiment}/${r.run}` : r.experiment ?? "";
    if (!force && app.view?.kind === r.view && app.view.key === key && app.view.handle.update?.(r)) return;
    app.view?.handle.destroy?.();
    const main = $("main");
    main.replaceChildren();
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
  await route();
  schedule();
}

boot();
