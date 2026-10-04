import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  accountPill, accountRows, ackCopy, budgetPhrase, capacityFromLiquidity, capacityFromProposal, capitalFitView, capitalView, evidenceGate,
  evidenceLabelBadge, fillBadges, gateCounts, gateSentence, isEvidenceError, orderRows, pmDepthLine, reconcileView, splitPositions,
  stagedBadges, usd,
} from "../src/lib/risk.ts";
import { bridgeable, markEvidenceRefused, hedgeTerms, prepareHedgeProposal, prepareOpportunityProposal, startOpportunityBridge, startRealBridge, type BridgeApi } from "../src/lib/realBridge.ts";
import { questionFromMarket, type EquityPick } from "../src/lib/markets.ts";
import type { AccountOut, Capacity, CapitalOut, LiquidityEquity, Proposal } from "../src/lib/api.ts";
import { init, reduce, sandboxFills } from "../src/lib/bridgeStream.ts";

const UNVALIDATED = { validated: false, status: "unvalidated estimate", evidence: "No out-of-sample test for this market.", rate_source: "pooled", basis_ticker: "SPY", reasons: ["GAP_POOLED_RATE"] };
const VALIDATED = { validated: true, status: "validated", evidence: "US recession 2025 on SPY: 97/151 out of sample." };

const CAPACITY: Capacity = {
  source: "live", label: "Capacity before approval",
  equity: { ticker: "TLT", available: true, hedge_shares: 500, price: 77.48, hedge_notional_usd: 38740, max_order_shares: 80510, per_day_shares: 478458,
    inside_caps: true, binding: "per_order_open5", est_cost_bp: 0.855, cost: { qty: 500, half_spread_bp: 0.645, impact_bp: 0.21, total_bp: 0.855 },
    orders_at_open_needed: 1, sessions_needed: 1, book_usd_capacity: 12475829.6, book_usd_within_one_session: 74141851.68, spread_bp: 1.29, spread_source: "quote",
    freshness: { age_s: 0, cache_stale: false, staleness: "fresh" }, note: null },
  pm: { available: true, source: "polymarket", depth: { mid: 0.725, buy: { "2c": { contracts: 8103.2, usd: 5970.34 } }, sell: { "2c": { contracts: 4382.87, usd: 3112.65 } } }, max_order_contracts: { buy: 4051, sell: 2191 } },
  capital: { fits: true, checked: true, breaches: [], add_notional: 38740, gross: { now: 0, after: 38740, limit_usd: 500000 }, event: { key: "polymarket:4620900", now: 0, after: 38740, limit_usd: 200000 },
    buying_power: { basis: "notional", required: 38740, available: 2000000 }, limits: { max_gross_hedge_pct: 0.5, max_event_pct: 0.2, reg_t_initial: 0.5, reg_t_maintenance: 0.3, short_put_mode: "cash_secured" } },
};

describe("evidence gate", () => {
  it("needs the acknowledgement only on an unvalidated market, and never upgrades it", () => {
    const u = evidenceGate(UNVALIDATED);
    assert.equal(u.needsAck, true);
    assert.equal(u.validated, false);
    assert.equal(u.badge.text, "unvalidated estimate");
    assert.equal(u.reason, UNVALIDATED.evidence);
    const v = evidenceGate(VALIDATED);
    assert.deepEqual([v.needsAck, v.validated, v.badge.tone], [false, true, "measured"]);
    const n = evidenceGate(null);
    assert.deepEqual([n.known, n.needsAck], [false, false]);
  });
  it("the acknowledgement copy names the ticker and the label decisions will carry", () => {
    const c = ackCopy("TLT");
    assert.match(c, /TLT/);
    assert.match(c, /not passed its out-of-sample test/);
    assert.match(c, /unvalidated \(acknowledged\)/);
    assert.match(ackCopy("NVDA", "opportunity"), /options algo/);
  });
  it("labels every event's evidence string", () => {
    assert.equal(evidenceLabelBadge("validated")!.tone, "measured");
    assert.equal(evidenceLabelBadge("unvalidated (acknowledged)")!.text, "unvalidated · acknowledged");
    assert.equal(evidenceLabelBadge("override")!.text, "override · unvalidated");
    assert.equal(evidenceLabelBadge(null), null);
  });
  it("recognises the backend's evidence refusals", () => {
    assert.equal(isEvidenceError(new Error("EVIDENCE_UNVALIDATED: TLT on polymarket:1 is an unvalidated estimate")), true);
    assert.equal(isEvidenceError(new Error("EVIDENCE_GATE: no plan")), true);
    assert.equal(isEvidenceError(new Error("No replay file configured")), false);
  });
});

