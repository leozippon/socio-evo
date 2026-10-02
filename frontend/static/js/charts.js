// Chart primitives over simulated days, drawn as SVG at the width of their container.
//
// One x axis for every chart: days of the run, with interventions marked on it. Lines are 2px,
// columns at most 24px wide with a 2px surface gap between stacked segments, gridlines are
// hairlines, and text wears text colours, never series colours. Every chart has a crosshair
// tooltip that lists every series at the day under the pointer and a table twin that shows the
// same numbers without hovering. With many agent lines, one can be emphasised and the rest
// recede; small multiples give each agent its own panel.

import { fmt, h, onWidth, s } from "./dom.js";
import { icon } from "./icons.js";

const PAD = { top: 16, bottom: 24, left: 42, right: 14 };

/** About `count` round ticks covering [lo, hi]; whole numbers only if `integer`. */
export function ticks(lo, hi, count = 4, integer = false) {
  if (hi === lo) return [lo];
  const raw = (hi - lo) / count;
  const power = 10 ** Math.floor(Math.log10(raw));
  let step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((m) => m >= raw);
  if (integer) step = Math.max(1, Math.round(step));
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) out.push(+v.toFixed(10));
  return out;
}

/** A nice domain that holds every value, with zero in it when asked. */
function domain(values, { zero = false, min = null, max = null, integer = false } = {}) {
  const finite = values.filter((v) => v !== null && Number.isFinite(v));
  let lo = min ?? Math.min(...finite, zero ? 0 : Infinity);
  let hi = max ?? Math.max(...finite, zero ? 0 : -Infinity);
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) [lo, hi] = [0, 1];
  if (lo === hi) [lo, hi] = [lo - 1, hi + 1];
  const t = ticks(lo, hi, 4, integer);
  const step = t.length > 1 ? t[1] - t[0] : 1;
  return [min ?? Math.min(lo, Math.floor(lo / step) * step), max ?? Math.max(hi, Math.ceil(hi / step) * step)];
}

/** The tooltip of a chart: values lead, labels follow, each row keyed by a short line. */
function tooltip(host) {
  const tip = h("div", { class: "tip", role: "status", hidden: true });
  host.append(tip);
  return {
    show(x, y, title, rows) {
      tip.replaceChildren(
        h("div", { class: "tip-title" }, title),
        ...rows.map((row) =>
          h("div", { class: `tip-row${row.strong ? " strong" : ""}` }, h("span", { class: "tip-key", style: { background: row.color ?? "transparent" } }), h("b", {}, row.value), h("span", {}, row.label)),
        ),
      );
      tip.hidden = false;
      const box = host.getBoundingClientRect();
      const width = tip.offsetWidth;
      tip.style.left = `${Math.max(4, Math.min(x + 14 > box.width - width ? x - width - 14 : x + 14, box.width - width - 4))}px`;
      tip.style.top = `${Math.max(0, y - 10)}px`;
    },
    hide() {
      tip.hidden = true;
    },
  };
}

/**
 * A chart over days. `spec`:
 *   days: [first, last] day of the axis
 *   y: {format, zero, min, max, label}
 *   lines: [{key, label, color, points: [[day, value|null]], glyph?: (r) => SVG, faint?}]
 *   stacks: [{key, label, color, values: Map(day -> value)}]  stacked columns, bottom first
 *   markers: [{day, label, announced}]  interventions
 *   cursor: day (fractional) of the moment shown, or null
 *   endLabels: label line ends with their glyph and name
 *   height: plot height in pixels
 *   highlight: key of the emphasised line, or null; onHighlight(key) when the pointer picks one
 */
export class DayChart {
  constructor(spec) {
    this.spec = { height: 170, lines: [], stacks: [], markers: [], ...spec };
    this.el = h("div", { class: "chart" });
    this.svg = s("svg", { class: "chart-svg", role: "img" });
    this.el.append(this.svg);
    this.tip = tooltip(this.el);
    this.width = 0;
    this.near = null; // the line the pointer picked, if any
    this.stop = onWidth(this.el, (width) => {
      this.width = width;
      this.render();
    });
    this.svg.addEventListener("pointermove", (event) => this.hover(event));
    this.svg.addEventListener("pointerleave", () => this.leave());
  }

  update(patch) {
    Object.assign(this.spec, patch);
    this.render();
  }

