#include <gtest/gtest.h>
#include "hedgecore/blocks/signals.hpp"
#include "tick_helpers.hpp"

using namespace hedgecore;
using namespace hedgecore::blocks;
using namespace hctest;

TEST(Signals, PMidHandComputedAndMissingSide) {
  MarketTick t = pm(kSec, 0.40, 0.02);
  EXPECT_DOUBLE_EQ(PMid::read(t), 0.40);
  t.yes_ask = NaN;
  EXPECT_TRUE(std::isnan(PMid::read(t)));
  t.yes_ask = 0.30;
  EXPECT_TRUE(std::isnan(PMid::read(t)));
}

TEST(Signals, ImpliedProbDeVigsWithNo) {
  MarketTick t;
  t.yes_bid = 0.40; t.yes_ask = 0.44;
  t.no_bid = 0.60;  t.no_ask = 0.62;
  EXPECT_NEAR(ImpliedProb::read(t), 0.42 / 1.03, 1e-12);
  t.no_bid = NaN;
  EXPECT_DOUBLE_EQ(ImpliedProb::read(t), 0.42);
  t.yes_bid = NaN; t.no_bid = 0.60;
  EXPECT_NEAR(ImpliedProb::read(t), 0.39, 1e-12);
  EXPECT_TRUE(std::isnan(ImpliedProb::read(MarketTick{})));
}

TEST(Signals, BookImbalanceTopN) {
  MarketTick t = with_book(pm(kSec, 0.5), 300, 100);
  EXPECT_DOUBLE_EQ((BookImbalance{1}.read(t)), 0.5);
  t.bids[2].qty = NaN;
  EXPECT_DOUBLE_EQ((BookImbalance{3}.read(t)), (600.0 - 300.0) / 900.0);
  t.asks[0].qty = NaN;
  EXPECT_TRUE(std::isnan(BookImbalance{3}.read(t)));
}

TEST(Signals, MicropriceWeightsBySize) {
  MarketTick t = with_book(pm(kSec, 0.50, 0.01), 300, 100);
  EXPECT_NEAR(Microprice::read(t), (0.49 * 100 + 0.51 * 300) / 400, 1e-12);
  t.bids[0].qty = NaN;
  EXPECT_TRUE(std::isnan(Microprice::read(t)));
}

TEST(Signals, CrossVenueGap) {
  MarketTick t = pm(kSec, 0.50);
  t.p_other_venue = 0.46;
  EXPECT_NEAR(CrossVenueGap::read(t), 0.04, 1e-12);
  t.p_other_venue = NaN;
  EXPECT_TRUE(std::isnan(CrossVenueGap::read(t)));
}

TEST(Signals, DeltaDpWindowAndNaNSkip) {
  DeltaDp d{2};
  EXPECT_TRUE(std::isnan(d.update(0.10)));
  EXPECT_TRUE(std::isnan(d.update(0.12)));
  EXPECT_NEAR(d.update(0.15), 0.05, 1e-12);
  EXPECT_TRUE(std::isnan(d.update(NaN)));
  EXPECT_NEAR(d.update(0.20), 0.08, 1e-12);
}

TEST(Signals, EwmaVolJudgesAgainstThePast) {
  EwmaVol v{0.5};
  auto o = v.update(0.50);
  EXPECT_TRUE(std::isnan(o.dp));
  o = v.update(0.52);
  EXPECT_NEAR(o.dp, 0.02, 1e-12);
  EXPECT_TRUE(std::isnan(o.sigma_prev));
  EXPECT_NEAR(o.sigma, 0.02, 1e-12);
  o = v.update(0.52);
  EXPECT_NEAR(o.sigma_prev, 0.02, 1e-12);
  EXPECT_NEAR(o.sigma, std::sqrt(2e-4), 1e-12);
  o = v.update(NaN);
  EXPECT_TRUE(std::isnan(o.sigma));
  EXPECT_EQ(v.n, 2);
}

TEST(Signals, MomentumAndMeanRevertZ) {
  Momentum m{0.5};
  EXPECT_TRUE(std::isnan(m.update(0.1)));
  EXPECT_NEAR(m.update(0.2), 0.1, 1e-12);
  EXPECT_NEAR(m.update(0.2), 0.05, 1e-12);
  MeanRevertZ z{0.5};
  EXPECT_TRUE(std::isnan(z.update(1.0)));
  EXPECT_TRUE(std::isnan(z.update(2.0)));
  EXPECT_NEAR(z.update(2.5), (2.5 - 1.5) / 0.5, 1e-12);
  EXPECT_TRUE(std::isnan(z.update(NaN)));
}

TEST(Signals, OptionImpliedProbAndGap) {
  MarketTick t = pm(kSec, 0.40);
  EXPECT_TRUE(std::isnan(OptionImpliedProb::read(t)));
  t.opt_delta = -0.30;
  EXPECT_DOUBLE_EQ(OptionImpliedProb::read(t), 0.30);
  t.opt_implied_prob = 0.35;
  EXPECT_DOUBLE_EQ(OptionImpliedProb::read(t), 0.35);
  EXPECT_NEAR(PMvsOptionGap::read(t), 0.05, 1e-12);
}

TEST(Signals, EightKScoreRange) {
  MarketTick t;
  EXPECT_TRUE(std::isnan(EightKScore::read(t)));
  t.eightk_score = 0.7;
  EXPECT_DOUBLE_EQ(EightKScore::read(t), 0.7);
  t.eightk_score = 1.5;
  EXPECT_TRUE(std::isnan(EightKScore::read(t)));
}