describe("gates on fills", () => {
  const capped = { status: "filled", evidence: "unvalidated (acknowledged)", gates: [{ reason: "liquidity_capped", limit: "per_order_open5", limit_qty: 80510.4, capped_from: 90000, rule: "<= 10% of the opening 5-minute volume" }] };
  const refused = { status: "held", reject_reason: "capital_budget: per-event budget", gates: [{ reason: "capital_budget", enforced: true, breaches: ["event_exposure"] }] };
  const advisory = { status: "filled", gates: [{ reason: "capital_budget", enforced: false, breaches: ["gross_hedge_notional"] }] };
  it("badges the evidence label and each gate", () => {
    assert.deepEqual(fillBadges(capped).map((b) => b.text), ["unvalidated · acknowledged", "liquidity capped · 90,000→80,510"]);
    assert.deepEqual(fillBadges(refused).map((b) => b.text), ["capital budget · refused"]);
    assert.deepEqual(fillBadges(advisory).map((b) => b.text), ["capital budget · advisory"]);
    assert.deepEqual(fillBadges({ status: "held", reject_reason: "liquidity_capped: per day (limit 0 shares left)" }).map((b) => b.text), ["liquidity capped"]);
    assert.deepEqual(fillBadges(undefined, "validated").map((b) => b.text), ["validated"]);
  });
  it("explains them in the trade log", () => {
    assert.match(gateSentence(capped), /cut it from 90000 to 80510/);
    assert.match(gateSentence(refused), /Capital budget refused it \(per-event budget\)/);
    assert.match(gateSentence(advisory), /advisory only in the replay sandbox/);
    assert.equal(gateSentence({ status: "filled" }), "");
  });
  it("counts capped and refused orders, never below the summary's counters", () => {
    assert.deepEqual(gateCounts([capped, refused, advisory, undefined]), { liquidity: 1, capital: 1 });
    assert.deepEqual(gateCounts([capped], { liquidity_capped: 3, capital_refused: 2 }), { liquidity: 3, capital: 2 });
  });
  it("badges staged plans by their evidence gate and budget decisions", () => {
    assert.deepEqual(stagedBadges({ evidence_gate: "override", decisions: [{ code: "EVIDENCE_OVERRIDE" }, { code: "LIQUIDITY_CAPPED", detail: "cut to 80,510" }] }).map((b) => b.text), ["override · unvalidated", "liquidity capped"]);
    assert.deepEqual(stagedBadges({ evidence_gate: "validated", reason: "CAPITAL_BUDGET" }).map((b) => b.text), ["validated", "capital budget"]);
    assert.deepEqual(stagedBadges({ decisions: [{ code: "CAPITAL_BUDGET_ADVISORY" }] }).map((b) => b.text), ["capital budget · advisory"]);
  });
});

