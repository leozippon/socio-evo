// Every resident's events side by side on one canvas: a lane per resident over simulated time.
// A lane, top to bottom: three rows of markers (tasks, money, social, rest and the body) in
// which markers within a few pixels fold into one count; the conversation row, naming the
// partners where there is room; the base event as a band (idle light, movement hatched, work
// solid with the task written, sleep dim, dead dark) with the place as a strip under it; and
// the purse as a step line.
// The view zooms and pans by wheel, pinch, drag and buttons, a day strip over the axis moves
// across a long run, and the moment shown elsewhere is a cursor.

import { DAY, dateOf, duration, hhmm, livedDay, secondOfDay } from "../clock.js";
import { fmt, h } from "../dom.js";
import { lowerBound, purseAt } from "../replay.js";
import { EVENTS } from "../world.js";
import { describeMarker } from "./events.js";

const LABEL_WIDE = 150; // the label column: the rows' captions, the badge and name by the band, the purse by its line
const LABEL_NARROW = 80; // on a phone, the name and the purse
const STRIP_Y = 4; // the day strip over the axis
const STRIP_H = 8;
const AXIS_H = 50;
const LANE_H = 108;
const ROWS = ["tasks", "money", "social"];
const ROW_Y = [11, 24, 37]; // the rows' centres
const ROW_H = 13;
const ROW_OF = { claim: 0, submission: 0, abandon: 0, expiry: 0, payment: 1, gift: 1, purchase: 1, settlement: 1, speech: 2, message: 2, rating: 2, skill_shared: 2, move_in: 2, journal: 2, forced_sleep: 2, condition: 2, death: 2 };
const CONV_Y = 45;
const CONV_H = 14;
const BAND_Y = 61;
const BAND_H = 22;
const PLACE_Y = 83;
const PLACE_H = 5;
const PURSE_Y = 91;
const PURSE_H = 11;
const GLYPH = 5; // half a glyph's box
const GAP = 8; // a marker closer than this to the last one drawn in its row joins its count
const MIN_SPAN = 600;
const FONT = "system-ui, sans-serif";
const PLACE_COLOUR = { home: "o1", workplace: "o3", social: "o5", shop: "o5" };
const TOKENS = ["page", "surface", "surface-3", "ink", "ink-2", "muted", "line", "line-2", "accent", "accent-soft", "good", "serious", "critical", "warn", "o1", "o3", "o5", "lane-idle", "lane-sleep", "lane-movement", "lane-work", "lane-dead", "lane-conversation", "lane-skill", "lane-rating", ...[1, 2, 3, 4, 5, 6, 7, 8].flatMap((n) => [`a${n}`, `a${n}-ink`])];

