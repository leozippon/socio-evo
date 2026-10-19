// Perceived content is determined by delivery, never by actor proximity or hidden payloads.
const received = (event, reader) => event.kind !== "decision" &&
  (reader ? (event.audience ?? []).includes(reader) : (event.audience ?? []).length > 0);

export function receivedEvents(events, through, reader = null) {
  return events.filter((event) => event.time <= through && received(event, reader))
    .map((event) => ({ ...event, text: reader ? event.personal?.[reader] ?? event.text : event.text }));
}

export function nextReceivedTime(events, after, reader = null) {
  return events.find((event) => event.time > after && received(event, reader))?.time ?? null;
}
