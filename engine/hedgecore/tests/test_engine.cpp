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
}

TEST(Engine, FirstTickSizesInitialHedge) {
  Engine e(spec());
  auto d = e.on_tick({kSec, 0.20}, kSec);
  EXPECT_EQ(d.action, Action::Order);
  EXPECT_EQ(d.reason, Reason::Rebalance);
  EXPECT_DOUBLE_EQ(d.target_hedge, 100.0);
  EXPECT_DOUBLE_EQ(d.order_qty, 100.0);
  EXPECT_GE(d.latency_ns, 0);
}

TEST(Engine, StaleTickHolds) {
  Engine e(spec());
  auto d = e.on_tick({kSec, 0.20}, 5 * kSec);
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
  auto d = e.on_tick({2 * kSec, 0.21}, 2 * kSec);
  EXPECT_EQ(d.action, Action::Hold);
  EXPECT_EQ(d.reason, Reason::InsideBand);
  d = e.on_tick({3 * kSec, 0.30}, 3 * kSec);
  EXPECT_EQ(d.action, Action::Order);
  EXPECT_DOUBLE_EQ(d.order_qty, 50.0);
}

TEST(Engine, SigmaGateIgnoresNoise) {
  Engine e(spec());
  e.on_tick({kSec, 0.50}, kSec);
  e.on_fill(250);
  double p = 0.50;
  for (int i = 0; i < 200; ++i) {
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
  auto d = e.on_tick({kSec, 0.50}, kSec);
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

TEST(Engine, NaNFillLatchesInvalid) {
  Engine e(spec());
  e.on_fill(std::numeric_limits<double>::quiet_NaN());
  EXPECT_DOUBLE_EQ(e.current_hedge(), 0.0);
  auto d = e.on_tick({kSec, 0.20}, kSec);
  EXPECT_EQ(d.action, Action::Hold);
  EXPECT_EQ(d.reason, Reason::Invalid);
  e.on_fill(std::numeric_limits<double>::infinity());
  d = e.on_tick({2 * kSec, 0.20}, 2 * kSec);
  EXPECT_EQ(d.action, Action::Hold);
  EXPECT_EQ(d.reason, Reason::Invalid);
}

TEST(Engine, FutureTickHoldsStale) {
  Engine e(spec());
  auto d = e.on_tick({kSec + 4 * kSec, 0.20}, kSec);
  EXPECT_EQ(d.action, Action::Hold);
  EXPECT_EQ(d.reason, Reason::Stale);
}

TEST(Engine, ExtremeTimestampsDoNotOverflow) {
  Engine e(spec());
  auto d = e.on_tick({std::numeric_limits<std::int64_t>::min(), 0.20}, std::numeric_limits<std::int64_t>::max());
  EXPECT_EQ(d.reason, Reason::Stale);
}

namespace {
HedgeSpec fee_spec() {
  auto s = spec();
  s.gap_per_share = 1.0;
  s.fee_per_share = 0.0035;
  s.half_spread = 0.01;
  return s;
}
}

TEST(FeeGate, BlocksSmallMove) {
  auto s = fee_spec();
  s.band_shares = 0;
  Engine e(s);
  e.on_tick({kSec, 0.20}, kSec);
  e.on_fill(100);
  auto d = e.on_tick({2 * kSec, 0.21}, 2 * kSec);
  EXPECT_EQ(d.action, Action::Hold);
  EXPECT_EQ(d.reason, Reason::BelowFees);
  EXPECT_DOUBLE_EQ(d.order_qty, 0.0);
}

TEST(FeeGate, AllowsLargeMove) {
  auto s = fee_spec();
  s.band_shares = 0;
  Engine e(s);
  e.on_tick({kSec, 0.20}, kSec);
  e.on_fill(100);
  auto d = e.on_tick({2 * kSec, 0.30}, 2 * kSec);
  EXPECT_EQ(d.action, Action::Order);
  EXPECT_DOUBLE_EQ(d.order_qty, 50.0);
}

TEST(FeeGate, FirstOrderSizedWhenBenefitEnough) {
  Engine e(fee_spec());
  auto d = e.on_tick({kSec, 0.20}, kSec);
  EXPECT_EQ(d.action, Action::Order);
  EXPECT_DOUBLE_EQ(d.order_qty, 100.0);
}

TEST(FeeGate, InvalidNewFieldsHoldInvalid) {
  const double nan = std::numeric_limits<double>::quiet_NaN();
  const double inf = std::numeric_limits<double>::infinity();
  auto check = [](HedgeSpec s) {
    Engine e(s);
    auto d = e.on_tick({kSec, 0.20}, kSec);
    EXPECT_EQ(d.action, Action::Hold);
    EXPECT_EQ(d.reason, Reason::Invalid);
  };
  for (double bad : {-1.0, nan, inf}) {
    auto s = fee_spec(); s.gap_per_share = bad; check(s);
    s = fee_spec(); s.fee_per_share = bad; check(s);
    s = fee_spec(); s.half_spread = bad; check(s);
    s = fee_spec(); s.min_benefit_ratio = bad; check(s);
  }
}

TEST(FeeGate, InactiveWhenGapZero) {
  auto s = spec();
  s.fee_per_share = 1000.0;
  s.half_spread = 1000.0;
  Engine e(s);
  auto d = e.on_tick({kSec, 0.20}, kSec);
  EXPECT_EQ(d.action, Action::Order);
}

TEST(FeeGate, ReasonName) { EXPECT_STREQ(to_string(Reason::BelowFees), "below_fees"); }

TEST(FeeGate, BelowFeesHoldKeepsReferencePrice) {
  auto s = fee_spec();
  s.band_shares = 0;
  Engine e(s);
  e.on_tick({kSec, 0.20}, kSec);
  e.on_fill(100);
  auto d1 = e.on_tick({2 * kSec, 0.21}, 2 * kSec);
  EXPECT_EQ(d1.reason, Reason::BelowFees);
  auto d2 = e.on_tick({3 * kSec, 0.22}, 3 * kSec);
  EXPECT_EQ(d2.action, Action::Order);
  EXPECT_DOUBLE_EQ(d2.order_qty, 10.0);
}

TEST(Engine, ZeroQuantityNeverOrders) {
  auto s = spec();
  s.band_shares = 0;
  Engine e(s);
  e.on_tick({kSec, 0.20}, kSec);
  e.on_fill(100);
  auto d = e.on_tick({2 * kSec, 0.2001}, 2 * kSec);
  EXPECT_EQ(d.action, Action::Hold);
  EXPECT_EQ(d.reason, Reason::InsideBand);
  EXPECT_DOUBLE_EQ(d.order_qty, 0.0);
}

TEST(FeeGate, RiskCapAndGateTogether) {
  auto s = fee_spec();
  s.band_shares = 0;
  s.max_hedge_shares = 50;
  {
    Engine e(s);
    auto d = e.on_tick({kSec, 0.20}, kSec);
    EXPECT_EQ(d.action, Action::Order);
    EXPECT_EQ(d.reason, Reason::RiskCapped);
    EXPECT_DOUBLE_EQ(d.order_qty, 50.0);
  }
  {
    s.gap_per_share = 0.001;
    Engine e(s);
    auto d = e.on_tick({kSec, 0.20}, kSec);
    EXPECT_EQ(d.action, Action::Hold);
    EXPECT_EQ(d.reason, Reason::BelowFees);
    EXPECT_DOUBLE_EQ(d.target_hedge, 50.0);
    EXPECT_DOUBLE_EQ(d.order_qty, 0.0);
  }
}
