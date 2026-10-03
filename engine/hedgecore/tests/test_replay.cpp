#include <gtest/gtest.h>
#include <cmath>
#include <string_view>
#include <variant>
#include <vector>
#include "hedgecore/replay.hpp"
#include "tick_helpers.hpp"

using namespace hedgecore;
using namespace hctest;

namespace {
// Deterministic synthetic path: the PM adverse probability leads the stock (stock falls as p rises).
std::vector<MarketTick> leading_path(int n = 400) {
  std::vector<MarketTick> v;
  double p = 0.2, u = 100.0;
  std::uint64_t s = 12345;
  for (int i = 0; i < n; ++i) {
    s = s * 6364136223846793005ULL + 1442695040888963407ULL;
    const double z = (static_cast<double>(s >> 11) / 9007199254740992.0) - 0.5;
    const double dp = 0.01 * z + 0.001;  // drifts from 0.2 toward 0.7
    p = std::min(0.95, std::max(0.05, p + dp));
    u = u * (1.0 - 0.5 * dp) + 0.02 * z;
    MarketTick t = with_book(pm((i + 1) * kSec, p, 0.005, u, 0.01), 500, 500);
    t.no_bid = 1 - p - 0.005;
    t.no_ask = 1 - p + 0.005;
    t.p_other_venue = std::min(0.99, std::max(0.01, p - 0.08 * z));
    t.opt_mid = 2.0 + 10 * (p - 0.2);
    t.opt_iv = 0.3 + 0.1 * p;
    t.opt_implied_prob = std::min(1.0, std::max(0.0, p - 0.2 * z));
    t.eightk_score = (i == 100) ? 0.8 : (i == 300 ? -0.8 : 0.0);
    v.push_back(t);
  }
  return v;
}
}  // namespace

TEST(Replay, HandComputedSingleFill) {
  // One tick at p = 0.2: DeltaBridge sells round(0.5 * 1000 * 0.2) = 100 shares at the bid 99.99.
  const std::vector<MarketTick> ticks{pm(kSec, 0.20, 0.005, 100.0, 0.01), pm(2 * kSec, 0.20, 0.005, 101.0, 0.01)};
  Position pos;
  pos.shares_held = 1000;
  const auto* f = find_family("equity_delta_bridge");
  Params p = f->spec.defaults();  // coverage 0.5, band 10, sigma_k 1, fee_ratio 1, impact 0.03
  FeeModel fm;
  const ReplayStats s = replay("equity_delta_bridge", p, pos, ticks, fm);
  EXPECT_EQ(s.n_ticks, 2u);
  EXPECT_EQ(s.n_orders, 1u);
  EXPECT_EQ(s.n_fills, 1u);
  EXPECT_NEAR(s.fees, 100 * 0.0035, 1e-12);
  EXPECT_NEAR(s.turnover, 100 * 99.99, 1e-9);
  // Short 100 @ 99.99 marked at 101: -101 - fee.
  EXPECT_NEAR(s.pnl, 100 * (99.99 - 101.0) - 0.35, 1e-9);
  EXPECT_NEAR(s.max_dd, 0.35 + 101.0, 1e-9);  // peak 0 at start
  // One underlying change: unhedged 1000, hedged 1000 - 100 = 900 -> variance of a single sample is 0 -> NaN.
  EXPECT_TRUE(std::isnan(s.hedge_var_reduction));
  EXPECT_TRUE(std::isnan(s.hedge_var_reduction_vs_static));
  EXPECT_NEAR(s.avg_hedge_ratio, 0.1, 1e-12);  // 100 short over the one interval
  EXPECT_GE(s.p99_ns, s.p50_ns);
}