  scales() {
    const { days, height, lines, stacks, y = {} } = this.spec;
    const right = this.labelled() ? 78 : PAD.right;
    const values = [...lines.flatMap((line) => line.points.map((p) => p[1]))];
    if (stacks.length) {
      const totals = new Map();
      for (const stack of stacks) for (const [day, v] of stack.values) totals.set(day, (totals.get(day) ?? 0) + v);
      values.push(...totals.values(), 0);
    }
    const [lo, hi] = domain(values, y);
    const x0 = PAD.left;
    const x1 = Math.max(x0 + 40, this.width - right);
    const span = Math.max(1, days[1] - days[0] + 1);
    const x = (day) => x0 + ((day - days[0] + 0.5) / span) * (x1 - x0);
    const yy = (v) => PAD.top + height - ((v - lo) / (hi - lo)) * height;
    return { x, y: yy, lo, hi, x0, x1, band: (x1 - x0) / span };
  }

  /** Whether line ends carry direct labels: when asked for and there is room. */
  labelled() {
    return Boolean(this.spec.endLabels) && this.width > 300;
  }

  render() {
    if (!this.width) return;
    const { days, height, lines, stacks, markers, cursor, y = {}, highlight } = this.spec;
    const sc = (this.sc = this.scales());
    const total = PAD.top + height + PAD.bottom;
    this.svg.setAttribute("viewBox", `0 0 ${this.width} ${total}`);
    this.svg.setAttribute("height", total);
    this.svg.setAttribute("width", this.width);
    const parts = [];
    // Grid and y axis.
    for (const v of ticks(sc.lo, sc.hi, 4, y.integer)) {
      parts.push(s("line", { class: v === 0 ? "axis" : "grid", x1: sc.x0, x2: sc.x1, y1: sc.y(v), y2: sc.y(v) }));
      parts.push(s("text", { class: "tick", x: sc.x0 - 6, y: sc.y(v) + 3.5, "text-anchor": "end" }, (y.format ?? fmt.compact)(v)));
    }
    // X axis: every so many days from the first, spaced to fit.
    const every = [1, 2, 3, 5, 7, 14, 28, 56].find((k) => sc.band * k >= 24) ?? 100;
    for (let d = days[0]; d <= days[1]; d += every) parts.push(s("text", { class: "tick", x: sc.x(d), y: PAD.top + height + 16, "text-anchor": "middle" }, String(d)));
    parts.push(s("line", { class: "axis", x1: sc.x0, x2: sc.x1, y1: PAD.top + height, y2: PAD.top + height }));
    // Interventions, before the data so the data stays on top.
    for (const marker of markers) {
      const mx = sc.x(marker.day) - sc.band / 2;
      parts.push(
        s(
          "g",
          { class: `marker${marker.announced ? " announced" : ""}` },
          s("title", {}, marker.label),
          s("line", { x1: mx, x2: mx, y1: PAD.top - 6, y2: PAD.top + height }),
          s("path", { d: `M${mx},${PAD.top - 12}h7l-2,3l2,3h-7z` }),
        ),
      );
    }
    // Stacked columns.
    if (stacks.length) {
      const width = Math.min(24, Math.max(2, sc.band - 4));
      for (let d = days[0]; d <= days[1]; d++) {
        let base = 0;
        const segments = stacks.map((stack) => [stack, stack.values.get(d) ?? 0]).filter(([, v]) => v > 0);
        segments.forEach(([stack, v], i) => {
          const top = sc.y(base + v);
          const bottom = sc.y(base) - (i > 0 ? 2 : 0);
          base += v;
          if (bottom - top < 0.5) return;
          const last = i === segments.length - 1;
          parts.push(s("path", { class: "column", d: column(sc.x(d) - width / 2, top, width, bottom - top, last ? Math.min(4, (bottom - top) / 2, width / 2) : 0), style: { fill: stack.color } }));
        });
      }
    }
    // Lines: context first, the emphasised one last.
    const ordered = [...lines].sort((a, b) => (a.key === highlight) - (b.key === highlight));
    for (const line of ordered) {
      const dim = (highlight && line.key !== highlight) || line.faint;
      const d = path(line.points.map(([day, v]) => (v === null ? null : [sc.x(day), sc.y(v)])));
      if (!d) continue;
      parts.push(s("path", { class: `line${dim ? " dim" : ""}${line.key === highlight ? " lit" : ""}`, d, style: { stroke: dim ? null : line.color }, "data-key": line.key }));
      const known = line.points.filter((p) => p[1] !== null);
      if ((known.length === 1 || this.spec.dots) && !dim) for (const [day, v] of known) parts.push(s("circle", { class: "dot", cx: sc.x(day), cy: sc.y(v), r: 4, style: { fill: line.color } }));
    }
    if (this.labelled()) parts.push(...this.endLabels(sc));
    if (cursor !== null && cursor !== undefined && cursor >= days[0] - 1 && cursor <= days[1] + 1) {
      const cx = sc.x(cursor) - sc.band / 2;
      parts.push(s("line", { class: "now", x1: cx, x2: cx, y1: PAD.top - 4, y2: PAD.top + height }));
    }
    this.crosshair = s("line", { class: "crosshair", y1: PAD.top, y2: PAD.top + height, visibility: "hidden" });
    parts.push(this.crosshair);
    this.svg.replaceChildren(...parts);
    this.svg.setAttribute("aria-label", this.spec.label ?? "");
  }

