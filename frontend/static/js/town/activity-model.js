// Activity intervals are membership intervals, not tool durations. Planned end times are
// deadlines only; only activity_left closes an interval. A resumed activity gets a new row.
export const ACTIVITY_LABELS = { rest: "Rest", move: "Move", work: "Work", conversation: "Conversation" };

export function activityIntervals(events, through, reader = null) {
  const intervals = [];
  const active = new Map();
  for (const event of events) {
    if (event.time > through) continue;
    const p = event.payload ?? {};
    if (reader && event.actor !== reader && !(event.audience ?? []).includes(reader)) continue;
    if (event.kind === "activity_entered") {
      const previous = active.get(event.actor);
      if (previous) { previous.end = event.time; previous.reason = "Next activity started"; }
      const interval = {
        id: `${event.seq}:${event.actor}`, activity: p.activity, actor: event.actor,
        type: p.activity_type, start: event.time, end: null, place: event.place,
        reason: null, tool: null,
      };
      intervals.push(interval);
      active.set(event.actor, interval);
    } else if (event.kind === "activity_left") {
      const interval = active.get(event.actor);
      if (interval?.activity === p.activity) {
        interval.end = event.time;
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