TEST(Replay, HedgeReducesVarianceOnLeadingPath) {
  const auto ticks = leading_path();
  Position pos;
  pos.shares_held = 1000;
  const auto* f = find_family("equity_delta_bridge");
  Params p = f->spec.defaults();
  p.v[0] = 1.0;  // coverage
  p.v[2] = 0.0;  // sigma gate off
  p.v[4] = 0.0;  // fee gate off
  const ReplayStats s = replay("equity_delta_bridge", p, pos, ticks);
  EXPECT_GT(s.n_fills, 5u);
  ASSERT_TRUE(std::isfinite(s.hedge_var_reduction));
  EXPECT_GT(s.hedge_var_reduction, 0.0);
}

TEST(Replay, DeterministicAcrossRunsExceptLatency) {
  const auto ticks = leading_path();
  Position pos;
  pos.shares_held = 500;
  for (const auto& f : catalog().families) {
    const auto a = replay_grid(f.id, pos, ticks);
    const auto b = replay_grid(f.id, pos, ticks);
    ASSERT_EQ(a.size(), f.preset_count);
    for (std::size_t i = 0; i < a.size(); ++i) {
      EXPECT_EQ(a[i].preset_index, i);
      EXPECT_EQ(a[i].n_orders, b[i].n_orders) << f.id;
      EXPECT_EQ(a[i].n_fills, b[i].n_fills) << f.id;
      EXPECT_EQ(a[i].pnl, b[i].pnl) << f.id;
      EXPECT_EQ(a[i].fees, b[i].fees) << f.id;
      EXPECT_EQ(a[i].max_dd, b[i].max_dd) << f.id;
      EXPECT_EQ(a[i].turnover, b[i].turnover) << f.id;
      const bool both_nan = std::isnan(a[i].hedge_var_reduction) && std::isnan(b[i].hedge_var_reduction);
      EXPECT_TRUE(both_nan || a[i].hedge_var_reduction == b[i].hedge_var_reduction) << f.id;
      const bool vs_nan = std::isnan(a[i].hedge_var_reduction_vs_static) && std::isnan(b[i].hedge_var_reduction_vs_static);
      EXPECT_TRUE(vs_nan || a[i].hedge_var_reduction_vs_static == b[i].hedge_var_reduction_vs_static) << f.id;
    }
  }
}

TEST(Replay, EveryFamilyTradesSomewhereOnTheGrid) {
  const auto ticks = leading_path(600);
  Position pos;
  pos.shares_held = 1000;
  for (const auto& f : catalog().families) {
    std::size_t fills = 0;
    for (const auto& s : replay_grid(f.id, pos, ticks)) fills += s.n_fills;
    EXPECT_GT(fills, 0u) << f.id;
  }
}

TEST(Replay, PassiveLimitFillsOnlyWhenTradedThrough) {
  // stress_lead_hedge in calm joins the touch: sell limit at the ask 100.01; fills next tick only if bid >= 100.01.
  Position pos;
  pos.shares_held = 1000;
  const auto* f = find_family("stress_lead_hedge");
  Params p = f->spec.defaults();
  p.v[5] = 0.0;  // fee gate off
  std::vector<MarketTick> ticks{pm(kSec, 0.2, 0.005, 100.0, 0.01), pm(2 * kSec, 0.2, 0.005, 100.0, 0.01)};
  ReplayStats s = replay("stress_lead_hedge", p, pos, ticks);
  EXPECT_EQ(s.n_orders, 2u);
  EXPECT_EQ(s.n_fills, 0u);  // never traded through
  ticks[1] = pm(2 * kSec, 0.2, 0.005, 100.05, 0.01);  // bid 100.04 >= 100.01
  s = replay("stress_lead_hedge", p, pos, ticks);
  EXPECT_GE(s.n_fills, 1u);
  EXPECT_NEAR(s.turnover, 100 * 100.01, 1e-6);  // slice of 100 at the limit
}