  /** Direct labels at line ends, spread so they never overlap, with leaders where moved. */
  endLabels(sc) {
    const ends = this.spec.lines
      .filter((line) => !line.faint)
      .map((line) => {
        const last = line.points.findLast((p) => p[1] !== null);
        return last && { line, x: sc.x(last[0]), y: sc.y(last[1]) };
      })
      .filter(Boolean)
      .sort((a, b) => a.y - b.y);
    const gap = 14;
    const placed = ends.map((end) => ({ ...end, ly: end.y }));
    for (let i = 1; i < placed.length; i++) placed[i].ly = Math.max(placed[i].ly, placed[i - 1].ly + gap);
    const bottom = PAD.top + this.spec.height + 6;
    const over = placed.length ? placed.at(-1).ly - bottom : 0;
    if (over > 0) for (const p of placed) p.ly -= over;
    for (let i = placed.length - 2; i >= 0; i--) placed[i].ly = Math.min(placed[i].ly, placed[i + 1].ly - gap);
    const lx = sc.x1 + 14;
    return placed.map(({ line, x, y, ly }) => {
      const dim = this.spec.highlight && line.key !== this.spec.highlight;
      return s(
        "g",
        { class: `end-label${dim ? " dim" : ""}`, "data-key": line.key },
        Math.abs(ly - y) > 2 || lx - x > 16 ? s("path", { class: "leader", d: `M${x + 3},${y}L${lx - 9},${ly}` }) : null,
        line.glyph ? s("g", { transform: `translate(${lx},${ly})` }, line.glyph(5.5)) : null,
        s("text", { class: "end-text", x: lx + 9, y: ly + 3.5 }, line.label),
      );
    });
  }

  hover(event) {
    const { sc } = this;
    if (!sc) return;
    const box = this.svg.getBoundingClientRect();
    const px = event.clientX - box.left;
    const { days } = this.spec;
    const day = Math.max(days[0], Math.min(days[1], Math.round(days[0] + (px - sc.x0) / sc.band - 0.5)));
    // Picking a line: the one nearest the pointer, if close. Emphasis re-renders the chart, so
    // it comes before the crosshair is placed.
    if (this.spec.onHighlight && this.spec.lines.length > 1) {
      const py = event.clientY - box.top;
      let near = null;
      for (const line of this.spec.lines) {
        const point = line.points.find((p) => p[0] === day);
        if (!point || point[1] === null) continue;
        const dist = Math.abs(sc.y(point[1]) - py);
        if (dist < 10 && (!near || dist < near[1])) near = [line.key, dist];
      }
      const key = near ? near[0] : null;
      if (key !== this.near) {
        this.near = key;
        this.spec.onHighlight(key, false);
      }
    }
    const rows = this.rowsAt(day);
    if (!rows.length) return this.leave();
    this.crosshair.setAttribute("x1", sc.x(day));
    this.crosshair.setAttribute("x2", sc.x(day));
    this.crosshair.setAttribute("visibility", "visible");
    const markers = this.spec.markers.filter((m) => m.day === day).map((m) => ({ value: "", label: m.label, color: null }));
    this.tip.show(sc.x(day), event.clientY - box.top, `Day ${day}`, [...rows, ...markers]);
  }

  rowsAt(day) {
    const format = this.spec.y?.format ?? fmt.num;
    const rows = [];
    for (const line of this.spec.lines) {
      const point = line.points.find((p) => p[0] === day);
      if (point && point[1] !== null) rows.push({ value: format(point[1]), label: line.label, color: line.color, strong: line.key === this.spec.highlight, v: point[1] });
    }
    rows.sort((a, b) => b.v - a.v);
    for (const stack of [...this.spec.stacks].reverse()) {
      const v = stack.values.get(day);
      if (v !== undefined) rows.push({ value: format(v), label: stack.label, color: stack.color });
    }
    return rows;
  }

  leave() {
    this.tip.hide();
    this.crosshair?.setAttribute("visibility", "hidden");
    if (this.spec.onHighlight && this.near) {
      this.near = null;
      this.spec.onHighlight(null, false);
    }
  }

  table() {
    return dayTable(this.spec);
  }

  destroy() {
    this.stop();
  }
}

