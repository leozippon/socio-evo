// The things of a life, as a reader sees them: the goods of the town's catalogue with what each
// does in plain words, what a resident owns as item cards, and its body's three needs as bars
// read in the bands of the world's own words. Everything here is drawn from `world.json`
// (the catalogue and the bands) and the timeline (purchases, the things owned, the markers of
// the body); nothing is computed beyond looking those up.

import { hhmm, secondOfDay } from "./clock.js";
import { fmt, h } from "./dom.js";
import { icon } from "./icons.js";
import { shortName } from "./world.js";

/** The three needs in the order the town tells them, each with the word a reader knows it by. */
export const NEEDS = [
  ["satiety", "Food", "bowl"],
  ["energy", "Energy", "zap"],
  ["health", "Health", "heart"],
];

/** The icon of a good, by what it does. */
export function goodIcon(good) {
  if (good.effect === "food") return good.kind === "consumable" ? "basket" : "meal";
  if (good.effect === "appearance") return /\bbook\b/.test(good.name) ? "book" : "coat";
  return { travel: "bicycle", messaging: "phone", examination: "clinic", treatment: "pill" }[good.effect] ?? "spark";
}

/** A good's name as a label: without its article, capitalised. */
export function goodName(good) {
  const name = good.name.replace(/^(a|an|the)\s+/i, "");
  return name[0].toUpperCase() + name.slice(1);
}

/** What a good does for its owner, in a sentence. */
export function goodEffect(good) {
  const share = (n) => (n >= 100 ? "a day's food" : `${Math.round(n)}% of a day's food`);
  switch (good.effect) {
    case "food":
      return good.nourishment ? `A helping of ${share(good.nourishment)}, eaten as the owner gets hungry` : "Cooked with in the kitchen, not eaten as it is";
    case "travel":
      return good.factor === 0.5 ? "Halves the time of every journey" : `Journeys take ${Math.round(good.factor * 100)}% of the time`;
    case "messaging":
      return `Write to other owners wherever they are${good.fee_per_day ? `; charged ${fmt.money(good.fee_per_day)} a day` : ""}`;
    case "appearance":
      return `Others see its owner ${good.phrase}`;
    case "examination":
      return "The doctor tells the body's numbers and why health last moved";
    case "treatment":
      return `Restores ${fmt.int(good.restores)} health`;
    default:
      return "";
  }
}

/** The kind of good in a word: kept, a stock, or used up as bought. */
export const goodKind = (good) => ({ durable: good.fee_per_day ? "kept, charged daily" : "kept", consumable: "a stock", immediate: "used at once" })[good.kind] ?? good.kind;

/** Where a good is sold: the store, by its short name. */
export const soldAt = (good, world) => world.places.filter((place) => place.kind === "store").map(shortName).join(", ");

/** What is kept of a consumable in words: `6 helpings`, `4 units`. */
export function stockText(good, units) {
  if (good.kind !== "consumable") return null;
  return fmt.plural(units, good.nourishment ? "helping" : "unit");
}

/**
 * An item card: the icon, the name, and a line that says what it is worth to its owner. With
 * `units`, a consumable's stock; with `price`, the catalogue's price tag and where it is sold.
 */
export function itemCard(good, { units = null, price = false, world = null, compact = false } = {}) {
  const line = units !== null && good.kind === "consumable" ? stockText(good, units) : goodEffect(good);
  return h(
    "div",
    { class: `item kind-${good.kind} effect-${good.effect}${compact ? " compact" : ""}`, title: `${goodName(good)}: ${goodEffect(good)}${price && world ? `. ${fmt.money(good.price)} at ${soldAt(good, world)}` : ""}` },
    h("span", { class: "item-icon" }, icon(goodIcon(good), compact ? 16 : 22)),
    h("span", { class: "item-text" }, h("b", {}, goodName(good)), compact ? null : h("span", { class: "item-line" }, line)),
    price ? h("span", { class: "item-price" }, fmt.money(good.price), world ? h("small", {}, soldAt(good, world)) : null) : null,
    compact && units !== null && good.kind === "consumable" ? h("span", { class: "item-count" }, `×${fmt.int(units)}`) : null,
  );
}

/** The things a resident owns (`things`, by good id) as item cards, or a quiet line if none. */
export function inventory(world, things, { compact = false } = {}) {
  const cards = world.goods.filter((good) => things[good.id]).map((good) => itemCard(good, { units: things[good.id], compact }));
  return h("div", { class: `inventory${compact ? " compact" : ""}` }, cards.length ? cards : h("span", { class: "muted small-text" }, "Nothing of their own yet"));
}

/** The band of a need a value falls in, from the world's bands (top down). */
export const bandOf = (world, need, value) => world.needs[need].bands.find((band) => value >= band.floor) ?? world.needs[need].bands.at(-1);

/** The tone of a band, from the top (good) to the lowest (critical). */
function bandTone(bands, index) {
  if (index === 0) return "good";
  if (index === bands.length - 1) return "critical";
  return index === 1 && bands.length > 3 ? "warn" : "serious";
}

/**
 * A need as a bar read in bands: the bar is divided at the bands' floors and filled up to the
 * top of the band the resident is in, which is named beside it; the last number the world gave
 * (at a band crossing, at midnight or at the start) is told on hover. `state` is a need of
 * `bodyAt`, or null for a need still in its top band.
 */
export function needBar(world, need, state, { label = true, size = "" } = {}) {
  const [, word, glyph] = NEEDS.find(([key]) => key === need);
  const bands = world.needs[need].bands;
  const told = state?.value !== undefined && state?.value !== null;
  const index = state?.band ? Math.max(0, bands.findIndex((band) => band.name === state.band)) : told ? bands.indexOf(bandOf(world, need, state.value)) : 0;
  const top = index === 0 ? 100 : bands[index - 1].floor;
  const tone = bandTone(bands, index);
  const known = told ? `last told ${Math.round(state.value)} of 100 at ${hhmm(secondOfDay(state.t))}` : "full at the start, no number told since";
  const title = `${word}: ${bands[index].name} (${bands[index].floor} to ${top} of 100); ${known}.`;
  return h(
    "div",
    { class: `need need-${need} tone-${tone} ${size}`, title, role: "img", "aria-label": `${word}: ${bands[index].name}` },
    h("span", { class: "need-icon" }, icon(glyph, size === "mini" ? 11 : 14)),
    label ? h("span", { class: "need-word" }, word) : null,
    h(
      "span",
      { class: "need-bar" },
      h("span", { class: "need-fill", style: { width: `${top}%` } }),
      bands.slice(1).map((band) => h("i", { class: "need-tick", style: { left: `${band.floor}%` } })),
    ),
    label ? h("span", { class: "need-band" }, bands[index].name) : null,
  );
}

/** The three needs of a resident as bars, from the body of `bodyAt`. */
export const needBars = (world, body, options = {}) => h("div", { class: `needs${options.size === "mini" ? " mini" : ""}` }, NEEDS.map(([need]) => needBar(world, need, body[need] ?? null, options)));
