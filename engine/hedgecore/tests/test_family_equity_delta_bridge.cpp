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

TEST(EquityDeltaBridge, RepeatedRejectsBackOffInsteadOfResendingEveryTick) {
  // Approved 800, 400 filled, then every re-send is rejected (coverage cap at the bridge, closed market). The first
  // reject is re-sent at once; after that each re-send waits 1, 2, 4, 8, ... s (at most 60 s) after the last one.
  F a(params<F>({{"coverage", 1.0}, {"sigma_k", 0}}), held(1000));
  const Intent first = a.on_tick(pm(kSec, 0.80), kSec);
  ASSERT_TRUE(is_order(first));
  EXPECT_DOUBLE_EQ(first.qty, 800.0);
  a.on_fill(Instrument::Equity, -400, 99.99);
  std::vector<int> sent;
  for (int k = 2; k <= 200; ++k) {
    const Intent i = a.on_tick(pm(k * kSec, 0.80), k * kSec);
    if (is_order(i)) {
      sent.push_back(k);
      EXPECT_DOUBLE_EQ(i.qty, 400.0);
      a.on_reject(Instrument::Equity);
    } else {
      EXPECT_EQ(i.reason, rc(Rc::Cooldown)) << "tick " << k;  // still working: only the backoff holds it
    }
  }
  // 2, 3 (first reject re-sent at once), then +1, +2, +4, +8, +16, +32, +60, +60 s.
  EXPECT_EQ(sent, (std::vector<int>{2, 3, 4, 6, 10, 18, 34, 66, 126, 186}));
  // A fill clears the backoff: the rest goes out on the next tick.
  a.on_fill(Instrument::Equity, -100, 99.99);
  const Intent after = a.on_tick(pm(201 * kSec, 0.80), 201 * kSec);
  ASSERT_TRUE(is_order(after)) << reason_name(after.reason);
  EXPECT_DOUBLE_EQ(after.qty, 300.0);
}

TEST(EquityDeltaBridge, RejectBackoffDoesNotDelayAnOrderOnTheOtherSide) {
  F a(params<F>({{"coverage", 1.0}, {"sigma_k", 0}, {"impact", 0}}), held(1000));
  ASSERT_TRUE(is_order(a.on_tick(pm(kSec, 0.80), kSec)));
  a.on_fill(Instrument::Equity, -400, 99.99);
  for (int k = 2; k <= 6; ++k)
    if (is_order(a.on_tick(pm(k * kSec, 0.80), k * kSec))) a.on_reject(Instrument::Equity);
  const Intent buy = a.on_tick(pm(7 * kSec, 0.10), 7 * kSec);  // target 100 < 400 held: buy back now
  ASSERT_TRUE(is_order(buy)) << reason_name(buy.reason);
  EXPECT_EQ(buy.side, +1);
  EXPECT_DOUBLE_EQ(buy.qty, 300.0);
}
