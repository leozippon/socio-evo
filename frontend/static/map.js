// Town map on a canvas: places at their configured coordinates, agents as tokens.

const PALETTE = ["#0072b2", "#e69f00", "#009e73", "#cc79a7", "#d55e00", "#56b4e9", "#b3a100", "#7a7a7a"];
export const agentColor = (world, name) => PALETTE[world.agents.findIndex((a) => a.name === name) % PALETTE.length];

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

export class TownMap {
  constructor(canvas, world, { onSelect }) {
    this.canvas = canvas;
    this.world = world;
    this.onSelect = onSelect;
    this.ctx = canvas.getContext("2d");
    this.shown = {}; // agent -> {x, y} currently drawn, easing towards its target
    this.selected = null;
    this.bubbleWindow = 15; // simulated minutes a line of speech stays up
    canvas.addEventListener("click", (e) => this.click(e));
    new ResizeObserver(() => this.resize()).observe(canvas.parentElement);
    this.resize();
  }

  resize() {
    const width = this.canvas.parentElement.clientWidth;
    const xs = this.world.places.map((p) => p.x);
    const ys = this.world.places.map((p) => p.y);
    this.spanX = Math.max(...xs) - Math.min(...xs);
    this.spanY = Math.max(...ys) - Math.min(...ys);
    this.unit = width / (this.spanX + 1.6);
    const height = Math.max(240, this.unit * (this.spanY + 1.6));
    const ratio = window.devicePixelRatio || 1;
    this.canvas.style.height = `${height}px`;
    this.canvas.width = width * ratio;
    this.canvas.height = height * ratio;
    this.ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    this.width = width;
    this.height = height;
    this.minX = Math.min(...xs);
    this.minY = Math.min(...ys);
    this.shown = {};
    this.ctx.font = "600 11px system-ui, sans-serif";
    this.labels = Object.fromEntries(
      this.world.places.map((p) => [p.id, wrap(this.ctx, p.name, Math.min(this.unit * 0.92, 170) - 12, 3)]),
    );
  }

  /** Pixel centre of a place. */
  centre(place) {
    return {
      x: this.width / 2 + (place.x - this.minX - this.spanX / 2) * this.unit,
      y: this.height / 2 + (place.y - this.minY - this.spanY / 2) * this.unit,
    };
  }

  box(place) {
    const c = this.centre(place);
    const w = Math.min(this.unit * 0.92, 170);
    const h = Math.min(this.unit * 0.88, 150);
    return { x: c.x - w / 2, y: c.y - h / 2, w, h };
  }

  /** Where each agent's token belongs, spread over a grid inside its place. */
  targets(locations) {
    const byPlace = {};
    for (const [name, id] of Object.entries(locations)) (byPlace[id] ??= []).push(name);
    const out = {};
    for (const place of this.world.places) {
      const names = byPlace[place.id] ?? [];
      const b = this.box(place);
      const top = b.y + 30 + this.labels[place.id].length * 13;
      const room = { w: b.w - 8, h: b.y + b.h - top - 4 };
      let r = 11;
      let cell = { w: 48, h: 2 * r + 15 };
      let cols;
      for (;;) {
        cols = Math.max(1, Math.floor(room.w / cell.w));
        if (Math.ceil(names.length / cols) * cell.h <= room.h || r <= 6) break;
        r -= 1;
        cell = { w: Math.max(40, 2 * r + 24), h: 2 * r + 15 };
      }
      names.forEach((name, i) => {
        const inRow = Math.min(cols, names.length - Math.floor(i / cols) * cols);
        const col = i % cols;
        out[name] = {
          x: b.x + b.w / 2 + (col - (inRow - 1) / 2) * cell.w,
          y: top + Math.floor(i / cols) * cell.h + r,
          r,
        };
      });
    }
    return out;
  }

