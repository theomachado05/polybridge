#include "family_helpers.hpp"

using namespace hctest;
using F = hedgecore::algos::MacroFedHedge;

TEST(MacroFedHedge, CooldownThenMomentumConfirmedOrder) {
  F a(params<F>({{"impact", 0}}), held(1000));
  const Intent first = a.on_tick(pm(kSec, 0.40), kSec);
  ASSERT_TRUE(is_order(first));
  EXPECT_DOUBLE_EQ(first.qty, 200.0);
  a.on_fill(Instrument::Equity, -200, 100);
  EXPECT_EQ(a.on_tick(pm(2 * kSec, 0.50), 2 * kSec).reason, rc(Rc::Cooldown));
  const Intent i = a.on_tick(pm(100 * kSec, 0.50), 100 * kSec);
  ASSERT_TRUE(is_order(i));
  EXPECT_DOUBLE_EQ(i.qty, 50.0);
  EXPECT_NEAR(i.signal, 0.07, 1e-12);
}

TEST(MacroFedHedge, MomentumDisagreementHolds) {
  F a(params<F>({{"impact", 0}, {"cooldown_s", 0}}), held(1000));
  a.on_tick(pm(kSec, 0.40), kSec);
  a.on_fill(Instrument::Equity, -200, 100);
  a.on_tick(pm(2 * kSec, 0.50), 2 * kSec);
  const Intent i = a.on_tick(pm(3 * kSec, 0.35), 3 * kSec);
  EXPECT_EQ(i.reason, rc(Rc::NoSignal));
  EXPECT_NEAR(i.signal, 0.025, 1e-12);
}

TEST(MacroFedHedge, Safety) { expect_nan_and_stale_safety<F>(params<F>(), held(1000)); }
