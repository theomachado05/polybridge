#include "family_helpers.hpp"

using namespace hctest;
using F = hedgecore::algos::FigStress;

TEST(FigStress, ConvexSizing) {
  F lin(params<F>({{"gamma", 1}}), held(1000));
  EXPECT_DOUBLE_EQ(lin.on_tick(pm(kSec, 0.40), kSec).qty, 300.0);  // 0.75 * 1000 * 0.4
  F cvx(params<F>({{"gamma", 2}}), held(1000));
  EXPECT_DOUBLE_EQ(cvx.on_tick(pm(kSec, 0.40), kSec).qty, 120.0);  // 0.75 * 1000 * 0.16
}

TEST(FigStress, DrawdownKillLatchesOnHedgeLoss) {
  F a(params<F>({{"gamma", 1}, {"dd_frac", 0.05}}), held(1000));  // limit 0.05 * 1000 * 100 = $5,000
  ASSERT_TRUE(is_order(a.on_tick(pm(kSec, 0.40), kSec)));
  a.on_fill(Instrument::Equity, -300, 99.99);
  EXPECT_EQ(a.on_tick(pm(2 * kSec, 0.40, 0.005, 115.0), 2 * kSec).reason, rc(Rc::InsideBand));  // dd 4503
  EXPECT_EQ(a.on_tick(pm(3 * kSec, 0.40, 0.005, 120.0), 3 * kSec).reason, rc(Rc::DrawdownKill));  // dd 6003
  EXPECT_EQ(a.on_tick(pm(4 * kSec, 0.90, 0.005, 100.0), 4 * kSec).reason, rc(Rc::DrawdownKill));  // latched
}

TEST(FigStress, Safety) { expect_nan_and_stale_safety<F>(params<F>(), held(1000)); }

TEST(FigStress, KilledHedgeCanStillShrink) {
  F a(params<F>({{"gamma", 1}, {"dd_frac", 0.05}}), held(1000));
  ASSERT_TRUE(is_order(a.on_tick(pm(kSec, 0.40), kSec)));
  a.on_fill(Instrument::Equity, -300, 99.99);
  EXPECT_EQ(a.on_tick(pm(2 * kSec, 0.40, 0.005, 120.0), 2 * kSec).reason, rc(Rc::DrawdownKill));
  const Intent cut = a.on_tick(pm(3 * kSec, 0.0, 0.0, 120.0), 3 * kSec);  // adverse odds gone: cover the hedge
  ASSERT_TRUE(is_order(cut));
  EXPECT_EQ(cut.side, +1);
  EXPECT_DOUBLE_EQ(cut.qty, 300.0);
  EXPECT_EQ(cut.reason, rc(Rc::DrawdownKill));
  a.on_fill(Instrument::Equity, +300, 120.01);
  EXPECT_EQ(a.on_tick(pm(4 * kSec, 0.90, 0.005, 120.0), 4 * kSec).reason, rc(Rc::DrawdownKill));  // never regrows
}

TEST(FigStress, PreExistingHedgeCountsTowardDrawdown) {
  // A 300-share short carried in from before the algo started loses 300 * 20 = $6,000 > $5,000 when the stock rallies.
  F a(params<F>({{"gamma", 1}, {"dd_frac", 0.05}}), held(1000, -300));
  EXPECT_EQ(a.on_tick(pm(kSec, 0.40), kSec).reason, rc(Rc::InsideBand));
  EXPECT_EQ(a.on_tick(pm(2 * kSec, 0.60, 0.005, 120.0), 2 * kSec).reason, rc(Rc::DrawdownKill));
}
