#include "family_helpers.hpp"

using namespace hctest;
using F = hedgecore::algos::EightKOpportunity;

namespace {
MarketTick ek(std::int64_t ts, double p, double score) {
  MarketTick t = pm(ts, p, 0.005);
  t.eightk_score = score;
  t.opt_mid = 1.5;
  return t;
}
}  // namespace

TEST(EightKOpportunity, BullishTagConfirmedSellsPutThenClosesAfterWindow) {
  F a(params<F>(), Position{});  // window 24 h, thr 0.5, confirm 0.01, contracts 1
  EXPECT_EQ(a.on_tick(ek(kSec, 0.50, 0.8), kSec).reason, rc(Rc::Warmup));
  for (int i = 2; i <= 5; ++i) EXPECT_EQ(a.on_tick(ek(i * kSec, 0.50, 0.0), i * kSec).reason, rc(Rc::Warmup));
  const Intent e = a.on_tick(ek(6 * kSec, 0.48, 0.0), 6 * kSec);  // adverse prob fell 0.02
  ASSERT_TRUE(is_order(e));
  EXPECT_EQ(e.instrument, Instrument::Option);
  EXPECT_EQ(e.side, -1);
  EXPECT_DOUBLE_EQ(e.qty, 1.0);
  EXPECT_DOUBLE_EQ(e.signal, 0.8);
  a.on_fill(Instrument::Option, -1, 1.45);
  const std::int64_t late = kSec + 25 * 3600 * kSec;
  const Intent x = a.on_tick(ek(late, 0.48, 0.0), late);
  ASSERT_TRUE(is_order(x));
  EXPECT_EQ(x.side, +1);
  EXPECT_EQ(x.reason, rc(Rc::Exit));
}

TEST(EightKOpportunity, BearishTagBuysPutSpread) {
  F a(params<F>(), Position{});
  a.on_tick(ek(kSec, 0.50, -0.9), kSec);
  for (int i = 2; i <= 5; ++i) a.on_tick(ek(i * kSec, 0.50, 0.0), i * kSec);
  EXPECT_EQ(a.on_tick(ek(6 * kSec, 0.52, 0.0), 6 * kSec).side, +1);
}

TEST(EightKOpportunity, WeakTagNoWindowAndUnconfirmed) {
  F a(params<F>(), Position{});
  EXPECT_EQ(a.on_tick(ek(kSec, 0.50, 0.3), kSec).reason, rc(Rc::OutsideEventWindow));
  F b(params<F>(), Position{});
  b.on_tick(ek(kSec, 0.50, 0.8), kSec);
  for (int i = 2; i <= 5; ++i) b.on_tick(ek(i * kSec, 0.50, 0.0), i * kSec);
  EXPECT_EQ(b.on_tick(ek(6 * kSec, 0.505, 0.0), 6 * kSec).reason, rc(Rc::NoSignal));
  expect_nan_and_stale_safety<F>(params<F>(), Position{});
}
