// The agent panel: profile, balance and esteem over the run, and the agent's files as of now.

import { getDiff, getFiles, getHistory } from "./api.js";
import { h, renderDiff, sparkline } from "./panels.js";
import { formatTime } from "./replay.js";

const TABS = ["policy", "skills", "insights", "diary", "history"];

export class AgentPanel {
  constructor(container, { run, world, series }) {
    this.container = container;
    this.run = run;
    this.world = world;
    this.series = series;
    this.name = null;
    this.tab = "policy";
    this.histories = new Map(); // agent -> versions, oldest first
    this.files = new Map(); // commit -> files
    this.diffOf = null; // commit whose diff is open
    this.shownKey = null;
    this.token = 0;
  }

  select(name) {
    this.name = name;
    this.diffOf = null;
    this.shownKey = null;
  }

  /** Forget cached histories: the run has moved on. */
  invalidate() {
    this.histories.clear();
    this.shownKey = null;
  }

  async update(state, bounds) {
    if (!this.name) {
      this.container.replaceChildren(h("h2", {}, "Agent"), h("p", { class: "muted" }, "Click an agent on the map."));
      return;
    }
    const token = ++this.token;
    this.stateTime = state.time;
    let versions = this.histories.get(this.name);
    if (!versions) {
      versions = await getHistory(this.run, this.name);
      this.histories.set(this.name, versions);
    }
    const version = [...versions].reverse().find((v) => v.time <= state.time) ?? null;
    const key = `${this.name}|${this.tab}|${version?.commit}|${versions.length}`;
    if (token !== this.token) return; // a newer update superseded this one
    if (key !== this.shownKey) {
      this.shownKey = key;
      this.frame = null;
    }
    if (!this.frame) await this.buildFrame(versions, version, token);
    if (this.frame && token === this.token) this.updateStats(state, bounds);
  }

  async buildFrame(versions, version, token) {
    const profile = this.world.agents.find((a) => a.name === this.name);
    const files = version ? await this.filesAt(version.commit) : null;
    if (token !== this.token) return;
    this.stats = h("div", { class: "stats" });
    const tabs = h(
      "div",
      { class: "tabs", role: "tablist" },
      TABS.map((tab) =>
        h("button", { class: tab === this.tab ? "on" : "", role: "tab", onclick: () => this.setTab(tab) }, tab),
      ),
    );
    const asOf = version ? `as of ${formatTime(version.time)} · ${version.commit.slice(0, 7)}` : "before the first commit";
    this.frame = h(
      "div",
      {},
      h("h2", {}, profile.name),
      h("p", { class: "muted" }, `${profile.age}, ${profile.occupation}`),
      h("details", {}, h("summary", {}, "Backstory"), h("p", {}, profile.backstory)),
      this.stats,
      tabs,
      this.tab === "history" ? null : h("p", { class: "muted" }, asOf),
      this.tab === "history" ? this.historyView(versions, version) : this.filesView(files),
    );
    this.container.replaceChildren(this.frame);
  }

  updateStats(state, [t0, t1]) {
    const name = this.name;
    const balance = state.balances[name];
    const esteem = state.esteem[name];
    this.stats.replaceChildren(
      h("div", {}, h("span", { class: "label" }, "Balance"), h("strong", {}, `${balance} credits`), sparkline(this.series.balance[name], t0, t1, state.time, `Balance of ${name} over the run`)),
      h(
        "div",
        {},
        h("span", { class: "label" }, "Esteem (1 to 5)"),
        h("strong", {}, esteem == null ? "not rated yet" : esteem.toFixed(2)),
        sparkline(this.series.esteem[name], t0, t1, state.time, `Esteem of ${name} over the run`, (v) => v.toFixed(1)),
      ),
    );
  }

  setTab(tab) {
    this.tab = tab;
    this.shownKey = null;
    this.onChange?.();
  }

  async filesAt(commit) {
    if (!this.files.has(commit)) this.files.set(commit, await getFiles(this.run, this.name, commit));
    return this.files.get(commit);
  }

  filesView(files) {
    if (!files) return h("p", { class: "muted" }, "No version yet.");
    const text = (s) => h("pre", { class: "doc" }, s);
    switch (this.tab) {
      case "policy":
        return files.policy.trim() ? text(files.policy) : h("p", { class: "muted" }, "No policy written yet.");
      case "skills": {
        const names = Object.keys(files.skills);
        return names.length
          ? h("div", {}, names.map((n) => h("details", {}, h("summary", {}, n), text(files.skills[n]))))
          : h("p", { class: "muted" }, "No skills yet.");
      }
      case "insights":
        return files.insights.length
          ? h(
              "ul",
              { class: "plain" },
              files.insights.map((i) => h("li", {}, h("span", { class: "muted" }, `day ${i.day}${i.subject ? ` · about ${i.subject}` : ""}: `), i.text)),
            )
          : h("p", { class: "muted" }, "No insights yet.");
      case "diary":
        return files.diary ? h("div", {}, h("p", { class: "muted" }, files.diary.name), text(files.diary.text)) : h("p", { class: "muted" }, "No diary yet.");
    }
  }

  historyView(versions, current) {
    const detail = h("div", {});
    const show = async (version) => {
      this.diffOf = version.commit;
      detail.replaceChildren(h("p", { class: "muted" }, "Loading diff…"));
      const { diff } = await getDiff(this.run, this.name, version.commit);
      detail.replaceChildren(h("p", { class: "muted" }, version.body || ""), diff.trim() ? renderDiff(diff) : h("p", { class: "muted" }, "No file changes."));
    };
    const list = h(
      "ol",
      { class: "history" },
      [...versions].reverse().map((v) =>
        h(
          "li",
          { class: `${v.commit === current?.commit ? "current" : ""}${v.time > this.stateTime ? " future" : ""}` },
          h(
            "button",
            { onclick: () => show(v) },
            h("span", { class: "when" }, formatTime(v.time)),
            v.level ? h("span", { class: "kind" }, `${v.level} ${v.trigger}`) : h("span", { class: "kind quietkind" }, "experience"),
            h("span", {}, v.subject),
          ),
        ),
      ),
    );
    const open = versions.find((v) => v.commit === this.diffOf);
    if (open) show(open);
    return h("div", {}, list, detail);
  }
}
