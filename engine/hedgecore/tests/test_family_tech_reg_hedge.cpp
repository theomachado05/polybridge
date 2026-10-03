#include "family_helpers.hpp"

using namespace hctest;
using F = hedgecore::algos::TechRegHedge;

TEST(TechRegHedge, MicropriceSizedAndSliced) {
  F a(params<F>({{"coverage", 1.0}}), held(1000));
  const Intent i = a.on_tick(with_book(pm(kSec, 0.50, 0.01), 300, 100), kSec);  // micro 0.505 -> 505
  ASSERT_TRUE(is_order(i));
  EXPECT_DOUBLE_EQ(i.qty, 200.0);
  EXPECT_EQ(i.reason, rc(Rc::Sliced));
  EXPECT_NEAR(i.signal, 0.505, 1e-12);
}

TEST(TechRegHedge, FallsBackToMidWithoutBook) {
  F a(params<F>({{"coverage", 1.0}, {"child_max", 1000}}), held(1000));
  const Intent i = a.on_tick(pm(kSec, 0.50), kSec);
  EXPECT_DOUBLE_EQ(i.qty, 500.0);
  EXPECT_EQ(i.reason, rc(Rc::Rebalance));
}

TEST(TechRegHedge, FeeRatio) {
  // 10-share step on dp 0.02 with impact 0.005: benefit 0.1 vs cost 0.135 -> blocked even at ratio 1.
  F a(params<F>({{"coverage", 1.0}, {"band_shares", 10}, {"impact", 0.005}, {"fee_ratio", 1}}), held(1000));
  a.on_tick(pm(kSec, 0.50), kSec);
  a.on_fill(Instrument::Equity, -500, 100);
  EXPECT_EQ(a.on_tick(pm(2 * kSec, 0.51), 2 * kSec).reason, rc(Rc::BelowFees));
  F b(params<F>({{"coverage", 1.0}, {"band_shares", 10}, {"impact", 0.03}, {"fee_ratio", 2}}), held(1000));
  b.on_tick(pm(kSec, 0.50), kSec);
  b.on_fill(Instrument::Equity, -500, 100);
  EXPECT_TRUE(is_order(b.on_tick(pm(2 * kSec, 0.51), 2 * kSec)));  // benefit 0.3 >= 2 * 0.135
}

TEST(TechRegHedge, Safety) { expect_nan_and_stale_safety<F>(params<F>(), held(1000)); }
