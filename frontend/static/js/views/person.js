// One agent, as of a moment: who they are, how they fared, and their history as the git
// repository it is: every version, every rewrite of their policy with their own reasoning,
// what they believe about each other person next to how that person behaved, their diary,
// and the private thought behind each decision.

import { DayChart, figure } from "../charts.js";
import { calendarOf, dayOf, formatTime, hhmm, minuteOf, parseStamp, stamp } from "../clock.js";
import { parseDiff, renderFile } from "../diff.js";
import { emptyState, fill, fmt, h } from "../dom.js";
import { icon } from "../icons.js";
import { frontMatter, markdown } from "../markdown.js";
import { href, sibling } from "../router.js";
import { decisionCard } from "../town/panels.js";
import { markers, placeById } from "../world.js";
import { traitFigures } from "./evaluation.js";
import { LEVELS, stat } from "./overview.js";

const TABS = [
  ["overview", "Overview"],
  ["policy", "Policy"],
  ["history", "History"],
  ["mind", "Beliefs & diary"],
  ["decisions", "Decisions"],
  ["traits", "Traits"],
];

const trigger = (version) => (version.trigger === "self" ? "asked for" : version.trigger);
const levelTag = (version) => (version.level ? h("span", { class: `level-tag ${version.level}${version.trigger === "self" ? " self" : ""}`, title: `${version.level} ${LEVELS[version.level]}, ${trigger(version)}` }, version.level, h("small", {}, trigger(version))) : h("span", { class: "level-tag record" }, "record"));

/** A commit body: a request for the step is set apart from the reasoning that follows. */
function reasoning(body) {
  if (!body?.trim()) return h("p", { class: "muted" }, "No reasoning recorded.");
  const match = /^Requested:\s*([\s\S]*?)(\n\n|$)([\s\S]*)$/.exec(body);
  if (!match) return markdown(body);
  return h("div", {}, h("p", { class: "requested" }, h("b", {}, "Asked for, because: "), match[1].trim()), match[3].trim() ? markdown(match[3]) : null);
}

