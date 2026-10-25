// Time is the main control. Two strips: the whole run, lived day by lived day, with the nights'
// file rewrites and forced sleeps marked; and the current day in detail, from one checkpoint to
// the next, with the fixed hours of the night and what happened when. Both strips are scrubbed
// by dragging, with a finger as well as a mouse.

import { DAY, dateOf, formatTime, hhmm, livedDay, parseHHMM, secondOfDay } from "../clock.js";
import { fill, h, onWidth, s } from "../dom.js";
import { icon } from "../icons.js";

export const SPEEDS = [1, 3, 10, 30]; // simulated minutes per second
const RUN_H = 30;
const DAY_H = 40;

export class Timeline {
  constructor({ world, cast, onSeek, onPlay, onStep, onSpeed, onLive }) {
    this.world = world;
    this.cast = cast;
    this.hours = { ...world.day, midnight: "00:00" };
    this.handlers = { onSeek, onSpeed };
    this.run = { planned: world.days, days: [], last: null, running: false, loaded: new Set() };
    this.marks = { rewrites: [], forced: [] };
    this.dayEntries = [];
    this.time = 0;
    this.speedNow = SPEEDS[1];
    this.width = 0;

    const button = (name, label, handler, cls = "") => h("button", { type: "button", class: `icon-btn ${cls}`, title: label, "aria-label": label, onclick: handler }, icon(name, 20));
    this.playButton = button("play", "Play (space)", onPlay, "play");
    this.liveButton = h("button", { type: "button", class: "tl-live", onclick: onLive, title: "Follow the newest moment of the run (End)" }, h("span", { class: "dot" }), "Live");
    this.speedButton = h("button", { type: "button", class: "tl-speed", onclick: () => onSpeed(SPEEDS[(SPEEDS.indexOf(this.speedNow) + 1) % SPEEDS.length]) });
    this.clock = h("div", { class: "tl-clock", "aria-live": "off" });
    this.runStrip = s("svg", { class: "strip run-strip", height: RUN_H, width: "100%", "aria-hidden": "true" });
    this.dayStrip = s("svg", { class: "strip day-strip", height: DAY_H, width: "100%", "aria-hidden": "true" });
    this.runWrap = h("div", { class: "strip-wrap run", tabindex: "0", role: "slider", "aria-label": "The whole run" }, this.runStrip);
    this.dayWrap = h("div", { class: "strip-wrap day", tabindex: "0", role: "slider", "aria-label": "This day" }, this.dayStrip);
    this.controls = h(
      "div",
      { class: "tl-controls" },
      h(
        "div",
        { class: "tl-transport" },
        button("start", "Previous day (Shift+←)", () => onStep("day", -1), "tl-day"),
        button("back", "Previous moment (←)", () => onStep("moment", -1)),
        this.playButton,
        button("forward", "Next moment (→)", () => onStep("moment", 1)),
        button("end", "Next day (Shift+→)", () => onStep("day", 1), "tl-day"),
      ),
      this.clock,
      h("div", { class: "tl-right" }, this.liveButton, this.speedButton),
    );
    this.el = h("div", { class: "timeline" }, this.controls, this.runWrap, this.dayWrap);
    this.drag(this.runWrap, (x) => this.runTime(x));
    this.drag(this.dayWrap, (x) => this.dayTime(x));
    this.stop = onWidth(this.runWrap, (width) => {
      this.width = width;
      this.render();
    });
  }

  drag(wrap, timeAtX) {
    let active = false;
    const seek = (event) => {
      const box = wrap.getBoundingClientRect();
      this.handlers.onSeek(timeAtX(Math.max(0, Math.min(box.width - 0.01, event.clientX - box.left))), true);
    };
    wrap.addEventListener("pointerdown", (event) => {
      if (event.pointerType === "mouse" && event.button !== 0) return;
      active = true;
      wrap.setPointerCapture(event.pointerId);
      wrap.classList.add("active");
      seek(event);
    });
    wrap.addEventListener("pointermove", (event) => active && seek(event));
    const end = () => {
      active = false;
      wrap.classList.remove("active");
    };
    wrap.addEventListener("pointerup", end);
    wrap.addEventListener("pointercancel", end);
  }

  /** The days the run strip shows: those lived, and the rest planned. */
  count() {
    return Math.max(this.run.planned, this.run.days.length, 1);
  }

  dayWidth() {
    return this.width / this.count();
  }

