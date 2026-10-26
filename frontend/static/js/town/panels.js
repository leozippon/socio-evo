// The town's panels. Each renders one moment: `m` holds the moment of the timeline (where
// everyone is and what each is in), the day's entries up to that moment, who is selected and
// whose wording is read.

import { hhmm, secondOfDay } from "../clock.js";
import { emptyState, fill, fmt, h } from "../dom.js";
import { icon } from "../icons.js";
import { markersBetween } from "../replay.js";
import { EVENTS, shortName } from "../world.js";
import { STRUCTURE, clockOf, detail, feedItems, glyph, involved, line, textFor, witnessed } from "./events.js";

const RECENT = 30 * 60; // seconds of speech the moment panel keeps in view

/** A resident's doing in a few words: at work on a task, talking, on the way, asleep, idle. */
export function doing(found, places) {
  const { segment, conversation, moving, held } = found;
  if (!segment) return "";
  if (moving) return `on the way to ${places.get(moving.to) ? shortName(places.get(moving.to)) : moving.to}`;
  const bits = [];
  if (conversation) bits.push(`talking with ${conversation.with.join(", ")}`);
  if (segment.kind === "work") bits.push(held ? `at work on task ${held.task}` : "at work, no task");
  else if (segment.kind === "sleep") bits.push("asleep");
  else if (!conversation) bits.push("idle");
  if (segment.kind !== "work" && held) bits.push(`holds task ${held.task}`);
  return bits.join(" · ");
}

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

/** The moment: who is where and what each is in, and what was said lately. */
export class NowPanel {
  constructor() {
    this.el = h("div", { class: "panel now" });
    this.key = null;
  }

  update(m) {
    const key = `${m.time}|${m.selected}|${m.reader}|${m.dayEntries.length}`;
    if (key === this.key) return;
    this.key = key;
    const where = byPlace(m);
    const places = m.world.places.filter((place) => where.has(place.id));
    const moving = where.get(null) ?? [];
    const recent = m.dayEntries.filter((e) => e.kind === "speech" && e.sim_time >= m.time - RECENT).slice(-6);
    fill(
      this.el,
      h("div", { class: "now-head" }, h("h3", {}, m.phase)),
      places.length || moving.length
        ? h(
            "ul",
            { class: "scenes" },
            places.map((place) =>
              h(
                "li",
                {},
                h("span", { class: "scene-name" }, h("b", {}, shortName(place)), h("span", { class: "muted" }, ` · ${fmt.plural(where.get(place.id).length, "person", "people")}`)),
                h("span", { class: "present" }, where.get(place.id).map((name) => m.cast.badge(name, 16))),
                h("span", { class: "sr" }, where.get(place.id).join(", ")),
              ),
            ),
            moving.length ? h("li", {}, h("span", { class: "scene-name" }, h("b", {}, "On the way")), h("span", { class: "present" }, moving.map((name) => m.cast.badge(name, 16)))) : null,
          )
        : emptyState("Nobody is anywhere yet.", "The residents appear as the run records its first entries."),
      h(
        "ul",
        { class: "doings" },
        m.cast.names.map((name) => {
          const found = m.state.residents[name];
          return h(
            "li",
            { class: m.selected === name ? "on" : "" },
            h("button", { type: "button", class: "linkish", onclick: () => m.select(name) }, m.cast.badge(name, 18), h("b", {}, name)),
            h("span", { class: "muted" }, ` ${doing(found, m.places)}`),
          );
        }),
      ),
      h("p", { class: "turn-label" }, recent.length ? "Said lately" : "Nothing said lately"),
      recent.length ? h("ul", { class: "outcomes" }, recent.map((e) => h("li", {}, glyph(e), h("span", { class: "muted" }, `${clockOf(e)} `), line(e, m)))) : null,
    );
  }
}

/** The people of the town at the moment: where each is, what it holds, how it fares. */
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
      h(
        "ul",
        { class: "people-list" },
        m.cast.names.map((name) => {
          const found = m.state.residents[name];
          const place = found.moving ? null : m.places.get(found.segment?.place);
          const delta = found.purse - m.dayStartPurses[name];
          return h(
            "li",
            {},
            h(
              "button",
              { type: "button", class: `person-row${m.selected === name ? " on" : ""}`, "aria-pressed": String(m.selected === name), onclick: () => m.select(name) },
              m.cast.badge(name, 28),
              h("span", { class: "person-main" }, h("b", {}, name), h("span", { class: "muted" }, place ? shortName(place) : found.moving ? "on the way" : ""), h("span", { class: "person-job" }, doing(found, m.places))),
              h(
                "span",
                { class: "person-figures" },
                h("span", { class: `money${found.purse < 0 ? " debt" : ""}`, title: "Money, and its change since the day began" }, fmt.money(found.purse), delta ? h("small", { class: delta > 0 ? "up" : "down" }, ` ${fmt.signed(delta)}`) : null),
                h("span", { class: "esteem", title: "The event the resident is in" }, EVENTS[found.conversation ? "conversation" : found.segment?.kind] ?? ""),
              ),
            ),
          );
        }),
      ),
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
    let entries = m.dayEntries.filter((e) => !STRUCTURE.has(e.kind) || e.kind === "board_posted");
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
    if (e.kind === "board_posted") return h("li", { class: "feed-scene" }, h("span", {}, textFor(e, m.reader)));
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

