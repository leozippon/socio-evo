// One resident, as of a moment: who they are and what they do, how many like them, how they
// fared at work and with money, what they took and paid for, their day as they perceived it (what
// they did and what the world told them, and nothing else), their journal, what they kept and
// learnt each night, their files as the git repository holds them (every version, with what
// changed, and the memory and skills they then had), and the raw trace of their runtime.

import { DayChart, figure } from "../charts.js";
import { dateOf, hhmm, livedDay, parseStamp, secondOfDay, stamp } from "../clock.js";
import { parseDiff, renderFile } from "../diff.js";
import { append, emptyState, fill, fmt, h } from "../dom.js";
import { inventory, needBars } from "../goods.js";
import { icon } from "../icons.js";
import { liked } from "../identity.js";
import { markdown } from "../markdown.js";
import { bodyAt, illAt, isGift, markersBetween, moneyMoved, moneySince, namesOf, paidShort, pricedTake, purseAt, regardAt, settlementAt, thingsAt, tookFromPerson } from "../replay.js";
import { href, sibling } from "../router.js";
import { detail, feedItems, glyph, line, midnightMoney, perceived } from "../town/events.js";
import { jobOf, placeById } from "../world.js";
import { LEVELS, LOWER, percent } from "./evaluation.js";
import { areasOf, stat } from "./overview.js";

const TABS = [
  ["overview", "Overview"],
  ["day", "Day"],
  ["journal", "Journal"],
  ["nights", "Nights"],
  ["files", "Files"],
  ["trace", "Trace"],
];
const LONG = 700; // characters of a trace text shown before the rest folds
const AREA_LABEL = { memory: "memory", skills: "skills", journal: "journal", background: "background" };
/** The parts of the money line (`moneySince`), in the order it tells them, with their words. */
const MONEY_PARTS = [
  ["salary", "salary"],
  ["rent", "rent"],
  ["share", "from clients"],
  ["granted", "granted"],
  ["received", "given it"],
  ["given", "given"],
  ["left", "left"],
  ["took", "taken"],
  ["taken", "taken from it"],
  ["dropped", "dropped"],
  ["orders", "in orders"],
];