/** The marker's glyph in a box of ten pixels, as the legend and the lanes draw it. */
export function drawMarker(g, m, cx, cy, C) {
  g.lineWidth = 1.5;
  g.lineJoin = "round";
  g.lineCap = "butt";
  g.beginPath();
  switch (m.kind) {
    case "speech": // a tick; a private word is hollow
      g.roundRect(cx - 1.5, cy - 5, 3, 10, 1.5);
      if (m.private) {
        g.strokeStyle = C["lane-conversation"];
        g.stroke();
      } else {
        g.fillStyle = C["lane-conversation"];
        g.fill();
      }
      break;
    case "claim":
      g.moveTo(cx - 5, cy - 4);
      g.lineTo(cx + 5, cy - 4);
      g.lineTo(cx, cy + 5);
      g.closePath();
      g.fillStyle = C["ink-2"];
      g.fill();
      break;
    case "submission":
      if (m.resolved === undefined) {
        g.rect(cx - 4, cy - 4, 8, 8);
        g.fillStyle = C.surface;
        g.fill();
        g.strokeStyle = C.muted;
        g.stroke();
        break;
      }
      g.rect(cx - 5, cy - 5, 10, 10);
      g.fillStyle = m.resolved ? C.good : C.critical;
      g.fill();
      g.strokeStyle = C.surface;
      g.lineWidth = 1.8;
      g.beginPath();
      if (m.resolved) {
        g.moveTo(cx - 3, cy);
        g.lineTo(cx - 0.8, cy + 2.3);
        g.lineTo(cx + 3.2, cy - 2.5);
      } else {
        g.moveTo(cx - 2.5, cy - 2.5);
        g.lineTo(cx + 2.5, cy + 2.5);
        g.moveTo(cx + 2.5, cy - 2.5);
        g.lineTo(cx - 2.5, cy + 2.5);
      }
      g.stroke();
      break;
    case "abandon":
      g.moveTo(cx, cy - 5);
      g.lineTo(cx + 5, cy + 4);
      g.lineTo(cx - 5, cy + 4);
      g.closePath();
      g.fillStyle = C.surface;
      g.fill();
      g.strokeStyle = C.serious;
      g.stroke();
      break;
    case "expiry":
      g.arc(cx, cy, 4.5, 0, 2 * Math.PI);
      g.fillStyle = C.surface;
      g.fill();
      g.strokeStyle = C.critical;
      g.stroke();
      g.beginPath();
      g.moveTo(cx - 3, cy + 3);
      g.lineTo(cx + 3, cy - 3);
      g.stroke();
      break;
    case "payment":
    case "gift":
      g.moveTo(cx, cy - 5.5);
      g.lineTo(cx + 5, cy);
      g.lineTo(cx, cy + 5.5);
      g.lineTo(cx - 5, cy);
      g.closePath();
      if (m.kind === "payment") {
        g.fillStyle = C.good;
        g.fill();
      } else {
        g.fillStyle = C.surface;
        g.fill();
        g.strokeStyle = C.good;
        g.stroke();
      }
      break;
    case "skill_shared":
      g.strokeStyle = C["lane-skill"];
      g.lineWidth = 2.4;
      g.lineCap = "round";
      g.moveTo(cx - 4.5, cy);
      g.lineTo(cx + 4.5, cy);
      g.moveTo(cx, cy - 4.5);
      g.lineTo(cx, cy + 4.5);
      g.stroke();
      break;
    case "rating":
      for (let i = 0; i < 10; i++) {
        const r = i % 2 ? 2.3 : 5.5;
        const a = -Math.PI / 2 + (i * Math.PI) / 5;
        g.lineTo(cx + r * Math.cos(a), cy + r * Math.sin(a));
      }
      g.closePath();
      g.fillStyle = C["lane-rating"];
      g.fill();
      break;
    case "journal":
      g.rect(cx - 3.5, cy - 4.5, 7, 9);
      g.fillStyle = C.surface;
      g.fill();
      g.strokeStyle = C.ink;
      g.stroke();
      g.beginPath();
      g.moveTo(cx - 1.5, cy - 1.5);
      g.lineTo(cx + 1.5, cy - 1.5);
      g.moveTo(cx - 1.5, cy + 1);
      g.lineTo(cx + 1.5, cy + 1);
      g.stroke();
      break;
    case "forced_sleep":
      g.strokeStyle = C.critical;
      g.lineWidth = 2.2;
      g.lineCap = "round";
      g.moveTo(cx - 4, cy - 4);
      g.lineTo(cx + 4, cy + 4);
      g.moveTo(cx + 4, cy - 4);
      g.lineTo(cx - 4, cy + 4);
      g.stroke();
      break;
    case "purchase": // a hollow diamond: money out, for a thing
      g.moveTo(cx, cy - 5.5);
      g.lineTo(cx + 5, cy);
      g.lineTo(cx, cy + 5.5);
      g.lineTo(cx - 5, cy);
      g.closePath();
      g.fillStyle = C.surface;
      g.fill();
      g.strokeStyle = C.muted;
      g.stroke();
      break;
    case "settlement": // a hollow disc with a bar: the rent and the charges taken at midnight
      g.arc(cx, cy, 4.5, 0, 2 * Math.PI);
      g.fillStyle = C.surface;
      g.fill();
      g.strokeStyle = C["ink-2"];
      g.stroke();
      g.beginPath();
      g.moveTo(cx - 2.5, cy);
      g.lineTo(cx + 2.5, cy);
      g.stroke();
      break;
    case "message": // a folded note
      g.rect(cx - 5, cy - 3.5, 10, 7);
      g.fillStyle = C.surface;
      g.fill();
      g.strokeStyle = C["lane-conversation"];
      g.stroke();
      g.beginPath();
      g.moveTo(cx - 5, cy - 3.5);
      g.lineTo(cx, cy + 0.5);
      g.lineTo(cx + 5, cy - 3.5);
      g.stroke();
      break;
    case "move_in": // a house
      g.moveTo(cx - 5.5, cy);
      g.lineTo(cx, cy - 5.5);
      g.lineTo(cx + 5.5, cy);
      g.lineTo(cx + 3.5, cy);
      g.lineTo(cx + 3.5, cy + 5);
      g.lineTo(cx - 3.5, cy + 5);
      g.lineTo(cx - 3.5, cy);
      g.closePath();
      g.fillStyle = C.o1;
      g.fill();
      break;
    case "condition": // a small ring: how the body feels changed; filled where it is at its worst
      g.arc(cx, cy, 3.2, 0, 2 * Math.PI);
      g.fillStyle = m.lowest ? C.warn : C.surface;
      g.fill();
      g.strokeStyle = m.lowest ? C.warn : C.muted;
      g.stroke();
      break;
    case "death": // a dark disc: the lane ends here
      g.arc(cx, cy, 5, 0, 2 * Math.PI);
      g.fillStyle = C.ink;
      g.fill();
      break;
    default: // a kind the viewer does not know
      g.arc(cx, cy, 4, 0, 2 * Math.PI);
      g.strokeStyle = C["ink-2"];
      g.stroke();
  }
}

const countHalf = (g, count) => Math.max(8, g.measureText(String(count)).width / 2 + 5);

/** Several markers of a row within a few pixels, drawn as one count. */
export function drawCount(g, count, cx, cy, C) {
  g.font = `600 10px ${FONT}`;
  g.textAlign = "center";
  g.textBaseline = "middle";
  const half = countHalf(g, count);
  g.beginPath();
  g.roundRect(cx - half, cy - 6, 2 * half, 12, 6);
  g.fillStyle = C["ink-2"];
  g.fill();
  g.fillStyle = C.surface;
  g.fillText(String(count), cx, cy + 0.5);
}

/** The colour tokens of the stylesheet the canvas draws with, read afresh for the colour scheme. */
export function readColours() {
  const style = getComputedStyle(document.documentElement);
  return Object.fromEntries(TOKENS.map((name) => [name, style.getPropertyValue(`--${name}`).trim()]));
}

/** The legend of the lanes: the bands and strips as swatches, every marker drawn as on the lanes, the lines. */
export function legend(C) {
  const swatch = (kind) => h("i", { class: `swatch ${kind}` });
  const glyph = (m) => {
    const canvas = h("canvas", { width: 28, height: 28 });
    const g = canvas.getContext("2d");
    g.scale(2, 2);
    drawMarker(g, m, 7, 7, C);
    return canvas;
  };
  const count = () => {
    const canvas = h("canvas", { class: "count", width: 48, height: 28 });
    const g = canvas.getContext("2d");
    g.scale(2, 2);
    drawCount(g, 5, 12, 7, C);
    return canvas;
  };
  const item = (mark, label) => h("span", {}, mark, label);
  const row = (lead, ...items) => h("div", { class: "legend-row" }, h("span", { class: "legend-lead" }, lead), items);
  return h(
    "div",
    { class: "lanes-legend" },
    row("Doing", ...["idle", "movement", "work", "sleep", "dead"].map((k) => item(swatch(k), EVENTS[k])), item(swatch("conversation"), "Conversation, above what it interrupted")),
    row("Where", item(swatch("place-home"), "at home"), item(swatch("place-workplace"), "at the workplace"), item(swatch("place-social"), "out, at a social place or a shop"), item(swatch("place-road"), "on the way")),
    row("Tasks", item(glyph({ kind: "claim" }), "claimed"), item(glyph({ kind: "submission", resolved: true }), "handed in, accepted"), item(glyph({ kind: "submission", resolved: false }), "not accepted"), item(glyph({ kind: "submission" }), "awaiting the verdict"), item(glyph({ kind: "abandon" }), "given up"), item(glyph({ kind: "expiry" }), "claim run out")),
    row("Money", item(glyph({ kind: "payment" }), "paid for a task"), item(glyph({ kind: "gift" }), "money handed over"), item(glyph({ kind: "purchase" }), "something bought"), item(glyph({ kind: "settlement" }), "rent and charges taken at midnight")),
    row("Social", item(glyph({ kind: "speech" }), "something said"), item(glyph({ kind: "speech", private: true }), "said privately"), item(glyph({ kind: "message" }), "a message written"), item(glyph({ kind: "rating" }), "a rating given"), item(glyph({ kind: "skill_shared" }), "a skill passed on"), item(glyph({ kind: "move_in" }), "moved house"), item(glyph({ kind: "journal" }), "to bed with the day's journal"), item(glyph({ kind: "forced_sleep" }), "forced sleep")),
    row("Body", item(glyph({ kind: "condition" }), "feels differently: hungrier, more tired, better or worse"), item(glyph({ kind: "condition", lowest: true }), "starving, exhausted or gravely ill"), item(glyph({ kind: "death" }), "died")),
    row("Lines", item(count(), "several within a few pixels: hover, or zoom in"), item(swatch("dashed"), "checkpoint"), item(swatch("now"), "now"), item(swatch("cursor"), "the moment shown"), item(swatch("purse"), "purse, one scale for all")),
  );
}

