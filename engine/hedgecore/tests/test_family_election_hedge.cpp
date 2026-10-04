#include "family_helpers.hpp"

using namespace hctest;
using F = hedgecore::algos::ElectionHedge;

TEST(ElectionHedge, TiltAboveNeutralOnly) {
  F a(params<F>({{"sigma_k", 0}}), held(1000));
  EXPECT_DOUBLE_EQ(a.on_tick(pm(kSec, 0.70), kSec).qty, 200.0);
  F b(params<F>({{"sigma_k", 0}}), held(1000));
  EXPECT_EQ(b.on_tick(pm(kSec, 0.40), kSec).reason, rc(Rc::InsideBand));
  F c(params<F>({{"sigma_k", 0}, {"beta", 2}, {"p_neutral", 0.3}}), held(1000));
  EXPECT_DOUBLE_EQ(c.on_tick(pm(kSec, 0.70), kSec).qty, 800.0);
}

TEST(ElectionHedge, PositionCapNeverExceedsShares) {
  F a(params<F>({{"sigma_k", 0}, {"beta", 2}, {"p_neutral", 0.3}}), held(1000));
  const Intent i = a.on_tick(pm(kSec, 0.95), kSec);
  EXPECT_DOUBLE_EQ(i.qty, 1000.0);
}

TEST(ElectionHedge, Safety) { expect_nan_and_stale_safety<F>(params<F>(), held(1000)); }
