"use strict";
// The timeline viewer: one lane per resident over simulated time, read from /api/timeline; and
// the overview of all the runs, one table of days per run, read from /api/progress.

const DAY = 86400;
const LABEL_W = 136, AXIS_H = 40, LANE_H = 74;
const MARK_Y = 10, BAR_Y = 19, BAR_H = 20, PURSE_Y = 45, PURSE_H = 22, MARK_GAP = 10;
const MIN_SPAN = 600, REFRESH_MS = 5000, PANEL_LIMIT = 400;
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const KIND_NAMES = { idle: "Idle", movement: "Movement", work: "Work", sleep: "Sleep", conversation: "Conversation" };
const MARKERS = {
  speech: "speech", claim: "claim", submission: "submission and verdict", payment: "payment",
  gift: "gift", skill_shared: "skill shared", rating: "rating", journal: "journal",
  forced_sleep: "forced sleep", abandon: "task given up or lost",
};
const COLOURS = ["page", "surface", "ink", "ink-2", "muted", "grid", "axis", "select", "idle", "sleep",
  "movement", "work", "conversation", "skill", "rating", "good", "critical", "on-fill"];
const OVERVIEW = ""; // the run selector's value for the overview of all the runs
// The overview's columns: heading, what it shows, and the field of the day or the cell made of it.
const PROGRESS_COLUMNS = [
  ["Day", "The lived day, from one checkpoint to the next", "day"],
  ["Date", "Its date", (d) => dateName(d.date)],
  ["Hours", "The real hours the day took", (d) => (d.in_progress ? "…" : d.hours.toFixed(2))],
  ["Claims", "Tasks claimed", "claims"],
  ["Sub.", "Tasks handed in", "submissions"],
  ["✓", "Handed in and accepted", "accepted"],
  ["✗", "Handed in and not accepted", "rejected"],
  ["Paid", "Payments for accepted tasks", "payments"],
  ["Amount", "The total paid", (d, run) => d.paid && money(d.paid, run.currency)],
  ["Speech", "Things said", "speeches"],
  ["Gifts", "Gifts of money", "gifts"],
  ["Skills", "Skills passed on", "skills_shared"],
  ["Ratings", "Ratings given", "ratings"],
  ["Journals", "Gone to bed with the day's journal", "journals"],
  ["Forced", "Fallen asleep at the forced hour without a journal", "forced_sleeps"],
  ["Purses", "The residents' purses at the end of the day (now, for the day in progress): lowest · median · highest",
    (d, run) => [d.purse.min, d.purse.median, d.purse.max].map((n) => money(n, run.currency)).join(" · ")],
];

const $ = (id) => document.getElementById(id);
const canvas = $("canvas"), ctx = canvas.getContext("2d"), tip = $("tip");
const state = { runs: [], run: null, data: null, t0: 0, t1: DAY, selected: null, drag: null, busy: false, drawn: {} };
let C = {};

// Time ------------------------------------------------------------------------------------

const pad = (n) => String(n).padStart(2, "0");
function hhmm(t) {
  const s = ((t % DAY) + DAY) % DAY;
  return `${pad(Math.floor(s / 3600))}:${pad(Math.floor((s % 3600) / 60))}`;
}
function dateName(iso, later = 0) { // the date `later` days after `iso`, e.g. "Mon 2 Mar"
  const [y, m, d] = iso.split("-").map(Number);
  const day = new Date(Date.UTC(y, m - 1, d + later));
  return `${WEEKDAYS[day.getUTCDay()]} ${day.getUTCDate()} ${MONTHS[day.getUTCMonth()]}`;
}
const dateOf = (t) => dateName(state.data.start_date, Math.floor(t / DAY));
const dayOf = (t) => Math.floor(t / DAY) + 1;
const moment = (t) => `Day ${dayOf(t)}, ${dateOf(t)} ${hhmm(t)}`;
function between(a, b) {
  return dayOf(a) === dayOf(b) ? `${moment(a)}–${hhmm(b)}` : `${moment(a)} – ${moment(b)}`;
}
function duration(s) {
  const d = Math.floor(s / DAY), h = Math.floor((s % DAY) / 3600), m = Math.floor((s % 3600) / 60);
  return [d && `${d} d`, h && `${h} h`, (m || (!d && !h)) && `${m} min`].filter(Boolean).join(" ");
}