/** A place's name without its article, capitalised, for a label on a band. */
const short = (name) => {
  const text = name.replace(/^the\s+/i, "");
  return text[0].toUpperCase() + text.slice(1);
};

export class Lanes {
  /**
   * `timeline` is the run's timeline document and `world` its world; `onSelect(name)` is called
   * for a lane picked, `onMoment(t)` for a time clicked, `onView(t0, t1)` whenever the window
   * changes.
   */
  constructor({ timeline, world, cast, onSelect, onMoment, onView }) {
    this.data = timeline;
    this.cast = cast;
    this.kinds = new Map(world.places.map((place) => [place.id, place.kind]));
    this.handlers = { onSelect, onMoment, onView };
    this.canvas = h("canvas", { class: "lanes-canvas", "aria-label": "Every resident's events over simulated time" });
    this.ctx = this.canvas.getContext("2d");
    this.tip = h("div", { class: "lanes-tip", role: "tooltip", hidden: true });
    this.el = h("div", { class: "lanes" }, this.canvas, this.tip);
    this.C = readColours();
    this.hatch = null;
    this.paths = new Map();
    this.labelW = LABEL_WIDE;
    this.t0 = 0;
    this.t1 = DAY;
    this.cursor = null;
    this.selected = null;
    this.hover = null; // what is under the pointer: {px, py, found}
    this.lit = null; // the conversations to outline, by lane, while one is hovered
    this.heard = null; // the residents who heard the speech hovered
    this.drawn = {}; // where each lane's markers were drawn, for hovering
    this.drag = null;
    this.pinch = null;
    this.pointers = new Map();
    this.gestures();
    this.observer = new ResizeObserver(() => this.draw());
    this.observer.observe(this.el);
    this.scheme = matchMedia("(prefers-color-scheme: dark)");
    this.onScheme = () => {
      this.C = readColours();
      this.hatch = null;
      this.draw();
    };
    this.scheme.addEventListener("change", this.onScheme);
  }

  setData(timeline) {
    this.data = timeline;
    this.hover = null;
    this.lit = null;
    this.heard = null;
    this.draw();
  }

  setCursor(time) {
    this.cursor = time;
    this.draw();
  }

  setSelected(name) {
    this.selected = name;
    this.draw();
  }

  // The window -------------------------------------------------------------------------------

  domain() {
    const d = this.data;
    return [Math.floor(d.start / DAY) * DAY, Math.max(Math.ceil((d.now + 1) / DAY) * DAY, DAY)];
  }

  plotW() {
    return Math.max(this.canvas.clientWidth - this.labelW, 1);
  }

  x(t) {
    return this.labelW + ((t - this.t0) / (this.t1 - this.t0)) * this.plotW();
  }

  tAt(px) {
    return this.t0 + ((px - this.labelW) / this.plotW()) * (this.t1 - this.t0);
  }

  setView(t0, t1, quiet = false) {
    const [d0, d1] = this.domain();
    const span = Math.min(Math.max(t1 - t0, MIN_SPAN), d1 - d0);
    t0 = Math.min(Math.max(t0, d0), d1 - span);
    this.t0 = t0;
    this.t1 = t0 + span;
    this.draw();
    if (!quiet) this.handlers.onView?.(this.t0, this.t1);
  }

  zoom(factor, around = (this.t0 + this.t1) / 2) {
    this.setView(around - (around - this.t0) * factor, around + (this.t1 - around) * factor);
  }

  pan(fraction) {
    const shift = (this.t1 - this.t0) * fraction;
    this.setView(this.t0 + shift, this.t1 + shift);
  }

  wholeRun() {
    this.setView(...this.domain());
  }

  /** The lived day in the middle of the window, at full width. */
  oneDay() {
    const day = livedDay(this.data.days, (this.t0 + this.t1) / 2);
    this.setView(day.start, day.start + DAY);
  }

  /** Centre the window on a time, keeping its width. */
  centre(time) {
    const half = (this.t1 - this.t0) / 2;
    this.setView(time - half, time + half);
  }

  /** The window moved to the start of the run, or to now, keeping its width. */
  toStart() {
    this.setView(this.domain()[0], this.domain()[0] + (this.t1 - this.t0));
  }

  toNow() {
    this.setView(this.data.now - (this.t1 - this.t0), this.data.now);
  }

  // Drawing -----------------------------------------------------------------------------------

  hourStep() {
    const perSecond = this.plotW() / (this.t1 - this.t0);
    return [300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200].find((step) => step * perSecond >= 56) || null;
  }

  /** The lived days, and the days still to come up to the end of the domain. */
  days() {
    const lived = this.data.days;
    if (!lived.length) return [];
    const found = lived.map((day) => ({ ...day, planned: false }));
    const last = lived.at(-1);
    const [, d1] = this.domain();
    for (let start = last.end ?? last.start + DAY, k = 1; start < d1; start += DAY, k++) found.push({ day: last.day + k, start, end: null, planned: true });
    return found;
  }

