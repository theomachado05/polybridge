#include "family_helpers.hpp"

using namespace hctest;
using F = hedgecore::algos::ClosedSessionHedge;

namespace {
constexpr std::int64_t kFri1500 = 1790967600LL * kSec;   // 2026-10-02 15:00 EDT, regular session
constexpr std::int64_t kSat1200 = 1791043200LL * kSec;   // 2026-10-03 12:00 EDT, Saturday
constexpr std::int64_t kMon0930 = 1791207000LL * kSec;   // 2026-10-05 09:30 EDT, session open
constexpr std::int64_t kThanks = 1795705200LL * kSec;    // 2026-11-26 10:00 EST, Thanksgiving (NYSE closed)
Intent tick(F& a, std::int64_t ts, double p, double u = 100.0) { return a.on_tick(pm(ts, p, 0.005, u), ts); }
// 0.5 * 1000 shares * $100 * 7.52 bp/pp * 1e-2 = 3,760 contracts.
constexpr double kDefaultTarget = 3760.0;
}  // namespace

TEST(ClosedSessionHedge, ClosedMarketBuysAdverseYesSizedByRate) {
  F a(params<F>(), held(1000));
  const Intent i = tick(a, kSat1200, 0.30);
  ASSERT_TRUE(is_order(i));
  EXPECT_EQ(i.instrument, Instrument::PredYes);
  EXPECT_EQ(i.side, +1);
  EXPECT_DOUBLE_EQ(i.qty, kDefaultTarget);
  EXPECT_TRUE(std::isnan(i.limit_px));  // marketable
  EXPECT_EQ(i.venue, Venue::Poly);
  EXPECT_EQ(i.reason, rc(Rc::Rebalance));
  EXPECT_DOUBLE_EQ(i.signal, 0.0);  // no PM move since the close yet
}

TEST(ClosedSessionHedge, SizingOffsetsTheExpectedEquityMovePerPoint) {
  // A 1 pp adverse move: expected equity loss = N_cov * S * r * 1e-4; the YES leg gains $0.01 per contract.
  const double n_cov = 0.5 * 1000, s = 100.0, r = 7.52;
  EXPECT_NEAR(kDefaultTarget * 0.01, n_cov * s * r * 1e-4, 0.01);
  F half(params<F>({{"rate_scale", 0.5}}), held(1000));
  EXPECT_DOUBLE_EQ(tick(half, kSat1200, 0.30).qty, 1880.0);
  F full(params<F>({{"coverage", 1.0}, {"rate_bp_per_pp", 10.0}}), held(1000));
  EXPECT_DOUBLE_EQ(tick(full, kSat1200, 0.30, 50.0).qty, 5000.0);  // 1000 * 50 * 10 * 1e-2
}

TEST(ClosedSessionHedge, OpenSessionDoesNotTradeThePmLeg) {
  F a(params<F>(), held(1000));
  const Intent i = tick(a, kFri1500, 0.30);  // same quote as the closed test, but in the regular session
  EXPECT_FALSE(is_order(i));
  EXPECT_EQ(i.reason, rc(Rc::OutOfSession));
  F h(params<F>(), held(1000));
  EXPECT_TRUE(is_order(tick(h, kThanks, 0.30)));  // a weekday NYSE holiday is closed
}

TEST(ClosedSessionHedge, HandoffAtOpenUnwindsTheYesLeg) {
  F a(params<F>(), held(1000));
  ASSERT_TRUE(is_order(tick(a, kSat1200, 0.30)));
  a.on_fill(Instrument::PredYes, kDefaultTarget, 0.305);
  EXPECT_EQ(tick(a, kSat1200 + kSec, 0.31).reason, rc(Rc::ZeroTarget));  // fully hedged, S unchanged
  const Intent u = tick(a, kMon0930, 0.40);
  ASSERT_TRUE(is_order(u));
  EXPECT_EQ(u.instrument, Instrument::PredYes);
  EXPECT_EQ(u.side, -1);
  EXPECT_DOUBLE_EQ(u.qty, kDefaultTarget);
  EXPECT_EQ(u.reason, rc(Rc::Handoff));
  EXPECT_TRUE(is_order(tick(a, kMon0930 + kSec, 0.40)));  // not filled yet: re-sent
  a.on_fill(Instrument::PredYes, -kDefaultTarget, 0.395);
  const Intent after = tick(a, kMon0930 + 2 * kSec, 0.40);
  EXPECT_FALSE(is_order(after));  // handoff_equity = 0: the staged equity orders own the equity leg
  EXPECT_EQ(after.reason, rc(Rc::OutOfSession));
}