  /** The lived day holding a time, and how far into its 24 hours the time lies (0 to 1). */
  within(time) {
    const day = livedDay(this.run.days, time) ?? { day: 1, start: 0 };
    return { day, fraction: Math.max(0, Math.min(1, (time - day.start) / DAY)) };
  }

  /** The x of a time on the run strip. */
  runX(time) {
    const { day, fraction } = this.within(time);
    return (day.day - 1) * this.dayWidth() + fraction * (this.dayWidth() - 2) + 1;
  }

  runTime(x) {
    const number = Math.min(this.count(), Math.floor(x / this.dayWidth()) + 1);
    const day = this.run.days.find((found) => found.day === number) ?? this.run.days.at(-1);
    if (!day) return 0;
    const fraction = (x - (number - 1) * this.dayWidth()) / this.dayWidth();
    return day.start + Math.round(fraction * DAY);
  }

  dayX(time) {
    return this.within(time).fraction * this.width;
  }

  dayTime(x) {
    const { day } = this.within(this.time);
    return day.start + Math.round((x / this.width) * DAY);
  }

  setRun(run) {
    this.run = { ...this.run, ...run };
    this.render();
  }

  setMarks(marks) {
    this.marks = marks;
    this.render();
  }

  setDay(entries) {
    this.dayEntries = entries;
    this.renderDay();
  }

  setCursor(exact, { playing, follow, speed, phase }) {
    const time = Math.floor(exact);
    const moved = this.within(time).day !== this.within(this.time).day;
    this.time = time;
    if (this.playing !== playing) {
      this.playing = playing;
      this.playButton.replaceChildren(icon(playing ? "pause" : "play", 20));
      this.playButton.setAttribute("aria-label", playing ? "Pause (space)" : "Play (space)");
      this.playButton.title = playing ? "Pause (space)" : "Play (space)";
    }
    this.liveButton.classList.toggle("on", follow);
    this.liveButton.hidden = !this.run.running;
    if (speed !== this.speedNow || !this.speedButton.textContent) {
      this.speedNow = speed;
      this.speedButton.textContent = `${speed}×`;
      this.speedButton.title = `Playback: ${speed} simulated minute${speed > 1 ? "s" : ""} per second. Tap for ${SPEEDS[(SPEEDS.indexOf(speed) + 1) % SPEEDS.length]}×.`;
      this.speedButton.setAttribute("aria-label", this.speedButton.title);
    }
    const text = this.run.days.length ? formatTime(time, this.run.days) : formatTime(time);
    fill(this.clock, h("b", {}, text), h("span", {}, `${dateOf(this.world.start_date, time)}${phase ? ` · ${phase}` : ""}`));
    this.runWrap.setAttribute("aria-valuetext", text);
    this.dayWrap.setAttribute("aria-valuetext", text);
    if (moved) this.renderDay();
    this.placeCursor();
  }

  placeCursor() {
    if (!this.width) return;
    for (const [strip, x] of [
      [this.runStrip, this.runX(this.time)],
      [this.dayStrip, this.dayX(this.time)],
    ]) {
      const cursor = strip.querySelector(".cursor");
      if (cursor) cursor.setAttribute("transform", `translate(${x.toFixed(1)},0)`);
    }
  }

