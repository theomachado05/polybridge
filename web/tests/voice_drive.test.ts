// Voice drives the screen: the pure mapping from a client tool result to {route, storeUpdate, announcement}.
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { navigateReply, resolveMarket, SCREENS, SCREEN_PATH, searchedMarkets, VOICE_ANCHOR, voiceDrive, voiceStartLabel } from "../src/lib/voiceDrive.ts";
import { buildClientTools, VOICE_TOOLS, type ToolReply } from "../src/lib/voice.ts";
import type { Market, Proposal } from "../src/lib/api.ts";
import { startRealBridge, type BridgeApi } from "../src/lib/realBridge.ts";
import { questionFromMarket, type EquityPick } from "../src/lib/markets.ts";

const ok = (tool: string, data: unknown, summary = "done"): ToolReply => ({ ok: true, tool, summary, data });
const fail = (tool: string, extra: Partial<ToolReply> = {}): ToolReply => ({ ok: false, tool, summary: "That did not work.", data: null, ...extra });
const MKT: Market = { source: "polymarket", id: "4620900", question: "US recession in 2025?", yes_price: 0.12, volume_24h: 900, end_date: "2025-12-31", url: null, token_id: "tok", recorded: "rec.csv" };
const FIT = { event_class: "macro", division: "hedge", family: "delta_bridge", preset_index: 1, params: {}, score: 0.314, alternatives: [], rationale: "r", llm: "gemini", ticks_source: "replay", n_ticks: 400 };
const PROP = { id: "p7", ticker: "SPY", family: "hedge", strategy: "short_shares", shares_held: 1000, target_coverage: 0.5, status: "proposed",
  market: { source: "polymarket", id: "4620900", token_id: "tok" }, direction: "down_on_yes", evidence: { validated: true }, created_at: "", decided_at: null };

