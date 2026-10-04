#include "family_helpers.hpp"

using namespace hctest;
using F = hedgecore::algos::PolyKalshiSpread;

namespace {
MarketTick gap_tick(std::int64_t ts, double other, double hs = 0.01, Venue v = Venue::Poly) {
  MarketTick t = pm(ts, 0.55, hs);
  t.venue = v;
  t.no_bid = 0.44;
  t.no_ask = 0.46;
  t.p_other_venue = other;
  return t;
}
}

TEST(PolyKalshiSpread, RichVenueBuysNoThenExitsOnConvergence) {
  F a(params<F>(), Position{});
  const Intent e = a.on_tick(gap_tick(kSec, 0.50), kSec);
  ASSERT_TRUE(is_order(e));
  EXPECT_EQ(e.instrument, Instrument::PredNo);
  EXPECT_EQ(e.side, +1);
  EXPECT_DOUBLE_EQ(e.qty, 500.0);
  EXPECT_EQ(e.reason, rc(Rc::Entry));
  EXPECT_EQ(e.venue, Venue::Poly);
  a.on_fill(Instrument::PredNo, 500, 0.46);
  EXPECT_EQ(a.on_tick(gap_tick(2 * kSec, 0.53), 2 * kSec).reason, rc(Rc::NoSignal));
  const Intent x = a.on_tick(gap_tick(3 * kSec, 0.545), 3 * kSec);
  ASSERT_TRUE(is_order(x));
  EXPECT_EQ(x.side, -1);
  EXPECT_EQ(x.reason, rc(Rc::Exit));
}

TEST(PolyKalshiSpread, CheapVenueBuysYes) {
  F a(params<F>(), Position{});
  const Intent e = a.on_tick(gap_tick(kSec, 0.60), kSec);
  ASSERT_TRUE(is_order(e));
  EXPECT_EQ(e.instrument, Instrument::PredYes);
}

TEST(PolyKalshiSpread, GapFlipKillsAndLatches) {
  F a(params<F>(), Position{});
  ASSERT_TRUE(is_order(a.on_tick(gap_tick(kSec, 0.50), kSec)));
  a.on_fill(Instrument::PredNo, 500, 0.46);
  const Intent k = a.on_tick(gap_tick(2 * kSec, 0.58), 2 * kSec);
  ASSERT_TRUE(is_order(k));
  EXPECT_EQ(k.reason, rc(Rc::GapFlipKill));
  a.on_fill(Instrument::PredNo, -500, 0.44);
  EXPECT_EQ(a.on_tick(gap_tick(3 * kSec, 0.50), 3 * kSec).reason, rc(Rc::GapFlipKill));
}

TEST(PolyKalshiSpread, FeeSpreadAndSizeCap) {
  F narrow(params<F>(), Position{});
  EXPECT_EQ(narrow.on_tick(gap_tick(kSec, 0.525), kSec).reason, rc(Rc::BelowFees));
  F wide(params<F>(), Position{});
  EXPECT_EQ(wide.on_tick(gap_tick(kSec, 0.50, 0.03), kSec).reason, rc(Rc::SpreadTooWide));
  F k(params<F>({{"entry_gap", 0.03}}), Position{});
  EXPECT_EQ(k.on_tick(gap_tick(kSec, 0.50, 0.01, Venue::Kalshi), kSec).reason, rc(Rc::BelowFees));
  F p(params<F>({{"entry_gap", 0.03}}), Position{});
  EXPECT_TRUE(is_order(p.on_tick(gap_tick(kSec, 0.50, 0.01, Venue::Poly), kSec)));
  F one(params<F>({{"size", 100}}), Position{});
  EXPECT_DOUBLE_EQ(one.on_tick(gap_tick(kSec, 0.50), kSec).qty, 100.0);
}

TEST(PolyKalshiSpread, MissingOtherVenue) {
  F a(params<F>(), Position{});
  EXPECT_EQ(a.on_tick(gap_tick(kSec, NaN), kSec).reason, rc(Rc::SignalMissing));
  expect_nan_and_stale_safety<F>(params<F>(), Position{});
}

TEST(PolyKalshiSpread, GapBelowEntryIsNoSignalNotFees) {
  F a(params<F>(), Position{});
  EXPECT_EQ(a.on_tick(gap_tick(kSec, 0.54), kSec).reason, rc(Rc::NoSignal));
}

TEST(PolyKalshiSpread, RejectedEntryDisarmsTheStop) {
  F a(params<F>(), Position{});
  ASSERT_TRUE(is_order(a.on_tick(gap_tick(kSec, 0.50), kSec)));
  EXPECT_NE(a.kill.entry_sign, 0);
  a.on_reject(Instrument::PredNo);
  EXPECT_EQ(a.kill.entry_sign, 0);
}