  /** Draw one frame for `state`; `dt` is seconds since the last frame. */
  draw(state, dt) {
    const ctx = this.ctx;
    ctx.clearRect(0, 0, this.width, this.height);
    for (const place of this.world.places) this.drawPlace(place);
    const target = this.targets(state.locations);
    const ease = Math.min(1, dt * 7);
    this.hit = [];
    for (const { name } of this.world.agents) {
      const t = target[name];
      if (!t) continue;
      const s = (this.shown[name] ??= { x: t.x, y: t.y });
      s.x += (t.x - s.x) * ease;
      s.y += (t.y - s.y) * ease;
      this.drawToken(name, s, t.r);
    }
    for (const { name } of this.world.agents) {
      const line = state.speech[name];
      if (line && state.time - line.time < this.bubbleWindow && state.time >= line.time) this.drawBubble(this.shown[name], line.text);
    }
  }

  drawPlace(place) {
    const ctx = this.ctx;
    const b = this.box(place);
    ctx.save();
    ctx.fillStyle = css(`--${place.kind}-fill`);
    ctx.strokeStyle = css(`--${place.kind}`);
    ctx.lineWidth = place.kind === "work" ? 2.5 : 1.5;
    if (place.kind === "social") ctx.setLineDash([6, 4]);
    ctx.beginPath();
    ctx.roundRect(b.x, b.y, b.w, b.h, place.kind === "work" ? 3 : place.kind === "social" ? 26 : 10);
    ctx.fill();
    ctx.stroke();
    ctx.restore();
    ctx.fillStyle = css("--muted");
    ctx.font = "9px system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "alphabetic";
    ctx.fillText(place.kind.toUpperCase(), b.x + b.w / 2, b.y + 12);
    ctx.fillStyle = css("--fg");
    ctx.font = "600 11px system-ui, sans-serif";
    this.labels[place.id].forEach((line, i) => ctx.fillText(line, b.x + b.w / 2, b.y + 25 + i * 13));
  }

  drawToken(name, at, r) {
    const ctx = this.ctx;
    const selected = name === this.selected;
    ctx.beginPath();
    ctx.arc(at.x, at.y, r, 0, 2 * Math.PI);
    ctx.fillStyle = agentColor(this.world, name);
    ctx.fill();
    ctx.lineWidth = selected ? 3 : 1.5;
    ctx.strokeStyle = selected ? css("--fg") : css("--bg");
    ctx.stroke();
    ctx.fillStyle = css("--fg");
    ctx.font = `${selected ? "700" : "500"} 11px system-ui, sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    ctx.fillText(name, at.x, at.y + r + 2);
    this.hit.push({ name, x: at.x, y: at.y, r: Math.max(r, 12) });
  }

  drawBubble(at, text) {
    if (!at) return;
    const ctx = this.ctx;
    ctx.font = "11px system-ui, sans-serif";
    const short = text.replace(/^[^:]+ says: /, "");
    const lines = wrap(ctx, short, 190, 3);
    const w = Math.max(...lines.map((l) => ctx.measureText(l).width)) + 14;
    const h = lines.length * 14 + 10;
    const x = Math.min(Math.max(at.x - w / 2, 4), this.width - w - 4);
    const y = Math.max(at.y - 22 - h, 4);
    ctx.fillStyle = css("--bubble");
    ctx.strokeStyle = css("--fg");
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.roundRect(x, y, w, h, 7);
    ctx.moveTo(at.x - 5, y + h);
    ctx.lineTo(at.x, y + h + 7);
    ctx.lineTo(at.x + 5, y + h);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = css("--fg");
    ctx.textAlign = "left";
    ctx.textBaseline = "alphabetic";
    lines.forEach((line, i) => ctx.fillText(line, x + 7, y + 15 + i * 14));
  }

  click(event) {
    const rect = this.canvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    const hit = (this.hit ?? []).find((t) => Math.hypot(t.x - x, t.y - y) <= t.r);
    if (hit) this.onSelect(hit.name);
  }
}

/** Split `text` into at most `maxLines` lines no wider than `width`, ending in an ellipsis if cut. */
function wrap(ctx, text, width, maxLines) {
  const lines = [];
  let line = "";
  const words = text.split(/\s+/);
  for (let i = 0; i < words.length; i++) {
    const next = line ? `${line} ${words[i]}` : words[i];
    if (ctx.measureText(next).width <= width || !line) line = next;
    else {
      lines.push(line);
      line = words[i];
    }
    if (lines.length === maxLines) {
      lines[maxLines - 1] = lines[maxLines - 1].replace(/\s*\S*$/, "") + "…";
      return lines;
    }
  }
  lines.push(line);
  return lines;
}
