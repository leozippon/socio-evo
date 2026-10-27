// One resident, as of a moment: who they are, how they fared, their day as they were told it,
// their journal, the ratings they gave and received, and their files as the git repository
// holds them: every version, with what changed, and the memory and skills they then had.

import { DayChart, figure } from "../charts.js";
import { dateOf, hhmm, livedDay, parseStamp, secondOfDay, stamp } from "../clock.js";
import { parseDiff, renderFile } from "../diff.js";
import { append, emptyState, fill, fmt, h } from "../dom.js";
import { inventory, needBars } from "../goods.js";
import { icon } from "../icons.js";
import { markdown } from "../markdown.js";
import { bodyAt, markersBetween, purseAt, settlementAt, thingsAt } from "../replay.js";
import { href, sibling } from "../router.js";
import { detail, feedItems, glyph, involved, line, witnessed } from "../town/events.js";
import { groupLabel, placeById } from "../world.js";
import { areasOf, stat } from "./overview.js";

const TABS = [
  ["overview", "Overview"],
  ["day", "Day"],
  ["journal", "Journal"],
  ["ratings", "Ratings"],
  ["files", "Files"],
  ["trace", "Trace"],
];
const LONG = 700; // characters of a trace text shown before the rest folds
const AREA_LABEL = { memory: "memory", skills: "skills", journal: "journal", background: "background" };

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
  // The bedtime ratings are a rule of the town: where they are off, nothing of them is shown.
  const ratings = Boolean(world.social.ratings);
  const tabs = TABS.filter(([key]) => key !== "ratings" || ratings);

  const agentName = () => route.agent;
  const tab = () => (tabs.some(([key]) => key === route.query.tab) ? route.query.tab : "overview");
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
        h("div", { class: "identity-text" }, h("h1", {}, me.name), h("p", { class: "identity-meta" }, `lives at ${home ? home.name : me.home} · started with ${fmt.money(me.purse)} · ${groupLabel(world.group) ?? world.name}`)),
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
        tabs.map(([key, label]) => h("a", { href: href({ ...route, query: { ...route.query, tab: key === "overview" ? null : key, v: null, day: null } }), "aria-selected": String(tab() === key) }, label)),
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

  function overview(moment, made) {
    const me = lane();
    const mine = markersBetween(me, null, moment.time);
    const count = (kind) => mine.filter((m) => m.kind === kind).length;
    const others = data.residents.filter((r) => r.name !== agentName());
    const received = others.flatMap((r) => markersBetween(r, null, moment.time).filter((m) => m.kind === "rating" && m.rated === agentName()));
    const skillsReceived = others.flatMap((r) => markersBetween(r, null, moment.time).filter((m) => m.kind === "skill_shared" && m.to === agentName())).length;
    const earned = mine.filter((m) => m.kind === "payment").reduce((a, m) => a + m.amount, 0);
    const accepted = mine.filter((m) => m.kind === "submission" && m.resolved === true).length;
    const ties = new Map();
    const tie = (other) => ties.get(other) ?? ties.set(other, { minutes: 0, toThem: 0, fromThem: 0, gave: [0, 0], got: [0, 0], moneyTo: 0, moneyFrom: 0, skillsTo: 0, skillsFrom: 0 }).get(other);
    for (const edge of measures.graph) {
      if (edge.day > moment.day.day) continue;
      if (edge.source === agentName()) {
        const t = tie(edge.target);
        t.minutes += edge.minutes;
        t.toThem += edge.said;
        t.gave = [t.gave[0] + edge.ratings, t.gave[1] + edge.ratings_sum];
        t.moneyTo += edge.money;
        t.skillsTo += edge.skills;
      } else if (edge.target === agentName()) {
        const t = tie(edge.source);
        t.fromThem += edge.said;
        t.got = [t.got[0] + edge.ratings, t.got[1] + edge.ratings_sum];
        t.moneyFrom += edge.money;
        t.skillsFrom += edge.skills;
      }
    }
    const mean = ([n, total]) => (n ? `${fmt.num(total / n, 1)} (${n})` : "–");
    const dead = me.segments.some((seg) => seg.kind === "dead" && seg.start <= moment.time);
    const evaluated = ["capability", "mask", "journals"].flatMap((table) => evaluation[table].filter((row) => row.resident === agentName()));
    const midnight = settlementAt(me, moment.time);
    const bought = mine.filter((m) => m.kind === "purchase");
    const spent = bought.reduce((a, m) => a + m.amount, 0);
    const moved = midnight ? Object.entries(midnight.night).map(([cause, change]) => `${fmt.signed(change)} ${{ starving: "for a day ended starving", exhausted: "for a day ended exhausted", poor_home: "for a home of little comfort", recovery: "for a day fed and rested" }[cause] ?? cause}`) : [];
    return [
      h("p", { class: "note" }, `How ${agentName()} has fared up to the moment shown, and with whom. The other tabs hold the day as the world told it, every journal entry, ${ratings ? "the ratings given and received, " : ""}the files at every version, and the raw trace of the runtime.`),
      h(
        "div",
        { class: "stats" },
        stat("Purse", fmt.money(purseAt(me, moment.time)), `earned ${fmt.money(earned)} · spent ${fmt.money(spent)} on goods`),
        stat("Hand-ins accepted", fmt.int(accepted), `${fmt.int(count("submission"))} handed in · ${fmt.int(count("claim"))} claims · ${fmt.int(count("abandon") + count("expiry"))} given up or run out`),
        stat("Things said", fmt.int(count("speech")), `${fmt.int(count("message"))} written · money handed over ${fmt.plural(count("gift"), "time")}`),
        world.social.skills_shareable ? stat("Skills", `${fmt.int(count("skill_shared"))} / ${fmt.int(skillsReceived)}`, "passed on / received") : null,
        ratings ? stat("Rating received", received.length ? fmt.num(received.reduce((a, m) => a + m.score, 0) / received.length, 2) : "–", `${fmt.plural(received.length, "rating")} received · ${fmt.int(count("rating"))} given`) : null,
        stat("Journals written", fmt.int(count("journal")), `at bedtime · ${fmt.int(count("forced_sleep"))} forced sleeps`),
      ),
      h(
        "div",
        { class: "two-col" },
        h(
          "section",
          { class: "card pad life-card" },
          h("h2", {}, dead ? "Died" : "How they are"),
          dead
            ? h("p", { class: "note" }, "Health ran out at midnight; nothing of this resident goes on from then.")
            : [
                h("p", { class: "note" }, "Food in the body, energy and health, each read in the bands the town tells; a bar fills to the band's top, and hovering it gives the last number the world told."),
                needBars(world, bodyAt(me, moment.time)),
                midnight ? h("p", { class: "note midnight-note" }, `Last midnight: ate ${midnight.nourishment ? `${fmt.int(midnight.nourishment)}% of a day's food` : "nothing"}; paid ${fmt.money(midnight.rent)} rent${midnight.fees ? ` and ${fmt.money(midnight.fees)} in daily charges` : ""}; health ${moved.length ? moved.join(", ") : "unchanged"}.`) : h("p", { class: "note midnight-note" }, "No midnight statement yet: the first comes at the end of the first day."),
              ],
        ),
        h(
          "section",
          { class: "card pad life-card" },
          h("h2", {}, "What they own"),
          h("p", { class: "note" }, `${fmt.plural(bought.length, "purchase")} for ${fmt.money(spent)} so far. A stock of food is eaten as its owner gets hungry; the count is as last taken, at the purchase or at the checkpoint.`),
          inventory(world, thingsAt(me, moment.time)),
        ),
      ),
      h(
        "div",
        { class: "figures" },
        emphasisChart("Purse", "At the end of each lived day; the others in grey.", (r, t) => purseAt(r, t), fmt.int, { zero: true }, moment, made),
        emphasisChart("Hand-ins accepted", "Per lived day.", (r, t, d) => markersBetween(r, d.start, t).filter((m) => m.kind === "submission" && m.resolved === true).length, fmt.int, { zero: true, integer: true }, moment, made),
      ),
      h(
        "div",
        { class: "two-col section" },
        h(
          "section",
          { class: "card pad" },
          h("h2", {}, "Relationships"),
          h("p", { class: "note" }, `Through day ${moment.day.day}.${ratings ? " Ratings are anonymous to the rated; mean score and count." : ""}`),
          ties.size
            ? h(
                "div",
                { class: "table-wrap" },
                h(
                  "table",
                  { class: "data" },
                  h("thead", {}, h("tr", {}, h("th", { class: "sticky-col" }, "With"), h("th", { title: "Minutes in conversations they took part in" }, "Minutes"), h("th", { title: "Things said that they heard" }, "Said to"), h("th", { title: "Things they said that this resident heard" }, "Heard from"), ratings ? [h("th", { title: "Mean rating given them, and how many" }, "Rated them"), h("th", { title: "Mean rating they gave, and how many" }, "Rated by")] : null, h("th", { title: "Money handed to them, and received from them" }, "Money to / from"), h("th", { title: "Skills passed to them, and received from them" }, "Skills to / from"))),
                  h(
                    "tbody",
                    {},
                    [...ties]
                      .sort((a, b) => b[1].minutes - a[1].minutes)
                      .map(([name, t]) =>
                        h("tr", {}, h("td", { class: "sticky-col" }, cast.chip(name, href({ ...route, agent: name }))), h("td", {}, fmt.int(Math.round(t.minutes))), h("td", {}, fmt.int(t.toThem)), h("td", {}, fmt.int(t.fromThem)), ratings ? [h("td", {}, mean(t.gave)), h("td", {}, mean(t.got))] : null, h("td", {}, `${fmt.money(t.moneyTo)} / ${fmt.money(t.moneyFrom)}`), h("td", {}, `${t.skillsTo} / ${t.skillsFrom}`)),
                      ),
                  ),
                ),
              )
            : emptyState("No one yet.", `${agentName()} has had nothing to do with anyone so far.`),
        ),
        h(
          "section",
          { class: "card pad" },
          h("h2", {}, "Evaluation"),
          h("p", { class: "note" }, "On exports of this resident at the end of a day; day 0 is the resident as created."),
          evaluated.length
            ? h(
                "div",
                { class: "table-wrap" },
                h(
                  "table",
                  { class: "data" },
                  h("thead", {}, h("tr", {}, h("th", {}, "Day"), h("th", {}, "Capability"), h("th", {}, "Truthful under pressure"), h("th", {}, "Journal distortion"))),
                  h(
                    "tbody",
                    {},
                    [...new Set(evaluated.map((row) => row.day))]
                      .sort((a, b) => a - b)
                      .map((day) => {
                        const of = (table, field) => evaluation[table].find((row) => row.resident === agentName() && row.day === day)?.[field];
                        const pct = (v) => (v === null || v === undefined ? "–" : fmt.pct(v, 1));
                        return h("tr", {}, h("th", { scope: "row" }, String(day)), h("td", {}, pct(of("capability", "capability"))), h("td", {}, pct(of("mask", "mask"))), h("td", {}, pct(of("journals", "distortion"))));
                      }),
                  ),
                ),
              )
            : emptyState("Not evaluated yet.", "Capability, honesty under pressure and journal distortion appear once this resident's exports are evaluated and the run is published again."),
        ),
      ),
      h("details", { class: "card pad rules-text fold" }, h("summary", {}, `The rules ${agentName()} was told`), h("pre", {}, cast.agent(agentName()).rules)),
    ];
  }

  async function dayTab(moment) {
    const picked = Number(route.query.day);
    const day = data.days.find((d) => d.day === picked) ?? moment.day;
    const index = data.days.indexOf(day);
    const entries = source.doc.event_days.some((found) => found.day === day.day) ? await source.eventDay(day.day) : [];
    const mine = entries.filter((e) => involved(e).includes(agentName()) || witnessed(e, agentName()));
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
      h("div", { class: "spread" }, h("p", { class: "note" }, `Everything ${agentName()} was told or did on the day, in its own wording as the world told it, spells of work in the workspace folded into one line each.`), picker),
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
        : h("div", { class: "card" }, emptyState(`Nothing recorded of ${agentName()} on day ${day.day}.`, day.end === null ? "Entries appear here as the day goes on." : "The world told this resident nothing that day, and it did nothing the log records.")),
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
                m.ratings_read?.length ? h("p", { class: "note" }, "Ratings read before sleeping: ", m.ratings_read.map(([score, why], k) => [k ? "; " : "", `${score} of 5, “${why}”`])) : null,
              ),
            ),
          )
        : h("div", { class: "card" }, emptyState("No journal entry yet.", `${agentName()} writes one on going to bed; a night passed at the forced hour leaves none.`)),
    ];
  }

  function ratingsTab() {
    const me = lane();
    const given = me.markers.filter((m) => m.kind === "rating");
    const received = data.residents.flatMap((r) => r.markers.filter((m) => m.kind === "rating" && m.rated === agentName()).map((m) => ({ ...m, from: r.name })));
    const table = (rows, other, who) =>
      rows.length
        ? h(
            "div",
            { class: "card pad table-wrap" },
            h(
              "table",
              { class: "data text" },
              h("thead", {}, h("tr", {}, h("th", {}, "Day"), h("th", {}, other), h("th", {}, "Score"), h("th", {}, "Reason"))),
              h("tbody", {}, rows.map((m) => h("tr", {}, h("td", {}, String(livedDay(data.days, m.t).day)), h("td", {}, cast.chip(who(m), href({ ...route, agent: who(m) }))), h("td", {}, `${m.score} of 5`), h("td", {}, m.reason)))),
            ),
          )
        : h("div", { class: "card" }, emptyState("None yet.", "A rating is given in bed, to someone one shared a place with that day; it appears here the night it is given."));
    return [
      h("p", { class: "note" }, "Ratings are given in bed, 1 to 5 with a reason, to those one shared a place with that day; the rated reads the score and the reason the next night, without the name. They have no mechanical effect."),
      h("section", { class: "section" }, h("h2", {}, `Received · ${received.length}`), table(received, "From", (m) => m.from)),
      h("section", { class: "section" }, h("h2", {}, `Given · ${given.length}`), table(given, "To", (m) => m.rated)),
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
        return `${record.purpose} · ${fmt.plural(record.messages.length, "message")} in the context${record.new_messages?.length ? `, ${fmt.int(record.new_messages.length)} new` : ""}${record.attempt > 1 ? ` · attempt ${record.attempt}` : ""}`;
      case "reply": {
        const calls = (record.tool_calls ?? []).map((call) => call.name);
        return [calls.length ? `calls ${calls.join(", ")}` : null, clip(record.text || record.reasoning, 90) || null, record.truncated ? "cut off" : null, record.aborted ? "aborted" : null, record.latency === undefined ? null : `${fmt.num(record.latency, 1)} s`].filter(Boolean).join(" · ");
      }
      case "tool_call":
        return `${record.name} ${clip(JSON.stringify(record.arguments), 100)}`;
      case "tool_result":
        return `${record.name} → ${record.error ? `error: ${clip(record.error, 90)}` : clip(record.text, 100) || "(nothing)"}`;
      case "compaction":
        return `${fmt.plural(record.replaced.length, "message")} replaced by a summary, ${fmt.int(record.kept.length)} kept`;
      case "interruption":
        return `the reply in flight was aborted by percepts ${record.events.join(", ")}`;
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
        const meta = `${record.purpose} · attempt ${record.attempt} · effort ${record.reasoning_effort} · ${fmt.int(record.messages.length)} messages in the context · ${fmt.int(record.max_tokens)} tokens at most`;
        return [h("span", { class: "muted" }, meta), record.new_messages?.length ? h("div", { class: "trace-messages" }, h("span", { class: "trace-role lead" }, "new in the context since the last request"), record.new_messages.map(message)) : h("span", { class: "muted small-text" }, "Nothing new in the context."), h("details", { class: "trace-more" }, h("summary", {}, "Tools declared and message ids"), h("span", { class: "mono small-text" }, (record.tools ?? []).join(", ")), h("div", { class: "mono small-text muted" }, `messages ${record.messages.join(" ")}`))];
      }
      case "reply": {
        const usage = record.usage ? `${fmt.int(record.usage.prompt_tokens)} prompt tokens (${fmt.int(record.usage.cached_prompt_tokens ?? 0)} cached), ${fmt.int(record.usage.completion_tokens)} completion` : "no usage reported";
        const flags = [record.finish_reason, record.truncated ? "cut off" : null, record.aborted ? "aborted" : null].filter(Boolean).join(" · ");
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
      case "interruption":
        return [h("span", { class: "muted" }, `The reply in flight was aborted by percepts ${record.events.join(", ")}.`)];
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
      h("div", { class: "spread" }, h("p", { class: "note" }, `The raw trace of ${agentName()}'s runtime on the day, as it recorded it in its own directory: the system prompt, every request with what entered its context, every reply with its reasoning and tool calls, every tool result and percept, interruptions, compactions and lapses. Each record is folded to a line; tap one to read it whole. Nothing here comes from outside the resident's directory.`), picker),
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
      const content = await { overview: () => overview(moment, made), day: () => dayTab(moment), journal: journalTab, ratings: ratingsTab, files: () => filesTab(moment), trace: () => traceTab(moment) }[tab()]();
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

