#include "family_helpers.hpp"

using namespace hctest;
using F = hedgecore::algos::NoBidSeller;

namespace {
MarketTick nb_tick(std::int64_t ts, double no_bid, double no_ask, double other) {
  MarketTick t = pm(ts, 0.39, 0.01);
  t.no_bid = no_bid;
  t.no_ask = no_ask;
  t.p_other_venue = other;
  return t;
}
}

TEST(NoBidSeller, SellsRichNoKellySizedAndRouted) {
  F a(params<F>(), Position{});
  const Intent i = a.on_tick(nb_tick(kSec, 0.64, 0.66, 0.40), kSec);
  ASSERT_TRUE(is_order(i));
  EXPECT_EQ(i.instrument, Instrument::PredNo);
  EXPECT_EQ(i.side, -1);
  EXPECT_DOUBLE_EQ(i.qty, 1736.0);
  EXPECT_EQ(i.reason, rc(Rc::RoutedPoly));
  EXPECT_EQ(i.venue, Venue::Poly);
  EXPECT_NEAR(i.signal, 0.04, 1e-12);
}

TEST(NoBidSeller, IcebergCapsToDisplayedSize) {
  F a(params<F>(), Position{});
  MarketTick t = with_book(nb_tick(kSec, 0.64, 0.66, 0.40), 1000, 1000);
  const Intent i = a.on_tick(t, kSec);
  ASSERT_TRUE(is_order(i));
  EXPECT_DOUBLE_EQ(i.qty, 500.0);
  EXPECT_EQ(i.reason, rc(Rc::IcebergCapped));
}

TEST(NoBidSeller, KellyCapIsARiskCapAndExitWhenCheap) {
  F a(params<F>(), Position{});
  ASSERT_TRUE(is_order(a.on_tick(nb_tick(kSec, 0.64, 0.66, 0.40), kSec)));
  a.on_fill(Instrument::PredNo, -1736, 0.64);
  EXPECT_EQ(a.on_tick(nb_tick(2 * kSec, 0.64, 0.66, 0.40), 2 * kSec).reason, rc(Rc::ZeroTarget));
  const Intent x = a.on_tick(nb_tick(3 * kSec, 0.53, 0.55, 0.40), 3 * kSec);
  ASSERT_TRUE(is_order(x));
  EXPECT_EQ(x.side, +1);
  EXPECT_DOUBLE_EQ(x.qty, 1736.0);
  EXPECT_EQ(x.reason, rc(Rc::Exit));
}

TEST(NoBidSeller, NotRichEnoughAndFairSources) {
  F a(params<F>(), Position{});
  EXPECT_EQ(a.on_tick(nb_tick(kSec, 0.61, 0.63, 0.40), kSec).reason, rc(Rc::NoSignal));
  F b(params<F>(), Position{});
  EXPECT_EQ(b.on_tick(nb_tick(kSec, 0.64, 0.66, NaN), kSec).reason, rc(Rc::SignalMissing));
  F c(params<F>({{"fair_source", 1}}), Position{});
  EXPECT_EQ(c.on_tick(nb_tick(kSec, 0.64, 0.66, 0.40), kSec).reason, rc(Rc::Warmup));
  F d(params<F>({{"fair_source", 2}}), Position{});
  MarketTick t = nb_tick(kSec, 0.64, 0.66, NaN);
  t.opt_implied_prob = 0.40;
  EXPECT_TRUE(is_order(d.on_tick(t, kSec)));
  expect_nan_and_stale_safety<F>(params<F>(), Position{});
}

TEST(NoBidSeller, NotionalCapLimitsTheShortNo) {
  F a(params<F>({{"max_notional", 640}}), Position{});
  const Intent i = a.on_tick(nb_tick(kSec, 0.64, 0.66, 0.40), kSec);
  ASSERT_TRUE(is_order(i));
  EXPECT_DOUBLE_EQ(i.qty, 1000.0);
  EXPECT_EQ(i.reason, rc(Rc::NotionalCapped));
  a.on_fill(Instrument::PredNo, -1000, 0.64);
  EXPECT_EQ(a.on_tick(nb_tick(2 * kSec, 0.64, 0.66, 0.40), 2 * kSec).reason, rc(Rc::NotionalCapped));
}

TEST(NoBidSeller, DailyLossCapStopsNewSalesButAllowsExit) {
  F a(params<F>({{"daily_loss", 100}}), Position{});
  ASSERT_TRUE(is_order(a.on_tick(nb_tick(kSec, 0.64, 0.66, 0.40), kSec)));
  a.on_fill(Instrument::PredNo, -1000, 0.64);
  MarketTick t = nb_tick(2 * kSec, 0.79, 0.81, 0.30);
  t.yes_bid = 0.19;
  t.yes_ask = 0.21;
  EXPECT_EQ(a.on_tick(t, 2 * kSec).reason, rc(Rc::DailyLossCap));
  MarketTick c = nb_tick(3 * kSec, 0.75, 0.77, 0.10);
  c.yes_bid = 0.19;
  c.yes_ask = 0.21;
  const Intent x = a.on_tick(c, 3 * kSec);
  ASSERT_TRUE(is_order(x));
  EXPECT_EQ(x.side, +1);
  EXPECT_EQ(x.reason, rc(Rc::Exit));
}