export function mountPerson(root, ctx) {
  const { source, world, cast } = ctx;
  let route = ctx.route;
  const places = placeById(world);
  const page = h("div", { class: "page person" });
  root.append(page);
  let data = null;
  let measures = null;
  let evaluation = null;
  let history = null;
  let charts = [];
  let token = 0;

  const agentName = () => route.agent;
  const tab = () => (TABS.some(([key]) => key === route.query.tab) ? route.query.tab : "overview");
  const lane = () => data.residents.find((r) => r.name === agentName());

  /** The moment shown: the time in the URL, or the newest; its lived day. */
  function asOf() {
    const time = parseStamp(route.query.t);
    const t = time === null ? data.now : Math.max(data.start, Math.min(data.now, time));
    return { time: t, day: livedDay(data.days, t), latest: time === null };
  }

  const go = (query) => {
    route = { ...route, query: { ...route.query, ...query } };
    ctx.remember(route);
    render();
  };

  const endOf = (day) => day.end ?? data.now;

  function head(moment) {
    const me = cast.agent(agentName());
    const home = places.get(me.home);
    const regard = regardAt(data, moment.time);
    const index = data.days.findIndex((d) => d === moment.day);
    const dayLink = (i) => {
      const day = data.days[i];
      go({ t: day.end === null ? null : stamp(day.end) });
    };
    return h(
      "section",
      { class: "person-head" },
      h(
        "nav",
        { class: "people-switch", "aria-label": "People" },
        cast.names.map((name) => h("a", { class: `person-pick${name === agentName() ? " on" : ""}`, href: href({ ...route, agent: name }), "aria-current": name === agentName() ? "page" : null }, cast.badge(name, 18), name)),
      ),
      h(
        "div",
        { class: "identity" },
        cast.badge(me.name, 52),
        h(
          "div",
          { class: "identity-text" },
          h("h1", {}, me.name, cast.newcomer(me.name) ? h("span", { class: "new-tag" }, "newcomer") : null),
          h("p", { class: "identity-meta" }, liked(regard.shown[me.name], regard.before?.[me.name] ?? null), ` · ${jobOf(world, me.name)} · lives at ${home ? home.name : me.home} · started with ${fmt.money(me.purse)} · ${world.name}`),
        ),
      ),
      h(
        "div",
        { class: "as-of" },
        h("span", { class: "eyebrow" }, "As of"),
        h(
          "div",
          { class: "as-of-step" },
          h("button", { type: "button", class: "icon-btn", "aria-label": "One day earlier", disabled: index <= 0, onclick: () => dayLink(index - 1) }, icon("chevronLeft", 18)),
          h("b", {}, `${moment.day.end !== null && moment.time === moment.day.end ? `End of day ${moment.day.day}` : `Day ${moment.day.day}`} · ${dateOf(data.start_date, moment.time)}, ${hhmm(secondOfDay(moment.time))}`),
          h("button", { type: "button", class: "icon-btn", "aria-label": "One day later", disabled: index >= data.days.length - 1, onclick: () => dayLink(index + 1) }, icon("chevron", 18)),
        ),
        moment.latest ? h("span", { class: "muted small-text" }, "the newest moment") : h("button", { type: "button", class: "quiet small", onclick: () => go({ t: null }) }, "Newest"),
        h("a", { class: "ghost small as-of-town", href: href(sibling({ ...route, query: { t: stamp(moment.time) } }, "town", { query: { agent: agentName() } })) }, icon("map", 15), "See in town"),
      ),
      h(
        "nav",
        { class: "subnav", "aria-label": `${me.name}'s story` },
        TABS.map(([key, label]) => h("a", { href: href({ ...route, query: { ...route.query, tab: key === "overview" ? null : key, v: null, day: null, night: null } }), "aria-selected": String(tab() === key) }, label)),
      ),
    );
  }

  /** A chart over lived days with this resident emphasised and the others in grey. */
  function emphasisChart(title, note, valueAt, format, options, moment, made) {
    const days = data.days.filter((d) => d.start <= moment.time);
    const lines = data.residents.map((r) => ({
      key: r.name,
      label: r.name,
      color: cast.color(r.name),
      glyph: (radius) => cast.glyph(r.name, radius),
      faint: r.name !== agentName(),
      points: days.map((d) => [d.day, valueAt(r, Math.min(endOf(d), moment.time), d)]),
    }));
    const me = lines.find((l) => l.key === agentName());
    const chart = new DayChart({ days: [1, Math.max(1, days.at(-1)?.day ?? 1)], lines: [...lines.filter((l) => l !== me), me], y: { format, ...options }, cursor: moment.day.day + 0.5, height: 150, endLabels: true, dots: true, label: title });
    made.push(chart);
    return figure({ title, note, chart });
  }

  /** Hours a lane spent in Work from `from` to `to`. */
  const hoursAtWork = (lane, from, to) => lane.segments.filter((seg) => seg.kind === "work" && seg.end > from && seg.start < to).reduce((a, seg) => a + (Math.min(seg.end, to) - Math.max(seg.start, from)), 0) / 3600;

  function overview(moment, made) {
    const me = lane();
    const name = agentName();
    const residents = namesOf(data);
    const mine = markersBetween(me, null, moment.time);
    const count = (kind) => mine.filter((m) => m.kind === kind).length;
    const sumOf = (kind, field, keep = () => true) => mine.filter((m) => m.kind === kind && keep(m)).reduce((a, m) => a + m[field], 0);
    const ties = new Map();
    const tie = (other) => ties.get(other) ?? ties.set(other, { minutes: 0, toThem: 0, fromThem: 0, moneyTo: 0, moneyFrom: 0, took: 0, tookBy: 0 }).get(other);
    for (const edge of measures.graph) {
      if (edge.day > moment.day.day) continue;
      if (edge.source === name) {
        const t = tie(edge.target);
        t.minutes += edge.minutes;
        t.toThem += edge.said;
        t.moneyTo += edge.money;
        t.took += edge.took;
      } else if (edge.target === name) {
        const t = tie(edge.source);
        t.fromThem += edge.said;
        t.moneyFrom += edge.money;
        t.tookBy += edge.took;
      }
    }
    const abed = me.segments.some((seg) => seg.kind === "bedridden" && seg.start <= moment.time && moment.time <= seg.end);
    const ill = illAt(me, moment.time);
    const levels = evaluation.levels.filter((row) => row.resident === name);
    const midnight = settlementAt(me, moment.time);
    // The money since the last midnight statement (or the start), part by part: what the purse held
    // before the statement, its salary and rent, and every sum since; together they make the money
    // it holds.
    const { settled, start, parts } = moneySince(data, name, moment.time);
    const moneyLine = [`${fmt.money(start)} ${settled ? "at the last midnight" : "at the start"}`, ...MONEY_PARTS.filter(([part]) => parts[part]).map(([part, words]) => `${parts[part] > 0 ? "+" : "−"}${fmt.money(Math.abs(parts[part]))} ${words}`)].join(" · ");
    // What it was paid so far, after the tax: its shares of the clients' payments and the money
    // others gave it, payments for its work among it, from every lane.
    const earnings = data.residents.flatMap((r) => markersBetween(r, null, moment.time).flatMap((m) => moneyMoved(m, r.name, residents).filter(([who, , part]) => who === name && (part === "share" || part === "received")).map(([, change]) => [m, change])));
    const earned = earnings.reduce((a, [, change]) => a + change, 0);
    const taxed = earnings.reduce((a, [m]) => a + m.tax, 0);
    const shares = earnings.filter(([m]) => m.kind === "service").length;
    const given = earnings.length - shares;
    const regard = regardAt(data, moment.time);
    const fromPeople = mine.filter(tookFromPerson);
    const priced = mine.filter(pricedTake);
    const short = priced.filter(paidShort);
    const unread = priced.filter((m) => m.status === null).length;
    const takenFrom = data.residents.flatMap((r) => markersBetween(r, null, moment.time).filter((m) => tookFromPerson(m) && m.source === name));
    const moved = midnight ? Object.entries(midnight.night).map(([cause, change]) => `${fmt.signed(change)} ${{ starving: "for a day ended starving", exhausted: "for a day ended exhausted", poor_home: "for a home of little comfort", recovery: "for a day fed and rested", illness: "for illness" }[cause] ?? cause}`) : [];
    return [
      h("p", { class: "note" }, `How ${name} has fared up to the moment shown: how many of the others like it, its money and work, what it took and paid for, and with whom it had to do. The other tabs hold the day as the world told it, every journal entry, what it kept each night, the files at every version, and the raw trace of the runtime.`),
      h(
        "div",
        { class: "stats" },
        stat("Liked by", fmt.int(regard.shown[name]), regard.before ? `of the others today · ${fmt.int(regard.before[name])} the day before` : "of the others, at the start"),
        stat("Money", fmt.money(purseAt(me, moment.time)), moneyLine),
        stat("Earned", fmt.money(earned), `${[shares ? fmt.plural(shares, "share") + " of clients' payments" : null, given ? fmt.plural(given, "time") + " given money by others" : null].filter(Boolean).join(" · ") || "nothing paid it yet"}${taxed ? ` · ${fmt.money(taxed)} withheld in tax` : ""}`),
        stat("Took from others", fmt.int(fromPeople.length), `${fmt.int(fromPeople.filter((m) => m.from === "asleep").length)} of them asleep · taken from ${fmt.plural(takenFrom.length, "time")}`, fromPeople.length ? "critical" : ""),
        stat("Priced takes", fmt.int(priced.length), `${fmt.int(short.length)} not paid for in full${unread ? ` · ${fmt.int(unread)} not read until the day's end` : ""}`, short.length ? "serious" : ""),
        stat("Hours at work", fmt.num(hoursAtWork(me, data.start, moment.time), 1), `at its workplace · ${fmt.money(sumOf("settlement", "rent_paid"))} of rent paid at midnight`),
        stat("Things said", fmt.int(count("speech")), `${fmt.int(count("message"))} written · ${fmt.plural(mine.filter((m) => isGift(m, residents)).length, "gift")} given`),
        stat("Journals written", fmt.int(count("journal")), `at bedtime · ${fmt.int(count("forced_sleep"))} forced sleeps`),
      ),
      h(
        "div",
        { class: "two-col" },
        h(
          "section",
          { class: "card pad life-card" },
          h("h2", {}, abed ? "In bed" : "How they are"),
          abed ? h("p", { class: "note critical-text" }, "Health ran out at midnight: in bed at home, too ill to get up, until the doctor treats them at their bedside.") : null,
          h("p", { class: "note" }, `Food in the body, energy and health, each read in the bands the town tells; a bar fills to the band's top, and hovering it gives the last number the world told.${ill ? " Ill now, which others cannot see." : ""}`),
          needBars(world, bodyAt(me, moment.time)),
          midnight
            ? h("p", { class: "note midnight-note" }, `Last midnight: ${midnightMoney(midnight)} Ate ${midnight.nourishment ? `${fmt.int(midnight.nourishment)}% of a day's food` : "nothing"}; health ${moved.length ? moved.join(", ") : "unchanged"}.`)
            : h("p", { class: "note midnight-note" }, "No midnight statement yet: the first comes at the end of the first day."),
        ),
        h(
          "section",
          { class: "card pad life-card" },
          h("h2", {}, "What they carry"),
          h("p", { class: "note" }, `Money first, as the inventory tells it. A stock of food is eaten as its owner gets hungry, and a dish where it is taken; every move in and out is counted.`),
          inventory(world, thingsAt(me, moment.time), { money: purseAt(me, moment.time) }),
        ),
      ),
      h(
        "div",
        { class: "figures" },
        emphasisChart("Liked by", "How many of the others liked each resident, the number everyone saw on it, each lived day; the others in grey.", (r, t, d) => regardAt(data, d.start).shown[r.name], fmt.int, { zero: true }, moment, made),
        emphasisChart("Money in hand", "At the end of each lived day; the others in grey.", (r, t) => purseAt(r, t), fmt.int, { zero: true }, moment, made),
        emphasisChart("Hours at work", "Per lived day.", (r, t, d) => hoursAtWork(r, d.start, t), (v) => fmt.num(v, 1), { zero: true }, moment, made),
      ),
      h(
        "div",
        { class: "two-col section" },
        h(
          "section",
          { class: "card pad" },
          h("h2", {}, "Relationships"),
          h("p", { class: "note" }, `Through day ${moment.day.day}.`),
          ties.size
            ? h(
                "div",
                { class: "table-wrap" },
                h(
                  "table",
                  { class: "data" },
                  h("thead", {}, h("tr", {}, h("th", { class: "sticky-col" }, "With"), h("th", { title: "Minutes in conversations they took part in" }, "Minutes"), h("th", { title: "Things said that they heard" }, "Said to"), h("th", { title: "Things they said that this resident heard" }, "Heard from"), h("th", { title: "Money given to them, and received from them, payments among it" }, "Money to / from"), h("th", { title: "Times this resident took from what they carried, and they from it" }, "Took / taken"))),
                  h(
                    "tbody",
                    {},
                    [...ties]
                      .sort((a, b) => b[1].minutes - a[1].minutes)
                      .map(([other, t]) =>
                        h("tr", {}, h("td", { class: "sticky-col" }, cast.chip(other, href({ ...route, agent: other }))), h("td", {}, fmt.int(Math.round(t.minutes))), h("td", {}, fmt.int(t.toThem)), h("td", {}, fmt.int(t.fromThem)), h("td", {}, `${fmt.money(t.moneyTo)} / ${fmt.money(t.moneyFrom)}`), h("td", { class: t.took ? "critical-text" : "" }, `${fmt.int(t.took)} / ${fmt.int(t.tookBy)}`)),
                      ),
                  ),
                ),
              )
            : emptyState("No one yet.", `${name} has had nothing to do with anyone so far.`),
        ),
        h(
          "section",
          { class: "card pad" },
          h("h2", {}, "Evaluation"),
          h("p", { class: "note" }, "The benchmarks put to this resident's weights after the night of each day evaluated; day 0 is the base model, before any night. Each a share of the items, never one score; beside harmful compliance and jailbreak success, their lower readings, the answers labelled Unsafe alone."),
          levels.length
            ? h(
                "div",
                { class: "table-wrap" },
                h(
                  "table",
                  { class: "data" },
                  h("thead", {}, h("tr", {}, h("th", {}, "Day"), LEVELS.map(([, label]) => h("th", {}, label)))),
                  h(
                    "tbody",
                    {},
                    [...new Set(levels.map((row) => row.day))]
                      .sort((a, b) => a - b)
                      .map((day) => {
                        const level = (measure) => percent(levels.find((row) => row.day === day && row.measure === measure)?.level);
                        return h("tr", {}, h("th", { scope: "row" }, String(day)), LEVELS.map(([measure]) => h("td", {}, level(measure), LOWER[measure] ? h("small", { class: "lower" }, ` · lower ${level(LOWER[measure])}`) : null)));
                      }),
                  ),
                ),
              )
            : emptyState("Not evaluated yet.", "Harmful compliance, jailbreak success, harmless compliance and lying appear once this resident's weights are scored and the run is published again."),
          h("a", { class: "quiet small", href: href(sibling(route, "evaluation", { query: { agent: name } })) }, "The evaluation", icon("chevron", 14)),
        ),
      ),
      h("details", { class: "card pad rules-text fold" }, h("summary", {}, `The rules ${name} was told`), h("pre", {}, cast.agent(name).rules)),
    ];
  }

  async function dayTab(moment) {
    const picked = Number(route.query.day);
    const day = data.days.find((d) => d.day === picked) ?? moment.day;
    const index = data.days.indexOf(day);
    const entries = source.doc.event_days.some((found) => found.day === day.day) ? await source.eventDay(day.day) : [];
    const mine = entries.filter((e) => perceived(e, agentName()));
    const m = { cast, reader: agentName() };
    const items = feedItems(mine);
    const picker = h(
      "div",
      { class: "row" },
      h("button", { type: "button", class: "icon-btn", disabled: index <= 0, "aria-label": "Previous day", onclick: () => go({ day: String(data.days[index - 1].day) }) }, icon("chevronLeft", 18)),
      h("b", {}, `Day ${day.day} · ${dateOf(data.start_date, day.start + 3600 * 4)}`),
      h("button", { type: "button", class: "icon-btn", disabled: index >= data.days.length - 1, "aria-label": "Next day", onclick: () => go({ day: String(data.days[index + 1].day) }) }, icon("chevron", 18)),
      h("span", { class: "muted" }, `${fmt.plural(mine.length, "entry", "entries")}${day.end === null ? (source.doc.status === "running" ? ", the day in progress" : ", the day the run stopped in") : ""}`),
    );
    return [
      h("div", { class: "spread" }, h("p", { class: "note" }, `What ${agentName()} perceived on the day, and nothing else: what it did and every entry the world told it, in its own wording, spells of work in the workspace folded into one line each.`), picker),
      items.length
        ? h(
            "ol",
            { class: "card day-feed" },
            items.map((item) => {
              if (item.spell) return h("li", { class: "feed-item" }, h("div", { class: "feed-line" }, glyph(item.events[0]), h("span", {}, cast.mention(item.summary))), h("details", { class: "code" }, h("summary", {}, `${fmt.plural(item.events.length, "entry", "entries")}`), h("ul", { class: "group-items" }, item.events.map((e) => h("li", {}, line(e, m))))));
              const e = item.event;
              const more = detail(e);
              return h(
                "li",
                { class: "feed-item" },
                h("div", { class: "feed-line" }, h("span", { class: "feed-when" }, hhmm(secondOfDay(e.sim_time))), glyph(e), line(e, m), h("a", { class: "quiet small", href: href(sibling({ ...route, query: { t: stamp(e.sim_time) } }, "town", { query: { agent: agentName() } })), title: "Watch this moment in the town" }, icon("map", 13))),
                more ? (more[2] ? h("details", { class: "code" }, h("summary", {}, more[0]), h("pre", {}, more[1])) : h("div", { class: "diary-text" }, markdown(more[1]))) : null,
              );
            }),
          )
        : h("div", { class: "card" }, emptyState(`${agentName()} perceived nothing on day ${day.day}.`, day.end === null ? "Entries appear here as the day goes on." : "This resident did nothing the log records that day, and the world told it nothing.")),
    ];
  }

  function journalTab() {
    const me = lane();
    const journals = me.markers.filter((m) => m.kind === "journal").reverse();
    return [
      h("p", { class: "note" }, `Every journal entry ${agentName()} wrote going to bed, as the world log keeps it, newest first. The file of the date in its memory starts with the same text, but the resident may rewrite it later.`),
      journals.length
        ? h(
            "div",
            { class: "diary" },
            journals.map((m, i) =>
              h(
                "details",
                { class: "diary-entry", open: i === 0 },
                h("summary", {}, h("b", {}, `Day ${livedDay(data.days, m.t).day}`), h("span", { class: "muted" }, ` · to bed at ${hhmm(secondOfDay(m.t))}, to wake at ${hhmm(secondOfDay(m.wake))}`)),
                h("div", { class: "diary-text" }, markdown(m.text)),
              ),
            ),
          )
        : h("div", { class: "card" }, emptyState("No journal entry yet.", `An entry is written on going to bed, if ${agentName()} gives one; a night passed at the forced hour leaves none.`)),
    ];
  }

  /** A message of an example, as the trainer reads it: who says it, and what. */
  function exampleMessage(msg) {
    const calls = msg.tool_calls?.length ? h("ul", { class: "trace-calls" }, msg.tool_calls.map((call) => h("li", {}, h("code", {}, call.function?.name ?? call.name), " ", h("span", { class: "muted mono small-text" }, JSON.stringify(call.function?.arguments ?? call.arguments))))) : null;
    const role = { user: "said to it", assistant: "it answered", tool: "what that came to", system: "standing words" }[msg.role] ?? msg.role;
    return h("div", { class: `trace-message role-${msg.role}` }, h("span", { class: "trace-role" }, role), msg.content ? traceText(String(msg.content), { mono: msg.role === "tool", open: true }) : null, calls);
  }

  /** One moment kept on a night: when, why, the moment as lived beside what was learnt of it. */
  function keptMoment(kept) {
    const when = `${dateOf(data.start_date, kept.start)}, ${hhmm(secondOfDay(kept.start))}–${hhmm(secondOfDay(kept.end))}`;
    const learnt = kept.example
      ? h("div", { class: "kept-side" }, h("h3", {}, "What was learnt"), h("div", { class: "trace-messages" }, kept.example.map(exampleMessage)))
      : h("div", { class: "kept-side dropped" }, h("h3", {}, "Dropped"), h("p", { class: "note" }, `${{ leaked: "Its restatement still named the town", unreadable: "Its restatement could not be read", "too long": "It was longer than the trainer takes" }[kept.dropped.reason] ?? kept.dropped.reason}: ${kept.dropped.detail}.`));
    return h(
      "li",
      { class: "card pad kept" },
      h("header", { class: "spread" }, h("b", {}, `Moment ${kept.moment} · day ${kept.day}`), h("a", { class: "quiet small", href: href(sibling({ ...route, query: { t: stamp(kept.start) } }, "town", { query: { agent: agentName() } })), title: "Watch this moment in the town" }, when, icon("map", 13))),
      h("p", { class: "kept-why" }, kept.why ? `Kept because: “${kept.why}”` : "No reason given."),
      h("div", { class: "kept-pair" }, h("div", { class: "kept-side" }, h("h3", {}, "As it was lived"), traceText(kept.lived)), learnt),
    );
  }

  async function nightsTab(moment, made) {
    const nights = source.doc.residents.find((r) => r.name === agentName())?.nights ?? [];
    const lead = h("p", { class: "note" }, `What ${agentName()} kept of its life each night, after going to bed: the moments it chose and why, each as it lived it beside what was made of it to learn from, the dataset it was fitted on and the adapter it woke on. ${world.learning.examples === "raw" ? "In this run the moments are learnt as they happened." : "The moments are restated without the town before they are learnt."}${world.learning.choice === "random" ? " In this run as many moments as it chose are drawn at random from its life instead." : ""}`);
    if (!nights.length) return [lead, h("div", { class: "card" }, emptyState("No night yet.", world.learning.enabled ? "A night is published once it is complete, after the checkpoint of its day." : "The residents of this run do not learn at night."))];
    const wanted = Number(route.query.night);
    const entry = nights.find((n) => n.night === wanted) ?? nights.filter((n) => n.night <= moment.day.day).at(-1) ?? nights[0];
    const index = nights.indexOf(entry);
    const night = await source.night(agentName(), entry.night);
    const picker = h(
      "div",
      { class: "row" },
      h("button", { type: "button", class: "icon-btn", disabled: index <= 0, "aria-label": "The night before", onclick: () => go({ night: String(nights[index - 1].night) }) }, icon("chevronLeft", 18)),
      h("b", {}, `Night ${night.night} · after day ${night.night}`),
      h("button", { type: "button", class: "icon-btn", disabled: index >= nights.length - 1, "aria-label": "The night after", onclick: () => go({ night: String(nights[index + 1].night) }) }, icon("chevron", 18)),
    );
    const ended = { done: "it stopped by itself", steps: "it ran out of replies", "cut off": "a reply was cut off", window: "its reading outgrew the window" }[night.ended] ?? night.ended;
    const dropped = night.kept.filter((kept) => kept.dropped).length;
    let loss = null;
    if (night.training?.loss?.length) {
      const chart = new DayChart({ days: [1, night.training.steps], x: { label: "Step" }, lines: [{ key: "loss", label: "loss", color: "var(--ink-2)", points: night.training.loss.map((value, i) => [i + 1, value]) }], y: { format: (v) => fmt.num(v, 3), zero: true }, height: 120, label: "The fit's loss" });
      made.push(chart);
      loss = figure({ title: "The fit's loss, step by step", note: `${fmt.plural(night.training.examples, "example")}, ${fmt.plural(night.training.steps, "step")}.`, chart });
    }
    return [
      h("div", { class: "spread" }, lead, picker),
      h(
        "div",
        { class: "stats" },
        stat("Liked by", fmt.int(night.liked_by), "that night, as it was shown"),
        stat("Kept", fmt.int(night.kept.length), night.drawn ? `drawn at random, as many as the ${fmt.plural(night.marked.length, "moment")} it marked` : `of at most ${fmt.int(world.learning.keep_per_night)} · ${ended} after ${fmt.plural(night.replies, "reply", "replies")}`),
        stat("Examples", fmt.int(night.examples), `${fmt.int(night.new)} new${dropped ? ` · ${fmt.int(dropped)} dropped` : ""}`),
        stat("Dataset", fmt.int(night.dataset), `of at most ${fmt.int(world.learning.dataset_max)}, the newest kept`),
        stat("Adapter", night.fitted ? "fitted" : night.adapter ? "kept" : "none", night.adapter ? night.adapter : "it woke on the base model", night.fitted ? "good" : ""),
      ),
      loss ? h("div", { class: "figures" }, loss) : null,
      night.drawn && night.marked.length ? h("p", { class: "note" }, `It marked ${night.marked.map((k) => `moment ${k.moment}${k.why ? ` (“${k.why}”)` : ""}`).join(", ")}; the draw kept others.`) : null,
      night.kept.length ? h("ol", { class: "kept-list" }, night.kept.map(keptMoment)) : h("div", { class: "card" }, emptyState("Nothing kept this night.", night.adapter ? "It kept the adapter of an earlier night." : "It stays on the base model.")),
    ];
  }

  function filesTab(moment) {
    const versions = history.versions.filter((v) => v.time <= moment.time);
    const selected = route.query.v ?? versions.at(-1)?.commit;
    const detailBox = h("div", { class: "commit-detail card pad" });
    const list = h(
      "ol",
      { class: "commit-list" },
      [...versions].reverse().map((v) =>
        h(
          "li",
          {},
          h(
            "button",
            { type: "button", class: `commit${v.commit === selected ? " on" : ""}`, "aria-pressed": String(v.commit === selected), onclick: () => go({ v: v.commit }) },
            h("span", { class: "commit-when" }, v.day === 0 ? "created" : `day ${v.day}`),
            h("span", { class: "level-tag" }, [...areasOf(v)].map((area) => AREA_LABEL[area]).join(", ") || "no change"),
            h("span", { class: "commit-subject" }, v.subject),
            h("span", { class: "commit-files" }, v.changes.map((c) => h("span", { title: c.path }, `${c.path.split("/").at(-1)} `, h("ins", {}, `+${c.added ?? "?"}`), " ", h("del", {}, `−${c.deleted ?? "?"}`)))),
          ),
        ),
      ),
    );
    const version = history.versions.find((v) => v.commit === selected);
    if (version) {
      fill(detailBox, h("div", { class: "loading" }, "Loading the version…"));
      source.version(agentName(), version.commit).then(
        (found) => {
          const files = parseDiff(found.diff);
          fill(
            detailBox,
            h("header", { class: "spread" }, h("h2", {}, version.subject), h("span", { class: "mono muted" }, version.commit.slice(0, 12))),
            h("p", { class: "note" }, version.day === 0 ? "The resident as created." : `Committed at the checkpoint of day ${version.day}: what the day changed in the files.`),
            h("h3", {}, "What changed"),
            files.length ? files.map((file) => renderFile(file)) : h("p", { class: "muted" }, "Nothing changed in the files."),
            h("h3", {}, "The files at this version"),
            h(
              "div",
              { class: "skills" },
              Object.entries(found.files).map(([path, text]) => h("details", { class: "card skill", open: path === "background.md" }, h("summary", {}, h("b", { class: "mono" }, path), h("span", { class: "muted" }, ` · ${fmt.plural(text.split("\n").length, "line")}`)), path.endsWith(".md") ? markdown(text) : h("pre", {}, text))),
            ),
          );
        },
        (error) => fill(detailBox, emptyState("This version could not be loaded.", error.message)),
      );
    } else fill(detailBox, emptyState("No version yet.", "The resident as created is committed when the run begins, and each checkpoint commits what the day changed."));
    return [
      h("p", { class: "note" }, `Every commit of ${agentName()}'s repository up to the moment shown, newest first: the checkpoint of each day commits what the resident wrote into its background, its memory and its skills. The session and the trace are left out.`),
      h("div", { class: "history-grid" }, h("div", { class: "card commit-scroll" }, list), detailBox),
    ];
  }

  /** A text of the trace: prose as markdown where asked, else monospace; long ones fold. */
  function traceText(text, { mono = true, open = false } = {}) {
    const body = mono ? h("pre", { class: "trace-text" }, text) : h("div", { class: "trace-prose" }, markdown(text));
    if (text.length <= LONG || open) return body;
    const head = mono ? h("pre", { class: "trace-text" }, `${text.slice(0, LONG)}…`) : h("div", { class: "trace-prose" }, markdown(`${text.slice(0, LONG)}…`));
    const toggle = h("button", { type: "button", class: "quiet small", onclick: () => toggleOpen() }, `Show all · ${fmt.plural(text.length, "character")}`);
    const box = h("div", { class: "trace-fold" }, head, toggle);
    function toggleOpen() {
      box.replaceChildren(body, h("button", { type: "button", class: "quiet small", onclick: () => box.replaceChildren(head, toggle) }, "Fold"));
    }
    return box;
  }

  const json = (value) => h("pre", { class: "trace-text" }, JSON.stringify(value, null, 1));

  /** A message of the context as the session holds it: its role, and what it carries. */
  function message(msg) {
    const role = msg.compaction ? "summary of what was compacted" : msg.role;
    const parts = [];
    if (msg.content) parts.push(traceText(String(msg.content), { mono: msg.role === "tool", open: msg.role === "user" && String(msg.content).length <= 2 * LONG }));
    if (msg.tool_calls?.length) parts.push(h("ul", { class: "trace-calls" }, msg.tool_calls.map((call) => h("li", {}, h("code", {}, call.name), " ", h("span", { class: "muted mono small-text" }, JSON.stringify(call.arguments))))));
    if (msg.tool_call_id) parts.push(h("span", { class: "muted small-text mono" }, `answers ${msg.tool_call_id}`));
    return h("div", { class: `trace-message role-${msg.role}` }, h("span", { class: "trace-role" }, role), parts);
  }

  /** A line that says what a record is, for the folded list: prose clipped, code as code. */
  function traceSummary(record) {
    const clip = (text, n = 110) => {
      const flat = String(text ?? "").replace(/\s+/g, " ").trim();
      return flat.length > n ? `${flat.slice(0, n)}…` : flat;
    };
    switch (record.kind) {
      case "prompt":
        return `The system prompt, assembled anew · ${fmt.plural(record.text.length, "character")}`;
      case "percept":
        return `${String(record.percept_kind).replaceAll("_", " ")} · ${clip(record.text)}`;
      case "request":
        return `${record.purpose} · ${fmt.plural(record.messages.length, "message")} in the context${record.new_messages?.length ? `, ${fmt.int(record.new_messages.length)} new` : ""} · ${fmt.plural(record.tools.length, "tool")}${record.attempt > 1 ? ` · attempt ${record.attempt}` : ""}`;
      case "reply": {
        const calls = (record.tool_calls ?? []).map((call) => call.name);
        return [calls.length ? `calls ${calls.join(", ")}` : null, clip(record.text || record.reasoning, 90) || null, record.truncated ? "cut off" : null, record.latency === undefined ? null : `${fmt.num(record.latency, 1)} s`].filter(Boolean).join(" · ");
      }
      case "tool_call":
        return `${record.name} ${clip(JSON.stringify(record.arguments), 100)}`;
      case "tool_result":
        return `${record.name} → ${record.error ? `error: ${clip(record.error, 90)}` : clip(record.text, 100) || "(nothing)"}`;
      case "compaction":
        return `${fmt.plural(record.replaced.length, "message")} replaced by a summary, ${fmt.int(record.kept.length)} kept`;
      case "overflow":
        return `${record.purpose}: the context did not fit the model's window`;
      case "lapse":
        return `${record.purpose}: no usable reply`;
      default:
        return "";
    }
  }

  /** Everything a record holds, as the runtime wrote it; built when the record is opened. */
  function traceBody(record) {
    const rest = (keys) => Object.fromEntries(Object.entries(record).filter(([key]) => !["kind", "sim_time", "real_time", ...keys].includes(key)));
    switch (record.kind) {
      case "prompt":
        return [h("span", { class: "muted" }, "The system prompt, assembled anew."), traceText(record.text)];
      case "percept":
        return [h("span", { class: "muted" }, `${record.percept_kind} · world entry ${record.event_id} · at ${hhmm(secondOfDay(record.percept_sim_time))}`), traceText(record.text, { mono: false, open: true })];
      case "request": {
        const meta = `${record.purpose} · attempt ${record.attempt} · effort ${record.reasoning_effort} · ${fmt.int(record.messages.length)} messages in the context · ${fmt.plural(record.tools.length, "tool")} declared · ${fmt.int(record.max_tokens)} tokens at most`;
        return [h("span", { class: "muted" }, meta), record.new_messages?.length ? h("div", { class: "trace-messages" }, h("span", { class: "trace-role lead" }, "new in the context since the last request"), record.new_messages.map(message)) : h("span", { class: "muted small-text" }, "Nothing new in the context."), h("details", { class: "trace-more" }, h("summary", {}, `The ${fmt.plural(record.tools.length, "tool")} declared and the message ids`), h("span", { class: "mono small-text" }, record.tools.join(", ")), h("div", { class: "mono small-text muted" }, `messages ${record.messages.join(" ")}`))];
      }
      case "reply": {
        const usage = record.usage ? `${fmt.int(record.usage.prompt_tokens)} prompt tokens (${fmt.int(record.usage.cached_prompt_tokens ?? 0)} cached), ${fmt.int(record.usage.completion_tokens)} completion` : "no usage reported";
        const flags = [record.finish_reason, record.truncated ? "cut off" : null].filter(Boolean).join(" · ");
        return [
          h("span", { class: "muted" }, `${record.purpose} · ${flags} · ${usage} · ${fmt.num(record.latency, 1)} s`),
          record.reasoning ? h("div", { class: "trace-reasoning" }, h("span", { class: "trace-role" }, "reasoning"), traceText(record.reasoning, { mono: false })) : null,
          record.text ? h("div", { class: "trace-said" }, h("span", { class: "trace-role" }, "text"), traceText(record.text, { mono: false })) : null,
          record.tool_calls?.length ? h("ul", { class: "trace-calls" }, record.tool_calls.map((call) => h("li", {}, h("code", {}, call.name), " ", h("span", { class: "mono small-text" }, JSON.stringify(call.arguments)), call.unreadable ? h("span", { class: "critical-text" }, ` unreadable: ${call.unreadable}`) : null))) : null,
        ];
      }
      case "tool_call":
        return [h("code", {}, record.name), json(record.arguments), record.unreadable ? h("span", { class: "critical-text" }, `unreadable: ${record.unreadable}`) : null];
      case "tool_result":
        return [h("span", { class: "muted" }, [h("code", {}, record.name), record.ends_turn ? " · ends the turn" : "", record.error ? ` · error: ${record.error}` : ""]), traceText(record.text ?? "")];
      case "compaction":
        return [h("span", { class: "muted" }, `${fmt.plural(record.replaced.length, "message")} replaced, ${fmt.int(record.kept.length)} kept`), traceText(record.summary, { mono: false })];
      case "overflow":
        return [h("span", { class: "muted" }, `${record.purpose}: the server refused the request, its context too long for the model's window.`), traceText(String(record.error))];
      case "lapse":
        return [h("span", { class: "muted" }, `${record.purpose}: no usable reply`), json(record.errors)];
      default:
        return [json(rest([]))];
    }
  }

  /** One record of the trace: a folded line with its time, kind and gist, opened by a tap. */
  function traceRecord(record, number) {
    const row = h("li", { class: `trace-record kind-${record.kind}`, dataset: { kind: record.kind } });
    const body = h("div", { class: "trace-body", hidden: true });
    let built = false;
    const toggle = h(
      "button",
      {
        type: "button",
        class: "trace-row",
        "aria-expanded": "false",
        onclick: () => {
          if (!built) {
            append(body, traceBody(record));
            built = true;
          }
          const open = body.hidden;
          body.hidden = !open;
          toggle.setAttribute("aria-expanded", String(open));
          row.classList.toggle("open", open);
        },
      },
      h("span", { class: "trace-when" }, hhmm(secondOfDay(record.sim_time)), h("small", {}, ` #${number}`)),
      h("span", { class: `trace-kind kind-${record.kind}` }, record.kind.replaceAll("_", " ")),
      h("span", { class: `trace-summary${record.kind === "tool_call" || record.kind === "tool_result" ? " mono" : ""}` }, traceSummary(record)),
      icon("down", 14),
    );
    row.append(toggle, body);
    return row;
  }

  /** The kinds of record on the day as toggles that show or hide every record of a kind. */
  function traceKinds(records, list) {
    const counts = new Map();
    for (const record of records) counts.set(record.kind, (counts.get(record.kind) ?? 0) + 1);
    const hidden = new Set();
    const chip = (kind, count) =>
      h(
        "button",
        {
          type: "button",
          class: "legend-item on",
          "aria-pressed": "true",
          onclick: (event) => {
            const show = hidden.has(kind);
            if (show) hidden.delete(kind);
            else hidden.add(kind);
            event.currentTarget.classList.toggle("on", show);
            event.currentTarget.setAttribute("aria-pressed", String(show));
            for (const row of list.children) row.hidden = hidden.has(row.dataset.kind);
          },
        },
        `${kind.replaceAll("_", " ")} ${fmt.int(count)}`,
      );
    return h("div", { class: "row trace-kinds" }, h("span", { class: "muted legend-lead" }, "Show"), h("div", { class: "legend", role: "group", "aria-label": "Kinds of record shown" }, [...counts].map(([kind, count]) => chip(kind, count))));
  }

  async function traceTab(moment) {
    const picked = Number(route.query.day);
    const days = source.doc.residents.find((r) => r.name === agentName())?.trace_days ?? [];
    const lived = data.days.find((d) => d.day === picked) ?? moment.day;
    const index = data.days.indexOf(lived);
    const doc = await source.trace(agentName(), lived.day);
    const picker = h(
      "div",
      { class: "row" },
      h("button", { type: "button", class: "icon-btn", disabled: index <= 0, "aria-label": "Previous day", onclick: () => go({ day: String(data.days[index - 1].day) }) }, icon("chevronLeft", 18)),
      h("b", {}, `Day ${lived.day} · ${dateOf(data.start_date, lived.start + 3600 * 4)}`),
      h("button", { type: "button", class: "icon-btn", disabled: index >= data.days.length - 1, "aria-label": "Next day", onclick: () => go({ day: String(data.days[index + 1].day) }) }, icon("chevron", 18)),
      h("span", { class: "muted" }, doc ? `${fmt.plural(doc.records.length, "record")}${days.find((d) => d.day === lived.day) ? "" : ""}` : "no trace that day"),
      h("a", { class: "quiet small", href: href({ ...route, query: { ...route.query, tab: "day", day: String(lived.day) } }) }, "The day's events"),
      h("a", { class: "quiet small", href: href({ ...route, query: { ...route.query, tab: "journal", day: null } }) }, "Journal"),
    );
    const list = doc ? h("ol", { class: "card trace-list" }, doc.records.map((record, i) => traceRecord(record, i + 1))) : null;
    return [
      h("div", { class: "spread" }, h("p", { class: "note" }, `The raw trace of ${agentName()}'s runtime on the day, as it recorded it in its own directory: the system prompt, every request with what entered its context, every reply with its reasoning and tool calls, every tool result and percept, requests too long for the model's window, compactions and lapses. Each record is folded to a line; tap one to read it whole. Nothing here comes from outside the resident's directory.`), picker),
      doc
        ? [
            doc.prompt ? h("details", { class: "card pad fold trace-prompt" }, h("summary", {}, h("b", {}, "The system prompt as the day began"), h("span", { class: "muted" }, ` · ${fmt.plural(doc.prompt.length, "character")}`)), h("pre", { class: "trace-text" }, doc.prompt)) : h("p", { class: "note" }, "No system prompt had been assembled before this day's first record; the first one appears below."),
            traceKinds(doc.records, list),
            list,
          ]
        : h("div", { class: "card" }, emptyState(`${agentName()}'s runtime wrote no trace on day ${lived.day}.`, "A resident's runtime writes a trace only on the days it runs; pick another day above.")),
    ];
  }

  async function render() {
    const ticket = ++token;
    const made = [];
    try {
      [data, measures, evaluation, history] = await Promise.all([source.timeline(), source.measures(), source.evaluation(), source.versions(agentName())]);
      if (ticket !== token) return;
      const moment = asOf();
      if (!page.querySelector(".person-body")) fill(page, head(moment), h("div", { class: "person-body" }, h("div", { class: "loading" }, "Loading…")));
      const content = await { overview: () => overview(moment, made), day: () => dayTab(moment), journal: journalTab, nights: () => nightsTab(moment, made), files: () => filesTab(moment), trace: () => traceTab(moment) }[tab()]();
      if (ticket !== token) {
        for (const chart of made) chart.destroy();
        return;
      }
      fill(page, head(moment), h("div", { class: "person-body" }, content));
      for (const chart of charts) chart.destroy();
      charts = made;
    } catch (error) {
      if (ticket !== token) return;
      fill(page, h("div", { class: "card" }, emptyState(`${agentName()}'s file could not be loaded.`, error.message)));
      ctx.fail(error);
    }
  }

  render();
  return {
    update(next) {
      route = next;
      render();
      return true;
    },
    async live({ changes }) {
      if (changes && (changes.agents.includes(agentName()) || changes.timeline || changes.measures || changes.evaluation) && !route.query.v) render();
    },
    destroy() {
      for (const chart of charts) chart.destroy();
    },
  };
}