TEST(Replay, MissingPricesRejectInsteadOfFillingAtZero) {
  Position pos;
  pos.shares_held = 1000;
  MarketTick t = pm(kSec, 0.2);
  t.under_px = t.under_bid = t.under_ask = NaN;
  const auto* f = find_family("equity_delta_bridge");
  Params p = f->spec.defaults();
  p.v[4] = 0.0;  // fee gate off so the algo still emits
  const ReplayStats s = replay("equity_delta_bridge", p, pos, std::vector<MarketTick>{t});
  EXPECT_EQ(s.n_orders, 1u);
  EXPECT_EQ(s.n_fills, 0u);
  EXPECT_EQ(s.n_rejected, 1u);
  EXPECT_EQ(s.pnl, 0.0);
}

TEST(Replay, UnknownFamilyThrows) {
  EXPECT_THROW(replay_grid("nope", Position{}, std::vector<MarketTick>{}), std::invalid_argument);
}

TEST(Replay, PassiveSlicedHedgeConvergesWhenTheMarketTradesThrough) {
  // stress_lead_hedge in calm: target 150 in 100-share passive children joining the ask. The stock rises 0.05 a
  // tick, so each resting sell is traded through on the next tick. Both children fill (fee gate on, default impact).
  std::vector<MarketTick> ticks;
  for (int i = 0; i < 12; ++i) ticks.push_back(pm((i + 1) * kSec, 0.20, 0.005, 100.0 + 0.05 * i, 0.01));
  Position pos;
  pos.shares_held = 1000;
  const ReplayStats s = replay("stress_lead_hedge", find_family("stress_lead_hedge")->spec.defaults(), pos, ticks);
  EXPECT_EQ(s.n_fills, 2u);
  EXPECT_EQ(s.n_rejected, 0u);
}

TEST(Replay, ExpiredPassiveOrderIsRequotedWithBackoff) {
  // Flat stock: a resting sell at the ask never trades through. The algo keeps re-quoting instead of going quiet
  // (or fee-gating the approved rebalance), but repeated expiries back off: orders at 1, 2, 3, 5, 9 s.
  std::vector<MarketTick> ticks;
  for (int i = 0; i < 10; ++i) ticks.push_back(pm((i + 1) * kSec, 0.20));
  Position pos;
  pos.shares_held = 1000;
  const ReplayStats s = replay("stress_lead_hedge", find_family("stress_lead_hedge")->spec.defaults(), pos, ticks);
  EXPECT_EQ(s.n_orders, 5u);
  EXPECT_EQ(s.n_fills, 0u);
  EXPECT_EQ(s.n_rejected, 5u);
}

namespace {
constexpr std::int64_t kFri1900 = 1790967600LL * kSec;  // 2026-10-02 15:00 EDT, in session
constexpr std::int64_t kSat1600 = 1791043200LL * kSec;  // 2026-10-03, Saturday
constexpr std::int64_t kMon0930 = 1791207000LL * kSec;  // 2026-10-05 09:30 EDT, session open
constexpr std::int64_t kHour = 3600LL * kSec;
// A recorded tick: PM quote plus an equity bar close with no live quote (as app.pipeline.ticks builds them).
MarketTick bar_tick(std::int64_t ts, double p, double u) {
  MarketTick t = pm(ts, p, 0.005, u, 0.01);
  t.under_bid = t.under_ask = NaN;
  return t;
}
}  // namespace

TEST(Replay, StaleBarCloseIsNotAFillPriceOutOfSession) {
  // The PM jumps on Saturday. The only equity price is Friday's close: the sell is rejected, not filled at it. At
  // Monday's open the as-of close is still Friday's (no bar has closed yet): still rejected. Once the first Monday
  // bar closes (after the gap), the hedge fills there.
  Position pos;
  pos.shares_held = 1000;
  Params p = find_family("equity_delta_bridge")->spec.defaults();
  p.v[0] = 1.0;  // coverage
  p.v[2] = 0.0;  // sigma gate off
  p.v[4] = 0.0;  // fee gate off
  const std::vector<MarketTick> ticks{bar_tick(kSat1600, 0.60, 100.0), bar_tick(kMon0930, 0.60, 100.0),
                                      bar_tick(kMon0930 + kHour, 0.60, 94.0)};
  const ReplayStats s = replay("equity_delta_bridge", p, pos, ticks);
  EXPECT_EQ(s.n_fills, 1u);
  EXPECT_EQ(s.n_rejected, 2u);
  EXPECT_NEAR(s.turnover, 600 * (94.0 - 0.01), 1e-6);  // sold at the post-gap price, not Friday's 100
  EXPECT_LT(s.pnl, 0.0);                              // so the gap is not booked as hedge profit
}

