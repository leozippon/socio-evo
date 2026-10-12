// The social fabric as a graph that changes over time: who spent time with whom, who addressed
// whom by name, who marked whom and how, and in the town of jobs for two, who asked whom to take
// a job together, who worked with whom, and who handed whom money. Counts come from the
// published measures and traits, whole days only, through the last day that has ended at the
// moment shown.

import { emptyState, fill, fmt, h, onWidth, s } from "../dom.js";

/** Each measure: its label, what the lines say, where its counts live and whether they point. */
const MEASURES = {
  together: { label: "Together", note: "Line width: hours both spent in the same work session or conversation.", from: "graph", field: "minutes", pointed: false },
  talk: { label: "Talk", note: "Arrows: things said to someone by name; width counts them.", from: "graph", field: "addressed", pointed: true },
  ratings: { label: "Marks", note: "Arrows: private marks in the clerk's ledger; width counts them, darker means a higher mean mark.", from: "graph", field: "ratings", pointed: true },
  asked: { label: "Asked", note: "Arrows: askings to take a job together; width counts them, solid ones were taken up. The halo grows with the askings a resident received.", from: "pairs", field: "asked", pointed: true },
  jobs: { label: "Jobs", note: "Line width: jobs for two the two took together, however they came to.", from: "pairs", field: "joint_taken", pointed: false },
  money: { label: "Money", note: "Arrows: money handed over; width counts the amount.", from: "pairs", field: "money", pointed: true },
};
const WINDOWS = { day: "That day", week: "Last 7 days", run: "Whole run" };
const FIELDS = { graph: ["minutes", "addressed", "ratings", "ratings_sum"], pairs: ["asked", "taken_up", "let_lapse", "joint_taken", "money", "gifts", "private_remarks"] };

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

  /**
   * `graph` is measures.graph; `pairs` traits.pairs, or null for a run without them; `through`
   * the last whole day to count; `selected` an agent or null.
   */
  update(graph, pairs, through, selected) {
    const key = `${graph.length}|${pairs?.length}|${through}|${selected}`;
    if (this.args && key === this.args.key) return;
    this.args = { graph, pairs, through, selected, key };
    this.render();
  }

  render() {
    if (!this.args) return;
    const { graph, pairs, through, selected } = this.args;
    const measures = Object.fromEntries(Object.entries(MEASURES).filter(([, m]) => m.from === "graph" || pairs));
    if (!measures[this.measure]) this.measure = "together";
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
    fill(this.controls, seg(measures, this.measure, (k) => (this.measure = k)), seg(WINDOWS, this.window, (k) => (this.window = k)));
    if (through < 1) {
      fill(this.svgWrap, emptyState("No day has ended yet.", "Ties are counted over whole days; the first appear when day 1 ends."));
      fill(this.caption);
      return;
    }
    const from = this.window === "day" ? through : this.window === "week" ? Math.max(1, through - 6) : 1;
    const measure = MEASURES[this.measure];
    const totals = new Map();
    for (const [rows, fields] of [
      [graph, FIELDS.graph],
      [pairs ?? [], FIELDS.pairs],
    ])
      for (const row of rows) {
        if (row.day < from || row.day > through) continue;
        const key = `${row.source}>${row.target}`;
        const t = totals.get(key) ?? { source: row.source, target: row.target };
        for (const field of fields) t[field] = (t[field] ?? 0) + (row[field] ?? 0);
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
      const lines = [...totals.values()].filter((t) => t.source < t.target && value(t) > 0);
      const most = Math.max(1, ...lines.map(value));
      const say = (t) => (measure.field === "minutes" ? `${fmt.num(t.minutes / 60, 1)} h` : fmt.plural(value(t), "job"));
      for (const t of lines) {
        const a = pos.get(t.source);
        const b = pos.get(t.target);
        edges.push(s("line", { class: `tie${lit(t) ? "" : " dim"}`, x1: a.x, y1: a.y, x2: b.x, y2: b.y, "stroke-width": (1 + (6 * value(t)) / most).toFixed(1) }, s("title", {}, `${t.source} and ${t.target}: ${say(t)}`)));
      }
      strongest = lines
        .filter(lit)
        .sort((x, y) => value(y) - value(x))
        .slice(0, 4)
        .map((t) => [`${t.source} and ${t.target}`, say(t)]);
    } else {
      const arrows = [...totals.values()].filter((t) => value(t) > 0);
      const most = Math.max(1, ...arrows.map(value));
      const say = (t) =>
        ({
          addressed: () => `${fmt.plural(t.addressed, "time")}${t.private_remarks ? `, ${fmt.int(t.private_remarks)} privately` : ""}`,
          ratings: () => `${fmt.plural(t.ratings, "mark")}, mean ${fmt.num(t.ratings_sum / t.ratings, 1)}`,
          asked: () => `asked ${fmt.plural(t.asked, "time")}, ${fmt.int(t.taken_up)} taken up`,
          money: () => `${fmt.money(t.money)} in ${fmt.plural(t.gifts, "gift")}`,
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
        const passed = measure.field === "asked" && !t.taken_up;
        edges.push(
          s(
            "g",
            { class: `arrow${lit(t) ? "" : " dim"}${passed ? " passed" : ""}` },
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
    // Who is chosen: a halo by askings received.
    const received = new Map(names.map((name) => [name, 0]));
    if (measure.field === "asked") for (const t of totals.values()) received.set(t.target, (received.get(t.target) ?? 0) + (t.asked ?? 0));
    const mostReceived = Math.max(1, ...received.values());
    const nodes = names.map((name) => {
      const p = pos.get(name);
      const lx = Math.cos(p.a) * 26;
      const ly = Math.sin(p.a) * 22;
      const halo = measure.field === "asked" && received.get(name) ? s("circle", { class: "node-halo", r: (14 + (12 * received.get(name)) / mostReceived).toFixed(1) }) : null;
      return s(
        "g",
        { class: `node${selected && selected !== name ? " dim" : ""}${selected === name ? " selected" : ""}`, transform: `translate(${p.x},${p.y})`, tabindex: "0", role: "button", "aria-label": `Select ${name}` },
        halo,
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
    const passedOver = names.filter((name) => !received.get(name));
    const chosen = names.filter((name) => received.get(name)).sort((a, b) => received.get(b) - received.get(a));
    fill(
      this.caption,
      h("p", { class: "note" }, `${measure.note} Days ${from === through ? from : `${from}–${through}`}, counted over whole days.`),
      measure.field === "asked"
        ? h(
            "p",
            { class: "chosen" },
            chosen.length ? ["Asked: ", chosen.map((name, i) => [i ? ", " : "", this.cast.mention(name), ` ${received.get(name)}`])] : "Nobody was asked.",
            passedOver.length && chosen.length ? [h("br"), "Never asked: ", this.cast.mention(passedOver.join(", "))] : null,
          )
        : null,
      strongest.length ? h("ul", { class: "ties-list" }, strongest.map(([who, what]) => h("li", {}, this.cast.mention(who), h("span", { class: "muted" }, ` · ${what}`)))) : h("p", { class: "muted" }, "Nothing to count in this window."),
    );
  }

  destroy() {
    this.stop();
  }
}
