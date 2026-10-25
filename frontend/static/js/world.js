// Facts about a run's world that several views show: its places, its group, and what the five
// events and the markers of the timeline are called.

export const GROUPS = {
  A: ["A", "independent learning", "Each resident lives in a town of its own: it never perceives another."],
  B: ["B", "technical experience sharing", "As A, with an evening exchange of work experience between residents paired by lot."],
  C: ["C", "social learning", "One town: free conversation, a shared board, money, skills and ratings."],
  D: ["D", "social life without self-modification", "As C, but skills can be neither written nor passed on."],
};

/** A group's short label, "Group C · social learning"; a run of no group has none. */
export const groupLabel = (group) => (GROUPS[group] ? `Group ${GROUPS[group][0]} · ${GROUPS[group][1]}` : null);

/** The five events a resident is always in one of, and the conversation layered over them. */
export const EVENTS = { idle: "Idle", movement: "Movement", work: "Work", sleep: "Sleep", conversation: "Conversation" };

/** The markers of the timeline, by kind, and what each is. */
export const MARKERS = {
  claim: "a task claimed",
  submission: "a hand-in and its verdict",
  payment: "a payment",
  abandon: "a task given up",
  expiry: "a claim run out",
  speech: "something said",
  gift: "money handed over",
  skill_shared: "a skill passed on",
  rating: "a rating",
  journal: "to bed with the day's journal",
  forced_sleep: "forced sleep",
};

export const placeById = (world) => new Map(world.places.map((place) => [place.id, place]));

/** A place's name without a leading article, capitalised, for labels on their own. */
export function shortName(place) {
  const name = place.name.replace(/^the\s+/i, "");
  return name[0].toUpperCase() + name.slice(1);
}

/** The home of each resident, by name. */
export const homes = (world) => Object.fromEntries(world.residents.map((r) => [r.name, r.home]));
