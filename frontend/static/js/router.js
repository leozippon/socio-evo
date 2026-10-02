// Hash routes: every view and the moment it shows live in the URL, so a moment can be shared.
//
//   #/                                    every experiment and run
//   #/compare/<experiment>                the seeds of an experiment side by side
//   #/run/<experiment>/<run>              the run's dashboard
//   #/run/<experiment>/<run>/town         the town; ?t=<day>-<HH:MM>&e=<seq>&agent=&truth=0&panel=
//   #/run/<experiment>/<run>/people/<agent>   one person; ?t=&tab=&v=<commit>
//   #/run/<experiment>/<run>/evaluation   held-out evaluation; ?agent=&day=&probe=

const VIEWS = { "": "overview", town: "town", people: "person", evaluation: "evaluation" };

export function parse(hash) {
  const [path, search = ""] = hash.replace(/^#/, "").split("?");
  const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
  const query = Object.fromEntries(new URLSearchParams(search));
  if (parts[0] === "compare" && parts[1]) return { view: "compare", experiment: parts[1], query };
  if (parts[0] === "run" && parts[1] && parts[2]) {
    const view = VIEWS[parts[3] ?? ""];
    if (view) return { view, experiment: parts[1], run: parts[2], agent: parts[4] ?? null, query };
  }
  if (parts.length) return { view: "missing", query };
  return { view: "home", query };
}

export function href(route) {
  const enc = encodeURIComponent;
  let path = "/";
  if (route.view === "compare") path = `/compare/${enc(route.experiment)}`;
  else if (route.view !== "home") {
    const tail = { overview: "", town: "/town", person: `/people${route.agent ? `/${enc(route.agent)}` : ""}`, evaluation: "/evaluation" }[route.view];
    path = `/run/${enc(route.experiment)}/${enc(route.run)}${tail}`;
  }
  const query = Object.entries(route.query ?? {}).filter(([, value]) => value !== null && value !== undefined && value !== "");
  return `#${path}${query.length ? `?${new URLSearchParams(query)}` : ""}`;
}

/** A route to another view of the same run, carrying the shared moment along. */
export function sibling(route, view, extra = {}) {
  const query = { t: route.query.t, ...extra.query };
  return { view, experiment: route.experiment, run: route.run, agent: extra.agent ?? null, query };
}

/** Go to a route: a new history entry, and the app re-renders on hashchange. */
export function navigate(route) {
  location.hash = href(route);
}

/** Record a route in the address bar without a new history entry or a re-render. */
export function remember(route) {
  const target = href(route);
  if (location.hash !== target) history.replaceState(null, "", target);
}
