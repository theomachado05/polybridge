#include "family_helpers.hpp"

using namespace hctest;
using F = hedgecore::algos::EquityDeltaBridge;

TEST(EquityDeltaBridge, FirstTickSizesInitialHedge) {
  F a(params<F>(), held(1000));
  const Intent i = a.on_tick(pm(kSec, 0.20), kSec);
  ASSERT_TRUE(is_order(i));
  EXPECT_EQ(i.instrument, Instrument::Equity);
  EXPECT_EQ(i.side, -1);                 // sell to open the short hedge
  EXPECT_DOUBLE_EQ(i.qty, 100.0);        // round(0.5 * 1000 * 0.20)
  EXPECT_TRUE(std::isnan(i.limit_px));   // marketable
  EXPECT_EQ(i.reason, rc(Rc::Rebalance));
  EXPECT_DOUBLE_EQ(i.signal, 0.20);
  EXPECT_GE(i.latency_ns, 0);
}

TEST(EquityDeltaBridge, BandHoldsSmallChanges) {
  F a(params<F>({{"sigma_k", 0}}), held(1000));
  ASSERT_TRUE(is_order(a.on_tick(pm(kSec, 0.20), kSec)));
  a.on_fill(Instrument::Equity, -100, 99.99);
  EXPECT_EQ(a.on_tick(pm(2 * kSec, 0.21), 2 * kSec).reason, rc(Rc::InsideBand));  // target 105, |5| < 10
}

TEST(EquityDeltaBridge, FeeGateBlocksWhenBenefitBelowCost) {
  // delta 10 shares on dp 0.02: benefit = 10 * 100 * impact * 0.02; cost = 10 * (0.0035 + 0.01) = 0.135.
  F ok(params<F>({{"sigma_k", 0}, {"impact", 0.03}}), held(1000));
  ok.on_tick(pm(kSec, 0.20), kSec);
  ok.on_fill(Instrument::Equity, -100, 99.99);
  EXPECT_TRUE(is_order(ok.on_tick(pm(2 * kSec, 0.22), 2 * kSec)));  // benefit 0.6 >= 0.135
  F no(params<F>({{"sigma_k", 0}, {"impact", 0.001}}), held(1000));
  no.on_tick(pm(kSec, 0.20), kSec);
  no.on_fill(Instrument::Equity, -100, 99.99);
  EXPECT_EQ(no.on_tick(pm(2 * kSec, 0.22), 2 * kSec).reason, rc(Rc::BelowFees));  // 0.02 < 0.135
}

TEST(EquityDeltaBridge, ExistingHedgeAboveTargetIsReduced) {
  F a(params<F>({{"sigma_k", 0}, {"impact", 0}}), held(1000, -300));
  const Intent i = a.on_tick(pm(kSec, 0.20), kSec);
  ASSERT_TRUE(is_order(i));
  EXPECT_EQ(i.side, +1);
  EXPECT_DOUBLE_EQ(i.qty, 200.0);
}

TEST(EquityDeltaBridge, WashSaleGuardBlocksReShortAfterLossCover) {
  F a(params<F>({{"sigma_k", 0}, {"impact", 0}, {"wash_guard", 1}}), held(1000));
  ASSERT_TRUE(is_order(a.on_tick(pm(kSec, 0.20), kSec)));
  a.on_fill(Instrument::Equity, -100, 99.99);
  const Intent cover = a.on_tick(pm(2 * kSec, 0.05, 0.005, 101.0), 2 * kSec);  // target 25: buy 75 at a loss
  ASSERT_TRUE(is_order(cover));
  EXPECT_EQ(cover.side, +1);
  a.on_fill(Instrument::Equity, 75, 101.01);
  EXPECT_EQ(a.on_tick(pm(3 * kSec, 0.30, 0.005, 101.0), 3 * kSec).reason, rc(Rc::WashSale));
}

TEST(EquityDeltaBridge, NaNFillLatchesInvalidState) {
  F a(params<F>(), held(1000));
  a.on_fill(Instrument::Equity, NaN, 100);
  EXPECT_EQ(a.on_tick(pm(kSec, 0.2), kSec).reason, rc(Rc::InvalidState));
}

TEST(EquityDeltaBridge, MissingQuotesAndStale) {
  MarketTick t = pm(kSec, 0.2);
  t.yes_bid = NaN;
  F a(params<F>(), held(1000));
  EXPECT_EQ(a.on_tick(t, kSec).reason, rc(Rc::SignalMissing));
  expect_nan_and_stale_safety<F>(params<F>(), held(1000));
}

TEST(EquityDeltaBridge, OutOfBoundsParamsHold) {
  F a(params<F>({{"coverage", 1.5}}), held(1000));
  EXPECT_EQ(a.on_tick(pm(kSec, 0.2), kSec).reason, rc(Rc::InvalidParams));
}
