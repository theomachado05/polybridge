import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { chainLabel, flagLabel, greekMarks, hedgeNotes, hedgeRows, ladder, legLine, markLine, optionFillBadge, sideCells } from "../src/lib/optionsView.ts";
import type { ChainContract, HedgeQuoteOut, LiveChainOut } from "../src/lib/api.ts";

const c = (strike: number, right: "call" | "put", over: Partial<ChainContract> = {}): ChainContract => ({
  ticker: `O:SPY261005${right === "call" ? "C" : "P"}00${strike}000`, strike, right, expiry: "2026-10-05", bid: 1, ask: 1.04, mid: 1.02,
  quote_source: "massive_last_nbbo", mark_source: "quote", volume: 12034, open_interest: 2043, iv: 0.1012, delta: right === "call" ? 0.68 : -0.29,
  greeks_source: "massive", stale: false, liquidity_flags: [], ...over,
});
const CHAIN: LiveChainOut = {
  underlying: "SPY", available: true, market_open: false, expiry: "2026-10-05", dte: 2, n_contracts: 6,
  underlying_price: { price: 769.64, source: "massive_option_snapshot" }, snapshot_label: "last close snapshot (market closed)",
  contracts: [c(767, "call"), c(767, "put"), c(770, "call"), c(770, "put"), c(773, "call"), c(773, "put", { stale: true, stale_reason: "old quote", liquidity_flags: ["low_open_interest"] })],
  freshness: { n_quoted: 6, n_stale: 0 },
};

describe("strike ladder", () => {
  it("one row per strike, ascending, ATM nearest spot, ITM sides marked", () => {
    const rows = ladder(CHAIN);
    assert.deepEqual(rows.map((r) => r.strike), [767, 770, 773]);
    assert.deepEqual(rows.map((r) => r.atm), [false, true, false]);
    assert.deepEqual(rows.map((r) => r.callItm), [true, false, false]);
    assert.deepEqual(rows.map((r) => r.putItm), [false, true, true]);
    assert.ok(rows.every((r) => r.call && r.put));
    assert.deepEqual(ladder(null), []);
  });
  it("cells with source, liquidity flags and staleness", () => {
    const x = sideCells(CHAIN.contracts[0]);
    assert.deepEqual([x.bid, x.ask, x.iv, x.delta, x.oi, x.vol], ["1.00", "1.04", "10.1%", "0.68", "2,043", "12,034"]);
    assert.match(x.title, /last NBBO \(15-min delayed\)/);
    const st = sideCells(CHAIN.contracts[5]);
    assert.equal(st.stale, true);
    assert.match(st.title, /low OI/);
    assert.match(st.title, /stale: old quote/);
    assert.equal(sideCells(null).bid, "n/a");
  });
  it("computed IV and delta are marked visibly, Massive's are not", () => {
    assert.deepEqual(sideCells(CHAIN.contracts[0]).marks, { iv: "", delta: "" });
    assert.deepEqual(greekMarks(c(770, "put", { iv_source: "computed", greeks_source: "computed" })), { iv: "c", delta: "c" });
    assert.deepEqual(greekMarks(c(770, "put", { iv_source: "massive", greeks_source: "massive+computed" })), { iv: "", delta: "c*" });
    assert.deepEqual(greekMarks(c(770, "put", { iv: null, delta: null, iv_source: null, greeks_source: null })), { iv: "", delta: "" });
    assert.match(sideCells(c(770, "put", { iv_source: "computed", greeks_source: "computed" })).title, /IV computed · greeks computed/);
  });
  it("the fill tag follows the account's options_supported", () => {
    assert.equal(optionFillBadge({ broker: "webull-paper", options_supported: false }).text, "simulated fills");
    const wb = optionFillBadge({ broker: "webull-paper", options_supported: true, options_route: "webull-paper" });
    assert.deepEqual([wb.text, wb.tone], ["Webull paper fills", "paper"]);
    assert.equal(optionFillBadge({ broker: "sim" }).text, "simulated fills");
    assert.equal(optionFillBadge(null).tone, "neutral");
  });
  it("labels a closed market as the last close, an open one as delayed NBBO", () => {
    assert.equal(chainLabel(CHAIN).text, "last close · 6/6 quoted");
    assert.equal(chainLabel({ ...CHAIN, market_open: true, freshness: { n_quoted: 6, n_stale: 2 } }).text, "delayed NBBO · 6/6 quoted · 2 stale");
    assert.equal(chainLabel({ ...CHAIN, available: false, reason: "no key", contracts: [] }).text, "chain unavailable");
  });
});

