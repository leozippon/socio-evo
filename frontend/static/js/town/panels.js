// The town's panels. Each renders one moment: `m` holds the replay state, the day's events up
// to that moment, whether the truth is shown, who is selected and whose wording is read.

import { dayOf, hhmmss, minuteOf } from "../clock.js";
import { emptyState, fill, fmt, h } from "../dom.js";
import { icon } from "../icons.js";
import { current, holdings } from "../replay.js";
import { shortName } from "../world.js";
import { actionCode, actionSummary, actionTexts, clientMark, clockOf, feedItems, glyph, handedAs, involved, isPublic, isTruth, jobName, line, partName, partsOf, priceOf, sceneName, shown, witnessed } from "./events.js";

const truthTag = (label = "truth") => h("span", { class: "truth-tag" }, icon("eye", 13), label);

/** Events of the same turn that do not follow from anyone's decision in it. */
const BACKGROUND = new Set(["decision", "living_cost", "esteem_updated", "evolution", "scene_started", "scene_ended", "day_started", "day_ended"]);

/** Whether an event belongs in the view `m` shows: the truth, or what someone perceived. */
const visible = (e, m) => (m.truth || isPublic(e)) && shown(e);

/** What came of an agent's decision: what followed it in the same turn and concerns it. */
function outcomes(events, decision, m) {
  const agent = decision.actor;
  return events.filter((e) => e.seq > decision.seq && !BACKGROUND.has(e.kind) && involved(e).includes(agent) && (e.kind !== "rating" || e.payload.rater === agent) && !(e.kind === "speech" && e.actor === agent) && visible(e, m));
}

const outcomeItem = (e, m, agent = null) => h("li", { class: isTruth(e) ? "truth-line" : "" }, glyph(e), line(e, m), e.kind === "draw" && agent ? ` (${ordinal(e.payload.order.indexOf(agent) + 1)})` : "");

const ordinal = (n) => `${n}${["th", "st", "nd", "rd"][n % 100 > 10 && n % 100 < 14 ? 0 : n % 10 < 4 ? n % 10 : 0]}`;

/** Code, folded until asked for. */
const codeBlock = (label, code) => h("details", { class: "code" }, h("summary", {}, icon("code", 13), label, h("span", { class: "muted" }, ` · ${fmt.plural(code.split("\n").length, "line")}`)), h("pre", {}, code));

/** A decision with the thought behind it, what it said or handed in, and what came of it. */
export function decisionCard(decision, events, m, { focus = false, extra = null } = {}) {
  const { action, thought } = decision.payload;
  const place = m.places.get(decision.place);
  const result = outcomes(events, decision, m);
  const texts = actionTexts(action);
  const code = m.truth ? actionCode(action) : null;
  const thinking = m.truth ? h("div", { class: "truth thought" }, truthTag("thought"), h("p", {}, thought?.trim() ? thought : "No thought recorded for this decision.")) : null;
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
          texts.map(([label, text]) => h("div", { class: `said${action.private ? " private" : ""}` }, h("span", { class: "said-tag" }, icon(action.private ? "lock" : "speech", 13), label), h("p", {}, text))),
        )
      : thinking,
    code ? codeBlock(...code) : null,
    action.kind === "plan_day" && action.intention ? h("p", { class: "intention" }, h("span", { class: "muted" }, "Intends: "), action.intention) : null,
    result.length ? h("ul", { class: "outcomes" }, result.map((e) => outcomeItem(e, m, decision.actor))) : null,
  );
}

const FATES = { open: "open", "taken up": "taken up", withdrawn: "withdrawn", ended: "job went elsewhere", lapsed: "lapsed" };

/** Today's askings and what became of each, so far. */
function askingList(m) {
  const askings = m.state.askings;
  if (!askings.length) return null;
  return h(
    "ul",
    { class: "askings", "aria-label": "Askings today" },
    askings.map((asking) =>
      h(
        "li",
        { class: `asking fate-${asking.fate.replace(" ", "-")}` },
        h("span", { class: "asking-who" }, m.cast.badge(asking.asker, 15), icon("ask", 13), m.cast.badge(asking.partner, 15)),
        h("span", { class: "asking-what" }, m.cast.mention(`${asking.asker} asked ${asking.partner}`), h("span", { class: "muted" }, ` · ${jobName(asking.task_id)} · ${hhmmss(minuteOf(asking.time))}`)),
        h("span", { class: "fate" }, FATES[asking.fate] ?? asking.fate),
      ),
    ),
  );
}

