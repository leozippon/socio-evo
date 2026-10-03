// Opt-in native Chromium form regression; no dependencies, header overrides or fetch submissions.
// CHROMIUM=/path/to/chrome node tests/frontend/native_form_check.mjs SERVICE=HTTPS_ORIGIN ...
// Optional private JSON on stdin: {SERVICE: {username, password}}. Never prints credentials/cookies.
// WEBUI_BROWSER_SPKI scopes a certificate exception to one certificate's public key (not CA validation).
// WEBUI_BROWSER_PROXY optionally supplies a Chromium proxy URL, e.g. socks5://127.0.0.1:PORT.
// WEBUI_BROWSER_SCREENSHOTS optionally names a private directory for authentication-page PNGs.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { setTimeout as delay } from "node:timers/promises";

const targets = process.argv.slice(2).map(arg => {
  const [service, origin] = arg.split("=");
  assert(["cornerhead", "socio-evo"].includes(service), "unknown service");
  const url = new URL(origin);
  assert(url.protocol === "https:" && url.origin === origin && url.port, "exact HTTPS origin required");
  return { service, origin };
});
assert(targets.length && process.env.CHROMIUM, "explicit CHROMIUM and targets required");
let input = "";
for await (const chunk of process.stdin) input += chunk;
let credentials;
try { credentials = input.trim() ? JSON.parse(input) : {}; }
catch { throw new Error("private credential stdin must be valid JSON (content withheld)"); }
const profile = await mkdtemp(join(tmpdir(), "webui-browser-"));
let browser, sessionId;
const pending = new Map();
const listeners = new Set();
let id = 0;
const deadline = setTimeout(() => { browser?.kill("SIGKILL"); process.exitCode = 1; }, 60000);
function command(method, params = {}) {
  return new Promise((resolve, reject) => {
    const key = ++id;
    const timer = setTimeout(() => { pending.delete(key); reject(new Error(`CDP timeout: ${method}`)); }, 10000);
    pending.set(key, msg => {
      clearTimeout(timer);
      if (msg.error) reject(new Error(`CDP failed: ${method}`));
      else resolve(msg.result);
    });
    browser.stdio[3].write(JSON.stringify({ id: key, method, params, sessionId }) + "\0");
  });
}
async function loaded(action) {
  let listener, timer;
  const load = new Promise((resolve, reject) => {
    timer = setTimeout(() => reject(new Error("navigation timeout")), 15000);
    listener = msg => { if (msg.method === "Page.loadEventFired") resolve(); };
    listeners.add(listener);
  });
  try { await action(); await load; }
  finally { clearTimeout(timer); listeners.delete(listener); }
}
async function evaluate(expression) {
  const result = await command("Runtime.evaluate", { expression, returnByValue: true });
  assert(!result.exceptionDetails, "page evaluation failed");
  return result.result.value;
}
// Check computed styles, not just markup: a blocked CSP stylesheet must fail here.
async function presentation(service, page) {
  const palettes = service === "cornerhead"
    ? { light: ["#f3f5f9", "#ffffff", "#2456c4"], dark: ["#12151c", "#1b1f28", "#3987e5"] }
    : { light: ["#f4efe4", "#fffdf8", "#1f1b14"], dark: ["#14120e", "#1e1b16", "#f1ebdf"] };
  const rgb = hex => `rgb(${[1, 3, 5].map(offset => parseInt(hex.slice(offset, offset + 2), 16)).join(", ")})`;
  for (const theme of ["light", "dark"]) {
    await command("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: theme }] });
    for (const [viewport, width, height] of [["desktop", 1280, 900], ["mobile", 320, 640]]) {
      await command("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: viewport === "mobile" });
      const styles = await evaluate(`(() => {
        const card = document.querySelector('.card');
        const action = document.querySelector('button, .button-link');
        const css = element => getComputedStyle(element);
        const elements = [card, ...document.querySelectorAll('input:not([type="hidden"]), button, .button-link')];
        return {
          page: css(document.body).backgroundColor, card: css(card).backgroundColor,
          action: css(action).backgroundColor, radius: css(card).borderRadius,
          mark: document.querySelector('.brand-mark').tagName.toLowerCase(),
          fits: document.documentElement.scrollWidth <= innerWidth && elements.every(element => {
            const box = element.getBoundingClientRect();
            return box.left >= 0 && box.right <= innerWidth && box.top >= 0 && box.bottom <= innerHeight;
          }),
          fields: [...document.querySelectorAll('input:not([type="hidden"])')].map(input => ({
            id: input.id, label: input.labels.length, autocomplete: input.autocomplete,
            size: parseFloat(css(input).fontSize)
          }))
        };
      })()`);
      assert.equal(styles.page, rgb(palettes[theme][0]), `${service} ${theme} page stylesheet applied`);
      assert.equal(styles.card, rgb(palettes[theme][1]), "service surface token applied");
      assert.equal(styles.action, rgb(palettes[theme][2]), "service primary action token applied");
      assert.equal(styles.radius, service === "cornerhead" ? "12px" : "14px", "service card shape");
      assert.equal(styles.mark, "svg", "original service SVG mark");
      assert(styles.fits, `${service} ${page} ${theme} ${viewport} must not overflow`);
      for (const field of styles.fields) {
        assert.equal(field.label, 1, "accessible field label");
        assert.equal(field.autocomplete, field.id === "username" ? "username" : "current-password", "native autofill semantics");
        assert(field.size >= 16, "mobile form text must not trigger input zoom");
      }
      if (page === "login") {
        const focus = await evaluate(`(() => {
          const input = document.getElementById('username'); input.focus();
          const css = getComputedStyle(input);
          const result = { outline: css.outlineWidth, shadow: css.boxShadow };
          input.blur(); return result;
        })()`);
        assert(service === "cornerhead" ? focus.shadow !== "none" : focus.outline === "2px", "service input focus indicator");
      }
      if (process.env.WEBUI_BROWSER_SCREENSHOTS) {
        const { data } = await command("Page.captureScreenshot", { format: "png" });
        await writeFile(join(process.env.WEBUI_BROWSER_SCREENSHOTS, `${service}-${page}-${theme}-${viewport}.png`), Buffer.from(data, "base64"), { mode: 0o600 });
      }
    }
  }
}
try {
  const args = ["--headless", "--no-sandbox", "--disable-gpu", "--no-first-run",
    "--remote-debugging-pipe", `--user-data-dir=${profile}`, "about:blank"];
  if (process.env.WEBUI_BROWSER_SPKI) args.push(`--ignore-certificate-errors-spki-list=${process.env.WEBUI_BROWSER_SPKI}`);
  if (process.env.WEBUI_BROWSER_PROXY) args.push(`--proxy-server=${process.env.WEBUI_BROWSER_PROXY}`);
  // Chromium reads fd 3 and writes fd 4: inherited private pipes, never a DevTools TCP listener.
  browser = spawn(process.env.CHROMIUM, args, { stdio: ["ignore", "ignore", "ignore", "pipe", "pipe"] });
  const pipeFailed = () => {
    for (const respond of pending.values()) respond({ error: true });
    pending.clear();
  };
  browser.on("error", pipeFailed);
  browser.on("exit", pipeFailed);
  browser.stdio[3].on("error", pipeFailed);
  browser.stdio[4].on("error", pipeFailed);
  browser.stdio[4].setEncoding("utf8");
  let received = "";
  browser.stdio[4].on("data", chunk => {
    received += chunk;
    let end;
    while ((end = received.indexOf("\0")) !== -1) {
      const frame = received.slice(0, end);
      received = received.slice(end + 1);
      let msg;
      try { msg = JSON.parse(frame); }
      catch { pipeFailed(); browser.kill("SIGTERM"); return; }
      if (msg.id) { pending.get(msg.id)?.(msg); pending.delete(msg.id); }
      else if (msg.sessionId === sessionId) for (const listener of listeners) listener(msg);
    }
  });
  const { targetId } = await command("Target.createTarget", { url: "about:blank" });
  ({ sessionId } = await command("Target.attachToTarget", { targetId, flatten: true }));
  await command("Page.enable");
  await command("Log.enable");
  const cspViolations = [];
  listeners.add(({ method, params }) => {
    if (method === "Log.entryAdded" && /content security policy|content-security-policy/i.test(params.entry.text)) {
      cspViolations.push(params.entry.text);
    }
  });
  await command("Network.enable");
  await command("Network.setCacheDisabled", { cacheDisabled: true });
  for (const { service, origin } of targets) {
    await command("Network.clearBrowserCookies");
    const posts = [], responses = [], origins = new Map();
    const observe = ({ method, params }) => {
      if (method === "Network.requestWillBeSent" && params.type === "Document") {
        if (params.request.method === "POST") posts.push({ id: params.requestId, url: params.request.url });
        if (params.redirectResponse) responses.push(params.redirectResponse);
      }
      if (method === "Network.requestWillBeSentExtraInfo") {
        const entry = Object.entries(params.headers).find(([name]) => name.toLowerCase() === "origin");
        if (entry) origins.set(params.requestId, entry[1]);
      }
      if (method === "Network.responseReceived" && params.type === "Document") responses.push(params.response);
    };
    listeners.add(observe);
    const navigate = path => loaded(() => command("Page.navigate", { url: origin + path }));
    const submit = async (path, credential, expected) => {
      assert(await evaluate(`Boolean(document.querySelector('form[action="${path}"]'))`), `native ${path} form must be present (check rate limits)`);
      posts.length = responses.length = 0;
      await loaded(() => evaluate(`(() => {
        const form = document.querySelector('form');
        ${credential ? `form.elements.username.value = ${JSON.stringify(credential.username)};
        form.elements.password.value = ${JSON.stringify(credential.password)};` : ""}
        form.requestSubmit();
      })()`));
      assert.equal(posts.length, 1, "one native document POST required");
      assert.equal(posts[0].url, origin + path, "native form destination");
      assert.equal(origins.get(posts[0].id), origin, "browser must generate exact Origin including port");
      assert(responses.some(response => response.url === origin + path && response.status === expected),
        `native ${path} expected ${expected}`);
    };
    await navigate("/_auth/login");
    const login = responses.at(-1);
    assert.equal(login.status, 200, "GET login");
    const policy = Object.entries(login.headers).find(([name]) => name.toLowerCase() === "referrer-policy")?.[1];
    assert(policy && policy.split(/[\n,]/).every(value => value.trim() === "same-origin"), "both response policies must be same-origin");
    const cookies = (await command("Network.getCookies", { urls: [origin] })).cookies;
    assert(cookies.some(cookie => cookie.name === `__Host-${service}_csrf` && cookie.secure && cookie.httpOnly), "real CSRF cookie required");
    await presentation(service, "login");
    await submit("/_auth/login", { username: "browser-regression-dummy", password: "not-valid" }, 401);
    assert(await evaluate("document.body.textContent.includes('Invalid username or password')"), "dummy login reaches credential validation");
    await presentation(service, "error");
    if (credentials[service]) {
      await navigate("/_auth/login");
      assert.equal(responses.at(-1).status, 200, "fresh login GET (rate limits apply)");
      await submit("/_auth/login", credentials[service], 303);
      assert.equal(responses.at(-1).url, origin + "/", "login redirects to protected site");
      assert.equal(responses.at(-1).status, 200, "authenticated site");
      const old = (await command("Network.getCookies", { urls: [origin] })).cookies.find(cookie => cookie.name === `__Host-${service}_session`);
      assert(old, "session cookie required");
      await navigate("/_auth/logout");
      assert.equal(responses.at(-1).status, 200, "logout GET confirmation");
      await presentation(service, "logout");
      assert((await command("Network.getCookies", { urls: [origin] })).cookies.some(cookie => cookie.name === old.name && cookie.value === old.value), "GET must retain session");
      await submit("/_auth/logout", null, 303);
      assert(!(await command("Network.getCookies", { urls: [origin] })).cookies.some(cookie => cookie.name === old.name), "logout clears session");
      assert((await command("Network.setCookie", { name: old.name, value: old.value, url: origin + "/", secure: true, httpOnly: true, sameSite: "Lax", path: "/" })).success, "replay cookie must be installed");
      responses.length = 0;
      await navigate("/");
      assert(responses.some(response => response.url === origin + "/" && response.status === 303), "old session rejected server-side");
      assert.equal(responses.at(-1).url, origin + "/_auth/login", "revoked session returns to login");
    }
    assert.equal(cspViolations.length, 0, "authentication pages must have no CSP violations");
    listeners.delete(observe);
    console.log(`${service}: native dummy POST 401; exact browser Origin ${origin}${credentials[service] ? "; native login 200, logout confirmation and revocation passed" : " (authenticated flow not requested)"}`);
  }
} catch (error) {
  // Only assertion messages written here are printed; never CDP payloads, input or cookie values.
  console.error(`Native form regression failed: ${error.message}`);
  process.exitCode = 1;
} finally {
  clearTimeout(deadline);
  browser?.stdio[3]?.end();
  browser?.stdio[4]?.destroy();
  if (browser && browser.exitCode === null) {
    browser.kill("SIGTERM");
    await Promise.race([new Promise(resolve => browser.once("exit", resolve)), delay(2000)]);
    if (browser.exitCode === null) browser.kill("SIGKILL");
  }
  await rm(profile, { recursive: true, force: true });
}
