// Offline unit tests for the UI's data layer: `pnpm test` (node:test, native TypeScript, HTTP mocked).
import { afterEach, describe, it } from "node:test";
import assert from "node:assert/strict";
import { fmtK, fmtMoney, fmtNs, fmtPct, prettyId, sparkPath } from "../src/lib/fmt.ts";
import { initSim, seeded, simCover, simPnl, stepSim } from "../src/lib/sim.ts";
import { blockUi, parseLibrary, shortlist } from "../src/lib/library.ts";
import { demoSteps, fitSteps, type PipeContext } from "../src/lib/pipeline.ts";
import { INSTRUMENTS, QUESTIONS, demoImpacts, questionFromMarket } from "../src/lib/demo.ts";
import { getAccount, getLibrary, getOrders, getPositions, postFit, type FitOut } from "../src/lib/api.ts";

describe("fmt", () => {
  it("formats like the prototype", () => {
    assert.equal(fmtPct(-3.2), "−3.2%");
    assert.equal(fmtPct(0.6), "+0.6%");
    assert.equal(fmtPct(0), "0.0%");
    assert.equal(fmtK(48200), "48.2k");
    assert.equal(fmtK(2400000), "2.4M");
    assert.equal(fmtMoney(1240, true), "+$1,240");
    assert.equal(fmtMoney(-12.4), "−$12");
    assert.equal(fmtNs(38_000_000), "38.0 ms");
    assert.equal(fmtNs(950), "950 ns");
    assert.equal(fmtNs(null), "n/a");
    assert.equal(prettyId("equity_delta_bridge"), "Equity Delta Bridge");
  });
  it("draws a sparkline inside the box", () => {
    const d = sparkPath([1, 2, 3], 300, 56);
    assert.match(d, /^M0\.0 52\.0 L150\.0 28\.0 L300\.0 4\.0$/);
    assert.equal(sparkPath([1], 300, 56), "");
  });
});

describe("demo simulator", () => {
  const seed = () => initSim({ ticker: "ABNB", px: 128.4, held: 1200, yesCents: 23, volN: 48200, movePct: -3.2 }, seeded(7), 1_700_000_000_000);

  it("seeds 60 points of history and the two prototype trades", () => {
    const s = seed();
    assert.equal(s.hist.length, 60);
    assert.equal(s.phist.length, 60);
    assert.equal(s.trades.length, 2);
    assert.equal(s.hedge, Math.round(1200 * 0.38));
    assert.equal(s.trades[0].side, "SELL");
    assert.match(s.trades[0].reason, /^Polymarket YES \+1\.8¢ on 62\.7k volume; Kalshi 25¢ confirming\. Delta-Bridge expects ABNB drift /);
  });

  it("is deterministic for a seed and keeps prices and probabilities bounded", () => {
    let a = seed(), b = seed();
    const ra = seeded(11), rb = seeded(11);
    for (let i = 0; i < 400; i++) { a = stepSim(a, ra, 1e12 + i); b = stepSim(b, rb, 1e12 + i); }
    assert.deepEqual(a, b);
    assert.ok(a.p >= 0.03 && a.p <= 0.92);
    assert.ok(a.vol >= 0.18 && a.vol <= 0.62);
    assert.ok(a.hedge >= 0);
    assert.ok(a.trades.length <= 8);
    assert.ok(a.tradeCount > 7, "hedges fire over 400 ticks");
    assert.ok(simCover(a) >= 0 && simCover(a) <= 100);
    assert.ok(Number.isFinite(simPnl(a)));
  });

  it("adds to the short hedge when the adverse probability jumps", () => {
    const s = { ...seed(), lastTradeTick: -9 };
    const rng = (() => { const xs = [0.01, 0.9, 0.99, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5]; let i = 0; return () => xs[i++ % xs.length]; })();
    const n = stepSim(s, rng, 1e12);
    assert.ok(n.p > s.pAtHedge + 0.011);
    assert.equal(n.trades[0].side, "SELL");
    assert.ok(n.hedge > s.hedge);
    assert.equal(n.tradeCount, s.tradeCount + 1);
  });
});