// Data helpers ----------------------------------------------------------------------------

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const money = (n, currency = state.data.currency) => (n < 0 ? `-${currency}${-n}` : `${currency}${n}`);
const placeName = (id) => (id == null ? "on the way" : state.data.places[id] || id);
const listed = (names) => names.join(", ");
function lowerBound(items, t, key) {
  let lo = 0, hi = items.length;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (key(items[mid]) < t) lo = mid + 1; else hi = mid; }
  return lo;
}
function at(spans, t) {
  const i = lowerBound(spans, t, (s) => s.end);
  const s = spans[i === spans.length ? i - 1 : i];
  return s && s.start <= t && t <= s.end ? s : null;
}
function purseAt(points, t) {
  const i = lowerBound(points, t + 1, (p) => p[0]) - 1;
  return points[Math.max(i, 0)][1];
}
function domain(d = state.data) {
  return [Math.floor(d.start / DAY) * DAY, Math.max(Math.ceil((d.now + 1) / DAY) * DAY, DAY)];
}

// The view --------------------------------------------------------------------------------

const plotW = () => Math.max(canvas.clientWidth - LABEL_W, 1);
const x = (t) => LABEL_W + ((t - state.t0) / (state.t1 - state.t0)) * plotW();
const tAt = (px) => state.t0 + ((px - LABEL_W) / plotW()) * (state.t1 - state.t0);

function setView(t0, t1) {
  const [d0, d1] = domain();
  const span = Math.min(Math.max(t1 - t0, MIN_SPAN), d1 - d0);
  t0 = Math.min(Math.max(t0, d0), d1 - span);
  state.t0 = t0;
  state.t1 = t0 + span;
  draw();
  schedulePanel();
}
function zoom(factor, around = (state.t0 + state.t1) / 2) {
  setView(around - (around - state.t0) * factor, around + (state.t1 - around) * factor);
}
function pan(fraction) {
  const shift = (state.t1 - state.t0) * fraction;
  setView(state.t0 + shift, state.t1 + shift);
}
function wholeRun() { setView(...domain()); }
function oneDay() {
  const midnight = Math.floor((state.t0 + state.t1) / 2 / DAY) * DAY;
  setView(midnight, midnight + DAY);
}

// Drawing ---------------------------------------------------------------------------------

function readColours() {
  const style = getComputedStyle(document.documentElement);
  C = Object.fromEntries(COLOURS.map((name) => [name, style.getPropertyValue(`--${name}`).trim()]));
}

function drawMarker(g, m, cx, cy) {
  g.lineWidth = 1.6;
  g.beginPath();
  switch (m.kind) {
    case "speech":
      g.fillStyle = C.conversation; g.arc(cx, cy, 3.5, 0, 2 * Math.PI); g.fill(); break;
    case "claim":
      g.fillStyle = C["ink-2"]; g.moveTo(cx - 4.5, cy - 3.5); g.lineTo(cx + 4.5, cy - 3.5); g.lineTo(cx, cy + 4); g.fill(); break;
    case "submission": {
      g.fillStyle = m.resolved === undefined ? C.muted : m.resolved ? C.good : C.critical;
      g.fillRect(cx - 4.5, cy - 4.5, 9, 9);
      g.strokeStyle = C["on-fill"]; g.beginPath();
      if (m.resolved) { g.moveTo(cx - 2.5, cy); g.lineTo(cx - 0.5, cy + 2); g.lineTo(cx + 2.8, cy - 2.2); }
      else if (m.resolved === false) { g.moveTo(cx - 2.2, cy - 2.2); g.lineTo(cx + 2.2, cy + 2.2); g.moveTo(cx + 2.2, cy - 2.2); g.lineTo(cx - 2.2, cy + 2.2); }
      g.stroke(); break;
    }
    case "payment":
    case "gift":
      g.moveTo(cx, cy - 5); g.lineTo(cx + 4.5, cy); g.lineTo(cx, cy + 5); g.lineTo(cx - 4.5, cy); g.closePath();
      if (m.kind === "payment") { g.fillStyle = C.good; g.fill(); }
      else { g.fillStyle = C.surface; g.fill(); g.strokeStyle = C.good; g.stroke(); }
      break;
    case "skill_shared":
      g.strokeStyle = C.skill; g.lineWidth = 2.4;
      g.moveTo(cx - 4, cy); g.lineTo(cx + 4, cy); g.moveTo(cx, cy - 4); g.lineTo(cx, cy + 4); g.stroke(); break;
    case "rating":
      for (let i = 0; i < 10; i++) {
        const r = i % 2 ? 2.2 : 5, a = -Math.PI / 2 + (i * Math.PI) / 5;
        g.lineTo(cx + r * Math.cos(a), cy + r * Math.sin(a));
      }
      g.closePath(); g.fillStyle = C.rating; g.fill(); break;
    case "journal":
      g.fillStyle = C.surface; g.strokeStyle = C.ink; g.rect(cx - 3, cy - 4.5, 6, 9); g.fill(); g.stroke();
      g.beginPath(); g.moveTo(cx - 1.2, cy - 1.5); g.lineTo(cx + 1.2, cy - 1.5); g.moveTo(cx - 1.2, cy + 1); g.lineTo(cx + 1.2, cy + 1); g.stroke(); break;
    case "forced_sleep":
      g.strokeStyle = C.critical; g.lineWidth = 2.2;
      g.moveTo(cx - 3.5, cy - 3.5); g.lineTo(cx + 3.5, cy + 3.5); g.moveTo(cx + 3.5, cy - 3.5); g.lineTo(cx - 3.5, cy + 3.5); g.stroke(); break;
    default: // abandon, expiry
      g.strokeStyle = C.critical; g.fillStyle = C.surface;
      g.moveTo(cx - 4, cy + 3.5); g.lineTo(cx + 4, cy + 3.5); g.lineTo(cx, cy - 4); g.closePath(); g.fill(); g.stroke();
  }
}

