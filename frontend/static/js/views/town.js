// The town, alive: the map, the cast, the timeline and the panels, all showing one moment that
// is reconstructed from the event log. Event days load on demand, the needed prefix first and
// the rest behind it; playing applies only the events it crosses; a live run is followed only
// while the viewer stays at its newest moment.

import { calendarOf, dayOf, dayStart, hhmm, minuteOf, parseStamp, slotAt, stamp } from "../clock.js";
import { fill, fmt, h } from "../dom.js";
import { icon } from "../icons.js";
import { Replay, holdings } from "../replay.js";
import { href, sibling } from "../router.js";
import { actionSummary } from "../town/events.js";
import { TiesPanel } from "../town/graph.js";
import { TownMap } from "../town/map.js";
import { BoardPanel, ChroniclePanel, FeedPanel, NowPanel } from "../town/panels.js";
import { SPEEDS, Timeline } from "../town/timeline.js";
import { placeById, shortName } from "../world.js";

const QUIET = 12; // simulated minutes without events that playback crosses quickly
const SKIP_SPEED = 240; // simulated minutes per second across quiet stretches
const PANELS = [
  ["now", "Now", "thought"],
  ["feed", "Feed", "speech"],
  ["board", "Board", "board"],
  ["ties", "Ties", "people"],
  ["day", "Day", "book"],
];

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
  const map = new TownMap({
    world,
    cast,
    onSelect: (name) => select(name),
    fit: () => (window.innerWidth > 1100 ? stage.clientHeight - castBar.offsetHeight - timeline.el.offsetHeight - 22 : null),
  });
  const timeline = new Timeline({
    world,
    cast,
    onSeek: (time) => seek(time, true),
    onPlay: () => togglePlay(),
    onStep: (unit, direction) => step(unit, direction),
    onSpeed: (speed) => {
      view.speed = speed;
      paint(false);
    },
    onTruth: () => setTruth(!view.truth),
    onLive: () => {
      view.follow = true;
      seek(liveEnd());
    },
  });
  const castBar = h("div", { class: "cast-bar", role: "list", "aria-label": "The people of the town" });
  const panels = {
    now: new NowPanel(),
    feed: new FeedPanel({
      onFollow: (on) => {
        view.only = on;
        sync(true);
        refreshPanel(true);
      },
    }),
    board: new BoardPanel({ replay }),
    ties: new TiesPanel({ cast, onSelect: (name) => select(name) }),
    day: new ChroniclePanel({ onJump: (time) => seek(time, true) }),
  };
  const panelTabs = h(
    "div",
    { class: "panel-tabs", role: "tablist" },
    PANELS.map(([key, label, glyph]) => h("button", { type: "button", role: "tab", "data-panel": key, "aria-selected": String(view.panel === key), onclick: () => showPanel(key) }, icon(glyph, 15), label)),
  );
  const panelBody = h("div", { class: "panel-body", role: "tabpanel" });
  const selectedBox = h("div", { class: "selected-box" });
  const stage = h("section", { class: "town-stage", "aria-label": "The town" }, map.el, castBar, timeline.el);
  const page = h("div", { class: "town" }, stage, h("aside", { class: "town-side" }, selectedBox, panelTabs, panelBody));
  root.append(page);
  let resizing = null;
  const onResize = () => {
    clearTimeout(resizing);
    resizing = setTimeout(() => {
      map.layout();
      paint(false);
    }, 120);
  };
  window.addEventListener("resize", onResize);

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
      scenes.set(scene.place, scene.kind === "work" ? `working · round ${Math.min(round, world.scenes.work_rounds)}` : `talking · ${fmt.plural(scene.present.length, "person", "people")}`);
    }
    const key = `${m.state.seq}|${Math.floor(m.state.time / turn)}|${view.truth}`;
    return { state: m.state, minute: minuteOf(m.state.time), selected: view.selected, speech, thinking, scenes, effects, key };
  }

  function renderCast(m) {
    const holding = holdings(m.state);
    const start = replay.snapshots.get(m.state.day)?.balances;
    fill(
      castBar,
      cast.names.map((name) => {
        const place = places.get(m.state.locations[name]);
        const delta = start ? m.state.balances[name] - start[name] : 0;
        const esteem = m.state.esteem[name];
        return h(
          "button",
          { type: "button", role: "listitem", class: `cast-card${view.selected === name ? " on" : ""}`, "aria-pressed": String(view.selected === name), onclick: () => select(name), title: `${name}: ${place ? place.name : ""}` },
          cast.badge(name, 22),
          h(
            "span",
            { class: "cast-text" },
            h("span", { class: "cast-name" }, h("b", {}, name), h("span", { class: "cast-esteem", title: "Esteem as last published" }, icon("star", 11), esteem === null ? "–" : fmt.num(esteem, 1))),
            h("span", { class: `cast-money${m.state.balances[name] < 0 ? " debt" : ""}`, title: "Balance, and its change since the day began" }, fmt.credits(m.state.balances[name]), delta ? h("small", { class: delta > 0 ? "up" : "down" }, ` ${fmt.signed(delta)}`) : null),
            h("span", { class: "cast-where" }, place ? shortName(place) : "", holding[name] ? ` · ${holding[name]}` : ""),
          ),
        );
      }),
    );
  }

  /** The selected agent, and in the truth view the thought behind its latest decision today. */
  function renderSelected(m = moment()) {
    if (!view.selected) {
      fill(selectedBox);
      selectedBox.hidden = true;
      return;
    }
    selectedBox.hidden = false;
    const agent = cast.agent(view.selected);
    const own = m.dayEvents.findLast((e) => e.kind === "decision" && e.actor === view.selected);
    const place = places.get(m.state.locations[view.selected]);
    fill(
      selectedBox,
      h(
        "div",
        { class: "selected-head" },
        cast.badge(view.selected, 30),
        h("div", {}, h("b", {}, agent.name), h("div", { class: "muted" }, `${agent.age}, ${agent.occupation} · ${place ? shortName(place) : ""}`)),
        h("a", { class: "btn small", href: href(sibling({ ...route, query: { ...route.query, t: stamp(Math.floor(view.time)) } }, "person", { agent: view.selected })) }, "Open file", icon("chevron", 14)),
        h("button", { type: "button", class: "tl-btn", "aria-label": "Clear the selection (Escape)", title: "Clear the selection (Escape)", onclick: () => select(null) }, icon("close", 16)),
      ),
      view.truth && own
        ? h(
            "button",
            { type: "button", class: "selected-thought truth", title: "Read the whole thought", onclick: (event) => event.currentTarget.classList.toggle("open") },
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
      renderCast(m);
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
   * Say that the moment cannot be shown yet, or at all: the map is covered and the cast and
   * panels, which would show some other moment, are marked as not current. Null clears it.
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
  function select(name) {
    view.selected = name === view.selected ? null : name;
    if (!view.selected) view.only = false;
    renderSelected();
    renderCast(moment());
    paint(false);
    refreshPanel(true);
    sync();
  }

  function setTruth(on) {
    view.truth = on;
    renderSelected();
    paint(false);
    refreshPanel(true);
    sync();
  }

  function showPanel(key) {
    view.panel = key;
    for (const tab of panelTabs.children) tab.setAttribute("aria-selected", String(tab.dataset.panel === key));
    refreshPanel(true);
    sync();
  }

  function onKey(event) {
    if (event.target.closest("input, select, textarea") || event.metaKey || event.ctrlKey || event.altKey) return;
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
      Escape: () => view.selected && select(null),
    };
    const action = keys[event.key];
    if (!action) return;
    if (event.key === " " && event.target.closest("button, a, summary")) return;
    event.preventDefault();
    action();
  }

  // Start ----------------------------------------------------------------------------------------
  async function start() {
    replay.expect(source.doc.event_days.map((d) => d.day));
    timeline.setRun({ eventDays: source.doc.event_days, last: source.doc.last_time, running: running(), loaded: new Set() });
    renderCast(moment());
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
      window.removeEventListener("resize", onResize);
      map.destroy();
      timeline.destroy();
      panels.ties.destroy();
    },
  };
}