describe("library manifest parsing", () => {
  const manifest = {
    total_presets: 1290,
    families: [
      { id: "equity_delta_bridge", division: "hedge", event_classes: ["all"], instruments: ["equity"], blocks: ["DeltaDp", "Sigma", "DeltaBridge", "FeeGate", "PositionCap"], params: [{ name: "c", min: 0.1, max: 1, grid: [0.25, 0.5, 0.75] }, { name: "k", grid: [1, 2] }], preset_count: 6, latency: { p50_ns: 180, p99_ns: 900 } },
      { id: "fig_stress", division: "hedge", event_classes: ["fig"], blocks: [{ name: "EwmaVol", kind: "signal" }, { name: "TaxLotSelector", kind: "tax" }, { name: "VenueRouter", kind: "routing" }], params: { c: [0.5, 1], band: { grid: [5, 10, 20] } } },
    ],
  };
  it("maps block kinds to the UI families", () => {
    assert.equal(blockUi("DeltaDp"), "Reader");
    assert.equal(blockUi("Sigma"), "Gate");
    assert.equal(blockUi("DeltaBridge"), "Impact");
    assert.equal(blockUi("FeeGate"), "Execution");
    assert.equal(blockUi({ name: "X", kind: "tax" }), "Tax");
    assert.equal(blockUi({ name: "Y", kind: "routing" }), "Routing");
    assert.equal(blockUi("Unknown"), null);
  });
  it("parses rows, preset counts and the reported total", () => {
    const lib = parseLibrary(manifest)!;
    assert.equal(lib.total, 1290);
    assert.equal(lib.rows.length, 2);
    assert.equal(lib.rows[0].code, "PB-0001");
    assert.equal(lib.rows[0].presets, 6);
    assert.deepEqual(lib.rows[0].uiFamilies, ["Gate", "Reader", "Impact", "Execution"]);
    assert.equal(lib.rows[0].p50ns, 180);
    assert.equal(lib.rows[1].presets, 6, "derived from the grid when preset_count is missing");
    assert.deepEqual(lib.rows[1].params.map((p) => p.name), ["c", "band"]);
    assert.deepEqual(lib.rows[1].uiFamilies, ["Reader", "Tax", "Routing"]);
    assert.deepEqual(shortlist(lib, "fig").map((r) => r.id), ["equity_delta_bridge", "fig_stress"]);
  });
  it("sums presets when no total is reported, accepts a bare array, rejects empties", () => {
    const lib = parseLibrary(manifest.families)!;
    assert.equal(lib.total, 12);
    assert.equal(parseLibrary({ families: [] }), null);
    assert.equal(parseLibrary(null), null);
  });
});

