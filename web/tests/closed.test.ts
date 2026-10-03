// Offline tests for closed-market mode's view logic (U1-U5): session pill and headline, the evidence gate on the
// expected gap, staged hedge B actions and merge, hedge A gating, the research-only opportunity card, the stream
// reducer's closed-market events, and the hedge A opt-in on the proposal.
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  HEDGE_A_FALLBACK, HEDGE_B_FALLBACK, OPPORTUNITY_FALLBACK, PHASE_LABEL, appendTimeline, bandText, closedHeadline, etDayTime, executionText,
  fmtBp, fmtEt, fmtPp, gapBadge, hedgeAView, mergeOrders, newerOrder, normalizeGap, opportunityView, pnlRows, sessionClosed, sessionPill,
  stagedActions, stagedHedgeText, stagedStatusText, weekendExposure, weekendModeCopy, type GapView, type StagedOrder,
  currentGap, exposureTotal, pnlTotals, type ClosurePnl, type ExposureRowLite,
} from "../src/lib/closed.ts";
import { init, quantile, reduce } from "../src/lib/bridgeStream.ts";
import { reusableBridge, startRealBridge, type BridgeApi } from "../src/lib/realBridge.ts";
import { questionFromMarket, type EquityPick } from "../src/lib/demo.ts";
import type { Proposal, ProposalBody } from "../src/lib/api.ts";

// The recorded weekend (us-recession-in-2025, validated) as the bridge reports it on a Saturday tick.
const SAT = {
  at: "2025-04-05T18:00:05Z", phase: "weekend", closed: true, label: "Market closed · reopens Mon 09:30 ET / pre-market 04:00",
  next_open: "2025-04-07T13:30:00Z", next_open_et: "2025-04-07T09:30:00-04:00",
  next_premarket: "2025-04-07T08:00:00Z", next_premarket_et: "2025-04-07T04:00:00-04:00", last_close: "2025-04-04T20:00:00Z", closure_kind: "weekend",
};
const validatedGap: GapView = {
  bp: -128.8, band: [-210.4, -47.2], band_level: 0.8, n: 231, rate_source: "market", rate_bp_per_pp: 10.73, validated: true, status: "validated",
  evidence: "Validated out of sample on this market (R2): sign right in 97 of 151 (64.2%), slope +1.28 (permutation p < 0.001).", active: true,
};
const order = (over: Partial<StagedOrder> = {}): StagedOrder => ({
  id: "s1", status: "staged", ticker: "SPY", side: "sell", qty: 222, session_target: "pre_market", execute_at: "2025-04-07T08:00:00Z",
  decisions: [{ at: "2025-04-05T18:00:05Z", code: "PLANNED" }], ...over,
});

describe("session (U1)", () => {
  it("labels every phase for the nav pill", () => {
    const want = { regular: "Regular", pre_market: "Pre-market", after_hours: "After-hours", overnight: "Overnight", weekend: "Weekend", holiday: "Holiday" };
    assert.deepEqual(PHASE_LABEL, want);
    for (const [phase, text] of Object.entries(want)) assert.equal(sessionPill({ phase, label: "x" })?.text, text);
    assert.equal(sessionPill({ phase: "lunch" }), null);
    assert.equal(sessionPill(null), null);
  });
  it("counts pre-market as closed (the equity algo still holds) and regular as open", () => {
    assert.equal(sessionClosed({ phase: "pre_market" }), true);
    assert.equal(sessionClosed({ phase: "regular" }), false);
    assert.equal(sessionClosed({ phase: "weekend", equities_open: false }), true);
    assert.equal(sessionClosed({ phase: "regular", closed: false }), false);
    assert.equal(sessionClosed(null), false);
  });
  it("shows the backend's closed headline, and builds the same sentence when it has none", () => {
    assert.equal(closedHeadline(SAT), "Market closed · reopens Mon 09:30 ET / pre-market 04:00");
    assert.equal(closedHeadline({ ...SAT, label: "" }), "Market closed · reopens Mon 09:30 ET / pre-market 04:00");
    assert.equal(closedHeadline({ ...SAT, label: null, phase: "after_hours" }), "After-hours · reopens Mon 09:30 ET / pre-market 04:00");
    assert.equal(closedHeadline({ ...SAT, label: null, phase: "pre_market" }), "Pre-market · regular open 09:30 ET");
    // GET /session names the pre-market fields next_extended_open(_et)
    const api = { phase: "weekend", equities_open: false, next_open: SAT.next_open, next_open_et: SAT.next_open_et, next_extended_open: SAT.next_premarket, next_extended_open_et: SAT.next_premarket_et };
    assert.equal(closedHeadline(api), "Market closed · reopens Mon 09:30 ET / pre-market 04:00");
    assert.equal(closedHeadline({ phase: "regular", closed: false, label: "Market open · closes 16:00 ET" }), null);
  });
  it("reads ET day and time off the offset string, and formats UTC instants in ET", () => {
    assert.deepEqual(etDayTime("2025-04-07T09:30:00-04:00"), { day: "Mon", hm: "09:30" });
    assert.equal(etDayTime("garbage"), null);
    assert.equal(fmtEt("2025-04-07T08:05:00Z"), "Mon 04:05 ET");
    assert.equal(fmtEt("2025-04-05T18:00:05Z", true), "Sat 5 Apr 2025 14:00 ET");
    assert.equal(fmtEt(null), "—");
  });
});