describe("liquidity & capacity card", () => {
  it("reads a proposal's capacity block: caps, cost, book size, binding limit, sources", () => {
    const v = capacityFromProposal(CAPACITY);
    assert.equal(v.available, true);
    const row = (k: string) => v.rows.find((r) => r.k === k)!;
    assert.equal(row("MAX ORDER").v, "80,510 sh");
    assert.equal(row("MAX POSITION / DAY").v, "478,458 sh");
    assert.equal(row("EST. COST").v, "0.85 bp");
    assert.equal(row("BOOK-SIZE CAPACITY").v, "$12.5M");
    assert.equal(row("SESSIONS NEEDED").v, "1");
    assert.equal(v.binding, "10% of the opening 5-min volume");
    assert.equal(v.verdict.text, "inside the caps");
    assert.ok(v.sources.some((s) => s.includes("Massive last NBBO quote")));
    assert.equal(v.stale, false);
  });
  it("flags a hedge above one order's cap, a stale cache and missing numbers", () => {
    const big = capacityFromProposal({ ...CAPACITY, equity: { ...CAPACITY.equity!, hedge_shares: 200000, inside_caps: false, sessions_needed: 1, orders_at_open_needed: 3, freshness: { age_s: 900, cache_stale: true } } });
    assert.equal(big.verdict.text, "above one order's cap");
    assert.equal(big.rows.find((r) => r.k === "MAX ORDER")!.warn, true);
    assert.equal(big.stale, true);
    const none = capacityFromProposal({ equity: { available: false, reason: "no MASSIVE_API_KEY" } });
    assert.deepEqual([none.available, none.reason, none.verdict.text], [false, "no MASSIVE_API_KEY", "caps unknown"]);
    assert.equal(capacityFromProposal(null).available, false);
  });
  it("reads GET /liquidity/{ticker} for the Bridge screen and the Build preview", () => {
    const spy: LiquidityEquity = { ticker: "SPY", available: true, price: 769.64, adv_shares: 46047314, adv_usd: 35210479442, sigma_daily: 0.0065, spread_bp: 1.69, spread_source: "quote",
      max_order_shares: 124240, max_position_shares: 460473, per_day_shares: 460473, binding: "per_order_open5", est_cost_bp: 4.22, cost: { qty: 124240, half_spread_bp: 0.84, impact_bp: 3.38, total_bp: 4.22 },
      capacity: { coverage: 0.5, book_usd: 191240147.2, book_usd_within_one_session: 708796879.4 }, freshness: { age_s: 0, cache_stale: false, staleness: "fresh" },
      sources: { spread: { source: "quote", phase: "overnight", note: "last quote outside the regular session: its spread may be wider than at the open" } } };
    const v = capacityFromLiquidity(spy, 500);
    assert.equal(v.verdict.text, "hedge inside the caps");
    assert.equal(v.rows.find((r) => r.k === "BOOK-SIZE CAPACITY")!.v, "$191.2M");
    assert.equal(v.rows.find((r) => r.k === "ADV")!.sub, "$35.2B");
    assert.ok(v.sources.some((s) => s.includes("outside the regular session")));
    assert.equal(capacityFromLiquidity(spy, 200000).verdict.text, "hedge above one order's cap");
    assert.equal(capacityFromLiquidity({ ticker: "X", available: false, reason: "no key" }).reason, "no key");
  });
  it("summarises the PM book and the capital fit", () => {
    assert.match(pmDepthLine(CAPACITY)!, /max order 4,051 buy \/ 2,191 sell contracts/);
    const fit = capitalFitView(CAPACITY);
    assert.equal(fit.badge.text, "fits the capital budget");
    assert.ok(fit.lines[0].includes("$38,740") && fit.lines[0].includes("$500,000"));
    const breach = capitalFitView({ capital: { ...CAPACITY.capital!, fits: false, breaches: [{ kind: "event_exposure" }] } });
    assert.equal(breach.badge.text, "breaches the capital budget");
    assert.ok(breach.lines.some((l) => l.startsWith("Breach: per-event budget")));
    assert.equal(capitalFitView({ capital: { fits: null, checked: false, note: "no hedge price yet" } }).lines[0], "no hedge price yet");
  });
});

