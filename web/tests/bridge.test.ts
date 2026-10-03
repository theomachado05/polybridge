// Offline tests for opening a live bridge (proposal reuse, approval, fee gate) with the API injected.
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { feeGateOff, gapPerShare, runnableFit, startRealBridge, type BridgeApi } from "../src/lib/realBridge.ts";
import { QUESTIONS, REAL_INSTRUMENTS, questionFromMarket, type EquityPick } from "../src/lib/demo.ts";
import type { Proposal } from "../src/lib/api.ts";
import { init, reduce } from "../src/lib/bridgeStream.ts";
import { blockUi } from "../src/lib/library.ts";

const q = questionFromMarket({ source: "polymarket", id: "m1", question: "Will X happen?", yes_price: 0.4, volume_24h: 1000, end_date: null, url: null, token_id: "tok" });
const eq: EquityPick = { t: "ABNB", move: -3, rev: null, brand: null, why: "", direction: "down_on_yes", name: "Airbnb", px: 130, held: 1200 };

const prop = (over: Partial<Proposal>): Proposal => ({
  id: "p1", ticker: "ABNB", family: "hedge", strategy: "protective_put", shares_held: 1200, target_coverage: 0.5, status: "proposed",
  basis: "market_event", market: { source: "polymarket", id: "m1", token_id: "tok" }, direction: "down_on_yes",
  created_at: "2026-10-03T00:00:00Z", decided_at: null, ...over,
});

function fakeApi(existing: Proposal[], opts: { failBridge?: boolean } = {}) {
  const calls: string[] = [];
  const api: BridgeApi = {
    listProposals: async () => { calls.push("list"); return existing; },
    createProposal: async () => { calls.push("create"); return prop({ id: "new" }); },
    approveProposal: async (id: string) => { calls.push(`approve:${id}`); return prop({ id, status: "approved" }); },
    getEquity: async () => { calls.push("equity"); throw new Error("no quote"); },
    startBridge: async (body) => {
      calls.push(`bridge:${body.proposal_id}:${body.source}:${body.gap_per_share}`);
      if (opts.failBridge) throw new Error("No replay file configured");
      return { bridge_id: `b-${body.proposal_id}` };
    },
  };
  return { api, calls };
}

describe("startRealBridge", () => {
  it("creates and approves a new proposal when none exists, with the fee-gate gap from spot and move", async () => {
    const { api, calls } = fakeApi([]);
    const r = await startRealBridge(q, eq, "100%", api);
    assert.deepEqual(r, { bridgeId: "b-new", gap: 3.9, applied: null });
    assert.deepEqual(calls, ["list", "create", "approve:new", "bridge:new:replay:3.9"]);
  });
  it("reuses an approved proposal for the same market, ticker and direction (no new proposal per run)", async () => {
    const { api, calls } = fakeApi([prop({ id: "old", status: "approved" })]);
    const r = await startRealBridge(q, eq, "100%", api);
    assert.equal(r.bridgeId, "b-old");
    assert.ok(!calls.includes("create") && !calls.some((c) => c.startsWith("approve")));
  });
  it("approves a pending proposal instead of creating another", async () => {
    const { api, calls } = fakeApi([prop({ id: "pend" })]);
    await startRealBridge(q, eq, "100%", api);
    assert.ok(calls.includes("approve:pend") && !calls.includes("create"));
  });
  it("ignores proposals for another market, ticker or direction", async () => {
    const { api, calls } = fakeApi([
      prop({ id: "a", status: "approved", market: { source: "polymarket", id: "other" } }),
      prop({ id: "b", status: "approved", ticker: "NVDA" }),
      prop({ id: "c", status: "approved", direction: "up_on_yes" }),
    ]);
    await startRealBridge(q, eq, "100%", api);
    assert.ok(calls.includes("create"));
  });
  it("tries replay then live, and says the approved proposal is reused when both fail", async () => {
    const { api, calls } = fakeApi([], { failBridge: true });
    await assert.rejects(startRealBridge(q, eq, "100%", api), /proposal new stays approved and is reused/);
    assert.deepEqual(calls.filter((c) => c.startsWith("bridge")), ["bridge:new:replay:3.9", "bridge:new:live:3.9"]);
  });
  it("never touches the backend for a demo market", async () => {
    const { api, calls } = fakeApi([]);
    await assert.rejects(startRealBridge(QUESTIONS[0], eq, "100%", api), /demo set/);
    assert.deepEqual(calls, []);
  });
});

