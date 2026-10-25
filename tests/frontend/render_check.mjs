// Renders every route of a published site in headless Chromium, at a desktop and at a phone
// width, and fails on what a reader would meet as broken: an error or uncaught exception in the
// console, a request that fails, a view that never finishes loading, and horizontal overflow of
// the document (scrollWidth > clientWidth) or of the town's panels.
//
//   node tests/frontend/render_check.mjs SITE [--run NAME] [--route NAME] [--shots DIR] [--dark]
//
// The site is served from a local port. The routes are the home page, every comparison, and
// for one run (the first, or NAME) the dashboard with each of its sections, the town with each
// panel, the timeline, one resident with each tab, and the evaluation; `--route` keeps one of
// them, by the name the summary gives it. `--shots` writes a full-page screenshot of every route
// and width into DIR; `--dark` renders in the dark colour scheme. Chromium is found through
// SOCIO_EVO_CHROME, else in Playwright's cache, else on PATH. Prints a JSON summary, an overflow
// naming the widest elements outside any sideways-scrolling box; exits 1 on failures and 2 when
// no Chromium is found.

import { execFileSync, spawn } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { createServer } from "node:http";
import { homedir, tmpdir } from "node:os";
import { extname, join, resolve } from "node:path";

const WIDTHS = [
  { width: 1440, height: 900, mobile: false },
  { width: 390, height: 844, mobile: true },
];
const SETTLE_MS = 20000;
const TYPES = { ".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript", ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png" };
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));

const args = process.argv.slice(2);
const options = { "--run": null, "--route": null, "--shots": null, "--dark": false };
const positional = [];
for (let i = 0; i < args.length; i++) {
  if (args[i] === "--dark") options[args[i]] = true;
  else if (args[i] in options) options[args[i]] = args[++i];
  else positional.push(args[i]);
}
if (positional.length !== 1) {
  console.error("usage: node render_check.mjs SITE [--run NAME] [--route NAME] [--shots DIR] [--dark]");
  process.exit(2);
}
const site = resolve(positional[0]);
const runName = options["--run"];
const onlyRoute = options["--route"];
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
  return {
    log,
    evaluate,
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
  return { overflow, text: document.getElementById("main").innerText.trim().length };
})()`;

/** The routes of the site: the home page, every comparison, and one run's views. */
function routes() {
  const index = JSON.parse(readFileSync(join(site, "data", "index.json"), "utf8"));
  const found = [["home", "#/"]];
  for (const comparison of index.comparisons ?? []) found.push([`compare-${comparison.name}`, `#/compare/${encodeURIComponent(comparison.name)}`]);
  const entry = runName ? index.runs.find((run) => run.name === runName) : index.runs[0];
  if (runName && !entry) throw new Error(`no run ${runName} in the index`);
  if (!entry) return found;
  const run = JSON.parse(readFileSync(join(site, "data", entry.url.split("?")[0]), "utf8"));
  const base = `#/run/${encodeURIComponent(entry.name)}`;
  found.push(["run", base]);
  for (const section of ["money", "social", "evolution", "evaluation", "usage"]) found.push([`run-${section}`, `${base}?section=${section}`]);
  found.push(["town", `${base}/town`]);
  const agent = run.residents[0]?.name;
  if (agent) {
    for (const panel of ["people", "feed", "work", "ties", "day"]) found.push([`town-${panel}`, `${base}/town?panel=${panel}&agent=${encodeURIComponent(agent)}`]);
    found.push(["timeline", `${base}/timeline?agent=${encodeURIComponent(agent)}`]);
    found.push(["person", `${base}/people/${encodeURIComponent(agent)}`]);
    for (const tab of ["day", "journal", "ratings", "files", "trace"]) found.push([`person-${tab}`, `${base}/people/${encodeURIComponent(agent)}?tab=${tab}`]);
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
try {
  await page.scheme(dark ? "dark" : "light");
  const found = routes().filter(([name]) => !onlyRoute || name === onlyRoute);
  if (!found.length) throw new Error(`no route named ${onlyRoute}`);
  for (const size of WIDTHS) {
    await page.viewport(size);
    for (const [name, hash] of found) {
      const where = `${name} at ${size.width}px`;
      page.log.length = 0;
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
      const measured = await page.evaluate(MEASURES);
      checks += 1;
      if (!settled) failures.push({ where, what: "did not finish loading" });
      if (!measured.text) failures.push({ where, what: "nothing shown" });
      for (const line of measured.overflow) failures.push({ where, what: `horizontal overflow: ${line}` });
      for (const line of page.log) failures.push({ where, what: line });
      if (shots) await page.shot(join(shots, `${size.width}${dark ? "-dark" : ""}-${name}.png`));
    }
  }
} finally {
  page.close();
  server.close();
}
console.log(JSON.stringify({ chrome, routes: checks / WIDTHS.length, widths: WIDTHS.length, checks, failures }, null, 1));
process.exit(failures.length ? 1 : 0);
