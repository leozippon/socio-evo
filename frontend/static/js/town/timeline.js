// Time is the main control. Two strips: the whole run, day by day, with interventions,
// policy and skill rewrites and found defects marked; and the current day in detail, with its
// slots and what happened when. Nights are left out of both: nothing happens then. Both strips
// are scrubbed by dragging, with a finger as well as a mouse.

import { calendarOf, dayOf, dayStart, formatTime, hhmm, minuteOf, slotAt } from "../clock.js";
import { fill, h, onWidth, s } from "../dom.js";
import { icon } from "../icons.js";

export const SPEEDS = [1, 3, 10, 30]; // simulated minutes per second
const RUN_H = 30;
const DAY_H = 40;

export class Timeline {
  constructor({ world, cast, onSeek, onPlay, onStep, onSpeed, onTruth, onLive }) {
    this.world = world;
    this.cast = cast;
    this.cal = calendarOf(world);
    this.from = this.cal.start - 25; // the shown part of every day
    this.to = this.cal.end + 25;
    this.handlers = { onSeek, onSpeed, onTruth };
    this.run = { days: world.days, eventDays: [], last: null, running: false, loaded: new Set() };
    this.marks = { evolution: [], defects: [] };
    this.dayEvents = [];
    this.time = 0;
    this.speedNow = SPEEDS[1];
    this.width = 0;

    const button = (name, label, handler, cls = "") => h("button", { type: "button", class: `icon-btn ${cls}`, title: label, "aria-label": label, onclick: handler }, icon(name, 20));
    this.playButton = button("play", "Play (space)", onPlay, "play");
    this.liveButton = h("button", { type: "button", class: "tl-live", onclick: onLive, title: "Follow the newest moment of the run (End)" }, h("span", { class: "dot" }), "Live");
    this.speedButton = h("button", { type: "button", class: "tl-speed", onclick: () => onSpeed(SPEEDS[(SPEEDS.indexOf(this.speedNow) + 1) % SPEEDS.length]) });
    this.truthButton = h("button", { type: "button", class: "tl-truth", "aria-pressed": "true", onclick: () => onTruth(), title: "Show what no agent perceived: thoughts, true quality, ratings (T)", "aria-label": "Show the truth" }, icon("eye", 18), h("span", {}, "Truth"));
    this.clock = h("div", { class: "tl-clock", "aria-live": "off" });
    this.runStrip = s("svg", { class: "strip run-strip", height: RUN_H, width: "100%", "aria-hidden": "true" });
    this.dayStrip = s("svg", { class: "strip day-strip", height: DAY_H, width: "100%", "aria-hidden": "true" });
    this.runWrap = h("div", { class: "strip-wrap run", tabindex: "0", role: "slider", "aria-label": "The whole run" }, this.runStrip);
    this.dayWrap = h("div", { class: "strip-wrap day", tabindex: "0", role: "slider", "aria-label": "This day" }, this.dayStrip);
    this.el = h(
      "div",
      { class: "timeline" },
      h(
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
        h("div", { class: "tl-right" }, this.liveButton, this.speedButton, this.truthButton),
      ),
      this.runWrap,
      this.dayWrap,
    );
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

  dayWidth() {
    return this.width / Math.max(1, this.run.days);
  }

  /** The x of a time on the run strip. */
  runX(time) {
    const day = dayOf(time);
    const m = Math.max(this.from, Math.min(this.to, minuteOf(time)));
    return (day - 1) * this.dayWidth() + ((m - this.from) / (this.to - this.from)) * (this.dayWidth() - 2) + 1;
  }

  runTime(x) {
    const day = Math.min(this.run.days, Math.floor(x / this.dayWidth()) + 1);
    const within = (x - (day - 1) * this.dayWidth()) / this.dayWidth();
    return dayStart(day) + Math.round(this.from + within * (this.to - this.from));
  }

  dayX(minute) {
    return ((Math.max(this.from, Math.min(this.to, minute)) - this.from) / (this.to - this.from)) * this.width;
  }

  dayTime(x) {
    return dayStart(dayOf(this.time)) + Math.round(this.from + (x / this.width) * (this.to - this.from));
  }

  setRun(run) {
    this.run = { ...this.run, ...run };
    this.render();
  }

  setMarks(marks) {
    this.marks = marks;
    this.render();
  }

  setDay(events) {
    this.dayEvents = events;
    this.renderDay();
  }

  setCursor(exact, { playing, follow, truth, speed, phase }) {
    const time = Math.floor(exact);
    const moved = dayOf(time) !== dayOf(this.time);
    this.time = time;
    if (this.playing !== playing) {
      this.playing = playing;
      this.playButton.replaceChildren(icon(playing ? "pause" : "play", 20));
      this.playButton.setAttribute("aria-label", playing ? "Pause (space)" : "Play (space)");
      this.playButton.title = playing ? "Pause (space)" : "Play (space)";
    }
    this.liveButton.classList.toggle("on", follow);
    this.liveButton.hidden = !this.run.running;
    this.truthButton.setAttribute("aria-pressed", String(truth));
    if (speed !== this.speedNow || !this.speedButton.textContent) {
      this.speedNow = speed;
      this.speedButton.textContent = `${speed}×`;
      this.speedButton.title = `Playback: ${speed} simulated minute${speed > 1 ? "s" : ""} per second. Tap for ${SPEEDS[(SPEEDS.indexOf(speed) + 1) % SPEEDS.length]}×.`;
      this.speedButton.setAttribute("aria-label", this.speedButton.title);
    }
    const slot = slotAt(this.cal, minuteOf(time));
    const text = formatTime(time);
    fill(this.clock, h("b", {}, text), h("span", {}, phase ?? slot?.name ?? ""));
    this.runWrap.setAttribute("aria-valuetext", text);
    this.dayWrap.setAttribute("aria-valuetext", text);
    if (moved) this.renderDay();
    this.placeCursor();
  }

  placeCursor() {
    if (!this.width) return;
    for (const [strip, x] of [
      [this.runStrip, this.runX(this.time)],
      [this.dayStrip, this.dayX(minuteOf(this.time))],
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
    const begun = new Map(this.run.eventDays.map((d) => [d.day, d]));
    const every = dw >= 24 ? 1 : dw >= 12 ? 7 : 14;
    for (let day = 1; day <= this.run.days; day++) {
      const x = (day - 1) * dw;
      const entry = begun.get(day);
      const cls = entry ? (entry.settled ? "day settled" : "day partial") : "day planned";
      parts.push(s("rect", { class: `${cls}${entry && !this.run.loaded.has(day) ? " unloaded" : ""}`, x: x + 1, y: 12, width: Math.max(1, dw - 2), height: height - 14, rx: Math.min(3, dw / 4) }));
      if (day === 1 || day % every === 0) parts.push(s("text", { class: "tick", x: x + dw / 2, y: 8, "text-anchor": "middle" }, String(day)));
    }
    for (const found of this.world.interventions) {
      const x = this.runX(found.time);
      parts.push(s("g", { class: `flagmark${found.announcement ? " announced" : ""}` }, s("title", {}, `Day ${found.day}: conditions change${found.announcement ? " (announced)" : " (not announced)"}`), s("line", { x1: x, x2: x, y1: 12, y2: height - 2 }), s("path", { d: `M${x},${height - 2}v-8h5l-1.6,2l1.6,2h-5` })));
    }
    // Rewrites of policy (diamonds) and skills (squares) at the end of their night, in the
    // agent's colour; one row per level, packed into the day.
    const nights = new Map();
    for (const step of this.marks.evolution) {
      if (!nights.has(step.day)) nights.set(step.day, []);
      nights.get(step.day).push(step);
    }
    for (const [day, steps] of nights)
      for (const [level, y] of [
        ["L2", 17],
        ["L1", 24],
      ]) {
        const row = steps.filter((step) => step.level === level);
        const spacing = Math.min(5, (dw - 5) / Math.max(1, row.length));
        row.forEach((step, i) => {
          const x = day * dw - 4 - i * spacing;
          const d = level === "L2" ? `M${x},${y - 3}l3,3l-3,3l-3,-3z` : `M${x - 2.2},${y - 2.2}h4.4v4.4h-4.4z`;
          parts.push(s("path", { class: `evo ${level}${step.trigger === "self" ? " self" : ""}`, d, style: { fill: this.cast.color(step.agent) } }, s("title", {}, `Day ${day}, ${step.agent}: ${step.subject} (${step.trigger === "self" ? "asked for" : step.trigger})`)));
        });
      }
    for (const found of this.marks.defects) parts.push(s("circle", { class: "defect", cx: this.runX(found.time), cy: 16, r: 2.4 }, s("title", {}, found.text)));
    if (this.run.running && this.run.last !== null) parts.push(s("circle", { class: "live-edge", cx: this.runX(this.run.last), cy: height - 8, r: 3.5 }, s("title", {}, `Latest event: ${formatTime(this.run.last)}`)));
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
    const day = dayOf(this.time);
    this.cal.slots.forEach((slot, i) => {
      const x0 = this.dayX(slot.start);
      const x1 = this.dayX(slot.end);
      parts.push(s("rect", { class: `slot ${i % 2 ? "odd" : ""}`, x: x0, y: 13, width: Math.max(0, x1 - x0 - 1), height: height - 13, rx: 3 }, s("title", {}, `${slot.name}, ${hhmm(slot.start)}–${hhmm(slot.end)}`)));
      // A name only where it fits: in full, without its time, or not at all.
      const room = x1 - x0 - 6;
      const label = room > 6.5 * (slot.name.length + 6) ? `${slot.name} ${hhmm(slot.start)}` : room > 6.5 * slot.name.length ? slot.name : null;
      if (label) parts.push(s("text", { class: "slot-name", x: x0 + 3, y: 9 }, label));
    });
    // How much happened, in five-minute buckets, and the moments worth finding.
    const buckets = new Map();
    for (const event of this.dayEvents) {
      const k = Math.floor(minuteOf(event.time) / 5) * 5;
      buckets.set(k, (buckets.get(k) ?? 0) + 1);
    }
    for (const [minute, count] of buckets) {
      const hgt = Math.min(height - 22, 2 + Math.log2(1 + count) * 3.4);
      parts.push(s("rect", { class: "density", x: this.dayX(minute) - 1.25, y: height - 2 - hgt, width: 2.5, height: hgt, rx: 1 }));
    }
    for (const event of this.dayEvents) {
      const x = this.dayX(minuteOf(event.time));
      if (event.kind === "speech") parts.push(s("circle", { class: "speech-mark", cx: x, cy: 18, r: 1.8 }));
      if (event.kind === "work_submitted") parts.push(s("circle", { class: `work-mark ${event.payload?.passed ? "good" : "serious"}`, cx: x, cy: 24, r: 2.6 }));
      if (event.kind === "defect_discovered" || event.kind === "clawback") parts.push(s("circle", { class: "work-mark critical", cx: x, cy: 24, r: 2.6 }));
    }
    if (this.run.running && this.run.last !== null && dayOf(this.run.last) === day) parts.push(s("circle", { class: "live-edge", cx: this.dayX(minuteOf(this.run.last)), cy: height - 6, r: 3.5 }));
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
