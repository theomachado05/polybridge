#!/usr/bin/env node
// Drives the real UI in headless Chrome over the DevTools protocol (no dependencies: Node's global WebSocket + fetch).
// Click path: Landing -> Build chat (search a market, pick the ticker, pick the hedge) -> Connect -> AI pipeline -> approve ->
// Bridge live (replay) -> Library -> Portfolio -> Profile, saving a screenshot of each of the 8 screens, and checking
// that what the UI shows is what the backend runs. On the Bridge screen it waits for the bridge's first broker fill (or
// the end of the replay) up to --fill-deadline-s, instead of sampling after a fixed delay.
//
//   node web/e2e/ui_walk.mjs --web http://localhost:3000 --api http://localhost:8000 --out web/e2e/screens \
//     [--query "fed rate hike 2026" --market "Another Fed rate hike in 2026" --ticker TLT --fill-deadline-s 90]
//
// Prints one JSON line per check (`{"check":..., "ok":..., "detail":...}`) and `{"shots":[...]}` at the end; exit 1 if
// any check fails. Chrome is always killed, even if the page's SSE connection never lets it exit by itself.
import { spawn } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const arg = (k, d) => { const i = process.argv.indexOf(`--${k}`); return i > 0 ? process.argv[i + 1] : d; };
const WEB = arg("web", "http://localhost:3000");
const API = arg("api", "http://localhost:8000");
const OUT = arg("out", "web/e2e/screens");
const CHROME = arg("chrome", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome");
const PORT = Number(arg("cdp-port", "9333"));
const QUERY = arg("query", "fed rate hike 2026");
const MARKET_TEXT = arg("market", "Another Fed rate hike in 2026");
const TICKER = arg("ticker", "TLT");
const MIN_WATCH_S = Number(arg("bridge-watch-s", "6")); // at least this long on the Bridge screen, so the chart has moved
const FILL_DEADLINE_S = Number(arg("fill-deadline-s", "90")); // then until the first broker fill or the replay ends

const results = [];
const shots = [];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const check = (name, ok, detail = "") => { results.push({ check: name, ok: !!ok, detail }); console.log(JSON.stringify({ check: name, ok: !!ok, detail })); return !!ok; };

mkdirSync(OUT, { recursive: true });
const profile = mkdtempSync(join(tmpdir(), "pb-ui-"));
const chrome = spawn(CHROME, ["--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars", `--user-data-dir=${profile}`,
  `--remote-debugging-port=${PORT}`, "--window-size=1440,1000", "about:blank"], { stdio: "ignore", detached: true });
const killChrome = () => { try { process.kill(-chrome.pid, "SIGKILL"); } catch {} try { rmSync(profile, { recursive: true, force: true }); } catch {} };
process.on("exit", killChrome);
const hardStop = setTimeout(() => { console.log(JSON.stringify({ check: "ui walk finished within its time limit", ok: false, detail: "hard stop" })); killChrome(); process.exit(1); }, 240_000 + FILL_DEADLINE_S * 1000);

async function connect() {
  for (let i = 0; i < 60; i++) {
    try {
      const t = await (await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, { method: "PUT" })).json();
      const ws = new WebSocket(t.webSocketDebuggerUrl);
      await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
      return ws;
    } catch { await sleep(300); }
  }
  throw new Error("Chrome DevTools did not come up");
}