describe("pipeline steps", () => {
  const ctx: PipeContext = { question: "Will the Fed cut rates at the December meeting?", venues: ["Kalshi"], yes: 62, vol: "2.4M", ticker: "JPM", held: 400, move: -0.9, rev: -0.6, brand: 0, why: "NII compresses." };
  const fit: FitOut = { event_class: "macro_fed", division: "hedge", family: "macro_fed_hedge", preset_index: 14, params: { c: 0.5, k: 2 }, score: 0.412, alternatives: [{ family: "equity_delta_bridge", score: 0.3 }], rationale: "Fed odds lead bank stocks.", llm: "rules", ticks_source: "live_history", n_ticks: 1440 };

  it("maps the fit response to classify, shortlist, history, tune, explain, ready", () => {
    const steps = fitSteps(fit, ctx);
    assert.deepEqual(steps.map((s) => s.key), ["classify", "shortlist", "history", "tune", "explain", "ready"]);
    assert.match(steps[0].text, /Macro Fed \(keyword rules\)\. Division: hedge\./);
    assert.match(steps[1].text, /2 families cover Macro Fed: Macro Fed Hedge, Equity Delta Bridge\./);
    assert.match(steps[2].text, /^1,440 ticks of real Kalshi price history/);
    assert.match(steps[3].text, /Macro Fed Hedge preset #14 · hedge variance reduction 41\.2% · c=0\.5, k=2\. Runners-up: Equity Delta Bridge 30\.0%\./);
    assert.equal(steps[4].text, "Fed odds lead bank stocks.");
  });
  it("labels replay and missing history honestly", () => {
    assert.match(fitSteps({ ...fit, ticks_source: "replay", n_ticks: 50 }, ctx)[2].text, /recorded replay file \(not live history\)/);
    assert.match(fitSteps({ ...fit, ticks_source: "none", n_ticks: 0 }, ctx)[2].text, /No usable price history/);
    assert.match(fitSteps({ ...fit, llm: "gemini" }, ctx)[0].text, /\(Gemini\)/);
  });
  it("keeps the prototype's scripted steps as the demo fallback", () => {
    const steps = demoSteps(ctx);
    assert.equal(steps.length, 6);
    assert.equal(steps[0].name, "Parsing question");
    assert.match(steps[2].text, /expected move on YES −0\.9%/);
  });
});

describe("demo data adapters", () => {
  it("turns a search hit into a wizard question", () => {
    const q = questionFromMarket({ source: "polymarket", id: "m1", question: "Will Congress pass X?", yes_price: 0.234, volume_24h: 48200, end_date: null, url: null, token_id: "t" });
    assert.equal(q.id, "polymarket:m1");
    assert.equal(q.ev, "congress pass X");
    assert.equal(q.yes, 23);
    assert.equal(q.vol, "48.2k");
    assert.deepEqual(q.venues, ["Polymarket"]);
  });
  it("has impacts for every sample question and four instruments", () => {
    for (const q of QUESTIONS) assert.ok(demoImpacts(q).length > 0);
    const inst = INSTRUMENTS(128.4, "Taxable");
    assert.equal(inst.length, 4);
    assert.equal(inst.filter((i) => i.rec).length, 1);
    assert.equal(inst[1].short, "Put spread 119/110");
  });
});

describe("api client (mocked HTTP)", () => {
  const realFetch = globalThis.fetch;
  afterEach(() => { globalThis.fetch = realFetch; });
  const mock = (routes: Record<string, unknown>, calls: { url: string; init?: RequestInit }[] = []) => {
    globalThis.fetch = (async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      const path = new URL(url).pathname;
      if (!(path in routes)) return new Response(JSON.stringify({ detail: "Not Found" }), { status: 404 });
      return new Response(JSON.stringify(routes[path]), { status: 200, headers: { "Content-Type": "application/json" } });
    }) as typeof fetch;
    return calls;
  };

  it("posts the fit body and returns the response", async () => {
    const calls = mock({ "/pipeline/fit": { family: "x" } });
    const out = await postFit({ ticker: "JPM", question: "Q?", direction: "down_on_yes" });
    assert.deepEqual(out, { family: "x" });
    assert.equal(calls[0].init?.method, "POST");
    assert.deepEqual(JSON.parse(String(calls[0].init?.body)), { ticker: "JPM", question: "Q?", direction: "down_on_yes" });
  });
  it("accepts positions/orders as a bare list or wrapped", async () => {
    mock({ "/positions": { positions: [{ symbol: "ABNB", qty: -40 }] }, "/orders": [{ id: "1", symbol: "ABNB", side: "sell", qty: 40, status: "filled" }] });
    assert.equal((await getPositions())[0].qty, -40);
    assert.equal((await getOrders())[0].status, "filled");
  });
  it("surfaces a missing endpoint as an error the screens fall back on", async () => {
    mock({});
    await assert.rejects(getLibrary(), /Not Found/);
    await assert.rejects(getAccount(), (e: Error & { status?: number }) => e.status === 404);
  });
  it("reports an unreachable backend without throwing a raw TypeError", async () => {
    globalThis.fetch = (async () => { throw new TypeError("fetch failed"); }) as typeof fetch;
    await assert.rejects(getAccount(), /Cannot reach the backend/);
  });
});
