// The town's panels. Each renders one moment: `m` holds the replay state, the day's events up
// to that moment, whether the truth is shown and who is selected.

import { hhmm, minuteOf } from "../clock.js";
import { emptyState, fill, fmt, h } from "../dom.js";
import { icon } from "../icons.js";
import { holdings } from "../replay.js";
import { shortName } from "../world.js";
import { actionSummary, actionTexts, clockOf, feedItems, glyph, involved, isPublic, isTruth, line, sceneName } from "./events.js";

const truthTag = (label = "truth") => h("span", { class: "truth-tag" }, icon("eye", 13), label);

/** Events of the same turn that do not follow from anyone's decision in it. */
const BACKGROUND = new Set(["decision", "living_cost", "esteem_updated", "evolution", "scene_started", "scene_ended", "day_started", "day_ended"]);

/** What came of an agent's decision: what happened to it in the same turn, its own ratings. */
function outcomes(events, agent, m) {
  return events
    .filter((e) => !BACKGROUND.has(e.kind) && involved(e).includes(agent) && (e.kind !== "rating" || e.payload.rater === agent) && !(e.kind === "speech" && e.actor === agent) && (m.truth || isPublic(e)))
    .map((e) => h("li", { class: `${isTruth(e) ? "truth-line" : ""}` }, glyph(e), line(e, m.cast, m.lookups), e.kind === "draw" ? ` (${ordinal(e.payload.order.indexOf(agent) + 1)})` : ""));
}

const ordinal = (n) => `${n}${["th", "st", "nd", "rd"][n % 100 > 10 && n % 100 < 14 ? 0 : n % 10 < 4 ? n % 10 : 0]}`;

/** A decision with the thought behind it and what came of it. */
export function decisionCard(decision, events, m, { focus = false, extra = null } = {}) {
  const { action, thought } = decision.payload;
  const place = m.places.get(decision.place);
  const result = outcomes(events, decision.actor, m);
  const texts = actionTexts(action);
  const thinking = m.truth ? h("div", { class: "truth thought" }, truthTag("thought"), h("p", {}, thought)) : null;
  return h(
    "article",
    { class: `decision${focus ? " focus" : ""}`, "data-agent": decision.actor },
    h(
      "header",
      {},
      h("button", { type: "button", class: "linkish", onclick: () => m.select(decision.actor) }, m.cast.badge(decision.actor, 20), h("b", {}, decision.actor)),
      h("span", { class: "muted" }, `${place ? shortName(place) : ""} · ${clockOf(decision)}`),
      extra ? h("span", { class: "decision-extra" }, extra) : null,
      h("span", { class: "action-kind" }, actionSummary(action, m.lookups)),
    ),
    texts.length
      ? h(
          "div",
          { class: "pair" },
          thinking,
          texts.map(([field, text]) => h("div", { class: "said" }, h("span", { class: "said-tag" }, icon("speech", 13), field === "said" ? (action.to ? `said to ${action.to}` : "said") : field.replaceAll("_", " ")), h("p", {}, text))),
        )
      : thinking,
    action.kind === "submit_work" && m.truth ? h("details", { class: "code" }, h("summary", {}, "Delivered code and report"), h("p", {}, action.report), h("pre", {}, action.solution)) : null,
    action.kind === "plan_day" && action.intention ? h("p", { class: "intention" }, h("span", { class: "muted" }, "Intends: "), action.intention) : null,
    result.length ? h("ul", { class: "outcomes" }, result) : null,
  );
}

/** The moment: the scenes in progress and, in the latest turn, each decision with its thought. */
export class NowPanel {
  constructor() {
    this.el = h("div", { class: "panel now" });
    this.key = null;
  }