/** The moment: the scenes in progress and, in the latest turn, each decision with its thought. */
export class NowPanel {
  constructor() {
    this.el = h("div", { class: "panel now" });
    this.key = null;
  }

  update(m) {
    const key = `${m.state.seq}|${m.truth}|${m.selected}|${m.reader}`;
    if (key === this.key) return;
    this.key = key;
    const decisions = m.dayEvents.filter((e) => e.kind === "decision");
    const latest = decisions.at(-1);
    const scenes = Object.entries(m.state.scenes);
    const asks = askingList(m);
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
      asks ? h("details", { class: "asks", open: true }, h("summary", {}, `Askings today · ${m.state.askings.length}`), asks) : null,
    );
    // What the town learnt that is no one's decision's outcome: the morning's notices, pairs
    // the clerk formed, and anything since the latest turn but comings and goings.
    const newsOf = (turn, told) => m.dayEvents.filter((e) => !BACKGROUND.has(e.kind) && !told.has(e.seq) && visible(e, m) && (latest ? e.time > latest.time ? e.kind !== "move" && e.kind !== "left" : e.time === latest.time : true));
    if (!latest) {
      const news = newsOf([], new Set());
      fill(this.el, head, news.length ? h("ul", { class: "outcomes news" }, news.map((e) => outcomeItem(e, m))) : null, emptyState(m.state.day ? "Nobody has decided anything yet today." : "The run has not begun its first day here.", "Press play, or step through the moments."));
      return;
    }
    const turn = m.dayEvents.filter((e) => e.time === latest.time);
    const inTurn = turn.filter((e) => e.kind === "decision");
    const order = (e) => (e.actor === m.selected ? -1 : m.cast.names.indexOf(e.actor));
    inTurn.sort((a, b) => order(a) - order(b));
    const ago = m.state.time - latest.time;
    const body = [];
    if (m.selected && m.truth && !inTurn.some((e) => e.actor === m.selected)) {
      const own = decisions.findLast((e) => e.actor === m.selected);
      if (own) body.push(h("p", { class: "turn-label" }, `${m.selected}'s latest decision, ${clockOf(own)}`), decisionCard(own, m.dayEvents.filter((e) => e.time === own.time), m, { focus: true }));
    }
    body.push(h("p", { class: "turn-label" }, ago > 0 ? `The latest turn, ${Math.round(ago * 60)} sec ago at ${clockOf(latest)}` : `This turn, ${clockOf(latest)}`, m.truth ? null : h("span", { class: "muted" }, " · thoughts hidden")));
    if (m.truth) {
      const told = new Set(inTurn.flatMap((d) => outcomes(turn, d, m).map((e) => e.seq)));
      // What the town learnt before the turn's decisions (the morning's notices) comes first.
      const news = newsOf(turn, told);
      const first = inTurn.length ? Math.min(...inTurn.map((e) => e.seq)) : Infinity;
      const before = news.filter((e) => e.seq < first);
      const after = news.filter((e) => e.seq > first);
      const cards = inTurn.map((e) => decisionCard(e, turn, m, { focus: e.actor === m.selected }));
      body.pop();
      if (before.length) body.push(h("p", { class: "turn-label" }, `In the town, ${clockOf(latest)}`), h("ul", { class: "outcomes news" }, before.map((e) => outcomeItem(e, m))));
      body.push(h("p", { class: "turn-label" }, ago > 0 ? `The latest turn, ${Math.round(ago * 60)} sec ago at ${clockOf(latest)}` : `This turn, ${clockOf(latest)}`), ...cards);
      if (after.length) body.push(h("p", { class: "turn-label" }, "Also in the town"), h("ul", { class: "outcomes news" }, after.map((e) => outcomeItem(e, m))));
    } else {
      const seen = m.dayEvents.filter((e) => e.time >= latest.time && isPublic(e) && e.kind !== "decision" && shown(e) && (e.time === latest.time || (e.kind !== "move" && e.kind !== "left")));
      body.push(seen.length ? h("ul", { class: "outcomes public" }, seen.map((e) => outcomeItem(e, m))) : emptyState("Nothing anyone could perceive happened in this turn."));
    }
    fill(this.el, head, h("div", { class: "turn" }, body));
  }
}