const ws = await connect();
let nextId = 1;
const pending = new Map();
ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); } };
const send = (method, params = {}) => new Promise((res, rej) => {
  const id = nextId++;
  pending.set(id, (d) => (d.error ? rej(new Error(`${method}: ${d.error.message}`)) : res(d.result)));
  ws.send(JSON.stringify({ id, method, params }));
});
const ev = async (expression) => {
  const r = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description ?? "evaluate failed");
  return r.result.value;
};
const waitFor = async (expression, what, timeoutMs = 30_000) => {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) { try { if (await ev(expression)) return true; } catch {} await sleep(250); }
  check(`UI: ${what}`, false, "timed out");
  throw new Error(`timed out waiting for: ${what}`);
};
const shot = async (n, name) => {
  await sleep(700); // let transitions settle
  // Full page (the pipeline and bridge screens are taller than the window), capped so a runaway page stays small.
  const { contentSize } = await send("Page.getLayoutMetrics");
  const height = Math.min(Math.max(Math.ceil(contentSize.height), 1000), 2400);
  const { data } = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true, clip: { x: 0, y: 0, width: 1440, height, scale: 1 } });
  const file = join(OUT, `${String(n).padStart(2, "0")}-${name}.png`);
  writeFileSync(file, Buffer.from(data, "base64"));
  shots.push(file);
};
// Click the first element of `sel` whose text includes `text` (a real DOM click: React handlers and Next links fire).
const click = (sel, text) => ev(`(() => { const el = [...document.querySelectorAll(${JSON.stringify(sel)})].find(e => e.innerText && e.innerText.includes(${JSON.stringify(text)})); if (!el) return false; el.click(); return true; })()`);
const has = (sel, text) => `[...document.querySelectorAll(${JSON.stringify(sel)})].some(e => e.innerText && e.innerText.includes(${JSON.stringify(text)}))`;
const goto = async (path) => { await send("Page.navigate", { url: WEB + path }); await sleep(800); await waitFor("document.readyState !== 'loading' && document.body && document.body.innerText.length > 20", `${path} renders`, 60_000); };
const pretty = (id) => String(id).replace(/_/g, " ").toLowerCase();

