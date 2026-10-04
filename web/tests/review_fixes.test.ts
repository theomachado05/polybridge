// Pins the review fixes: exact-terms proposal reuse, no hedge fit without a direction, honest labels.
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  REPLAY_SANDBOX_SENTENCE, fillScopeLabel, fitDirection, liveVenue, priceSubtitle, startRealBridge, type BridgeApi,
} from "../src/lib/realBridge.ts";
import { isOpenMarket, questionFromMarket, topImpact, type EquityPick } from "../src/lib/markets.ts";
import type { Proposal } from "../src/lib/api.ts";
import { parseLibrary, shortlist } from "../src/lib/library.ts";
import { IN_SAMPLE_NOTE, fitSteps, hedgeScoreText, noFitSteps, type PipeContext } from "../src/lib/pipeline.ts";
import { engineBridgeFor } from "../src/lib/portfolioView.ts";

const q = questionFromMarket({ source: "polymarket", id: "m1", question: "Will X happen?", yes_price: 0.4, volume_24h: 1000, end_date: null, url: null, token_id: "tok" });
const eq: EquityPick = { t: "ABNB", move: -3, rev: null, brand: null, why: "", direction: "down_on_yes", name: "Airbnb", px: 130, held: 0 };
const prop = (over: Partial<Proposal>): Proposal => ({
  id: "p1", ticker: "ABNB", family: "hedge", strategy: "protective_put", shares_held: 500, target_coverage: 0.5, status: "approved",
  basis: "market_event", market: { source: "polymarket", id: "m1", token_id: "tok" }, direction: "down_on_yes",
  created_at: "2026-10-03T00:00:00Z", decided_at: null, ...over,
});
function api(existing: Proposal[]) {
  const calls: { create?: Record<string, unknown> } = {};
  const a: BridgeApi = {
    listProposals: async () => existing,
    createProposal: async (body) => { calls.create = body as Record<string, unknown>; return prop({ id: "new", status: "proposed" }); },
    approveProposal: async (id: string) => prop({ id, status: "approved" }),
    getEquity: async () => { throw new Error("no quote"); },
    startBridge: async (body) => ({ bridge_id: `b-${body.proposal_id}` }),
  };
  return { api: a, calls };
}

describe("proposal reuse matches the exact approved terms", () => {
  it("without a fit, an approval at another coverage is not reused after Max hedge is lowered", async () => {
    const old = prop({ id: "old", target_coverage: 0.5 });
    const { api: a, calls } = api([old]);
    const r = await startRealBridge(q, eq, "20%", a);
    assert.equal(r.bridgeId, "b-new");
    assert.equal(calls.create?.target_coverage, 0.2);
    // same terms are still reused
    assert.equal((await startRealBridge(q, eq, "100%", api([old]).api)).bridgeId, "b-old");
  });
  it("an approval for another position size is not reused (with or without a fit)", async () => {
    const old = prop({ id: "old", shares_held: 500 });
    const held = { ...eq, held: 100 };
    const { api: a, calls } = api([old]);
    assert.equal((await startRealBridge(q, held, "100%", a)).bridgeId, "b-new");
    assert.equal(calls.create?.shares_held, 100);
    const fit = { family: "macro_fed_hedge", preset_index: 5 };
    const withFit = prop({ id: "fit", shares_held: 500, target_coverage: 1, algo: fit });
    assert.equal((await startRealBridge(q, held, "100%", api([withFit]).api, fit)).bridgeId, "b-new");
    assert.equal((await startRealBridge(q, eq, "100%", api([withFit]).api, fit)).bridgeId, "b-fit");
  });
});