describe("expected gap and the evidence gate (U2)", () => {
  it("reads VALIDATED only when the backend validated it, says so, and the market's own rate is in use", () => {
    assert.deepEqual(gapBadge(validatedGap), { validated: true, text: "validated", reason: validatedGap.evidence });
    assert.equal(gapBadge({ ...validatedGap, rate_source: "pooled" }).validated, false);
    assert.equal(gapBadge({ ...validatedGap, status: "unvalidated estimate" }).validated, false);
    assert.equal(gapBadge({ ...validatedGap, validated: false }).text, "unvalidated estimate");
    const none = gapBadge(null);
    assert.equal(none.validated, false);
    assert.match(none.reason, /unvalidated estimate/);
  });
  it("normalizes both the bridge view and GET /closed/expected-gap's names", () => {
    const fromRoute = normalizeGap({ expected_gap_bp: -75, band_bp: [-150, 0], n_closures: 40, label: "pooled", validated: false, status: "unvalidated estimate", active: true, evidence: "No out-of-sample test" });
    assert.deepEqual([fromRoute?.bp, fromRoute?.band, fromRoute?.n, fromRoute?.rate_source, fromRoute?.validated], [-75, [-150, 0], 40, "pooled", false]);
    assert.equal(normalizeGap(validatedGap as unknown as Record<string, unknown>)?.bp, -128.8);
    assert.equal(normalizeGap(null), null);
    assert.equal(normalizeGap({ bp: null, active: false })?.active, false);
  });
  it("always shows the band and the closures behind the rate", () => {
    assert.equal(bandText(validatedGap), "80% band −210.4 to −47.2 bp · 231 closures, this market's rate");
    assert.equal(bandText({ ...validatedGap, band: null, rate_source: "pooled", n: 1, band_level: undefined }), "no band (no move yet) · 1 closure, pooled rate");
    assert.equal(fmtBp(-128.8), "−128.8 bp");
    assert.equal(fmtPp(8), "+8.0 pts");
    assert.equal(fmtBp(null), "n/a");
  });
  it("weekend exposure is expected gap × position value, with the band", () => {
    const x = weekendExposure(505_500, validatedGap)!;
    assert.ok(Math.abs(x.usd - -6510.84) < 0.01);
    assert.ok(x.lo! < x.usd && x.usd < x.hi!);
    assert.equal(weekendExposure(null, validatedGap), null);
    assert.equal(weekendExposure(1000, { ...validatedGap, bp: null }), null);
  });
});