  clock(t) {
    return `${dateOf(this.data.start_date, t)} ${hhmm(secondOfDay(t))}`;
  }

  /** The axis; `boxes` are the time labels drawn over it later, which hour labels keep clear of. */
  drawAxis(height, boxes) {
    const { ctx, C, t0, t1 } = this;
    const width = this.canvas.clientWidth;
    const left = this.labelW;
    ctx.save();
    ctx.beginPath();
    ctx.rect(left, 0, width - left, height);
    ctx.clip();
    ctx.textBaseline = "middle";
    const step = this.hourStep();
    if (step) {
      ctx.font = `11px ${FONT}`;
      ctx.textAlign = "center";
      for (let t = Math.ceil(t0 / step) * step; t <= t1; t += step) {
        if (t % DAY === 0) continue;
        const px = Math.round(this.x(t)) + 0.5;
        ctx.fillStyle = C.line;
        ctx.fillRect(px - 0.5, AXIS_H - 5, 1, height - AXIS_H + 5);
        // A label cut by the edge, or under a time box, is left out.
        if (px - 18 < left || px + 18 > width || boxes.some((box) => Math.abs(box.cx - px) < box.half + 20)) continue;
        ctx.fillStyle = C.muted;
        ctx.fillText(hhmm(secondOfDay(t)), px, AXIS_H - 11);
      }
    }
    const after = this.x(this.data.now);
    let nowBox = null; // where "now" is written, which a day's name keeps clear of
    if (after >= left && after + 30 <= width) {
      ctx.font = `600 11px ${FONT}`;
      ctx.textAlign = "left";
      ctx.fillStyle = C["ink-2"];
      ctx.fillText("now", after + 5, STRIP_Y + STRIP_H + 13);
      nowBox = [after, after + 5 + ctx.measureText("now").width];
    }
    // Midnights as faint lines through the lanes.
    for (let t = Math.ceil(t0 / DAY) * DAY; t <= t1; t += DAY) {
      const px = Math.round(this.x(t)) + 0.5;
      ctx.fillStyle = C["line-2"];
      ctx.fillRect(px - 0.5, AXIS_H - 5, 1, height - AXIS_H + 5);
    }
    // The lived days, from checkpoint to checkpoint, each named with its date where there is
    // room and closed by a dashed line; the days still to come are named quietly.
    ctx.setLineDash([3, 3]);
    ctx.strokeStyle = C.muted;
    ctx.lineWidth = 1;
    ctx.textAlign = "left";
    ctx.font = `600 11.5px ${FONT}`;
    for (const day of this.days()) {
      if (day.end !== null && day.end >= t0 && day.end <= t1) {
        const px = Math.round(this.x(day.end)) + 0.5;
        ctx.beginPath();
        ctx.moveTo(px, STRIP_Y + STRIP_H + 4);
        ctx.lineTo(px, height);
        ctx.stroke();
      }
      let from = Math.max(this.x(day.start), left) + 6;
      const date = dateOf(this.data.start_date, day.start + 4 * 3600);
      const width_ = (text) => ctx.measureText(text).width;
      // A name that would run into "now" moves past it.
      if (nowBox && from < nowBox[1] + 8 && from + width_(`${day.day}`) > nowBox[0] - 4) from = nowBox[1] + 8;
      const room = Math.min(this.x(day.end ?? day.start + DAY), width) - from - 4;
      const label = [`Day ${day.day} · ${date}`, `Day ${day.day}`, `${day.day}`].find((text) => width_(text) <= room);
      if (!label) continue;
      ctx.fillStyle = day.planned ? C.muted : C.ink;
      ctx.fillText(label, from, STRIP_Y + STRIP_H + 13);
    }
    ctx.setLineDash([]);
    ctx.restore();
  }

  /** The day strip: the whole run across the plot, the lived part darker, the window on it. */
  drawStrip() {
    const { ctx, C } = this;
    const [d0, d1] = this.domain();
    const left = this.labelW;
    const w = this.plotW();
    const sx = (t) => left + ((t - d0) / (d1 - d0)) * w;
    ctx.fillStyle = C["surface-3"];
    ctx.fillRect(left, STRIP_Y, w, STRIP_H);
    ctx.fillStyle = C["line-2"];
    ctx.fillRect(left, STRIP_Y, Math.max(sx(this.data.now) - left, 0), STRIP_H);
    ctx.fillStyle = C.surface;
    for (const day of this.data.days) if (day.end !== null) ctx.fillRect(Math.round(sx(day.end)), STRIP_Y, 1, STRIP_H);
    const x0 = Math.round(sx(this.t0));
    const x1 = Math.max(Math.round(sx(this.t1)), x0 + 3);
    ctx.fillStyle = C.accent;
    ctx.globalAlpha = 0.3;
    ctx.fillRect(x0, STRIP_Y - 1, x1 - x0, STRIP_H + 2);
    ctx.globalAlpha = 1;
    ctx.strokeStyle = C.accent;
    ctx.lineWidth = 1;
    ctx.strokeRect(x0 + 0.5, STRIP_Y - 0.5, x1 - x0 - 1, STRIP_H + 1);
  }

  /** A time box on the axis at `x`, kept inside the plot: its place, to draw it with `drawBox`. */
  box(x, text, fill, colour, stroke) {
    const { ctx } = this;
    ctx.font = `600 11px ${FONT}`;
    const half = ctx.measureText(text).width / 2 + 6;
    const cx = Math.min(Math.max(x, this.labelW + half), this.canvas.clientWidth - half);
    return { cx, half, text, fill, colour, stroke };
  }

  drawBox({ cx, half, text, fill, colour, stroke }) {
    const { ctx } = this;
    ctx.font = `600 11px ${FONT}`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.beginPath();
    ctx.roundRect(cx - half, AXIS_H - 19, 2 * half, 16, 4);
    ctx.fillStyle = fill;
    ctx.fill();
    ctx.strokeStyle = stroke;
    ctx.lineWidth = 1;
    ctx.stroke();
    ctx.fillStyle = colour;
    ctx.fillText(text, cx, AXIS_H - 10.5);
  }

