#include "family_helpers.hpp"

using namespace hctest;
using F = hedgecore::algos::HousingRates;

TEST(HousingRates, LinearBetaAndMaxCoverage) {
  F a(params<F>({{"beta", 0.5}, {"sigma_k", 0}}), held(1000));
  EXPECT_DOUBLE_EQ(a.on_tick(pm(kSec, 0.60), kSec).qty, 300.0);  // 1000 * 0.5 * 0.6
  F b(params<F>({{"beta", 1.5}, {"max_cov", 0.5}, {"sigma_k", 0}}), held(1000));
  EXPECT_DOUBLE_EQ(b.on_tick(pm(kSec, 0.60), kSec).qty, 500.0);  // 0.9 clamped to 0.5
}

TEST(HousingRates, SigmaGateAfterWarmup) {
  F a(params<F>({{"sigma_k", 2}, {"impact", 0}}), held(1000));
  EXPECT_TRUE(is_order(a.on_tick(pm(kSec, 0.50), kSec)));        // warm-up passes
  EXPECT_TRUE(is_order(a.on_tick(pm(2 * kSec, 0.51), 2 * kSec)));  // first change: no prior sigma
  EXPECT_EQ(a.on_tick(pm(3 * kSec, 0.52), 3 * kSec).reason, rc(Rc::BelowSigma));  // 0.01 < 2 * 0.01
}

TEST(HousingRates, Safety) { expect_nan_and_stale_safety<F>(params<F>(), held(1000)); }
