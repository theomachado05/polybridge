#include "family_helpers.hpp"

using namespace hctest;
using F = hedgecore::algos::StressLeadHedge;

TEST(StressLeadHedge, CalmJoinsTheTouchInSlices) {
  F a(params<F>(), held(1000));  // coverage 0.75, child_max 100
  const Intent i = a.on_tick(pm(kSec, 0.20), kSec);
  ASSERT_TRUE(is_order(i));
  EXPECT_DOUBLE_EQ(i.qty, 100.0);           // target 150 clipped to the child cap
  EXPECT_DOUBLE_EQ(i.limit_px, 100.01);     // sell joins the ask
  EXPECT_EQ(i.reason, rc(Rc::Sliced));
}

TEST(StressLeadHedge, StressCrossesUnsliced) {
  F a(params<F>({{"impact", 0}}), held(1000));
  const double path[] = {0.20, 0.201, 0.20, 0.201, 0.20, 0.201};
  std::int64_t ts = kSec;
  for (double p : path) { a.on_tick(pm(ts, p), ts); ts += kSec; }
  const Intent i = a.on_tick(pm(ts, 0.30), ts);  // dp(5) ~ 0.1 vs sigma ~ 0.001
  ASSERT_TRUE(is_order(i));
  EXPECT_DOUBLE_EQ(i.qty, 225.0);           // round(0.75 * 1000 * 0.30), no slicing in stress
  EXPECT_TRUE(std::isnan(i.limit_px));
  EXPECT_EQ(i.reason, rc(Rc::Aggressive));
  EXPECT_GT(i.signal, 2.0);                 // the stress ratio
}

TEST(StressLeadHedge, BandAndSafety) {
  F a(params<F>({{"impact", 0}, {"band_shares", 50}}), held(1000));
  a.on_tick(pm(kSec, 0.20), kSec);
  a.on_fill(Instrument::Equity, -150, 100);
  EXPECT_EQ(a.on_tick(pm(2 * kSec, 0.25), 2 * kSec).reason, rc(Rc::InsideBand));  // 188 - 150 < 50
  expect_nan_and_stale_safety<F>(params<F>(), held(1000));
}