describe("staged orders, hedge B (U2, U3)", () => {
  it("offers Approve plan only on a plan awaiting approval, Cancel while it can still trade", () => {
    assert.deepEqual(stagedActions({ status: "staged" }), { approve: true, cancel: true });
    assert.deepEqual(stagedActions({ status: "approved" }), { approve: false, cancel: true });
    assert.deepEqual(stagedActions({ status: "working" }), { approve: false, cancel: true });
    for (const s of ["filled", "cancelled", "rejected", "skipped"]) assert.deepEqual(stagedActions({ status: s }), { approve: false, cancel: false });
  });
  it("says when it executes: pre-market or the open", () => {
    assert.equal(executionText(order()), "pre-market Mon 04:00 ET");
    assert.equal(executionText(order({ session_target: "regular_open", execute_at: "2025-04-07T13:30:00Z" })), "the Mon 09:30 ET open");
    assert.equal(stagedStatusText(order({ status: "approved" })), "approved · executes at pre-market Mon 04:00 ET");
    assert.equal(stagedStatusText(order({ status: "filled", filled_qty: 222, fill_px: 488.45 })), "filled 222 @ 488.45");
    assert.equal(stagedStatusText(order({ status: "cancelled", reason: "PM_REVERTED" })), "cancelled (pm reverted)");
  });
  it("keeps the newest copy of an order (decisions only grow) and lists newest plans first", () => {
    const a = order(), b = order({ status: "approved", decisions: [...a.decisions!, { at: "2025-04-05T19:00:00Z", code: "APPROVED" }] });
    assert.equal(newerOrder(a, b)?.status, "approved");
    assert.equal(newerOrder(b, a)?.status, "approved");
    const lite = { id: "s1", status: "staged", qty: 222, session_target: "pre_market", execute_at: a.execute_at } as StagedOrder;
    assert.equal(mergeOrders([lite], { s1: b })[0].status, "approved");
    const older = order({ id: "s0", decisions: [{ at: "2025-04-04T21:00:00Z", code: "PLANNED" }] });
    assert.deepEqual(mergeOrders([older], [a]).map((o) => o.id), ["s1", "s0"]);
  });
  it("hedge B is never called hedged against the gap: it trades after the gap; cancelled and skipped plans never count", () => {
    assert.equal(stagedHedgeText([]).state, "none");
    assert.equal(stagedHedgeText([order()]).badge, "Hedge B awaiting approval");
    const ap = stagedHedgeText([order({ status: "approved" })]);
    assert.equal(ap.state, "approved");
    assert.equal(ap.badge, "Hedge B approved · executes pre-market Mon 04:00 ET (after the gap)");
    assert.equal(stagedHedgeText([order({ status: "approved", session_target: "regular_open", execute_at: "2025-04-07T13:30:00Z" })]).badge,
      "Hedge B approved · executes the Mon 09:30 ET open (after the gap)");
    assert.equal(stagedHedgeText([order({ status: "working" })]).badge, "Hedge B sent (after the gap)");
    const f = stagedHedgeText([order({ status: "filled", filled_qty: 222, fill_px: 488.45 })]);
    assert.equal(f.badge, "Hedge B filled (after the gap)");
    assert.match(f.text, /cannot recover it/);
    assert.equal(stagedHedgeText([order({ status: "cancelled" }), order({ id: "x", status: "skipped" })]).state, "none");
    for (const st of ["staged", "approved", "working", "filled"]) {
      const h = stagedHedgeText([order({ status: st })]);
      assert.doesNotMatch(`${h.badge} ${h.text}`, /\bhedged\b/i);
    }
  });
  it("timeline rows replayed on reconnect are not duplicated", () => {
    const row = { at: "2025-04-04T20:00:05Z", at_et: "Fri", event: "close" };
    assert.equal(appendTimeline(appendTimeline([], row), { ...row }).length, 1);
    assert.equal(appendTimeline([], null).length, 0);
  });
});

describe("hedge A gating and honest copy (U2, U4)", () => {
  it("is shown only when the proposal opted in, and is always an estimate, never protection", () => {
    assert.equal(hedgeAView(null), null);
    assert.equal(hedgeAView({ enabled: false, label: "x" }), null);
    const v = hedgeAView({ enabled: true, contracts: 1200, equity_equiv_shares: 180, pnl_usd: -40 })!;
    assert.equal(v.title, "Hedge A · estimate — not protection");
    assert.match(v.label, /not protection/);
    assert.deepEqual([v.contracts, v.equivShares, v.pnl], [1200, 180, -40]);
  });
  it("Weekend mode copy: hedge B default with R1's evidence, hedge A no evidence; backend labels win when present", () => {
    const fb = weekendModeCopy(null);
    assert.equal(fb.hedgeB, HEDGE_B_FALLBACK);
    assert.equal(fb.hedgeA, HEDGE_A_FALLBACK);
    assert.match(fb.hedgeB, /11\.4%/);
    assert.match(fb.hedgeA, /no evidence/);
    assert.doesNotMatch(fb.hedgeA, /(?<!not )protection(?! )/);
    const api = weekendModeCopy({ hedge_b: { label: "B from API", vr0: 0.1142, vr0_ci: [0.051, 0.1814] }, hedge_a: { label: "A from API", vr0: 0.0476, vr0_ci: [-0.008, 0.1] } });
    assert.equal(api.hedgeB, "B from API");
    assert.equal(api.hedgeBStat, "+11.4% (95% CI +5.1% to +18.1%)");
    assert.equal(api.hedgeAStat, "+4.8% (95% CI −0.8% to +10.0%)");
  });
});

