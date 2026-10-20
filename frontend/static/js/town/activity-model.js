import { dayOf, dayStart, formatTime, stamp } from "../clock.js";
import { href } from "../router.js";
import { shortName } from "../world.js";

// Activity intervals are membership intervals, not tool durations. Planned end times are
// deadlines only; only activity_left closes an interval. A resumed activity gets a new row.
export const ACTIVITY_LABELS = { rest: "Rest", planning: "Planning", move: "Move", work: "Work", conversation: "Conversation" };
export const activityType = (row) => row.type === "rest" && row.phase === "choosing_next_activity" ? "planning" : row.type;
export const activityLabel = (row) => ACTIVITY_LABELS[activityType(row)] ?? row.type;

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

/** A Planning result is the resident's actual entry, not a proposed or rejected choice. */
export function planningSuccessor(events, interval, through) {
  if (activityType(interval) !== "planning" || interval.endSeq == null || interval.end > through) return null;
  const next = events.filter((event) => event.actor === interval.actor && event.seq > interval.endSeq && event.time <= through)
    .sort((a, b) => a.seq - b.seq)[0];
  return next?.kind === "activity_entered" && next.time === interval.end && next.payload?.activity_type
    && next.payload.phase !== "choosing_next_activity" ? next : null;
}

/** Describe only an entered successor; the immediately preceding choice may clarify it. */
export function planningOutcomeSummary(events, interval, through, places = null) {
  const next = planningSuccessor(events, interval, through);
  if (!next) return null;
  const p = next.payload, type = p.activity_type;
  const previous = events.filter((event) => event.actor === interval.actor && event.seq >= interval.startSeq && event.seq < interval.endSeq && event.time <= through)
    .sort((a, b) => a.seq - b.seq).at(-1);
  const action = previous?.kind === "decision" && previous.time === next.time && previous.payload?.action?.kind === "activity" ? previous.payload.action : null;
  const operation = action?.operation;
  const where = (id) => places?.has(id) ? shortName(places.get(id)) : id;
  let title = activityLabel({ type });
  if (type === "work" && operation === "resume_work" && action.target === p.activity) title = "Resume Work";
  else if (type === "work" && operation === "select_work") title = "Start Work";
  else if (type === "conversation" && operation === "select_conversation" && action.target === p.activity) title = "Join Conversation";
  else if (type === "conversation" && operation === "start_chat") title = "Start Conversation";
  if (type === "rest") {
    const args = operation === "select_rest" ? action.arguments : null;
    if (args?.until && ["today", "tomorrow"].includes(args.day ?? "today")) title += ` until ${args.until} ${args.day ?? "today"}`;
    else if (Number.isFinite(p.end) && p.end > next.time) title += ` until ${formatTime(p.end)}`;
  }
  if (type === "conversation") {
    const peers = (p.participants ?? []).filter((name) => name !== interval.actor);
    if (peers.length) title += ` with ${peers.join(", ")}`;
  }
  const destination = p.destination ?? (type === "move" && operation === "select_move" ? action.target : null);
  if (type === "move" && destination) return `${title} to ${where(destination)}`;
  return `${title}${next.place ? ` · ${type === "move" ? "From " : p.outside ? "Outside " : ""}${where(next.place)}` : ""}`;
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

/** Shared conversations, never one copy per resident or per message recipient. */
export function activityConversations(events, through, day, reader = null) {
  const groups = new Map();
  const recorded = events.filter((event) => event.time <= through);
  const activityTypes = new Map(recorded.filter((event) => event.kind === "activity_entered")
    .map((event) => [event.payload.activity, event.payload.activity_type]));
  const conversationScenes = new Set(recorded.filter((event) => event.kind === "scene_started" && ["conversation", "meeting"].includes(event.payload.kind)).map((event) => event.scene));
  const visible = recorded.filter((event) => !reader || event.actor === reader || (event.audience ?? []).includes(reader))
    .sort((a, b) => a.time - b.time || a.seq - b.seq);
  const group = (id, event) => {
    if (!groups.has(id)) groups.set(id, { id, start: event.time, last: event.time, place: event.place, participants: new Set(), messages: [], entries: [], seen: new Set() });
    const row = groups.get(id);
    row.last = event.time;
    row.place ??= event.place;
    return row;
  };
  const sceneParticipants = new Map();
  const membership = (row, event, action, actors) => {
    for (const actor of new Set(actors)) {
      if (!actor) continue;
      row.participants.add(actor);
      row.entries.push({ kind: action, actor, time: event.time, seq: event.seq });
    }
  };
  for (const event of visible) {
    const p = event.payload ?? {};
    if (event.kind === "activity_entered" && p.activity_type === "conversation" && p.activity) {
      const row = group(`activity:${p.activity}`, event);
      membership(row, event, "joined", [event.actor]);
    } else if (event.kind === "scene_started" && ["conversation", "meeting"].includes(p.kind) && event.scene) {
      const row = group(`scene:${event.scene}`, event);
      sceneParticipants.set(event.scene, p.participants ?? []);
      membership(row, event, "joined", p.participants ?? []);
    }
    const id = p.activity ? `activity:${p.activity}` : event.scene ? `scene:${event.scene}` : null;
    if (!id) continue;
    if (event.kind === "activity_left" || event.kind === "scene_ended") {
      // An exit can be visible even when the entry was private.
      const conversation = p.activity ? activityTypes.get(p.activity) === "conversation" : conversationScenes.has(event.scene);
      const row = groups.get(id) ?? (conversation ? group(id, event) : null);
      if (row) {
        row.last = event.time;
        membership(row, event, "left", event.kind === "activity_left" ? [event.actor] : p.participants ?? sceneParticipants.get(event.scene) ?? []);
      }
      continue;
    }
    if (!["speech", "conversation_message"].includes(event.kind)) continue;
    // Speech may survive in older exports without its membership records.
    const conversation = p.activity ? !activityTypes.has(p.activity) || activityTypes.get(p.activity) === "conversation" : conversationScenes.has(event.scene);
    const row = groups.get(id) ?? (conversation ? group(id, event) : null);
    if (!row) continue;
    const key = p.message?.id != null ? `message:${p.message.id}` : `event:${event.seq}`;
    if (row.seen.has(key)) continue;
    row.seen.add(key);
    row.messages.push(event);
    row.entries.push({ kind: "speech", time: event.time, seq: event.seq, event });
    row.last = event.time;
    if (event.actor ?? p.message?.author) row.participants.add(event.actor ?? p.message.author);
  }
  const start = dayStart(day), end = start + 1440;
  return [...groups.values()].filter((row) => row.start < end && row.last >= start)
    .map(({ seen, ...row }) => ({ ...row, participants: [...row.participants] }));
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