describe("capital usage and the Webull account", () => {
  const CAP: CapitalOut = { broker: "webull-paper", account_read: true, account_label: "Individual Margin", account_type: "margin", equity: 1_000_000, buying_power: 2_000_000, buying_power_basis: "notional",
    limits: { max_gross_hedge_pct: 0.5, max_event_pct: 0.2, reg_t_initial: 0.5, reg_t_maintenance: 0.3, short_put_mode: "cash_secured" },
    gross_hedge_notional: 253_000, gross_limit_usd: 500_000, equity_hedge_usd: 253_000, staged_pending_usd: 0, option_risk_usd: 0,
    margin: { initial_required: 126_500, maintenance_required: 75_900, excess_over_maintenance: 924_100, rule: "Reg T 50% / 30%" },
    events: [{ event: "polymarket:516710", total_usd: 253_000, limit_usd: 200_000, use_pct: 1.265 }],
    breaches: [{ kind: "event_exposure", event: "polymarket:516710", after_usd: 253_000, limit_usd: 200_000 }] };
  it("tiles, meters and breaches from GET /capital", () => {
    const v = capitalView(CAP);
    assert.equal(v.read, true);
    assert.equal(v.tiles.find((t) => t.k === "GROSS HEDGE NOTIONAL")!.v, "$253,000");
    assert.equal(v.tiles.find((t) => t.k === "MARGIN USED (INITIAL)")!.v, "$126,500");
    assert.equal(v.meters[0].text, "$253,000 of $500,000 · 51%");
    assert.equal(v.events[0].warn, true);
    assert.equal(v.events[0].frac! > 1, true);
    assert.equal(v.breaches[0], "per-event budget (polymarket:516710): $253,000 vs limit $200,000");
    assert.equal(v.status.text, "1 breach");
    const bad = capitalView({ account_read: false, account_checked: true, account_error: "Webull 503", breaches: [{ kind: "account_unreadable" }] });
    assert.deepEqual([bad.read, bad.checked], [false, true]);
    assert.equal(bad.error, "Account unreadable (Webull 503): exposure-increasing orders are refused (fail closed).");
    assert.match(bad.enforcement, /refused until it can be read again/);
  });
  it("'within budget' only on a real read; not checked and stale reads say so", () => {
    assert.deepEqual(capitalView({ ...CAP, breaches: [] }).status, { tone: "measured", text: "within budget" });
    const nc = capitalView({ broker: "fake", account_read: false, account_checked: false, account_error: "the broker returned no account equity", breaches: [] });
    assert.equal(nc.checked, false);
    assert.equal(nc.status.text, "budget not checked");
    assert.equal(nc.status.tone, "neutral");
    assert.match(nc.error!, /^Capital budget not checked \(the broker returned no account equity\)/);
    assert.match(nc.enforcement, /Nothing is enforced/);
    assert.doesNotMatch(nc.enforcement, /fail closed/);
    assert.equal(capitalView({ account_read: false, breaches: [] }).checked, false);
    assert.equal(capitalView({ account_read: false, breaches: [{ kind: "account_unreadable" }] }).status.text, "1 breach");
    const st = capitalView({ ...CAP, breaches: [], account_stale: true, account_age_s: 14.2, account_error: "account read failed (BrokerError)" });
    assert.deepEqual([st.stale?.text, st.stale?.tone, st.status.text], ["stale · 14s old", "caution", "within budget"]);
    assert.match(st.enforcement, /last good read/);
    assert.equal(capitalView(CAP).stale, null);
  });
  it("the budget sentence uses the enforced limits, not constants", () => {
    assert.equal(budgetPhrase(CAP.limits), "gross hedge ≤ 50% of equity, one event ≤ 20%, buying power");
    assert.equal(budgetPhrase({ max_gross_hedge_pct: 0.3, max_event_pct: 0.1 }), "gross hedge ≤ 30% of equity, one event ≤ 10%, buying power");
    assert.equal(budgetPhrase(null), "gross hedge, per-event and buying-power limits");
  });
  it("the account pill says broker, account type and whether the market is open", () => {
    const wb: AccountOut = { broker: "webull-paper", cash: 1e6, equity: 1e6, buying_power: 2e6, currency: "USD", account_label: "Individual Margin", market_open: false, overnight_buying_power: 2e6, day_buying_power: 4e6, option_buying_power: 1e6 };
    assert.equal(accountPill(wb).text, "Webull paper · Individual Margin · market closed");
    assert.equal(accountPill(wb, { equities_open: true }).text, "Webull paper · Individual Margin · market open");
    assert.equal(accountPill({ broker: "sim", cash: 1, equity: 1, buying_power: 1, currency: "USD" }).text, "Simulated account");
    assert.equal(accountPill(null).tone, "demo");
    const rows = accountRows(wb);
    assert.deepEqual(rows.slice(0, 3).map((r) => r.v), ["$1,000,000", "$1,000,000", "$2,000,000"]);
    assert.equal(rows[2].sub, "overnight figure");
    assert.equal(accountRows({ ...wb, buying_power: 3e6 })[2].sub, undefined);
    assert.equal(accountRows({ ...wb, overnight_buying_power: null, buying_power: 4e6 })[2].sub, "intraday figure");
    assert.ok(rows.some((r) => r.k === "DAY BUYING POWER" && r.v === "$4,000,000"));
  });
  it("keeps demo holdings apart from the broker's positions", () => {
    const s = splitPositions([
      { symbol: "TLT", qty: 1000, broker: "demo", account: "demo holdings" },
      { symbol: "SPY", qty: -500, broker: "webull-paper", account: "Webull paper account" },
      { symbol: "IWM", qty: 0, broker: "webull-paper", account: "Webull paper account" },
    ]);
    assert.deepEqual(s.broker.map((p) => p.symbol), ["SPY"]);
    assert.deepEqual(s.demo.map((p) => p.symbol), ["TLT"]);
  });
  it("order history: newest first, origin and the broker's own status word", () => {
    const rows = orderRows([
      { id: "a", symbol: "SPY", side: "sell", qty: 100, status: "filled", broker_status: "FILLED", fill_px: 769.5, created_at: "2026-10-01T14:00:00Z", origin: "polybridge" },
      { id: "b", symbol: "TLT", side: "buy", qty: 50, status: "cancelled", broker_status: "EXPIRED", created_at: "2026-10-02T15:30:00Z", origin: "webull_history" },
    ]);
    assert.deepEqual(rows.map((r) => r.key), ["b", "a"]);
    assert.equal(rows[0].status, "cancelled (EXPIRED)");
    assert.equal(rows[0].origin, "Webull history");
    assert.equal(rows[1].status, "filled");
    assert.equal(rows[1].px, "769.50");
    assert.equal(rows[0].when, "2026-10-02 15:30");
  });
  it("reconciler status in one line", () => {
    assert.equal(reconcileView({ running: true, state: "idle", idle_reason: "market closed", passes: 0, supported: true }).badge.text, "reconciler idle");
    const run = reconcileView({ running: true, state: "running", interval_s: 15, passes: 4, supported: true, last_result: { checked: 2, open_at_webull: 1, updated: 1 } });
    assert.equal(run.badge.text, "reconciling");
    assert.match(run.line, /2 tracked, 1 open at Webull, 1 updated/);
    assert.equal(reconcileView({ supported: false, broker: "sim" }).badge.text, "no reconciler");
    assert.equal(reconcileView(null).badge.text, "reconcile n/a");
  });
  it("formats money compactly and honestly", () => {
    assert.equal(usd(191240147.2), "$191.2M");
    assert.equal(usd(-1234), "−$1,234");
    assert.equal(usd(null), "n/a");
    assert.equal(usd(12500, { compact: true }), "$12.5k");
  });
});

