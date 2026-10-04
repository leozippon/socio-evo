// The town, alive: the map, the timeline and the panels, all showing one moment that is
// reconstructed from the event log. Event days load on demand, the needed prefix first and the
// rest behind it; playing applies only the events it crosses; a live run is followed only while
// the viewer stays at its newest moment.
//
// On a wide screen the panels stand beside the map and the timeline under it. On a narrower one
// the map fills the screen and a bottom sheet holds the timeline, always in reach of a thumb,
// with the panels above it: dragged or tapped up to read, down to watch.

import { calendarOf, dayOf, dayStart, hhmm, minuteOf, parseStamp, slotAt, stamp } from "../clock.js";
import { fill, fmt, h } from "../dom.js";
import { icon } from "../icons.js";
import { Replay } from "../replay.js";
import { href, sibling } from "../router.js";
import { actionSummary, sceneName } from "../town/events.js";
import { TiesPanel } from "../town/graph.js";
import { TownMap } from "../town/map.js";
import { BoardPanel, ChroniclePanel, FeedPanel, NowPanel, PeoplePanel } from "../town/panels.js";
import { SPEEDS, Timeline } from "../town/timeline.js";
import { placeById, shortName } from "../world.js";

const QUIET = 12; // simulated minutes without events that playback crosses quickly
const SKIP_SPEED = 240; // simulated minutes per second across quiet stretches
const PANELS = [
  ["now", "Now"],
  ["people", "People"],
  ["feed", "Feed"],
  ["board", "Board"],
  ["ties", "Ties"],
  ["day", "Day"],
];
const WIDE = matchMedia("(min-width: 1000px)");