function hourStep() {
  const perSecond = plotW() / (state.t1 - state.t0);
  return [300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200].find((s) => s * perSecond >= 52) || null;
}

function drawAxis(height) {
  const right = canvas.clientWidth, step = hourStep(), perDay = (plotW() * DAY) / (state.t1 - state.t0);
  ctx.font = "11px system-ui, sans-serif";
  ctx.textBaseline = "middle";
  if (step) {
    for (let t = Math.ceil(state.t0 / step) * step; t <= state.t1; t += step) {
      if (t % DAY === 0) continue;
      const px = Math.round(x(t)) + 0.5;
      ctx.fillStyle = C.grid; ctx.fillRect(px - 0.5, AXIS_H - 6, 1, height - AXIS_H + 6);
      ctx.fillStyle = C.muted; ctx.textAlign = "center"; ctx.fillText(hhmm(t), px, AXIS_H - 12);
    }
  }
  const every = [1, 2, 4, 7, 14].find((k) => k * perDay >= 64) || 28;
  ctx.textAlign = "left";
  for (let t = Math.floor(state.t0 / DAY) * DAY; t <= state.t1; t += DAY) {
    const px = Math.round(x(t)) + 0.5;
    if (t >= state.t0) { ctx.fillStyle = C.axis; ctx.fillRect(px - 0.5, 4, 1, height - 4); }
    if ((dayOf(t) - 1) % every) continue;
    const label = every * perDay >= 130 ? `Day ${dayOf(t)} · ${dateOf(t)}` : `Day ${dayOf(t)}`;
    const left = Math.max(px, LABEL_W) + 5, room = Math.min(x(t + every * DAY), right) - left - 6;
    ctx.fillStyle = C.ink;
    if (ctx.measureText(label).width <= room) ctx.fillText(label, left, 13);
  }
  ctx.setLineDash([3, 3]);
  ctx.strokeStyle = C.muted;
  for (const day of state.data.days) {
    if (day.end == null || day.end < state.t0 || day.end > state.t1) continue;
    const px = Math.round(x(day.end)) + 0.5;
    ctx.beginPath(); ctx.moveTo(px, AXIS_H - 4); ctx.lineTo(px, height); ctx.stroke();
  }
  ctx.setLineDash([]);
}