TEST(ClosedSessionHedge, HandoffMovesTheHedgeIntoTheEquityWhenEnabled) {
  F a(params<F>({{"handoff_equity", 1}}), held(1000));
  ASSERT_TRUE(is_order(tick(a, kSat1200, 0.30)));
  a.on_fill(Instrument::PredYes, kDefaultTarget, 0.305);
  ASSERT_EQ(tick(a, kMon0930, 0.30).reason, rc(Rc::Handoff));  // step 1: unwind YES first
  a.on_fill(Instrument::PredYes, -kDefaultTarget, 0.295);
  const Intent e = tick(a, kMon0930 + kSec, 0.30);  // step 2: equity at the DeltaBridge target
  ASSERT_TRUE(is_order(e));
  EXPECT_EQ(e.instrument, Instrument::Equity);
  EXPECT_EQ(e.side, -1);
  EXPECT_DOUBLE_EQ(e.qty, 150.0);  // round(0.5 * 1000 * 0.30)
  EXPECT_EQ(e.reason, rc(Rc::Handoff));
  a.on_fill(Instrument::Equity, -150, 99.99);
  const Intent r = tick(a, kMon0930 + 2 * kSec, 0.50);  // later in-session moves are ordinary rebalances
  ASSERT_TRUE(is_order(r));
  EXPECT_DOUBLE_EQ(r.qty, 100.0);
  EXPECT_EQ(r.reason, rc(Rc::Rebalance));
}

TEST(ClosedSessionHedge, CoverageIsCombinedAcrossEquityAndPmLegs) {
  F part(params<F>(), held(1000, -300));  // a 300-share equity short already covers 300 of c * N = 500
  EXPECT_DOUBLE_EQ(tick(part, kSat1200, 0.30).qty, 1504.0);  // 200 * 100 * 7.52 * 1e-2
  F full(params<F>(), held(1000, -600));
  const Intent i = tick(full, kSat1200, 0.30);
  EXPECT_FALSE(is_order(i));
  EXPECT_EQ(i.reason, rc(Rc::ZeroTarget));
}

TEST(ClosedSessionHedge, NotionalCapLimitsYesDollars) {
  F a(params<F>({{"max_notional", 1000}}), held(1000));
  const Intent i = tick(a, kSat1200, 0.30);
  ASSERT_TRUE(is_order(i));
  EXPECT_DOUBLE_EQ(i.qty, 3278.0);  // floor(1000 / 0.305)
  EXPECT_EQ(i.reason, rc(Rc::NotionalCapped));
  a.on_fill(Instrument::PredYes, 3278, 0.305);
  EXPECT_EQ(tick(a, kSat1200 + kSec, 0.30).reason, rc(Rc::NotionalCapped));
}

TEST(ClosedSessionHedge, PositionCapKeepsPayoffWithinCoveredValue) {
  // r_eff = 100 * 5 = 500 bp/pp would size 250,000 contracts; payoff is capped at N_cov * S = $50,000.
  F a(params<F>({{"rate_bp_per_pp", 100}, {"rate_scale", 5}, {"max_notional", 0}}), held(1000));
  const Intent i = tick(a, kSat1200, 0.30);
  ASSERT_TRUE(is_order(i));
  EXPECT_DOUBLE_EQ(i.qty, 50000.0);
  EXPECT_EQ(i.reason, rc(Rc::PositionCapped));
}

TEST(ClosedSessionHedge, BandAndResizeOnPriceChange) {
  F a(params<F>(), held(1000));
  ASSERT_TRUE(is_order(tick(a, kSat1200, 0.30)));
  a.on_fill(Instrument::PredYes, kDefaultTarget, 0.305);
  EXPECT_EQ(tick(a, kSat1200 + kSec, 0.30, 100.1).reason, rc(Rc::InsideBand));  // target 3764: |4| < 50
  const Intent up = tick(a, kSat1200 + 2 * kSec, 0.30, 102.0);                   // target 3835
  ASSERT_TRUE(is_order(up));
  EXPECT_EQ(up.side, +1);
  EXPECT_DOUBLE_EQ(up.qty, 75.0);
  const Intent down = tick(a, kSat1200 + 3 * kSec, 0.30, 90.0);  // target 3384: reduce, no fee gate
  ASSERT_TRUE(is_order(down));
  EXPECT_EQ(down.side, -1);
  EXPECT_DOUBLE_EQ(down.qty, 376.0);
}

