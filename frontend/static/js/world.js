// Facts about a run's world that several views show: its places, and what the five events of
// the timeline are called.

/** The events a resident is always in one of (dead to the end, once its health ran out), and the conversation layered over them. */
export const EVENTS = { idle: "Idle", movement: "Movement", work: "Work", sleep: "Sleep", dead: "Dead", conversation: "Conversation" };

export const placeById = (world) => new Map(world.places.map((place) => [place.id, place]));

/** A place's name without a leading article, capitalised, for labels on their own. */
export function shortName(place) {
  const name = place.name.replace(/^the\s+/i, "");
  return name[0].toUpperCase() + name.slice(1);
}

/** The home of each resident, by name. */
export const homes = (world) => Object.fromEntries(world.residents.map((r) => [r.name, r.home]));
