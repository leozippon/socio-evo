// Every resident's events side by side on one canvas: a lane per resident over simulated time
// with its base event as a bar (idle, movement, work with the task held, sleep), conversation
// layered over it, the markers of what it did above, and its purse as a step line below. The
// view zooms and pans by wheel, drag and buttons; the moment shown elsewhere is a cursor.

import { DAY, dateOf, duration, hhmm, livedDay, secondOfDay } from "../clock.js";
import { fmt, h } from "../dom.js";
import { lowerBound, purseAt } from "../replay.js";
import { EVENTS, MARKERS } from "../world.js";
import { describeMarker } from "./events.js";

const LABEL_WIDE = 136; // the label column: the name, what the resident is in, its purse
const LABEL_NARROW = 84; // on a phone, the name and the purse
const AXIS_H = 40;
export const LANE_H = 74;
const MARK_Y = 10;
const BAR_Y = 19;
const BAR_H = 20;
const PURSE_Y = 45;
const PURSE_H = 22;
const MARK_GAP = 10;
const MIN_SPAN = 600;
const TOKENS = ["page", "surface", "ink", "ink-2", "muted", "line", "line-2", "accent", "accent-soft", "good", "critical", "lane-idle", "lane-sleep", "lane-movement", "lane-work", "lane-conversation", "lane-skill", "lane-rating"];

/** The marker's glyph, as the legend and the lanes draw it. */
export function drawMarker(g, m, cx, cy, C) {
  g.lineWidth = 1.6;
  g.beginPath();
  switch (m.kind) {
    case "speech":
      g.fillStyle = C["lane-conversation"];
      g.arc(cx, cy, 3.5, 0, 2 * Math.PI);
      g.fill();
      break;
    case "claim":
      g.fillStyle = C["ink-2"];
      g.moveTo(cx - 4.5, cy - 3.5);
      g.lineTo(cx + 4.5, cy - 3.5);
      g.lineTo(cx, cy + 4);
      g.fill();
      break;
    case "submission": {
      g.fillStyle = m.resolved === undefined ? C.muted : m.resolved ? C.good : C.critical;
      g.fillRect(cx - 4.5, cy - 4.5, 9, 9);
      g.strokeStyle = C.surface;
      g.beginPath();
      if (m.resolved) {
        g.moveTo(cx - 2.5, cy);
        g.lineTo(cx - 0.5, cy + 2);
        g.lineTo(cx + 2.8, cy - 2.2);
      } else if (m.resolved === false) {
        g.moveTo(cx - 2.2, cy - 2.2);
        g.lineTo(cx + 2.2, cy + 2.2);
        g.moveTo(cx + 2.2, cy - 2.2);
        g.lineTo(cx - 2.2, cy + 2.2);
      }
      g.stroke();
      break;
    }
    case "payment":
    case "gift":
      g.moveTo(cx, cy - 5);
      g.lineTo(cx + 4.5, cy);
      g.lineTo(cx, cy + 5);
      g.lineTo(cx - 4.5, cy);
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
      g.moveTo(cx - 4, cy);
      g.lineTo(cx + 4, cy);
      g.moveTo(cx, cy - 4);
      g.lineTo(cx, cy + 4);
      g.stroke();
      break;
    case "rating":
      for (let i = 0; i < 10; i++) {
        const r = i % 2 ? 2.2 : 5;
        const a = -Math.PI / 2 + (i * Math.PI) / 5;
        g.lineTo(cx + r * Math.cos(a), cy + r * Math.sin(a));
      }
      g.closePath();
      g.fillStyle = C["lane-rating"];
      g.fill();
      break;
    case "journal":
      g.fillStyle = C.surface;
      g.strokeStyle = C.ink;
      g.rect(cx - 3, cy - 4.5, 6, 9);
      g.fill();
      g.stroke();
      g.beginPath();
      g.moveTo(cx - 1.2, cy - 1.5);
      g.lineTo(cx + 1.2, cy - 1.5);
      g.moveTo(cx - 1.2, cy + 1);
      g.lineTo(cx + 1.2, cy + 1);
      g.stroke();
      break;
    case "forced_sleep":
      g.strokeStyle = C.critical;
      g.lineWidth = 2.2;
      g.moveTo(cx - 3.5, cy - 3.5);
      g.lineTo(cx + 3.5, cy + 3.5);
      g.moveTo(cx + 3.5, cy - 3.5);
      g.lineTo(cx - 3.5, cy + 3.5);
      g.stroke();
      break;
    default: // abandon, expiry
      g.strokeStyle = C.critical;
      g.fillStyle = C.surface;
      g.moveTo(cx - 4, cy + 3.5);
      g.lineTo(cx + 4, cy + 3.5);
      g.lineTo(cx, cy - 4);
      g.closePath();
      g.fill();
      g.stroke();
  }
}