describe("voice drives the screen", () => {
  it("search_markets → Build step 1 with the query typed in", () => {
    const d = voiceDrive("search_markets", { q: "recession" }, ok("search_markets", { markets: [MKT], stale: false }));
    assert.deepEqual(d, { route: "/build", storeUpdate: { kind: "search", query: "recession" }, announcement: "Showing markets for “recession”", scrollTo: null });
    assert.equal(voiceDrive("search_markets", { q: "zzz" }, ok("search_markets", { markets: [] })).announcement, "No markets for “zzz”");
    assert.deepEqual(searchedMarkets(ok("search_markets", { markets: [MKT, { nope: 1 }] })), [MKT]);
    assert.deepEqual(searchedMarkets(fail("search_markets")), []);
  });

  it("fit → the fit lands in the store for that market + ticker, and the pipeline shows its steps", () => {
    const d = voiceDrive("fit", { ticker: "spy", market_source: "polymarket", market_id: "4620900", direction: "down_on_yes", shares_held: 1000 }, ok("fit", FIT), [MKT]);
    assert.equal(d.route, "/build/fit");
    assert.equal(d.scrollTo, VOICE_ANCHOR.steps);
    assert.deepEqual(d.storeUpdate, { kind: "fit", market: MKT, ticker: "SPY", direction: "down_on_yes", sharesHeld: 1000, fit: FIT });
    assert.equal(d.announcement, "SPY fit ready · score 0.31");
    // A market the agent did not search for: a minimal row with nothing invented.
    const u = voiceDrive("fit", { ticker: "TLT", market_id: "77", question: "Fed cut?" }, ok("fit", { ...FIT, score: null })).storeUpdate;
    assert.ok(u && u.kind === "fit");
    assert.deepEqual(u.market, { source: "polymarket", id: "77", question: "Fed cut?", yes_price: null, volume_24h: 0, end_date: null, url: null, token_id: null });
    assert.equal(u.direction, null);
    assert.match(voiceDrive("fit", { ticker: "TLT", market_id: "77" }, ok("fit", { ...FIT, score: null })).announcement, /unscored/);
    // No market id: the fit cannot be pinned to a pick, so the screen stays.
    assert.equal(voiceDrive("fit", { ticker: "SPY", question: "recession" }, ok("fit", FIT)).route, null);
  });

  it("propose → the pipeline's approval panel with that pending proposal", () => {
    const d = voiceDrive("propose", { ticker: "SPY", shares_held: 1000, market_id: "4620900" }, ok("propose", PROP), [MKT]);
    assert.deepEqual(d, { route: "/build/fit", storeUpdate: { kind: "proposal", proposal: PROP, market: MKT }, announcement: "Proposal p7 is waiting for your approval", scrollTo: VOICE_ANCHOR.approval });
    // Filing-tag proposals (no market) and opportunities have no hedge approval panel.
    assert.equal(voiceDrive("propose", {}, ok("propose", { ...PROP, market: null })).route, null);
    assert.equal(voiceDrive("propose", {}, ok("propose", { ...PROP, family: "opportunity" })).route, null);
  });

  it("approve moves only with confirm true, and reflects the approval", () => {
    const approved = { ...PROP, status: "approved", ack_unvalidated: true };
    const d = voiceDrive("approve", { proposal_id: "p7", confirm: true, ack_unvalidated: true }, ok("approve", approved));
    assert.equal(d.route, "/build/fit");
    assert.equal(d.scrollTo, VOICE_ANCHOR.approval);
    assert.deepEqual(d.storeUpdate, { kind: "proposal", proposal: approved, market: resolveMarket("polymarket", "4620900", "tok", null) });
    assert.equal(d.announcement, "Proposal p7 approved");
    assert.equal(voiceDrive("approve", { proposal_id: "p7" }, ok("approve", approved)).route, null);
    const gated = voiceDrive("approve", { proposal_id: "p7" }, fail("approve", { needs_confirmation: true }));
    assert.deepEqual(gated, { route: null, storeUpdate: null, announcement: "Waiting for your spoken yes", scrollTo: null });
  });

  it("start_bridge → that bridge, live", () => {
    const d = voiceDrive("start_bridge", { proposal_id: "p7", confirm: true }, ok("start_bridge", { bridge_id: "b9" }));
    assert.deepEqual(d, { route: "/bridge/b9", storeUpdate: { kind: "bridge", bridgeId: "b9", proposalId: "p7" }, announcement: "Bridge b9 is live", scrollTo: null });
    assert.equal(voiceDrive("start_bridge", { proposal_id: "p7" }, ok("start_bridge", { bridge_id: "b9" })).route, null);
  });

  it("bridge_status → that bridge; account and positions → the portfolio's panels", () => {
    assert.deepEqual(voiceDrive("bridge_status", { bridge_id: "b9" }, ok("bridge_status", { status: "running" })),
      { route: "/bridge/b9", storeUpdate: null, announcement: "Showing bridge b9", scrollTo: null });
    assert.deepEqual(voiceDrive("account", {}, ok("account", { cash: 1 })),
      { route: "/portfolio", storeUpdate: { kind: "account" }, announcement: "Opening your account", scrollTo: VOICE_ANCHOR.account });
    assert.deepEqual(voiceDrive("positions", {}, ok("positions", [])),
      { route: "/portfolio", storeUpdate: { kind: "account" }, announcement: "Opening your positions", scrollTo: VOICE_ANCHOR.positions });
  });

  it("navigate → the named screen (a bridge by id), answered in the browser", () => {
    for (const screen of SCREENS) {
      const r = navigateReply({ screen });
      assert.equal(r.ok, true);
      assert.equal(voiceDrive("navigate", { screen }, r).route, SCREEN_PATH[screen]);
    }
    assert.equal(SCREEN_PATH.landing, "/");
    const b = navigateReply({ screen: "bridge", bridge_id: "b9" });
    assert.deepEqual(b.data, { screen: "bridge", bridge_id: "b9" });
    assert.deepEqual(voiceDrive("navigate", { screen: "bridge", bridge_id: "b9" }, b), { route: "/bridge/b9", storeUpdate: null, announcement: "Opening bridge b9", scrollTo: null });
    assert.equal(voiceDrive("navigate", { screen: "portfolio" }, navigateReply({ screen: "portfolio" })).announcement, "Opening your portfolio");
    // bridge_id only counts with the bridge screen
    assert.equal(voiceDrive("navigate", { screen: "library", bridge_id: "b9" }, navigateReply({ screen: "library", bridge_id: "b9" })).route, "/library");
    const bad = navigateReply({ screen: "settings" });
    assert.equal(bad.ok, false);
    assert.match(bad.summary, /cannot open settings/);
    assert.equal(voiceDrive("navigate", { screen: "settings" }, bad).route, null);
  });

  it("an error never navigates away and never touches the store", () => {
    for (const tool of VOICE_TOOLS) {
      const d = voiceDrive(tool, { q: "x", ticker: "SPY", market_id: "1", confirm: true, bridge_id: "b", screen: "portfolio" }, fail(tool, { status: 500 }));
      assert.equal(d.route, null, tool);
      assert.equal(d.storeUpdate, null, tool);
      assert.match(d.announcement, /did not work · staying here$/, tool);
    }
  });

  it("says what it is doing while a tool runs", () => {
    assert.equal(voiceStartLabel("search_markets", {}), "Searching markets…");
    assert.equal(voiceStartLabel("search_markets", { q: "fed" }), "Searching markets for “fed”…");
    assert.equal(voiceStartLabel("fit", { ticker: "spy" }), "Fitting SPY…");
    assert.equal(voiceStartLabel("navigate", { screen: "portfolio" }), "Opening your portfolio");
    assert.equal(voiceStartLabel("account", {}), "Opening your account…");
  });

  it("navigate never calls the backend", async () => {
    const calls: string[] = [];
    const tools = buildClientTools(async (name) => { calls.push(name); return ok(name, null); });
    const out = await tools.navigate({ screen: "portfolio" });
    assert.deepEqual(calls, []);
    assert.match(out, /^ok: true\nsummary: The screen now shows your portfolio\./);
    await tools.account({});
    assert.deepEqual(calls, ["account"]);
  });
});

describe("the mouse continues from a voice proposal", () => {
  it("approving on the pipeline approves and runs the proposal voice drafted, not a new one", async () => {
    const seen: string[] = [];
    const api: BridgeApi = {
      listProposals: async () => { seen.push("list"); return []; },
      createProposal: async () => { seen.push("create"); throw new Error("must not create"); },
      approveProposal: async (id, ack) => { seen.push(`approve:${id}:${ack}`); return { ...(PROP as Proposal), id, status: "approved" }; },
      getEquity: async () => { throw new Error("unused"); },
      startBridge: async (b) => { seen.push(`start:${b.proposal_id}`); return { bridge_id: "b1" }; },
    };
    const q = questionFromMarket(MKT);
    const eq: EquityPick = { t: "SPY", move: -2, rev: null, brand: null, why: "", direction: "down_on_yes", name: "SPY", px: 500, held: 1000 };
    const r = await startRealBridge(q, eq, "100%", api, null, { proposal: PROP as Proposal, ackUnvalidated: false });
    assert.equal(r.bridgeId, "b1");
    assert.deepEqual(seen, ["approve:p7:false", "start:p7"]);
    // Already approved by voice: no second approval.
    seen.length = 0;
    await startRealBridge(q, eq, "100%", api, null, { proposal: { ...(PROP as Proposal), status: "approved" } });
    assert.deepEqual(seen, ["start:p7"]);
  });
});