  update(m) {
    const key = `${m.state.seq}|${m.truth}|${m.selected}`;
    if (key === this.key) return;
    this.key = key;
    const decisions = m.dayEvents.filter((e) => e.kind === "decision");
    const latest = decisions.at(-1);
    const scenes = Object.entries(m.state.scenes);
    const head = h(
      "div",
      { class: "now-head" },
      h("h3", {}, m.phase),
      scenes.length
        ? h(
            "ul",
            { class: "scenes" },
            scenes.map(([, scene]) => {
              const place = m.places.get(scene.place);
              const round = Math.floor((m.state.time - scene.start) / m.world.scenes.turn_minutes) + 1;
              const most = scene.kind === "work" ? m.world.scenes.work_rounds : scene.kind === "conversation" ? m.world.scenes.conversation_turns : null;
              return h(
                "li",
                {},
                h("span", { class: "scene-name" }, h("b", {}, sceneName(scene.kind)), place ? ` · ${shortName(place)}` : "", most ? h("span", { class: "muted" }, ` · ${scene.kind === "work" ? "round" : "turn"} ${Math.min(round, most)} of ${most}`) : null),
                h("span", { class: "present" }, scene.present.map((name) => m.cast.badge(name, 16))),
                h("span", { class: "sr" }, scene.present.join(", ")),
              );
            }),
          )
        : null,
    );
    if (!latest) {
      fill(this.el, head, emptyState(m.state.day ? "Nobody has decided anything yet today." : "The run has not begun its first day here.", "Press play, or step through the moments."));
      return;
    }
    const turn = m.dayEvents.filter((e) => e.time === latest.time);
    const inTurn = turn.filter((e) => e.kind === "decision");
    const order = (e) => (e.actor === m.selected ? -1 : m.cast.names.indexOf(e.actor));
    inTurn.sort((a, b) => order(a) - order(b));
    const ago = m.state.time - latest.time;
    const body = [];
    if (m.selected && !inTurn.some((e) => e.actor === m.selected)) {
      const own = decisions.findLast((e) => e.actor === m.selected);
      if (own) body.push(h("p", { class: "turn-label" }, `${m.selected}'s latest decision, ${clockOf(own)}`), decisionCard(own, m.dayEvents.filter((e) => e.time === own.time), m, { focus: true }));
    }
    body.push(h("p", { class: "turn-label" }, ago > 0 ? `The latest turn, ${ago} min ago at ${clockOf(latest)}` : `This turn, ${clockOf(latest)}`, m.truth ? null : h("span", { class: "muted" }, " · thoughts hidden")));
    if (m.truth) body.push(...inTurn.map((e) => decisionCard(e, turn, m, { focus: e.actor === m.selected })));
    else {
      const seen = turn.filter((e) => isPublic(e) && e.kind !== "decision");
      body.push(seen.length ? h("ul", { class: "outcomes public" }, seen.map((e) => h("li", {}, glyph(e), line(e, m.cast, m.lookups)))) : emptyState("Nothing anyone could perceive happened in this turn."));
    }
    fill(this.el, head, h("div", { class: "turn" }, body));
  }
}

/** The people of the town at the moment: where each is, what they hold, how they fare. */
export class PeoplePanel {
  constructor() {
    this.el = h("div", { class: "panel people" });
    this.key = null;
  }

  update(m) {
    const key = `${m.state.seq}|${m.selected}`;
    if (key === this.key) return;
    this.key = key;
    const holding = holdings(m.state);
    fill(
      this.el,
      h(
        "ul",
        { class: "people-list" },
        m.cast.names.map((name) => {
          const place = m.places.get(m.state.locations[name]);
          const balance = m.state.balances[name];
          const delta = m.dayStart ? balance - m.dayStart[name] : 0;
          const esteem = m.state.esteem[name];
          return h(
            "li",
            {},
            h(
              "button",
              { type: "button", class: `person-row${m.selected === name ? " on" : ""}`, "aria-pressed": String(m.selected === name), onclick: () => m.select(name) },
              m.cast.badge(name, 28),
              h("span", { class: "person-main" }, h("b", {}, name), h("span", { class: "muted" }, place ? shortName(place) : "", holding[name] ? ` · holds ${holding[name]}` : "")),
              h(
                "span",
                { class: "person-figures" },
                h("span", { class: `money${balance < 0 ? " debt" : ""}`, title: "Balance, and its change since the day began" }, fmt.credits(balance), delta ? h("small", { class: delta > 0 ? "up" : "down" }, ` ${fmt.signed(delta)}`) : null),
                h("span", { class: "esteem", title: "Esteem as last published" }, icon("star", 12), esteem === null ? "–" : fmt.num(esteem, 1)),
              ),
            ),
          );
        }),
      ),
    );
  }
}

