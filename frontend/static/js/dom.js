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
  credits: (n) => (n === null || n === undefined ? "–" : `${n < 0 ? "−" : ""}${integer.format(Math.abs(n))} ${Math.abs(n) === 1 ? "crown" : "crowns"}`),
  plural: (n, one, many = `${one}s`) => `${integer.format(n)} ${n === 1 ? one : many}`,
  wall: (iso) => (iso ? new Date(iso).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" }) : "–"),
};

/** A quiet message for a view or panel with nothing to show yet, and why. */
export const emptyState = (title, ...detail) => h("div", { class: "empty" }, h("p", { class: "empty-title" }, title), detail.length ? h("p", {}, ...detail) : null);

/**
 * A technical term with its one-line definition on the spot: tap or click it to read the
 * definition beside it, tap anywhere else or press Escape to close it. Without a definition, the
 * label alone.
 */
export function term(label, definition) {
  if (!definition) return h("span", {}, label);
  return h("button", { type: "button", class: "term", "aria-expanded": "false", onclick: (event) => openTerm(event.currentTarget, definition) }, label);
}

let pop = null;
function closeTerm() {
  if (!pop) return;
  pop.box.remove();
  pop.anchor.setAttribute("aria-expanded", "false");
  document.removeEventListener("pointerdown", pop.outside, true);
  document.removeEventListener("keydown", pop.key, true);
  window.removeEventListener("scroll", closeTerm, true);
  window.removeEventListener("resize", closeTerm);
  pop = null;
}
function openTerm(anchor, definition) {
  const again = pop?.anchor === anchor;
  closeTerm();
  if (again) return;
  const box = h("div", { class: "term-pop", role: "tooltip" }, definition);
  document.body.append(box);
  const r = anchor.getBoundingClientRect();
  const width = Math.min(320, window.innerWidth - 24);
  box.style.width = `${width}px`;
  box.style.left = `${Math.max(12, Math.min(window.innerWidth - width - 12, r.left))}px`;
  const below = r.bottom + 6;
  box.style.top = `${below + box.offsetHeight > window.innerHeight - 8 ? Math.max(8, r.top - box.offsetHeight - 6) : below}px`;
  anchor.setAttribute("aria-expanded", "true");
  const outside = (event) => event.target !== anchor && !box.contains(event.target) && closeTerm();
  const key = (event) => event.key === "Escape" && closeTerm();
  pop = { box, anchor, outside, key };
  document.addEventListener("pointerdown", outside, true);
  document.addEventListener("keydown", key, true);
  window.addEventListener("scroll", closeTerm, true);
  window.addEventListener("resize", closeTerm);
}

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