  /** Diagonal stripes in the colour of movement, for the band of a walk. */
  hatched() {
    if (!this.hatch) {
      const tile = document.createElement("canvas");
      tile.width = tile.height = 8;
      const g = tile.getContext("2d");
      g.fillStyle = this.C["lane-idle"];
      g.fillRect(0, 0, 8, 8);
      g.strokeStyle = this.C["lane-movement"];
      g.lineWidth = 2.5;
      g.beginPath();
      g.moveTo(-2, 10);
      g.lineTo(10, -2);
      g.moveTo(-2, 2);
      g.lineTo(2, -2);
      g.moveTo(6, 10);
      g.lineTo(10, 6);
      g.stroke();
      this.hatch = this.ctx.createPattern(tile, "repeat");
    }
    return this.hatch;
  }

  placeColour(seg) {
    if (seg.kind === "movement") return this.C["line-2"];
    const token = PLACE_COLOUR[this.kinds.get(seg.place)];
    return token ? this.C[token] : this.C["line-2"];
  }

  placeName(id) {
    return id == null ? "on the way" : this.data.places[id] || id;
  }

  /** The resident's badge, as the identity module draws it, with radius `r`. */
  badge(name, cx, cy, r) {
    const { ctx, C } = this;
    const shape = this.cast.shape(name);
    const slot = this.cast.slot(name);
    if (!this.paths.has(shape.d)) this.paths.set(shape.d, new Path2D(shape.d));
    ctx.save();
    ctx.translate(cx, cy);
    ctx.scale(r, r);
    ctx.fillStyle = C[`a${slot}`];
    ctx.fill(this.paths.get(shape.d));
    ctx.restore();
    const initial = this.cast.initials.get(name);
    ctx.fillStyle = C[`a${slot}-ink`];
    ctx.font = `600 ${(initial.length > 1 ? 0.95 : 1.25) * r}px ${FONT}`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(initial, cx, cy + shape.dy * r + 0.5);
  }

  fit(text, width) {
    const { ctx } = this;
    if (ctx.measureText(text).width <= width) return text;
    while (text.length > 1 && ctx.measureText(`${text}…`).width > width) text = text.slice(0, -1);
    return `${text}…`;
  }

  /** The band's label, the longest of its forms that fits the band's visible part. */
  bandLabel(seg, x0, x1, top) {
    const { ctx, C } = this;
    const left = Math.max(x0, this.labelW) + 5;
    const room = Math.min(x1, this.canvas.clientWidth) - left - 4;
    if (room < 16) return;
    const place = seg.place == null ? "on the way" : short(this.placeName(seg.place));
    const what = seg.kind === "work" ? (seg.task == null ? "Work, no task" : `Task ${seg.task}`) : seg.kind === "movement" ? `→ ${place}` : (EVENTS[seg.kind] ?? seg.kind);
    const forms = seg.kind === "movement" ? [what, "→"] : [`${what} · ${place}`, what];
    ctx.font = `600 11px ${FONT}`;
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    const text = forms.find((form) => ctx.measureText(form).width <= room);
    if (!text) return;
    const y = top + BAND_Y + BAND_H / 2 + 0.5;
    if (seg.kind === "movement") {
      ctx.lineWidth = 3;
      ctx.lineJoin = "round";
      ctx.strokeStyle = C["lane-idle"];
      ctx.strokeText(text, left, y);
    }
    ctx.fillStyle = seg.kind === "work" ? C.surface : C.ink;
    ctx.fillText(text, left, y);
  }

  /** The partners of a conversation named on its band, as many as fit, the rest counted. */
  partners(c, x0, x1, y) {
    const { ctx, C } = this;
    ctx.font = `600 10.5px ${FONT}`;
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    let px = Math.max(x0, this.labelW) + 5;
    const end = Math.min(x1, this.canvas.clientWidth) - 4;
    const cy = y + CONV_H / 2;
    for (let i = 0; i < c.with.length; i++) {
      const name = c.with[i];
      const w = 13 + ctx.measureText(name).width;
      if (px + w > end) {
        const more = `+${c.with.length - i}`;
        if (i && px + ctx.measureText(more).width <= end) {
          ctx.fillStyle = C.ink;
          ctx.fillText(more, px, cy + 0.5);
        }
        return;
      }
      this.badge(name, px + 5, cy, 5);
      ctx.fillStyle = C.ink;
      ctx.font = `600 10.5px ${FONT}`;
      ctx.textAlign = "left";
      ctx.fillText(name, px + 13, cy + 0.5);
      px += w + 8;
    }
  }

  /** The markers of one row grouped: each joins the group before it when drawn within GAP of it. */
  clusters(markers) {
    const { ctx } = this;
    ctx.font = `600 10px ${FONT}`;
    const found = [];
    for (const m of markers) {
      const x = this.x(m.t);
      const last = found.at(-1);
      if (last && x - last.right < GAP) {
        last.items.push(m);
        last.cx = (last.x0 + x) / 2;
        last.half = countHalf(ctx, last.items.length);
        last.right = Math.max(last.cx + last.half, x + GLYPH);
      } else found.push({ items: [m], x0: x, cx: x, half: GLYPH, right: x + GLYPH });
    }
    return found;
  }