export function mountTown(root, ctx) {
  const { source, world, cast } = ctx;
  let route = ctx.route;
  const cal = calendarOf(world);
  const places = placeById(world);
  const replay = new Replay(world);
  const lookups = { tasks: replay.tasks, places };
  const running = () => source.doc.status === "running";
  const liveEnd = () => source.doc.last_time ?? 0;

  const view = {
    time: 0,
    playing: false,
    speed: SPEEDS.includes(Number(route.query.speed)) ? Number(route.query.speed) : 3,
    truth: route.query.truth !== "0",
    selected: cast.has(route.query.agent) ? route.query.agent : null,
    only: route.query.only === "1",
    panel: PANELS.some(([key]) => key === route.query.panel) ? route.query.panel : "now",
    follow: false,
  };
  let measures = null;
  let raf = 0;
  let last = performance.now();
  let lastPanels = 0;
  let lastUrl = 0;
  let shownSeq = null;
  let destroyed = false;
  let ready = false; // the moment asked for has been shown, so the URL may follow the view

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
      paint(false);
      sync();
    },
    onTruth: () => setTruth(!view.truth),
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
    board: new BoardPanel({ replay }),
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
  /** Heights of the sheet's resting states, from the town's height and the sheet's own parts. */
  function measureSheet() {
    if (WIDE.matches) {
      dock.style.transform = "";
      page.style.removeProperty("--peek");
      map.setInset(0);
      return;
    }
    sheet.full = page.clientHeight;
    sheet.peek = grip.offsetHeight + timeline.el.offsetHeight + panelTabs.offsetHeight;
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
  /** Drag the sheet by its grip or its tab bar; a tap on the grip opens or closes it. */
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
      // Rest where the finger was heading, or at the nearest state.
      const states = ["peek", "half", "full"];
      const projected = sheet.height - (drag.velocity ?? 0) * 180;
      setSheet(states.reduce((best, state) => (Math.abs(restingHeight(state) - projected) < Math.abs(restingHeight(best) - projected) ? state : best), "peek"));
    };
    target.addEventListener("pointerup", end);
    target.addEventListener("pointercancel", end);
  }
  sheetDrag(grip, { tap: true });
  sheetDrag(panelTabs, { tap: false });
  // A tap on a tab of a closed sheet opens it; the click handler shows the panel.
  const layout = new ResizeObserver(() => measureSheet());
  layout.observe(page);
  layout.observe(timeline.el);
  const onMedia = () => measureSheet();
  WIDE.addEventListener("change", onMedia);

  // The moment ----------------------------------------------------------------------------------
  function phase(state) {
    const minute = minuteOf(state.time);
    if (state.seq < 0) return "Before the first day";
    const kinds = new Set(Object.values(state.scenes).map((scene) => scene.kind));
    if (kinds.has("planning")) return "Morning: everyone plans the day";
    if (kinds.has("review")) return "Evening: everyone rates the people they met";
    if (minute < cal.start) return "Night";
    if (minute >= cal.end) return state.ended ? "Night: diaries, reflection and evolution" : "Night: everyone goes home";
    const slot = slotAt(cal, minute);
    return slot ? `${slot.name[0].toUpperCase()}${slot.name.slice(1)}, ${hhmm(slot.start)}–${hhmm(slot.end)}` : "Early morning";
  }

  function moment() {
    const state = replay.state;
    const day = dayOf(state.time);
    return {
      state,
      world,
      cast,
      places,
      lookups,
      dayEvents: replay.eventsOf(day).filter((e) => e.seq <= state.seq),
      dayStart: replay.snapshots.get(state.day)?.balances ?? null,
      truth: view.truth,
      selected: view.selected,
      follow: view.only,
      phase: phase(state),
      select: (name) => select(name),
    };
  }

  /** What the map shows besides positions: who speaks where, who is deciding right now. */
  function mapFrame(m, effects) {
    const turn = world.scenes.turn_minutes;
    const recent = m.state.time - 2 * turn;
    const speech = new Map();
    for (const e of m.dayEvents) {
      if (e.kind !== "speech" || e.time < recent || m.state.locations[e.actor] !== e.place) continue;
      if (!speech.has(e.place)) speech.set(e.place, []);
      speech.get(e.place).push({ agent: e.actor, text: e.payload.utterance, to: e.payload.to });
    }
    const thinking = new Set();
    if (view.truth) for (const e of m.dayEvents) if (e.kind === "decision" && m.state.time - e.time < turn) thinking.add(e.actor);
    const scenes = new Map();
    for (const scene of Object.values(m.state.scenes)) {
      if (!scene.place) continue;
      const round = Math.floor((m.state.time - scene.start) / turn) + 1;
      const label = scene.kind === "work" ? `working · round ${Math.min(round, world.scenes.work_rounds)}` : scene.kind === "conversation" ? `talking · ${fmt.plural(scene.present.length, "person", "people")}` : sceneName(scene.kind).toLowerCase();
      scenes.set(scene.place, { kind: scene.kind, present: scene.present, label });
    }
    const key = `${m.state.seq}|${Math.floor(m.state.time / turn)}|${view.truth}`;
    return { state: m.state, minute: minuteOf(m.state.time), selected: view.selected, speech, thinking, scenes, effects, key };
  }

  /** The selected agent, and in the truth view the thought behind its latest decision today. */
  function renderSelected(m = moment()) {
    selectedBox.hidden = !view.selected;
    if (!view.selected) return fill(selectedBox);
    const agent = cast.agent(view.selected);
    const own = m.dayEvents.findLast((e) => e.kind === "decision" && e.actor === view.selected);
    const place = places.get(m.state.locations[view.selected]);
    fill(
      selectedBox,
      h(
        "div",
        { class: "selected-head" },
        cast.badge(view.selected, 34),
        h("div", { class: "selected-text" }, h("b", {}, agent.name), h("span", { class: "muted" }, `${agent.occupation}${place ? ` · at ${shortName(place)}` : ""}`)),
        h("a", { class: "ghost small", href: href(sibling({ ...route, query: { ...route.query, t: stamp(Math.floor(view.time)) } }, "person", { agent: view.selected })) }, "File", icon("chevron", 14)),
        h("button", { type: "button", class: "icon-btn", "aria-label": "Clear the selection (Escape)", title: "Clear the selection (Escape)", onclick: () => select(null) }, icon("close", 18)),
      ),
      view.truth && own
        ? h(
            "button",
            { type: "button", class: "selected-thought truth", "aria-expanded": "false", title: "Read the whole thought", onclick: (event) => event.currentTarget.setAttribute("aria-expanded", String(event.currentTarget.classList.toggle("open"))) },
            h("span", { class: "truth-tag" }, icon("thought", 13), `thinks, ${hhmm(minuteOf(own.time))} · ${actionSummary(own.payload.action, lookups)}`),
            h("span", { class: "thought-text" }, own.payload.thought),
          )
        : null,
    );
  }

  function refreshPanel(force = false) {
    const m = moment();
    const panel = panels[view.panel];
    if (view.panel === "ties") {
      const through = m.state.ended ? m.state.day : m.state.day - 1;
      if (measures) panel.update(measures.graph, through, view.selected);
      else fill(panel.el, h("div", { class: "loading" }, "Loading the measures…"));
    } else panel.update(m, force);
    if (panelBody.firstChild !== panel.el) panelBody.replaceChildren(panel.el);
  }

  /** Draw the current moment; `walk` lets moved agents walk there. */
  function paint(walk, effects = []) {
    const m = moment();
    const changed = m.state.seq !== shownSeq;
    timeline.setCursor(view.time, { playing: view.playing, follow: view.follow && running(), truth: view.truth, speed: view.speed, phase: m.phase });
    map.update(mapFrame(m, effects), walk);
    if (changed) {
      renderSelected(m);
      if (dayOf(m.state.time) !== dayOf(replay.event(shownSeq ?? -1)?.time ?? -1)) timeline.setDay(replay.eventsOf(dayOf(m.state.time)));
      shownSeq = m.state.seq;
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
        truth: view.truth ? null : "0",
        panel: view.panel === "now" ? null : view.panel,
        only: view.only && view.selected ? "1" : null,
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
          .then((events) => {
            if (destroyed) return;
            replay.load(day, events);
            dayLoaded();
          })
          .finally(() => inflight.delete(day)),
      );
    return inflight.get(day);
  }

  let marksTimer = null;
  function dayLoaded() {
    timeline.setRun({ loaded: new Set(replay.days.keys()) });
    clearTimeout(marksTimer);
    marksTimer = setTimeout(() => {
      const evolution = [];
      const defects = [];
      for (const day of replay.sortedDays())
        for (const e of replay.eventsOf(day)) {
          if (e.kind === "evolution" && e.payload.level !== "L0") evolution.push({ day, agent: e.payload.agent, level: e.payload.level, trigger: e.payload.trigger, subject: e.payload.subject });
          if (e.kind === "defect_discovered") defects.push({ time: e.time, text: e.text });
        }
      timeline.setMarks({ evolution, defects });
    }, 120);
  }

  /**
   * Say that the moment cannot be shown yet, or at all: the map is covered and the panels,
   * which would show some other moment, are marked as not current. Null clears it.
   */
  function unavailable(message, failed = false) {
    map.cover(message, failed);
    page.classList.toggle("stale", Boolean(message));
    page.classList.toggle("failed", failed);
    if (failed) panelBody.replaceChildren(h("div", { class: "panel" }, h("div", { class: "curtain-error" }, icon("alert", 18), message)));
    else if (!message) refreshPanel(true);
  }

  /** Load the days a moment needs, covering the map meanwhile; false if that failed. */
  async function ensure(time) {
    const missing = replay.missing(time);
    if (!missing.length) return true;
    const total = missing.length;
    let done = 0;
    unavailable(`Reconstructing day ${dayOf(time)} from the event log… ${total > 1 ? `loading ${total} days` : "loading it"}`);
    try {
      const queue = [...missing];
      await Promise.all(
        Array.from({ length: Math.min(4, queue.length) }, async () => {
          while (queue.length) {
            await fetchDay(queue.shift());
            done += 1;
            if (total > 1) map.cover(`Reconstructing day ${dayOf(time)} from the event log… ${done} of ${total} days loaded`);
          }
        }),
      );
      unavailable(null);
      return true;
    } catch (error) {
      unavailable(`Could not load the events of this moment: ${error.message}`, true);
      ctx.fail(error);
      return false;
    }
  }

  async function prefetch() {
    for (const day of source.doc.event_days.map((d) => d.day)) {
      if (destroyed) return;
      if (!replay.has(day)) {
        try {
          await fetchDay(day);
        } catch (error) {
          ctx.fail(error);
          return;
        }
      }
    }
  }

  // Moving through time -------------------------------------------------------------------------
  const clampTime = (time) => Math.max(0, Math.min(liveEnd(), time));

  async function seek(time, user = false) {
    time = clampTime(time);
    view.time = time;
    if (user) view.follow = time >= liveEnd();
    if (replay.missing(time).length) {
      view.playing = false;
      timeline.setCursor(time, { playing: false, follow: view.follow && running(), truth: view.truth, speed: view.speed, phase: "" });
      if (!(await ensure(time)) || view.time !== time || destroyed) return;
    } else if (page.classList.contains("failed")) unavailable(null);
    replay.seek(Math.floor(time));
    paint(false);
  }

  function step(unit, direction) {
    view.playing = false;
    if (unit === "moment") {
      const target = direction > 0 ? replay.nextTime(view.time) : replay.previousTime(view.time);
      if (target !== null) seek(target, true);
      else paint(false);
      return;
    }
    const today = dayStart(dayOf(view.time)) + cal.start;
    const target = direction > 0 ? today + 1440 : view.time > today ? today : today - 1440;
    seek(Math.max(cal.start, target), true);
  }

  function togglePlay() {
    if (!view.playing && view.time >= liveEnd() && !running()) seek(dayStart(1) + cal.start);
    view.playing = !view.playing;
    last = performance.now();
    paint(false);
  }

  function frame(now) {
    raf = requestAnimationFrame(frame);
    const dt = Math.min(0.25, (now - last) / 1000);
    last = now;
    map.tick(now);
    if (!view.playing) return;
    const end = liveEnd();
    const next = replay.nextTime(view.time);
    const quiet = next === null || next - view.time > QUIET;
    let time = view.time + dt * (quiet ? Math.max(view.speed, SKIP_SPEED) : view.speed);
    if (next !== null && quiet && time > next) time = next;
    if (time >= end) {
      time = end;
      if (running()) view.follow = true;
      else view.playing = false;
    }
    if (replay.missing(time).length) {
      view.playing = false;
      seek(time).then(() => {
        view.playing = true;
        last = performance.now();
      });
      return;
    }
    const before = replay.state.seq;
    view.time = time;
    replay.seek(Math.floor(time));
    const effects = [];
    if (replay.state.seq > before && replay.state.seq - before < 80)
      for (let seq = before + 1; seq <= replay.state.seq; seq++) {
        const e = replay.event(seq);
        if (e.kind === "payment") effects.push({ agent: e.payload.agent, text: `+${e.payload.amount}`, tone: "good" });
        if (e.kind === "clawback") effects.push({ agent: e.payload.agent, text: `−${e.payload.amount}`, tone: "critical" });
        if (e.kind === "living_cost") effects.push({ agent: e.payload.agent, text: `−${e.payload.amount}`, tone: "muted" });
      }
    paint(true, effects);
  }

  // Choices -------------------------------------------------------------------------------------
  /** Select an agent, or clear the selection; from the map, a narrow screen opens the sheet. */
  function select(name, fromMap = false) {
    view.selected = name === view.selected ? null : name;
    if (!view.selected) view.only = false;
    renderSelected();
    paint(false);
    refreshPanel(true);
    sync();
    if (view.selected && !WIDE.matches) {
      if (fromMap && sheet.state === "peek") setSheet("half");
      map.reveal(view.selected);
    }
  }

  function setTruth(on) {
    view.truth = on;
    renderSelected();
    paint(false);
    refreshPanel(true);
    sync();
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
      Home: () => seek(dayStart(1) + cal.start, true),
      End: () => {
        view.follow = true;
        seek(liveEnd());
      },
      t: () => setTruth(!view.truth),
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
    replay.expect(source.doc.event_days.map((d) => d.day));
    timeline.setRun({ eventDays: source.doc.event_days, last: source.doc.last_time, running: running(), loaded: new Set() });
    renderSelected();
    showPanel(view.panel);
    if (!source.doc.event_days.length) {
      replay.seek(0);
      paint(false);
      map.cover("The run has not recorded its first day yet. The town fills in as it does.");
      return;
    }
    const wanted = parseStamp(route.query.t);
    const initial = wanted ?? (running() ? liveEnd() : dayStart(1) + cal.start);
    view.time = initial;
    view.follow = running() && initial >= liveEnd();
    await seek(initial);
    ready = true;
    sync();
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
      if (cast.has(next.query.agent) !== Boolean(view.selected) || (next.query.agent && next.query.agent !== view.selected)) {
        view.selected = cast.has(next.query.agent) ? next.query.agent : null;
        renderSelected();
      }
      if (wanted !== null && wanted !== view.time) seek(wanted, true);
      return true;
    },
    async live({ changes }) {
      if (!changes) return;
      const days = source.doc.event_days.map((d) => d.day);
      replay.expect(days);
      timeline.setRun({ eventDays: source.doc.event_days, last: source.doc.last_time, running: running(), loaded: new Set(replay.days.keys()) });
      try {
        await Promise.all(changes.days.filter((day) => replay.has(day) || day <= dayOf(view.time) || view.follow).map((day) => fetchDay(day)));
      } catch (error) {
        ctx.fail(error);
      }
      if (changes.measures) measures = await source.measures();
      timeline.setDay(replay.eventsOf(dayOf(view.time)));
      if (view.follow) await seek(liveEnd());
      else {
        replay.seek(Math.floor(view.time));
        paint(false);
      }
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