/** The colour tokens of the stylesheet the canvas draws with, read afresh for the colour scheme. */
export function readColours() {
  const style = getComputedStyle(document.documentElement);
  return Object.fromEntries(TOKENS.map((name) => [name, style.getPropertyValue(`--${name}`).trim()]));
}

/** The legend of the lanes: the events as swatches and every marker drawn as on the lanes. */
export function legend(C) {
  const items = ["idle", "movement", "work", "sleep"].map((k) => h("span", {}, h("i", { class: "swatch", style: { background: `var(--lane-${k})` } }), EVENTS[k]));
  items.push(h("span", {}, h("i", { class: "swatch thin", style: { background: "var(--lane-conversation)" } }), "Conversation, over what it interrupted"));
  for (const [kind, label] of Object.entries(MARKERS)) {
    const canvas = h("canvas", { width: 28, height: 28 });
    const g = canvas.getContext("2d");
    g.scale(2, 2);
    drawMarker(g, { kind, resolved: kind === "submission" ? true : undefined }, 7, 7, C);
    items.push(h("span", {}, canvas, label));
  }
  items.push(h("span", {}, h("i", { class: "swatch dashed" }), "checkpoint"), h("span", {}, h("i", { class: "swatch purse" }), "purse, one scale for all"));
  return h("div", { class: "lanes-legend" }, items);
}

export class Lanes {
  /**
   * `timeline` is the run's timeline document; `onSelect(name)` is called for a lane picked,
   * `onMoment(t)` for a time clicked, `onView(t0, t1)` whenever the window changes.
   */
  constructor({ timeline, cast, onSelect, onMoment, onView }) {
    this.data = timeline;
    this.cast = cast;
    this.handlers = { onSelect, onMoment, onView };
    this.canvas = h("canvas", { class: "lanes-canvas", "aria-label": "Every resident's events over simulated time" });
    this.ctx = this.canvas.getContext("2d");
    this.tip = h("div", { class: "lanes-tip", role: "tooltip", hidden: true });
    this.el = h("div", { class: "lanes" }, this.canvas, this.tip);
    this.C = readColours();
    this.labelW = LABEL_WIDE;
    this.t0 = 0;
    this.t1 = DAY;
    this.cursor = null;
    this.selected = null;
    this.drawn = {};
    this.drag = null;
    this.gestures();
    this.observer = new ResizeObserver(() => this.draw());
    this.observer.observe(this.el);
    this.scheme = matchMedia("(prefers-color-scheme: dark)");
    this.onScheme = () => {
      this.C = readColours();
      this.draw();
    };
    this.scheme.addEventListener("change", this.onScheme);
  }

