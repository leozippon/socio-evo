import { calendarOf, dayOf, dayStart, hhmmss, minuteOf } from "../clock.js";
import { fill, h } from "../dom.js";
import { speechText } from "./events.js";
import { shortName } from "../world.js";
import { activityDuration, activityIntervals, activityLink, activityType, activityLabel, ACTIVITY_LABELS, activityConversations } from "./activity-model.js";

const clock = (time) => hhmmss(minuteOf(time));
const label = activityLabel;

/** Activity overview and shared conversation transcripts at the current replay moment. */
export class ActivitiesPanel {
  constructor() {
    this.el = h("section", { class: "activities-panel", "aria-label": "Resident activities" });
  }

  update(m) {
    const now = m.state.time, day = dayOf(now), base = dayStart(day);
    const cal = calendarOf(m.world), from = base + cal.start, to = base + cal.end;
    const span = Math.max(1, to - from);
    const percent = (time) => Math.max(0, Math.min(100, (time - from) / span * 100));
    const reader = !m.truth ? m.selected : null;
    const rows = !m.truth && !reader ? [] : activityIntervals(m.activityEvents, now, reader);
    const today = rows.filter((row) => (row.end ?? now) >= base && row.start < base + 1440);
    const current = new Map(rows.filter((row) => row.end == null).map((row) => [row.actor, row]));
    const place = (row) => `${row.outside ? "Outside · " : ""}${m.places.has(row.place) ? shortName(m.places.get(row.place)) : row.place || "Not recorded"}`;
    const link = (name, row = null) => activityLink(m.route, name, now, row, day);
    const purposeLabel = (purpose) => ({ summary: "Work summary", experience: "Experience" })[purpose] ?? purpose;
    const sourceTask = (row) => m.activityEvents.find((event) => event.payload?.activity === row.sourceActivityId && event.payload?.task_id)?.payload.task_id;
    const tooltip = h("div", { class: "activity-tooltip", role: "tooltip", id: "activity-hover", hidden: true });
    const hide = () => { tooltip.hidden = true; };
    const show = (row, event) => {
      const anchor = event.currentTarget.getBoundingClientRect();
      const x = event.clientX || anchor.left, y = event.clientY || anchor.bottom;
      fill(tooltip, h("b", {}, `${row.actor} · ${label(row)}`),
        h("span", {}, `${clock(row.start)}–${row.end == null ? "ongoing" : clock(row.end)}`),
        h("span", {}, `${activityDuration(((row.end ?? now) - row.start) * 60)} · ${place(row)}`),
        row.purpose ? h("span", {}, `Purpose: ${purposeLabel(row.purpose)}`) : null,
        row.sourceActivityId ? h("span", {}, `Source activity: ${row.sourceActivityId}`) : null,
        sourceTask(row) ? h("span", {}, `Source job: ${sourceTask(row)}`) : null,
        h("span", {}, row.end == null ? `In progress${row.tool ? ` · ${row.tool}` : ""}` : activityType(row) === "reflect" && row.completed != null ? row.completed ? "Completed" : "Cancelled" : row.reason),
        h("small", {}, "Open resident activity details →"));
      tooltip.hidden = false;
      tooltip.style.left = `${Math.max(8, Math.min(window.innerWidth - 270, x - 80))}px`;
      tooltip.style.top = `${Math.max(8, Math.min(window.innerHeight - tooltip.offsetHeight - 8, y + 15))}px`;
    };
    const lanes = m.world.agents.map(({ name }) => {
      const active = current.get(name), known = m.truth || name === reader;
      const status = active ? `${active.outside && active.type === "rest" ? "Waiting outside" : label(active)}${active.purpose ? ` · ${purposeLabel(active.purpose)}` : ""}${active.tool ? ` · ${active.tool}` : ""}` : known ? "Between activities" : "Not observed";
      return h("div", { class: "activity-lane" },
        h("a", { class: "linkish activity-person", href: link(name), "aria-label": `${name}'s daily activities` },
          m.cast.badge(name, 18), h("span", {}, h("b", {}, name), h("small", {}, status))),
        h("div", { class: "activity-track", "aria-label": `${name}: ${status}` },
          today.filter((row) => row.actor === name).map((row) => h("a", {
            href: link(name, row), class: `activity-block activity-${activityType(row)}${row.end == null ? " ongoing" : ""}`,
            style: { left: `${percent(row.start)}%`, width: `${Math.max(0.35, percent(row.end ?? now) - percent(row.start))}%` },
            "aria-label": `${name} · ${label(row)} · ${clock(row.start)}–${row.end == null ? "ongoing" : clock(row.end)}`,
            "aria-describedby": "activity-hover", onpointerenter: (event) => show(row, event), onpointerleave: hide,
            onfocus: (event) => show(row, event), onblur: hide, onkeydown: (event) => { if (event.key === "Escape") hide(); },
          })),
          h("span", { class: "activity-cursor", style: { left: `${percent(now)}%` }, "aria-hidden": "true" })),
      );
    });
    const conversations = !m.truth && !reader ? [] : activityConversations(m.activityEvents, now, day, reader);
    const scope = `${m.route.experiment}/${m.route.run}/${day}`;
    if (this.conversationScope !== scope) { this.conversationScope = scope; this.conversationId = null; }
    const selected = conversations.find((row) => row.id === this.conversationId) ?? conversations.at(-1);
    this.conversationId = selected?.id ?? null;
    const conversationLabel = (row) => `${clock(row.start)} · ${place(row)} · ${row.participants.join(", ") || "No participants recorded"}`;
    const transcript = h("div", { class: "conversation-detail" });
    const showConversation = (row) => {
      this.conversationId = row.id;
      fill(transcript,
        h("p", { class: "note" }, conversationLabel(row)),
        row.entries.length ? h("ol", { class: "conversation-messages", "aria-label": "Conversation timeline" }, row.entries.map((entry) => {
          if (entry.kind !== "speech") return h("li", { class: "conversation-membership" },
            h("time", {}, clock(entry.time)), h("span", {}, `${entry.actor} ${entry.kind}`));
          const event = entry.event;
          return h("li", {}, h("header", {}, h("time", {}, clock(event.time)), h("b", {}, event.actor ?? event.payload.message?.author ?? "Unknown speaker")),
            h("p", {}, speechText(event)));
        })) : h("p", { class: "note" }, "No messages recorded yet."));
    };
    if (selected) showConversation(selected);
    fill(this.el,
      h("header", { class: "activity-heading" }, h("h3", {}, "Activities"), h("time", {}, `Day ${day} · ${clock(now)}`)),
      h("p", { class: "note" }, "Hover or focus a segment for a summary. Open it to inspect that resident's activity, tools and feedback."),
      h("div", { class: "activity-legend" }, Object.entries(ACTIVITY_LABELS).map(([type, name]) => h("span", {}, h("i", { class: `activity-${type}` }), name))),
      h("div", { class: "activity-lanes" }, h("div", { class: "activity-axis" }, h("span", {}, "Resident / current activity"), h("div", { class: "activity-ruler" }, [0, 1 / 3, 2 / 3, 1].map((part) => h("span", {}, clock(from + span * part).slice(0, 5))))), lanes),
      h("div", { class: "activity-heading" }, h("h4", {}, "Conversations"), h("span", { class: "muted" }, `Day ${day}`)),
      selected ? [
        h("label", { class: "conversation-picker" }, "Conversation ", h("select", {
          "aria-label": "Conversation", onchange: (event) => showConversation(conversations.find((row) => row.id === event.target.value)),
        }, conversations.map((row) => h("option", { value: row.id, selected: row.id === selected.id }, conversationLabel(row))))),
        transcript,
      ] : h("p", { class: "note" }, "No conversations recorded at this moment."), tooltip,
    );
  }
}
