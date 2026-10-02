// Time is the main control. Two strips: the whole run, day by day, with interventions,
// policy and skill rewrites and found defects marked; and the current day in detail, with its
// slots and what happened when. Nights are left out of both: nothing happens then.

import { calendarOf, dayOf, dayStart, formatTime, hhmm, minuteOf, slotAt } from "../clock.js";
import { fill, h, onWidth, s } from "../dom.js";
import { icon } from "../icons.js";

export const SPEEDS = [1, 3, 10, 30]; // simulated minutes per second

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
    this.width = 0;

    const button = (name, label, handler, extra = {}) => h("button", { type: "button", class: "tl-btn", title: label, "aria-label": label, onclick: handler, ...extra }, icon(name, 18));
    this.playButton = button("play", "Play (space)", onPlay, { class: "tl-btn play" });
    this.liveButton = h("button", { type: "button", class: "tl-live", onclick: onLive, title: "Follow the newest moment of the run (End)" }, h("span", { class: "dot" }), "Live");
    this.speed = h(
      "div",
      { class: "seg speeds", role: "group", "aria-label": "Playback speed in simulated minutes per second" },
      SPEEDS.map((v) => h("button", { type: "button", "data-speed": v, "aria-pressed": "false", onclick: () => onSpeed(v), title: `${v} simulated minute${v > 1 ? "s" : ""} per second` }, `${v}×`)),
    );
    this.truthButton = h("button", { type: "button", class: "ghost small truth-toggle", "aria-pressed": "true", onclick: () => onTruth(), title: "Show what no agent perceived: thoughts, true quality, ratings (T)" }, icon("eye", 15), h("span", {}, "Truth"));
    this.clock = h("div", { class: "tl-clock", "aria-live": "off" });
    this.runStrip = s("svg", { class: "strip run-strip", height: 34, width: "100%" });
    this.dayStrip = s("svg", { class: "strip day-strip", height: 46, width: "100%" });
    this.runWrap = h("div", { class: "strip-wrap", tabindex: "0", role: "slider", "aria-label": "The whole run" }, this.runStrip);
    this.dayWrap = h("div", { class: "strip-wrap", tabindex: "0", role: "slider", "aria-label": "This day" }, this.dayStrip);
    this.el = h(
      "div",
      { class: "timeline" },
      h(
        "div",
        { class: "tl-controls" },
        h(
          "div",
          { class: "tl-transport" },
          button("start", "Start of the day (Shift+←)", () => onStep("day", -1)),
          button("back", "Previous moment (←)", () => onStep("moment", -1)),
          this.playButton,
          button("forward", "Next moment (→)", () => onStep("moment", 1)),
          button("end", "Next day (Shift+→)", () => onStep("day", 1)),
        ),
        this.clock,
        h("div", { class: "tl-right" }, this.speed, this.truthButton, this.liveButton),
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
      this.handlers.onSeek(timeAtX(Math.max(0, Math.min(box.width, event.clientX - box.left))), true);
    };
    wrap.addEventListener("pointerdown", (event) => {
      active = true;
      wrap.setPointerCapture(event.pointerId);
      seek(event);
    });
    wrap.addEventListener("pointermove", (event) => active && seek(event));
    wrap.addEventListener("pointerup", () => (active = false));
    wrap.addEventListener("pointercancel", () => (active = false));
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
    this.playButton.replaceChildren(icon(playing ? "pause" : "play", 18));
    this.playButton.setAttribute("aria-label", playing ? "Pause (space)" : "Play (space)");
    this.playButton.title = playing ? "Pause (space)" : "Play (space)";
    this.liveButton.classList.toggle("on", follow);
    this.liveButton.hidden = !this.run.running;
    this.truthButton.setAttribute("aria-pressed", String(truth));
    for (const b of this.speed.children) b.setAttribute("aria-pressed", String(Number(b.dataset.speed) === speed));
    const slot = slotAt(this.cal, minuteOf(time));
    fill(this.clock, h("b", {}, formatTime(time)), h("span", { class: "muted" }, phase ?? slot?.name ?? ""));
    const text = formatTime(time);
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
    const height = 34;
    const dw = this.dayWidth();
    const parts = [];
    const begun = new Map(this.run.eventDays.map((d) => [d.day, d]));
    for (let day = 1; day <= this.run.days; day++) {
      const x = (day - 1) * dw;
      const entry = begun.get(day);
      const cls = entry ? (entry.settled ? "day settled" : "day partial") : "day planned";
      parts.push(s("rect", { class: `${cls}${entry && !this.run.loaded.has(day) ? " unloaded" : ""}`, x: x + 1, y: 8, width: Math.max(1, dw - 2), height: height - 12, rx: 3 }));
      const every = dw >= 22 ? 1 : dw >= 11 ? 2 : 7;
      if (day === 1 || day % every === 0) parts.push(s("text", { class: "tick", x: x + dw / 2, y: 6, "text-anchor": "middle" }, String(day)));
    }
    for (const found of this.world.interventions) {
      const x = this.runX(found.time);
      parts.push(s("g", { class: `flagmark${found.announcement ? " announced" : ""}` }, s("title", {}, `Day ${found.day}: conditions change${found.announcement ? " (announced)" : " (not announced)"}`), s("line", { x1: x, x2: x, y1: 8, y2: height - 4 }), s("path", { d: `M${x},${height - 4}v-9h6l-2,2.2l2,2.2h-6` })));
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
        ["L2", height - 15],
        ["L1", height - 8],
      ]) {
        const row = steps.filter((step) => step.level === level);
        const spacing = Math.min(5, (dw - 5) / Math.max(1, row.length));
        row.forEach((step, i) => {
          const x = day * dw - 4 - i * spacing;
          const d = level === "L2" ? `M${x},${y - 3}l3,3l-3,3l-3,-3z` : `M${x - 2.2},${y - 2.2}h4.4v4.4h-4.4z`;
          parts.push(s("path", { class: `evo ${level}${step.trigger === "self" ? " self" : ""}`, d, style: { fill: this.cast.color(step.agent) } }, s("title", {}, `Day ${day}, ${step.agent}: ${step.subject} (${step.trigger === "self" ? "asked for" : step.trigger})`)));
        });
      }
    for (const found of this.marks.defects) parts.push(s("circle", { class: "defect", cx: this.runX(found.time), cy: 13, r: 2.6 }, s("title", {}, found.text)));
    if (this.run.running && this.run.last !== null) parts.push(s("circle", { class: "live-edge", cx: this.runX(this.run.last), cy: height - 10, r: 3.5 }, s("title", {}, `Latest event: ${formatTime(this.run.last)}`)));
    parts.push(s("g", { class: "cursor" }, s("line", { x1: 0, x2: 0, y1: 4, y2: height }), s("circle", { cx: 0, cy: height - 2, r: 3.5 })));
    this.runStrip.setAttribute("viewBox", `0 0 ${this.width} ${height}`);
    this.runStrip.setAttribute("height", height);
    this.runStrip.setAttribute("width", this.width);
    this.runStrip.replaceChildren(...parts);
    this.renderDay();
  }

  renderDay() {
    if (!this.width) return;
    const height = 46;
    const parts = [];
    const day = dayOf(this.time);
    this.cal.slots.forEach((slot, i) => {
      const x0 = this.dayX(slot.start);
      const x1 = this.dayX(slot.end);
      parts.push(s("rect", { class: `slot ${i % 2 ? "odd" : ""}`, x: x0, y: 14, width: Math.max(0, x1 - x0), height: height - 14 }, s("title", {}, `${slot.name}, ${hhmm(slot.start)}–${hhmm(slot.end)}`)));
      // A name only where it fits: in full, without its time, or not at all.
      const room = x1 - x0 - 6;
      const label = room > 7 * (slot.name.length + 6) ? `${slot.name} ${hhmm(slot.start)}` : room > 7 * slot.name.length ? slot.name : null;
      if (label) parts.push(s("text", { class: "slot-name", x: x0 + 4, y: 10 }, label));
    });
    if (this.width - this.dayX(this.cal.end) > 34) parts.push(s("text", { class: "slot-name", x: this.dayX(this.cal.end) + 3, y: 10 }, "night"));
    // How much happened, in five-minute buckets, and the moments worth finding.
    const buckets = new Map();
    for (const event of this.dayEvents) {
      const k = Math.floor(minuteOf(event.time) / 5) * 5;
      buckets.set(k, (buckets.get(k) ?? 0) + 1);
    }
    for (const [minute, count] of buckets) {
      const hgt = Math.min(height - 18, 3 + Math.log2(1 + count) * 4);
      parts.push(s("rect", { class: "density", x: this.dayX(minute) - 1.5, y: height - hgt, width: 3, height: hgt, rx: 1 }));
    }
    for (const event of this.dayEvents) {
      const x = this.dayX(minuteOf(event.time));
      if (event.kind === "speech") parts.push(s("circle", { class: "speech-mark", cx: x, cy: 19, r: 2.2 }));
      if (event.kind === "work_submitted") parts.push(s("circle", { class: `work-mark ${event.payload.passed ? "good" : "serious"}`, cx: x, cy: 25, r: 2.6 }));
      if (event.kind === "defect_discovered" || event.kind === "clawback") parts.push(s("circle", { class: "work-mark critical", cx: x, cy: 25, r: 2.6 }));
    }
    if (this.run.running && this.run.last !== null && dayOf(this.run.last) === day) parts.push(s("circle", { class: "live-edge", cx: this.dayX(minuteOf(this.run.last)), cy: height - 6, r: 3.5 }));
    parts.push(s("g", { class: "cursor" }, s("line", { x1: 0, x2: 0, y1: 12, y2: height }), s("path", { d: "M-5,12h10l-5,6z" })));
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
