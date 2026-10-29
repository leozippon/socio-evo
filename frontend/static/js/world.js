// Facts about a run's world that several views show: its places, its occupations and who works
// where, and what the events of the timeline are called.

/** The events a resident is always in one of, and the conversation layered over them. */
export const EVENTS = { idle: "Idle", movement: "Movement", work: "Work", sleep: "Sleep", bedridden: "In bed", conversation: "Conversation" };

/** The kinds of place where an occupation works, in the order a reader meets them. */
export const WORKPLACES = ["office", "store", "restaurant", "hospital", "hall"];

export const placeById = (world) => new Map(world.places.map((place) => [place.id, place]));

/** The town's place of a kind, such as its one store; undefined if it has none. */
export const placeOfKind = (world, kind) => world.places.find((place) => place.kind === kind);

/** A place's name without a leading article, capitalised, for labels on their own. */
export function shortName(place) {
  const name = place.name.replace(/^the\s+/i, "");
  return name[0].toUpperCase() + name.slice(1);
}

/** The home of each resident, by name. */
export const homes = (world) => Object.fromEntries(world.residents.map((r) => [r.name, r.home]));

/** A resident's occupation as the world configures it: `{id, title, workplace, wage_per_hour, per_service}`. */
export function occupationOf(world, name) {
  const resident = world.residents.find((r) => r.name === name);
  return world.occupations.find((occupation) => occupation.id === resident.occupation);
}

/** A resident's occupation in a few words: "the shopkeeper at the Store". */
export function jobOf(world, name) {
  const occupation = occupationOf(world, name);
  const place = world.places.find((p) => p.id === occupation.workplace);
  return `${occupation.title} at ${place.name}`;
}

/** The residents whose workplace is the place `id`. */
export const workersAt = (world, id) => world.residents.filter((r) => occupationOf(world, r.name).workplace === id).map((r) => r.name);
