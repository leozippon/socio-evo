// The town's panels. Each renders one moment: `m` holds the moment of the timeline (where
// everyone is and what each is in), the timeline itself, the day's entries up to that moment,
// who is selected and whose wording is read.

import { dateOf, hhmm, secondOfDay } from "../clock.js";
import { emptyState, fill, fmt, h } from "../dom.js";
import { goodName, inventory, needBars } from "../goods.js";
import { icon } from "../icons.js";
import { bodyAt, holderAt, illAt, markersBetween, openAt, shopsAt, thingsAt } from "../replay.js";
import { WORKPLACES, occupationOf, placeOfKind, shortName } from "../world.js";
import { STRUCTURE, clockOf, describeMarker, detail, feedItems, glyph, involved, line, tone, witnessed } from "./events.js";

/** A resident's doing in a few words: at work, talking, on the way, asleep, in bed, idle. */
export function doing(found, places) {
  const { segment, conversation, moving, held } = found;
  if (!segment) return "";
  if (moving) return `on the way to ${places.get(moving.to) ? shortName(places.get(moving.to)) : moving.to}`;
  const bits = [];
  if (conversation) bits.push(`talking with ${conversation.with.join(", ")}`);
  if (segment.kind === "work") bits.push(held ? `at work on task ${held.task}` : "at work");
  else if (segment.kind === "sleep") bits.push("asleep");
  else if (segment.kind === "bedridden") bits.push("in bed, too ill to get up");
  else if (!conversation) bits.push("idle");
  if (segment.kind !== "work" && held) bits.push(`holds task ${held.task}`);
  return bits.join(" · ");
}

/** Where a resident is, in a word or two: the place's short name; nothing on the way, which `doing` tells. */
export const whereabouts = (found, places) => (found.moving ? "" : places.get(found.segment?.place) ? shortName(places.get(found.segment.place)) : "");

/** The residents at each place at the moment, by place id; those on the way under null. */
export function byPlace(m) {
  const found = new Map();
  for (const [name, resident] of Object.entries(m.state.residents)) {
    const place = resident.moving ? null : resident.segment?.place ?? null;
    if (!found.has(place)) found.set(place, []);
    found.get(place).push(name);
  }
  return found;
}

/**
 * The people of the town at the moment, one card each: where it is and what it is doing, how
 * its body stands in three bars, its money and the day's change, and what it owns.
 */
export class PeoplePanel {
  constructor() {
    this.el = h("div", { class: "panel people" });
    this.key = null;
  }

  update(m) {
    const key = `${m.time}|${m.selected}`;
    if (key === this.key) return;
    this.key = key;
    fill(
      this.el,
      h("p", { class: "note roster-note" }, `${m.phase}. Tap someone to follow them.`),
      h(
        "ul",
        { class: "people-list" },
        m.cast.names.map((name) => {
          const found = m.state.residents[name];
          const delta = found.purse - m.dayStartPurses[name];
          const abed = found.segment?.kind === "bedridden";
          const things = thingsAt(found.lane, m.time);
          return h(
            "li",
            {},
            h(
              "button",
              { type: "button", class: `person-row${m.selected === name ? " on" : ""}${abed ? " abed" : ""}`, "aria-pressed": String(m.selected === name), onclick: () => m.select(name) },
              m.cast.badge(name, 30),
              h(
                "span",
                { class: "person-main" },
                h("span", { class: "person-line" }, h("b", {}, name), h("span", { class: "muted" }, `${occupationOf(m.world, name).title} · ${whereabouts(found, m.places) || "on the way"}`)),
                h("span", { class: "person-job" }, doing(found, m.places), illAt(found.lane, m.time) ? h("span", { class: "ill-tag" }, " · ill") : null),
                inventory(m.world, things, { compact: true }),
              ),
              h(
                "span",
                { class: "person-figures" },
                h("span", { class: "money", title: "Money in hand, and its change since the day began" }, fmt.money(found.purse), delta ? h("small", { class: delta > 0 ? "up" : "down" }, ` ${fmt.signed(delta)}`) : null),
                needBars(m.world, bodyAt(found.lane, m.time), { label: false, size: "mini" }),
              ),
            ),
          );
        }),
      ),
      h("p", { class: "note small-text" }, "The bars are food in the body, energy and health, each filled to the band the resident is in; hover one for the last number told. Who is ill the resident alone knows, until the doctor examines it."),
    );
  }
}

