// The social fabric as a graph that changes over time: who spent time with whom, who addressed
// whom by name, who rated whom and how. Counts come from the published measures, whole days
// only, through the last day that has ended at the moment shown.

import { emptyState, fill, fmt, h, onWidth, s } from "../dom.js";

const MEASURES = {
  together: { label: "Time together", note: "Line width: hours both spent in the same work session or conversation." },
  talk: { label: "Addressed", note: "Arrows: things said to someone by name; width counts them." },
  ratings: { label: "Ratings", note: "Arrows: private evening ratings; width counts them, darker means a higher mean score." },
};
const WINDOWS = { day: "That day", week: "Last 7 days", run: "Whole run" };

export class TiesPanel {
  constructor({ cast, onSelect }) {
    this.cast = cast;
    this.onSelect = onSelect;
    this.measure = "together";
    this.window = "week";
    this.el = h("div", { class: "panel ties" });
    this.controls = h("div", { class: "ties-controls" });
    this.svgWrap = h("div", { class: "ties-graph" });
    this.caption = h("div", { class: "ties-caption" });
    this.el.append(this.controls, this.svgWrap, this.caption);
    this.width = 0;
    this.stop = onWidth(this.svgWrap, (width) => {
      this.width = width;
      this.render();
    });
    this.args = null;
  }

  /** `graph` is measures.graph; `through` the last whole day to count; `selected` an agent or null. */
  update(graph, through, selected) {
    const key = `${graph.length}|${through}|${selected}`;
    if (this.args && key === this.args.key) return;
    this.args = { graph, through, selected, key };
    this.render();
  }

