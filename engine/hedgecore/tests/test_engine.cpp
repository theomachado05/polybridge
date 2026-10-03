#include <gtest/gtest.h>
#include <limits>
#include "hedgecore/engine.hpp"

using namespace hedgecore;

namespace {
constexpr std::int64_t kSec = 1'000'000'000;

HedgeSpec spec() {
  HedgeSpec s;
  s.ticker = "ABNB";
  s.shares_held = 1000;
  s.target_coverage = 0.5;
  s.band_shares = 10;
  return s;
}
}  // namespace

TEST(Engine, FirstTickSizesInitialHedge) {
  Engine e(spec());
  auto d = e.on_tick({kSec, 0.20}, kSec);
  EXPECT_EQ(d.action, Action::Order);
  EXPECT_EQ(d.reason, Reason::Rebalance);
  EXPECT_DOUBLE_EQ(d.target_hedge, 100.0);   // 0.5 * 1000 * 0.20
  EXPECT_DOUBLE_EQ(d.order_qty, 100.0);
  EXPECT_GE(d.latency_ns, 0);
}

TEST(Engine, StaleTickHolds) {
  Engine e(spec());
  auto d = e.on_tick({kSec, 0.20}, 5 * kSec);  // 4 s old > 2 s limit
  EXPECT_EQ(d.action, Action::Hold);
  EXPECT_EQ(d.reason, Reason::Stale);
}

TEST(Engine, OutOfRangeProbabilityHolds) {
  Engine e(spec());
  EXPECT_EQ(e.on_tick({kSec, 1.5}, kSec).reason, Reason::Invalid);
  EXPECT_EQ(e.on_tick({kSec, -0.1}, kSec).reason, Reason::Invalid);
  EXPECT_EQ(e.on_tick({kSec, std::numeric_limits<double>::quiet_NaN()}, kSec).reason, Reason::Invalid);
}

TEST(Engine, BandSuppressesSmallRebalances) {
  Engine e(spec());
  e.on_tick({kSec, 0.20}, kSec);
  e.on_fill(100);
  auto d = e.on_tick({2 * kSec, 0.21}, 2 * kSec);  // target 105, |105-100| < 10
  EXPECT_EQ(d.action, Action::Hold);
  EXPECT_EQ(d.reason, Reason::InsideBand);
  d = e.on_tick({3 * kSec, 0.30}, 3 * kSec);       // target 150
  EXPECT_EQ(d.action, Action::Order);
  EXPECT_DOUBLE_EQ(d.order_qty, 50.0);
}

TEST(Engine, SigmaGateIgnoresNoise) {
  Engine e(spec());
  e.on_tick({kSec, 0.50}, kSec);
  e.on_fill(250);
  double p = 0.50;
  for (int i = 0; i < 200; ++i) {                  // build a noise level of about 0.001
    p += (i % 2 ? -0.001 : 0.001);
    e.on_tick({(2 + i) * kSec, p}, (2 + i) * kSec);
  }
  auto d = e.on_tick({300 * kSec, p + 0.0005}, 300 * kSec);
  EXPECT_EQ(d.reason, Reason::BelowSigma);
}

TEST(Engine, RiskCapLimitsHedge) {
  auto s = spec();
  s.max_hedge_shares = 120;
  Engine e(s);
  auto d = e.on_tick({kSec, 0.50}, kSec);          // uncapped target 250
  EXPECT_EQ(d.reason, Reason::RiskCapped);
  EXPECT_DOUBLE_EQ(d.target_hedge, 120.0);
  EXPECT_DOUBLE_EQ(d.order_qty, 120.0);
}

TEST(Engine, ReasonNames) {
  EXPECT_STREQ(to_string(Reason::InsideBand), "inside_band");
  EXPECT_STREQ(to_string(Reason::RiskCapped), "risk_capped");
}

TEST(Engine, NaNCoverageHoldsInvalid) {
  auto s = spec();
  s.target_coverage = std::numeric_limits<double>::quiet_NaN();
  Engine e(s);
  auto d = e.on_tick({kSec, 0.20}, kSec);
  EXPECT_EQ(d.action, Action::Hold);
  EXPECT_EQ(d.reason, Reason::Invalid);
}

TEST(Engine, NegativeSharesHoldsInvalid) {
  auto s = spec();
  s.shares_held = -1000;
  Engine e(s);
  auto d = e.on_tick({kSec, 0.20}, kSec);
  EXPECT_EQ(d.action, Action::Hold);
  EXPECT_EQ(d.reason, Reason::Invalid);
}

TEST(Engine, CoverageAboveOneHoldsInvalid) {
  auto s = spec();
  s.target_coverage = 1.5;
  Engine e(s);
  auto d = e.on_tick({kSec, 0.20}, kSec);
  EXPECT_EQ(d.action, Action::Hold);
  EXPECT_EQ(d.reason, Reason::Invalid);
}