/** Everything that happened today up to the moment, as the town perceived it or as it was. */
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
    const key = `${m.state.seq}|${m.truth}|${m.selected}|${m.follow}`;
    if (key === this.key && !force) return;
    this.key = key;
    fill(
      this.bar,
      h("span", { class: "muted" }, m.truth ? "Everything that happened" : "What the town's people perceived"),
      m.selected ? h("button", { type: "button", class: "ghost small", "aria-pressed": String(m.follow), onclick: () => this.onFollow(!m.follow) }, m.cast.badge(m.selected, 14), m.follow ? `Only ${m.selected}` : `Follow ${m.selected}`) : null,
    );
    let events = m.dayEvents.filter((e) => e.kind !== "scene_ended" && e.kind !== "day_ended");
    if (!m.truth) events = events.filter((e) => isPublic(e) || e.kind === "scene_started" || e.kind === "day_started");
    if (m.selected && m.follow)
      events = events.filter((e) => (m.truth ? involved(e).includes(m.selected) : e.audience.includes(m.selected) || e.actor === m.selected) || (e.kind === "scene_started" && e.payload.participants?.includes(m.selected)) || e.kind === "day_started");
    const items = feedItems(events);
    let lastTime = null;
    const rows = [];
    for (const item of items) {
      if (item.time !== lastTime) {
        rows.push(h("li", { class: "feed-time" }, hhmm(minuteOf(item.time))));
        lastTime = item.time;
      }
      rows.push(this.item(item, m));
    }
    this.list.replaceChildren(...(rows.length ? rows : [h("li", {}, emptyState("Nothing yet today."))]));
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
    if (item.summary) {
      const truth = item.events.every(isTruth);
      const opened = this.open.has(key);
      return h(
        "li",
        { class: `feed-item group${truth ? " truth" : ""}` },
        h("button", { type: "button", class: "group-head", "aria-expanded": String(opened), onclick: toggle }, glyph(item.events[0]), h("span", {}, item.summary), truth ? truthTag() : null, icon(opened ? "down" : "chevron", 14)),
        opened ? h("ul", { class: "group-items" }, item.events.map((e) => h("li", {}, line(e, m.cast, m.lookups)))) : null,
      );
    }
    const e = item.event;
    if (e.kind === "scene_started") {
      const place = m.places.get(e.place);
      return h("li", { class: "feed-scene" }, h("span", {}, `${sceneName(e.payload.kind)}${place ? ` · ${shortName(place)}` : ""}`), h("span", { class: "present" }, (e.payload.participants ?? []).map((name) => m.cast.badge(name, 14))));
    }
    if (e.kind === "day_started") return h("li", { class: "feed-scene" }, h("span", {}, `Day ${m.state.day || ""} begins`));
    if (e.kind === "decision") {
      const opened = this.open.has(key);
      return h(
        "li",
        { class: "feed-item truth decision-item" },
        h("div", { class: "feed-line" }, glyph(e), line(e, m.cast, m.lookups)),
        h("button", { type: "button", class: `thought-line${opened ? " open" : ""}`, onclick: toggle, "aria-expanded": String(opened), title: opened ? "Fold the thought" : "Read the whole thought" }, e.payload.thought),
      );
    }
    return h(
      "li",
      { class: `feed-item${isTruth(e) ? " truth" : ""}${e.audience.length === 1 && e.kind !== "draw" ? " private" : ""}` },
      h("div", { class: "feed-line" }, glyph(e), line(e, m.cast, m.lookups), isTruth(e) ? truthTag() : null),
      e.kind === "work_submitted" && e.payload.report && !e.text.includes(e.payload.report) ? h("p", { class: "report" }, e.payload.report) : null,
    );
  }
}

/** The task board at the moment: open, claimed, and what was delivered today. */
export class BoardPanel {
  constructor({ replay }) {
    this.replay = replay;
    this.el = h("div", { class: "panel board" });
    this.open = new Set();
    this.key = null;
  }

