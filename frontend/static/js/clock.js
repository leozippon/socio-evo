// Simulated time: minutes (including whole-second fractions) since 00:00 on day 1 (frontend/README.md, "How the bundle works").
// Pure functions, shared by the replay engine (which also runs under node) and every view.

export const DAY = 1440;

export const dayOf = (time) => Math.floor(time / DAY) + 1;
export const minuteOf = (time) => ((time % DAY) + DAY) % DAY;
export const dayStart = (day) => (day - 1) * DAY;

const pad = (n) => String(n).padStart(2, "0");
export const hhmm = (minute) => `${pad(Math.floor(minute / 60))}:${pad(Math.floor(minute % 60))}`;

/** A clock display shown to whole seconds, never fractional digits. */
export const hhmmss = (minute) => {
  const seconds = ((Math.floor(minute * 60 + 1e-7) % 86400) + 86400) % 86400;
  return `${pad(Math.floor(seconds / 3600))}:${pad(Math.floor(seconds / 60) % 60)}:${pad(seconds % 60)}`;
};
export const eventTime = (event) => Number.isFinite(event.payload?.sim_seconds) ? event.payload.sim_seconds / 60 : event.time;

/** Preserve event sequence when precise seconds and legacy minute stamps are mixed. */
export function normalizeEventTimes(events) {
  let through = 0;
  return events.map((event) => {
    through = Math.max(through, eventTime(event));
    return { ...event, time: through };
  });
}

/** Minutes after midnight of an `HH:MM` string. */
export function parseHHMM(text) {
  const match = /^(\d{1,2}):(\d{2})(?::(\d{2}))?$/.exec(text);
  if (!match) throw new Error(`not a clock time: ${text}`);
  return Number(match[1]) * 60 + Number(match[2]) + Number(match[3] ?? 0) / 60;
}

export const timeAt = (day, clock) => dayStart(day) + parseHHMM(clock);
export const formatTime = (time) => `Day ${dayOf(time)} · ${hhmmss(minuteOf(time))}`;

/** The compact, URL-friendly form of a time: `5-09:05` is day 5 at 09:05. */
export const stamp = (time) => `${dayOf(time)}-${hhmmss(minuteOf(time))}`;
export function parseStamp(text) {
  const match = /^(\d+)-(\d{1,2}:\d{2}(?::\d{2})?)$/.exec(text ?? "");
  return match ? timeAt(Number(match[1]), match[2]) : null;
}

/** The calendar of a world in minutes: day start, slots with their ends, day end. */
export function calendarOf(world) {
  const { calendar } = world;
  const end = parseHHMM(calendar.day_end);
  const starts = calendar.slots.map((slot) => parseHHMM(slot.start));
  return {
    start: parseHHMM(calendar.day_start),
    end,
    slots: calendar.slots.map((slot, i) => ({ name: slot.name, start: starts[i], end: starts[i + 1] ?? end })),
  };
}

/** The slot a clock minute falls in, or null before the first slot and after the day end. */
export const slotAt = (cal, minute) => cal.slots.find((slot) => minute >= slot.start && minute < slot.end) ?? null;

/** Whether a place is open at a clock minute; a place without hours is open until the day ends at `dayEnd` (`HH:MM`). */
export function isOpen(place, minute, dayEnd) {
  if (!place.hours.length) return place.kind === "home" || minute < parseHHMM(dayEnd);
  return place.hours.some((span) => {
    const [from, to] = span.split("-").map(parseHHMM);
    return minute >= from && minute < to;
  });
}

/** The next clock minute at which a closed place opens, or null if it never does today. */
export function opensAt(place, minute) {
  const starts = place.hours.map((span) => parseHHMM(span.split("-")[0])).filter((m) => m > minute);
  return starts.length ? Math.min(...starts) : null;
}

/**
 * How much daylight the town has at a clock minute: 0 at night, 1 in full day, in between at
 * dawn and dusk. Purely visual; sunrise and sunset are fixed, not part of the world.
 */
export function daylight(minute) {
  const ramp = (from, to) => Math.min(1, Math.max(0, (minute - from) / (to - from)));
  return ramp(5 * 60, 7 * 60 + 30) * (1 - ramp(18 * 60 + 30, 21 * 60 + 30));
}
