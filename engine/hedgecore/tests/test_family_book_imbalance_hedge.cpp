#include "family_helpers.hpp"

using namespace hctest;
using F = hedgecore::algos::BookImbalanceHedge;

TEST(BookImbalanceHedge, LopsidedBookPreHedgesOnMicroprice) {
  F a(params<F>(), held(1000));
  const Intent i = a.on_tick(with_book(pm(kSec, 0.50, 0.01), 600, 200), kSec);
  ASSERT_TRUE(is_order(i));
  EXPECT_DOUBLE_EQ(i.qty, 379.0);
  EXPECT_TRUE(std::isnan(i.limit_px));
  EXPECT_EQ(i.reason, rc(Rc::Aggressive));
  EXPECT_DOUBLE_EQ(i.signal, 0.5);
}

TEST(BookImbalanceHedge, BalancedBookUsesMidAndJoins) {
  F a(params<F>(), held(1000));
  const Intent i = a.on_tick(with_book(pm(kSec, 0.50, 0.01), 500, 500), kSec);
  ASSERT_TRUE(is_order(i));
  EXPECT_DOUBLE_EQ(i.qty, 375.0);
  EXPECT_DOUBLE_EQ(i.limit_px, 100.01);
  EXPECT_EQ(i.reason, rc(Rc::Rebalance));
}

TEST(BookImbalanceHedge, DepthGateFailsClosed) {
  F a(params<F>(), held(1000));
  EXPECT_EQ(a.on_tick(with_book(pm(kSec, 0.5), 600, 100), kSec).reason, rc(Rc::ThinBook));
  EXPECT_EQ(a.on_tick(pm(kSec, 0.5), kSec).reason, rc(Rc::ThinBook));
  expect_nan_and_stale_safety<F>(params<F>(), held(1000));
}
