#include "family_helpers.hpp"

using namespace hctest;
using F = hedgecore::algos::CryptoRegHedge;

TEST(CryptoRegHedge, WarmupUnscaledThenInverseVol) {
  F a(params<F>({{"impact", 0}}), held(1000));
  const Intent w = a.on_tick(pm(kSec, 0.20), kSec);
  EXPECT_DOUBLE_EQ(w.qty, 150.0);
  EXPECT_DOUBLE_EQ(w.signal, 1.0);
  const Intent noisy = a.on_tick(pm(2 * kSec, 0.24), 2 * kSec);
  EXPECT_DOUBLE_EQ(noisy.qty, 90.0);
  EXPECT_DOUBLE_EQ(noisy.signal, 0.5);
}

TEST(CryptoRegHedge, CalmScaleCappedAndCoverageClamped) {
  F a(params<F>({{"impact", 0}}), held(1000));
  a.on_tick(pm(kSec, 0.20), kSec);
  const Intent i = a.on_tick(pm(2 * kSec, 0.201), 2 * kSec);
  EXPECT_DOUBLE_EQ(i.signal, 1.5);
  EXPECT_DOUBLE_EQ(i.qty, 201.0);
}

TEST(CryptoRegHedge, Safety) { expect_nan_and_stale_safety<F>(params<F>(), held(1000)); }