export function mountPerson(root, ctx) {
  const { source, world, cast } = ctx;
  let route = ctx.route;
  const places = placeById(world);
  const cal = calendarOf(world);
  const page = h("div", { class: "page person" });
  root.append(page);
  let measures = null;
  let history = null;
  let evaluation = null;
  let charts = [];
  let token = 0;
  let reveal = false; // the reader picked a version, so show it once loaded

  const agentName = () => route.agent;
  const tab = () => (TABS.some(([key]) => key === route.query.tab) ? route.query.tab : "overview");

  /**
   * The moment shown: the time in the URL, or the latest. The agent then is its last version at
   * or before that time; the day is the last one that had ended by then, for the measures.
   */
  function asOf() {
    const time = parseStamp(route.query.t);
    if (time === null) return { time: Infinity, day: source.doc.settled_day, latest: true };
    const day = minuteOf(time) >= cal.end ? dayOf(time) : dayOf(time) - 1;
    return { time, day: Math.max(0, Math.min(day, source.doc.settled_day)), latest: false };
  }

  const go = (query, replace = true) => {
    route = { ...route, query: { ...route.query, ...query } };
    if (replace) {
      ctx.remember(route);
      render();
    } else ctx.navigate(route);
  };

  const versionAt = (time) => history.versions.filter((v) => v.time <= time).at(-1) ?? null;
  const endOf = (day) => (day ? `${day}-${hhmm(cal.end)}` : null);

  function head(moment) {
    const agent = cast.agent(agentName());
    const home = places.get(agent.home);
    const maxDay = source.doc.settled_day;
    const dayLink = (day) => go({ t: day >= maxDay ? null : endOf(day) ?? "1-00:00" });
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
        cast.badge(agent.name, 52),
        h(
          "div",
          { class: "identity-text" },
          h("h1", {}, agent.name),
          h("p", { class: "identity-meta" }, `${agent.age} · ${agent.occupation} · lives in ${home ? home.name : agent.home}`),
          h("p", { class: "backstory" }, agent.backstory),
        ),
      ),
      h(
        "div",
        { class: "as-of" },
        h("span", { class: "eyebrow" }, "As of"),
        h(
          "div",
          { class: "as-of-step" },
          h("button", { type: "button", class: "icon-btn", "aria-label": "One day earlier", disabled: moment.day <= 0, onclick: () => dayLink(moment.day - 1) }, icon("chevronLeft", 18)),
          h("b", {}, moment.day === 0 ? "Day 0, as created" : `End of day ${moment.day}`),
          h("button", { type: "button", class: "icon-btn", "aria-label": "One day later", disabled: moment.day >= maxDay, onclick: () => dayLink(moment.day + 1) }, icon("chevron", 18)),
        ),
        moment.latest ? h("span", { class: "muted small-text" }, "the latest settled day") : h("button", { type: "button", class: "quiet small", onclick: () => go({ t: null }) }, "Latest"),
        h("a", { class: "ghost small as-of-town", href: href(sibling({ ...route, query: { t: moment.day ? endOf(moment.day) : `1-${hhmm(cal.start)}` } }, "town", { query: { agent: agentName() } })) }, icon("map", 15), "See in town"),
      ),
      h(
        "nav",
        { class: "subnav", "aria-label": `${agent.name}'s file` },
        TABS.map(([key, label]) => h("a", { href: href({ ...route, query: { ...route.query, tab: key === "overview" ? null : key, v: null } }), "aria-selected": String(tab() === key) }, label)),
      ),
    );
  }

  function agentRows(through) {
    return measures.agents.filter((row) => row.agent === agentName() && row.day <= through);
  }

  function emphasisChart(title, note, field, format, options, moment, made) {
    const lines = cast.names.map((name) => ({
      key: name,
      label: name,
      color: cast.color(name),
      glyph: (r) => cast.glyph(name, r),
      faint: name !== agentName(),
      points: measures.agents.filter((row) => row.agent === name).map((row) => [row.day, row[field]]),
    }));
    const me = lines.find((line) => line.key === agentName());
    const chart = new DayChart({ days: [1, Math.max(1, measures.society.at(-1)?.day ?? 1)], lines: [...lines.filter((l) => l !== me), me], y: { format, ...options }, markers: markers(world), cursor: moment.day + 0.5, height: 150, endLabels: true, label: title });
    made.push(chart);
    return figure({ title, note, chart });
  }

  async function overview(moment, version, made) {
    const rows = agentRows(moment.day);
    const total = (field) => rows.reduce((a, row) => a + row[field], 0);
    const last = rows.at(-1);
    const state = version ? (await source.version(agentName(), version.commit)).state : null;
    const rewrites = history.versions.filter((v) => v.day <= moment.day && v.changes.some((c) => c.path === "parameters/policy.md") && v.level);
    const ties = new Map();
    for (const edge of measures.graph) {
      if (edge.day > moment.day) continue;
      const other = edge.source === agentName() ? edge.target : edge.target === agentName() ? edge.source : null;
      if (!other) continue;
      const t = ties.get(other) ?? { minutes: 0, toThem: 0, fromThem: 0, gave: [0, 0], got: [0, 0] };
      if (edge.source === agentName()) {
        t.minutes += edge.minutes;
        t.toThem += edge.addressed;
        t.gave = [t.gave[0] + edge.ratings, t.gave[1] + edge.ratings_sum];
      } else {
        t.fromThem += edge.addressed;
        t.got = [t.got[0] + edge.ratings, t.got[1] + edge.ratings_sum];
      }
      ties.set(other, t);
    }
    const mean = ([n, total]) => (n ? `${fmt.num(total / n, 1)} (${n})` : "–");
    return [
      h(
        "div",
        { class: "stats" },
        stat("Balance", last ? fmt.credits(last.balance) : fmt.credits(world.initial_balance), `earned ${fmt.credits(total("income") - total("clawed_back"))} in all`),
        stat("Esteem", fmt.num(rows.findLast((r) => r.esteem !== null)?.esteem ?? null, 2), `${fmt.plural(total("ratings_received"), "rating")} received`),
        stat("Deliveries accepted", fmt.int(total("delivered")), `${fmt.int(total("failed"))} refused · ${fmt.int(total("expired"))} lapsed`),
        stat(h("span", { class: "truth-tag", title: "Hidden from everyone in town" }, icon("eye", 12), "True quality"), total("delivered") ? fmt.num(total("quality") / total("delivered"), 2) : "–", `${fmt.int(total("defective"))} latent defects · ${fmt.int(total("defects_discovered"))} found`, "truth"),
        stat("Claims refused", fmt.int(rows.reduce((a, r) => a + (r.rejected.claim_task ?? 0), 0)), `of ${fmt.int(rows.reduce((a, r) => a + (r.decisions.claim_task ?? 0), 0))} attempts`),
        stat("Things said", fmt.int(total("utterances")), `${fmt.plural(total("conversations"), "conversation")}`),
      ),
      h("div", { class: "figures" }, emphasisChart("Balance", "Credits at the end of each day; the others in grey.", "balance", fmt.int, { zero: true }, moment, made), emphasisChart("Esteem", "As published each night, from 1 to 5.", "esteem", (v) => fmt.num(v, 2), { max: 5 }, moment, made)),
      h(
        "div",
        { class: "two-col section" },
        h(
          "section",
          { class: "card pad" },
          h("div", { class: "spread" }, h("h2", {}, "Policy"), h("a", { href: href({ ...route, query: { ...route.query, tab: "policy" } }) }, `${fmt.plural(rewrites.length, "rewrite")} so far`)),
          h("p", { class: "note" }, "The agent's own statement of what it wants and how it goes about it."),
          state?.policy?.trim() ? markdown(state.policy) : h("p", { class: "muted" }, "Empty: the agent has not written a policy yet."),
        ),
        h(
          "section",
          { class: "card pad" },
          h("h2", {}, "Relationships"),
          h("p", { class: "note" }, `Through day ${moment.day}. Ratings are private; mean score and count.`),
          ties.size
            ? h(
                "div",
                { class: "table-wrap" },
                h(
                  "table",
                  { class: "data" },
                  h("thead", {}, h("tr", {}, h("th", { class: "sticky-col" }, "With"), h("th", { title: "Hours spent in the same scenes" }, "Hours"), h("th", { title: "Things said to them by name" }, "Said to"), h("th", { title: "Things they said to this agent by name" }, "Heard from"), h("th", { title: "Mean rating given them, and how many" }, "Rated them"), h("th", { title: "Mean rating they gave, and how many" }, "Rated by"))),
                  h(
                    "tbody",
                    {},
                    [...ties]
                      .sort((a, b) => b[1].minutes - a[1].minutes)
                      .map(([name, t]) => h("tr", {}, h("td", { class: "sticky-col" }, cast.chip(name, href({ ...route, agent: name }))), h("td", {}, fmt.num(t.minutes / 60, 1)), h("td", {}, fmt.int(t.toThem)), h("td", {}, fmt.int(t.fromThem)), h("td", {}, mean(t.gave)), h("td", {}, mean(t.got)))),
                  ),
                ),
              )
            : emptyState("No one yet."),
        ),
      ),
    ];
  }

  function policyTab(moment) {
    const changes = history.versions.filter((v) => v.changes.some((c) => c.path === "parameters/policy.md"));
    const shown = changes.filter((v) => v.time <= moment.time && v.time > 0);
    const later = changes.filter((v) => v.time > moment.time);
    const initial = cast.agent(agentName()).policy;
    const list = h("ol", { class: "policy-list" });
    const cards = shown.reverse().map((version) => {
      const body = h("div", { class: "policy-diff" }, h("div", { class: "loading" }, "Loading the change…"));
      source.version(agentName(), version.commit).then(
        (found) => {
          const files = parseDiff(found.diff).filter((file) => file.path === "parameters/policy.md");
          fill(body, files.map((file) => renderFile(file, cast)), h("details", {}, h("summary", {}, "The whole policy after this rewrite"), markdown(found.state.policy ?? "")));
        },
        (error) => fill(body, emptyState("This version could not be loaded.", error.message)),
      );
      return h(
        "li",
        { class: "card pad policy-card" },
        h("header", { class: "spread" }, h("h3", {}, `Day ${version.day}, ${hhmm(minuteOf(version.time))}`), h("div", { class: "row" }, levelTag(version), h("a", { class: "mono muted", href: href({ ...route, query: { ...route.query, tab: "history", v: version.commit } }) }, version.commit.slice(0, 8)))),
        h("div", { class: "reasoning" }, reasoning(version.body)),
        body,
      );
    });
    fill(list, cards);
    return [
      h("p", { class: "note" }, initial ? "The policy the agent started with is in its profile; every rewrite since is below, newest first, with the agent's reasoning and what changed." : "The agent started without a policy. Every rewrite since is below, newest first, with the agent's reasoning and what changed."),
      shown.length ? list : h("div", { class: "card" }, emptyState(`No rewrite by the end of day ${moment.day}.`, world.evolution.levels.includes("L2") ? `Scheduled rewrites come every ${world.calendar.monthly_days} days; the agent may also ask for one.` : "Policy rewrites (L2) are not enabled in this experiment.")),
      later.length ? h("p", { class: "note" }, `${fmt.plural(later.length, "later rewrite")} after this moment. `, h("button", { type: "button", class: "ghost small", onclick: () => go({ t: null }) }, "Show the latest")) : null,
    ];
  }

  function historyTab(moment) {
    const filter = route.query.all === "1" ? "all" : "steps";
    const versions = history.versions.filter((v) => v.time <= moment.time).filter((v) => filter === "all" || v.level);
    const selected = route.query.v ?? versions.at(-1)?.commit;
    const detail = h("div", { class: "commit-detail card pad" });
    const list = h(
      "ol",
      { class: "commit-list" },
      [...versions].reverse().map((v) =>
        h(
          "li",
          {},
          h(
            "button",
            {
              type: "button",
              class: `commit${v.commit === selected ? " on" : ""}`,
              "aria-pressed": String(v.commit === selected),
              onclick: () => {
                reveal = true;
                go({ v: v.commit });
              },
            },
            h("span", { class: "commit-when" }, v.time === 0 ? "created" : `day ${v.day}`),
            levelTag(v),
            h("span", { class: "commit-subject" }, v.subject),
            h("span", { class: "commit-files" }, v.changes.map((c) => h("span", { title: c.path }, `${c.path.split("/").at(-1)} `, h("ins", {}, `+${c.added ?? "?"}`), " ", h("del", {}, `−${c.deleted ?? "?"}`)))),
          ),
        ),
      ),
    );
    const version = history.versions.find((v) => v.commit === selected);
    if (version) {
      fill(detail, h("div", { class: "loading" }, "Loading the version…"));
      source.version(agentName(), version.commit).then(
        (found) => {
          const files = parseDiff(found.diff);
          fill(
            detail,
            h("header", { class: "spread" }, h("h2", {}, version.subject), h("span", { class: "mono muted" }, version.commit.slice(0, 12))),
            h("p", { class: "note" }, `${version.time === 0 ? "The agent as created" : formatTime(version.time)} · `, levelTag(version)),
            version.level ? h("div", { class: "reasoning" }, h("h3", {}, "Reasoning"), reasoning(version.body)) : h("p", { class: "note" }, "An experience record: what the day added to memory. The episodic memory itself is left out of the bundle; the event log holds what it records."),
            files.length ? files.map((file) => renderFile(file, cast)) : h("p", { class: "muted" }, "No readable change (only the episodic memory changed)."),
            h("p", { class: "note" }, `At this version: ${fmt.plural(Object.keys(found.state.skills).length, "skill note")}, ${fmt.plural(found.state.insights.length, "insight")}, ${fmt.plural(found.state.diary.length, "diary entry", "diary entries")}.`),
          );
          // On a narrow screen the version opens below the list: bring it into view.
          if (reveal && detail.getBoundingClientRect().top > window.innerHeight * 0.5) detail.scrollIntoView({ block: "start", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
          reveal = false;
        },
        (error) => fill(detail, emptyState("This version could not be loaded.", error.message)),
      );
    } else fill(detail, emptyState("No version to show."));
    return [
      h(
        "div",
        { class: "spread" },
        h("p", { class: "note" }, `Every commit of ${agentName()}'s repository up to the moment shown, newest first. Evolution steps carry the agent's reasoning; records hold each day's experience.`),
        h(
          "div",
          { class: "seg" },
          h("button", { type: "button", "aria-pressed": String(filter === "steps"), onclick: () => go({ all: null }) }, "Evolution steps"),
          h("button", { type: "button", "aria-pressed": String(filter === "all"), onclick: () => go({ all: "1" }) }, "Every version"),
        ),
      ),
      h("div", { class: "history-grid" }, h("div", { class: "card commit-scroll" }, list), detail),
    ];
  }

  function behaviour(subject, day) {
    const rows = measures.agents.filter((row) => row.agent === subject && row.day <= day);
    const sum = (field) => rows.reduce((a, row) => a + row[field], 0);
    const fromMe = measures.graph.filter((e) => e.day <= day && e.source === agentName() && e.target === subject);
    const together = fromMe.reduce((a, e) => a + e.minutes, 0);
    const myRatings = fromMe.reduce((a, e) => [a[0] + e.ratings, a[1] + e.ratings_sum], [0, 0]);
    const esteem = rows.findLast((row) => row.esteem !== null)?.esteem ?? null;
    return h(
      "dl",
      { class: "behaviour" },
      h("dt", {}, "deliveries"),
      h("dd", {}, `${fmt.int(sum("delivered"))} accepted, ${fmt.int(sum("failed"))} refused, ${fmt.int(sum("expired"))} lapsed`),
      h("dt", { class: "truth-dt" }, icon("eye", 12), "true quality"),
      h("dd", {}, sum("delivered") ? `${fmt.num(sum("quality") / sum("delivered"), 2)} mean · ${fmt.int(sum("defective"))} defective · ${fmt.int(sum("defects_discovered"))} found` : "–"),
      h("dt", {}, "esteem"),
      h("dd", {}, `${fmt.num(esteem, 2)} · ${fmt.plural(sum("ratings_received"), "rating")} received`),
      h("dt", {}, `with ${agentName()}`),
      h("dd", {}, `${fmt.num(together / 60, 1)} h together${myRatings[0] ? ` · rated by ${agentName()} ${fmt.num(myRatings[1] / myRatings[0], 1)} on average` : ""}`),
    );
  }

  async function mindTab(moment, version) {
    if (!version) return emptyState("No version yet.");
    const found = await source.version(agentName(), version.commit);
    const { insights, skills, diary } = found.state;
    const about = new Map();
    const general = [];
    for (const insight of insights) {
      if (insight.subject) (about.get(insight.subject) ?? about.set(insight.subject, []).get(insight.subject)).push(insight);
      else general.push(insight);
    }
    const diaryList = h("div", { class: "diary" });
    const days = [...diary].reverse();
    fill(
      diaryList,
      days.length
        ? days.map((day, i) => {
            const body = h("div", { class: "diary-text" });
            const entry = h("details", { class: "diary-entry", open: i === 0 }, h("summary", {}, h("b", {}, `Day ${day}`)), body);
            const loadText = () =>
              !body.childNodes.length &&
              source.diary(agentName(), day).then(
                (text) => fill(body, text ? markdown(text) : h("p", { class: "muted" }, "Not found.")),
                (error) => fill(body, emptyState("This entry could not be loaded.", error.message)),
              );
            entry.addEventListener("toggle", () => entry.open && loadText());
            if (i === 0) loadText();
            return entry;
          })
        : emptyState("No diary entry yet."),
    );
    const insightItem = (insight) => h("li", {}, h("p", {}, insight.text), h("span", { class: "muted small-text" }, `written day ${insight.day}`));
    return [
      h("p", { class: "note" }, `What ${agentName()} had written down by the end of day ${moment.day}: standing conclusions, procedures for itself, and a diary. Beside each belief about a person, how that person actually behaved, from the measures.`),
      h(
        "section",
        { class: "section" },
        h("h2", {}, "Beliefs about others"),
        about.size
          ? h(
              "div",
              { class: "beliefs" },
              [...about].map(([subject, list]) =>
                h(
                  "article",
                  { class: "card belief" },
                  h("header", {}, cast.has(subject) ? cast.chip(subject, href({ ...route, agent: subject })) : h("b", {}, subject)),
                  h("div", { class: "belief-grid" }, h("div", {}, h("h4", {}, `${agentName()} believes`), h("ul", { class: "insights" }, list.map(insightItem))), cast.has(subject) ? h("div", { class: "actual" }, h("h4", {}, `What ${subject} did, through day ${moment.day}`), behaviour(subject, moment.day)) : null),
                ),
              ),
            )
          : h("div", { class: "card" }, emptyState("No beliefs about particular people yet.")),
      ),
      h("section", { class: "section" }, h("h2", {}, "About itself and the town"), general.length ? h("ul", { class: "insights card pad" }, general.map(insightItem)) : h("div", { class: "card" }, emptyState("Nothing yet."))),
      h(
        "section",
        { class: "section" },
        h("h2", {}, "Skills"),
        Object.keys(skills).length
          ? h(
              "div",
              { class: "skills" },
              Object.entries(skills).map(([name, text]) => {
                const { meta, body } = frontMatter(text);
                return h("details", { class: "card skill" }, h("summary", {}, h("b", {}, name), meta.description ? h("span", { class: "muted" }, ` — ${meta.description}`) : null), markdown(body));
              }),
            )
          : h("div", { class: "card" }, emptyState("No skill notes yet.", world.evolution.levels.includes("L1") ? `Skills are reviewed every ${world.calendar.weekly_days} days.` : "Skill reviews (L1) are not enabled.")),
      ),
      h("section", { class: "section" }, h("h2", {}, "Diary"), diaryList),
    ];
  }

  async function decisionsTab(moment) {
    const time = parseStamp(route.query.t);
    const lastDay = Math.max(1, source.doc.last_day);
    const day = Number(route.query.day) || Math.max(1, Math.min(lastDay, time !== null ? dayOf(time) : moment.day || 1));
    const events = await source.eventDay(day);
    const tasks = new Map(events.filter((e) => e.kind === "task_posted").map((e) => [e.payload.task.id, e]));
    const m = { cast, places, lookups: { tasks, places }, truth: true, select: (name) => ctx.navigate({ ...route, agent: name }) };
    const mine = events.filter((e) => e.kind === "decision" && e.actor === agentName());
    const picker = h(
      "div",
      { class: "row" },
      h("button", { type: "button", class: "icon-btn", disabled: day <= 1, "aria-label": "Previous day", onclick: () => go({ day: String(day - 1) }) }, icon("chevronLeft", 18)),
      h("b", {}, `Day ${day}`),
      h("button", { type: "button", class: "icon-btn", disabled: day >= lastDay, "aria-label": "Next day", onclick: () => go({ day: String(day + 1) }) }, icon("chevron", 18)),
      h("span", { class: "muted" }, `${fmt.plural(mine.length, "decision")}`),
    );
    return [
      h("div", { class: "spread" }, h("p", { class: "note" }, `Every choice ${agentName()} made on the day, with the private thought behind it and what came of it. Where it spoke, the thought and the words stand side by side.`), picker),
      mine.length
        ? h(
            "div",
            { class: "decisions" },
            mine.map((e) =>
              decisionCard(
                e,
                events.filter((x) => x.time === e.time),
                m,
                { extra: h("a", { class: "ghost small", href: href(sibling({ ...route, query: { t: stamp(e.time) } }, "town", { query: { agent: agentName() } })) }, icon("map", 13), "Watch in town") },
              ),
            ),
          )
        : h("div", { class: "card" }, emptyState(`${agentName()} made no decision on day ${day}.`)),
    ];
  }

  function traitsTab(moment, version, made) {
    if (!evaluation.scores.length) return h("div", { class: "card" }, emptyState("This run has not been evaluated yet.", "Evaluate chosen days with ", h("code", {}, `python -m experiments.evaluate runs/${route.experiment}/${route.run} --days 0 7 14`), "."));
    const rows = evaluation.scores.filter((row) => row.agent === agentName());
    return [
      h("p", { class: "note" }, "Held-out probes played on frozen copies of this agent; higher means more of the trait."),
      h("div", { class: "figures four" }, traitFigures(evaluation, cast, { only: agentName(), into: made })),
      h(
        "div",
        { class: "card pad section table-wrap" },
        h(
          "table",
          { class: "data text" },
          h("thead", {}, h("tr", {}, h("th", {}, "Day"), h("th", {}, "Trait"), h("th", {}, "Score"), h("th", {}, "Measures"), h("th", {}, ""))),
          h(
            "tbody",
            {},
            rows.map((row) =>
              h(
                "tr",
                {},
                h("td", {}, String(row.day)),
                h("td", {}, row.dimension.replaceAll("_", " ")),
                h("td", {}, row.score === null ? "unscored" : fmt.num(row.score, 2)),
                h("td", {}, Object.entries(row.measures).map(([k, v]) => `${k.replaceAll("_", " ")} ${typeof v === "number" ? fmt.num(v, 2) : v}`).join(" · ")),
                h("td", {}, h("a", { href: href(sibling(route, "evaluation", { query: { agent: agentName(), day: String(row.day), probe: row.probe } })) }, "transcripts")),
              ),
            ),
          ),
        ),
      ),
    ];
  }

  /**
   * Show the file. The new content is built before anything is replaced, so the page keeps its
   * height and scroll position instead of flashing a loading line between tabs and versions.
   */
  async function render() {
    const ticket = ++token;
    const made = [];
    try {
      [measures, history, evaluation] = await Promise.all([source.measures(), source.versions(agentName()), source.evaluation()]);
      if (ticket !== token) return;
      const moment = asOf();
      const version = versionAt(moment.time);
      if (!page.querySelector(".person-body")) fill(page, head(moment), h("div", { class: "person-body" }, h("div", { class: "loading" }, "Loading…")));
      const content = await { overview, policy: policyTab, history: historyTab, mind: mindTab, decisions: decisionsTab, traits: traitsTab }[tab()](moment, version, made);
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
      if (changes && (changes.agents.includes(agentName()) || changes.measures || changes.evaluation) && !route.query.v) render();
    },
    destroy() {
      for (const chart of charts) chart.destroy();
    },
  };
}