describe("opportunity at the open (U5)", () => {
  it("is research-only and never offers a trade, whatever the research status says", () => {
    const v = opportunityView(null);
    assert.equal(v.trade, false);
    assert.equal(v.title, "Opportunity at the open · research only");
    assert.equal(v.text, OPPORTUNITY_FALLBACK);
    assert.equal(v.verdict, "R3 NULL");
    assert.equal(opportunityView({ label: "L", verdict: "NULL" }, { status: "supported", verdict: "PASS" }).trade, false);
  });
});

describe("closure P&L rows", () => {
  it("lists the legs vs no hedge; hedge A only when it ran, marked an estimate", () => {
    const p = { since: null, s_close: 505.5, s_now: 494.63, shares_held: 1000, unhedged_usd: -10870, carried_hedge_shares: 278, carried_hedge_usd: 3022,
      staged_short_shares: 222, staged_usd: -1607, algo_short_shares: -182, algo_usd: 1179, hedge_a_usd: null, hedge_a_estimate: false, hedged_usd: -8276, vs_no_hedge_usd: 2594, price_source: "recorded" };
    assert.deepEqual(pnlRows(p).map((r) => r.k), ["Holding, no hedge", "Hedge carried from the close (278 sh)", "Staged order, hedge B (222 sh)", "Algo after the open (182 sh)"]);
    assert.equal(pnlRows({ ...p, hedge_a_estimate: true, hedge_a_usd: 12 }).at(-1)?.k, "Hedge A (estimate)");
    assert.deepEqual(pnlRows(null), []);
  });
});

describe("stream reducer: closed-market events", () => {
  it("keeps the latest tick's closed block, ignores hold latencies, and merges staged / timeline / hedge A events", () => {
    let s = reduce(init, { k: "open" });
    s = reduce(s, { k: "tick", p: 0.6, closed: { session: SAT, closure: { pm_move_pp: 4.5, since: SAT.last_close, status: "TRACKING", p_close: 0.555, p_now: 0.6 }, expected_gap: validatedGap, hold: true } });
    assert.equal(s.closed?.session?.phase, "weekend");
    s = reduce(s, { k: "decision", d: { action: "hold", reason: "session_closed", order_qty: 0, target_hedge: null, current_hedge: 278, latency_ns: null } });
    s = reduce(s, { k: "decision", d: { action: "hold", reason: "inside_band", order_qty: 0, target_hedge: null, current_hedge: 278, latency_ns: 1200 } });
    assert.deepEqual(s.lat, [1200]);
    assert.equal(quantile(s.lat, 0.5), 1200);
    assert.equal(s.reasons.session_closed, 1);
    const row = { at: "2025-04-05T18:00:05Z", at_et: "Sat", event: "plan", staged_id: "s1" };
    s = reduce(s, { k: "staged", d: { event: "planned", order: order(), timeline: row } });
    s = reduce(s, { k: "staged", d: { event: "update", order: order({ qty: 240, decisions: [...order().decisions!, { at: "x", code: "RESIZED" }] }), timeline: null } });
    assert.equal(s.staged.s1.qty, 240);
    s = reduce(s, { k: "staged", d: { event: "planned", order: order(), timeline: row } });  // a stale copy never wins
    assert.equal(s.staged.s1.qty, 240);
    assert.equal(s.timeline.length, 1);
    s = reduce(s, { k: "handoff", d: { event: "open", timeline: { at: "2025-04-07T13:30:05Z", at_et: "Mon", event: "open" } } });
    assert.deepEqual(s.timeline.map((r) => r.event), ["plan", "open"]);
    assert.equal(s.hedgeA, null);
    s = reduce(s, { k: "hedge_a", d: { summary: { enabled: true, contracts: 10 } } });
    assert.equal(s.hedgeA?.contracts, 10);
    // the server replays history on reconnect: state starts over
    assert.deepEqual(reduce(s, { k: "open" }).staged, {});
  });
});