  render() {
    if (!this.args) return;
    const { graph, through, selected } = this.args;
    const seg = (options, current, set) =>
      h(
        "div",
        { class: "seg" },
        Object.entries(options).map(([key, label]) =>
          h(
            "button",
            {
              type: "button",
              "aria-pressed": String(current === key),
              onclick: () => {
                set(key);
                this.args.key = null;
                this.render();
              },
            },
            typeof label === "string" ? label : label.label,
          ),
        ),
      );
    fill(this.controls, seg(MEASURES, this.measure, (k) => (this.measure = k)), seg(WINDOWS, this.window, (k) => (this.window = k)));
    if (through < 1) {
      fill(this.svgWrap, emptyState("No day has ended yet.", "Ties are counted over whole days; the first appear when day 1 ends."));
      fill(this.caption);
      return;
    }
    const from = this.window === "day" ? through : this.window === "week" ? Math.max(1, through - 6) : 1;
    const totals = new Map();
    for (const edge of graph) {
      if (edge.day < from || edge.day > through) continue;
      const key = `${edge.source}>${edge.target}`;
      const t = totals.get(key) ?? { source: edge.source, target: edge.target, minutes: 0, addressed: 0, ratings: 0, ratings_sum: 0 };
      t.minutes += edge.minutes;
      t.addressed += edge.addressed;
      t.ratings += edge.ratings;
      t.ratings_sum += edge.ratings_sum;
      totals.set(key, t);
    }
    const names = this.cast.names;
    const size = Math.max(220, Math.min(this.width || 320, 420));
    const radius = size / 2 - 46;
    const pos = new Map(names.map((name, i) => {
      const a = (i / names.length) * 2 * Math.PI - Math.PI / 2;
      return [name, { x: size / 2 + radius * Math.cos(a), y: size / 2 + radius * Math.sin(a), a }];
    }));
    const edges = [];
    let strongest = [];
    if (this.measure === "together") {
      const pairs = [...totals.values()].filter((t) => t.source < t.target && t.minutes > 0);
      const most = Math.max(1, ...pairs.map((t) => t.minutes));
      for (const t of pairs) {
        const a = pos.get(t.source);
        const b = pos.get(t.target);
        const lit = !selected || t.source === selected || t.target === selected;
        edges.push(s("line", { class: `tie${lit ? "" : " dim"}`, x1: a.x, y1: a.y, x2: b.x, y2: b.y, "stroke-width": (1 + (6 * t.minutes) / most).toFixed(1) }, s("title", {}, `${t.source} and ${t.target}: ${fmt.num(t.minutes / 60, 1)} hours together`)));
      }
      strongest = pairs.sort((x, y) => y.minutes - x.minutes).filter((t) => !selected || t.source === selected || t.target === selected).slice(0, 4).map((t) => [`${t.source} and ${t.target}`, `${fmt.num(t.minutes / 60, 1)} h`]);
    } else {
      const field = this.measure === "talk" ? "addressed" : "ratings";
      const arrows = [...totals.values()].filter((t) => t[field] > 0);
      const most = Math.max(1, ...arrows.map((t) => t[field]));
      for (const t of arrows) {
        const a = pos.get(t.source);
        const b = pos.get(t.target);
        const lit = !selected || t.source === selected || t.target === selected;
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const len = Math.hypot(dx, dy);
        const ux = dx / len;
        const uy = dy / len;
        const start = { x: a.x + ux * 16, y: a.y + uy * 16 };
        const end = { x: b.x - ux * 19, y: b.y - uy * 19 };
        const bend = 0.14;
        const c = { x: (start.x + end.x) / 2 + -uy * len * bend, y: (start.y + end.y) / 2 + ux * len * bend };
        const mean = t.ratings ? t.ratings_sum / t.ratings : null;
        const level = mean === null ? 3 : Math.max(1, Math.min(5, Math.round(mean)));
        const title = field === "addressed" ? `${t.source} addressed ${t.target} ${fmt.plural(t.addressed, "time")}` : `${t.source} rated ${t.target} ${fmt.plural(t.ratings, "time")}, mean ${fmt.num(mean, 2)}`;
        const w = (1 + (4 * t[field]) / most).toFixed(1);
        const angle = Math.atan2(end.y - c.y, end.x - c.x);
        const wing = (turn) => `${(end.x - 8 * Math.cos(angle + turn)).toFixed(1)},${(end.y - 8 * Math.sin(angle + turn)).toFixed(1)}`;
        const head = `M${end.x.toFixed(1)},${end.y.toFixed(1)}L${wing(-0.45)}L${wing(0.45)}Z`;
        const color = field === "ratings" ? `var(--o${level})` : null;
        edges.push(
          s(
            "g",
            { class: `arrow${lit ? "" : " dim"}` },
            s("title", {}, title),
            s("path", { class: "arrow-line", d: `M${start.x},${start.y}Q${c.x},${c.y} ${end.x},${end.y}`, "stroke-width": w, style: color ? { stroke: color } : null }),
            s("path", { class: "arrow-head", d: head, style: color ? { fill: color } : null }),
          ),
        );
      }
      strongest = arrows
        .filter((t) => !selected || t.source === selected || t.target === selected)
        .sort((x, y) => y[field] - x[field])
        .slice(0, 4)
        .map((t) => [`${t.source} → ${t.target}`, field === "addressed" ? fmt.plural(t.addressed, "time") : `${fmt.plural(t.ratings, "rating")}, mean ${fmt.num(t.ratings_sum / t.ratings, 1)}`]);
    }
    const nodes = names.map((name) => {
      const p = pos.get(name);
      const lx = Math.cos(p.a) * 26;
      const ly = Math.sin(p.a) * 22;
      return s(
        "g",
        { class: `node${selected && selected !== name ? " dim" : ""}${selected === name ? " selected" : ""}`, transform: `translate(${p.x},${p.y})`, tabindex: "0", role: "button", "aria-label": `Select ${name}` },
        s("circle", { class: "node-hit", r: 18 }),
        this.cast.glyph(name, 12),
        s("text", { class: "node-name", x: lx, y: ly + 4, "text-anchor": Math.abs(lx) < 6 ? "middle" : lx > 0 ? "start" : "end" }, name),
      );
    });
    for (const [i, node] of nodes.entries()) {
      node.addEventListener("click", () => this.onSelect(names[i]));
      node.addEventListener("keydown", (event) => event.key === "Enter" && this.onSelect(names[i]));
    }
    fill(this.svgWrap, s("svg", { class: "ties-svg", viewBox: `0 0 ${size} ${size}`, width: size, height: size, role: "img", "aria-label": `${MEASURES[this.measure].label}, days ${from} to ${through}` }, s("g", {}, edges), s("g", {}, nodes)));
    fill(
      this.caption,
      h("p", { class: "note" }, `${MEASURES[this.measure].note} Days ${from === through ? from : `${from}–${through}`}, counted over whole days.`),
      strongest.length ? h("ul", { class: "ties-list" }, strongest.map(([who, what]) => h("li", {}, this.cast.mention(who), h("span", { class: "muted" }, ` · ${what}`)))) : h("p", { class: "muted" }, "Nothing to count in this window."),
    );
  }

  destroy() {
    this.stop();
  }
}
