// Hash routes: every view and the moment it shows live in the URL, so a moment can be shared. A
// run is named by its path under the runs root, URL-encoded as one segment (`pilot%2Fa`).
//
//   #/                                  every run, with its progress day by day
//   #/compare/<comparison>              the runs of a set compared
//   #/run/<run>                         the run's dashboard; ?section=
//   #/run/<run>/town                    the town; ?t=<day>-<HH:MM>&agent=&as=1&only=1&panel=&speed=
//   #/run/<run>/timeline                every resident's events side by side; ?t=&agent=&from=&to=
//   #/run/<run>/people/<agent>          one resident; ?t=&tab=&day=&v=<commit>
//   #/run/<run>/evaluation              the evaluation of the run's residents

const VIEWS = { "": "overview", town: "town", timeline: "lanes", people: "person", evaluation: "evaluation" };
const TAILS = { overview: "", town: "/town", lanes: "/timeline", person: "/people", evaluation: "/evaluation" };

export function parse(hash) {
  const [path, search = ""] = hash.replace(/^#/, "").split("?");
  const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
  const query = Object.fromEntries(new URLSearchParams(search));
  if (parts[0] === "compare" && parts[1]) return { view: "compare", comparison: parts[1], query };
  if (parts[0] === "run" && parts[1]) {
    const view = VIEWS[parts[2] ?? ""];
    if (view) return { view, run: parts[1], agent: parts[3] ?? null, query };
  }
  if (parts.length) return { view: "missing", query };
  return { view: "home", query };
}

export function href(route) {
  const enc = encodeURIComponent;
  let path = "/";
  if (route.view === "compare") path = `/compare/${enc(route.comparison)}`;
  else if (route.view !== "home") path = `/run/${enc(route.run)}${TAILS[route.view]}${route.view === "person" && route.agent ? `/${enc(route.agent)}` : ""}`;
  const query = Object.entries(route.query ?? {}).filter(([, value]) => value !== null && value !== undefined && value !== "");
  return `#${path}${query.length ? `?${new URLSearchParams(query)}` : ""}`;
}

/** A route to another view of the same run, carrying the shared moment along. */
export function sibling(route, view, extra = {}) {
  const query = { t: route.query.t, ...extra.query };
  return { view, run: route.run, agent: extra.agent ?? null, query };
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
