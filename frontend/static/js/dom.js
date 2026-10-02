// Small DOM helpers and number formats. Text from the bundle only ever enters the page as text
// nodes or attribute values, never as markup.

const SVG = "http://www.w3.org/2000/svg";

function build(element, attrs, children) {
  for (const [key, value] of Object.entries(attrs ?? {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key.startsWith("on") && typeof value === "function") element.addEventListener(key.slice(2), value);
    else if (key === "style" && typeof value === "object")
      for (const [name, v] of Object.entries(value)) element.style.setProperty(name, v);
    else if (key === "dataset") Object.assign(element.dataset, value);
    else element.setAttribute(key, value === true ? "" : value);
  }
  append(element, children);
  return element;
}

/** Append children: nodes, strings (as text), arrays of either; null and false are skipped. */
export function append(element, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    element.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return element;
}

export const h = (tag, attrs, ...children) => build(document.createElement(tag), attrs, children);
export const s = (tag, attrs, ...children) => build(document.createElementNS(SVG, tag), attrs, children);

/** Replace the children of `element`. */
export const fill = (element, ...children) => {
  element.replaceChildren();
  return append(element, children);
};

const integer = new Intl.NumberFormat("en", { maximumFractionDigits: 0 });
const compact = new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 });

export const fmt = {
  int: (n) => (n === null || n === undefined ? "–" : integer.format(n)),
  compact: (n) => (n === null || n === undefined ? "–" : compact.format(n)),
  num: (n, digits = 1) => (n === null || n === undefined ? "–" : n.toFixed(digits)),
  pct: (n, digits = 0) => (n === null || n === undefined ? "–" : `${(n * 100).toFixed(digits)}%`),
  signed: (n) => (n > 0 ? `+${integer.format(n)}` : n < 0 ? `−${integer.format(-n)}` : "±0"),
  credits: (n) => (n === null || n === undefined ? "–" : `${n < 0 ? "−" : ""}${integer.format(Math.abs(n))} cr`),
  plural: (n, one, many = `${one}s`) => `${integer.format(n)} ${n === 1 ? one : many}`,
  wall: (iso) => (iso ? new Date(iso).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" }) : "–"),
};

/** A quiet message for a view or panel with nothing to show yet, and why. */
export const emptyState = (title, ...detail) => h("div", { class: "empty" }, h("p", { class: "empty-title" }, title), detail.length ? h("p", {}, ...detail) : null);

/** Observe the width of `element`, calling `fn(width)` when it settles on a new value. */
export function onWidth(element, fn) {
  let last = -1;
  let timer = null;
  const observer = new ResizeObserver(([entry]) => {
    const width = Math.round(entry.contentRect.width);
    if (width === last || width === 0) return;
    clearTimeout(timer);
    timer = setTimeout(() => {
      last = width;
      fn(width);
    }, last < 0 ? 0 : 60);
  });
  observer.observe(element);
  return () => observer.disconnect();
}
