// Offline tests for the Opportunity (options) path: which fits are offered, proposal → approval → bridge with caps,
// the stream reducer's options fields, and the honest fill text.
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { DEFAULT_OPP_CAPS, opportunityFit, startOpportunityBridge, type BridgeApi } from "../src/lib/realBridge.ts";
import { questionFromMarket } from "../src/lib/demo.ts";
import type { Proposal, ProposalBody } from "../src/lib/api.ts";
import { init, reduce } from "../src/lib/bridgeStream.ts";
import { OPP_REPLAY_NOTE, gapPts, legLine, libraryIdea, optionFamilyIdea, optionFillText } from "../src/lib/opportunity.ts";

const q = questionFromMarket({ source: "polymarket", id: "nvda-150", question: "Will NVDA close above $150 on Dec 18, 2026?", yes_price: 0.55, volume_24h: 1000, end_date: "2026-12-18", url: null, token_id: "tok" });
const fit = { family: "binary_vs_spread_arb", preset_index: 4 };

const prop = (over: Partial<Proposal>): Proposal => ({
  id: "p1", ticker: "NVDA", family: "opportunity", strategy: "options:call_spread/put_spread", shares_held: 0, target_coverage: 0.5,
  status: "proposed", basis: "market_event", market: { source: "polymarket", id: "nvda-150", token_id: "tok" }, direction: null,
  algo: { family: "binary_vs_spread_arb", preset_index: 4 }, max_contracts: 10, max_notional: 10_000,
  created_at: "2026-10-03T00:00:00Z", decided_at: null, ...over,
});

function fakeApi(existing: Proposal[], failLive = false) {
  const calls: string[] = [];
  const bodies: ProposalBody[] = [];
  const api: BridgeApi = {
    listProposals: async () => existing,
    createProposal: async (b) => { bodies.push(b); calls.push("create"); return prop({ id: "new" }); },
    approveProposal: async (id) => { calls.push(`approve:${id}`); return prop({ id, status: "approved" }); },
    getEquity: async () => { throw new Error("unused"); },
    startBridge: async (b) => {
      calls.push(`bridge:${b.proposal_id}:${b.source}`);
      if (failLive && b.source === "live") throw new Error("no live book");
      return { bridge_id: `b-${b.proposal_id}` };
    },
  };
  return { api, calls, bodies };
}

describe("opportunityFit", () => {
  it("offers only an options family with a real replay score", () => {
    assert.deepEqual(opportunityFit({ division: "opportunity", family: "vol_vs_pm_move", preset_index: 2, score: 0.4 }), { family: "vol_vs_pm_move", preset_index: 2, score: 0.4 });
    assert.equal(opportunityFit({ division: "opportunity", family: "vol_vs_pm_move", preset_index: 2, score: null }), null);  // rules pick
    assert.equal(opportunityFit({ division: "opportunity", family: "no_bid_seller", preset_index: 2, score: 0.9 }), null);  // PM legs, not options
    assert.equal(opportunityFit({ division: "hedge", family: "binary_vs_spread_arb", preset_index: 2, score: 0.9 }), null);
    assert.equal(opportunityFit(null), null);
  });
});

describe("startOpportunityBridge", () => {
  it("creates an opportunity proposal with the options algo and caps, approves it, starts live first", async () => {
    const { api, calls, bodies } = fakeApi([]);
    const r = await startOpportunityBridge(q, "NVDA", fit, api);
    assert.equal(r.bridgeId, "b-new");
    assert.deepEqual(calls, ["create", "approve:new", "bridge:new:live"]);
    const b = bodies[0] as Extract<ProposalBody, { division: "opportunity" }>;
    assert.equal(b.division, "opportunity");
    assert.deepEqual(b.algo, { family: "binary_vs_spread_arb", preset_index: 4, source: "ai_fit" });
    assert.equal(b.max_contracts, DEFAULT_OPP_CAPS.max_contracts);
    assert.equal(b.max_notional, DEFAULT_OPP_CAPS.max_notional);
  });
  it("reuses an approved proposal for the same market, algo and caps; falls back to replay", async () => {
    const { api, calls } = fakeApi([prop({ id: "old", status: "approved" })], true);
    const r = await startOpportunityBridge(q, "NVDA", fit, api);
    assert.equal(r.bridgeId, "b-old");
    assert.deepEqual(calls, ["bridge:old:live", "bridge:old:replay"]);
  });
  it("never reuses a proposal approved for another algo or other caps", async () => {
    const { api, calls } = fakeApi([prop({ id: "a", status: "approved", algo: { family: "vol_vs_pm_move", preset_index: 4 } }), prop({ id: "b", status: "approved", max_contracts: 3 })]);
    await startOpportunityBridge(q, "NVDA", fit, api);
    assert.ok(calls.includes("create"));
  });
});