/** Everything that happened today up to the moment, as the town's people read it. */
export class FeedPanel {
  constructor({ onFollow }) {
    this.el = h("div", { class: "panel feed" });
    this.list = h("ol", { class: "feed-list" });
    this.bar = h("div", { class: "feed-bar" });
    this.el.append(this.bar, this.list);
    this.open = new Set();
    this.onFollow = onFollow;
    this.key = null;
    this.list.addEventListener("scroll", () => (this.pinned = this.list.scrollTop + this.list.clientHeight >= this.list.scrollHeight - 30));
    this.pinned = true;
  }

  update(m, force = false) {
    const key = `${m.time}|${m.selected}|${m.follow}|${m.reader}|${m.dayEntries.length}`;
    if (key === this.key && !force) return;
    this.key = key;
    fill(
      this.bar,
      h("span", { class: "muted" }, m.reader ? `As ${m.reader} read it` : "As the town's people read it"),
      m.selected ? h("button", { type: "button", class: "ghost small", "aria-pressed": String(m.follow), onclick: () => this.onFollow(!m.follow) }, m.cast.badge(m.selected, 14), m.follow ? `Only ${m.selected}` : `Follow ${m.selected}`) : null,
    );
    let entries = m.dayEntries.filter((e) => !STRUCTURE.has(e.kind));
    if (m.selected && m.follow) entries = entries.filter((e) => involved(e).includes(m.selected) || witnessed(e, m.selected));
    const items = feedItems(entries);
    let lastTime = null;
    const rows = [];
    for (const item of items) {
      if (item.time !== lastTime) {
        rows.push(h("li", { class: "feed-time" }, hhmm(secondOfDay(item.time))));
        lastTime = item.time;
      }
      rows.push(this.item(item, m));
    }
    this.list.replaceChildren(...(rows.length ? rows : [h("li", {}, emptyState("Nothing has happened yet today.", m.selected && m.follow ? `Entries that concern ${m.selected} appear here as the day goes on.` : "Entries appear here as the day goes on."))]));
    // Keep the newest line in view, unless the reader has scrolled up; after layout, since
    // the panel may only now be shown.
    if (this.pinned) requestAnimationFrame(() => (this.list.scrollTop = this.list.scrollHeight));
  }

  item(item, m) {
    const key = `${item.events[0].seq}`;
    const toggle = () => {
      if (this.open.has(key)) this.open.delete(key);
      else this.open.add(key);
      this.update(m, true);
    };
    const opened = this.open.has(key);
    if (item.spell) {
      return h(
        "li",
        { class: "feed-item group" },
        h("button", { type: "button", class: "group-head", "aria-expanded": String(opened), onclick: toggle }, glyph(item.events[0]), h("span", {}, m.cast.mention(item.summary)), icon(opened ? "down" : "chevron", 14)),
        opened ? h("ul", { class: "group-items" }, item.events.map((e) => this.entryLine(e, m))) : null,
      );
    }
    const e = item.event;
    const more = detail(e);
    const personal = e.audience.length === 1 && !e.actor;
    return h(
      "li",
      { class: `feed-item${personal ? " private" : ""}` },
      h("div", { class: "feed-line" }, glyph(e), line(e, m)),
      more ? (more[2] ? h("details", { class: "code" }, h("summary", {}, more[0]), h("pre", {}, more[1])) : h("p", { class: "report" }, more[1])) : null,
    );
  }

  entryLine(e, m) {
    const more = detail(e);
    return h("li", {}, line(e, m), more?.[2] ? h("details", { class: "code" }, h("summary", {}, more[0]), h("pre", {}, more[1])) : null);
  }
}

/** Whether the place `id` is open at the moment: someone whose workplace it is is at work there. */
const serving = (m, id) => m.cast.names.filter((name) => occupationOf(m.world, name).workplace === id && m.state.residents[name].segment?.kind === "work" && m.state.residents[name].segment.place === id);

/** The markers of `kind` on every lane since the lived day began, up to the moment, each with its resident. */
const today = (m, kind) => m.timeline.residents.flatMap((lane) => markersBetween(lane, m.day.start, m.time).filter((mk) => mk.kind === kind).map((mk) => [lane.name, mk]));

/** A small table of rows, each an array of cells, under a header; or a quiet line when empty. */
const table = (head, rows, empty) => (rows.length ? h("div", { class: "table-wrap" }, h("table", { class: "data compact-table" }, h("thead", {}, h("tr", {}, head.map((cell) => h("th", {}, cell)))), h("tbody", {}, rows.map((row) => h("tr", {}, row.map((cell) => h("td", {}, cell))))))) : h("p", { class: "muted small-text" }, empty));

