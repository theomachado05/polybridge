#include "family_helpers.hpp"

using namespace hctest;
using F = hedgecore::algos::VolVsPmMove;

namespace {
MarketTick vt(std::int64_t ts, double p, double iv) {
  MarketTick t = pm(ts, p, 0.005);
  t.opt_iv = iv;
  t.opt_mid = 2.0;
  return t;
}
// Five flat ticks, then the sixth (window 5) carries the move.
Intent sixth(F& a, double p6, double iv6) {
  for (int i = 1; i <= 5; ++i) EXPECT_EQ(a.on_tick(vt(i * kSec, 0.50, 0.30), i * kSec).reason, rc(Rc::Warmup));
  return a.on_tick(vt(6 * kSec, p6, iv6), 6 * kSec);
}
}  // namespace

TEST(VolVsPmMove, PmRepricesIvStillBuysStraddleThenExitsWhenIvCatchesUp) {
  F a(params<F>(), Position{});  // window 5, pm_move 0.04, iv_still 0.01, contracts 5
  const Intent e = sixth(a, 0.55, 0.30);
  ASSERT_TRUE(is_order(e));
  EXPECT_EQ(e.side, +1);
  EXPECT_DOUBLE_EQ(e.qty, 5.0);
  EXPECT_NEAR(e.signal, 0.05, 1e-12);
  a.on_fill(Instrument::Option, 5, 2.05);
  EXPECT_EQ(a.on_tick(vt(7 * kSec, 0.55, 0.31), 7 * kSec).reason, rc(Rc::NoSignal));
  const Intent x = a.on_tick(vt(8 * kSec, 0.55, 0.32), 8 * kSec);  // +0.02 >= 2 * iv_still
  ASSERT_TRUE(is_order(x));
  EXPECT_EQ(x.reason, rc(Rc::Exit));
}

TEST(VolVsPmMove, IvSpikeWithQuietPmSellsVol) {
  F a(params<F>(), Position{});
  const Intent e = sixth(a, 0.50, 0.34);
  ASSERT_TRUE(is_order(e));
  EXPECT_EQ(e.side, -1);
}

TEST(VolVsPmMove, MaxHoldForcesExit) {
  F a(params<F>({{"max_hold", 2}}), Position{});
  ASSERT_TRUE(is_order(sixth(a, 0.55, 0.30)));
  a.on_fill(Instrument::Option, 5, 2.05);
  EXPECT_FALSE(is_order(a.on_tick(vt(7 * kSec, 0.55, 0.30), 7 * kSec)));
  EXPECT_EQ(a.on_tick(vt(8 * kSec, 0.55, 0.30), 8 * kSec).reason, rc(Rc::Exit));
}

TEST(VolVsPmMove, MissingIv) {
  F a(params<F>(), Position{});
  EXPECT_EQ(a.on_tick(vt(kSec, 0.5, NaN), kSec).reason, rc(Rc::SignalMissing));
  expect_nan_and_stale_safety<F>(params<F>(), Position{});
}