const q = questionFromMarket({ source: "polymarket", id: "m1", question: "Will X happen?", yes_price: 0.4, volume_24h: 1000, end_date: null, url: null, token_id: "tok" });
const eq: EquityPick = { t: "ABNB", move: -3, rev: null, brand: null, why: "", direction: "down_on_yes", name: "Airbnb", px: 130, held: 1200 };
const prop = (over: Partial<Proposal>): Proposal => ({
  id: "p1", ticker: "ABNB", family: "hedge", strategy: "protective_put", shares_held: 1200, target_coverage: 0.5, status: "proposed",
  basis: "market_event", market: { source: "polymarket", id: "m1", token_id: "tok" }, direction: "down_on_yes",
  created_at: "2026-10-03T00:00:00Z", decided_at: null, evidence: UNVALIDATED, ...over,
});
function api(existing: Proposal[]) {
  const calls: string[] = [];
  const bodies: unknown[] = [];
  const a: BridgeApi = {
    listProposals: async () => existing,
    createProposal: async (b) => { calls.push("create"); bodies.push(b); return prop({ id: "new" }); },
    approveProposal: async (id: string, ack?: boolean) => {
      calls.push(`approve:${id}:${ack ? "ack" : "noack"}`);
      if (!ack) throw new Error("EVIDENCE_UNVALIDATED: ABNB on polymarket:m1 is an unvalidated estimate.");
      return prop({ id, status: "approved", ack_unvalidated: true });
    },
    getEquity: async () => { throw new Error("no quote"); },
    startBridge: async (b) => { calls.push(`bridge:${b.proposal_id}:${b.source}`); return { bridge_id: `b-${b.proposal_id}` }; },
  };
  return { a, calls, bodies };
}

