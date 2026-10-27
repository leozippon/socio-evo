// Every resident's events side by side over the run: one lane per resident, zoomed and panned
// over simulated time, with the moment shown elsewhere as a cursor. A lane picked lists what
// that resident did and heard in the visible window; an entry picked centres the view on it.

import { DAY, dateOf, hhmm, livedDay, parseStamp, secondOfDay, stamp } from "../clock.js";
import { emptyState, fill, fmt, h } from "../dom.js";
import { icon } from "../icons.js";
import { lowerBound, purseAt } from "../replay.js";
import { href, sibling } from "../router.js";
import { concerns, describeMarker } from "../town/events.js";
import { Lanes, legend, readColours } from "../town/lanes.js";

const PANEL_LIMIT = 400;

export function mountLanes(root, ctx) {
  const { source, cast, world } = ctx;
  let route = ctx.route;
  const page = h("div", { class: "page lanes-page" });
  root.append(page);
  let data = null;
  let lanes = null;
  let selected = cast.has(route.query.agent) ? route.query.agent : null;
  let cursor = parseStamp(route.query.t);
  let timer = null;

  const who = h("h2", {}, "No resident selected");
  const window_ = h("p", { class: "note" }, "Pick a lane to list what that resident did and heard in the visible window.");
  const entries = h("ol", { class: "lane-entries" });
  const panel = h("aside", { class: "card lanes-panel" }, who, window_, entries);
  // The legend stays in view beside the lanes; on a phone it starts folded, under a heading that opens it.
  const legendBox = h("details", { class: "card fold lanes-legend-box", open: matchMedia("(min-width: 700px)").matches }, h("summary", {}, "What the lanes show"));

  const moment = (t) => `Day ${livedDay(data.days, t).day}, ${dateOf(data.start_date, t)} ${hhmm(secondOfDay(t))}`;
  const between = (a, b) => (Math.floor(a / DAY) === Math.floor(b / DAY) ? `${moment(a)}–${hhmm(secondOfDay(b))}` : `${moment(a)} – ${moment(b)}`);

  function remember() {
    route = { ...route, query: { ...route.query, agent: selected, t: cursor === null ? null : stamp(Math.floor(cursor)), from: lanes ? String(Math.round(lanes.t0)) : null, to: lanes ? String(Math.round(lanes.t1)) : null } };
    ctx.remember(route);
  }

  function renderPanel() {
    if (!data || !lanes) return;
    const lane = data.residents.find((r) => r.name === selected);
    if (!lane) {
      who.textContent = "No resident selected";
      window_.textContent = "Pick a lane to list what that resident did and heard in the visible window.";
      entries.replaceChildren();
      return;
    }
    const { t0, t1 } = lanes;
    const found = [];
    for (const other of data.residents) {
      for (let i = lowerBound(other.markers, t0, (m) => m.t); i < other.markers.length && other.markers[i].t <= t1; i++) {
        const m = other.markers[i];
        if (concerns(m, other.name, selected)) found.push([m, other.name]);
      }
    }
    found.sort((a, b) => a[0].seq - b[0].seq);
    fill(who, cast.badge(selected, 22), ` ${selected}`, h("a", { class: "ghost small", href: href(sibling({ ...route, query: { t: cursor === null ? null : stamp(Math.floor(cursor)) } }, "person", { agent: selected })) }, "Story", icon("chevron", 14)));
    const shown = found.slice(0, PANEL_LIMIT);
    window_.textContent = `${between(Math.max(t0, data.start), Math.min(t1, data.now))} · purse ${fmt.money(purseAt(lane, Math.min(t1, data.now)))} · ${fmt.plural(found.length, "entry", "entries")}${found.length > shown.length ? `, the first ${shown.length} shown` : ""}`;
    fill(
      entries,
      shown.map(([m, by]) => {
        const [label, text] = describeMarker(m, by, selected);
        return h(
          "li",
          {
            onclick: () => {
              cursor = m.t;
              lanes.setCursor(cursor);
              lanes.centre(m.t);
            },
          },
          h("time", {}, `${moment(m.t)} · ${m.place ? data.places[m.place] ?? m.place : "on the way"}`),
          cast.mention(label),
          text ? h("div", { class: `text${m.kind === "journal" ? " journal" : ""}` }, text) : null,
        );
      }),
    );
  }

  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(() => {
      renderPanel();
      remember();
    }, 120);
  }

  function select(name) {
    selected = name;
    lanes.setSelected(name);
    schedule();
  }

  function onKey(event) {
    if (!lanes) return;
    const target = event.target instanceof Element ? event.target : document.body;
    if (target.closest("input, select, textarea") || event.metaKey || event.ctrlKey || event.altKey) return;
    const keys = {
      ArrowLeft: () => lanes.pan(event.shiftKey ? -1 : -0.25),
      ArrowRight: () => lanes.pan(event.shiftKey ? 1 : 0.25),
      Home: () => lanes.toStart(),
      End: () => lanes.toNow(),
      "+": () => lanes.zoom(0.5),
      "=": () => lanes.zoom(0.5),
      "-": () => lanes.zoom(2),
      0: () => lanes.wholeRun(),
      Escape: () => select(null),
    };
    const action = keys[event.key];
    if (!action) return;
    event.preventDefault();
    action();
  }

  function build() {
    lanes?.destroy();
    lanes = new Lanes({
      timeline: data,
      world,
      cast,
      onSelect: select,
      onMoment: (t) => {
        cursor = t;
        lanes.setCursor(t);
        schedule();
      },
      onView: () => schedule(),
    });
    lanes.setSelected(selected);
    lanes.setCursor(cursor);
    const control = (glyph, label, action) => h("button", { type: "button", class: "icon-btn", title: label, "aria-label": label, onclick: action }, icon(glyph, 18));
    const controls = h(
      "div",
      { class: "lanes-controls" },
      h("button", { type: "button", class: "ghost small", onclick: () => lanes.wholeRun() }, "Whole run"),
      h("button", { type: "button", class: "ghost small", onclick: () => lanes.oneDay() }, "Day"),
      control("chevronLeft", "Earlier (←)", () => lanes.pan(-0.5)),
      control("chevron", "Later (→)", () => lanes.pan(0.5)),
      control("minus", "Zoom out (−)", () => lanes.zoom(2)),
      control("plus", "Zoom in (+)", () => lanes.zoom(0.5)),
      cursor !== null ? h("a", { class: "ghost small", href: href(sibling({ ...route, query: { t: stamp(Math.floor(cursor)) } }, "town", { query: { agent: selected } })) }, icon("map", 15), "Watch in town") : null,
    );
    legendBox.querySelector(".lanes-legend")?.remove();
    legendBox.append(legend(readColours()));
    fill(
      page,
      h(
        "header",
        { class: "page-head spread" },
        h("div", {}, h("h1", {}, "Timeline"), h("p", { class: "lede" }, "Everyone's days side by side, one lane each: marks for what each did (tasks, money, social life and the body), whom it talked with, what it was doing and where, and its purse. Scroll or pinch to zoom, drag to move, use the strip at the top to jump across the run, and pick a lane to read its entries.")),
        controls,
      ),
      legendBox,
      h("div", { class: "lanes-grid" }, h("div", { class: "card lanes-card" }, lanes.el), panel),
    );
    const from = Number(route.query.from);
    const to = Number(route.query.to);
    requestAnimationFrame(() => {
      if (route.query.from && route.query.to && to > from) lanes.setView(from, to, true);
      else if (cursor !== null) {
        const day = livedDay(data.days, cursor);
        lanes.setView(day.start, day.start + DAY, true);
      } else lanes.wholeRun();
      renderPanel();
    });
  }

  async function load() {
    page.replaceChildren(h("div", { class: "loading" }, "Loading the timeline…"));
    try {
      data = await source.timeline();
      if (!data.residents.length) return fill(page, h("div", { class: "card" }, emptyState("This run has no residents.")));
      build();
    } catch (error) {
      fill(page, h("div", { class: "card" }, emptyState("The timeline could not be loaded.", error.message)));
      ctx.fail(error);
    }
  }

  document.addEventListener("keydown", onKey);
  load();
  return {
    update(next) {
      route = next;
      const wanted = parseStamp(next.query.t);
      if (wanted !== null && wanted !== cursor && lanes) {
        cursor = wanted;
        lanes.setCursor(cursor);
      }
      const agent = cast.has(next.query.agent) ? next.query.agent : null;
      if (agent !== selected && lanes) {
        selected = agent;
        lanes.setSelected(selected);
        renderPanel();
      }
      return true;
    },
    async live({ changes }) {
      if (!changes?.timeline || !lanes) return;
      const before = data;
      data = await source.timeline();
      const whole = lanes.t0 <= before.start && lanes.t1 >= before.now;
      const following = lanes.t1 >= before.now;
      lanes.setData(data);
      if (whole) lanes.wholeRun();
      else if (following) lanes.setView(lanes.t0 + (data.now - before.now), lanes.t1 + (data.now - before.now), true);
      renderPanel();
    },
    destroy() {
      clearTimeout(timer);
      document.removeEventListener("keydown", onKey);
      lanes?.destroy();
    },
  };
}