function drawLane(r, top, scale) {
  const { t0, t1 } = state;
  if (r.name === state.selected) { ctx.fillStyle = C.select; ctx.fillRect(0, top, canvas.clientWidth, LANE_H); }
  ctx.fillStyle = C.grid; ctx.fillRect(0, top + LANE_H - 1, canvas.clientWidth, 1);
  ctx.save();
  ctx.beginPath(); ctx.rect(LABEL_W, top, plotW(), LANE_H); ctx.clip();
  ctx.font = "11px system-ui, sans-serif"; ctx.textBaseline = "middle"; ctx.textAlign = "left";
  for (let i = lowerBound(r.segments, t0, (s) => s.end); i < r.segments.length && r.segments[i].start < t1; i++) {
    const s = r.segments[i], x0 = x(s.start), w = x(s.end) - x0;
    const gap = w > 6 ? 1 : 0;
    ctx.fillStyle = C[s.kind];
    ctx.fillRect(x0 + gap, top + BAR_Y, Math.max(w - 2 * gap, 0.6), BAR_H);
    if (s.kind === "work" && s.task != null && w > 52) {
      ctx.fillStyle = C["on-fill"]; ctx.fillText(`task ${s.task}`, Math.max(x0, LABEL_W) + 5, top + BAR_Y + BAR_H / 2);
    }
  }
  for (let i = lowerBound(r.conversations, t0, (s) => s.end); i < r.conversations.length && r.conversations[i].start < t1; i++) {
    const c = r.conversations[i], x0 = x(c.start), w = Math.max(x(c.end) - x0, 2);
    ctx.fillStyle = C.surface; ctx.fillRect(x0 - 1, top + BAR_Y + 4, w + 2, BAR_H - 8);
    ctx.fillStyle = C.conversation; ctx.fillRect(x0, top + BAR_Y + 5, w, BAR_H - 10);
  }
  // The purse: a step line under the bar, on one scale for every lane.
  const py = (v) => top + PURSE_Y + PURSE_H - ((v - scale.min) / (scale.max - scale.min || 1)) * PURSE_H;
  if (scale.min < 0) { ctx.fillStyle = C.grid; ctx.fillRect(LABEL_W, Math.round(py(0)), plotW(), 1); }
  ctx.strokeStyle = C["ink-2"]; ctx.lineWidth = 1.5; ctx.beginPath();
  const points = r.purse, first = Math.max(lowerBound(points, t0, (p) => p[0]) - 1, 0);
  ctx.moveTo(x(points[first][0]), py(points[first][1]));
  for (let i = first + 1; i < points.length && points[i - 1][0] <= t1; i++) {
    ctx.lineTo(x(points[i][0]), py(points[i - 1][1])); ctx.lineTo(x(points[i][0]), py(points[i][1]));
  }
  ctx.lineTo(x(state.data.now), py(points[points.length - 1][1]));
  ctx.stroke();
  // Markers of the same second are set side by side; where each was drawn is kept for hovering.
  const from = lowerBound(r.markers, tAt(LABEL_W - 6), (m) => m.t), to = lowerBound(r.markers, tAt(canvas.clientWidth + 6), (m) => m.t);
  const drawn = (state.drawn[r.name] = []);
  for (let i = from, same = 0; i < to; i++) {
    const m = r.markers[i];
    same = i > from && r.markers[i - 1].t === m.t ? same + 1 : 0;
    const px = x(m.t) + same * MARK_GAP;
    drawMarker(ctx, m, px, top + MARK_Y);
    drawn.push([px, m]);
  }
  ctx.restore();
  // The label: name, what the resident is doing at the end of the log, its purse then.
  const last = r.segments[r.segments.length - 1];
  ctx.textAlign = "left";
  ctx.fillStyle = C.ink; ctx.font = "600 13px system-ui, sans-serif"; ctx.fillText(r.name, 12, top + 14);
  ctx.font = "11px system-ui, sans-serif"; ctx.fillStyle = C.muted;
  ctx.fillText(fit(`${KIND_NAMES[last.kind].toLowerCase()} · ${placeName(last.place)}`, LABEL_W - 20), 12, top + 31);
  ctx.fillStyle = C["ink-2"]; ctx.fillText(money(points[points.length - 1][1]), 12, top + PURSE_Y + PURSE_H / 2);
}

function fit(text, width) {
  if (ctx.measureText(text).width <= width) return text;
  while (text.length > 1 && ctx.measureText(`${text}…`).width > width) text = text.slice(0, -1);
  return `${text}…`;
}