  update(m, force = false) {
    const key = `${m.state.seq}|${m.truth}`;
    if (key === this.key && !force) return;
    this.key = key;
    const task = (id) => this.replay.tasks.get(id)?.payload.task;
    const posted = (id) => this.replay.tasks.get(id);
    const row = (id, extra, cls = "") => {
      const t = task(id);
      const opened = this.open.has(id);
      return h(
        "li",
        { class: `task ${cls}` },
        h(
          "button",
          {
            type: "button",
            class: "task-head",
            "aria-expanded": String(opened),
            onclick: () => {
              if (opened) this.open.delete(id);
              else this.open.add(id);
              this.update(m, true);
            },
          },
          h("span", { class: "task-reward" }, t ? `${t.reward}` : "?", h("small", {}, "cr")),
          h("span", { class: "task-title" }, h("b", {}, t?.title ?? id), h("span", { class: "muted" }, `${id} · ${t ? fmt.plural(t.deadline_days, "day") : "?"} to deliver · posted day ${posted(id) ? Math.floor(posted(id).time / 1440) + 1 : "?"}`)),
          extra,
        ),
        opened ? this.detail(id, m) : null,
      );
    };
    const open = Object.keys(m.state.open).sort((a, b) => (task(b)?.reward ?? 0) - (task(a)?.reward ?? 0));
    const claimed = Object.entries(m.state.claims);
    const delivered = m.dayEvents.filter((e) => e.kind === "work_submitted" && e.payload.passed);
    const quality = new Map(m.dayEvents.filter((e) => e.kind === "work_assessed").map((e) => [`${e.actor}/${e.payload.task_id}`, e.payload.quality]));
    fill(
      this.el,
      h("p", { class: "note" }, `${m.state.conditions.tasks_per_day} tasks are posted each morning; one claim at a time; unclaimed tasks leave after ${m.world.task_shelf_life_days} days.`),
      h("h4", {}, `Open · ${open.length}`),
      open.length ? h("ul", { class: "tasks" }, open.map((id) => row(id, null))) : h("p", { class: "muted pad-s" }, "The board is empty."),
      h("h4", {}, `Claimed · ${claimed.length}`),
      claimed.length ? h("ul", { class: "tasks" }, claimed.map(([id, claim]) => row(id, h("span", { class: "task-who" }, m.cast.badge(claim.agent, 16), `due day ${claim.due_day}`), "claimed"))) : h("p", { class: "muted pad-s" }, "Nobody holds a task."),
      h("h4", {}, `Delivered today · ${delivered.length}`),
      delivered.length
        ? h(
            "ul",
            { class: "tasks" },
            delivered.map((e) => {
              const q = quality.get(`${e.actor}/${e.payload.task_id}`);
              return row(e.payload.task_id, h("span", { class: "task-who" }, m.cast.badge(e.actor, 16), m.truth && q !== undefined ? h("span", { class: `quality${q < 1 ? " flawed" : ""}`, title: "True quality: the share of hidden checks passed" }, icon("eye", 12), fmt.num(q, 2)) : null), "done");
            }),
          )
        : h("p", { class: "muted pad-s" }, "Nothing yet."),
    );
  }

  detail(id, m) {
    const t = this.replay.tasks.get(id)?.payload.task;
    const history = this.replay.taskEvents(id, m.state.seq).filter((e) => m.truth || isPublic(e));
    return h(
      "div",
      { class: "task-detail" },
      t ? h("pre", { class: "spec" }, t.specification) : null,
      h(
        "ol",
        { class: "task-history" },
        history.map((e) =>
          h(
            "li",
            { class: isTruth(e) ? "truth-line" : "" },
            h("span", { class: "muted" }, `Day ${Math.floor(e.time / 1440) + 1} ${clockOf(e)} `),
            line(e, m.cast, m.lookups),
            e.kind === "work_submitted" && m.truth ? h("details", { class: "code" }, h("summary", {}, "code"), h("pre", {}, e.payload.solution)) : null,
          ),
        ),
      ),
    );
  }
}

/** The day so far in its notable moments; each one jumps there. */
export class ChroniclePanel {
  constructor({ onJump }) {
    this.el = h("div", { class: "panel chronicle" });
    this.onJump = onJump;
    this.key = null;
  }

