// A small Markdown reader for what agents write (policies, skill notes, diaries): headings,
// paragraphs, lists, quotes, code and inline emphasis. It builds DOM nodes from text, so nothing
// an agent writes can become markup.

import { h } from "./dom.js";

/** Split YAML front matter (`---` fenced, simple `key: value` lines) from the body. */
export function frontMatter(text) {
  const match = /^---\n([\s\S]*?)\n---\n?/.exec(text ?? "");
  if (!match) return { meta: {}, body: text ?? "" };
  const meta = {};
  for (const line of match[1].split("\n")) {
    const pair = /^([\w-]+):\s*(.*)$/.exec(line);
    if (pair) meta[pair[1]] = pair[2].replace(/^["']|["']$/g, "");
  }
  return { meta, body: text.slice(match[0].length) };
}

function inline(text) {
  const out = [];
  const pattern = /(\*\*[^*]+\*\*|__[^_]+__|`[^`]+`|\*[^*\s][^*]*\*|_[^_\s][^_]*_)/g;
  let at = 0;
  for (const match of text.matchAll(pattern)) {
    out.push(text.slice(at, match.index));
    const token = match[0];
    if (token.startsWith("**") || token.startsWith("__")) out.push(h("strong", {}, token.slice(2, -2)));
    else if (token.startsWith("`")) out.push(h("code", {}, token.slice(1, -1)));
    else out.push(h("em", {}, token.slice(1, -1)));
    at = match.index + token.length;
  }
  out.push(text.slice(at));
  return out;
}

const LIST = /^\s*([-*+]|\d+[.)])\s+(.*)$/;

/** Render Markdown text as a fragment of block elements. */
export function markdown(text) {
  const lines = (text ?? "").replace(/\r\n/g, "\n").split("\n");
  const blocks = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i++;
      continue;
    }
    if (line.startsWith("```")) {
      const code = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) code.push(lines[i++]);
      i++;
      blocks.push(h("pre", {}, h("code", {}, code.join("\n"))));
      continue;
    }
    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (heading) {
      blocks.push(h(`h${Math.min(6, heading[1].length + 2)}`, { class: "md-h" }, inline(heading[2])));
      i++;
      continue;
    }
    if (LIST.test(line)) {
      const ordered = /^\s*\d/.test(line);
      const items = [];
      while (i < lines.length && lines[i].trim()) {
        const item = LIST.exec(lines[i]);
        if (item) items.push([item[2]]);
        else if (items.length) items.at(-1).push(lines[i].trim());
        i++;
      }
      blocks.push(h(ordered ? "ol" : "ul", {}, items.map((parts) => h("li", {}, inline(parts.join(" "))))));
      continue;
    }
    if (line.startsWith(">")) {
      const quote = [];
      while (i < lines.length && lines[i].startsWith(">")) quote.push(lines[i++].replace(/^>\s?/, ""));
      blocks.push(h("blockquote", {}, inline(quote.join(" "))));
      continue;
    }
    const paragraph = [];
    while (i < lines.length && lines[i].trim() && !LIST.test(lines[i]) && !/^(#{1,6}\s|```|>)/.test(lines[i])) paragraph.push(lines[i++].trim());
    blocks.push(h("p", {}, inline(paragraph.join(" "))));
  }
  return h("div", { class: "md" }, blocks);
}