let code = 0;
try {
  await send("Page.enable"); await send("Runtime.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });

  // `next dev` compiles each route on its first request; do it up front so the walk's clock is not the compiler's.
  for (const p of ["/", "/build", "/connect", "/build/fit", "/pipeline", "/bridge", "/tested", "/library", "/portfolio", "/profile"]) await fetch(WEB + p).catch(() => {});

  // 1. Landing
  await goto("/");
  check("UI: landing shows the library size", await ev("/1,\\d\\d\\d/.test(document.body.innerText)"), "");
  await shot(1, "landing");

  // 2. Build chat: client-side navigation (the store lives in memory), then search, pick the market, the stock, the hedge
  await click("a", "Build a bridge");
  await waitFor(`!!document.querySelector('input[aria-label=Composer]')`, "Build composer", 30_000);
  await ev(`document.querySelector('input[aria-label=Composer]').focus()`);
  await send("Input.insertText", { text: QUERY });
  await waitFor(has("button.pb-row", MARKET_TEXT), `search lists "${MARKET_TEXT}"`, 45_000);
  check("UI: live market search lists the target market", true, MARKET_TEXT);
  await click("button.pb-row", MARKET_TEXT);
  await waitFor(has("button.pb-row", TICKER), `mapping lists ${TICKER}`, 30_000);
  check("UI: /map lists the mapped tickers, labelled as an AI estimate", await ev(`document.body.innerText.toLowerCase().includes('estimate')`), "");
  await click("button.pb-row", TICKER);
  await waitFor(`document.querySelectorAll('button.pb-row').length > 0 && !!document.body.innerText.match(/hedge/i)`, "hedge menu", 30_000);
  await sleep(1500);
  await click("button.pb-row", "hort"); // the dynamic short-shares hedge (the one the engine runs)
  await waitFor(has("button", "Connect brokerage"), "Connect brokerage button", 30_000);
  // Liquidity preview + hedge-instrument comparison (real Massive data; best effort, the walk does not fail on it).
  try { await waitFor(`!!document.querySelector('[data-testid=hedge-compare]') && !/Pricing the four hedges/.test(document.querySelector('[data-testid=hedge-compare]').innerText)`, "hedge comparison answers", 30_000); } catch {}
  check("UI: build shows the liquidity preview and the hedge-instrument comparison", await ev(`!!document.querySelector('[data-testid=risk-preview]') && !!document.querySelector('[data-testid=hedge-compare]')`), "");
  await shot(2, "build");

  // 3. Connect
  await click("button", "Connect brokerage");
  await waitFor(has("button", "pipeline"), "Connect screen", 30_000);  // "Run the AI pipeline" (Gemini answered) or "Run the fit pipeline"
  check("UI: connect names the account orders route to", await ev(`/Simulated account|Webull paper/.test(document.body.innerText)`), "");
  await shot(3, "connect");

  // 4. Pipeline: wait for the fit, read what it says it picked, then approve
  await click("button", "pipeline");
  await waitFor(has("h2", "Approve the"), "pipeline reaches the approval gate", 90_000);
  const pipeText = await ev("document.body.innerText");
  const fitTag = /Rules \+ C\+\+ replay|AI · Gemini[^\n]*/.exec(pipeText)?.[0];
  check("UI: pipeline shows a fit, labelled \"Rules + C++ replay\" or \"AI · Gemini <model>\"", !!fitTag, fitTag ?? "no label");
  const fam = /AI fit for \w+: ([A-Za-z0-9 ]+?)(?: preset|\.|\n)/.exec(pipeText)?.[1]?.trim();
  check("UI: pipeline names the chosen family", !!fam, fam ?? "");
  // The approval step reads the pending proposal first: evidence gate + liquidity & capacity card.
  await waitFor(`!!document.querySelector('[data-testid=evidence-gate]') && !/checking evidence/i.test(document.querySelector('[data-testid=evidence-gate]').innerText)`, "evidence gate answers", 45_000);
  const unvalidated = await ev(`!!document.querySelector('[data-testid=evidence-ack]')`);
  // The generic AI fit is unvalidated (registry generic_ai_fit), so the box always carries an unvalidated verdict with the
  // acknowledgement (or an earlier one recorded), whatever the market's own gap evidence. Anything else fails.
  const gateText = await ev(`(document.querySelector('[data-testid=evidence-gate]') || {}).innerText || ""`);
  const gateOk = /unvalidated/i.test(gateText)
    && (unvalidated || await ev(`!!document.querySelector('[data-testid=evidence-acknowledged]')`));
  check("UI: approval shows the evidence gate", gateOk, /unvalidated/i.test(gateText) ? (unvalidated ? "unvalidated: acknowledgement required" : "unvalidated: acknowledged earlier") : `no verdict: ${gateText.slice(0, 80)}`);
  check("UI: approval shows the liquidity & capacity card", await ev(`!!document.querySelector('[data-testid=capacity-card]') || /Checking liquidity/.test(document.body.innerText)`), "");
  await shot(4, "pipeline");

  // 5. Approve -> bridge page (/bridge/<id>). On an unvalidated market the button stays disabled until the box is ticked.
  if (unvalidated) {
    check("UI: approve is disabled before the acknowledgement", await ev(`[...document.querySelectorAll('button')].some(b => b.disabled && /Acknowledge the unvalidated fit/.test(b.innerText))`), "");
    await ev(`document.querySelector('[data-testid=evidence-ack]').click()`);
    await waitFor(has("button", "Approve"), "approve enables after the acknowledgement", 10_000);
  }
  await click("button", "Approve"); // "Approve the unvalidated fit" or "Approve without the fee gate"
  await waitFor(`location.pathname.startsWith('/bridge') && /Bridge [0-9a-f]{8,}/.test(document.body.innerText)`, "opens the Bridge screen on a backend bridge", 60_000);
  const bridgeId = await ev("(/Bridge ([0-9a-f]{8,})/.exec(document.body.innerText) || [])[1]");
  check("UI: approve opened a backend bridge", /^[0-9a-f]{8,}$/.test(bridgeId), bridgeId);
  // Let the replay run until the broker has filled an order (or the replay is over), with a deadline: a fixed early
  // sample can land before the algo's first order on a quiet stretch of history.
  const t0 = Date.now();
  let sum = null;
  while (Date.now() - t0 < FILL_DEADLINE_S * 1000) {
    try { sum = await (await fetch(`${API}/bridges/${bridgeId}`)).json(); } catch {}
    const done = sum && (sum.broker_filled > 0 || (sum.status && sum.status !== "running"));
    if (done && Date.now() - t0 >= MIN_WATCH_S * 1000) break;
    await sleep(500);
  }
  const waited = ((Date.now() - t0) / 1000).toFixed(1);
  check("UI bridge reached a broker fill or the replay's end within the deadline",
    !!sum && (sum.broker_filled > 0 || sum.status !== "running"),
    `after ${waited}s (deadline ${FILL_DEADLINE_S}s): status=${sum?.status} ticks=${sum?.ticks} broker_filled=${sum?.broker_filled}`);
  await waitFor(`/Ticks received/.test(document.body.innerText)`, "bridge screen renders ticks", 30_000);
  await sleep(1000); // let the stream's latest fill reach the screen
  await shot(5, "bridge");
  sum = await (await fetch(`${API}/bridges/${bridgeId}`)).json();
  check("UI bridge runs hedgecore.Algo (engine=algo)", sum.engine === "algo", `engine=${sum.engine}`);
  check("UI bridge runs the fit the pipeline screen showed", fam && pretty(sum.algo?.family) === pretty(fam), `UI said "${fam}", backend runs ${sum.algo?.family} #${sum.algo?.preset_index} (source ${sum.algo?.source})`);
  check("UI bridge is a replay, labelled as one", sum.source === "replay" && (await ev(`/REPLAY/i.test(document.body.innerText)`)), `source=${sum.source}`);
  check("UI bridge received ticks and the broker took orders", sum.ticks > 0 && sum.broker_filled > 0, `ticks=${sum.ticks} orders=${sum.orders} broker_filled=${sum.broker_filled} scope=${sum.account_scope}`);

  // 6-8. Library, Portfolio, Profile through the nav (client-side, so the bridge keeps running in the store)
  await click("a", "Library");
  await waitFor(`/families|presets|Library/i.test(document.body.innerText) && document.body.innerText.length > 300`, "library renders", 30_000);
  await sleep(1500);
  check("UI: library shows the compiled catalog", await ev(`/1,\\d\\d\\d/.test(document.body.innerText)`), "");
  await shot(7, "library");
  await click("a", "Portfolio");
  await waitFor(`document.body.innerText.includes(${JSON.stringify(TICKER)})`, `portfolio lists ${TICKER}`, 45_000);
  try { await waitFor(`!!document.querySelector('[data-testid=capital-panel]') && !/Reading the account and the budget/.test(document.querySelector('[data-testid=capital-panel]').innerText)`, "capital panel answers", 30_000); } catch {}
  check("UI: portfolio shows the broker account and capital usage apart from demo holdings", await ev(`!!document.querySelector('[data-testid=broker-account]') && !!document.querySelector('[data-testid=capital-panel]')`), "");
  await sleep(1500);
  await shot(6, "portfolio");
  await ev(`(() => { const el = document.querySelector('a[href="/profile"]'); if (!el) return false; el.click(); return true; })()`);
  await waitFor(`location.pathname === '/profile'`, "profile route", 30_000);
  await shot(8, "profile");
} catch (e) {
  code = 1;
  let where = "";
  try { where = `${await ev("location.pathname")}: ${(await ev("document.body.innerText")).replace(/\s+/g, " ").slice(-400)}`; await shot(99, "failure"); } catch {}
  console.log(JSON.stringify({ check: "ui walk completed", ok: false, detail: `${e.message ?? e} | page at ${where}` }));
} finally {
  clearTimeout(hardStop);
  console.log(JSON.stringify({ shots }));
  try { ws.close(); } catch {}
  killChrome();
}
process.exit(code || (results.some((r) => !r.ok) ? 1 : 0));
