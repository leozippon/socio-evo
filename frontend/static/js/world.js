// Facts about a run's world that several views show: its places and the changes of conditions.

import { formatTime } from "./clock.js";

const CONDITIONS = {
  living_cost: ["living cost", (v) => `${v} cr`],
  tasks_per_day: ["tasks per day", String],
  reward_multiplier: ["reward multiplier", (v) => `×${v}`],
  defect_discovery_prob: ["chance a defect is found", (v) => `${Math.round(v * 100)}% a day`],
  clawback: ["clawback of defective work", (v) => (v ? "on" : "off")],
  esteem_public: ["public esteem", (v) => (v ? "on" : "off")],
};

export const conditionLabel = (key) => CONDITIONS[key]?.[0] ?? key.replaceAll("_", " ");
export const conditionValue = (key, value) => (CONDITIONS[key]?.[1] ?? String)(value);

/** The world's interventions in order, each with what it changed from what to what. */
export function interventions(world) {
  let conditions = { ...world.conditions };
  return world.interventions.map((found) => {
    const changes = Object.entries(found.conditions).map(([key, value]) => {
      const change = { key, label: conditionLabel(key), from: conditionValue(key, conditions[key]), to: conditionValue(key, value) };
      return change;
    });
    conditions = { ...conditions, ...found.conditions };
    const what = changes.length ? changes.map((c) => `${c.label} ${c.from} → ${c.to}`).join("; ") : "an announcement";
    return {
      day: found.day,
      time: found.time,
      changes,
      announcement: found.announcement,
      announced: found.announcement !== null,
      label: `${formatTime(found.time)}: ${what}${found.announcement === null ? " (not announced)" : " (announced)"}`,
    };
  });
}

/** Markers for every chart's day axis. */
export const markers = (world) => interventions(world).map((found) => ({ day: found.day, label: found.label, announced: found.announced }));

export const placeById = (world) => new Map(world.places.map((place) => [place.id, place]));

/** A place's name without a leading article, capitalised, for labels on their own. */
export function shortName(place) {
  const name = place.name.replace(/^the\s+/i, "");
  return name[0].toUpperCase() + name.slice(1);
}