const leg = (over: Record<string, unknown>) => ({ ticker: "O:SPY261014P00731000", right: "put", strike: 731, expiry: "2026-10-14", side: "buy", contracts: 10, bid: 0.38, ask: 0.39, mid: 0.385, spread_source: "nbbo", ...over });
const HQ: HedgeQuoteOut = {
  ticker: "SPY", shares: 1000, horizon_days: 30, protection_pct: 0.05, available: true, market_open: false, expiry: "2026-10-14", expiry_covers_horizon: false,
  assumptions: { borrow_rate_annual: 0.003, borrow_rate_assumed: true },
  ranking: { by: "expected_cost_bp", order: ["protective_put", "put_spread", "collar", "short_stock"], cheapest: "protective_put" },
  strategies: {
    short_stock: { available: true, upfront_usd: 0, upfront_bp: 0, expected_cost_usd: 326.77, expected_cost_bp: 4.2458, hedge_ratio: 1, liquidity: "liquid", liquidity_flags: ["borrow_rate_assumed"],
      protection: { floor_price: 769.64, floor_pct: 0 }, upside: { cap_price: 769.64, cap_pct: 0 }, capital: { cash_upfront_usd: 0, margin_initial_usd: 384820 } },
    protective_put: { available: true, legs: [leg({}) as never], upfront_usd: 396.5, upfront_bp: 5.15, expected_cost_usd: 11.5, expected_cost_bp: 0.1494, hedge_ratio: 0.0397, liquidity: "thin",
      liquidity_flags: ["low_open_interest", "size_vs_open_interest"], protection: { floor_price: 731, floor_pct: -0.0502 }, upside: { cap_price: null }, capital: { cash_upfront_usd: 396.5, margin_initial_usd: 0 } },
    collar: { available: true, legs: [leg({}) as never, leg({ ticker: "O:SPY261014C00791000", right: "call", strike: 791, side: "sell", bid: 0.38, ask: 0.4, mid: 0.39 }) as never], upfront_usd: 23, upfront_bp: 0.2988,
      expected_cost_usd: 28, expected_cost_bp: 0.3638, liquidity: "thin", protection: { floor_price: 731, floor_pct: -0.0502 }, upside: { cap_price: 791, cap_pct: 0.0277 } },
    put_spread: { available: false, reason: "no listed lower strike" },
  },
};

describe("hedge-instrument comparison", () => {
  it("four rows in a fixed order, each with its rank by friction", () => {
    const rows = hedgeRows(HQ);
    assert.deepEqual(rows.map((r) => r.id), ["short_stock", "protective_put", "collar", "put_spread"]);
    assert.deepEqual(rows.map((r) => r.rank), [4, 1, 3, 2]);
    assert.deepEqual(rows.map((r) => r.cheapest), [false, true, false, false]);
  });
  it("costs in $ and bp, protection, upside, capital and liquidity flags", () => {
    const [ss, pp, col, ps] = hedgeRows(HQ);
    assert.deepEqual([ss.upfront, ss.expected, ss.expectedBp], ["$0", "$327", "4.25 bp"]);
    assert.equal(ss.capital, "$384,820 initial margin");
    assert.equal(ss.flags[0], "borrow rate assumed");
    assert.deepEqual([pp.upfront, pp.upfrontBp, pp.expectedBp], ["$397", "5.2 bp", "0.15 bp"]);
    assert.equal(pp.protection, "floor 731.00 (-5.0%)");
    assert.equal(pp.upside, "uncapped");
    assert.equal(pp.liquidity.text, "thin");
    assert.deepEqual(pp.flags, ["low OI", "size vs OI"]);
    assert.equal(col.upside, "capped at 791.00 (+2.8%)");
    assert.equal(col.legs.length, 2);
    assert.equal(ps.available, false);
    assert.equal(ps.reason, "no listed lower strike");
  });
  it("leg lines show bid × ask with their source", () => {
    assert.equal(legLine(leg({}) as never), "+10 put 731 2026-10-14 · bid 0.38 × ask 0.39 (NBBO) · mid 0.39");
    assert.match(legLine(leg({ side: "sell", spread_source: "estimated", stale: true }) as never), /^−10 .*estimated spread.*stale$/);
  });
  it("notes say closed market, horizon not covered, borrow assumed, and what the ranking ignores", () => {
    const n = hedgeNotes(HQ);
    assert.equal(n.length, 4);
    assert.match(n[0], /Market closed/);
    assert.match(n[1], /2026-10-14 and would need rolling/);
    assert.match(n[2], /0\.30%\/yr/);
    assert.match(n[3], /ignores the upside/);
    assert.equal(flagLabel("no_volume_last_session"), "no volume");
  });
});

describe("leg marks", () => {
  it("mark ± half spread with its source; stale and missing marks say so", () => {
    const m = markLine({ contract: "O:SPY261014P00731000", available: true, mark: 0.385, half_spread: 0.005, spread_source: "nbbo", stale: false, market_open: true, as_of_label: "session quote (delayed feed)" });
    assert.equal(m.text, "mark 0.39 ± 0.01 · NBBO");
    assert.equal(m.tone, "measured");
    assert.equal(markLine({ contract: "x", available: true, mark: 1.2, half_spread: 0.05, spread_source: "estimated", stale: true }).tone, "caution");
    assert.match(markLine({ contract: "x", available: false, reason: "no key" }).text, /no mark \(no key\)/);
    assert.equal(markLine(null).text, "marking…");
  });
  it("a closed market's NBBO mark says last close and is not shown as measured", () => {
    const sat = markLine({ contract: "O:SPY261014P00731000", available: true, mark: 1.23, half_spread: 0.02, spread_source: "nbbo", stale: false, market_open: false, as_of_label: "last close (market closed)" });
    assert.equal(sat.text, "mark 1.23 ± 0.02 · NBBO · last close");
    assert.equal(sat.tone, "sim");
    assert.match(sat.title, /^last close \(market closed\)/);
    assert.equal(markLine({ contract: "x", available: true, mark: 1.23, half_spread: 0.02, spread_source: "nbbo", stale: false, as_of_label: "last close (market closed)" }).tone, "sim");
    assert.equal(markLine({ contract: "x", available: true, mark: 1.23, spread_source: "nbbo", stale: true, market_open: false }).tone, "caution");
  });
});