describe("hedge fit direction", () => {
  it("is unknown for a ticker outside the mapping, never guessed from the sign of a move", () => {
    assert.equal(fitDirection(q, { direction: undefined }), null);
    assert.equal(fitDirection(q, { direction: "up_on_yes" }), "up_on_yes");
    assert.equal(fitDirection(q, { direction: undefined, move: -1.2 } as EquityPick), null);
  });
  it("the pipeline says no hedge was fitted instead of claiming the endpoint failed", () => {
    const c: PipeContext = { question: "Will X?", venues: ["Polymarket"], yes: 40, vol: "1k", ticker: "AAPL", held: 500, move: 0, rev: null, brand: null, why: "", noDirection: true };
    const steps = noFitSteps(c);
    assert.match(steps.find((s) => s.key === "tune")!.text, /No hedge fit: AAPL is not in this market's mapping/);
    assert.match(steps.find((s) => s.key === "ready")!.text, /cannot orient a hedge/);
  });
});

describe("honest labels", () => {
  it("the fit score is labelled in-sample on the card and in the tune step (legacy raw score, no score_basis)", () => {
    assert.equal(hedgeScoreText(0.85, "hedge"), "85.0% var. reduction (in-sample replay)");
    assert.equal(hedgeScoreText(0.1234, "opportunity"), "0.123 in-sample");
    assert.equal(hedgeScoreText(null, "hedge"), "n/a");
    assert.match(IN_SAMPLE_NOTE, /in-sample/);
    const fit = { event_class: "fig", division: "hedge", family: "fig_stress", preset_index: 54, params: {}, score: 0.85, alternatives: [], rationale: "", llm: "rules", ticks_source: "live_history", n_ticks: 721 };
    const c: PipeContext = { question: "Will X?", venues: ["Polymarket"], yes: 40, vol: "1k", ticker: "IWM", held: 400, move: -3, rev: null, brand: null, why: "" };
    assert.match(fitSteps(fit, c).find((s) => s.key === "tune")!.text, /85\.0% \(in-sample: scored on the history it replays, not a forecast\)/);
  });
  it("a replay-sandbox bridge is never labelled as the account", () => {
    const acct = { name: "Simulated account", tone: "sim" as const };
    const sb = fillScopeLabel("replay_sandbox", acct);
    assert.equal(sb.sandbox, true);
    assert.match(sb.name, /not your account/);
    assert.equal(sb.filledVerb, "Sandbox filled");
    assert.deepEqual(fillScopeLabel("account", acct).name, "Simulated account");
    assert.equal(fillScopeLabel(undefined, { name: "Webull paper", tone: "paper" }).filledVerb, "Broker filled");
    assert.match(REPLAY_SANDBOX_SENTENCE, /isolated replay sandbox, not this account/);
  });
  it("names the venue a live bridge streams and the replay file it plays", () => {
    assert.equal(liveVenue("kalshi"), "Kalshi");
    assert.equal(liveVenue("polymarket"), "Polymarket");
    assert.equal(priceSubtitle("live", "kalshi").sub, "YES Kalshi midpoint");
    assert.match(priceSubtitle("live", "polymarket").sub, /Polymarket midpoint · Kalshi not streamed/);
    assert.match(priceSubtitle("replay", "polymarket", { file: "fed.jsonl" }, "m1").sub, /replay fed\.jsonl/);
    assert.equal(priceSubtitle("replay", "polymarket", { file: "fed.jsonl", market_id: "2589813" }, "2589812").mismatch, true);
    assert.equal(priceSubtitle("replay", "polymarket", { file: "fed.jsonl", market_id: "2589812" }, "2589812").mismatch, false);
    assert.equal(priceSubtitle("replay", "polymarket", null, "2589812").mismatch, false);
  });
});

describe("Build step copy and rows", () => {
  it("the AI names the largest move, not the first mapping row (a held ticker wins ties)", () => {
    const impacts = [{ t: "SPY", move: -2 }, { t: "XHB", move: -3 }, { t: "IWM", move: -3 }];
    assert.equal(topImpact(impacts)!.t, "XHB");
    assert.equal(topImpact(impacts, (t) => t === "IWM")!.t, "IWM");
    assert.equal(topImpact([]), undefined);
  });
  it("leaves out ended and effectively settled markets", () => {
    const now = Date.parse("2026-10-03T12:00:00Z");
    assert.equal(isOpenMarket({ end_date: "2026-10-02T20:00:00Z", yes_price: 0.5 }, now), false);
    assert.equal(isOpenMarket({ end_date: "2026-10-29T03:59:00Z", yes_price: 1 }, now), false);
    assert.equal(isOpenMarket({ end_date: "2026-10-29T03:59:00Z", yes_price: 0 }, now), false);
    assert.equal(isOpenMarket({ end_date: "2026-10-29T03:59:00Z", yes_price: 0.175 }, now), true);
    assert.equal(isOpenMarket({ end_date: null, yes_price: null }, now), true);
  });
});

describe("pipeline shortlist counts the fitted division only", () => {
  it("drops opportunity families from a hedge shortlist and keeps multi-division families", () => {
    const lib = parseLibrary({ families: [
      { id: "macro_fed_hedge", division: "hedge", event_classes: ["macro_fed"] },
      { id: "no_bid_seller", division: "opportunity", event_classes: ["all"] },
      { id: "poly_kalshi_spread", divisions: ["hedge", "opportunity"], event_classes: ["macro_fed"] },
    ] })!;
    assert.deepEqual(shortlist(lib, "macro_fed").map((r) => r.id), ["macro_fed_hedge", "no_bid_seller", "poly_kalshi_spread"]);
    assert.deepEqual(shortlist(lib, "macro_fed", "hedge").map((r) => r.id), ["macro_fed_hedge", "poly_kalshi_spread"]);
    assert.deepEqual(shortlist(lib, "macro_fed", "opportunity").map((r) => r.id), ["no_bid_seller", "poly_kalshi_spread"]);
  });
});

describe("Portfolio hedge status", () => {
  const none = { ticker: "IWM", hedge: { status: "none", bridge_id: null } };
  it("trusts the backend's bridging status first", () => {
    assert.equal(engineBridgeFor({ ticker: "IWM", hedge: { status: "bridging", bridge_id: "b1" } }, []), "b1");
  });
  it("shows a live hedge bridge this session opened while GET /portfolio is stale", () => {
    const live = { kind: "live", bridgeId: "23a6", q: { real: {} }, eq: { t: "IWM" } };
    assert.equal(engineBridgeFor(none, [live]), "23a6");
    assert.equal(engineBridgeFor(none, [{ ...live, mode: "opportunity" }]), null, "an options bridge is not a hedge");
    assert.equal(engineBridgeFor(none, [{ ...live, eq: { t: "SPY" } }]), null);
  });
});
