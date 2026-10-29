// Renders every route of a published site in headless Chromium, at a desktop, a tablet and a
// phone width, and fails on what a reader would meet as broken: an error or uncaught exception in
// the console, a request that fails, a view that never finishes loading, and horizontal overflow
// of the document (scrollWidth > clientWidth) or of the town's panels. At the touch widths it
// also plays the town with a finger: drags the day's strip, plays, changes the speed, opens the
// sheet and its panels, picks a resident and lets go of it while the town plays, pauses, then
// leaves for the dashboard and comes back; it fails when a control does not answer, when the
// address is rewritten more often than twice a second (browsers stop following a page that
// rewrites it faster, links included), when the address does not follow the moment once the
// drag ends, or when a control under a finger is made anew before the finger lifts (Safari then
// drops the tap).
//
//   node tests/frontend/render_check.mjs SITE [--run NAME] [--route NAME] [--shots DIR] [--dark]
//
// The site is served from a local port. The routes are the home page, every comparison, and
// for one run (the first, or NAME) the dashboard with each of its sections, the town with each
// panel, the timeline over the whole run and zoomed in to one hour with a moment shown, one
// resident with each tab, and the evaluation; `--route` keeps one of them, by the name the
// summary gives it, and `--at MOMENT` (`5-09:05`, calendar day and clock) shows the town and
// the resident at that moment instead of the newest. `--shots` writes a full-page screenshot of
// every route and width into DIR; `--dark` renders in the dark colour scheme. Chromium is found through
// SOCIO_EVO_CHROME, else in Playwright's cache, else on PATH. Prints a JSON summary, an overflow
// naming the widest elements outside any sideways-scrolling box; exits 1 on failures and 2 when
// no Chromium is found.

import { execFileSync, spawn } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { createServer } from "node:http";
import { homedir, tmpdir } from "node:os";
import { dirname, extname, join, resolve } from "node:path";

const WIDTHS = [
  { width: 1440, height: 900, mobile: false },
  { width: 768, height: 1024, mobile: true },
  { width: 390, height: 844, mobile: true },
];
const SETTLE_MS = 20000;
const TYPES = { ".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript", ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png" };
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));

const args = process.argv.slice(2);
const options = { "--run": null, "--route": null, "--at": null, "--shots": null, "--dark": false };
const positional = [];
for (let i = 0; i < args.length; i++) {
  if (args[i] === "--dark") options[args[i]] = true;
  else if (args[i] in options) options[args[i]] = args[++i];
  else positional.push(args[i]);
}
if (positional.length !== 1) {
  console.error("usage: node render_check.mjs SITE [--run NAME] [--route NAME] [--at MOMENT] [--shots DIR] [--dark]");
  process.exit(2);
}
const site = resolve(positional[0]);
const runName = options["--run"];
const onlyRoute = options["--route"];
const at = options["--at"];
const shots = options["--shots"];
const dark = options["--dark"];

function findChrome() {
  if (process.env.SOCIO_EVO_CHROME) return process.env.SOCIO_EVO_CHROME;
  const cache = join(homedir(), ".cache", "ms-playwright");
  for (const dir of existsSync(cache) ? readdirSync(cache).sort().reverse() : [])
    for (const candidate of [join(cache, dir, "chrome-headless-shell-linux64", "chrome-headless-shell"), join(cache, dir, "chrome-linux", "chrome")]) if (existsSync(candidate)) return candidate;
  for (const name of ["chromium", "chromium-browser", "google-chrome", "chrome"]) {
    try {
      return execFileSync("which", [name], { stdio: ["ignore", "pipe", "ignore"] }).toString().trim();
    } catch {
      /* not on PATH */
    }
  }
  return null;
}

