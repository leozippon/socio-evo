// The town, alive: the map, the timeline and the panels, all showing one moment of the run's
// timeline, with the entries of that lived day loaded on demand for what was said and done.
// Playing moves through the moments the timeline records and crosses quiet stretches quickly; a
// live run is followed only while the viewer stays at its newest moment.
//
// On a wide screen the panels stand beside the map and the timeline under it. On a narrower one
// the map fills the screen and a bottom sheet holds the timeline, always in reach of a thumb,
// with the panels above it: dragged or tapped up to read, down to watch.

import { DAY, parseHHMM, parseStamp, secondOfDay, stamp } from "../clock.js";
import { fill, fmt, h } from "../dom.js";
import { icon } from "../icons.js";
import { lowerBound, markersBetween, moment as momentOf, purseAt } from "../replay.js";
import { href, sibling } from "../router.js";
import { textFor } from "../town/events.js";
import { TiesPanel } from "../town/graph.js";
import { TownMap } from "../town/map.js";
import { ChroniclePanel, FeedPanel, NowPanel, PeoplePanel, WorkPanel, doing } from "../town/panels.js";
import { SPEEDS, Timeline } from "../town/timeline.js";
import { placeById, shortName } from "../world.js";
import { areasOf } from "./overview.js";

const QUIET = 12 * 60; // simulated seconds without a moment that playback crosses quickly
const SKIP_SPEED = 240 * 60; // simulated seconds per second across quiet stretches
const RECENT = 10 * 60; // seconds of speech and deeds the map keeps in view
const PANELS = [
  ["now", "Now"],
  ["people", "People"],
  ["feed", "Feed"],
  ["work", "Work"],
  ["ties", "Ties"],
  ["day", "Day"],
];
const WIDE = matchMedia("(min-width: 1000px)");
const SIDEWAYS = matchMedia("(orientation: landscape) and (max-height: 500px)"); // a phone held sideways

/** Every moment the timeline records, in order: where a segment, a conversation or a marker begins or ends. */
function momentsOf(data) {
  const found = new Set();
  for (const lane of data.residents) {
    for (const segment of lane.segments) found.add(segment.start).add(segment.end);
    for (const talk of lane.conversations) found.add(talk.start).add(talk.end);
    for (const marker of lane.markers) found.add(marker.t);
  }
  return [...found].sort((a, b) => a - b);
}

