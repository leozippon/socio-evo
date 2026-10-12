// Facts about a run's world that several views show: its places and the changes of conditions.

import { formatTime } from "./clock.js";
import { money } from "./dom.js";

const percent = (v) => `${Math.round(v * 100)}%`;
const CONDITIONS = {
  living_cost: ["living cost", (v, currency) => `${money(v, currency)} a day`],
  tasks_per_day: ["jobs per day", String],
  one_part_tasks: ["jobs for one per posting", String],
  two_part_tasks: ["jobs for two per posting", String],
  trusting_client_prob: ["clients who pay on the word", percent],
  reward_multiplier: ["reward multiplier", (v) => `×${v}`],
  two_part_premium: ["premium for a job for two", (v) => `×${v}`],
  incomplete_share: ["price of a part handed in as unfinished", percent],
  partner_choice: ["partners for jobs for two", (v) => (v ? "chosen by asking" : "paired by lot")],
  defect_discovery_prob: ["chance a fault comes to light", (v) => `${percent(v)} a day`],
  clawback: ["payment taken back for a fault", (v) => (v ? "yes" : "no")],
  esteem_public: ["standing posted beside the board", (v) => (v ? "yes" : "no")],
};

export const conditionLabel = (key) => CONDITIONS[key]?.[0] ?? key.replaceAll("_", " ");
/** A condition's value in words; amounts in `currency`, the run's `world.setting.currency`. */
export const conditionValue = (key, value, currency) => (CONDITIONS[key]?.[1] ?? String)(value, currency);

/** The world's interventions in order, each with what it changed from what to what. */
export function interventions(world) {
  let conditions = { ...world.conditions };
  const currency = world.setting.currency;
  return world.interventions.map((found) => {
    const changes = Object.entries(found.conditions).map(([key, value]) => {
      const change = { key, label: conditionLabel(key), from: conditionValue(key, conditions[key], currency), to: conditionValue(key, value, currency) };
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
