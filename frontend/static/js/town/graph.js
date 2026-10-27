// The social fabric as a graph that changes over time: who spent time in conversation with
// whom, who spoke to whom, who rated whom and how, who handed whom money, who passed on a
// skill. Counts come from the published measures' graph, by lived day, through the day shown.

import { emptyState, fill, fmt, h, onWidth, s } from "../dom.js";

/** Each measure: its label, what the lines say, its field and whether its lines point. */
const MEASURES = {
  together: { label: "Together", note: "Line width: minutes spent in conversations the other took part in.", field: "minutes", pointed: false },
  talk: { label: "Talk", note: "Arrows: things said that the other heard; width counts them.", field: "said", pointed: true },
  ratings: { label: "Ratings", note: "Arrows: ratings given at night; width counts them, darker means a higher mean score.", field: "ratings", pointed: true },
  money: { label: "Money", note: "Arrows: money handed over; width counts the amount.", field: "money", pointed: true },
  skills: { label: "Files", note: "Arrows: copies of files passed on; width counts them.", field: "skills", pointed: true },
};
const WINDOWS = { day: "That day", week: "Last 7 days", run: "Whole run" };
const FIELDS = ["minutes", "said", "said_private", "gifts", "money", "skills", "ratings", "ratings_sum"];

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

  /** `graph` is measures.graph; `through` the lived day to count through; `selected` a resident or null. */
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
      fill(this.svgWrap, emptyState("No day has begun yet.", "Who spoke, rated, paid and taught whom is drawn here once the first day is under way."));
      fill(this.caption);
      return;
    }
    const from = this.window === "day" ? through : this.window === "week" ? Math.max(1, through - 6) : 1;
    const measure = MEASURES[this.measure];
    const totals = new Map();
    for (const row of graph) {
      if (row.day < from || row.day > through) continue;
      const key = `${row.source}>${row.target}`;
      const t = totals.get(key) ?? { source: row.source, target: row.target };
      for (const field of FIELDS) t[field] = (t[field] ?? 0) + (row[field] ?? 0);
      totals.set(key, t);
    }
    const names = this.cast.names;
    const size = Math.max(220, Math.min(this.width || 320, 420));
    const radius = size / 2 - 46;
    const pos = new Map(
      names.map((name, i) => {
        const a = (i / names.length) * 2 * Math.PI - Math.PI / 2;
        return [name, { x: size / 2 + radius * Math.cos(a), y: size / 2 + radius * Math.sin(a), a }];
      }),
    );
    const lit = (t) => !selected || t.source === selected || t.target === selected;
    const value = (t) => t[measure.field] ?? 0;
    const edges = [];
    let strongest = [];
    if (!measure.pointed) {
      // Minutes are counted from each side; the line takes the larger of the two.
      const pairs = new Map();
      for (const t of totals.values()) {
        const key = [t.source, t.target].sort().join(">");
        const found = pairs.get(key) ?? { source: key.split(">")[0], target: key.split(">")[1], minutes: 0 };
        found.minutes = Math.max(found.minutes, t.minutes ?? 0);
        pairs.set(key, found);
      }
      const lines = [...pairs.values()].filter((t) => t.minutes > 0);
      const most = Math.max(1, ...lines.map((t) => t.minutes));
      const say = (t) => (t.minutes >= 60 ? `${fmt.num(t.minutes / 60, 1)} h` : `${fmt.int(Math.round(t.minutes))} min`);
      for (const t of lines) {
        const a = pos.get(t.source);
        const b = pos.get(t.target);
        edges.push(s("line", { class: `tie${lit(t) ? "" : " dim"}`, x1: a.x, y1: a.y, x2: b.x, y2: b.y, "stroke-width": (1 + (6 * t.minutes) / most).toFixed(1) }, s("title", {}, `${t.source} and ${t.target}: ${say(t)}`)));
      }
      strongest = lines
        .filter(lit)
        .sort((x, y) => y.minutes - x.minutes)
        .slice(0, 4)
        .map((t) => [`${t.source} and ${t.target}`, say(t)]);
    } else {
      const arrows = [...totals.values()].filter((t) => value(t) > 0);
      const most = Math.max(1, ...arrows.map(value));
      const say = (t) =>
        ({
          said: () => `${fmt.plural(t.said, "thing")} said${t.said_private ? `, ${fmt.int(t.said_private)} privately` : ""}`,
          ratings: () => `${fmt.plural(t.ratings, "rating")}, mean ${fmt.num(t.ratings_sum / t.ratings, 1)}`,
          money: () => `${fmt.money(t.money)} handed over, ${fmt.plural(t.gifts, "time")}`,
          skills: () => fmt.plural(t.skills, "file"),
        })[measure.field]();
      for (const t of arrows) {
        const a = pos.get(t.source);
        const b = pos.get(t.target);
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
        const w = (1 + (4 * value(t)) / most).toFixed(1);
        const angle = Math.atan2(end.y - c.y, end.x - c.x);
        const wing = (turn) => `${(end.x - 8 * Math.cos(angle + turn)).toFixed(1)},${(end.y - 8 * Math.sin(angle + turn)).toFixed(1)}`;
        const head = `M${end.x.toFixed(1)},${end.y.toFixed(1)}L${wing(-0.45)}L${wing(0.45)}Z`;
        const color = measure.field === "ratings" ? `var(--o${level})` : null;
        edges.push(
          s(
            "g",
            { class: `arrow${lit(t) ? "" : " dim"}` },
            s("title", {}, `${t.source} → ${t.target}: ${say(t)}`),
            s("path", { class: "arrow-line", d: `M${start.x},${start.y}Q${c.x},${c.y} ${end.x},${end.y}`, "stroke-width": w, style: color ? { stroke: color } : null }),
            s("path", { class: "arrow-head", d: head, style: color ? { fill: color } : null }),
          ),
        );
      }
      strongest = arrows
        .filter(lit)
        .sort((x, y) => value(y) - value(x))
        .slice(0, 4)
        .map((t) => [`${t.source} → ${t.target}`, say(t)]);
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
    fill(this.svgWrap, s("svg", { class: "ties-svg", viewBox: `0 0 ${size} ${size}`, width: size, height: size, role: "img", "aria-label": `${measure.label}, days ${from} to ${through}` }, s("g", {}, edges), s("g", {}, nodes)));
    fill(
      this.caption,
      h("p", { class: "note" }, `${measure.note} Days ${from === through ? from : `${from}–${through}`}, the day shown as far as it has gone.`),
      strongest.length ? h("ul", { class: "ties-list" }, strongest.map(([who, what]) => h("li", {}, this.cast.mention(who), h("span", { class: "muted" }, ` · ${what}`)))) : h("p", { class: "muted" }, `Nothing of this kind between any two residents in these days${selected ? ` with ${selected}` : ""}.`),
    );
  }

  destroy() {
    this.stop();
  }
}