TEST(Replay, FreshBarCloseInSessionFills) {
  Position pos;
  pos.shares_held = 1000;
  Params p = find_family("equity_delta_bridge")->spec.defaults();
  p.v[2] = 0.0;
  p.v[4] = 0.0;
  const std::vector<MarketTick> ticks{bar_tick(kFri1900 - kHour, 0.20, 100.0), bar_tick(kFri1900, 0.20, 100.5)};
  const ReplayStats s = replay("equity_delta_bridge", p, pos, ticks);
  EXPECT_EQ(s.n_fills, 1u);  // the first tick has no prior close to compare (rejected); the second is fresh
  EXPECT_NEAR(s.turnover, 100 * (100.5 - 0.01), 1e-6);
}

TEST(Replay, StaticShortWithConstantPmScoresHighButAddsNothingOverStatic) {
  // A constant PM probability carries no information. equity_delta_bridge at coverage 1 shorts 99% of the shares
  // once and never trades again: hedge_var_reduction ~ 1 - 0.01^2, yet it is exactly what a static short gives.
  std::vector<MarketTick> ticks;
  double u = 100.0;
  std::uint64_t r = 99;
  for (int i = 0; i < 500; ++i) {
    r = r * 6364136223846793005ULL + 1442695040888963407ULL;
    u += (static_cast<double>(r >> 11) / 9007199254740992.0 - 0.5);
    ticks.push_back(pm((i + 1) * kSec, 0.99, 0.005, u, 0.01));
  }
  Position pos;
  pos.shares_held = 1000;
  Params p = find_family("equity_delta_bridge")->spec.defaults();
  p.v[0] = 1.0;
  p.v[2] = 0.0;  // sigma gate off
  const ReplayStats s = replay("equity_delta_bridge", p, pos, ticks);
  EXPECT_EQ(s.n_fills, 1u);
  EXPECT_GT(s.hedge_var_reduction, 0.999);
  EXPECT_NEAR(s.avg_hedge_ratio, 0.99, 1e-12);
  ASSERT_TRUE(std::isfinite(s.hedge_var_reduction_vs_static));
  EXPECT_NEAR(s.hedge_var_reduction_vs_static, 0.0, 1e-6);
}

TEST(Replay, FullStaticHedgeHasNoVsStaticScore) {
  // Already fully hedged and the band never lets it trade: the static benchmark is flat, so no vs-static score.
  Position pos;
  pos.shares_held = 1000;
  pos.equity = -1000;
  Params p = find_family("equity_delta_bridge")->spec.defaults();
  p.v[1] = 1e6;  // band_shares
  std::vector<MarketTick> ticks;
  for (int i = 0; i < 6; ++i) ticks.push_back(pm((i + 1) * kSec, 0.5, 0.005, 100.0 + (i % 2), 0.01));
  const ReplayStats s = replay("equity_delta_bridge", p, pos, ticks);
  EXPECT_EQ(s.n_orders, 0u);
  EXPECT_NEAR(s.avg_hedge_ratio, 1.0, 1e-12);
  EXPECT_NEAR(s.hedge_var_reduction, 1.0, 1e-12);
  EXPECT_TRUE(std::isnan(s.hedge_var_reduction_vs_static));
}