/**
 * Each workplace at the moment, as its door and its books stand: the Office's board (the tasks
 * open, who holds each and since when, and the day's arrivals, acceptances and withdrawals),
 * the Store's shelves, prices and orders, the kitchen's menu and larder, the Hospital's fees,
 * the day's patients and who is ill or in bed, and the Town Hall's board of announcements with
 * the fund as the last checkpoint saved it.
 */
export class WorkPanel {
  constructor() {
    this.el = h("div", { class: "panel work" });
    this.key = null;
  }

  update(m) {
    const key = `${m.time}|${m.selected}|${Boolean(m.measures)}`;
    if (key === this.key) return;
    this.key = key;
    const shops = shopsAt(m.timeline, m.time);
    const goods = new Map(m.world.goods.map((good) => [good.id, good]));
    const dishes = new Map(m.world.dishes.map((dish) => [dish.id, dish]));
    const sections = {
      office: (place) => {
        const tasks = m.timeline.tasks;
        const arrived = tasks.filter((task) => task.arrived > m.day.start && task.arrived <= m.time).length;
        const accepted = tasks.filter((task) => task.accepted !== null && task.accepted > m.day.start && task.accepted <= m.time);
        const withdrawn = tasks.filter((task) => task.withdrawn !== null && task.withdrawn > m.day.start && task.withdrawn <= m.time).length;
        const open = tasks.filter((task) => openAt(task, m.time));
        const rows = open.map((task) => {
          const held = holderAt(task, m.time);
          return [
            h("b", {}, `${task.task}`),
            task.repo,
            held ? [m.cast.mention(held.holder), h("small", { class: "muted" }, ` since ${hhmm(secondOfDay(held.since))}${held.by ? `, given by ${held.by}` : ""}`)] : h("span", { class: "muted" }, "nobody"),
            dateOf(m.timeline.start_date, task.deadline - 1),
          ];
        });
        return [
          h("p", { class: "note" }, `Today ${fmt.plural(arrived, "task")} came in, ${accepted.length} ${accepted.length === 1 ? "was" : "were"} accepted (${accepted.map((task) => `${task.task} by ${task.by}`).join(", ") || "none"}) and ${withdrawn} withdrawn. A client pays the town ${fmt.money(m.world.work.payment)} for a task accepted.`),
          table(["Task", "Repository", "Held by", "Withdrawn after"], rows, "Nothing is open on the board."),
        ];
      },
      store: () => {
        const sold = today(m, "sale");
        const rows = m.world.goods.map((good) => [goodName(good), fmt.int(shops.stock[good.id] ?? 0), fmt.money(shops.prices[good.id]), shops.onOrder[good.id] ? fmt.int(shops.onOrder[good.id]) : ""]);
        const units = sold.reduce((a, [, mk]) => a + mk.quantity, 0);
        return [h("p", { class: "note" }, `Today ${fmt.plural(sold.length, "sale")} of ${fmt.plural(units, "unit")}, ${sold.filter(([, mk]) => mk.kitchen).length} of them for the kitchen.`), table(["Good", "In stock", "Price", "On order"], rows, "The Store sells nothing.")];
      },
      restaurant: () => {
        const served = today(m, "served");
        const menu = m.world.dishes.map((dish) => [goodName(dish), fmt.int(shops.portions[dish.id] ?? 0), fmt.money(shops.menu[dish.id])]);
        const larder = Object.entries(shops.larder).map(([id, units]) => `${units} × ${goodName(goods.get(id)).toLowerCase()}`);
        return [
          h("p", { class: "note" }, `Today ${fmt.plural(served.length, "dish", "dishes")} served${served.length ? `: ${served.map(([name, mk]) => `${dishes.get(mk.dish) ? goodName(dishes.get(mk.dish)).toLowerCase() : mk.name} to ${name}`).join(", ")}` : ""}. The kitchen holds ${larder.join(", ") || "nothing"}.`),
          table(["Dish", "Ready", "Price"], menu, "The kitchen cooks nothing."),
        ];
      },
      hospital: () => {
        const seen = [...today(m, "examination"), ...today(m, "treatment")].sort((a, b) => a[1].t - b[1].t);
        const ill = m.cast.names.filter((name) => illAt(m.state.residents[name].lane, m.time));
        const abed = m.cast.names.filter((name) => m.state.residents[name].segment?.kind === "bedridden");
        return [
          h("p", { class: "note" }, `An examination costs ${fmt.money(shops.fees.examination)}, a treatment ${fmt.money(shops.fees.treatment)}. Ill now: ${ill.join(", ") || "nobody"}; in bed: ${abed.join(", ") || "nobody"}.`),
          seen.length ? h("ul", { class: "outcomes" }, seen.map(([name, mk]) => h("li", {}, h("span", { class: "muted" }, `${hhmm(secondOfDay(mk.t))} `), m.cast.mention(`${name} ${describeMarker(mk, name, name)[0]}`)))) : h("p", { class: "muted small-text" }, "Nobody seen today."),
        ];
      },
      hall: () => {
        const said = m.timeline.residents.flatMap((lane) => markersBetween(lane, null, m.time).filter((mk) => mk.kind === "announcement").map((mk) => [lane.name, mk])).reverse();
        const reports = today(m, "report").length;
        // The fund as the last checkpoint before the moment saved it, from the town's days.
        const closed = m.timeline.days.filter((day) => day.end !== null && day.end <= m.time).map((day) => day.day);
        const fund = m.measures?.town.filter((row) => closed.includes(row.day)).at(-1);
        const owing = (field) => (fund ? m.measures.rows.filter((row) => row.day === fund.day && row[field]).map((row) => `${row.resident} ${fmt.money(row[field])}`) : []);
        const books = fund ? `The fund held ${fmt.money(fund.fund)} at the checkpoint of day ${fund.day}${owing("owed_wages").length ? `, owing ${owing("owed_wages").join(", ")}` : ""}${owing("arrears").length ? `; owed rent by ${owing("arrears").join(", ")}` : ""}. ` : "";
        return [
          h("p", { class: "note" }, `${books}The report was read ${fmt.plural(reports, "time")} today.`),
          said.length ? h("ul", { class: "outcomes" }, said.slice(0, 6).map(([name, mk]) => h("li", {}, h("span", { class: "muted" }, `${dateOf(m.timeline.start_date, mk.t)} ${hhmm(secondOfDay(mk.t))}, ${name}: `), `“${mk.text}”`))) : h("p", { class: "muted small-text" }, "Nothing is posted on the board."),
        ];
      },
    };
    fill(
      this.el,
      WORKPLACES.map((kind) => {
        const place = placeOfKind(m.world, kind);
        const staff = serving(m, place.id);
        return h(
          "section",
          { class: "workplace" },
          h("h3", { class: "workplace-head" }, h("span", {}, shortName(place)), h("span", { class: `pill ${staff.length ? "open" : "shut"}` }, staff.length ? `open · ${staff.join(", ")}` : "closed")),
          sections[kind](place),
        );
      }),
    );
  }
}