describe("stream reducer: options", () => {
  it("keeps the latest PM-vs-options view, the gap history and the option position", () => {
    let s = reduce(init, { k: "open" });
    s = reduce(s, { k: "tick", p: 0.55, options: { pm_mid: 0.55, opt_implied_prob: 0.4, gap: 0.15 } });
    s = reduce(s, { k: "tick", p: 0.56 });
    assert.equal(s.options?.gap, 0.15);
    assert.deepEqual(s.gaps, [0.15]);
    s = reduce(s, { k: "position", option_position: 3, risk_used: 1560, broker: "sim" });
    assert.equal(s.optionPosition, 3);
    assert.equal(s.riskUsed, 1560);
    assert.equal(s.hedge, 0);  // an options position event leaves the hedge fields alone
  });
});

describe("option fill text", () => {
  it("says simulated, shows every leg and the cap", () => {
    const t = optionFillText({ status: "filled", side: "buy", qty: 3, structure: "call_spread", fill_px: 5.2, fee: 3.9, broker: "sim", capped_from: 5, cap: "max_contracts",
      legs: [{ ticker: "O:NVDA261218C00145000", side: "buy", qty: 3, status: "filled", fill_px: 8.1, quote_mid: 8, quote_half_spread: 0.1 },
             { ticker: "O:NVDA261218C00155000", side: "sell", qty: 3, status: "filled", fill_px: 2.9, quote_mid: 3, quote_half_spread: 0.1 }] });
    assert.equal(t.head, "3 call spreads @ 5.20/sh net");
    assert.match(t.detail, /^Simulated fill by sim/);
    assert.match(t.detail, /clipped it from 5/);
    assert.match(t.detail, /BUY 3 O:NVDA261218C00145000 @ 8\.10 \(quote 8\.00 ± 0\.10\)/);
    assert.match(optionFillText({ status: "held", reject_reason: "risk cap: max_notional used up", qty: 0 }).detail, /^Held: risk cap/);
    assert.equal(gapPts(0.153), "+15.3 pts");
    assert.equal(gapPts(-0.01), "−1.0 pts");
    assert.equal(gapPts(null), "n/a");
    assert.equal(legLine({ ticker: "X", side: "sell", qty: 1, status: "filled", fill_px: null }), "SELL 1 X (no quote: broker price)");
  });
});

describe("opportunity card copy", () => {
  it("describes each options family by its own idea, not one hard-coded gap sentence", () => {
    const vol = optionFamilyIdea("vol_vs_pm_move");
    const ek = optionFamilyIdea("eightk_opportunity");
    assert.match(vol, /implied volatility|IV/);
    assert.match(ek, /8-K/);
    assert.doesNotMatch(vol, /options-implied probability/);
    assert.match(optionFamilyIdea("binary_vs_spread_arb"), /options-implied probability/);
  });
  it("prefers the library's idea text when it is loaded", () => {
    const lib = { families: [{ id: "vol_vs_pm_move", idea: "PM reprices but implied vol has not moved: buy the straddle" }] };
    assert.equal(libraryIdea(lib, "vol_vs_pm_move"), "PM reprices but implied vol has not moved: buy the straddle");
    assert.equal(libraryIdea(lib.families, "eightk_opportunity"), null);
    assert.equal(optionFamilyIdea("vol_vs_pm_move", libraryIdea(lib, "vol_vs_pm_move")), "PM reprices but implied vol has not moved: buy the straddle.");
  });
  it("says the replay's option prices are estimates and fills are simulated", () => {
    assert.match(OPP_REPLAY_NOTE, /estimates from .*bar closes/);
    assert.match(OPP_REPLAY_NOTE, /simulated/);
  });
});