/** The numbers behind a day chart, one row per day. */
export function dayTable(spec) {
  const { days, lines = [], stacks = [] } = spec;
  const format = spec.y?.format ?? fmt.num;
  const columns = [...lines.filter((l) => !l.faint).map((l) => [l.label, (d) => l.points.find((p) => p[0] === d)?.[1]]), ...stacks.map((st) => [st.label, (d) => st.values.get(d)])];
  const rows = [];
  for (let d = days[0]; d <= days[1]; d++) rows.push(h("tr", {}, h("th", { scope: "row" }, String(d)), ...columns.map(([, get]) => h("td", {}, get(d) === undefined || get(d) === null ? "–" : format(get(d))))));
  return h("div", { class: "table-wrap" }, h("table", { class: "data" }, h("thead", {}, h("tr", {}, h("th", {}, "Day"), ...columns.map(([label]) => h("th", {}, label)))), h("tbody", {}, rows)));
}

/** A polyline path through points, broken where a point is null. */
function path(points) {
  let d = "";
  let pen = false;
  for (const p of points) {
    if (!p) {
      pen = false;
      continue;
    }
    d += `${pen ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`;
    pen = true;
  }
  return d;
}

/** A column with rounded top corners of radius `r`, square at its base. */
function column(x, y, w, hgt, r) {
  return `M${x},${y + hgt}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + hgt}Z`;
}

/**
 * A figure: title, a line saying what is plotted and in which unit, the chart, an optional
 * legend, and a button that swaps the chart for its table.
 */
export function figure({ title, note, chart, legend = null, tools = [], wide = false }) {
  const body = h("div", { class: "figure-body" }, chart.el);
  let showing = "chart";
  const toggle = h("button", { class: "ghost small", type: "button", title: "Show the numbers as a table", "aria-pressed": "false" }, icon("table", 15), h("span", {}, "Table"));
  toggle.addEventListener("click", () => {
    showing = showing === "chart" ? "table" : "chart";
    toggle.setAttribute("aria-pressed", String(showing === "table"));
    toggle.lastChild.textContent = showing === "table" ? "Chart" : "Table";
    body.replaceChildren(showing === "table" ? chart.table() : chart.el);
  });
  return h(
    "figure",
    { class: `figure${wide ? " wide" : ""}` },
    h("figcaption", {}, h("div", { class: "figure-head" }, h("h3", {}, title), h("div", { class: "figure-tools" }, ...tools, toggle)), note ? h("p", { class: "note" }, note) : null, legend),
    body,
  );
}

/** A legend of agents that emphasises one on hover and pins it on click. */
export function agentLegend(cast, names, { selected, onPick }) {
  const items = names.map((name) =>
    h(
      "button",
      {
        type: "button",
        class: `legend-item${selected === name ? " on" : ""}`,
        "aria-pressed": String(selected === name),
        onclick: () => onPick(selected === name ? null : name, true),
        onpointerenter: () => onPick(name, false),
        onpointerleave: () => onPick(null, false),
      },
      cast.badge(name, 14),
      name,
    ),
  );
  return h("div", { class: "legend" }, items);
}

/** A legend of plain swatches, for columns. */
export const swatchLegend = (entries) =>
  h("div", { class: "legend static" }, entries.map(([label, color]) => h("span", { class: "legend-item" }, h("span", { class: "swatch", style: { background: color } }), label)));

/**
 * Small multiples: one panel per agent with that agent in its colour over the others in grey,
 * all on the same scale.
 */
export class Multiples {
  constructor(spec) {
    this.el = h("div", { class: "multiples" });
    this.charts = [];
    this.spec = spec;
    this.render();
  }

  render() {
    const { lines } = this.spec;
    const all = lines.flatMap((l) => l.points.map((p) => p[1]));
    const [min, max] = domain(all, this.spec.y);
    for (const chart of this.charts) chart.destroy();
    this.charts = lines.map((focus) => {
      const chart = new DayChart({
        ...this.spec,
        height: 70,
        y: { ...this.spec.y, min, max },
        lines: [...lines.filter((l) => l !== focus).map((l) => ({ ...l, faint: true })), focus],
        endLabels: false,
        onHighlight: null,
      });
      return chart;
    });
    this.el.replaceChildren(...lines.map((line, i) => h("div", { class: "multiple" }, h("div", { class: "multiple-title" }, line.glyph ? s("svg", { class: "badge", width: 14, height: 14, viewBox: "-1.3 -1.3 2.6 2.6" }, line.glyph(1)) : null, line.label), this.charts[i].el)));
  }

  update(patch) {
    Object.assign(this.spec, patch);
    this.render();
  }

  table() {
    return dayTable(this.spec);
  }

  destroy() {
    for (const chart of this.charts) chart.destroy();
  }
}
