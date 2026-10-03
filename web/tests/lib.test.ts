// Offline unit tests for the UI's data layer: `pnpm test` (node:test, native TypeScript, HTTP mocked).
import { afterEach, describe, it } from "node:test";
import assert from "node:assert/strict";
import { fmtK, fmtMoney, fmtNs, fmtPct, prettyId, sparkPath } from "../src/lib/fmt.ts";
import { blockUi, parseLibrary, shortlist } from "../src/lib/library.ts";
import { fitSteps, noFitSteps, type PipeContext } from "../src/lib/pipeline.ts";
import { FEATURED_REPLAY, HEDGE_INSTRUMENTS, featuredFirst, isFeaturedReplay, questionFromMarket } from "../src/lib/markets.ts";
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
  // No score_basis: an older backend whose hedge score was the raw variance cut (score.test.ts pins the vs-static labels).
  const fit: FitOut = { event_class: "macro_fed", division: "hedge", family: "macro_fed_hedge", preset_index: 14, params: { c: 0.5, k: 2 }, score: 0.412, alternatives: [{ family: "equity_delta_bridge", score: 0.3 }], rationale: "Fed odds lead bank stocks.", llm: "rules", ticks_source: "live_history", n_ticks: 1440 };

  it("maps the fit response to classify, shortlist, history, tune, explain, ready", () => {
    const steps = fitSteps(fit, ctx);
    assert.deepEqual(steps.map((s) => s.key), ["classify", "shortlist", "history", "tune", "explain", "ready"]);
    assert.match(steps[0].text, /Macro Fed \(keyword rules\)\. Division: hedge\./);
    assert.match(steps[1].text, /2 families cover Macro Fed: Macro Fed Hedge, Equity Delta Bridge\./);
    assert.match(steps[2].text, /^1,440 ticks of real Kalshi price history/);
    assert.match(steps[3].text, /Macro Fed Hedge preset #14 · hedge variance reduction 41\.2% \(in-sample: scored on the history it replays, not a forecast\) · c=0\.5, k=2\. Runners-up: Equity Delta Bridge 30\.0%\./);
    assert.equal(steps[4].text, "Fed odds lead bank stocks.");
  });
  it("labels replay and missing history honestly", () => {
    assert.match(fitSteps({ ...fit, ticks_source: "replay", n_ticks: 50 }, ctx)[2].text, /recorded replay file \(not live history\)/);
    assert.match(fitSteps({ ...fit, ticks_source: "none", n_ticks: 0 }, ctx)[2].text, /No usable price history/);
    assert.match(fitSteps({ ...fit, llm: "gemini:gemini-2.5-flash" }, ctx)[0].text, /\(Gemini 2\.5 Flash\)/);
    assert.match(fitSteps(fit, ctx)[5].text, /^Fit \(rules \+ C\+\+ replay\) for JPM/);
    assert.match(fitSteps({ ...fit, llm: "gemini:gemini-2.5-flash" }, ctx)[5].text, /^AI fit for JPM/);
  });
  it("without a fit, shows the pick's real facts and the engine's default spec, never scripted numbers", () => {
    const steps = noFitSteps(ctx);
    assert.equal(steps.length, 6);
    assert.match(steps[2].text, /expected move on YES −0\.9%/);
    assert.match(steps[3].text, /no presets were scored/);
    assert.doesNotMatch(steps.map((x) => x.text).join(" "), /lots|comps|confidence 0\.71|NYC LL18|71%/);
    assert.match(noFitSteps({ ...ctx, noDirection: true })[5].text, /until you say which outcome hurts it/);
  });
});

describe("market adapters", () => {
  it("turns a search hit into a wizard question", () => {
    const q = questionFromMarket({ source: "polymarket", id: "m1", question: "Will Congress pass X?", yes_price: 0.234, volume_24h: 48200, end_date: null, url: null, token_id: "t" });
    assert.equal(q.id, "polymarket:m1");
    assert.equal(q.ev, "congress pass X");
    assert.equal(q.yes, 23);
    assert.equal(q.vol, "48.2k");
    assert.deepEqual(q.venues, ["Polymarket"]);
  });
  it("offers only the hedge the engine runs, priced from a quote or not at all", () => {
    assert.deepEqual(HEDGE_INSTRUMENTS(null).map((i) => i.id), ["shares"]);
    assert.equal(HEDGE_INSTRUMENTS(null)[0].cost, "quote unavailable");
    assert.equal(HEDGE_INSTRUMENTS(null)[0].rec, false);
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
  it("surfaces a missing endpoint as an error the screens show with a retry", async () => {
    mock({});
    await assert.rejects(getLibrary(), /Not Found/);
    await assert.rejects(getAccount(), (e: Error & { status?: number }) => e.status === 404);
  });
  it("reports an unreachable backend without throwing a raw TypeError", async () => {
    globalThis.fetch = (async () => { throw new TypeError("fetch failed"); }) as typeof fetch;
    await assert.rejects(getAccount(), /Cannot reach the backend/);
  });
});

describe("featured replay market", () => {
  it("is moved to the front of the held-market rows, the others keep their order", () => {
    const rows = [{ id: "polymarket:2589813" }, { id: "kalshi:X" }, { id: `polymarket:${FEATURED_REPLAY.id}` }, { id: "polymarket:1" }];
    assert.deepEqual(featuredFirst(rows).map((r) => r.id), [`polymarket:${FEATURED_REPLAY.id}`, "polymarket:2589813", "kalshi:X", "polymarket:1"]);
    assert.deepEqual(featuredFirst([{ id: "a" }, { id: "b" }]).map((r) => r.id), ["a", "b"]);
    assert.equal(isFeaturedReplay({ id: "kalshi:4620900" }), false);
    assert.equal(FEATURED_REPLAY.ticker, "TLT");
  });
});