function draw() {
  if (!state.data) return;
  const residents = state.data.residents, height = AXIS_H + residents.length * LANE_H;
  const dpr = window.devicePixelRatio || 1, width = canvas.clientWidth;
  canvas.style.height = `${height}px`;
  canvas.width = Math.round(width * dpr); canvas.height = Math.round(height * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.fillStyle = C.surface; ctx.fillRect(0, 0, width, height);
  const after = x(state.data.now);
  if (after < width) { ctx.fillStyle = C.page; ctx.fillRect(Math.max(after, LABEL_W), AXIS_H, width, height); }
  drawAxis(height);
  const values = residents.flatMap((r) => r.purse.map((p) => p[1]));
  const scale = { min: Math.min(0, ...values), max: Math.max(0, ...values) };
  residents.forEach((r, i) => drawLane(r, AXIS_H + i * LANE_H, scale));
  if (after >= LABEL_W && after <= width) {
    ctx.fillStyle = C["ink-2"]; ctx.fillRect(Math.round(after), AXIS_H - 4, 1.5, height);
  }
  ctx.fillStyle = C.axis; ctx.fillRect(LABEL_W - 1, AXIS_H - 4, 1, height);
}

// Hover and selection ---------------------------------------------------------------------

function hit(px, py) {
  const residents = state.data ? state.data.residents : [];
  const i = Math.floor((py - AXIS_H) / LANE_H);
  if (py < AXIS_H || i >= residents.length) return null;
  const r = residents[i], y = py - AXIS_H - i * LANE_H, t = tAt(px);
  if (px < LABEL_W) return { r };
  if (y < BAR_Y - 1) {
    let best = null;
    for (const [mx, m] of state.drawn[r.name] || []) {
      if (Math.abs(mx - px) <= 6 && (!best || Math.abs(mx - px) < Math.abs(best[0] - px))) best = [mx, m];
    }
    return best ? { r, marker: best[1] } : { r };
  }
  if (t > state.data.now) return { r };
  if (y < BAR_Y + BAR_H + 2) {
    const c = at(r.conversations, t);
    if (c && y >= BAR_Y + 4 && y <= BAR_Y + BAR_H - 4) return { r, conversation: c };
    return { r, segment: at(r.segments, t) };
  }
  return { r, purse: [t, purseAt(r.purse, t)] };
}

function describeSegment(s) {
  const what = s.kind === "work" ? `Work · ${s.task == null ? "no task held" : `task ${s.task}`}` : KIND_NAMES[s.kind];
  const where = s.kind === "movement" ? `to ${placeName(s.place)}` : placeName(s.place);
  return `<b>${esc(what)}</b>\n${esc(where)}\n${between(s.start, s.end)} (${duration(s.end - s.start)})`;
}

function describe(m, by, who) {
  const own = by === who;
  switch (m.kind) {
    case "speech": {
      const how = m.private ? "privately " : "";
      return [own ? `said ${how}to ${listed(m.to)}` : `${by} said ${how}to ${listed(m.to)}`, m.text];
    }
    case "claim": return [`claimed task ${m.task} (${m.instance_id})`];
    case "submission": {
      if (m.resolved === undefined) return [`handed in task ${m.task}, awaiting the verdict`];
      const counts = `fail-to-pass ${m.fail_to_pass.join("/")}, pass-to-pass ${m.pass_to_pass.join("/")}`;
      return [`handed in task ${m.task}: ${m.resolved ? "accepted" : `not accepted (${m.status})`}`, counts];
    }
    case "payment": return [`was paid ${money(m.amount)} for task ${m.task}`];
    case "abandon": return [`gave up task ${m.task}`];
    case "expiry": return [`lost task ${m.task}: the claim ran out unpaid`];
    case "gift": return own ? [`gave ${m.to} ${money(m.amount)}`] : [`received ${money(m.amount)} from ${by}`];
    case "skill_shared": return own ? [`passed the skill “${m.skill}” to ${m.to}`] : [`received the skill “${m.skill}” from ${by}`];
    case "rating": return own ? [`rated ${m.rated} ${m.score} of 5`, m.reason] : [`was rated ${m.score} of 5 by ${by}`, m.reason];
    case "journal": {
      const read = m.ratings_read.length ? `\n\nRatings read: ${m.ratings_read.map(([s, why]) => `${s} of 5, “${why}”`).join("; ")}` : "";
      return [`went to bed until ${hhmm(m.wake)} and wrote the journal of day ${m.day}`, m.text + read];
    }
    case "forced_sleep": return [`fell asleep at the forced hour without a journal entry, to wake at ${hhmm(m.wake)}`];
    default: return [m.kind];
  }
}

function showTip(h, px, py) {
  let html = null;
  if (h && h.marker) {
    const [label, text] = describe(h.marker, h.r.name, h.r.name);
    html = `<b>${esc(h.r.name)}</b> ${esc(label)}${text ? `\n${esc(text.length > 400 ? `${text.slice(0, 400)}…` : text)}` : ""}\n<span class="muted">${moment(h.marker.t)} · ${esc(placeName(h.marker.place))}</span>`;
  } else if (h && h.conversation) {
    const c = h.conversation;
    html = `<b>Conversation</b> with ${esc(listed(c.with))}\nover ${esc(KIND_NAMES[c.over].toLowerCase())} at ${esc(placeName(c.place))}\n${between(c.start, c.end)} (${duration(c.end - c.start)})`;
  } else if (h && h.segment) {
    html = describeSegment(h.segment);
  } else if (h && h.purse) {
    html = `<b>Purse</b> ${money(h.purse[1])}\n${moment(h.purse[0])}`;
  }
  if (!html) { tip.hidden = true; return; }
  tip.innerHTML = html;
  tip.hidden = false;
  const box = $("plot").getBoundingClientRect();
  const left = Math.min(px + 14, box.width - tip.offsetWidth - 4), top = py + 16 + tip.offsetHeight > box.height ? py - tip.offsetHeight - 8 : py + 16;
  tip.style.left = `${Math.max(left, 4)}px`;
  tip.style.top = `${Math.max(top, 4)}px`;
}

// The panel -------------------------------------------------------------------------------

let panelTimer = null;
function schedulePanel() {
  clearTimeout(panelTimer);
  panelTimer = setTimeout(() => { renderPanel(); writeHash(); }, 120);
}

function renderPanel() {
  const who = state.selected, list = $("entries");
  const r = state.data && state.data.residents.find((x) => x.name === who);
  if (!r) {
    $("who").textContent = "No resident selected";
    $("window").textContent = "Click a lane to list what that resident did and heard in the visible window.";
    list.replaceChildren();
    return;
  }
  const { t0, t1 } = state;
  const found = [];
  for (const other of state.data.residents) {
    for (let i = lowerBound(other.markers, t0, (m) => m.t); i < other.markers.length && other.markers[i].t <= t1; i++) {
      const m = other.markers[i];
      const concerns = other.name === who
        || (m.kind === "speech" && m.to.includes(who))
        || ((m.kind === "gift" || m.kind === "skill_shared") && m.to === who)
        || (m.kind === "rating" && m.rated === who);
      if (concerns) found.push([m, other.name]);
    }
  }
  found.sort((a, b) => a[0].seq - b[0].seq);
  $("who").textContent = who;
  const shown = found.slice(0, PANEL_LIMIT);
  $("window").textContent = `${between(Math.max(t0, state.data.start), Math.min(t1, state.data.now))} · purse ${money(purseAt(r.purse, Math.min(t1, state.data.now)))} · ${found.length} entr${found.length === 1 ? "y" : "ies"}${found.length > shown.length ? `, the first ${shown.length} shown` : ""}`;
  list.replaceChildren(...shown.map(([m, by]) => {
    const [label, text] = describe(m, by, who);
    const li = document.createElement("li");
    li.dataset.t = m.t;
    li.innerHTML = `<time>${moment(m.t)} · ${esc(placeName(m.place))}</time>${esc(label)}${text ? `<div class="text${m.kind === "journal" ? " journal" : ""}">${esc(text)}</div>` : ""}`;
    return li;
  }));
}

// Loading ---------------------------------------------------------------------------------

async function getJSON(url) {
  const response = await fetch(url, { cache: "no-store" });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || response.statusText);
  return body;
}

