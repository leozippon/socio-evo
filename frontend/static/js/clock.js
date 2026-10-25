// Simulated time: integer seconds since 00:00 of calendar day 1 (frontend/README.md, "How the
// bundle works"). A lived day runs from one checkpoint to the next, so "Day N" in the viewer is a
// lived day of the run's timeline, while addresses carry the calendar day with the clock time.
// Pure functions, shared by the replay (which also runs under node) and every view.

export const DAY = 86400;
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export const calendarDay = (time) => Math.floor(time / DAY) + 1;
export const secondOfDay = (time) => ((time % DAY) + DAY) % DAY;
export const dayStart = (calendar) => (calendar - 1) * DAY;

const pad = (n) => String(n).padStart(2, "0");
export const hhmm = (seconds) => `${pad(Math.floor(seconds / 3600) % 24)}:${pad(Math.floor((seconds % 3600) / 60))}`;

/** Seconds after midnight of an `HH:MM` string. */
export function parseHHMM(text) {
  const match = /^(\d{1,2}):(\d{2})$/.exec(text);
  if (!match) throw new Error(`not a clock time: ${text}`);
  return Number(match[1]) * 3600 + Number(match[2]) * 60;
}

/** The date of a time as people read it, "Mon 2 Mar", from the ISO date of calendar day 1. */
export function dateOf(startDate, time) {
  const [y, m, d] = startDate.split("-").map(Number);
  const date = new Date(Date.UTC(y, m - 1, d + calendarDay(time) - 1));
  return `${WEEKDAYS[date.getUTCDay()]} ${date.getUTCDate()} ${MONTHS[date.getUTCMonth()]}`;
}

/** The compact, URL-friendly form of a time: `5-09:05` is calendar day 5 at 09:05. */
export const stamp = (time) => `${calendarDay(time)}-${hhmm(secondOfDay(time))}`;
export function parseStamp(text) {
  const match = /^(\d+)-(\d{1,2}:\d{2})$/.exec(text ?? "");
  return match ? dayStart(Number(match[1])) + parseHHMM(match[2]) : null;
}

/**
 * The lived day of a time among the `days` of a timeline (each `{day, start, end}`, `end` null
 * for the day in progress): the first whose end is at or after the time, the last for a time
 * beyond every end.
 */
export function livedDay(days, time) {
  return days.find((day) => day.end === null || time <= day.end) ?? days.at(-1);
}

/** A moment in words: `Day 3 · 14:05`, the day being the lived day where `days` is given. */
export const formatTime = (time, days = null) => `Day ${days ? livedDay(days, time).day : calendarDay(time)} · ${hhmm(secondOfDay(time))}`;

/** A span of seconds in words: `2 h 5 min`, `40 min`, `3 d 1 h`. */
export function duration(seconds) {
  const d = Math.floor(seconds / DAY);
  const h = Math.floor((seconds % DAY) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return [d && `${d} d`, h && `${h} h`, (m || (!d && !h)) && `${m} min`].filter(Boolean).join(" ");
}

/**
 * How much daylight the town has at a second of the day: 0 at night, 1 in full day, in between
 * at dawn and dusk. Purely visual; sunrise and sunset are fixed, not part of the world.
 */
export function daylight(second) {
  const ramp = (from, to) => Math.min(1, Math.max(0, (second - from) / (to - from)));
  return ramp(5 * 3600, 7.5 * 3600) * (1 - ramp(18.5 * 3600, 21.5 * 3600));
}
