#include "family_helpers.hpp"

using namespace hctest;
using F = hedgecore::algos::TechRegHedge;

TEST(TechRegHedge, MicropriceSizedAndSliced) {
  F a(params<F>({{"coverage", 1.0}}), held(1000));
  const Intent i = a.on_tick(with_book(pm(kSec, 0.50, 0.01), 300, 100), kSec);
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
  F a(params<F>({{"coverage", 1.0}, {"band_shares", 10}, {"impact", 0.005}, {"fee_ratio", 1}}), held(1000));
  a.on_tick(pm(kSec, 0.50), kSec);
  a.on_fill(Instrument::Equity, -500, 100);
  EXPECT_EQ(a.on_tick(pm(2 * kSec, 0.51), 2 * kSec).reason, rc(Rc::BelowFees));
  F b(params<F>({{"coverage", 1.0}, {"band_shares", 10}, {"impact", 0.03}, {"fee_ratio", 2}}), held(1000));
  b.on_tick(pm(kSec, 0.50), kSec);
  b.on_fill(Instrument::Equity, -500, 100);
  EXPECT_TRUE(is_order(b.on_tick(pm(2 * kSec, 0.51), 2 * kSec)));
}

TEST(TechRegHedge, Safety) { expect_nan_and_stale_safety<F>(params<F>(), held(1000)); }

TEST(TechRegHedge, SlicedRebalanceConvergesWithDefaultImpact) {
  F a(params<F>({{"child_max", 200}}), held(1000));
  ASSERT_GT(F::spec().defaults().v[static_cast<std::size_t>(F::spec().index_of("impact"))], 0.0);
  double hedge = 0;
  std::int64_t ts = kSec;
  int orders = 0;
  for (int k = 0; k < 10; ++k, ts += kSec) {
    const Intent i = a.on_tick(pm(ts, 0.60), ts);
    EXPECT_NE(i.reason, rc(Rc::BelowFees)) << "tick " << k;
    if (is_order(i)) { ++orders; a.on_fill(Instrument::Equity, i.side * i.qty, 100.0); hedge -= i.side * i.qty; }
  }
  const double target = a.core.work_target;
  EXPECT_DOUBLE_EQ(hedge, target);
  EXPECT_GE(target, 250.0);
  EXPECT_EQ(orders, 2);
  EXPECT_EQ(a.on_tick(pm(ts, 0.60), ts).reason, rc(Rc::InsideBand));
}

TEST(TechRegHedge, IncrementBeyondApprovedTargetIsFeeGated) {
  F a(params<F>({{"coverage", 1.0}, {"child_max", 200}, {"band_shares", 10}, {"impact", 0.005}}), held(1000));
  ASSERT_TRUE(is_order(a.on_tick(pm(kSec, 0.50), kSec)));
  a.on_fill(Instrument::Equity, -200, 100);
  const Intent i = a.on_tick(pm(2 * kSec, 0.51), 2 * kSec);
  ASSERT_TRUE(is_order(i));
  EXPECT_DOUBLE_EQ(a.core.work_target, 500.0);
  EXPECT_DOUBLE_EQ(i.qty, 200.0);
}