/** The work of the day at the moment: what each resident holds, has handed in and was paid. */
export class WorkPanel {
  constructor() {
    this.el = h("div", { class: "panel board" });
    this.key = null;
  }

  update(m) {
    const key = `${m.time}|${m.selected}`;
    if (key === this.key) return;
    this.key = key;
    const start = m.day.start;
    const totals = { claims: 0, accepted: 0, rejected: 0, paid: 0, abandoned: 0, expired: 0 };
    const rows = m.cast.names.map((name) => {
      const found = m.state.residents[name];
      const markers = markersBetween(found.lane, start, m.time);
      const handed = markers.filter((mk) => mk.kind === "submission");
      const paid = markers.filter((mk) => mk.kind === "payment");
      const lost = markers.filter((mk) => mk.kind === "abandon" || mk.kind === "expiry");
      totals.claims += markers.filter((mk) => mk.kind === "claim").length;
      totals.accepted += handed.filter((mk) => mk.resolved === true).length;
      totals.rejected += handed.filter((mk) => mk.resolved === false).length;
      totals.paid += paid.reduce((a, mk) => a + mk.amount, 0);
      totals.abandoned += lost.filter((mk) => mk.kind === "abandon").length;
      totals.expired += lost.filter((mk) => mk.kind === "expiry").length;
      return h(
        "li",
        { class: `task${m.selected === name ? " claimed" : ""}` },
        h(
          "div",
          { class: "task-head static" },
          h("span", { class: "task-reward" }, fmt.int(paid.length), h("small", {}, "paid")),
          h(
            "span",
            { class: "task-title" },
            h("button", { type: "button", class: "linkish", onclick: () => m.select(name) }, m.cast.badge(name, 16), h("b", {}, name)),
            h("span", { class: "task-meta" }, found.held ? h("span", { class: "muted" }, `holds task ${found.held.task} (${found.held.instance_id}) since ${hhmm(secondOfDay(found.held.since))}`) : h("span", { class: "muted" }, "holds no task")),
            handed.length || lost.length
              ? h(
                  "span",
                  { class: "parts" },
                  handed.map((mk) => h("span", { class: `part-chip${mk.resolved === true ? " in" : mk.resolved === false ? " missing" : ""}`, title: mk.resolved === undefined ? "awaiting the verdict" : mk.status }, `task ${mk.task}`, h("small", {}, mk.resolved === undefined ? "pending" : mk.resolved ? "accepted" : "not accepted"))),
                  lost.map((mk) => h("span", { class: "part-chip missing" }, `task ${mk.task}`, h("small", {}, mk.kind === "abandon" ? "given up" : "ran out"))),
                )
              : null,
          ),
        ),
      );
    });
    fill(
      this.el,
      h("p", { class: "note" }, `Day ${m.day.day} up to ${hhmm(secondOfDay(m.time))}: ${fmt.plural(totals.claims, "claim")}, ${totals.accepted} accepted, ${totals.rejected} not accepted, ${fmt.money(totals.paid)} paid${totals.abandoned ? `, ${totals.abandoned} given up` : ""}${totals.expired ? `, ${totals.expired} ran out` : ""}. Each task pays ${fmt.money(m.world.work.payment)} once accepted; everyone holds at most one.`),
      h("ul", { class: "tasks" }, rows),
    );
  }
}

/** The kinds of entry the chronicle keeps, each a moment worth finding. */
const NOTABLE = new Set(["wake", "claim", "verdict", "payment", "abandon", "expiry", "gift", "message", "purchase", "move_in", "skill_shared", "rating", "sleep", "forced_sleep", "exchange_pairing", "meeting", "settlement", "hungry"]);

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
    const notes = m.dayEntries.filter((e) => NOTABLE.has(e.kind) || (e.kind === "speech" && e.payload.private));
    const classOf = (e) => ({ good: "", serious: "serious", critical: "critical", warn: "warn" })[({ verdict: e.payload.resolved ? "good" : "serious", abandon: "serious", expiry: "critical", forced_sleep: "critical" })[e.kind]] ?? "";
    const broke = Object.entries(m.state.residents).filter(([, found]) => found.purse < 0);
    fill(
      this.el,
      h("p", { class: "note" }, `Day ${m.day.day} up to ${hhmm(secondOfDay(m.time))}, in its notable moments. Pick one to go there.`),
      notes.length
        ? h(
            "ol",
            { class: "chronicle-list" },
            notes.map((e) => h("li", { class: classOf(e) }, h("button", { type: "button", class: "linkish", onclick: () => this.onJump(e.sim_time) }, h("span", { class: "chron-time" }, clockOf(e)), h("span", {}, glyph(e), " ", line(e, m))))),
          )
        : emptyState("Nothing notable yet today.", "Wakings, claims, verdicts, payments, gifts, ratings and bedtimes appear here as they happen."),
      broke.length ? h("p", { class: "note" }, "In debt: ", broke.map(([name, found], i) => [i ? ", " : "", m.cast.mention(name), ` ${fmt.money(found.purse)}`])) : null,
    );
  }
}