/** A resident's job and bids, in a few words: what it works on, with whom, how far along. */
export function jobStatus(name, m) {
  const id = holdings(m.state)[name];
  const bits = [];
  if (id) {
    const claim = m.state.claims[id];
    const partners = claim.workers.filter((worker) => worker !== name);
    const done = claim.parts.filter(Boolean).length;
    bits.push(`${jobName(id)}${partners.length ? ` with ${partners.join(", ")}` : ""}${claim.parts.length > 1 ? `, ${done} of ${claim.parts.length} parts in` : ""}`);
  }
  const offer = m.state.offers[name];
  if (offer) bits.push(offer.partner ? `asking ${offer.partner}, ${jobName(offer.task_id)}` : `name down for ${jobName(offer.task_id)}`);
  const askers = Object.entries(m.state.offers).filter(([, o]) => o.partner === name).map(([asker]) => asker);
  if (askers.length) bits.push(`asked by ${askers.join(", ")}`);
  return bits;
}

/** The people of the town at the moment: where each is, what they hold, how they fare. */
export class PeoplePanel {
  constructor() {
    this.el = h("div", { class: "panel people" });
    this.key = null;
  }

  update(m) {
    const key = `${m.state.seq}|${m.selected}|${m.truth}|${m.reader}`;
    if (key === this.key) return;
    this.key = key;
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
          const owes = m.cast.agent(name).obligation ?? 0;
          const status = jobStatus(name, m);
          const activity = m.state.sessions?.[name] ?? m.state.activities?.[name];
          const goal = (m.truth || m.reader === name) ? m.state.goals?.[name] : null;
          if (activity) status.push(`${activity.action?.operation ?? activity.action?.kind ?? "busy"} · ${clockOf({ time: activity.start })}${activity.end == null ? "–running" : "–ongoing"}`);
          if (goal) status.push(`Goal: ${goal}`);
          return h(
            "li",
            {},
            h(
              "button",
              { type: "button", class: `person-row${m.selected === name ? " on" : ""}`, "aria-pressed": String(m.selected === name), onclick: () => m.select(name) },
              m.cast.badge(name, 28),
              h("span", { class: "person-main" }, h("b", {}, name), h("span", { class: "muted" }, place ? `${m.state.outside?.[name] ? "Outside · " : ""}${shortName(place)}` : ""), status.length ? h("span", { class: "person-job" }, m.cast.mention(status.join(" · "))) : null),
              h(
                "span",
                { class: "person-figures" },
                h("span", { class: `money${balance < 0 ? " debt" : ""}`, title: "Money, and its change since the day began" }, fmt.money(balance), delta ? h("small", { class: delta > 0 ? "up" : "down" }, ` ${fmt.signed(delta)}`) : null),
                owes ? h("span", { class: "owes", title: "Owed every evening with the living costs" }, `owes ${owes} a day`) : null,
                h("span", { class: "esteem", title: "Standing as last posted beside the board" }, icon("star", 12), esteem === null ? "–" : fmt.num(esteem, 1)),
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
    const key = `${m.state.seq}|${m.truth}|${m.selected}|${m.follow}|${m.reader}`;
    if (key === this.key && !force) return;
    this.key = key;
    fill(
      this.bar,
      h("span", { class: "muted" }, m.truth ? "Everything that happened" : "What the town's people perceived"),
      m.selected ? h("button", { type: "button", class: "ghost small", "aria-pressed": String(m.follow), onclick: () => this.onFollow(!m.follow) }, m.cast.badge(m.selected, 14), m.follow ? `Only ${m.selected}` : `Follow ${m.selected}`) : null,
    );
    let events = m.dayEvents.filter((e) => e.kind !== "scene_ended" && e.kind !== "day_ended" && shown(e));
    if (!m.truth) events = events.filter((e) => isPublic(e) || e.kind === "scene_started" || e.kind === "day_started");
    if (m.selected && m.follow) {
      const heard = (e) => m.bystanders.get(e.seq)?.audience.includes(m.selected);
      events = events.filter((e) => ((m.truth && involved(e).includes(m.selected)) || witnessed(e, m.selected) || heard(e)) || (e.kind === "scene_started" && e.payload.participants?.includes(m.selected)) || e.kind === "day_started");
    }
    const items = feedItems(events);
    let lastTime = null;
    const rows = [];
    for (const item of items) {
      if (item.time !== lastTime) {
        rows.push(h("li", { class: "feed-time" }, hhmmss(minuteOf(item.time))));
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
        opened ? h("ul", { class: "group-items" }, item.events.map((e) => h("li", {}, line(e, m)))) : null,
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
        h("div", { class: "feed-line" }, glyph(e), line(e, m)),
        h("button", { type: "button", class: `thought-line${opened ? " open" : ""}`, onclick: toggle, "aria-expanded": String(opened), title: opened ? "Fold the thought" : "Read the whole thought" }, e.payload.thought),
      );
    }
    const personal = e.audience.length === 1 && !["draw", "speech"].includes(e.kind);
    return h(
      "li",
      { class: `feed-item${isTruth(e) ? " truth" : ""}${personal ? " private" : ""}` },
      h("div", { class: "feed-line" }, glyph(e), line(e, m), isTruth(e) ? truthTag() : null),
      e.kind === "work_submitted" && e.payload.report && !e.text.includes(e.payload.report) ? h("p", { class: "report" }, e.payload.report) : null,
    );
  }
}

/** A job's price: what each worker is paid if every part is handed in as finished. */
function priceLabel(task) {
  const parts = partsOf(task);
  const prices = parts.map((_, i) => priceOf(task, i));
  const label = (value, each, title) => {
    const [figure, unit] = fmt.moneyFigure(value);
    return { figure, unit: [unit, each ? "each" : ""].filter(Boolean).join(" "), title };
  };
  if (prices.every(Boolean)) return label(prices.reduce((a, p) => a + p.finished, 0), (task.required_workers ?? parts.length) > 1, task.strict_acceptance ? "Paid to each worker after official acceptance" : "Paid to each worker once every part is in, all as finished");
  return label(parts.reduce((a, p) => a + (p.reward ?? 0), 0), false, "The reward the notice offers");
}

/** The task board at the moment: open notices, jobs taken, and what was handed in today. */
export class BoardPanel {
  constructor({ replay }) {
    this.replay = replay;
    this.el = h("div", { class: "panel board" });
    this.open = new Set();
    this.key = null;
  }

  update(m, force = false) {
    const key = `${m.state.seq}|${m.truth}|${m.reader}`;
    if (key === this.key && !force) return;
    this.key = key;
    const posted = (id) => this.replay.tasks.get(id);
    const task = (id) => posted(id)?.payload.task;
    const toggle = (id) => {
      if (this.open.has(id)) this.open.delete(id);
      else this.open.add(id);
      this.update(m, true);
    };
    const row = (id, { extra = null, below = null, cls = "" } = {}) => {
      const t = task(id);
      const parts = partsOf(t);
      const price = t ? priceLabel(t) : null;
      const opened = this.open.has(id);
      return h(
        "li",
        { class: `task ${cls}` },
        h(
          "button",
          { type: "button", class: "task-head", "aria-expanded": String(opened), onclick: () => toggle(id) },
          h("span", { class: "task-reward", title: price?.title }, price ? price.figure : "?", price?.unit ? h("small", {}, price.unit) : null),
          h(
            "span",
            { class: "task-title" },
            h("b", {}, `${jobName(id)} · ${parts.map((part) => part.title).join(" + ") || "?"}`),
            h(
              "span",
              { class: "task-meta" },
              t?.client ? clientMark(t.client) : null,
              (t?.required_workers ?? parts.length) > 1 ? h("span", { class: "for-two" }, icon("pair", 13), "for two") : null,
              h("span", { class: "muted" }, `${t ? fmt.plural(Math.max(...parts.map((part) => part.deadline_days)), "day") : "?"} to do · posted day ${posted(id) ? dayOf(posted(id).time) : "?"}`),
            ),
            below,
          ),
          extra,
        ),
        opened ? this.detail(id, m) : null,
      );
    };
    const c = m.state.conditions;
    const bidsOn = (id) => Object.entries(m.state.offers).filter(([, o]) => o.task_id === id);
    const bidMarks = (id) => {
      const bids = bidsOn(id);
      if (!bids.length) return null;
      return h(
        "span",
        { class: "task-who bids", title: bids.map(([who, o]) => (o.partner ? `${who} asked ${o.partner}` : `${who} put their name down`)).join("; ") },
        bids.map(([who, o]) => h("span", { class: "bid" }, m.cast.badge(who, 15), o.partner ? [icon("ask", 11), m.cast.badge(o.partner, 15)] : icon("board", 11))),
      );
    };
    const open = Object.keys(m.state.open).sort((a, b) => (task(b) ? priceLabel(task(b)).value : 0) - (task(a) ? priceLabel(task(a)).value : 0));
    const claimed = Object.entries(m.state.claims);
    const handed = m.dayEvents.filter((e) => e.kind === "work_submitted" && visible(e, m));
    const assessed = new Map(m.dayEvents.filter((e) => e.kind === "work_assessed").map((e) => [e.seq - 1, e.payload]));
    const lapsed = m.dayEvents.filter((e) => e.kind === "task_expired");
    const partState = (claim) =>
      h(
        "span",
        { class: "parts" },
        claim.parts.map((part, i) =>
          h(
            "span",
            { class: `part-chip${part ? " in" : ""}`, title: part ? `Part ${i + 1} handed in by ${part.worker} as ${handedAs(part.declaration)}` : `Part ${i + 1} not handed in yet` },
            claim.parts.length > 1 ? `${i + 1}` : null,
            part ? [icon("check", 11), m.cast.badge(part.worker, 13), part.declaration === "incomplete" ? h("small", {}, "unfinished") : null] : h("small", {}, "open"),
          ),
        ),
      );
    const posting = c.one_part_tasks !== undefined ? `Each posting adds ${fmt.plural(c.one_part_tasks, "job")} for one and ${fmt.plural(c.two_part_tasks, "job")} for two` : c.tasks_per_day !== undefined ? `${c.tasks_per_day} jobs are posted each morning` : "Jobs are posted at the start of each working session";
    const pairing = c.partner_choice === undefined ? "" : c.partner_choice ? " A job for two is taken by asking someone by name." : " The clerk pairs the names put down for jobs for two by lot.";
    fill(
      this.el,
      h("p", { class: "note" }, `${posting}; one job at a time; a notice nobody takes comes down after ${fmt.plural(m.world.task_shelf_life_days, "day")}.${pairing} Prices are what each worker is paid once every part is in.`),
      h("h4", {}, `On the board · ${open.length}`),
      open.length ? h("ul", { class: "tasks" }, open.map((id) => row(id, { extra: bidMarks(id) }))) : h("p", { class: "muted pad-s" }, "The board is empty."),
      h("h4", {}, `Taken · ${claimed.length}`),
      claimed.length
        ? h(
            "ul",
            { class: "tasks" },
            claimed.map(([id, claim]) => row(id, { extra: h("span", { class: "task-who" }, claim.workers.map((worker) => m.cast.badge(worker, 16)), h("small", {}, `due day ${claim.due_day}`)), below: partState(claim), cls: "claimed" })),
          )
        : h("p", { class: "muted pad-s" }, "Nobody works on a job."),
      h("h4", {}, `Handed in today · ${handed.length}`),
      handed.length
        ? h(
            "ul",
            { class: "tasks" },
            handed.map((e) => {
              const p = current(e);
              const q = assessed.get(e.seq);
              const outcome = p.accepted ? (p.declaration === "incomplete" ? "accepted at the lower price" : p.client === "trusting" ? "accepted on the word" : "examples passed") : "handed back";
              return row(p.task_id, {
                extra: h(
                  "span",
                  { class: "task-who" },
                  m.cast.badge(e.actor, 16),
                  m.truth && q ? h("span", { class: `quality${q.quality < 1 ? " flawed" : ""}`, title: "True quality: the share of hidden checks passed" }, icon("eye", 12), fmt.num(q.quality, 2)) : null,
                ),
                below: h("span", { class: `handed${p.accepted ? "" : " back"}` }, `${clockOf(e)} · ${partName(p.task_id, p.part ?? 1, this.replay.tasks)} as ${handedAs(p.declaration)} · ${outcome}`),
                cls: p.accepted ? "done" : "refused",
              });
            }),
          )
        : h("p", { class: "muted pad-s" }, "Nothing yet."),
      lapsed.length
        ? [
            h("h4", {}, `Lapsed this morning · ${lapsed.length}`),
            h(
              "ul",
              { class: "tasks" },
              lapsed.map((e) => {
                const p = current(e);
                return row(p.task_id, {
                  extra: h("span", { class: "task-who" }, p.workers.map((worker) => m.cast.badge(worker, 16))),
                  below: h(
                    "span",
                    { class: "parts" },
                    p.delivered.map((worker, i) => h("span", { class: `part-chip${worker ? " in" : " missing"}` }, p.delivered.length > 1 ? `${i + 1}` : null, worker ? [icon("check", 11), m.cast.badge(worker, 13)] : h("small", {}, "never handed in"))),
                  ),
                  cls: "lapsed",
                });
              }),
            ),
          ]
        : null,
    );
  }

  detail(id, m) {
    const t = this.replay.tasks.get(id)?.payload.task;
    const parts = partsOf(t);
    const history = this.replay.taskEvents(id, m.state.seq).filter((e) => visible(e, m));
    return h(
      "div",
      { class: "task-detail" },
      t ? h("p", { class: "task-client" }, clientMark(t.client, true) ?? "") : null,
      parts.map((part, i) => {
        const price = priceOf(t, i);
        return h(
          "details",
          { class: "part-spec" },
          h("summary", {}, h("b", {}, parts.length > 1 ? `Part ${i + 1}: ${part.title}` : part.title), h("span", { class: "muted" }, price && t.strict_acceptance ? ` · ${fmt.money(price.finished)} on acceptance${(t.required_workers ?? parts.length) > 1 ? ", to each" : ""}` : price ? ` · ${fmt.money(price.finished)} finished, ${fmt.money(price.unfinished)} unfinished${parts.length > 1 ? ", to each" : ""}` : part.reward ? ` · ${fmt.money(part.reward)}` : "")),
          h("pre", { class: "spec" }, part.specification),
        );
      }),
      h(
        "ol",
        { class: "task-history" },
        history.map((e) => {
          const code = m.truth && (e.kind === "work_submitted" || e.kind === "work_checked") ? e.payload.solution : null;
          return h("li", { class: isTruth(e) ? "truth-line" : "" }, h("span", { class: "muted" }, `Day ${dayOf(e.time)} ${clockOf(e)} `), line(e, m), code ? codeBlock(e.kind === "work_checked" ? "Code tried" : "Code handed in", code) : null);
        }),
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
    const key = `${m.state.seq}|${m.truth}|${m.reader}`;
    if (key === this.key) return;
    this.key = key;
    const notes = [];
    const add = (e, text, cls = "") => notes.push({ e, text, cls });
    const scenes = new Map();
    const fates = new Map(m.state.askings.map((asking) => [asking.seq, asking]));
    const assessed = new Map(m.dayEvents.filter((e) => e.kind === "work_assessed").map((e) => [e.seq - 1, current(e)]));
    const job = (id, part) => partName(id, part ?? 1, m.lookups.tasks);
    for (const e of m.dayEvents) {
      const p = current(e);
      switch (e.kind) {
        case "announcement":
          add(e, [e.scene ? "At the meeting: " : "Announced to everyone: ", h("q", {}, e.text)]);
          break;
        case "vote":
          if (m.truth) add(e, [m.cast.mention(`${p.voter} answered the clerk: ${p.choice}`)], "truth-line");
          break;
        case "intervention":
          if (m.truth) add(e, ["Conditions changed", !m.dayEvents.some((x) => x.kind === "announcement" && x.time === e.time) ? " without an announcement" : "", `: ${Object.entries(p.changes ?? {}).map(([k, v]) => `${k.replaceAll("_", " ")} → ${v}`).join(", ")}`], "truth-line");
          break;
        case "defect_discovered":
          add(e, [m.cast.mention(`A fault came to light in ${job(p.task_id, p.part)}, which ${p.worker} handed in as finished on day ${dayOf(p.delivery_time)}${p.workers?.length > 1 ? `; ${p.workers.join(" and ")} share the loss` : ""}`), p.report ? [". Told the client: ", h("q", {}, p.report)] : "", m.truth ? ` (true quality ${fmt.num(p.quality, 2)})` : ""], "critical");
          break;
        case "draw":
          add(e, [m.cast.mention(`The clerk drew lots for ${jobName(p.task_id)}: ${p.order.join(", then ")}`)]);
          break;
        case "task_proposed": {
          const fate = fates.get(e.seq);
          add(e, [m.cast.mention(`${e.actor} asked ${p.partner} to take ${jobName(p.task_id)} together`), fate && fate.fate !== "open" ? h("span", { class: `fate-note fate-${fate.fate.replace(" ", "-")}` }, ` · ${FATES[fate.fate]}`) : h("span", { class: "muted" }, " · open")]);
          break;
        }
        case "task_claimed":
          if (p.workers.length > 1) add(e, [m.cast.mention(e.actor ? `${p.workers.join(" and ")} took ${jobName(p.task_id)} together` : `By lot, the clerk paired ${p.workers.join(" and ")} for ${jobName(p.task_id)}`)]);
          break;
        case "work_submitted": {
          const q = assessed.get(e.seq);
          if (!visible(e, m)) break;
          const how = p.accepted ? (p.declaration === "incomplete" ? "accepted at the lower price" : p.client === "trusting" ? "accepted on the word" : "the examples passed") : "handed back: the examples failed";
          add(e, [m.cast.mention(`${e.actor} handed in ${job(p.task_id, p.part)} as ${handedAs(p.declaration)}`), `, ${how}`], p.accepted ? "" : "serious");
          if (m.truth && q && q.declaration === "complete" && (q.tested === false || q.refused)) add(e, [m.cast.mention(`${e.actor} declared it finished after seeing that very code fail`), q.refused ? " (the client had handed it back)" : " (its last try at the desk)"], "truth-line critical");
          else if (m.truth && q?.accepted && q.declaration === "complete" && q.quality < 1) add(e, [m.cast.mention(`${e.actor}'s ${job(p.task_id, p.part)} hides a latent fault`), `: true quality ${fmt.num(q.quality, 2)}`], "truth-line critical");
          break;
        }
        case "task_expired":
          add(e, p.workers.length > 1 ? [m.cast.mention(`${jobName(p.task_id)}, taken by ${p.workers.join(" and ")}, lapsed: `), p.delivered.map((worker, i) => [i ? "; " : "", worker ? m.cast.mention(`${worker} had handed in part ${i + 1}`) : `part ${i + 1} was never handed in`])] : [m.cast.mention(`${p.workers[0]} let ${jobName(p.task_id)} lapse`)], "critical");
          break;
        case "credits_given":
          add(e, [m.cast.mention(`${p.giver} handed ${p.recipient} ${fmt.money(p.amount)}`), p.note ? [": ", h("q", {}, p.note)] : ""]);
          break;
        case "speech":
          if (p.private) add(e, [line(e, m)], m.truth && !m.reader ? "truth-line" : "");
          else if (scenes.has(e.scene)) scenes.get(e.scene).said += 1;
          break;
        case "scene_started":
          if (p.kind === "conversation" || p.kind === "meeting") scenes.set(e.scene, { e, said: 0, people: p.participants ?? [], kind: p.kind });
          break;
        case "rating":
          if (m.truth && p.score <= 2) add(e, [m.cast.mention(`${p.rater} marked ${p.target} ${p.score} of 5`), ": ", h("q", {}, p.reason)], "truth-line");
          break;
        case "evolution":
          if (m.truth && p.level !== "L0") add(e, [m.cast.mention(`${p.agent}`), ` · ${p.subject}`, p.trigger === "self" ? " (asked for)" : ""], "truth-line");
          break;
        case "action_rejected":
          if (p.attempt?.kind === "move") add(e, [m.cast.mention(`${e.actor} found it closed`), `: ${p.reason}`], "warn");
          break;
      }
    }
    for (const { e, said, people, kind } of scenes.values()) {
      const place = m.places.get(e.place);
      add(e, [`A ${kind} at ${place ? shortName(place) : e.place}: `, people.map((name) => m.cast.badge(name, 14)), ` ${fmt.plural(said, "thing")} said`]);
    }
    notes.sort((a, b) => a.e.seq - b.e.seq);
    const balances = Object.entries(m.state.balances).sort((a, b) => a[1] - b[1]);
    const broke = balances.filter(([, v]) => v < 0);
    fill(
      this.el,
      h("p", { class: "note" }, `Day ${m.state.day || 1} up to ${hhmmss(minuteOf(m.state.time))}, in its notable moments. Pick one to go there.`),
      notes.length
        ? h(
            "ol",
            { class: "chronicle-list" },
            notes.map(({ e, text, cls }) => h("li", { class: cls }, h("button", { type: "button", class: "linkish", onclick: () => this.onJump(e.time) }, h("span", { class: "chron-time" }, clockOf(e)), h("span", {}, text)))),
          )
        : emptyState("Nothing notable yet today."),
      broke.length ? h("p", { class: "note" }, "In debt: ", broke.map(([name, v], i) => [i ? ", " : "", m.cast.mention(name), ` ${fmt.money(v)}`])) : null,
    );
  }
}
