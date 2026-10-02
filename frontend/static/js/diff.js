// Unified diffs of an agent's files, made readable: prose shows which words changed, and the
// insights file shows insights added, revised and dropped instead of raw JSON lines.

import { h } from "./dom.js";

/** Parse a `git diff` into files, each with its hunks of typed lines. */
export function parseDiff(text) {
  const files = [];
  let file = null;
  let hunk = null;
  for (const line of (text ?? "").split("\n")) {
    if (line.startsWith("diff --git ")) {
      const match = / b\/(.*)$/.exec(line);
      file = { path: match ? match[1] : line, status: "modified", hunks: [] };
      files.push(file);
      hunk = null;
    } else if (!file) continue;
    else if (line.startsWith("new file")) file.status = "added";
    else if (line.startsWith("deleted file")) file.status = "deleted";
    else if (line.startsWith("@@")) {
      hunk = { header: line, lines: [] };
      file.hunks.push(hunk);
    } else if (hunk && /^[ +-]/.test(line)) hunk.lines.push({ type: line[0], text: line.slice(1) });
    else if (hunk && line.startsWith("\\")) continue;
  }
  return files;
}

/** Words and the spaces between them, so a diff of tokens reads as a diff of words. */
const tokens = (text) => text.match(/\s+|[^\s]+/g) ?? [];

/** The longest common subsequence of two token lists, as runs of [kind, text]. */
export function wordDiff(before, after) {
  const a = tokens(before);
  const b = tokens(after);
  if (a.length * b.length > 250000) return [["-", before], ["+", after]];
  const table = Array.from({ length: a.length + 1 }, () => new Uint16Array(b.length + 1));
  for (let i = a.length - 1; i >= 0; i--)
    for (let j = b.length - 1; j >= 0; j--) table[i][j] = a[i] === b[j] ? table[i + 1][j + 1] + 1 : Math.max(table[i + 1][j], table[i][j + 1]);
  const runs = [];
  const push = (kind, text) => (runs.length && runs.at(-1)[0] === kind ? (runs.at(-1)[1] += text) : runs.push([kind, text]));
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      push("=", a[i++]);
      j++;
    } else if (table[i + 1][j] >= table[i][j + 1]) push("-", a[i++]);
    else push("+", b[j++]);
  }
  while (i < a.length) push("-", a[i++]);
  while (j < b.length) push("+", b[j++]);
  return runs;
}

const runsOf = (runs, keep) =>
  runs.filter(([kind]) => kind === "=" || kind === keep).map(([kind, text]) => (kind === "=" ? text : h(kind === "+" ? "ins" : "del", {}, text)));

/** A unified diff of prose: paired removed and added lines show the words that changed. */
function proseHunks(file) {
  const rows = [];
  for (const hunk of file.hunks) {
    let i = 0;
    const lines = hunk.lines;
    while (i < lines.length) {
      if (lines[i].type === " ") {
        rows.push(h("div", { class: "diff-line same" }, lines[i].text || " "));
        i++;
        continue;
      }
      const removed = [];
      const added = [];
      while (i < lines.length && lines[i].type === "-") removed.push(lines[i++].text);
      while (i < lines.length && lines[i].type === "+") added.push(lines[i++].text);
      const pairs = Math.min(removed.length, added.length);
      for (let k = 0; k < removed.length; k++) {
        if (k < pairs && removed[k].trim() && added[k].trim()) rows.push(h("div", { class: "diff-line del" }, runsOf(wordDiff(removed[k], added[k]), "-")));
        else rows.push(h("div", { class: "diff-line del" }, removed[k] || " "));
      }
      for (let k = 0; k < added.length; k++) {
        if (k < pairs && removed[k].trim() && added[k].trim()) rows.push(h("div", { class: "diff-line add" }, runsOf(wordDiff(removed[k], added[k]), "+")));
        else rows.push(h("div", { class: "diff-line add" }, added[k] || " "));
      }
    }
  }
  return rows;
}

function parseInsight(text) {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

/** The insights file's change as insights added, revised and dropped. */
function insightChanges(file, cast) {
  const removed = new Map();
  const added = new Map();
  for (const hunk of file.hunks)
    for (const line of hunk.lines) {
      if (line.type === " ") continue;
      const insight = parseInsight(line.text);
      if (insight) (line.type === "-" ? removed : added).set(insight.id, insight);
    }
  const rows = [];
  const about = (insight) => (insight.subject ? h("span", { class: "insight-subject" }, cast?.has(insight.subject) ? cast.chip(insight.subject) : insight.subject) : null);
  for (const [id, insight] of added) {
    const before = removed.get(id);
    if (before) {
      rows.push(h("div", { class: "insight-change revised" }, h("span", { class: "change-kind" }, "revised"), about(insight), h("p", {}, runsOf(wordDiff(before.text, insight.text), "+"))));
      removed.delete(id);
    } else rows.push(h("div", { class: "insight-change added" }, h("span", { class: "change-kind" }, "new"), about(insight), h("p", {}, insight.text)));
  }
  for (const insight of removed.values()) rows.push(h("div", { class: "insight-change dropped" }, h("span", { class: "change-kind" }, "dropped"), about(insight), h("p", {}, h("del", {}, insight.text))));
  return rows;
}

/** One file of a diff, rendered for reading. */
export function renderFile(file, cast = null) {
  const body = file.path.endsWith("insights.jsonl") ? insightChanges(file, cast) : proseHunks(file);
  return h(
    "section",
    { class: "diff-file" },
    h("div", { class: "diff-path" }, h("span", { class: `diff-status ${file.status}` }, file.status), file.path),
    h("div", { class: "diff-body" }, body.length ? body : h("div", { class: "diff-line same" }, "(no readable change)")),
  );
}
