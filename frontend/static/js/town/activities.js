import { calendarOf, dayOf, dayStart, hhmmss, minuteOf } from "../clock.js";
import { fill, h } from "../dom.js";
import { shortName } from "../world.js";
import { activityIntervals, ACTIVITY_LABELS } from "./activity-model.js";

const clock = (time) => hhmmss(minuteOf(time));
const label = (row) => ACTIVITY_LABELS[row.type] ?? row.type;

/** All residents on one clock: lanes for comparison and an ordered membership ledger. */
export class ActivitiesPanel {
  constructor({ onJump }) {
    this.onJump = onJump;
    this.person = "";
    this.el = h("section", { class: "activities-panel", "aria-label": "Resident activities" });
  }

  update(m) {
    const now = m.state.time;
    const day = dayOf(now);
    const base = dayStart(day);
    const cal = calendarOf(m.world);
    const from = base + cal.start;
    const to = base + cal.end;
    const span = Math.max(1, to - from);
    const percent = (time) => Math.max(0, Math.min(100, (time - from) / span * 100));
    const reader = !m.truth ? m.selected : null;
    // Without a selected resident there is no private viewpoint from which to infer activities.
    const rows = !m.truth && !reader ? [] : activityIntervals(m.activityEvents, now, reader);
    const today = rows.filter((row) => (row.end ?? now) >= base && row.start < base + 1440);
    const current = new Map(rows.filter((row) => row.end == null).map((row) => [row.actor, row]));
    const lanes = m.world.agents.map(({ name }) => {
      const active = current.get(name);
      const known = m.truth || name === reader;
      const status = active ? `${label(active)}${active.tool ? ` · ${active.tool}` : ""}` : known ? "Between activities" : "Not observed";
      return h("div", { class: "activity-lane" },
        h("button", { class: "linkish activity-person", type: "button", onclick: () => { this.person = name; m.select(name); this.update(m); } },
          m.cast.badge(name, 18), h("span", {}, h("b", {}, name), h("small", {}, status))),
        h("div", { class: "activity-track", "aria-label": `${name}: ${status}` },
          today.filter((row) => row.actor === name).map((row) => {
            const end = row.end ?? now;
            const title = `${name} · ${label(row)} · ${clock(row.start)}–${row.end == null ? "ongoing" : clock(row.end)}`;
            return h("button", {
              type: "button", class: `activity-block activity-${row.type}${row.end == null ? " ongoing" : ""}`,
              style: { left: `${percent(row.start)}%`, width: `${Math.max(0.35, percent(end) - percent(row.start))}%` },
              title, "aria-label": title, onclick: () => this.onJump(row.start),
            });
          }),
          h("span", { class: "activity-cursor", style: { left: `${percent(now)}%` }, "aria-hidden": "true" })),
      );
    });
    const entries = today.filter((row) => !this.person || row.actor === this.person);
    fill(this.el,
      h("header", { class: "activity-heading" }, h("h3", {}, "Activities"), h("time", {}, `Day ${day} · ${clock(now)}`)),
      h("p", { class: "note" }, "Each lane follows one resident. Select a segment to replay its start. Ongoing segments extend to the current replay time."),
      h("div", { class: "activity-legend" }, Object.entries(ACTIVITY_LABELS).map(([type, name]) => h("span", {}, h("i", { class: `activity-${type}` }), name))),
      h("div", { class: "activity-lanes" }, h("div", { class: "activity-axis" }, h("span", {}, "Resident / current activity"), h("div", { class: "activity-ruler" }, [0, 1 / 3, 2 / 3, 1].map((part) => h("span", {}, clock(from + span * part).slice(0, 5))))), lanes),
      h("div", { class: "activity-heading" }, h("h4", {}, "Activity history"),
        h("label", {}, "Resident ", h("select", { "aria-label": "Filter activity history", onchange: (event) => { this.person = event.target.value; this.update(m); } },
          ["", ...m.world.agents.map((agent) => agent.name)].map((name) => h("option", { value: name, selected: name === this.person }, name || "All residents"))))),
      h("p", { class: "note" }, "Ordered by start time. Gaps indicate that no activity has started yet; tool operations stay inside their parent activity."),
      entries.length ? h("ol", { class: "activity-history" }, entries.map((row) => h("li", {},
        h("button", { class: "linkish activity-time", type: "button", onclick: () => this.onJump(row.start) }, `${clock(row.start)}–${row.end == null ? "ongoing" : clock(row.end)}`),
        h("div", {}, h("b", {}, `${row.actor} · ${label(row)}`), h("span", { class: "activity-location" }, m.places.has(row.place) ? shortName(m.places.get(row.place)) : row.place || "Location not recorded"),
          h("small", {}, row.end == null ? `In progress${row.tool ? ` · ${row.tool}` : ""}` : row.reason)),
      ))) : h("p", { class: "note" }, "No recorded activities in this view yet."),
    );
  }
}
