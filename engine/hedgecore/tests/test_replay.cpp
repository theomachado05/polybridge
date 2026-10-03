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

TEST(Replay, ExpiredPassiveOrderIsRequotedEveryTick) {
  // Flat stock: a resting sell at the ask never trades through. The algo re-quotes each tick instead of going quiet.
  std::vector<MarketTick> ticks;
  for (int i = 0; i < 10; ++i) ticks.push_back(pm((i + 1) * kSec, 0.20));
  Position pos;
  pos.shares_held = 1000;
  const ReplayStats s = replay("stress_lead_hedge", find_family("stress_lead_hedge")->spec.defaults(), pos, ticks);
  EXPECT_EQ(s.n_orders, 10u);
  EXPECT_EQ(s.n_fills, 0u);
  EXPECT_EQ(s.n_rejected, 10u);
}

bool is_working(AnyAlgo& a) {
  return std::visit(
      [](auto& x) {
        if constexpr (requires { x.core.working; }) return x.core.working;
        else return false;
      },
      a);
}

TEST(Replay, NoHedgeFamilyStallsBelowFeesMidRebalance) {
  // Every hedge family at default params on a constant-probability path with immediate fills: while an approved
  // rebalance is unfinished, nothing may hold below_fees, and every approved rebalance completes. (A target that
  // grows for another reason, e.g. crypto_reg_hedge's volatility rescale, is a new increment and may be fee-gated.)
  for (const auto& f : catalog().families) {
    if (std::string_view(f.division) != "hedge") continue;
    Position pos;
    pos.shares_held = 1000;
    AnyAlgo a = make_algo(f.id, f.spec.defaults(), pos);
    int orders = 0;
    for (int k = 0; k < 40; ++k) {
      MarketTick t = with_book(pm((k + 1) * kSec, 0.60), 3000, 3000);
      const bool working = is_working(a);
      const Intent i = on_tick(a, t, t.ts_ns);
      if (working) EXPECT_NE(i.reason, code(Rc::BelowFees)) << f.id << " tick " << k;
      if (i.action == Action::Order) {
        ++orders;
        on_fill(a, Instrument::Equity, i.side * i.qty, i.side > 0 ? t.under_ask : t.under_bid);
      }
    }
    EXPECT_GT(orders, 0) << f.id;
    EXPECT_FALSE(is_working(a)) << f.id << " left a rebalance unfinished";
  }
}