  setData(timeline) {
    this.data = timeline;
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

  // Drawing -----------------------------------------------------------------------------------

  hourStep() {
    const perSecond = this.plotW() / (this.t1 - this.t0);
    return [300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200].find((step) => step * perSecond >= 52) || null;
  }

  drawAxis(height) {
    const { ctx, C, t0, t1 } = this;
    const right = this.canvas.clientWidth;
    const step = this.hourStep();
    const perDay = (this.plotW() * DAY) / (t1 - t0);
    ctx.font = "11px system-ui, sans-serif";
    ctx.textBaseline = "middle";
    if (step) {
      for (let t = Math.ceil(t0 / step) * step; t <= t1; t += step) {
        if (t % DAY === 0) continue;
        const px = Math.round(this.x(t)) + 0.5;
        ctx.fillStyle = C.line;
        ctx.fillRect(px - 0.5, AXIS_H - 6, 1, height - AXIS_H + 6);
        ctx.fillStyle = C.muted;
        ctx.textAlign = "center";
        ctx.fillText(hhmm(secondOfDay(t)), px, AXIS_H - 12);
      }
    }
    // Midnights as faint lines; the lived days, from checkpoint to checkpoint, named on the
    // top row with their date, in full where there is room, and closed by a dashed line.
    for (let t = Math.floor(t0 / DAY) * DAY; t <= t1; t += DAY) {
      if (t < t0) continue;
      const px = Math.round(this.x(t)) + 0.5;
      ctx.fillStyle = C["line-2"];
      ctx.fillRect(px - 0.5, 4, 1, height - 4);
    }
    ctx.setLineDash([3, 3]);
    ctx.strokeStyle = C.muted;
    ctx.textAlign = "left";
    const planned = this.data.days.length ? Math.ceil((this.domain()[1] - this.data.days.at(-1).start) / DAY) : 0;
    const days = [...this.data.days];
    for (let k = 1; k <= planned; k++) days.push({ day: this.data.days.at(-1).day + k, start: this.data.days.at(-1).start + k * DAY, end: null, planned: true });
    for (const day of days) {
      if (day.end !== null && day.end >= t0 && day.end <= t1) {
        const px = Math.round(this.x(day.end)) + 0.5;
        ctx.beginPath();
        ctx.moveTo(px, AXIS_H - 4);
        ctx.lineTo(px, height);
        ctx.stroke();
      }
      const left = Math.max(this.x(day.start), this.labelW) + 5;
      const room = Math.min(this.x(day.start + DAY), right) - left - 6;
      const date = dateOf(this.data.start_date, day.start + 4 * 3600);
      const label = [`Day ${day.day} · ${date}`, `Day ${day.day}`, `${day.day}`].find((text) => ctx.measureText(text).width <= room);
      if (!label || day.start + DAY < t0) continue;
      ctx.fillStyle = day.planned ? C.muted : C.ink;
      ctx.fillText(label, left, 13);
    }
    ctx.setLineDash([]);
  }

  drawLane(r, top, scale) {
    const { ctx, C, t0, t1 } = this;
    const width = this.canvas.clientWidth;
    if (r.name === this.selected) {
      ctx.fillStyle = C["accent-soft"];
      ctx.fillRect(0, top, width, LANE_H);
    }
    ctx.fillStyle = C.line;
    ctx.fillRect(0, top + LANE_H - 1, width, 1);
    ctx.save();
    ctx.beginPath();
    ctx.rect(this.labelW, top, this.plotW(), LANE_H);
    ctx.clip();
    ctx.font = "11px system-ui, sans-serif";
    ctx.textBaseline = "middle";
    ctx.textAlign = "left";
    for (let i = lowerBound(r.segments, t0, (seg) => seg.end); i < r.segments.length && r.segments[i].start < t1; i++) {
      const seg = r.segments[i];
      const x0 = this.x(seg.start);
      const w = this.x(seg.end) - x0;
      const gap = w > 6 ? 1 : 0;
      ctx.fillStyle = C[`lane-${seg.kind}`];
      ctx.fillRect(x0 + gap, top + BAR_Y, Math.max(w - 2 * gap, 0.6), BAR_H);
      if (seg.kind === "work" && seg.task != null && w > 52) {
        ctx.fillStyle = C.surface;
        ctx.fillText(`task ${seg.task}`, Math.max(x0, this.labelW) + 5, top + BAR_Y + BAR_H / 2);
      }
    }
    for (let i = lowerBound(r.conversations, t0, (c) => c.end); i < r.conversations.length && r.conversations[i].start < t1; i++) {
      const c = r.conversations[i];
      const x0 = this.x(c.start);
      const w = Math.max(this.x(c.end) - x0, 2);
      ctx.fillStyle = C.surface;
      ctx.fillRect(x0 - 1, top + BAR_Y + 4, w + 2, BAR_H - 8);
      ctx.fillStyle = C["lane-conversation"];
      ctx.fillRect(x0, top + BAR_Y + 5, w, BAR_H - 10);
    }
    // The purse: a step line under the bar, on one scale for every lane.
    const py = (v) => top + PURSE_Y + PURSE_H - ((v - scale.min) / (scale.max - scale.min || 1)) * PURSE_H;
    if (scale.min < 0) {
      ctx.fillStyle = C.line;
      ctx.fillRect(this.labelW, Math.round(py(0)), this.plotW(), 1);
    }
    ctx.strokeStyle = C["ink-2"];
    ctx.lineWidth = 1.5;
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
    // Markers of the same second are set side by side; where each was drawn is kept for hovering.
    const from = lowerBound(r.markers, this.tAt(this.labelW - 6), (m) => m.t);
    const to = lowerBound(r.markers, this.tAt(width + 6), (m) => m.t);
    const drawn = (this.drawn[r.name] = []);
    for (let i = from, same = 0; i < to; i++) {
      const m = r.markers[i];
      same = i > from && r.markers[i - 1].t === m.t ? same + 1 : 0;
      const px = this.x(m.t) + same * MARK_GAP;
      drawMarker(ctx, m, px, top + MARK_Y, C);
      drawn.push([px, m]);
    }
    ctx.restore();
    // The label: the resident's colour and name, what it is in at the end of the log (where
    // there is room), its purse then.
    const last = r.segments[r.segments.length - 1];
    ctx.textAlign = "left";
    ctx.fillStyle = this.colour(r.name);
    ctx.fillRect(12, top + 8, 4, 12);
    ctx.fillStyle = C.ink;
    ctx.font = "600 13px system-ui, sans-serif";
    ctx.fillText(this.fit(r.name, this.labelW - 30), 22, top + 14);
    ctx.font = "11px system-ui, sans-serif";
    if (this.labelW === LABEL_WIDE) {
      ctx.fillStyle = C.muted;
      ctx.fillText(this.fit(`${EVENTS[last.kind].toLowerCase()} · ${this.placeName(last.place)}`, this.labelW - 30), 22, top + 31);
    }
    ctx.fillStyle = C["ink-2"];
    ctx.fillText(fmt.money(points[points.length - 1][1]), 22, top + PURSE_Y + PURSE_H / 2);
  }

  colour(name) {
    const slot = this.cast.slot(name);
    return getComputedStyle(document.documentElement).getPropertyValue(`--a${slot}`).trim();
  }

  placeName(id) {
    return id == null ? "on the way" : this.data.places[id] || id;
  }

  fit(text, width) {
    const { ctx } = this;
    if (ctx.measureText(text).width <= width) return text;
    while (text.length > 1 && ctx.measureText(`${text}…`).width > width) text = text.slice(0, -1);
    return `${text}…`;
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
      ctx.fillRect(Math.max(after, this.labelW), AXIS_H, width, height);
    }
    this.drawAxis(height);
    const values = residents.flatMap((r) => r.purse.map((p) => p[1]));
    const scale = { min: Math.min(0, ...values), max: Math.max(0, ...values) };
    residents.forEach((r, i) => this.drawLane(r, AXIS_H + i * LANE_H, scale));
    if (after >= this.labelW && after <= width) {
      ctx.fillStyle = C["ink-2"];
      ctx.fillRect(Math.round(after), AXIS_H - 4, 1.5, height);
    }
    if (this.cursor !== null) {
      const cx = this.x(this.cursor);
      if (cx >= this.labelW && cx <= width) {
        ctx.fillStyle = C.accent;
        ctx.fillRect(Math.round(cx) - 0.5, AXIS_H - 8, 2, height);
        ctx.beginPath();
        ctx.moveTo(cx - 5, AXIS_H - 8);
        ctx.lineTo(cx + 5, AXIS_H - 8);
        ctx.lineTo(cx, AXIS_H - 2);
        ctx.fill();
      }
    }
    ctx.fillStyle = C["line-2"];
    ctx.fillRect(this.labelW - 1, AXIS_H - 4, 1, height);
  }