describe("hedge A opt-in on the proposal (U4)", () => {
  const q = questionFromMarket({ source: "polymarket", id: "516710", question: "US recession in 2025?", yes_price: 0.555, volume_24h: 1000, end_date: null, url: null, token_id: "tok" });
  const eq: EquityPick = { t: "SPY", move: -2, rev: null, brand: null, why: "", direction: "down_on_yes", name: "SPDR S&P 500", px: 505.5, held: 1000 };
  const prop = (over: Partial<Proposal>): Proposal => ({
    id: "p1", ticker: "SPY", family: "hedge", strategy: "x", shares_held: 1000, target_coverage: 0.5, status: "approved", basis: "market_event",
    market: { source: "polymarket", id: "516710", token_id: "tok" }, direction: "down_on_yes", created_at: "2026-10-03T00:00:00Z", decided_at: null, ...over,
  });
  function api(existing: Proposal[]) {
    const bodies: ProposalBody[] = [];
    const a: BridgeApi = {
      listProposals: async () => existing,
      createProposal: async (b) => { bodies.push(b); return prop({ id: "new", status: "proposed" }); },
      approveProposal: async (id) => prop({ id, status: "approved" }),
      getEquity: async () => { throw new Error("unused"); },
      startBridge: async (b) => ({ bridge_id: `b-${b.proposal_id}` }),
    };
    return { a, bodies };
  }
  it("sends closed_pm_hedge only when opted in (off by default)", async () => {
    const off = api([]);
    await startRealBridge(q, eq, "100%", off.a);
    assert.equal("closed_pm_hedge" in off.bodies[0], false);
    const on = api([]);
    await startRealBridge(q, eq, "100%", on.a, null, { closedPmHedge: true });
    assert.equal((on.bodies[0] as { closed_pm_hedge?: boolean }).closed_pm_hedge, true);
  });
  it("never reuses an approval made with the other hedge A choice", async () => {
    const plain = prop({ id: "plain" }), withA = prop({ id: "withA", closed_pm_hedge: true });
    assert.equal((await startRealBridge(q, eq, "100%", api([withA]).a)).bridgeId, "b-new");
    assert.equal((await startRealBridge(q, eq, "100%", api([plain, withA]).a)).bridgeId, "b-plain");
    assert.equal((await startRealBridge(q, eq, "100%", api([plain, withA]).a, null, { closedPmHedge: true })).bridgeId, "b-withA");
    assert.equal((await startRealBridge(q, eq, "100%", api([plain]).a, null, { closedPmHedge: true })).bridgeId, "b-new");
  });
});

describe("superseded staged plans fold into one line", () => {
  it("lists live and filled plans; counts cancelled / skipped ones by reason", async () => {
    const { splitOrders } = await import("../src/lib/closed.ts");
    const o = (id: string, status: string, reason: string | null = null, filled_qty = 0) =>
      ({ id, status, reason, filled_qty, qty: 1, session_target: "pre_market", execute_at: "2025-04-07T08:00:00Z" }) as StagedOrder;
    const r = splitOrders([o("a", "approved"), o("b", "cancelled", "PM_REVERTED"), o("c", "cancelled", "PM_REVERTED"), o("d", "skipped", "ALREADY_HEDGED"), o("e", "cancelled", "USER_CANCELLED", 5)]);
    assert.deepEqual(r.active.map((x) => x.id), ["a", "e"]);
    assert.equal(r.folded, 3);
    assert.equal(r.foldedText, "2 cancelled (pm reverted) · 1 skipped (already hedged)");
    assert.deepEqual(splitOrders([o("a", "filled")]), { active: [o("a", "filled")], folded: 0, foldedText: null });
  });
});