/** The site on a local port, as any static server would serve it. */
function serve(root) {
  return new Promise((ready) => {
    const server = createServer(async (request, response) => {
      const path = decodeURIComponent(new URL(request.url, "http://localhost").pathname);
      const file = resolve(join(root, path === "/" ? "index.html" : path));
      try {
        if (!file.startsWith(root)) throw new Error("outside the site");
        const data = await readFile(file);
        response.writeHead(200, { "content-type": TYPES[extname(file)] ?? "application/octet-stream", "cache-control": "no-store" });
        response.end(data);
      } catch {
        response.writeHead(404);
        response.end();
      }
    });
    server.listen(0, "127.0.0.1", () => ready({ server, url: `http://127.0.0.1:${server.address().port}/` }));
  });
}

/** Headless Chromium driven over the DevTools protocol: one page, its console and network kept. */
async function launch(chrome) {
  const profile = mkdtempSync(join(tmpdir(), "socio-evo-render-"));
  const proc = spawn(chrome, ["--headless", "--no-sandbox", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "about:blank"], { stdio: ["ignore", "ignore", "pipe"] });
  const port = await new Promise((found, failed) => {
    let text = "";
    proc.stderr.on("data", (chunk) => {
      text += chunk;
      const match = /DevTools listening on ws:\/\/127\.0\.0\.1:(\d+)\//.exec(text);
      if (match) found(Number(match[1]));
    });
    proc.on("exit", (code) => failed(new Error(`Chromium exited with ${code}: ${text.trim()}`)));
    setTimeout(() => failed(new Error(`Chromium did not start: ${text.trim()}`)), 15000);
  });
  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  const ws = new WebSocket(targets.find((target) => target.type === "page").webSocketDebuggerUrl);
  await new Promise((open) => (ws.onopen = open));
  let id = 0;
  const pending = new Map();
  const log = [];
  ws.onmessage = (message) => {
    const data = JSON.parse(message.data);
    if (data.id && pending.has(data.id)) {
      const { ok, fail } = pending.get(data.id);
      pending.delete(data.id);
      if (data.error) fail(new Error(JSON.stringify(data.error)));
      else ok(data.result);
    } else if (data.method === "Runtime.consoleAPICalled" && data.params.type === "error") log.push(`console.error: ${data.params.args.map((arg) => arg.value ?? arg.description).join(" ")}`);
    else if (data.method === "Runtime.exceptionThrown") log.push(`exception: ${data.params.exceptionDetails.exception?.description ?? data.params.exceptionDetails.text}`);
    else if (data.method === "Network.loadingFailed" && !data.params.canceled) log.push(`request failed: ${data.params.errorText}`);
    else if (data.method === "Network.responseReceived" && data.params.response.status >= 400) log.push(`HTTP ${data.params.response.status}: ${data.params.response.url}`);
  };
  const send = (method, params = {}) =>
    new Promise((ok, fail) => {
      pending.set(++id, { ok, fail });
      ws.send(JSON.stringify({ id, method, params }));
    });
  await send("Page.enable");
  await send("Runtime.enable");
  await send("Network.enable");
  await send("Network.setCacheDisabled", { cacheDisabled: true });
  const evaluate = async (expression) => {
    const result = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description ?? result.exceptionDetails.text);
    return result.result.value;
  };
  const touch = (type, points) => send("Input.dispatchTouchEvent", { type, touchPoints: points.map(([x, y], id) => ({ x, y, id })) });
  return {
    log,
    evaluate,
    touch,
    async viewport({ width, height, mobile }) {
      await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile });
      await send("Emulation.setTouchEmulationEnabled", { enabled: mobile });
    },
    scheme: (name) => send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: name }] }),
    go: (url) => send("Page.navigate", { url }),
    async shot(path) {
      const { cssContentSize } = await send("Page.getLayoutMetrics");
      const clip = { x: 0, y: 0, width: cssContentSize.width, height: Math.min(cssContentSize.height, 5000), scale: 1 };
      const { data } = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true, clip });
      writeFileSync(path, Buffer.from(data, "base64"));
    },
    close() {
      ws.close();
      proc.kill();
      rmSync(profile, { recursive: true, force: true });
    },
  };
}

