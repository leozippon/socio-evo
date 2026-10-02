// Simulated time: integer minutes since 00:00 on day 1 (frontend/README.md, "How the bundle works").
// Pure functions, shared by the replay engine (which also runs under node) and every view.

export const DAY = 1440;

export const dayOf = (time) => Math.floor(time / DAY) + 1;
export const minuteOf = (time) => ((time % DAY) + DAY) % DAY;
export const dayStart = (day) => (day - 1) * DAY;

const pad = (n) => String(n).padStart(2, "0");
export const hhmm = (minute) => `${pad(Math.floor(minute / 60))}:${pad(minute % 60)}`;

/** Minutes after midnight of an `HH:MM` string. */
export function parseHHMM(text) {
  const match = /^(\d{1,2}):(\d{2})$/.exec(text);
  if (!match) throw new Error(`not a clock time: ${text}`);
  return Number(match[1]) * 60 + Number(match[2]);
}

export const timeAt = (day, clock) => dayStart(day) + parseHHMM(clock);
export const formatTime = (time) => `Day ${dayOf(time)} · ${hhmm(minuteOf(time))}`;

/** The compact, URL-friendly form of a time: `5-09:05` is day 5 at 09:05. */
export const stamp = (time) => `${dayOf(time)}-${hhmm(minuteOf(time))}`;
export function parseStamp(text) {
  const match = /^(\d+)-(\d{1,2}:\d{2})$/.exec(text ?? "");
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

/** Whether a place is open at a clock minute; a place without hours never closes. */
export function isOpen(place, minute) {
  if (!place.hours.length) return true;
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