TEST(ClosedSessionHedge, FeeGatePricesTheRoundTrip) {
  // Benefit q * 0.01 * exp_move_pp against cost q * 2 * half-spread (0.005), Polymarket taker fee 0.
  F no(params<F>({{"exp_move_pp", 0.5}}), held(1000));
  EXPECT_EQ(tick(no, kSat1200, 0.30).reason, rc(Rc::BelowFees));
  F off(params<F>({{"exp_move_pp", 0}}), held(1000));
  EXPECT_TRUE(is_order(tick(off, kSat1200, 0.30)));
}

TEST(ClosedSessionHedge, ExpectedGapSignalTracksPmMoveSinceClose) {
  F a(params<F>(), held(1000));
  EXPECT_FALSE(is_order(tick(a, kFri1500, 0.30)));  // last in-session mark: 0.30
  const Intent i = tick(a, kSat1200, 0.35);
  ASSERT_TRUE(is_order(i));
  EXPECT_NEAR(i.signal, 7.52 * 5.0, 1e-9);  // r * 5 pp = 37.6 bp expected adverse gap
}

TEST(ClosedSessionHedge, PreExistingYesLegIsUnwoundAtOpen) {
  Position pos = held(1000);
  pos.pred_yes = 500;
  F a(params<F>(), pos);
  const Intent i = tick(a, kMon0930, 0.30);
  ASSERT_TRUE(is_order(i));
  EXPECT_EQ(i.side, -1);
  EXPECT_DOUBLE_EQ(i.qty, 500.0);
  EXPECT_EQ(i.reason, rc(Rc::Handoff));
}

TEST(ClosedSessionHedge, RepeatedYesRejectsBackOff) {
  F a(params<F>(), held(1000));
  ASSERT_TRUE(is_order(tick(a, kSat1200, 0.30)));
  a.on_reject(Instrument::PredYes);
  ASSERT_TRUE(is_order(tick(a, kSat1200, 0.30)));  // first reject: re-sent at once
  a.on_reject(Instrument::PredYes);
  EXPECT_EQ(tick(a, kSat1200, 0.30).reason, rc(Rc::Cooldown));  // second: wait 1 s
  EXPECT_TRUE(is_order(tick(a, kSat1200 + kSec, 0.30)));
}

TEST(ClosedSessionHedge, NaNAndStaleSafety) {
  expect_nan_and_stale_safety<F>(params<F>(), held(1000));
  F a(params<F>(), held(1000));
  MarketTick t = pm(kSat1200, 0.30);
  t.under_px = t.under_bid = t.under_ask = NaN;  // cannot size without S
  EXPECT_EQ(a.on_tick(t, kSat1200).reason, rc(Rc::SignalMissing));
  MarketTick q = pm(kSat1200, 0.30);
  q.yes_bid = q.yes_ask = NaN;  // no YES price: the notional cap cannot be measured
  EXPECT_EQ(a.on_tick(q, kSat1200).reason, rc(Rc::NotionalUnknown));
  F nocap(params<F>({{"max_notional", 0}}), held(1000));
  EXPECT_EQ(nocap.on_tick(q, kSat1200).reason, rc(Rc::FeeUnknown));
  F bad(params<F>(), held(1000));
  bad.on_fill(Instrument::PredYes, NaN, 0.3);
  EXPECT_EQ(tick(bad, kSat1200, 0.30).reason, rc(Rc::InvalidState));
  Position nanpos = held(1000);
  nanpos.pred_yes = NaN;
  F np(params<F>(), nanpos);
  EXPECT_EQ(tick(np, kSat1200, 0.30).reason, rc(Rc::InvalidParams));
  F open(params<F>({{"handoff_equity", 1}}), held(1000));
  MarketTick o = pm(kMon0930, 0.30);
  o.yes_bid = o.yes_ask = NaN;
  EXPECT_EQ(open.on_tick(o, kMon0930).reason, rc(Rc::SignalMissing));  // no probability for the equity target
}

TEST(ClosedSessionHedge, RunsThroughAnyAlgo) {
  AnyAlgo a = make_algo("closed_session_hedge", F::spec().defaults(), held(1000));
  const Intent i = on_tick(a, pm(kSat1200, 0.30), kSat1200);
  ASSERT_TRUE(is_order(i));
  EXPECT_EQ(i.instrument, Instrument::PredYes);
  on_fill(a, i.instrument, i.qty, 0.305);
  EXPECT_EQ(on_tick(a, pm(kMon0930, 0.30), kMon0930).reason, rc(Rc::Handoff));
}

