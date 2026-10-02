// Wires the viewer together: run picker, replay clock, map, feed and panels.

import { getEvents, getWorld, listRuns } from "./api.js";
import { AgentPanel } from "./agent.js";
import { TownMap, agentColor } from "./map.js";
import { h, renderBoard, renderFeed } from "./panels.js";
import { Replay, dayStarts, formatTime, series } from "./replay.js";

const $ = (id) => document.getElementById(id);
const SPEEDS = [
  ["10 min/s", 10],
  ["1 h/s", 60],
  ["4 h/s", 240],
  ["12 h/s", 720],
  ["1 day/s", 1440],
];
const POLL_MS = 3000;

let session = null; // everything belonging to the open run

function fail(error) {
  $("error").textContent = error.message ?? String(error);
  $("error").hidden = false;
}

const runId = (r) => `${r.experiment}/${r.directory}`;

async function main() {
  const runs = await listRuns();
  const picker = $("run");
  picker.replaceChildren(...runs.map((r) => h("option", { value: runId(r) }, `${runId(r)} · ${r.status} · ${r.days_done}/${r.days} days`)));
  if (!runs.length) return fail(new Error("No runs found under the runs root."));
  const wanted = location.hash.slice(1);
  if (runs.some((r) => runId(r) === wanted)) picker.value = wanted;
  picker.onchange = () => open(runs.find((r) => runId(r) === picker.value));
  await open(runs.find((r) => runId(r) === picker.value));
}

async function open(run) {
  if (session) clearTimeout(session.poll);
  location.hash = runId(run);
  $("error").hidden = true;
  const world = await getWorld(run);
  const replay = new Replay(world);
  const status = await fetchAll(run, replay);
  const map = new TownMap($("map"), world, { onSelect: (name) => select(name) });
  const agents = new AgentPanel($("agent"), { run, world, series: series(world, replay.events) });
  agents.onChange = () => (session.dirty = true);
  session = { run, world, replay, map, agents, status, cursor: replay.start, playing: false, speed: 60, dirty: true, lastFrame: performance.now(), poll: null };
  buildControls();
  buildLegend();
  refreshTimeline();
  select(null);
  schedulePoll();
}

/** Load every event of the run so far; returns the run status. */
async function fetchAll(run, replay) {
  const { events, status } = await getEvents(run, -1);
  replay.append(events);
  return status;
}

function schedulePoll() {
  const s = session;
  if (s.status !== "running") return;
  s.poll = setTimeout(async () => {
    try {
      const last = s.replay.events.at(-1)?.seq ?? -1;
      const { events, status } = await getEvents(s.run, last);
      const follow = s.cursor >= s.replay.end;
      s.status = status;
      if (events.length) {
        s.replay.append(events);
        s.agents.series = series(s.world, s.replay.events);
        s.agents.invalidate();
        refreshTimeline();
        if (follow) s.cursor = s.replay.end;
        s.dirty = true;
      }
    } catch (error) {
      fail(error);
    }
    if (session === s) schedulePoll();
  }, POLL_MS);
}

function select(name) {
  session.map.selected = name;
  session.agents.select(name);
  session.dirty = true;
  for (const chip of $("legend").children) chip.classList.toggle("on", chip.dataset.name === name);
}

function buildLegend() {
  const { world } = session;
  $("legend").replaceChildren(
    ...world.agents.map((a) =>
      h(
        "button",
        { class: "chip", "data-name": a.name, onclick: () => select(a.name) },
        h("span", { class: "dot", style: `background:${agentColor(world, a.name)}` }),
        a.name,
      ),
    ),
  );
}

function buildControls() {
  const s = session;
  $("speed").replaceChildren(...SPEEDS.map(([label, value]) => h("option", { value }, label)));
  $("speed").value = String(s.speed);
  $("speed").onchange = () => {
    s.speed = Number($("speed").value);
    s.map.bubbleWindow = Math.max(15, 3 * s.speed);
  };
  $("play").onclick = () => {
    if (s.cursor >= s.replay.end) s.cursor = s.replay.start;
    s.playing = !s.playing;
    s.lastFrame = performance.now();
  };
  $("scrub").oninput = () => {
    s.cursor = s.replay.start + Number($("scrub").value);
    s.dirty = true;
  };
  $("view").onchange = () => (s.dirty = true);
}

/** Resize the scrubber and its day marks to the events known so far. */
function refreshTimeline() {
  const { replay } = session;
  const span = replay.end - replay.start;
  $("scrub").max = String(span);
  $("days").replaceChildren(
    ...dayStarts(replay.events).map((t, i) =>
      h("span", { class: "daymark", style: `left:${span ? ((t - replay.start) / span) * 100 : 0}%` }, `D${i + 1}`),
    ),
  );
}

let lastRender = { applied: -1, time: -1 };
let lastPanels = 0;

function frame(now) {
  requestAnimationFrame(frame);
  const s = session;
  if (!s) return;
  const dt = Math.min(0.1, (now - s.lastFrame) / 1000);
  s.lastFrame = now;
  if (s.playing) {
    s.cursor = Math.min(s.replay.end, s.cursor + dt * s.speed);
    if (s.cursor >= s.replay.end && s.status !== "running") s.playing = false;
    $("scrub").value = String(s.cursor - s.replay.start);
  }
  const state = s.replay.seek(s.cursor);
  s.map.draw(state, dt);
  $("play").textContent = s.playing ? "Pause" : "Play";
  $("clock").textContent = `${formatTime(Math.floor(state.time))} · ${s.status}`;
  if (!s.playing) $("scrub").value = String(s.cursor - s.replay.start);
  const changed = state.applied !== lastRender.applied || s.dirty;
  if (changed && now - lastPanels > 250) {
    lastPanels = now;
    lastRender = { applied: state.applied };
    s.dirty = false;
    renderFeed($("feed"), s.replay.events, state.applied, $("view").value === "god", s.world);
    renderBoard($("board"), state);
    s.agents.update(state, [s.replay.start, s.replay.end]).catch(fail);
  }
}

main().catch(fail);
requestAnimationFrame(frame);