  drawLane(r, top, scale) {
    const { ctx, C, t0, t1 } = this;
    const width = this.canvas.clientWidth;
    const left = this.labelW;
    if (r.name === this.selected) {
      ctx.fillStyle = C["accent-soft"];
      ctx.fillRect(0, top, width, LANE_H);
    }
    ctx.fillStyle = C.line;
    ctx.fillRect(0, top + LANE_H - 1, width, 1);
    ctx.save();
    ctx.beginPath();
    ctx.rect(left, top, width - left, LANE_H);
    ctx.clip();
    // The band, with a seam where the event changes, and the place strip under it.
    for (let i = lowerBound(r.segments, t0, (seg) => seg.end); i < r.segments.length && r.segments[i].start < t1; i++) {
      const seg = r.segments[i];
      const x0 = this.x(seg.start);
      const x1 = this.x(seg.end);
      const w = Math.max(x1 - x0, 0.75);
      ctx.fillStyle = seg.kind === "movement" ? this.hatched() : (C[`lane-${seg.kind}`] ?? C["lane-idle"]);
      ctx.fillRect(x0, top + BAND_Y, w, BAND_H);
      if (i > 0 && w > 3) {
        ctx.fillStyle = C.surface;
        ctx.fillRect(x0, top + BAND_Y, 1, BAND_H);
      }
      ctx.fillStyle = this.placeColour(seg);
      ctx.fillRect(x0, top + PLACE_Y, w, PLACE_H);
      this.bandLabel(seg, x0, x1, top);
    }
    // The conversations, on their own row above the band.
    for (let i = lowerBound(r.conversations, t0, (c) => c.end); i < r.conversations.length && r.conversations[i].start < t1; i++) {
      const c = r.conversations[i];
      const x0 = this.x(c.start);
      const w = Math.max(this.x(c.end) - x0, 2);
      const y = top + CONV_Y;
      ctx.fillStyle = C["lane-conversation"];
      if (w < 8) ctx.fillRect(x0, y, w, CONV_H);
      else {
        ctx.globalAlpha = 0.3;
        ctx.fillRect(x0, y, w, CONV_H);
        ctx.globalAlpha = 1;
        ctx.fillRect(x0, y, w, 2.5);
        this.partners(c, x0, x0 + w, y);
      }
      if (this.lit?.get(r.name) === c) {
        ctx.strokeStyle = C.ink;
        ctx.lineWidth = 1.5;
        ctx.strokeRect(x0 - 0.75, y - 0.75, w + 1.5, CONV_H + 1.5);
      }
    }
    // The purse: a step line under the band, on one scale for every lane, from its baseline.
    const py = (v) => top + PURSE_Y + PURSE_H - ((v - scale.min) / (scale.max - scale.min || 1)) * PURSE_H;
    ctx.fillStyle = C.line;
    ctx.fillRect(left, Math.round(py(0)), width - left, 1);
    ctx.strokeStyle = C["ink-2"];
    ctx.lineWidth = 1.25;
    ctx.beginPath();
    const points = r.purse;
    const first = Math.max(lowerBound(points, t0, (p) => p[0]) - 1, 0);
    ctx.moveTo(this.x(points[first][0]), py(points[first][1]));
    for (let i = first + 1; i < points.length && points[i - 1][0] <= t1; i++) {
      ctx.lineTo(this.x(points[i][0]), py(points[i - 1][1]));
      ctx.lineTo(this.x(points[i][0]), py(points[i][1]));
    }
    ctx.lineTo(this.x(this.data.now), py(points[points.length - 1][1]));
    ctx.stroke();
    // The markers in their rows, those within a few pixels folded into a count; where each was
    // drawn is kept for hovering.
    const from = lowerBound(r.markers, this.tAt(left - 12), (m) => m.t);
    const to = lowerBound(r.markers, this.tAt(width + 12), (m) => m.t);
    const rows = ROWS.map(() => []);
    for (let i = from; i < to; i++) rows[ROW_OF[r.markers[i].kind] ?? 2].push(r.markers[i]);
    const drawn = (this.drawn[r.name] = []);
    rows.forEach((list, row) => {
      const cy = top + ROW_Y[row];
      for (const cluster of this.clusters(list)) {
        if (cluster.items.length === 1) drawMarker(ctx, cluster.items[0], cluster.cx, cy, C);
        else drawCount(ctx, cluster.items.length, cluster.cx, cy, C);
        drawn.push({ row, cx: cluster.cx, half: cluster.half, items: cluster.items });
      }
    });
    ctx.restore();
    // The label column: the rows' captions, the badge and name by the band, the purse by its
    // line; on a phone, the name and the purse. A hearer of the speech hovered wears a ring.
    const wide = left === LABEL_WIDE;
    const x = wide ? 31 : 27;
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    if (wide) {
      ctx.font = `10px ${FONT}`;
      ctx.fillStyle = C.muted;
      ROWS.forEach((name, k) => ctx.fillText(name, x, top + ROW_Y[k] + 0.5));
    }
    const mid = top + BAND_Y + BAND_H / 2;
    const [bx, br] = wide ? [18, 8] : [15, 7];
    if (this.heard?.has(r.name)) {
      ctx.beginPath();
      ctx.arc(bx, mid, br + 3.5, 0, 2 * Math.PI);
      ctx.strokeStyle = C.ink;
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }
    this.badge(r.name, bx, mid, br);
    ctx.font = `600 13px ${FONT}`;
    ctx.textAlign = "left";
    ctx.fillStyle = C.ink;
    ctx.fillText(this.fit(r.name, left - x - 6), x, mid + 0.5);
    ctx.font = `11.5px ${FONT}`;
    ctx.fillStyle = C["ink-2"];
    ctx.fillText(fmt.money(points[points.length - 1][1]), x, top + PURSE_Y + PURSE_H / 2 + 0.5);
  }