  // Hover and selection ------------------------------------------------------------------------

  hit(px, py) {
    const residents = this.data?.residents ?? [];
    const i = Math.floor((py - AXIS_H) / LANE_H);
    if (py < AXIS_H || i >= residents.length) return null;
    const r = residents[i];
    const y = py - AXIS_H - i * LANE_H;
    const t = this.tAt(px);
    if (px < this.labelW) return { r, t: null };
    if (y < BAR_Y - 1) {
      let best = null;
      for (const [mx, m] of this.drawn[r.name] || []) if (Math.abs(mx - px) <= 6 && (!best || Math.abs(mx - px) < Math.abs(best[0] - px))) best = [mx, m];
      return best ? { r, t, marker: best[1] } : { r, t };
    }
    if (t > this.data.now) return { r, t };
    if (y < BAR_Y + BAR_H + 2) {
      const c = this.at(r.conversations, t);
      if (c && y >= BAR_Y + 4 && y <= BAR_Y + BAR_H - 4) return { r, t, conversation: c };
      return { r, t, segment: this.at(r.segments, t) };
    }
    return { r, t, purse: [t, purseAt(r, t)] };
  }

  at(spans, t) {
    const i = lowerBound(spans, t, (span) => span.end);
    const span = spans[i === spans.length ? i - 1 : i];
    return span && span.start <= t && t <= span.end ? span : null;
  }