function message(text) {
  $("message").hidden = !text;
  $("message").textContent = text || "";
}

function renderRuns() {
  const select = $("run");
  select.replaceChildren(new Option("All runs", OVERVIEW), ...state.runs.map((run) => {
    const option = document.createElement("option");
    option.value = run.name;
    option.textContent = `${run.name} (${run.status}, ${run.days} day${run.days === 1 ? "" : "s"} done)`;
    return option;
  }));
  select.value = state.run ?? OVERVIEW;
}

// Shows the overview when no run is chosen, and the chosen run's timeline otherwise.
function showView() {
  document.body.classList.toggle("overview", state.run === null);
  if (state.run === null) {
    $("status").textContent = "";
    history.replaceState(null, "", "#progress");
  }
}

function renderStatus() {
  const run = state.runs.find((r) => r.name === state.run);
  $("status").textContent = run && state.data ? `${run.status} · log reaches ${moment(state.data.now)}` : "";
}

async function loadRun(view) {
  const name = state.run;
  if (!name) return;
  state.busy = true;
  try {
    const data = await getJSON(`/api/timeline?run=${encodeURIComponent(name)}`);
    if (state.run !== name) return; // another run was chosen meanwhile
    const before = state.data;
    state.data = data;
    message(data.residents.length ? "" : "This run has no residents.");
    if (view) setView(view[0], view[1]);
    else if (!before) wholeRun();
    else {
      const [d0, d1] = domain(before), grown = data.now - before.now;
      if (state.t0 <= d0 && state.t1 >= d1) wholeRun(); // the whole run stays whole
      else if (state.t1 >= before.now) setView(state.t0 + grown, state.t1 + grown); // follow the end
      else setView(state.t0, state.t1);
    }
    renderStatus();
  } catch (error) {
    if (state.run === name) message(`Could not load ${name}: ${error.message}`);
  } finally {
    state.busy = false;
  }
}