/** Whether the view has finished loading: something is shown, no spinner is in view, the map is uncovered. */
const SETTLED = `(() => {
  const main = document.getElementById("main");
  if (!main || !main.children.length) return false;
  if ([...document.querySelectorAll(".loading")].some((el) => !el.closest("[hidden]"))) return false;
  const curtain = document.querySelector(".map-curtain");
  return !curtain || curtain.hidden || curtain.classList.contains("failed");
})()`;

/**
 * What the page measures: the document's width against the viewport, naming the widest elements
 * outside any box that scrolls sideways on purpose, and the town's own boxes.
 */
const MEASURES = `(() => {
  const root = document.documentElement;
  const overflow = [];
  const scrolls = (el) => {
    for (let e = el.parentElement; e; e = e.parentElement) if (["auto", "scroll"].includes(getComputedStyle(e).overflowX)) return true;
    return false;
  };
  const name = (el) => el.tagName.toLowerCase() + (typeof el.className === "string" && el.className.trim() ? "." + el.className.trim().split(/\\s+/).join(".") : "");
  if (root.scrollWidth > root.clientWidth) {
    const wide = [...document.querySelectorAll("body *")]
      .filter((el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.right > root.clientWidth + 1 && !scrolls(el); })
      .slice(0, 4)
      .map((el) => name(el) + " to " + Math.round(el.getBoundingClientRect().right));
    overflow.push("document " + root.scrollWidth + " > " + root.clientWidth + (wide.length ? " (" + wide.join(", ") + ")" : ""));
  }
  for (const selector of [".panel-body", ".selected-box", ".town .timeline", ".town-dock"]) {
    const el = document.querySelector(selector);
    if (el && el.scrollWidth > el.clientWidth + 1) overflow.push(selector + " " + el.scrollWidth + " > " + el.clientWidth);
  }
  const fatal = document.querySelector("#main .fatal");
  const curtain = document.querySelector(".map-curtain");
  return { overflow, text: document.getElementById("main").innerText.trim().length, fatal: fatal ? fatal.innerText.trim() : null, covered: Boolean(curtain && !curtain.hidden) };
})()`;

/** Every write of the address, timed: replaced or pushed by the page. */
const COUNT_WRITES = `(() => {
  window.__writes = [];
  for (const name of ["replaceState", "pushState"]) {
    const write = history[name].bind(history);
    history[name] = (...args) => (window.__writes.push(performance.now()), write(...args));
  }
})()`;

/**
 * Play the town at `hash` with a finger and then use its other controls; returns what failed.
 * `go(hash)` opens a route and resolves to whether it settled.
 */