  render() {
    if (!this.width) return;
    const height = RUN_H;
    const dw = this.dayWidth();
    const parts = [];
    const lived = new Map(this.run.days.map((d) => [d.day, d]));
    const every = dw >= 24 ? 1 : dw >= 12 ? 7 : 14;
    for (let day = 1; day <= this.count(); day++) {
      const x = (day - 1) * dw;
      const entry = lived.get(day);
      const cls = entry ? (entry.end !== null ? "day settled" : "day partial") : "day planned";
      parts.push(s("rect", { class: `${cls}${entry && !this.run.loaded.has(day) ? " unloaded" : ""}`, x: x + 1, y: 12, width: Math.max(1, dw - 2), height: height - 14, rx: Math.min(3, dw / 4) }));
      if (day === 1 || day % every === 0) parts.push(s("text", { class: "tick", x: x + dw / 2, y: 8, "text-anchor": "middle" }, String(day)));
    }
    // Rewrites of memory (squares) and skills (diamonds) at the end of their day, in the
    // resident's colour, packed into the day.
    const nights = new Map();
    for (const step of this.marks.rewrites) {
      if (!nights.has(step.day)) nights.set(step.day, []);
      nights.get(step.day).push(step);
    }
    for (const [day, steps] of nights)
      for (const [area, y] of [
        ["skills", 17],
        ["memory", 24],
      ]) {
        const row = steps.filter((step) => step.area === area);
        const spacing = Math.min(5, (dw - 5) / Math.max(1, row.length));
        row.forEach((step, i) => {
          const x = day * dw - 4 - i * spacing;
          const d = area === "skills" ? `M${x},${y - 3}l3,3l-3,3l-3,-3z` : `M${x - 2.2},${y - 2.2}h4.4v4.4h-4.4z`;
          parts.push(s("path", { class: `evo ${area}`, d, style: { fill: this.cast.color(step.agent) } }, s("title", {}, `Day ${day}, ${step.agent}: ${step.files.join(", ")}`)));
        });
      }
    for (const found of this.marks.forced) parts.push(s("circle", { class: "defect", cx: this.runX(found.time), cy: 16, r: 2.4 }, s("title", {}, found.text)));
    if (this.run.running && this.run.last !== null) parts.push(s("circle", { class: "live-edge", cx: this.runX(this.run.last), cy: height - 8, r: 3.5 }, s("title", {}, `Latest entry: ${formatTime(this.run.last, this.run.days)}`)));
    parts.push(s("g", { class: "cursor" }, s("line", { x1: 0, x2: 0, y1: 10, y2: height }), s("circle", { cx: 0, cy: 10, r: 3 })));
    this.runStrip.setAttribute("viewBox", `0 0 ${this.width} ${height}`);
    this.runStrip.setAttribute("height", height);
    this.runStrip.setAttribute("width", this.width);
    this.runStrip.replaceChildren(...parts);
    this.renderDay();
  }

  renderDay() {
    if (!this.width) return;
    const height = DAY_H;
    const parts = [];
    const { day } = this.within(this.time);
    const start = day.start;
    // The day's hours, every third labelled, and the fixed hours of the world marked by name.
    for (let t = start - secondOfDay(start) + 3 * 3600; t < start + DAY; t += 3 * 3600) {
      if (t <= start) continue;
      const x = this.dayX(t);
      parts.push(s("line", { class: "hour", x1: x, x2: x, y1: 13, y2: height - 2 }));
      parts.push(s("text", { class: "slot-name", x: x + 3, y: 9 }, hhmm(secondOfDay(t))));
    }
    for (const [name, clock] of Object.entries(this.hours)) {
      let t = start - secondOfDay(start) + parseHHMM(clock);
      if (t <= start) t += DAY;
      if (t > start + DAY) continue;
      const x = this.dayX(t);
      parts.push(s("line", { class: "fixed-hour", x1: x, x2: x, y1: 11, y2: height - 2 }, s("title", {}, `${name.replaceAll("_", " ")} · ${clock}`)));
    }
    // How much happened, in five-minute buckets, and the moments worth finding.
    const buckets = new Map();
    for (const e of this.dayEntries) {
      const k = Math.floor((e.sim_time - start) / 300) * 300;
      buckets.set(k, (buckets.get(k) ?? 0) + 1);
    }
    for (const [offset, count] of buckets) {
      const hgt = Math.min(height - 22, 2 + Math.log2(1 + count) * 3.4);
      parts.push(s("rect", { class: "density", x: this.dayX(start + offset) - 1.25, y: height - 2 - hgt, width: 2.5, height: hgt, rx: 1 }));
    }
    for (const e of this.dayEntries) {
      const x = this.dayX(e.sim_time);
      if (e.kind === "speech") parts.push(s("circle", { class: "speech-mark", cx: x, cy: 18, r: 1.8 }));
      if (e.kind === "verdict") parts.push(s("circle", { class: `work-mark ${e.payload?.resolved ? "good" : "serious"}`, cx: x, cy: 24, r: 2.6 }));
      if (e.kind === "forced_sleep" || e.kind === "expiry") parts.push(s("circle", { class: "work-mark critical", cx: x, cy: 24, r: 2.6 }));
    }
    if (this.run.running && this.run.last !== null && this.within(this.run.last).day === day) parts.push(s("circle", { class: "live-edge", cx: this.dayX(this.run.last), cy: height - 6, r: 3.5 }));
    parts.push(s("g", { class: "cursor" }, s("line", { x1: 0, x2: 0, y1: 11, y2: height }), s("path", { d: "M-4.5,11h9l-4.5,5z" })));
    this.dayStrip.setAttribute("viewBox", `0 0 ${this.width} ${height}`);
    this.dayStrip.setAttribute("height", height);
    this.dayStrip.setAttribute("width", this.width);
    this.dayStrip.replaceChildren(...parts);
    this.placeCursor();
  }

  destroy() {
    this.stop();
  }
}