export function mountTown(root, ctx) {
  const { source, world, cast } = ctx;
  let route = ctx.route;
  const places = placeById(world);
  const hours = Object.fromEntries(Object.entries(world.day).map(([name, clock]) => [name, parseHHMM(clock)]));
  const running = () => source.doc.status === "running";

  const view = {
    time: 0,
    playing: false,
    speed: SPEEDS.includes(Number(route.query.speed)) ? Number(route.query.speed) : 3,
    selected: cast.has(route.query.agent) ? route.query.agent : null,
    only: route.query.only === "1",
    lens: route.query.as === "1", // read what the selected resident was told in its own wording
    panel: PANELS.some(([key]) => key === route.query.panel) ? route.query.panel : "now",
    follow: false,
  };
  let data = null; // the timeline document
  let moments = [];
  let measures = null;
  const loaded = new Map(); // lived day -> its entries
  let raf = 0;
  let last = performance.now();
  let lastPanels = 0;
  let lastUrl = 0;
  let shownKey = null;
  let destroyed = false;
  let ready = false; // the moment asked for has been shown, so the URL may follow the view

  const liveEnd = () => data?.now ?? 0;

  // Layout ------------------------------------------------------------------------------------
  const map = new TownMap({ world, cast, onSelect: (name) => select(name, true) });
  const timeline = new Timeline({
    world,
    cast,
    onSeek: (time) => seek(time, true),
    onPlay: () => togglePlay(),
    onStep: (unit, direction) => step(unit, direction),
    onSpeed: (speed) => {
      view.speed = speed;
      paint();
      sync();
    },
    onLive: () => {
      view.follow = true;
      seek(liveEnd());
    },
  });
  const panels = {
    now: new NowPanel(),
    people: new PeoplePanel(),
    feed: new FeedPanel({
      onFollow: (on) => {
        view.only = on;
        sync();
        refreshPanel(true);
      },
    }),
    work: new WorkPanel(),
    ties: new TiesPanel({ cast, onSelect: (name) => select(name) }),
    day: new ChroniclePanel({ onJump: (time) => seek(time, true) }),
  };
  const panelTabs = h(
    "div",
    { class: "panel-tabs", role: "tablist", "aria-label": "Panels" },
    PANELS.map(([key, label]) => h("button", { type: "button", role: "tab", "data-panel": key, "aria-selected": String(view.panel === key), onclick: () => showPanel(key, true) }, label)),
  );
  const panelBody = h("div", { class: "panel-body", role: "tabpanel" });
  const selectedBox = h("div", { class: "selected-box", hidden: true });
  const grip = h("button", { type: "button", class: "sheet-grip", "aria-label": "Show or hide the panels" }, h("span"));
  const side = h("aside", { class: "town-side", "aria-label": "The moment in detail" }, selectedBox, panelTabs, panelBody);
  const dock = h("div", { class: "town-dock" }, grip, timeline.el, side);
  const page = h("div", { class: "town" }, map.el, dock);
  root.append(page);

  // The sheet (narrow screens only) -------------------------------------------------------------
  const sheet = { state: "peek", height: 0, full: 0, peek: 0, drag: null };
  function measureSheet() {
    if (WIDE.matches) {
      dock.style.transform = "";
      page.style.removeProperty("--peek");
      map.setInset(0);
      return;
    }
    sheet.full = page.clientHeight;
    const end = SIDEWAYS.matches ? timeline.controls : panelTabs;
    sheet.peek = end.offsetTop + end.offsetHeight;
    page.style.setProperty("--peek", `${sheet.peek}px`);
    setSheet(sheet.state, false);
  }
  const restingHeight = (state) => ({ peek: sheet.peek, half: Math.max(sheet.peek + 220, Math.round(sheet.full * 0.56)), full: sheet.full })[state];
  function setSheet(state, animate = true) {
    if (WIDE.matches) return;
    sheet.state = state;
    sheet.height = Math.min(sheet.full, restingHeight(state));
    dock.classList.toggle("animate", animate);
    dock.style.transform = `translateY(${sheet.full - sheet.height}px)`;
    dock.dataset.state = state;
    grip.setAttribute("aria-expanded", String(state !== "peek"));
    map.setInset(sheet.height - sheet.peek + 20);
  }
  function sheetDrag(target, { tap }) {
    target.addEventListener("pointerdown", (event) => {
      if (WIDE.matches || (event.pointerType === "mouse" && event.button !== 0)) return;
      sheet.drag = { y: event.clientY, height: sheet.height, moved: false, id: event.pointerId, at: performance.now(), last: event.clientY };
    });
    target.addEventListener("pointermove", (event) => {
      const drag = sheet.drag;
      if (!drag || drag.id !== event.pointerId) return;
      const dy = event.clientY - drag.y;
      if (!drag.moved && Math.abs(dy) < 8) return;
      if (!drag.moved) target.setPointerCapture(event.pointerId);
      drag.moved = true;
      drag.velocity = (event.clientY - drag.last) / Math.max(1, performance.now() - drag.at);
      drag.last = event.clientY;
      drag.at = performance.now();
      sheet.height = Math.max(sheet.peek, Math.min(sheet.full, drag.height - dy));
      dock.classList.remove("animate");
      dock.style.transform = `translateY(${sheet.full - sheet.height}px)`;
    });
    const end = (event) => {
      const drag = sheet.drag;
      if (!drag || drag.id !== event.pointerId) return;
      sheet.drag = null;
      if (!drag.moved) return tap && event.type === "pointerup" && setSheet(sheet.state === "peek" ? "half" : "peek");
      const states = ["peek", "half", "full"];
      const projected = sheet.height - (drag.velocity ?? 0) * 180;
      setSheet(states.reduce((best, state) => (Math.abs(restingHeight(state) - projected) < Math.abs(restingHeight(best) - projected) ? state : best), "peek"));
    };
    target.addEventListener("pointerup", end);
    target.addEventListener("pointercancel", end);
  }
  sheetDrag(grip, { tap: true });
  sheetDrag(panelTabs, { tap: false });
  const layout = new ResizeObserver(() => measureSheet());
  layout.observe(page);
  layout.observe(timeline.el);
  const onMedia = () => measureSheet();
  WIDE.addEventListener("change", onMedia);

  // The moment ----------------------------------------------------------------------------------
  function phase(time, state) {
    const second = secondOfDay(time);
    const awake = Object.values(state.residents).filter((found) => found.segment && found.segment.kind !== "sleep").length;
    const up = `${awake} of ${cast.names.length} up`;
    if (second < hours.forced_sleep) return `Past midnight · ${up}`;
    if (second < hours.checkpoint) return `Forced sleep · ${up}`;
    if (second < hours.forced_wake) return `Night · ${up}`;
    if (second < 12 * 3600) return `Morning · ${up}`;
    if (second < 18 * 3600) return `Afternoon · ${up}`;
    return `Evening · ${up}`;
  }

  function moment() {
    const state = momentOf(data, view.time);
    const day = state.day;
    const entries = loaded.get(day.day) ?? [];
    return {
      time: Math.floor(view.time),
      day,
      state,
      world,
      cast,
      places,
      dayEntries: entries.slice(0, lowerBound(entries, Math.floor(view.time) + 1, (e) => e.sim_time)),
      dayStartPurses: Object.fromEntries(data.residents.map((lane) => [lane.name, purseAt(lane, day.start)])),
      reader: view.lens && view.selected ? view.selected : null,
      selected: view.selected,
      follow: view.only,
      phase: phase(view.time, state),
      select: (name) => select(name),
    };
  }

  /** What the map shows besides positions: who speaks where, what each just did, the notices. */
  function mapFrame(m, effects) {
    const recent = m.time - RECENT;
    const speech = new Map();
    for (const e of m.dayEntries) {
      if (e.kind !== "speech" || e.sim_time < recent) continue;
      const found = m.state.residents[e.actor];
      const here = found && !found.moving ? found.segment?.place : null;
      if (!here) continue;
      if (!speech.has(here)) speech.set(here, []);
      speech.get(here).push({ agent: e.actor, text: e.payload.text, to: e.payload.to, private: Boolean(e.payload.private) });
    }
    const scenes = new Map();
    for (const place of world.places) {
      const here = Object.entries(m.state.residents).filter(([, found]) => !found.moving && found.segment?.place === place.id);
      if (!here.length) continue;
      const working = here.filter(([, found]) => found.segment.kind === "work").length;
      const talking = here.filter(([, found]) => found.conversation).length;
      const asleep = here.filter(([, found]) => found.segment.kind === "sleep").length;
      const bits = [];
      if (working) bits.push(`${working} working`);
      if (talking) bits.push(`${talking} talking`);
      if (asleep) bits.push(`${asleep} asleep`);
      if (bits.length) scenes.set(place.id, { label: bits.join(" · ") });
    }
    const deeds = new Map();
    for (const lane of data.residents) {
      for (const mk of markersBetween(lane, recent, m.time)) {
        const deed = deedOf(mk);
        if (deed) deeds.set(lane.name, deed);
      }
    }
    const notices = m.dayEntries
      .filter((e) => e.sim_time >= m.time - 15 * 60 && ["forced_sleep", "expiry", "exchange_pairing", "meeting", "board_posted"].includes(e.kind))
      .slice(-3)
      .map((e) => ({ icon: e.kind === "forced_sleep" || e.kind === "expiry" ? "alert" : e.kind === "board_posted" ? "board" : "pair", tone: e.kind === "forced_sleep" || e.kind === "expiry" ? "critical" : null, text: textFor(e, m.reader) }));
    const key = `${m.time}|${m.dayEntries.length}|${m.reader}`;
    return { state: m.state, second: secondOfDay(m.time), selected: view.selected, speech, scenes, deeds, notices, effects, key };
  }

  /** What a marker says in a few words by the resident, with its tone. */
  function deedOf(mk) {
    switch (mk.kind) {
      case "claim":
        return { icon: "board", text: `claims task ${mk.task}` };
      case "submission":
        return mk.resolved === undefined ? { icon: "check", text: `hands in task ${mk.task}` } : { icon: mk.resolved ? "check" : "cross", text: mk.resolved ? `task ${mk.task} accepted` : `task ${mk.task} not accepted`, tone: mk.resolved ? "good" : "serious" };
      case "payment":
        return { icon: "coin", text: `paid ${fmt.money(mk.amount)} for task ${mk.task}`, tone: "good" };
      case "abandon":
        return { icon: "cross", text: `gives up task ${mk.task}`, tone: "serious" };
      case "expiry":
        return { icon: "clock", text: `task ${mk.task} ran out`, tone: "critical" };
      case "gift":
        return { icon: "coin", text: `hands ${mk.to} ${fmt.money(mk.amount)}` };
      case "skill_shared":
        return { icon: "spark", text: `passes “${mk.skill}” to ${mk.to}` };
      case "rating":
        return { icon: "star", text: `rates ${mk.rated} ${mk.score} of 5` };
      case "journal":
        return { icon: "book", text: "to bed, journal written" };
      case "forced_sleep":
        return { icon: "alert", text: "falls asleep at the forced hour", tone: "critical" };
      default:
        return null;
    }
  }

  /** The selected resident: who, where, doing what, and whose wording the panels read. */
  function renderSelected(m = moment()) {
    selectedBox.hidden = !view.selected;
    if (!view.selected) return fill(selectedBox);
    const found = m.state.residents[view.selected];
    const home = places.get(cast.agent(view.selected).home);
    fill(
      selectedBox,
      h(
        "div",
        { class: "selected-head" },
        cast.badge(view.selected, 34),
        h("div", { class: "selected-text" }, h("b", {}, view.selected), h("span", { class: "muted" }, `${home ? shortName(home) : ""} · ${fmt.money(found.purse)}`), h("span", { class: "selected-job" }, doing(found, places))),
        h("a", { class: "ghost small", href: href(sibling({ ...route, query: { ...route.query, t: stamp(Math.floor(view.time)) } }, "person", { agent: view.selected })) }, "File", icon("chevron", 14)),
        h("button", { type: "button", class: "icon-btn", "aria-label": "Clear the selection (Escape)", title: "Clear the selection (Escape)", onclick: () => select(null) }, icon("close", 18)),
      ),
      h(
        "div",
        { class: "seg lens", role: "group", "aria-label": "Whose wording to read" },
        h("button", { type: "button", "aria-pressed": String(!view.lens), title: "Every entry as the town's people read it", onclick: () => setLens(false) }, "As everyone read it"),
        h("button", { type: "button", "aria-pressed": String(view.lens), title: `What ${view.selected} was told, in ${view.selected}'s own wording`, onclick: () => setLens(true) }, `As ${view.selected} read it`),
      ),
    );
  }

  function setLens(on) {
    view.lens = on;
    renderSelected();
    paint();
    refreshPanel(true);
    sync();
  }

  function refreshPanel(force = false) {
    const m = moment();
    const panel = panels[view.panel];
    if (view.panel === "ties") {
      if (!measures) {
        panelBody.replaceChildren(h("div", { class: "panel" }, h("div", { class: "loading" }, "Loading the measures…")));
        return;
      }
      panel.update(measures.graph, m.day.day, view.selected);
    } else panel.update(m, force);
    if (panelBody.firstChild !== panel.el) panelBody.replaceChildren(panel.el);
  }

  /** Draw the current moment. */
  function paint(effects = []) {
    const m = moment();
    const key = `${m.time}|${m.dayEntries.length}`;
    const changed = key !== shownKey;
    timeline.setCursor(view.time, { playing: view.playing, follow: view.follow && running(), speed: view.speed, phase: m.phase });
    map.update(mapFrame(m, effects));
    if (changed) {
      renderSelected(m);
      if (!shownKey || m.day.day !== Number(shownKey.split("|")[2])) timeline.setDay(loaded.get(m.day.day) ?? []);
      shownKey = `${key}|${m.day.day}`;
    }
    const now = performance.now();
    if (changed && (!view.playing || now - lastPanels > 250)) {
      lastPanels = now;
      refreshPanel();
    }
    if (!view.playing || now - lastUrl > 1000) {
      lastUrl = now;
      sync();
    }
  }

  function sync() {
    if (!ready) return;
    route = {
      ...route,
      query: {
        ...route.query,
        t: stamp(Math.floor(view.time)),
        agent: view.selected,
        panel: view.panel === "now" ? null : view.panel,
        only: view.only && view.selected ? "1" : null,
        as: view.lens && view.selected ? "1" : null,
        speed: view.speed === 3 ? null : String(view.speed),
      },
    };
    ctx.remember(route);
  }

  // Loading ------------------------------------------------------------------------------------
  const inflight = new Map();
  function fetchDay(day) {
    if (!inflight.has(day))
      inflight.set(
        day,
        source
          .eventDay(day)
          .then((entries) => {
            if (destroyed) return;
            loaded.set(day, entries);
            timeline.setRun({ loaded: new Set(loaded.keys()) });
          })
          .finally(() => inflight.delete(day)),
      );
    return inflight.get(day);
  }

  const dayOf = (time) => momentOf(data, time).day;
  const hasDay = (time) => {
    const day = dayOf(time);
    return loaded.has(day.day) || !source.doc.event_days.some((found) => found.day === day.day);
  };

  function unavailable(message, failed = false) {
    map.cover(message, failed);
    page.classList.toggle("stale", Boolean(message));
    page.classList.toggle("failed", failed);
    if (failed) panelBody.replaceChildren(h("div", { class: "panel" }, h("div", { class: "curtain-error" }, icon("alert", 18), message)));
    else if (!message) refreshPanel(true);
  }

  /** Load the entries of the lived day of `time`, covering the map meanwhile; false if that failed. */
  async function ensure(time) {
    if (hasDay(time)) return true;
    const day = dayOf(time);
    unavailable(`Loading the entries of day ${day.day}…`);
    try {
      await fetchDay(day.day);
      unavailable(null);
      return true;
    } catch (error) {
      unavailable(`Could not load the entries of day ${day.day}: ${error.message}`, true);
      ctx.fail(error);
      return false;
    }
  }

  async function prefetch() {
    for (const found of source.doc.event_days) {
      if (destroyed) return;
      if (!loaded.has(found.day)) {
        try {
          await fetchDay(found.day);
        } catch (error) {
          ctx.fail(error);
          return;
        }
      }
    }
  }

  function marks() {
    const forced = data.residents.flatMap((lane) => lane.markers.filter((mk) => mk.kind === "forced_sleep").map((mk) => ({ time: mk.t, text: `${lane.name} fell asleep at the forced hour` })));
    timeline.setMarks({ rewrites: [], forced });
    Promise.all(cast.names.map((name) => source.versions(name))).then((histories) => {
      if (destroyed) return;
      const rewrites = [];
      histories.forEach((history, i) => {
        for (const version of history.versions) {
          if (version.day < 1) continue;
          const areas = areasOf(version);
          for (const area of ["memory", "skills"]) if (areas.has(area)) rewrites.push({ day: version.day, agent: cast.names[i], area, files: version.changes.map((c) => c.path) });
        }
      });
      timeline.setMarks({ rewrites, forced });
    }, ctx.fail);
  }

  // Moving through time -------------------------------------------------------------------------
  const clampTime = (time) => Math.max(data.start, Math.min(liveEnd(), time));

  async function seek(time, user = false) {
    time = clampTime(time);
    view.time = time;
    if (user) view.follow = time >= liveEnd();
    if (!hasDay(time)) {
      view.playing = false;
      timeline.setCursor(time, { playing: false, follow: view.follow && running(), speed: view.speed, phase: "" });
      if (!(await ensure(time)) || view.time !== time || destroyed) return;
    } else if (page.classList.contains("failed")) unavailable(null);
    paint();
  }

  const nextMoment = (time) => moments[lowerBound(moments, Math.floor(time) + 1, (t) => t)] ?? null;
  const previousMoment = (time) => moments[lowerBound(moments, time, (t) => t) - 1] ?? null;

  function step(unit, direction) {
    view.playing = false;
    if (unit === "moment") {
      const target = direction > 0 ? nextMoment(view.time) : previousMoment(view.time);
      if (target !== null) seek(target, true);
      else paint();
      return;
    }
    const day = dayOf(view.time);
    const target = direction > 0 ? day.start + DAY : view.time > day.start ? day.start : day.start - DAY;
    seek(target, true);
  }

  function togglePlay() {
    if (!view.playing && view.time >= liveEnd() && !running()) seek(data.start);
    view.playing = !view.playing;
    last = performance.now();
    paint();
  }

  function frame(now) {
    raf = requestAnimationFrame(frame);
    const dt = Math.min(0.25, (now - last) / 1000);
    last = now;
    map.tick(now);
    if (!view.playing || !data) return;
    const end = liveEnd();
    const next = nextMoment(view.time);
    const quiet = next === null || next - view.time > QUIET;
    let time = view.time + dt * (quiet ? Math.max(view.speed * 60, SKIP_SPEED) : view.speed * 60);
    if (next !== null && quiet && time > next) time = next;
    if (time >= end) {
      time = end;
      if (running()) view.follow = true;
      else view.playing = false;
    }
    if (!hasDay(time)) {
      view.playing = false;
      seek(time).then(() => {
        view.playing = true;
        last = performance.now();
      });
      return;
    }
    const before = view.time;
    view.time = time;
    const effects = [];
    for (const lane of data.residents)
      for (const mk of markersBetween(lane, before, time)) {
        if (mk.kind === "payment") effects.push({ agent: lane.name, text: `+${mk.amount}`, tone: "good" });
        if (mk.kind === "gift") effects.push({ agent: lane.name, text: `−${mk.amount}`, tone: "muted" }, { agent: mk.to, text: `+${mk.amount}`, tone: "good" });
      }
    for (const e of loaded.get(dayOf(time).day) ?? []) if (e.kind === "settlement" && e.sim_time > before && e.sim_time <= time) effects.push({ agent: e.actor, text: `−${e.payload.living_cost}`, tone: "muted" });
    paint(effects);
  }

  // Choices -------------------------------------------------------------------------------------
  function select(name, fromMap = false) {
    view.selected = name === view.selected ? null : name;
    if (!view.selected) view.only = false;
    renderSelected();
    paint();
    refreshPanel(true);
    sync();
    if (view.selected && !WIDE.matches) {
      if (fromMap && sheet.state === "peek") setSheet("half");
      map.reveal(view.selected);
    }
  }

  function showPanel(key, user = false) {
    view.panel = key;
    for (const tab of panelTabs.children) tab.setAttribute("aria-selected", String(tab.dataset.panel === key));
    refreshPanel(true);
    sync();
    if (user && !WIDE.matches && sheet.state === "peek") setSheet("half");
  }

  function onKey(event) {
    const target = event.target instanceof Element ? event.target : document.body;
    if (target.closest("input, select, textarea") || event.metaKey || event.ctrlKey || event.altKey) return;
    const keys = {
      " ": () => togglePlay(),
      ArrowRight: () => step(event.shiftKey ? "day" : "moment", 1),
      ArrowLeft: () => step(event.shiftKey ? "day" : "moment", -1),
      Home: () => seek(data.start, true),
      End: () => {
        view.follow = true;
        seek(liveEnd());
      },
      Escape: () => (view.selected ? select(null) : setSheet("peek")),
      "+": () => map.zoomBy(1.6),
      "=": () => map.zoomBy(1.6),
      "-": () => map.zoomBy(1 / 1.6),
      0: () => map.fitView(true),
    };
    const action = keys[event.key];
    if (!action) return;
    if (event.key === " " && target.closest("button, a, summary")) return;
    event.preventDefault();
    action();
  }

  // Start ----------------------------------------------------------------------------------------
  async function start() {
    try {
      data = await source.timeline();
    } catch (error) {
      map.cover(`The timeline could not be loaded: ${error.message}`, true);
      ctx.fail(error);
      return;
    }
    moments = momentsOf(data);
    timeline.setRun({ days: data.days, last: data.now, running: running(), loaded: new Set() });
    marks();
    if (!source.doc.event_days.length) {
      view.time = data.start;
      paint();
      map.cover("The run has not recorded its first entry yet. The town fills in as it does.");
      return;
    }
    const wanted = parseStamp(route.query.t);
    const initial = wanted ?? (running() ? liveEnd() : data.start);
    view.time = clampTime(initial);
    view.follow = running() && initial >= liveEnd();
    await seek(view.time);
    ready = true;
    sync();
    // A shared address that names a panel or a resident is read for them: on a phone the
    // sheet opens to show the panel, as it does when the reader asks for one.
    if (!WIDE.matches && (view.panel !== "now" || view.selected)) setSheet("half");
    source.measures().then((found) => {
      measures = found;
      if (view.panel === "ties") refreshPanel(true);
    }, ctx.fail);
    prefetch();
  }

  document.addEventListener("keydown", onKey);
  raf = requestAnimationFrame(frame);
  start();

  return {
    update(next) {
      const wanted = parseStamp(next.query.t);
      route = next;
      if (!data) return true;
      if (cast.has(next.query.agent) !== Boolean(view.selected) || (next.query.agent && next.query.agent !== view.selected)) {
        view.selected = cast.has(next.query.agent) ? next.query.agent : null;
        renderSelected();
      }
      if (wanted !== null && wanted !== view.time) seek(wanted, true);
      const panel = PANELS.some(([key]) => key === next.query.panel) ? next.query.panel : "now";
      if (panel !== view.panel) showPanel(panel);
      if ((next.query.as === "1") !== view.lens) setLens(next.query.as === "1");
      return true;
    },
    async live({ changes }) {
      if (!changes || !data) return;
      try {
        if (changes.timeline) {
          data = await source.timeline();
          moments = momentsOf(data);
          marks();
        }
        timeline.setRun({ days: data.days, last: data.now, running: running(), loaded: new Set(loaded.keys()) });
        for (const day of changes.dropped) loaded.delete(day);
        await Promise.all(changes.days.filter((day) => loaded.has(day)).map((day) => fetchDay(day)));
        if (changes.measures) measures = await source.measures();
      } catch (error) {
        ctx.fail(error);
      }
      shownKey = null;
      if (view.follow) await seek(liveEnd());
      else paint();
      if (view.panel === "ties") refreshPanel(true);
    },
    destroy() {
      destroyed = true;
      cancelAnimationFrame(raf);
      document.removeEventListener("keydown", onKey);
      WIDE.removeEventListener("change", onMedia);
      layout.disconnect();
      map.destroy();
      timeline.destroy();
      panels.ties.destroy();
    },
  };
}