async function exercise(page, go, hash) {
  const failed = [];
  const check = (ok, what) => ok || failed.push(what);
  const at = (selector) => page.evaluate(`(() => { const el = document.querySelector(${JSON.stringify(selector)}); if (!el) return null; const r = el.getBoundingClientRect(); return r.width && r.height ? [r.left + r.width / 2, r.top + r.height / 2, r.width] : null; })()`);
  const read = (expression) => page.evaluate(expression);
  const clock = () => read(`document.querySelector(".tl-clock")?.innerText`);
  const tap = async (selector, hold = 60) => {
    const point = await at(selector);
    if (!point) return check(false, `nothing to tap at ${selector}`), false;
    await page.touch("touchStart", [point]);
    await sleep(hold);
    await page.touch("touchEnd", []);
    await sleep(250);
    return true;
  };
  if (!(await go(hash))) return ["the town did not finish loading"];
  await read(COUNT_WRITES);

  // Drag along the day's strip for a while, as a finger scrubs, from its end to before its middle.
  const strip = await at(".strip-wrap.day");
  if (!strip) return ["the town has no day strip"];
  const [cx, cy, width] = strip;
  const [from, to] = [cx + width / 2 - 4, cx - width * 0.1];
  const before = await clock();
  const started = Date.now();
  await page.touch("touchStart", [[from, cy]]);
  for (let i = 0; i <= 60; i++) await page.touch("touchMove", [[from + ((to - from) * i) / 60, cy]]);
  await page.touch("touchEnd", []);
  const writes = await read("window.__writes");
  const gaps = writes.slice(1).map((t, i) => t - writes[i]);
  check(gaps.every((gap) => gap >= 450), `the address was written ${writes.length} times in a ${Date.now() - started} ms drag, at times less than half a second apart`);
  check((await clock()) !== before, "dragging the day's strip did not move the moment");
  await sleep(700);
  check(await read(`(() => { const t = new URLSearchParams(location.hash.split("?")[1]).get("t"); return Boolean(t) && document.querySelector(".tl-clock").innerText.includes(t.split("-")[1]); })()`), "the address did not follow the moment once the drag ended");

  // Play, change the speed, and use the panels while the town plays.
  const shown = await clock();
  await tap(".tl-transport .play");
  await sleep(1200);
  check((await clock()) !== shown, "playing did not move the moment");
  const speed = await read(`document.querySelector(".tl-speed").textContent`);
  await tap(".tl-speed");
  check((await read(`document.querySelector(".tl-speed").textContent`)) !== speed, "the speed did not change");
  if ((await read(`document.querySelector(".town-dock").dataset.state`)) === "peek") await tap(".sheet-grip");
  check((await read(`document.querySelector(".town-dock").dataset.state`)) !== "peek", "the sheet did not open");
  for (const panel of ["feed", "work", "day", "people"]) {
    await tap(`.panel-tabs [data-panel=${panel}]`);
    check(await read(`document.querySelector(".panel-tabs [data-panel=${panel}]").getAttribute("aria-selected") === "true"`), `the ${panel} panel did not open`);
  }
  await tap(".people-list li:first-child .person-row");
  check(await read(`!document.querySelector(".selected-box").hidden`), "picking a resident in the roster did not select it");
  // A finger rests on the selection's close button while the town plays: the button under it
  // must be the same element when it lifts, and the tap must land.
  const close = await at(".selected-box .icon-btn");
  if (close) {
    await page.touch("touchStart", [close]);
    await read(`window.__under = document.elementFromPoint(${close[0]}, ${close[1]}).closest("button")`);
    await sleep(400);
    check(await read(`window.__under.isConnected && document.elementFromPoint(${close[0]}, ${close[1]}).closest("button") === window.__under`), "a button under a finger was made anew while the town played");
    await page.touch("touchEnd", []);
    await sleep(250);
    check(await read(`document.querySelector(".selected-box").hidden`), "the close button did not clear the selection while the town played");
  } else check(false, "the selected resident has no close button");
  await tap(".tl-transport .play");
  check(await read(`document.querySelector(".tl-transport .play").getAttribute("aria-label").startsWith("Play")`), "the town did not pause");

  // Leave by the tab bar, and come back with the Back button to the moment left.
  const left = await clock();
  await tap(`.tabs a[data-view="overview"]`);
  await sleep(500);
  check(await read(`document.body.dataset.view === "overview"`), "the tab bar did not open the dashboard");
  await read("setTimeout(() => history.back()), true");
  await sleep(1500);
  check((await read(`document.body.dataset.view`)) === "town" && (await clock()) === left, "the Back button did not return to the town at the moment left");
  return failed;
}