// The overview: one table per run, a row per lived day, the day in progress highlighted.
async function loadProgress() {
  state.busy = true;
  try {
    const runs = await getJSON("/api/progress");
    if (state.run !== null) return; // a run was chosen meanwhile
    state.runs = runs;
    renderRuns();
    const running = runs.filter((r) => r.status === "running").length;
    $("status").textContent = `${runs.length} run${runs.length === 1 ? "" : "s"}, ${running} running`;
    $("progress").innerHTML = runs.length ? runs.map(progressTable).join("") : "<p>There are no runs under the runs root yet.</p>";
  } catch (error) {
    if (state.run === null) $("progress").innerHTML = `<p>Could not load the progress of the runs: ${esc(error.message)}</p>`;
  } finally {
    state.busy = false;
  }
}

function progressTable(run) {
  const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
  const pace = run.hours_per_day == null ? "no day completed yet" : `${run.hours_per_day.toFixed(2)} real hours per day`;
  const head = PROGRESS_COLUMNS.map(([name, title]) => `<th title="${esc(title)}">${esc(name)}</th>`).join("");
  const rows = run.daily.map((d) => {
    const cells = PROGRESS_COLUMNS.map(([, , cell]) => {
      const value = typeof cell === "string" ? d[cell] : cell(d, run);
      return `<td${value === 0 ? ' class="zero"' : ""}>${esc(value)}</td>`;
    });
    return `<tr${d.in_progress ? ' class="current" title="The day in progress"' : ""}>${cells.join("")}</tr>`;
  });
  return `<article class="run-progress"><h2>${esc(run.name)}</h2>`
    + `<p class="muted">${esc(run.status)} · day ${run.day} at ${run.clock} · ${plural(run.days, "day")} done · ${pace}</p>`
    + `<table><thead><tr>${head}</tr></thead><tbody>${rows.join("")}</tbody></table></article>`;
}

async function refresh() {
  if (state.busy || document.hidden) return;
  if (state.run === null) {
    if (state.runs.some((r) => r.status === "running")) await loadProgress();
    return;
  }
  const run = state.runs.find((r) => r.name === state.run);
  if (!run || run.status !== "running") return;
  try {
    state.runs = await getJSON("/api/runs");
    renderRuns();
  } catch (error) {
    message(`Could not list the runs: ${error.message}`);
    return;
  }
  await loadRun();
}

function readHash() {
  const p = new URLSearchParams(location.hash.slice(1));
  const from = Number(p.get("from")), to = Number(p.get("to"));
  return {
    overview: p.has("progress"), run: p.get("run"), who: p.get("who"),
    view: p.has("from") && p.has("to") && to > from ? [from, to] : null,
  };
}

function writeHash() {
  if (!state.run) return;
  const p = new URLSearchParams({ run: state.run });
  if (state.selected) p.set("who", state.selected);
  if (state.data) { p.set("from", Math.round(state.t0)); p.set("to", Math.round(state.t1)); }
  history.replaceState(null, "", `#${p}`);
}