describe("approval with the evidence gate", () => {
  it("prepares a pending proposal without approving it, with the override flag when set", async () => {
    const { a, calls, bodies } = api([]);
    const t = hedgeTerms(q, eq, "100%", null, { actOnUnvalidated: true });
    const p = await prepareHedgeProposal(t, a);
    assert.equal(p.status, "proposed");
    assert.deepEqual(calls, ["create"]);
    assert.equal((bodies[0] as { act_on_unvalidated?: boolean }).act_on_unvalidated, true);
  });
  it("reuses a pending proposal only for the same override choice", async () => {
    const pending = prop({ id: "pend", act_on_unvalidated: false });
    const { a, calls } = api([pending]);
    assert.equal((await prepareHedgeProposal(hedgeTerms(q, eq, "100%"), a)).id, "pend");
    assert.equal((await prepareHedgeProposal(hedgeTerms(q, eq, "100%", null, { actOnUnvalidated: true }), a)).id, "new");
    assert.deepEqual(calls, ["create"]);
  });
  it("never reuses a proposal approved without the acknowledgement on an unvalidated market", async () => {
    const stale = prop({ id: "old", status: "approved", ack_unvalidated: false });
    assert.equal(bridgeable(stale), false);
    assert.equal(bridgeable(prop({ status: "approved", ack_unvalidated: true })), true);
    assert.equal(bridgeable(prop({ status: "approved", evidence: VALIDATED })), true);
    const { a, calls } = api([stale]);
    const out = await startRealBridge(q, eq, "100%", a, null, { ackUnvalidated: true });
    assert.equal(out.bridgeId, "b-new");
    assert.deepEqual(calls, ["create", "approve:new:ack", "bridge:new:replay"]);
  });
  it("sends the acknowledgement with the approval, and surfaces the 409 without it", async () => {
    const { a, calls } = api([prop({ id: "pend" })]);
    await assert.rejects(startRealBridge(q, eq, "100%", a), (e: Error) => isEvidenceError(e));
    assert.deepEqual(calls, ["approve:pend:noack"]);
    const ok = await startRealBridge(q, eq, "100%", a, null, { ackUnvalidated: true });
    assert.equal(ok.bridgeId, "b-pend");
  });
  it("a bridge start refused by the evidence gate drops the proposal instead of promising reuse", async () => {
    const flipped = prop({ id: "flip", status: "approved", evidence: VALIDATED, ack_unvalidated: false });
    const { a: base, calls } = api([flipped]);
    const a: BridgeApi = { ...base, startBridge: async (b) => { calls.push(`bridge:${b.proposal_id}:${b.source}`); throw new Error("EVIDENCE_UNVALIDATED: ABNB on polymarket:m1 is an unvalidated estimate"); } };
    await assert.rejects(startRealBridge(q, eq, "100%", a), (e: Error) => isEvidenceError(e) && /not reused/.test(e.message) && !/reused on the next try/.test(e.message));
    assert.deepEqual(calls, ["bridge:flip:replay"]);
    assert.equal(bridgeable(flipped), false);
    assert.equal((await prepareHedgeProposal(hedgeTerms(q, eq, "100%"), a)).id, "new");
  });
  it("any other start failure keeps the approved proposal for the next try", async () => {
    const appr = prop({ id: "keep", status: "approved", evidence: VALIDATED });
    const { a: base } = api([appr]);
    const a: BridgeApi = { ...base, startBridge: async () => { throw new Error("503 engine not loaded"); } };
    await assert.rejects(startRealBridge(q, eq, "100%", a), /proposal keep stays approved and is reused on the next try/);
    assert.equal(bridgeable(appr), true);
    markEvidenceRefused("keep");
    assert.equal(bridgeable(appr), false);
  });
  it("the acknowledgement names the closed-market override when it is on", () => {
    assert.doesNotMatch(ackCopy("TLT"), /override/);
    assert.match(ackCopy("TLT", "hedge", { override: true }), /also confirms the closed-market override.*labelled “override”/);
    assert.doesNotMatch(ackCopy("NVDA", "opportunity", { override: true }), /override/);
  });
  it("opportunity proposals go through the same gate", async () => {
    const fit = { family: "binary_vs_spread_arb", preset_index: 3 };
    const { a, calls } = api([]);
    const p = await prepareOpportunityProposal(q, "NVDA", fit, a);
    assert.equal(p.status, "proposed");
    const { a: a2, calls: c2 } = api([prop({ id: "opp", ticker: "NVDA", family: "opportunity", algo: { family: fit.family, preset_index: 3 }, max_contracts: 10, max_notional: 10_000 })]);
    const r = await startOpportunityBridge(q, "NVDA", fit, a2, undefined, { ackUnvalidated: true });
    assert.equal(r.bridgeId, "b-opp");
    assert.deepEqual(calls, ["create"]);
    assert.equal(c2[0], "approve:opp:ack");
  });
});