describe("startRealBridge with an AI fit", () => {
  function fitApi(existing: Proposal[]) {
    const calls: { create?: unknown; bridges: unknown[] } = { bridges: [] };
    const api: BridgeApi = {
      listProposals: async () => existing,
      createProposal: async (body) => { calls.create = body; return prop({ id: "new", algo: (body as { algo?: Proposal["algo"] }).algo ?? null }); },
      approveProposal: async (id: string) => prop({ id, status: "approved" }),
      getEquity: async () => { throw new Error("no quote"); },
      startBridge: async (body) => { calls.bridges.push(body); return { bridge_id: `b-${body.proposal_id}` }; },
    };
    return { api, calls };
  }
  const fit = { family: "macro_fed_hedge", preset_index: 5 };

  it("sends the family and preset with the proposal and the bridge, and reports them as applied", async () => {
    const { api, calls } = fitApi([]);
    const r = await startRealBridge(q, eq, "100%", api, fit);
    assert.deepEqual(r.applied, fit);
    assert.deepEqual((calls.create as { algo: unknown }).algo, { family: "macro_fed_hedge", preset_index: 5, source: "ai_fit" });
    const b = calls.bridges[0] as { family: string; preset_index: number };
    assert.equal(b.family, "macro_fed_hedge");
    assert.equal(b.preset_index, 5);
  });
  it("reuses only a proposal approved with the same algo", async () => {
    const same = prop({ id: "same", status: "approved", target_coverage: 1, algo: { family: "macro_fed_hedge", preset_index: 5 } });
    const other = prop({ id: "other", status: "approved", algo: { family: "macro_fed_hedge", preset_index: 6 } });
    const none = prop({ id: "none", status: "approved" });
    assert.equal((await startRealBridge(q, eq, "100%", fitApi([other, none, same]).api, fit)).bridgeId, "b-same");
    const { api, calls } = fitApi([other, none]);
    assert.equal((await startRealBridge(q, eq, "100%", api, fit)).bridgeId, "b-new");
    assert.ok(calls.create);
    // no fit: a proposal approved with an algo is not reused (the bridge would run that algo, not the default)
    assert.equal((await startRealBridge(q, eq, "100%", fitApi([same, none]).api)).bridgeId, "b-none");
  });
  it("with a fit the approved target_coverage is the user's Max hedge (the backend caps the algo at it)", async () => {
    const { api, calls } = fitApi([]);
    await startRealBridge(q, eq, "40%", api, fit);
    assert.equal((calls.create as { target_coverage: number }).target_coverage, 0.4);
    const noFit = fitApi([]);
    await startRealBridge(q, eq, "100%", noFit.api);
    assert.equal((noFit.calls.create as { target_coverage: number }).target_coverage, 0.5); // default Engine: half
    // a proposal approved at another cap is not reused: the approval bounds what the bridge may hedge
    const atHalf = prop({ id: "half", status: "approved", target_coverage: 0.5, algo: { family: "macro_fed_hedge", preset_index: 5 } });
    assert.equal((await startRealBridge(q, eq, "40%", fitApi([atHalf]).api, fit)).bridgeId, "b-new");
    assert.equal((await startRealBridge(q, eq, "50%", fitApi([atHalf]).api, fit)).bridgeId, "b-half");
  });
  it("without a fit the bridge body carries no family (the engine default spec runs)", async () => {
    const { api, calls } = fitApi([]);
    const r = await startRealBridge(q, eq, "100%", api);
    assert.equal(r.applied, null);
    assert.equal((calls.bridges[0] as { family?: string }).family, undefined);
    assert.equal((calls.create as { algo?: unknown }).algo, undefined);
  });
  it("only a hedge-division fit with a preset is runnable on a bridge", () => {
    assert.deepEqual(runnableFit({ family: "macro_fed_hedge", preset_index: 5, division: "hedge" }), fit);
    assert.equal(runnableFit({ family: "no_bid_seller", preset_index: 2, division: "opportunity" }), null);
    assert.equal(runnableFit({ family: null, preset_index: null, division: "hedge" }), null);
    assert.equal(runnableFit(null), null);
  });
});

describe("fee gate and real hedge menu", () => {
  it("flags a live bridge that would start with the fee gate off", () => {
    assert.equal(gapPerShare(null, -3), 0);
    assert.equal(gapPerShare(100, 0), 0);
    assert.equal(feeGateOff(q, { ...eq, px: null }), true);
    assert.equal(feeGateOff(q, eq), false);
    assert.equal(feeGateOff(QUESTIONS[0], { ...eq, px: null }), false); // demo markets never reach the engine
  });
  it("offers only the engine's hedge on live markets, with no invented prices", () => {
    const menu = REAL_INSTRUMENTS(null);
    assert.deepEqual(menu.map((i) => i.id), ["shares"]);
    assert.equal(menu[0].cost, "quote unavailable");
    assert.equal(menu[0].rec, false);
    assert.equal(REAL_INSTRUMENTS(131.5)[0].cost, "last quote $131.50");
  });
});


describe("bridge stream reducer", () => {
  it("attaches a broker fill to the order it follows and tracks the broker's hedge", () => {
    let s = reduce(init, { k: "open" });
    s = reduce(s, { k: "tick", p: 0.4 });
    s = reduce(s, { k: "decision", d: { action: "hold", reason: "inside_band", order_qty: 0, target_hedge: 0, current_hedge: 0, latency_ns: 900 } });
    s = reduce(s, { k: "decision", d: { action: "order", reason: "rebalance", order_qty: 120, target_hedge: 120, current_hedge: 0, latency_ns: 1200 } });
    s = reduce(s, { k: "fill", f: { broker: "sim", status: "filled", fill_px: 131.2, filled_qty: 120 } });
    s = reduce(s, { k: "position", hedge: 120, coverage: 0.1, broker_hedge: 120, broker: "sim" });
    assert.equal(s.log[0].fill, undefined);
    assert.equal(s.log[1].fill?.fill_px, 131.2);
    assert.equal(s.brokerHedge, 120);
    assert.equal(s.fills, 1);
    assert.equal(s.broker, "sim");
  });
  it("keeps the broker hedge unknown on a backend without a broker", () => {
    const s = reduce(reduce(init, { k: "open" }), { k: "position", hedge: 50, coverage: 0.1 });
    assert.equal(s.brokerHedge, null);
  });
});

describe("compiled manifest blocks", () => {
  it("uses the manifest's own ui_kind, then kind, then the block name", () => {
    assert.equal(blockUi({ name: "PositionCap", kind: "risk", ui_kind: "Gate" }), "Gate");
    assert.equal(blockUi({ name: "Whatever", kind: "signals" }), "Reader");
    assert.equal(blockUi("FeeGate"), "Execution");
  });
});