  /** Who heard the speech hovered: a dotted line from the speaker's tick to a ring on each hearer's conversation row. */
  drawHeard() {
    const { ctx, C } = this;
    const found = this.hover?.found;
    const m = found?.cluster?.items.length === 1 ? found.cluster.items[0] : null;
    if (!m || m.kind !== "speech" || !m.to?.length) return;
    const x = Math.round(this.x(m.t)) + 0.5;
    if (x < this.labelW || x > this.canvas.clientWidth) return;
    const index = new Map(this.data.residents.map((r, i) => [r.name, i]));
    const ys = m.to.filter((name) => index.has(name)).map((name) => AXIS_H + index.get(name) * LANE_H + CONV_Y + CONV_H / 2);
    if (!ys.length) return;
    const own = AXIS_H + index.get(found.r.name) * LANE_H + ROW_Y[2];
    ctx.save();
    ctx.setLineDash([2, 3]);
    ctx.strokeStyle = C.ink;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x, Math.min(own, ...ys));
    ctx.lineTo(x, Math.max(own, ...ys));
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.lineWidth = 1.5;
    for (const y of ys) {
      ctx.beginPath();
      ctx.arc(x, y, 4, 0, 2 * Math.PI);
      ctx.fillStyle = C.surface;
      ctx.fill();
      ctx.stroke();
    }
    ctx.restore();
  }

  draw() {
    if (!this.data || !this.canvas.clientWidth) return;
    const { ctx, C } = this;
    const residents = this.data.residents;
    const height = AXIS_H + residents.length * LANE_H;
    const dpr = window.devicePixelRatio || 1;
    const width = this.canvas.clientWidth;
    this.labelW = width < 560 ? LABEL_NARROW : LABEL_WIDE;
    this.canvas.style.height = `${height}px`;
    this.canvas.width = Math.round(width * dpr);
    this.canvas.height = Math.round(height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = C.surface;
    ctx.fillRect(0, 0, width, height);
    const after = this.x(this.data.now);
    if (after < width) {
      ctx.fillStyle = C.page;
      ctx.fillRect(Math.max(after, this.labelW), AXIS_H, width, height - AXIS_H);
    }
    // The pointer's moment as a hairline with its time, the moment shown as the accent line
    // with its time, unless the pointer's box would cover it.
    const [d0, d1] = this.domain();
    const hx = this.hover && this.hover.px >= this.labelW && this.hover.px <= width && !this.hover.found?.strip && this.tAt(this.hover.px) >= d0 && this.tAt(this.hover.px) <= d1 ? this.hover.px : null;
    const cx = this.cursor !== null && this.x(this.cursor) >= this.labelW && this.x(this.cursor) <= width ? this.x(this.cursor) : null;
    const boxes = [];
    if (hx !== null) boxes.push(this.box(hx, this.clock(this.tAt(hx)), C.surface, C["ink-2"], C["line-2"]));
    if (cx !== null && (hx === null || Math.abs(hx - cx) > 90)) boxes.push(this.box(cx, this.clock(this.cursor), C.accent, C.surface, C.accent));
    this.drawAxis(height, boxes);
    const values = residents.flatMap((r) => r.purse.map((p) => p[1]));
    const scale = { min: Math.min(0, ...values), max: Math.max(0, ...values) };
    residents.forEach((r, i) => this.drawLane(r, AXIS_H + i * LANE_H, scale));
    this.drawHeard();
    if (after >= this.labelW && after <= width) {
      ctx.fillStyle = C["ink-2"];
      ctx.fillRect(Math.round(after) - 0.5, AXIS_H - 6, 1.5, height);
    }
    if (hx !== null) {
      ctx.fillStyle = C["line-2"];
      ctx.fillRect(Math.round(hx) - 0.5, AXIS_H - 6, 1, height);
    }
    if (cx !== null) {
      ctx.fillStyle = C.accent;
      ctx.fillRect(Math.round(cx) - 1, AXIS_H - 6, 2, height);
    }
    for (const box of boxes) this.drawBox(box);
    ctx.fillStyle = C["line-2"];
    ctx.fillRect(this.labelW - 1, 0, 1, height);
    this.drawStrip();
  }

  // Hover and selection ------------------------------------------------------------------------

  hit(px, py) {
    const residents = this.data?.residents ?? [];
    if (px >= this.labelW && py >= STRIP_Y - 3 && py <= STRIP_Y + STRIP_H + 3) return { strip: true };
    const i = Math.floor((py - AXIS_H) / LANE_H);
    if (py < AXIS_H || i >= residents.length) return null;
    const r = residents[i];
    const y = py - AXIS_H - i * LANE_H;
    const t = this.tAt(px);
    if (px < this.labelW) return { r, t: null };
    if (y < CONV_Y - 1) {
      const row = Math.min(Math.max(Math.round((y - ROW_Y[0]) / ROW_H), 0), ROWS.length - 1);
      let best = null;
      for (const c of this.drawn[r.name] ?? []) {
        const d = Math.abs(c.cx - px);
        if (c.row === row && d <= c.half + 2 && (!best || d < best.d)) best = { d, c };
      }
      return best ? { r, t, cluster: best.c, row } : { r, t };
    }
    if (t > this.data.now) return { r, t };
    if (y < BAND_Y - 1) {
      const c = this.at(r.conversations, t);
      return c ? { r, t, conversation: c } : { r, t };
    }
    if (y < PLACE_Y + PLACE_H + 2) return { r, t, segment: this.at(r.segments, t) };
    return { r, t, purse: [t, purseAt(r, t)] };
  }

  at(spans, t) {
    const i = lowerBound(spans, t, (span) => span.end);
    const span = spans[i === spans.length ? i - 1 : i];
    return span && span.start <= t && t <= span.end ? span : null;
  }

  /** The hovered conversation and the partners' conversations that overlap it, by lane. */
  litOf(found) {
    const c = found?.conversation;
    if (!c) return null;
    const lit = new Map([[found.r.name, c]]);
    for (const name of c.with) {
      const partner = this.data.residents.find((r) => r.name === name);
      const theirs = partner?.conversations.find((o) => o.start < c.end && c.start < o.end && o.with.includes(found.r.name));
      if (theirs) lit.set(name, theirs);
    }
    return lit;
  }

  moment(t) {
    return `Day ${livedDay(this.data.days, t).day}, ${this.clock(t)}`;
  }

  between(a, b) {
    return Math.floor(a / DAY) === Math.floor(b / DAY) ? `${this.moment(a)}–${hhmm(secondOfDay(b))}` : `${this.moment(a)} – ${this.moment(b)}`;
  }

  showTip(found, px, py) {
    let content = null;
    const where = (t, place) => h("div", { class: "muted" }, `${this.moment(t)} · ${this.placeName(place)}`);
    if (found?.cluster?.items.length === 1) {
      const m = found.cluster.items[0];
      const [label, text] = describeMarker(m, found.r.name, found.r.name);
      content = [h("b", {}, found.r.name), " ", this.cast.mention(label), text ? h("div", {}, text.length > 400 ? `${text.slice(0, 400)}…` : text) : null, where(m.t, m.place)];
    } else if (found?.cluster) {
      const items = found.cluster.items;
      const shown = items.slice(0, 8);
      content = [
        h("b", {}, `${items.length} in the ${ROWS[found.row]} row`),
        h("div", { class: "muted" }, this.between(items[0].t, items.at(-1).t)),
        h("ul", {}, shown.map((m) => h("li", {}, `${hhmm(secondOfDay(m.t))} `, this.cast.mention(describeMarker(m, found.r.name, found.r.name)[0])))),
        items.length > shown.length ? h("div", { class: "muted" }, `and ${items.length - shown.length} more: zoom in`) : null,
      ];
    } else if (found?.conversation) {
      const c = found.conversation;
      content = [h("b", {}, "Conversation"), " with ", this.cast.mention(c.with.join(", ")), h("div", {}, `over ${EVENTS[c.over]?.toLowerCase() ?? c.over} at ${this.placeName(c.place)}`), h("div", { class: "muted" }, `${this.between(c.start, c.end)} (${duration(c.end - c.start)})`)];
    } else if (found?.segment) {
      const seg = found.segment;
      const what = seg.kind === "work" ? `Work · ${seg.task == null ? "no task held" : `task ${seg.task}`}` : (EVENTS[seg.kind] ?? seg.kind);
      const place = seg.kind === "movement" ? `on the way to ${this.placeName(seg.place)}` : `at ${this.placeName(seg.place)}`;
      content = [h("b", {}, what), h("div", {}, place), h("div", { class: "muted" }, `${this.between(seg.start, seg.end)} (${duration(seg.end - seg.start)})`)];
    } else if (found?.purse) {
      content = [h("b", {}, "Purse"), ` ${fmt.money(found.purse[1])}`, h("div", { class: "muted" }, this.moment(found.purse[0]))];
    }
    if (!content) {
      this.tip.hidden = true;
      return;
    }
    this.tip.replaceChildren(...content.flat().filter(Boolean));
    this.tip.hidden = false;
    const box = this.el.getBoundingClientRect();
    const left = Math.min(px + 14, box.width - this.tip.offsetWidth - 4);
    const top = py + 16 + this.tip.offsetHeight > box.height ? py - this.tip.offsetHeight - 8 : py + 16;
    this.tip.style.left = `${Math.max(left, 4)}px`;
    this.tip.style.top = `${Math.max(top, 4)}px`;
  }

  /** Centre the window where the day strip was pointed at. */
  scrub(px) {
    const [d0, d1] = this.domain();
    this.centre(d0 + ((px - this.labelW) / this.plotW()) * (d1 - d0));
  }

  hoverAt(px, py) {
    const found = this.hit(px, py);
    this.hover = { px, py, found };
    this.lit = this.litOf(found);
    const m = found?.cluster?.items.length === 1 ? found.cluster.items[0] : null;
    this.heard = m?.kind === "speech" ? new Set(m.to) : null;
    this.showTip(found, px, py);
    this.draw();
  }

  clearHover() {
    this.tip.hidden = true;
    this.hover = null;
    this.lit = null;
    this.heard = null;
    this.draw();
  }

  gestures() {
    const canvas = this.canvas;
    canvas.addEventListener(
      "wheel",
      (e) => {
        if (!this.data) return;
        e.preventDefault();
        if (e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY)) this.pan((e.deltaX || e.deltaY) / this.plotW());
        else this.zoom(Math.exp(e.deltaY * 0.0015), Math.max(this.tAt(e.offsetX), this.t0));
      },
      { passive: false },
    );
    canvas.addEventListener("pointerdown", (e) => {
      if (!this.data) return;
      canvas.setPointerCapture(e.pointerId);
      this.pointers.set(e.pointerId, e.offsetX);
      if (this.pointers.size === 2) {
        // Two fingers: a pinch zooms around their middle.
        this.drag = null;
        this.pinch = { t0: this.t0, t1: this.t1, xs: [...this.pointers.values()] };
        this.tip.hidden = true;
        return;
      }
      if (this.hit(e.offsetX, e.offsetY)?.strip) {
        this.drag = { strip: true };
        this.scrub(e.offsetX);
        return;
      }
      this.drag = { x: e.offsetX, t0: this.t0, t1: this.t1, moved: false };
    });
    canvas.addEventListener("pointermove", (e) => {
      if (!this.data) return;
      if (this.pointers.has(e.pointerId)) this.pointers.set(e.pointerId, e.offsetX);
      if (this.pinch && this.pointers.size === 2) {
        const [a0, b0] = this.pinch.xs;
        const [a1, b1] = [...this.pointers.values()];
        const span0 = this.pinch.t1 - this.pinch.t0;
        const span = (span0 * Math.max(Math.abs(b0 - a0), 1)) / Math.max(Math.abs(b1 - a1), 1);
        const middle = this.pinch.t0 + (((a0 + b0) / 2 - this.labelW) / this.plotW()) * span0;
        const t0 = middle - (((a1 + b1) / 2 - this.labelW) / this.plotW()) * span;
        this.setView(t0, t0 + span);
        return;
      }
      const d = this.drag;
      if (d?.strip) return this.scrub(e.offsetX);
      if (d) {
        if (Math.abs(e.offsetX - d.x) > 3) {
          d.moved = true;
          canvas.classList.add("dragging");
          this.tip.hidden = true;
        }
        if (d.moved) {
          const shift = ((d.x - e.offsetX) / this.plotW()) * (d.t1 - d.t0);
          this.setView(d.t0 + shift, d.t1 + shift);
        }
        return;
      }
      this.hoverAt(e.offsetX, e.offsetY);
    });
    const release = (e) => {
      this.pointers.delete(e.pointerId);
      if (this.pinch) {
        if (!this.pointers.size) this.pinch = null;
        return;
      }
      const d = this.drag;
      this.drag = null;
      canvas.classList.remove("dragging");
      if (!d || d.strip || d.moved || !this.data || e.type !== "pointerup") return;
      const found = this.hit(e.offsetX, e.offsetY);
      if (!found || found.strip) return;
      this.handlers.onSelect?.(found.r.name);
      const t = found.cluster?.items.length === 1 ? found.cluster.items[0].t : found.t;
      if (t !== null && t <= this.data.now) this.handlers.onMoment?.(Math.max(this.data.start, Math.round(t)));
    };
    canvas.addEventListener("pointerup", release);
    canvas.addEventListener("pointercancel", release);
    canvas.addEventListener("pointerleave", () => {
      if (!this.drag && !this.pinch) this.clearHover();
    });
  }

  destroy() {
    this.observer.disconnect();
    this.scheme.removeEventListener("change", this.onScheme);
  }
}