describe("fix round: reuse, exposure total, stale gap, hedge A totals", () => {
  it("never reuses a bridge started under the other hedge A choice", () => {
    const withA = { id: "live:a", kind: "live", q: { id: "m1" }, eq: { t: "SPY" }, pmHedge: true };
    const plain = { id: "live:p", kind: "live", q: { id: "m1" }, eq: { t: "SPY" } };
    const opp = { id: "live:o", kind: "live", mode: "opportunity", q: { id: "m1" }, eq: { t: "SPY" } };
    assert.equal(reusableBridge([withA], "m1", "SPY", false), undefined);
    assert.equal(reusableBridge([plain], "m1", "SPY", true), undefined);
    assert.equal(reusableBridge([withA, plain], "m1", "SPY", false)?.id, "live:p");
    assert.equal(reusableBridge([withA, plain], "m1", "SPY", true)?.id, "live:a");
    assert.equal(reusableBridge([opp], "m1", "SPY", false), undefined);
    assert.equal(reusableBridge([{ ...plain, kind: "demo" }], "m1", "SPY", false), undefined);
  });

  it("the exposure total is labelled unvalidated unless every row is validated, carries a band, and counts a position once", () => {
    const pooled: GapView = { ...validatedGap, rate_source: "pooled", validated: false, status: "unvalidated estimate", band: [-20, 5], bp: -10 };
    const h = (over: Partial<ExposureRowLite> = {}): ExposureRowLite => ({ kind: "holding", ticker: "SPY", marketId: "m1", value: 100_000, gap: validatedGap, replay: false, ...over });
    const one = exposureTotal([h()])!;
    assert.equal(one.validated, true);
    assert.equal(Math.round(one.usd), -1288);
    assert.deepEqual([Math.round(one.lo!), Math.round(one.hi!)], [-2104, -472]);
    const mixed = exposureTotal([h(), h({ ticker: "TLT", marketId: "m2", gap: pooled })])!;
    assert.equal(mixed.validated, false);
    assert.equal(Math.round(mixed.usd), -1288 - 100);
    // A live bridge on the same ticker and market as a holding is the same position: counted once.
    const dup = exposureTotal([h(), h({ kind: "bridge" })])!;
    assert.equal(dup.rows, 1);
    assert.equal(exposureTotal([h({ kind: "bridge", ticker: "IWM", marketId: "m3" }), h()])!.rows, 2);
    assert.equal(exposureTotal([h({ replay: true })]), null);
    assert.equal(exposureTotal([h({ gap: { ...validatedGap, band: null } })])!.lo, null);
  });

  it("a kept gap from an earlier closure is not shown as this closure's expected gap", () => {
    const inactive = { bp: null, active: false, n: 0, rate_source: "market" };
    const last = { ...validatedGap, at: "2025-04-05T18:00:05Z" };
    // Next closure (began after the kept gap): no move yet, so the inactive current gap, not the old one.
    assert.equal(currentGap(inactive, last, true, "2025-04-07T20:00:00Z").gap?.bp, null);
    assert.equal(currentGap(inactive, last, true, null).gap?.bp, null);
    // Same closure: the kept gap stands.
    assert.equal(currentGap(inactive, last, true, "2025-04-04T20:00:00Z").gap?.bp, -128.8);
    // After the open: the gap it expected, labelled as past.
    assert.deepEqual([currentGap(inactive, last, false, null).gap?.bp, currentGap(inactive, last, false, null).past], [-128.8, true]);
    assert.equal(currentGap({ ...validatedGap, bp: -50 }, last, true, null).gap?.bp, -50);
  });

  it("with hedge A on, the hedged total is shown without it and again with the labelled estimate", () => {
    const p: ClosurePnl = {
      since: null, s_close: 500, s_now: 490, shares_held: 1000, unhedged_usd: -10000, carried_hedge_shares: 0, carried_hedge_usd: 0,
      staged_short_shares: 200, staged_usd: 1000, algo_short_shares: 0, algo_usd: 0, hedge_a_usd: 300, hedge_a_estimate: true,
      hedged_usd: -8700, vs_no_hedge_usd: 1300, price_source: "recorded",
    };
    const t = pnlTotals(p);
    assert.equal(t.length, 2);
    assert.deepEqual([t[0].v, t[1].v], [-9000, -8700]);
    assert.match(t[0].k, /without hedge A \(\+\$1,000 vs no hedge\)/);
    assert.match(t[1].k, /hedge A estimate/);
    assert.deepEqual(pnlTotals({ ...p, hedge_a_usd: null, hedge_a_estimate: false, hedged_usd: -9000, vs_no_hedge_usd: 1000 }),
      [{ k: "Hedged total (+$1,000 vs no hedge)", v: -9000 }]);
  });
});
