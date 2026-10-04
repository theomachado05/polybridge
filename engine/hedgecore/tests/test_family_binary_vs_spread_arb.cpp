#include "family_helpers.hpp"

using namespace hctest;
using F = hedgecore::algos::BinaryVsSpreadArb;

namespace {
MarketTick opt_tick(std::int64_t ts, double opt_prob, double opt_mid = 3.0) {
  MarketTick t = pm(ts, 0.60, 0.01);
  t.opt_implied_prob = opt_prob;
  t.opt_mid = opt_mid;
  return t;
}
}

TEST(BinaryVsSpreadArb, BuysSpreadWhenPmAboveOptionsAndExits) {
  F a(params<F>(), Position{});
  const Intent e = a.on_tick(opt_tick(kSec, 0.50), kSec);
  ASSERT_TRUE(is_order(e));
  EXPECT_EQ(e.instrument, Instrument::Option);
  EXPECT_EQ(e.side, +1);
  EXPECT_DOUBLE_EQ(e.qty, 5.0);
  EXPECT_NEAR(e.signal, 0.10, 1e-12);
  a.on_fill(Instrument::Option, 5, 3.05);
  EXPECT_EQ(a.on_tick(opt_tick(2 * kSec, 0.57), 2 * kSec).reason, rc(Rc::NoSignal));
  const Intent x = a.on_tick(opt_tick(3 * kSec, 0.595), 3 * kSec);
  ASSERT_TRUE(is_order(x));
  EXPECT_EQ(x.side, -1);
  EXPECT_EQ(x.reason, rc(Rc::Exit));
}

TEST(BinaryVsSpreadArb, SellsSpreadWhenPmBelowOptions) {
  F a(params<F>(), Position{});
  EXPECT_EQ(a.on_tick(opt_tick(kSec, 0.70), kSec).side, -1);
  F b(params<F>(), Position{});
  EXPECT_EQ(b.on_tick(opt_tick(kSec, 0.57), kSec).reason, rc(Rc::NoSignal));
}

TEST(BinaryVsSpreadArb, MissingOptionQuote) {
  F a(params<F>(), Position{});
  EXPECT_EQ(a.on_tick(opt_tick(kSec, 0.50, NaN), kSec).reason, rc(Rc::SignalMissing));
  expect_nan_and_stale_safety<F>(params<F>(), Position{});
}