TEST(ClosedSessionHedge, SessionEdgeIsExactToTheSecond) {
  // The calendar check is cached per tick minute; 09:29:59 is still closed and 09:30:00 is open.
  F a(params<F>(), held(1000));
  const Intent pre = tick(a, kMon0930 - kSec, 0.30);
  ASSERT_TRUE(is_order(pre));
  EXPECT_EQ(pre.side, +1);
  a.on_fill(Instrument::PredYes, pre.qty, 0.305);
  const Intent open = tick(a, kMon0930, 0.30);
  ASSERT_TRUE(is_order(open));
  EXPECT_EQ(open.reason, rc(Rc::Handoff));
  a.on_fill(Instrument::PredYes, -open.qty, 0.295);
  const std::int64_t close = kMon0930 + (6 * 3600 + 30 * 60) * kSec;  // 16:00 EDT
  EXPECT_EQ(tick(a, close - kSec, 0.30).reason, rc(Rc::OutOfSession));
  EXPECT_TRUE(is_order(tick(a, close, 0.30)));  // closed again at 16:00:00
}

namespace {
// ns of an ET wall-clock time; utc_off_h is 4 (EDT) or 5 (EST).
std::int64_t et(int y, unsigned m, unsigned d, int h, int mi, int s, int utc_off_h) {
  return ((hedgecore::days_from_civil(y, m, d) * 86400) + (h + utc_off_h) * 3600 + mi * 60 + s) * kSec;
}
}  // namespace

TEST(ClosedSessionHedge, EarlyCloseDayIsClosedFrom1300) {
  // 2026-11-27, the Friday after Thanksgiving: regular session 09:30-13:00 EST.
  F a(params<F>({{"handoff_equity", 1}}), held(1000));
  const Intent thu = tick(a, et(2026, 11, 26, 10, 0, 0, 5), 0.30);  // Thanksgiving: closed, YES bought
  ASSERT_TRUE(is_order(thu));
  a.on_fill(Instrument::PredYes, thu.qty, 0.305);
  const Intent open = tick(a, et(2026, 11, 27, 9, 30, 0, 5), 0.30);  // open: handoff unwind
  ASSERT_EQ(open.reason, rc(Rc::Handoff));
  a.on_fill(Instrument::PredYes, -open.qty, 0.295);
  const Intent eq = tick(a, et(2026, 11, 27, 12, 59, 0, 5), 0.30);  // still open: the equity handoff
  ASSERT_TRUE(is_order(eq));
  EXPECT_EQ(eq.instrument, Instrument::Equity);
  a.on_fill(Instrument::Equity, -eq.qty, 100.0);
  EXPECT_EQ(tick(a, et(2026, 11, 27, 12, 59, 59, 5), 0.30).reason, rc(Rc::InsideBand));  // in session, hedged
  // 13:00:00 is the early close: closed, so the PM leg is rebuilt for the remaining uncovered shares, never an equity
  // order and never a handoff.
  const Intent c = tick(a, et(2026, 11, 27, 13, 0, 0, 5), 0.30);
  ASSERT_TRUE(is_order(c));
  EXPECT_EQ(c.instrument, Instrument::PredYes);
  EXPECT_EQ(c.side, +1);
  EXPECT_EQ(c.reason, rc(Rc::Rebalance));
  EXPECT_DOUBLE_EQ(c.qty, 2632.0);  // (500 - 150) * 100 * 7.52 * 1e-2
  a.on_fill(Instrument::PredYes, c.qty, 0.305);
  const Intent mid = tick(a, et(2026, 11, 27, 14, 30, 0, 5), 0.30);  // between 13:00 and 16:00: still closed
  EXPECT_FALSE(is_order(mid));
  EXPECT_EQ(mid.reason, rc(Rc::ZeroTarget));
}

TEST(ClosedSessionHedge, ChristmasEveClosesAt1300) {
  F a(params<F>(), held(1000));
  EXPECT_EQ(tick(a, et(2026, 12, 24, 12, 59, 59, 5), 0.30).reason, rc(Rc::OutOfSession));
  const Intent i = tick(a, et(2026, 12, 24, 13, 0, 0, 5), 0.30);
  ASSERT_TRUE(is_order(i));
  EXPECT_EQ(i.instrument, Instrument::PredYes);
  EXPECT_EQ(i.reason, rc(Rc::Rebalance));
}

