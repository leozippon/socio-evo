import { dayOf, dayStart, formatTime, hhmmss, minuteOf, normalizeEventTimes, parseStamp, stamp } from "../clock.js";
import { emptyState, h } from "../dom.js";
import { href, sibling } from "../router.js";
import { activityDuration, activityIntervals, activityLink, activityTranscript, ACTIVITY_LABELS, residentActivitySummary, revealCurrentActivity } from "../town/activity-model.js";
import { bystanders, line } from "../town/events.js";
import { decisionCard } from "../town/panels.js";
import { shortName } from "../world.js";

const clock = (time) => hhmmss(minuteOf(time));
const label = (row) => ACTIVITY_LABELS[row.type] ?? row.type;
const pretty = (key) => key.replaceAll("_", " ");
const OUTCOMES = new Set(["work_submitted", "work_assessed", "payment", "work_checked", "task_expired"]);

/** A resident's day and one membership's transcript, both bounded by the shared replay cutoff. */
export async function personActivities({ source, world, cast, places, route, go }) {
  const latest = source.doc.last_time_seconds != null ? source.doc.last_time_seconds / 60 : source.doc.last_time ?? 0;
  const requested = parseStamp(route.query.t);
  const through = Math.min(latest, requested ?? latest);
  const days = source.doc.event_days.map((entry) => entry.day).filter((day) => day <= dayOf(through));
  if (!days.length) return emptyState("No recorded activity day yet.");
  const day = days.includes(Number(route.query.day)) ? Number(route.query.day) : days.at(-1);
  const cutoff = Math.min(through, dayStart(day + 1) - 1 / 60);
  const events = normalizeEventTimes(await source.eventDay(day)).filter((event) => event.time <= cutoff);
  const rows = activityIntervals(events, cutoff).filter((row) => row.actor === route.agent);
  const summary = residentActivitySummary(rows, route.agent, day, cutoff);
  const selected = rows.find((row) => row.id === route.query.activity);
  const place = (row) => `${row.outside ? "Outside · " : ""}${places.has(row.place) ? shortName(places.get(row.place)) : row.place || "Not recorded"}`;
  const reveal = (row, event) => revealCurrentActivity(event, row.id, selected?.id,
    () => document.getElementById("person-activity-detail")?.scrollIntoView({ block: "start", behavior: "smooth" }));
  const rowLink = (row) => activityLink(route, route.agent, through, row, day);
  const controls = h("div", { class: "spread activity-ledger-heading" },
    h("div", {}, h("h2", {}, "Daily activities"), h("p", { class: "note" }, `${summary.count} activities · Work ${activityDuration(summary.seconds.work)} · Conversation ${activityDuration(summary.seconds.conversation)}`)),
    h("label", {}, "Day ", h("select", { "aria-label": "Activity day", onchange: (event) => go({ day: event.target.value, activity: null }) }, days.map((value) => h("option", { value: String(value), selected: value === day }, `Day ${value}`)))),
  );
  const table = rows.length ? h("div", { class: "card pad table-wrap activity-table-wrap" }, h("table", { class: "data activity-table", "aria-label": `${route.agent}'s activities on day ${day}` },
    h("thead", {}, h("tr", {}, ["Start", "End", "Activity", "Place", "Elapsed", "Status", ""].map((text) => h("th", { scope: "col" }, text)))),
    h("tbody", {}, rows.map((row) => h("tr", { class: row.id === selected?.id ? "selected-activity" : "" },
      h("td", {}, h("a", { href: rowLink(row), onclick: (event) => reveal(row, event) }, clock(row.start))),
      h("td", {}, row.end == null ? "Ongoing" : clock(row.end)),
      h("td", {}, h("span", { class: "activity-type-label" }, h("i", { class: `activity-${row.type}` }), label(row))),
      h("td", {}, place(row)),
      h("td", {}, activityDuration(((row.end ?? cutoff) - row.start) * 60)),
      h("td", {}, row.end == null ? "In progress" : "Ended"),
      h("td", {}, h("a", { href: rowLink(row), onclick: (event) => reveal(row, event), "aria-current": row.id === selected?.id ? "true" : null, "aria-label": `Open ${route.agent}'s ${label(row)} at ${clock(row.start)}` }, row.id === selected?.id ? "Show details ↓" : "Details ↓")),
    ))),
  )) : h("div", { class: "card" }, emptyState("No recorded activities on this day.", "Older runs may contain actions without activity membership records."));
  let detail = h("div", { class: "card activity-detail-hint" }, emptyState(route.query.activity ? "This activity is not available at this moment." : "Select an activity to inspect it.", "Open a row to see its tools, feedback and received conversation in chronological order."));
  if (selected) {
    const transcript = activityTranscript(events, selected, cutoff);
    const tasks = new Map(events.filter((event) => event.kind === "task_posted").map((event) => [event.payload.task.id, event]));
    const m = { cast, places, lookups: { tasks, places }, truth: true, reader: null, bystanders: bystanders(transcript), select: () => {} };
    const received = transcript.filter((event) => ["speech", "conversation_message"].includes(event.kind));
    const participants = new Set([...selected.participants, ...received.flatMap((event) => event.payload.participants ?? event.audience ?? [])]);
    const task = transcript.map((event) => event.payload.task_id ?? event.payload.arguments?.task_id ?? event.payload.action?.task_id ?? event.payload.action?.arguments?.task_id).find(Boolean);
    const later = task && selected.endSeq != null ? events.filter((event) => event.seq > selected.endSeq && OUTCOMES.has(event.kind) && event.payload.task_id === task && (event.actor === route.agent || event.payload.agent === route.agent || (event.audience ?? []).includes(route.agent))) : [];
    const renderEvent = (event) => {
      if (event.kind === "decision") return h("li", {}, decisionCard(event, transcript.filter((row) => row.time === event.time), m));
      const title = `${clock(event.time)} · ${event.actor ? `${event.actor} · ` : ""}${pretty(event.kind)}`;
      const data = event.kind === "tool_started" ? event.payload.arguments : event.kind === "command_executed" ? event.payload.command : null;
      return h("li", { class: "activity-log-event" },
        h("header", {}, h("time", {}, title)),
        event.text?.length > 500 ? h("details", {}, h("summary", {}, `${event.text.slice(0, 180)}…`), h("pre", { class: "activity-output" }, event.text)) : h("p", {}, line(event, m)),
        data ? h("details", { class: "code" }, h("summary", {}, event.kind === "command_executed" ? "Command" : "Tool arguments"), h("pre", {}, typeof data === "string" ? data : JSON.stringify(data, null, 2))) : null,
      );
    };
    detail = h("section", { class: "card pad activity-detail", id: "person-activity-detail", "aria-label": "Activity details" },
      h("div", { class: "spread" }, h("h2", {}, `${route.agent} · ${label(selected)}`), h("a", { class: "ghost small", href: href(sibling({ ...route, query: { t: stamp(selected.start) } }, "town", { query: { agent: route.agent, panel: "activities" } })) }, "Watch in town")),
      h("p", { class: "activity-detail-period" }, `Day ${day} · ${clock(selected.start)}–${selected.end == null ? "ongoing" : clock(selected.end)} · ${activityDuration(((selected.end ?? cutoff) - selected.start) * 60)}`),
      h("dl", { class: "activity-facts" },
        h("dt", {}, "Place"), h("dd", {}, selected.type === "move" ? `From ${place(selected)}` : place(selected)),
        h("dt", {}, "Participants"), h("dd", {}, [...participants].join(", ")),
        h("dt", {}, "Status"), h("dd", {}, selected.end == null ? `In progress as of ${formatTime(cutoff)}` : selected.reason),
        h("dt", {}, "Activity ID"), h("dd", {}, h("code", {}, selected.activity)),
        task ? [h("dt", {}, "Task"), h("dd", {}, task)] : null),
      h("h3", {}, "Activity log"), h("p", { class: "note" }, "Recorded in delivery order. Includes this resident's operations and speech received while participating. Research view includes recorded thoughts."),
      h("ol", { class: "activity-detail-log" }, transcript.map(renderEvent)),
      later.length ? [h("h3", {}, "Subsequent task feedback"), h("p", { class: "note" }, "Task feedback delivered after the activity ended, up to this snapshot."), h("ol", { class: "activity-detail-log" }, later.map(renderEvent))] : null,
    );
  }
  return [controls, h("p", { class: "note" }, `Showing Day ${day} through ${clock(cutoff)}. Each row is one continuous membership; returning to the same activity produces a new row.`), table, detail];
}