function renderLegend() {
  const items = ["idle", "movement", "work", "sleep"].map((k) => `<span><i class="swatch" style="background:var(--${k})"></i>${KIND_NAMES[k]}</span>`);
  items.push(`<span><i class="swatch" style="background:var(--conversation);height:6px"></i>Conversation, over what it interrupted</span>`);
  $("legend").innerHTML = items.join("") + Object.keys(MARKERS).map((k) => `<span data-marker="${k}"><canvas width="28" height="28"></canvas>${MARKERS[k]}</span>`).join("")
    + `<span><i class="swatch" style="border-left:2px dashed var(--muted);border-radius:0;width:2px"></i>daily checkpoint</span><span><i class="swatch" style="border-bottom:2px solid var(--ink-2);border-radius:0;height:8px"></i>purse, one scale for all</span>`;
  for (const span of $("legend").querySelectorAll("[data-marker]")) {
    const g = span.querySelector("canvas").getContext("2d");
    g.scale(2, 2);
    const kind = span.dataset.marker;
    drawMarker(g, { kind, resolved: kind === "submission" ? true : undefined }, 7, 7);
  }
}

// Events ----------------------------------------------------------------------------------

canvas.addEventListener("wheel", (e) => {
  if (!state.data) return;
  e.preventDefault();
  if (e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY)) pan((e.deltaX || e.deltaY) / plotW());
  else zoom(Math.exp(e.deltaY * 0.0015), Math.max(tAt(e.offsetX), state.t0));
}, { passive: false });

canvas.addEventListener("pointerdown", (e) => {
  state.drag = { x: e.offsetX, y: e.offsetY, t0: state.t0, t1: state.t1, moved: false };
  canvas.setPointerCapture(e.pointerId);
});
canvas.addEventListener("pointermove", (e) => {
  const d = state.drag;
  if (d && state.data) {
    if (Math.abs(e.offsetX - d.x) > 3) { d.moved = true; canvas.classList.add("dragging"); tip.hidden = true; }
    if (d.moved) {
      const shift = ((d.x - e.offsetX) / plotW()) * (d.t1 - d.t0);
      setView(d.t0 + shift, d.t1 + shift);
    }
    return;
  }
  if (state.data) showTip(hit(e.offsetX, e.offsetY), e.offsetX, e.offsetY);
});
canvas.addEventListener("pointerup", (e) => {
  const d = state.drag;
  state.drag = null;
  canvas.classList.remove("dragging");
  if (d && !d.moved && state.data) {
    const h = hit(e.offsetX, e.offsetY);
    if (h) { state.selected = h.r.name; draw(); schedulePanel(); }
  }
});
canvas.addEventListener("pointerleave", () => { if (!state.drag) tip.hidden = true; });

$("entries").addEventListener("click", (e) => {
  const li = e.target.closest("li");
  if (!li) return;
  const t = Number(li.dataset.t), half = (state.t1 - state.t0) / 2;
  setView(t - half, t + half);
});
$("run").addEventListener("change", () => {
  const value = $("run").value;
  state.run = value === OVERVIEW ? null : value;
  state.data = null;
  state.selected = null;
  showView();
  if (state.run === null) loadProgress();
  else loadRun();
});
$("all").addEventListener("click", () => state.data && wholeRun());
$("day").addEventListener("click", () => state.data && oneDay());
$("earlier").addEventListener("click", () => state.data && pan(-0.5));
$("later").addEventListener("click", () => state.data && pan(0.5));
$("out").addEventListener("click", () => state.data && zoom(2));
$("in").addEventListener("click", () => state.data && zoom(0.5));
new ResizeObserver(() => draw()).observe($("plot"));
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { readColours(); renderLegend(); draw(); });

async function start() {
  readColours();
  renderLegend();
  try {
    state.runs = await getJSON("/api/runs");
  } catch (error) {
    message(`Could not list the runs: ${error.message}`);
    return;
  }
  const wanted = readHash();
  const running = state.runs.find((r) => r.status === "running");
  const chosen = state.runs.some((r) => r.name === wanted.run) ? wanted.run : (running || state.runs[0] || {}).name;
  state.run = wanted.overview || !chosen ? null : chosen;
  state.selected = wanted.who;
  renderRuns();
  showView();
  if (state.run === null) await loadProgress();
  else await loadRun(wanted.run === state.run ? wanted.view : null);
  setInterval(refresh, REFRESH_MS);
}

start();