/** The kinds of entry the chronicle keeps, each a moment worth finding. */
const NOTABLE = new Set(["task_arrived", "task_withdrawn", "claim", "assign", "verdict", "abandon", "gift", "message", "order", "delivery", "cook", "price", "examination", "treatment", "announcement", "illness", "recovered", "bedridden", "move_in", "sleep", "forced_sleep"]);

/** The day so far in its notable moments; each one jumps there. */
export class ChroniclePanel {
  constructor({ onJump }) {
    this.el = h("div", { class: "panel chronicle" });
    this.onJump = onJump;
    this.key = null;
  }

  update(m) {
    const key = `${m.time}|${m.reader}|${m.dayEntries.length}`;
    if (key === this.key) return;
    this.key = key;
    const notes = m.dayEntries.filter((e) => NOTABLE.has(e.kind) || (e.kind === "speech" && e.payload.private) || (e.kind === "condition" && e.payload.lowest));
    fill(
      this.el,
      h("p", { class: "note" }, `Day ${m.day.day} up to ${hhmm(secondOfDay(m.time))}, in its notable moments. Pick one to go there.`),
      notes.length
        ? h(
            "ol",
            { class: "chronicle-list" },
            notes.map((e) => h("li", { class: tone(e) && tone(e) !== "good" ? tone(e) : "" }, h("button", { type: "button", class: "linkish", onclick: () => this.onJump(e.sim_time) }, h("span", { class: "chron-time" }, clockOf(e)), h("span", {}, glyph(e), " ", line(e, m))))),
          )
        : emptyState("Nothing notable yet today.", "Tasks coming in, claimed, given and handed in, orders and deliveries, cooking, the doctor's patients, announcements, illness and bedtimes appear here as they happen."),
    );
  }
}