/** The routes of the site: the home page, every comparison, and one run's views. */
function routes() {
  const index = JSON.parse(readFileSync(join(site, "data", "index.json"), "utf8"));
  const found = [["home", "#/"]];
  for (const comparison of index.comparisons ?? []) found.push([`compare-${comparison.name}`, `#/compare/${encodeURIComponent(comparison.name)}`]);
  const entry = runName ? index.runs.find((run) => run.name === runName) : index.runs[0];
  if (runName && !entry) throw new Error(`no run ${runName} in the index`);
  if (!entry) return found;
  const runFile = join(site, "data", entry.url.split("?")[0]);
  const run = JSON.parse(readFileSync(runFile, "utf8"));
  const timeline = JSON.parse(readFileSync(join(dirname(runFile), run.timeline.split("?")[0]), "utf8"));
  const base = `#/run/${encodeURIComponent(entry.name)}`;
  found.push(["run", base]);
  for (const section of ["money", "trade", "body", "social", "evolution", "evaluation", "usage"]) found.push([`run-${section}`, `${base}?section=${section}`]);
  const when = at ? `&t=${at}` : "";
  found.push(["town", `${base}/town?${when.slice(1)}`]);
  const agent = run.residents[0]?.name;
  if (agent) {
    for (const panel of ["people", "feed", "work", "ties", "day"]) found.push([`town-${panel}`, `${base}/town?panel=${panel}&agent=${encodeURIComponent(agent)}${when}`]);
    found.push(["timeline", `${base}/timeline?agent=${encodeURIComponent(agent)}`]);
    // One hour of the first day, five hours in, with the moment shown in its middle.
    const from = timeline.start + 5 * 3600;
    const moment = from + 1800;
    const stamp = `${Math.floor(moment / 86400) + 1}-${String(Math.floor((moment % 86400) / 3600)).padStart(2, "0")}:${String(Math.floor((moment % 3600) / 60)).padStart(2, "0")}`;
    found.push(["timeline-hour", `${base}/timeline?agent=${encodeURIComponent(agent)}&t=${stamp}&from=${from}&to=${from + 3600}`]);
    found.push(["person", `${base}/people/${encodeURIComponent(agent)}?${when.slice(1)}`]);
    for (const tab of ["day", "journal", "files", "trace"]) found.push([`person-${tab}`, `${base}/people/${encodeURIComponent(agent)}?tab=${tab}${when}`]);
  } else found.push(["timeline", `${base}/timeline`]);
  found.push(["evaluation", `${base}/evaluation`]);
  return found;
}

const chrome = findChrome();
if (!chrome) {
  console.log(JSON.stringify({ skipped: "no Chromium found: set SOCIO_EVO_CHROME or install Playwright's chromium" }));
  process.exit(2);
}
const { server, url } = await serve(site);
const page = await launch(chrome);
if (shots) mkdirSync(shots, { recursive: true });
const failures = [];
let checks = 0;
let interactions = 0;
try {
  await page.scheme(dark ? "dark" : "light");
  const found = routes().filter(([name]) => !onlyRoute || name === onlyRoute);
  if (!found.length) throw new Error(`no route named ${onlyRoute}`);
  /** Open a route and wait until it has finished loading; whether it did. */
  const go = async (hash) => {
    await page.go("about:blank");
    await sleep(50);
    await page.go(url + hash);
    const start = Date.now();
    let settled = false;
    while (Date.now() - start < SETTLE_MS && !settled) {
      await sleep(100);
      settled = await page.evaluate(SETTLED).catch(() => false);
    }
    await sleep(400);
    return settled;
  };
  for (const size of WIDTHS) {
    await page.viewport(size);
    for (const [name, hash] of found) {
      const where = `${name} at ${size.width}px`;
      page.log.length = 0;
      const settled = await go(hash);
      const measured = await page.evaluate(MEASURES);
      checks += 1;
      if (!settled) failures.push({ where, what: "did not finish loading" });
      if (!measured.text) failures.push({ where, what: "nothing shown" });
      if (measured.fatal) failures.push({ where, what: `the viewer gave up: ${measured.fatal}` });
      for (const line of measured.overflow) failures.push({ where, what: `horizontal overflow: ${line}` });
      for (const line of page.log) failures.push({ where, what: line });
      if (shots) await page.shot(join(shots, `${size.width}${dark ? "-dark" : ""}-${name}.png`));
      if (name === "town" && size.mobile && !measured.covered) {
        page.log.length = 0;
        const what = await exercise(page, go, hash);
        interactions += 1;
        for (const line of [...what, ...page.log]) failures.push({ where: `the town played by touch at ${size.width}px`, what: line });
      }
    }
  }
} finally {
  page.close();
  server.close();
}
console.log(JSON.stringify({ chrome, routes: checks / WIDTHS.length, widths: WIDTHS.length, checks, interactions, failures }, null, 1));
process.exit(failures.length ? 1 : 0);