  moment(t) {
    return `Day ${livedDay(this.data.days, t).day}, ${dateOf(this.data.start_date, t)} ${hhmm(secondOfDay(t))}`;
  }

  between(a, b) {
    return Math.floor(a / DAY) === Math.floor(b / DAY) ? `${this.moment(a)}–${hhmm(secondOfDay(b))}` : `${this.moment(a)} – ${this.moment(b)}`;
  }

  showTip(found, px, py) {
    let content = null;
    if (found?.marker) {
      const [label, text] = describeMarker(found.marker, found.r.name, found.r.name);
      content = [h("b", {}, found.r.name), ` ${label}`, text ? h("div", {}, text.length > 400 ? `${text.slice(0, 400)}…` : text) : null, h("div", { class: "muted" }, `${this.moment(found.marker.t)} · ${this.placeName(found.marker.place)}`)];
    } else if (found?.conversation) {
      const c = found.conversation;
      content = [h("b", {}, "Conversation"), ` with ${c.with.join(", ")}`, h("div", {}, `over ${EVENTS[c.over].toLowerCase()} at ${this.placeName(c.place)}`), h("div", {}, `${this.between(c.start, c.end)} (${duration(c.end - c.start)})`)];
    } else if (found?.segment) {
      const seg = found.segment;
      const what = seg.kind === "work" ? `Work · ${seg.task == null ? "no task held" : `task ${seg.task}`}` : EVENTS[seg.kind];
      const where = seg.kind === "movement" ? `to ${this.placeName(seg.place)}` : this.placeName(seg.place);
      content = [h("b", {}, what), h("div", {}, where), h("div", {}, `${this.between(seg.start, seg.end)} (${duration(seg.end - seg.start)})`)];
    } else if (found?.purse) {
      content = [h("b", {}, "Purse"), ` ${fmt.money(found.purse[1])}`, h("div", {}, this.moment(found.purse[0]))];
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
      this.drag = { x: e.offsetX, y: e.offsetY, t0: this.t0, t1: this.t1, moved: false };
      canvas.setPointerCapture(e.pointerId);
    });
    canvas.addEventListener("pointermove", (e) => {
      const d = this.drag;
      if (d && this.data) {
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
      if (this.data) this.showTip(this.hit(e.offsetX, e.offsetY), e.offsetX, e.offsetY);
    });
    canvas.addEventListener("pointerup", (e) => {
      const d = this.drag;
      this.drag = null;
      canvas.classList.remove("dragging");
      if (d && !d.moved && this.data) {
        const found = this.hit(e.offsetX, e.offsetY);
        if (!found) return;
        this.handlers.onSelect?.(found.r.name);
        if (found.t !== null && found.t <= this.data.now) this.handlers.onMoment?.(Math.max(this.data.start, Math.round(found.marker?.t ?? found.t)));
      }
    });
    canvas.addEventListener("pointerleave", () => {
      if (!this.drag) this.tip.hidden = true;
    });
  }

  destroy() {
    this.observer.disconnect();
    this.scheme.removeEventListener("change", this.onScheme);
  }
}
