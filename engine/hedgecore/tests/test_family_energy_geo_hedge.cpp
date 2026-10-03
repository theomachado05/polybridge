#include "family_helpers.hpp"

using namespace hctest;
using F = hedgecore::algos::EnergyGeoHedge;

TEST(EnergyGeoHedge, CalmJoinsJumpCrosses) {
  F a(params<F>(), held(1000));  // coverage 0.75, jump 0.04
  const Intent calm = a.on_tick(pm(kSec, 0.20), kSec);
  ASSERT_TRUE(is_order(calm));
  EXPECT_DOUBLE_EQ(calm.qty, 150.0);
  EXPECT_DOUBLE_EQ(calm.limit_px, 100.01);
  EXPECT_EQ(calm.reason, rc(Rc::Passive));
  const Intent jump = a.on_tick(pm(2 * kSec, 0.26), 2 * kSec);
  ASSERT_TRUE(is_order(jump));
  EXPECT_DOUBLE_EQ(jump.qty, 195.0);
  EXPECT_TRUE(std::isnan(jump.limit_px));
  EXPECT_EQ(jump.reason, rc(Rc::Aggressive));
  EXPECT_NEAR(jump.signal, 0.06, 1e-12);
}

TEST(EnergyGeoHedge, WidePmSpreadIsSkipped) {
  F a(params<F>({{"max_pm_spread", 0.05}}), held(1000));
  EXPECT_EQ(a.on_tick(pm(kSec, 0.20, 0.04), kSec).reason, rc(Rc::SpreadTooWide));  // 0.08 wide
}

TEST(EnergyGeoHedge, Safety) { expect_nan_and_stale_safety<F>(params<F>(), held(1000)); }
