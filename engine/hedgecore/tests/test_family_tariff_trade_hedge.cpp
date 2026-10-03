#include "family_helpers.hpp"

using namespace hctest;
using F = hedgecore::algos::TariffTradeHedge;

namespace {
// p: 0.20 (fill 67) -> 0.22 -> 0.21; at the third tick z = (0.21 - 0.202) / 0.006 = 1.333 and delta = 72 - 67 = +5.
Intent third(double z_entry) {
  F a(params<F>({{"z_entry", z_entry}, {"band_shares", 1}, {"impact", 0}}), held(1000));
  const Intent i = a.on_tick(pm(kSec, 0.20), kSec);
  EXPECT_DOUBLE_EQ(i.qty, 67.0);  // round(0.75 * 1000 * 0.2^1.5)
  a.on_fill(Instrument::Equity, -67, 100);
  a.on_tick(pm(2 * kSec, 0.22), 2 * kSec);
  return a.on_tick(pm(3 * kSec, 0.21), 3 * kSec);
}
}  // namespace

TEST(TariffTradeHedge, BreakoutAllowsGrowth) {
  const Intent i = third(1.0);
  ASSERT_TRUE(is_order(i));
  EXPECT_DOUBLE_EQ(i.qty, 5.0);
  EXPECT_NEAR(i.signal, 0.008 / 0.006, 1e-9);
}

TEST(TariffTradeHedge, BelowBreakoutHolds) { EXPECT_EQ(third(2.0).reason, rc(Rc::NoSignal)); }

TEST(TariffTradeHedge, Safety) { expect_nan_and_stale_safety<F>(params<F>(), held(1000)); }