TEST(ClosedSessionHedge, OneOffClosureIsClosed) {
  // 2025-01-09: national day of mourning (President Carter), a full-day NYSE closure.
  F a(params<F>(), held(1000));
  EXPECT_EQ(tick(a, et(2025, 1, 8, 15, 0, 0, 5), 0.30).reason, rc(Rc::OutOfSession));
  const Intent i = tick(a, et(2025, 1, 9, 10, 0, 0, 5), 0.30);
  ASSERT_TRUE(is_order(i));
  EXPECT_EQ(i.instrument, Instrument::PredYes);
  EXPECT_EQ(i.reason, rc(Rc::Rebalance));
  a.on_fill(Instrument::PredYes, i.qty, 0.305);
  EXPECT_EQ(tick(a, et(2025, 1, 10, 9, 30, 0, 5), 0.30).reason, rc(Rc::Handoff));  // Friday's open
}

TEST(ClosedSessionHedge, ExternalEquityFillsLowerTheNextClosureTarget) {
  // handoff_equity = 0: the staged-order book shorts the equity at the open; the bridge forwards that fill here.
  F a(params<F>(), held(1000));
  ASSERT_TRUE(is_order(tick(a, kSat1200, 0.30)));
  a.on_fill(Instrument::PredYes, kDefaultTarget, 0.305);
  ASSERT_EQ(tick(a, kMon0930, 0.30).reason, rc(Rc::Handoff));
  a.on_fill(Instrument::PredYes, -kDefaultTarget, 0.295);
  a.on_fill(Instrument::Equity, -300, 100.0);  // the external equity fill
  const std::int64_t mon_close = kMon0930 + (6 * 3600 + 30 * 60) * kSec;
  const Intent i = tick(a, mon_close, 0.30);
  ASSERT_TRUE(is_order(i));
  EXPECT_DOUBLE_EQ(i.qty, 1504.0);  // (500 - 300) * 100 * 7.52 * 1e-2, not the full 3,760
  F unaware(params<F>(), held(1000));  // without the forwarded fill the YES leg would size on the full c * N
  EXPECT_DOUBLE_EQ(tick(unaware, mon_close, 0.30).qty, kDefaultTarget);
}

TEST(ClosedSessionHedge, RejectedBuysDoNotDelayTheHandoffSell) {
  Position pos = held(1000);
  pos.pred_yes = 1000;  // held YES; the closure wants 2,760 more
  F a(params<F>(), pos);
  for (int k = 3; k >= 1; --k) {
    const Intent b = tick(a, kMon0930 - k * kSec, 0.30);
    ASSERT_TRUE(is_order(b)) << k;
    EXPECT_EQ(b.side, +1);
    a.on_reject(Instrument::PredYes);  // the third reject backs the buy side off to kMon0930 + 1 s
  }
  const Intent u = tick(a, kMon0930, 0.30);  // a sell resets the backoff: the unwind goes at once
  ASSERT_TRUE(is_order(u));
  EXPECT_EQ(u.side, -1);
  EXPECT_DOUBLE_EQ(u.qty, 1000.0);
  EXPECT_EQ(u.reason, rc(Rc::Handoff));
}

TEST(ClosedSessionHedge, SignalIsTheExpectedGapInBpOnEveryPath) {
  F a(params<F>(), held(1000));
  const Intent pre = tick(a, kFri1500, 0.30);  // in session, no closure seen yet: no close mark
  EXPECT_EQ(pre.reason, rc(Rc::OutOfSession));
  EXPECT_TRUE(std::isnan(pre.signal));
  const Intent sat = tick(a, kSat1200, 0.35);
  ASSERT_TRUE(is_order(sat));
  a.on_fill(Instrument::PredYes, sat.qty, 0.355);
  const Intent u = tick(a, kMon0930, 0.40);  // handoff: 10 pp since Friday's in-session mark
  ASSERT_EQ(u.reason, rc(Rc::Handoff));
  EXPECT_NEAR(u.signal, 75.2, 1e-9);
  a.on_fill(Instrument::PredYes, -u.qty, 0.395);
  const Intent h = tick(a, kMon0930 + kSec, 0.40);
  EXPECT_EQ(h.reason, rc(Rc::OutOfSession));
  EXPECT_NEAR(h.signal, 75.2, 1e-9);  // bp, not the raw probability
  F e(params<F>({{"handoff_equity", 1}}), held(1000));
  tick(e, kFri1500, 0.30);
  tick(e, kSat1200, 0.35);
  const Intent eq = tick(e, kMon0930, 0.40);  // nothing to unwind: the equity handoff carries the same signal
  ASSERT_TRUE(is_order(eq));
  EXPECT_EQ(eq.instrument, Instrument::Equity);
  EXPECT_NEAR(eq.signal, 75.2, 1e-9);
}