describe("stream: evidence and gates on events", () => {
  it("keeps each decision's evidence label, each fill's gates and the staged refusal", () => {
    let s = reduce(init, { k: "open" });
    s = reduce(s, { k: "decision", d: { action: "order", reason: "rebalance", order_qty: 600, target_hedge: 600, current_hedge: 0, latency_ns: 900, evidence: "unvalidated (acknowledged)" } });
    s = reduce(s, { k: "fill", f: { status: "filled", qty: 500, filled_qty: 500, fill_px: 77.5, scope: "replay_sandbox", side: "sell", gates: [{ reason: "liquidity_capped", limit_qty: 500, capped_from: 600 }], evidence: "unvalidated (acknowledged)" } });
    assert.equal(s.log[0].evidence, "unvalidated (acknowledged)");
    assert.equal(s.log[0].fill!.gates![0].reason, "liquidity_capped");
    const sf = sandboxFills(s.log);
    assert.equal(sf[0].gates[0].capped_from, 600);
    assert.equal(sf[0].evidence, "unvalidated (acknowledged)");
    s = reduce(s, { k: "staged", d: { event: "refused", reason: "EVIDENCE_GATE", detail: "TLT on polymarket:1 is unvalidated", evidence: "unvalidated estimate" } });
    assert.deepEqual(s.refusal, { reason: "EVIDENCE_GATE", detail: "TLT on polymarket:1 is unvalidated", evidence: "unvalidated estimate" });
  });
});
