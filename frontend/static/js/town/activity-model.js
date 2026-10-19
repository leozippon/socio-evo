import { dayOf, dayStart, stamp } from "../clock.js";
import { href } from "../router.js";

// Activity intervals are membership intervals, not tool durations. Planned end times are
// deadlines only; only activity_left closes an interval. A resumed activity gets a new row.
export const ACTIVITY_LABELS = { rest: "Rest", move: "Move", work: "Work", conversation: "Conversation" };
export const activityLabel = (row) => row.type === "rest" && row.phase === "choosing_next_activity"
  ? "Deciding" : ACTIVITY_LABELS[row.type] ?? row.type;

export function activityIntervals(events, through, reader = null) {
  const intervals = [];
  const active = new Map();
  for (const event of events) {
    if (event.time > through) continue;
    const p = event.payload ?? {};
    if (reader && event.actor !== reader && !(event.audience ?? []).includes(reader)) continue;
    if (event.kind === "activity_entered") {
      const previous = active.get(event.actor);
      if (previous) { previous.end = event.time; previous.endSeq = event.seq - 1; previous.reason = "Next activity started"; }
      const interval = {
        id: `${event.seq}:${event.actor}`, startSeq: event.seq, endSeq: null, participants: [...(p.participants ?? [event.actor])], activity: p.activity, actor: event.actor,
        type: p.activity_type, phase: p.phase ?? null, start: event.time, end: null, place: event.place,
        reason: null, tool: null, outside: Boolean(p.outside),
      };
      for (const peer of active.values()) if (peer.activity === p.activity && !peer.participants.includes(event.actor)) peer.participants.push(event.actor);
      intervals.push(interval);
      active.set(event.actor, interval);
    } else if (event.kind === "activity_left") {
      const interval = active.get(event.actor);
      if (interval?.activity === p.activity) {
        interval.end = event.time;
        interval.endSeq = event.seq;
        interval.reason = p.reason ?? "Activity ended";
        interval.tool = null;
        active.delete(event.actor);
      }
    } else if (event.kind === "tool_started") {
      const interval = active.get(event.actor);
      if (interval?.activity === p.activity) interval.tool = p.tool;
    } else if (event.kind === "tool_completed" || event.kind === "tool_cancelled") {
      const interval = active.get(event.actor);
      if (interval?.activity === p.activity) interval.tool = null;
    }
  }
  return intervals.sort((a, b) => a.start - b.start);
}

/** Recorded events for one resident's membership, including speech actually heard there. */
export function activityTranscript(events, interval, through) {
  return events.filter((event) => {
    if (event.time > through || event.seq < interval.startSeq || (interval.endSeq != null && event.seq > interval.endSeq)) return false;
    const p = event.payload ?? {};
    if (event.actor === interval.actor) return !p.activity || p.activity === interval.activity;
    return ["speech", "conversation_message"].includes(event.kind) && p.activity === interval.activity && (event.audience ?? []).includes(interval.actor);
  });
}

export function residentActivitySummary(intervals, actor, day, through) {
  const start = dayStart(day), end = Math.min(through, start + 1440);
  const rows = intervals.filter((row) => row.actor === actor && row.start <= end && (row.end ?? end) >= start);
  const seconds = Object.fromEntries(Object.keys(ACTIVITY_LABELS).map((type) => [type, 0]));
  for (const row of rows) seconds[row.type] = (seconds[row.type] ?? 0) + Math.max(0, Math.round((Math.min(row.end ?? end, end) - Math.max(row.start, start)) * 60));
  return { count: rows.length, seconds, current: rows.findLast((row) => row.end == null) ?? null };
}

export function activityDuration(seconds) {
  const whole = Math.max(0, Math.round(seconds));
  const hour = Math.floor(whole / 3600), minute = Math.floor(whole / 60) % 60, second = whole % 60;
  return hour ? `${hour}h ${String(minute).padStart(2, "0")}m ${String(second).padStart(2, "0")}s` : minute ? `${minute}m ${String(second).padStart(2, "0")}s` : `${second}s`;
}

export function activityLink(route, actor, through, interval = null, day = dayOf(through)) {
  return href({ view: "person", experiment: route.experiment, run: route.run, agent: actor,
    query: { tab: "activities", day: String(day), t: stamp(through), activity: interval?.id ?? null } });
}

/** An unchanged hash does not fire hashchange: re-open the selected detail explicitly. */
export function revealCurrentActivity(event, key, selected, reveal) {
  if (key !== selected || event.button > 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return false;
  event.preventDefault();
  reveal();
  return true;
}