  update(m) {
    const key = `${m.state.seq}|${m.truth}`;
    if (key === this.key) return;
    this.key = key;
    const notes = [];
    const add = (e, text, cls = "") => notes.push({ e, text, cls });
    const scenes = new Map();
    for (const e of m.dayEvents) {
      const p = e.payload ?? {};
      switch (e.kind) {
        case "announcement":
          add(e, ["Announced to everyone: ", h("q", {}, e.text)]);
          break;
        case "intervention":
          if (m.truth) add(e, ["Conditions changed", !m.dayEvents.some((x) => x.kind === "announcement" && x.time === e.time) ? " without an announcement" : "", `: ${Object.entries(p.changes ?? {}).map(([k, v]) => `${k.replaceAll("_", " ")} → ${v}`).join(", ")}`], "truth-line");
          break;
        case "defect_discovered":
          add(e, [m.cast.mention(`A defect came to light in ${p.worker}'s delivery of ${p.task_id}`), ` (true quality ${fmt.num(p.quality, 2)})`], "critical");
          break;
        case "draw":
          add(e, [m.cast.mention(`${p.order[0]} won the draw for ${p.task_id} over ${p.order.slice(1).join(", ")}`)]);
          break;
        case "work_submitted":
          if (p.passed) add(e, [m.cast.mention(`${e.actor} delivered ${p.task_id}`), ", accepted"]);
          else if (m.truth || e.audience.length) add(e, [m.cast.mention(`${e.actor}'s delivery of ${p.task_id} was refused by the checks`)], "serious");
          break;
        case "work_assessed":
          if (m.truth && p.passed && p.quality < 1) add(e, [m.cast.mention(`${e.actor}'s accepted ${p.task_id} hides a defect`), `: true quality ${fmt.num(p.quality, 2)}`], "truth-line critical");
          break;
        case "task_expired":
          add(e, [m.cast.mention(`${p.agent} let ${p.task_id} lapse`)], "critical");
          break;
        case "scene_started":
          if (p.kind === "conversation") scenes.set(e.scene, { e, said: 0, people: p.participants ?? [] });
          break;
        case "speech":
          if (scenes.has(e.scene)) scenes.get(e.scene).said += 1;
          break;
        case "rating":
          if (m.truth && p.score <= 2) add(e, [m.cast.mention(`${p.rater} rated ${p.target} ${p.score} of 5`), ": ", h("q", {}, p.reason)], "truth-line");
          break;
        case "evolution":
          if (m.truth && p.level !== "L0") add(e, [m.cast.mention(`${p.agent}`), ` · ${p.subject}`, p.trigger === "self" ? " (asked for)" : ""], "truth-line");
          break;
        case "action_rejected":
          if (p.attempt?.kind === "move") add(e, [m.cast.mention(`${e.actor} found it closed`), `: ${p.reason}`], "warn");
          break;
      }
    }
    for (const { e, said, people } of scenes.values()) {
      const place = m.places.get(e.place);
      add(e, [`A conversation at ${place ? shortName(place) : e.place}: `, people.map((name) => m.cast.badge(name, 14)), ` ${fmt.plural(said, "thing")} said`]);
    }
    notes.sort((a, b) => a.e.seq - b.e.seq);
    const balances = Object.entries(m.state.balances).sort((a, b) => a[1] - b[1]);
    const broke = balances.filter(([, v]) => v < 0);
    fill(
      this.el,
      h("p", { class: "note" }, `Day ${m.state.day || 1} up to ${hhmm(minuteOf(m.state.time))}, in its notable moments. Pick one to go there.`),
      notes.length
        ? h(
            "ol",
            { class: "chronicle-list" },
            notes.map(({ e, text, cls }) => h("li", { class: cls }, h("button", { type: "button", class: "linkish", onclick: () => this.onJump(e.time) }, h("span", { class: "chron-time" }, clockOf(e)), h("span", {}, text)))),
          )
        : emptyState("Nothing notable yet today."),
      broke.length ? h("p", { class: "note" }, "In debt: ", broke.map(([name, v], i) => [i ? ", " : "", m.cast.mention(name), ` ${fmt.credits(v)}`])) : null,
    );
  }
}
