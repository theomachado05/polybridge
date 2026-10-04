#include <gtest/gtest.h>
#include <cmath>
#include <cstdio>
#include <set>
#include <string>
#include <vector>
#include "csv_reader.hpp"
#include "hedgecore/micro.hpp"
#include "tick_helpers.hpp"

using namespace hedgecore;
using namespace hctest;
using algos::LadderPair;

namespace {

Params ladder_params(double min_edge, double max_age_s, double cap, double event_cap = 1000, double cooldown_s = 3600) {
  Params p = LadderPair::spec().defaults();
  p.v[LadderPair::kMinEdge] = min_edge;
  p.v[LadderPair::kMaxAge] = max_age_s;
  p.v[LadderPair::kCap] = cap;
  p.v[LadderPair::kEventCap] = event_cap;
  p.v[LadderPair::kCooldown] = cooldown_s;
  return p;
}

LadderTick quote(double bid_rich, double ask_cheap, double qty = 50, double fee_rate = 0.0, std::int64_t ts = kSec,
                 Tri nested = Tri::True) {
  LadderTick t;
  t.ts_ns = ts;
  t.bid_rich = bid_rich;
  t.bid_rich_qty = qty;
  t.ask_cheap = ask_cheap;
  t.ask_cheap_qty = qty;
  t.fee_rate_rich = fee_rate;
  t.fee_rate_cheap = fee_rate;
  t.tick = 0.01;
  t.ts_rich_ns = ts;
  t.ts_cheap_ns = ts;
  t.nested = nested;
  t.event_held = 0;
  return t;
}

LadderRow row_of(const LadderTick& t, double yr, double yc, std::uint32_t pair = 1, std::uint32_t event = 1) {
  LadderRow r;
  r.tick = t;
  r.now_ns = t.ts_ns;
  r.pair = pair;
  r.event = event;
  r.result_rich = yr;
  r.result_cheap = yc;
  return r;
}

}

TEST(LadderPair, PnlAtResultNeverBelowLockedEdgeInAllThreeOutcomes) {
  const double outcomes[3][2] = {{1, 1}, {0, 1}, {0, 0}};
  std::uint64_t s = 7;
  int checked = 0;
  for (int k = 0; k < 2000; ++k) {
    s = s * 6364136223846793005ULL + 1442695040888963407ULL;
    const double u1 = static_cast<double>(s >> 11) / 9007199254740992.0;
    s = s * 6364136223846793005ULL + 1442695040888963407ULL;
    const double u2 = static_cast<double>(s >> 11) / 9007199254740992.0;
    const double ask = std::round(100 * (0.02 + 0.9 * u1)) / 100;
    const double bid = std::min(0.99, ask + std::round(100 * 0.15 * u2) / 100);
    const double fee_rate = (k % 3) * 0.02;
    for (const auto& o : outcomes) {
      const std::vector<LadderRow> rows{row_of(quote(bid, ask, 37, fee_rate), o[0], o[1])};
      const auto st = replay_ladder(ladder_params(1, 30, 100), rows);
      for (const auto& tr : st.trades) {
        ++checked;
        EXPECT_TRUE(tr.settled);
        EXPECT_GE(tr.pnl_points, 100.0 * tr.edge_locked - 1e-9) << bid << " " << ask << " " << o[0] << o[1];
        EXPECT_GE(tr.edge_locked, 0.01 + 0.01 - 1e-9);
      }
    }
  }
  EXPECT_GT(checked, 1000);
}

TEST(LadderPair, ExactNumbersForOneEntry) {
  LadderPair a(ladder_params(1, 30, 100), Position{});
  const PairIntent in = a.on_tick(quote(0.62, 0.55, 40, 0.02), kSec);
  ASSERT_EQ(in.action, MicroAction::Order);
  EXPECT_EQ(in.reason, code(Rc::Entry));
  EXPECT_EQ(in.rich.side, -1);
  EXPECT_EQ(in.cheap.side, +1);
  EXPECT_DOUBLE_EQ(in.rich.qty, 40);
  EXPECT_DOUBLE_EQ(in.cheap.qty, 40);
  EXPECT_DOUBLE_EQ(in.rich.limit_px, 0.62);
  EXPECT_DOUBLE_EQ(in.cheap.limit_px, 0.55);
  EXPECT_NEAR(in.signal, 100 * (0.07 - 0.004712 - 0.00495 - 0.01), 1e-9);
  EXPECT_GE(in.latency_ns, 0);
}

TEST(LadderPair, RefusesPairNotMarkedNested) {
  for (const Tri n : {Tri::False, Tri::Missing}) {
    LadderPair a(ladder_params(1, 30, 100), Position{});
    const PairIntent in = a.on_tick(quote(0.80, 0.50, 50, 0, kSec, n), kSec);
    EXPECT_EQ(in.action, MicroAction::Hold);
    EXPECT_EQ(in.reason, code(Rc::NotNested));
  }
  LadderTick unset = quote(0.80, 0.50);
  unset.nested = LadderTick{}.nested;
  LadderPair b(ladder_params(1, 30, 100), Position{});
  EXPECT_EQ(b.on_tick(unset, kSec).reason, code(Rc::NotNested));
  LadderPair c(ladder_params(1, 30, 100), Position{});
  EXPECT_EQ(c.on_tick(quote(0.80, 0.50), kSec).action, MicroAction::Order);
}

TEST(LadderPair, FreshnessFeeGateCapsAndCooldown) {
  {
    LadderPair a(ladder_params(1, 30, 100), Position{});
    LadderTick t = quote(0.80, 0.50, 50, 0, 40 * kSec);
    t.ts_cheap_ns = 9 * kSec;
    EXPECT_EQ(a.on_tick(t, 40 * kSec).reason, code(Rc::Stale));
    t.ts_cheap_ns = kNoTime;
    EXPECT_EQ(a.on_tick(t, 40 * kSec).reason, code(Rc::Stale));
    t.ts_cheap_ns = 41 * kSec;
    EXPECT_EQ(a.on_tick(t, 40 * kSec).reason, code(Rc::Stale));
  }
  {
    LadderPair a2(ladder_params(2, 30, 100), Position{}), a3(ladder_params(3, 30, 100), Position{});
    EXPECT_EQ(a2.on_tick(quote(0.53, 0.50), kSec).action, MicroAction::Order);
    EXPECT_EQ(a3.on_tick(quote(0.53, 0.50), kSec).reason, code(Rc::BelowFees));
  }
  {
    LadderPair a(ladder_params(1, 30, 100), Position{});
    LadderTick t = quote(0.80, 0.50);
    t.fee_rate_rich = NaN;
    EXPECT_EQ(a.on_tick(t, kSec).reason, code(Rc::FeeUnknown));
  }
  {
    LadderPair a(ladder_params(1, 30, 100), Position{});
    LadderTick t = quote(0.80, 0.50);
    t.bid_rich_qty = 700;
    t.ask_cheap_qty = 300;
    const PairIntent in = a.on_tick(t, kSec);
    EXPECT_DOUBLE_EQ(in.rich.qty, 100);
    EXPECT_EQ(in.reason, code(Rc::PositionCapped));
  }
  {
    LadderPair a(ladder_params(1, 30, 100, 120), Position{});
    LadderTick t = quote(0.80, 0.50);
    t.event_held = 100;
    const PairIntent in = a.on_tick(t, kSec);
    EXPECT_DOUBLE_EQ(in.rich.qty, 20);
    LadderPair b(ladder_params(1, 30, 100, 120), Position{});
    t.event_held = 120;
    EXPECT_EQ(b.on_tick(t, kSec).reason, code(Rc::EventCapped));
    LadderPair c(ladder_params(1, 30, 100, 120), Position{});
    t.event_held = NaN;
    EXPECT_EQ(c.on_tick(t, kSec).reason, code(Rc::PositionUnknown));
  }
  {
    LadderPair a(ladder_params(1, 30, 100), Position{});
    ASSERT_EQ(a.on_tick(quote(0.80, 0.50, 10), kSec).action, MicroAction::Order);
    a.on_fill(Leg::Rich, 10, 0.80);
    a.on_fill(Leg::Cheap, 10, 0.50);
    EXPECT_DOUBLE_EQ(a.held, 10);
    EXPECT_NEAR(a.capital.locked, 10 * (0.20 + 0.50), 1e-12);
    EXPECT_EQ(a.on_tick(quote(0.80, 0.50, 10, 0, 100 * kSec), 100 * kSec).reason, code(Rc::Cooldown));
    EXPECT_EQ(a.on_tick(quote(0.80, 0.50, 10, 0, 3601 * kSec), 3601 * kSec).action, MicroAction::Order);
  }
}

TEST(LadderPair, LegRiskGuardCancelsUnwindsAndFlags) {
  {
    LadderPair a(ladder_params(1, 30, 100), Position{});
    ASSERT_EQ(a.on_tick(quote(0.80, 0.50, 10), kSec).action, MicroAction::Order);
    a.on_reject(Leg::Rich);
    const PairIntent c = a.on_tick(quote(0.80, 0.50, 10), kSec);
    EXPECT_EQ(c.action, MicroAction::Cancel);
    EXPECT_EQ(c.cancel, Leg::Cheap);
    EXPECT_EQ(c.reason, code(Rc::LegRisk));
    a.on_reject(Leg::Cheap);
    EXPECT_FALSE(a.flagged);
    EXPECT_DOUBLE_EQ(a.held, 0);
  }
  {
    LadderPair a(ladder_params(1, 30, 100), Position{});
    ASSERT_EQ(a.on_tick(quote(0.80, 0.50, 10), kSec).action, MicroAction::Order);
    a.on_fill(Leg::Cheap, 10, 0.50);
    EXPECT_EQ(a.on_tick(quote(0.80, 0.50, 10), kSec).reason, code(Rc::Working));
    a.on_fill(Leg::Rich, 4, 0.80);
    a.on_reject(Leg::Rich);
    EXPECT_TRUE(a.flagged);
    EXPECT_DOUBLE_EQ(a.held, 4);
    const PairIntent u = a.on_tick(quote(0.80, 0.50, 10), 2 * kSec);
    ASSERT_EQ(u.action, MicroAction::Unwind);
    EXPECT_EQ(u.cheap.side, -1);
    EXPECT_DOUBLE_EQ(u.cheap.qty, 6);
    EXPECT_EQ(u.rich.side, 0);
    EXPECT_EQ(a.on_tick(quote(0.80, 0.50, 10), 3 * kSec).reason, code(Rc::LegRisk));
    a.on_reject(Leg::Cheap);
    EXPECT_EQ(a.on_tick(quote(0.80, 0.50, 10), 4 * kSec).action, MicroAction::Unwind);
    a.on_fill(Leg::Cheap, 6, 0.49);
    const PairIntent after = a.on_tick(quote(0.80, 0.50, 10, 0, 9000 * kSec), 9000 * kSec);
    EXPECT_EQ(after.action, MicroAction::Hold);
    EXPECT_EQ(after.reason, code(Rc::LegRisk));
    EXPECT_EQ(a.leg_risk_events, 1u);
  }
  {
    LadderPair a(ladder_params(1, 30, 100), Position{});
    a.on_fill(Leg::Rich, 5, 0.5);
    EXPECT_EQ(a.on_tick(quote(0.80, 0.50), kSec).reason, code(Rc::InvalidState));
  }
}

namespace {
struct FreshRows {
  std::vector<LadderRow> rows;
  double research_mean = 0;
  std::size_t research_n = 0;
};

FreshRows fresh_rows(double tick) {
  const auto csv = read_csv(std::string(HEDGECORE_TEST_DIR) +
                            "/../../../research/results/ladder_replay/order_check/trades_fresh.csv");
  FreshRows out;
  std::map<std::string, std::uint32_t> pair_id, event_id;
  for (std::size_t r = 0; r < csv.rows.size(); ++r) {
    const double rich = to_d(csv.at(r, "fill_rich")), cheap = to_d(csv.at(r, "fill_cheap"));
    const double fr = to_d(csv.at(r, "fee_rich")), fc = to_d(csv.at(r, "fee_cheap"));
    const double size = to_d(csv.at(r, "print_size"));
    LadderRow row;
    row.tick.ts_ns = static_cast<std::int64_t>(to_d(csv.at(r, "t_entry"))) * kSec;
    row.tick.bid_rich = rich;
    row.tick.bid_rich_qty = size;
    row.tick.ask_cheap = cheap;
    row.tick.ask_cheap_qty = size;
    row.tick.fee_rate_rich = fr == 0 ? 0.0 : fr / (rich * (1 - rich));
    row.tick.fee_rate_cheap = fc == 0 ? 0.0 : fc / (cheap * (1 - cheap));
    row.tick.tick = tick;
    row.tick.ts_rich_ns = static_cast<std::int64_t>(to_d(csv.at(r, "t_print_rich"))) * kSec;
    row.tick.ts_cheap_ns = static_cast<std::int64_t>(to_d(csv.at(r, "t_print_cheap"))) * kSec;
    row.tick.nested = Tri::True;
    row.now_ns = row.tick.ts_ns;
    row.pair = pair_id.emplace(csv.at(r, "pair"), static_cast<std::uint32_t>(pair_id.size())).first->second;
    row.event = event_id.emplace(csv.at(r, "event"), static_cast<std::uint32_t>(event_id.size())).first->second;
    if (to_d(csv.at(r, "settled")) == 1) {
      row.result_rich = to_d(csv.at(r, "result_rich"));
      row.result_cheap = to_d(csv.at(r, "result_cheap"));
    }
    out.rows.push_back(row);
    out.research_mean += to_d(csv.at(r, "pnl_points"));
  }
  out.research_n = csv.rows.size();
  out.research_mean /= static_cast<double>(out.research_n);
  std::stable_sort(out.rows.begin(), out.rows.end(),
                   [](const LadderRow& a, const LadderRow& b) { return a.now_ns < b.now_ns; });
  return out;
}
}

TEST(LadderPair, ReplayOfFreshOrderCheckTradesReproducesCountAndMean) {
  const FreshRows f = fresh_rows(0.0);
  ASSERT_EQ(f.research_n, 562u);
  const auto st = replay_ladder(ladder_params(0, 60, 100, 0, 3600), f.rows);
  std::printf("research: %zu trades, mean %+.4f points | family replay: %zu trades, mean %+.4f points, "
              "$%.2f on $%.2f, leg rejects %zu\n",
              f.research_n, f.research_mean, st.n_trades, st.mean_pnl_points, st.total_pnl_usd, st.total_capital_usd,
              st.n_leg_rejects);
  EXPECT_EQ(st.n_trades, f.research_n);
  EXPECT_NEAR(st.mean_pnl_points, f.research_mean, 1e-9);
  EXPECT_EQ(std::round(100 * st.mean_pnl_points) / 100, 8.82);
  EXPECT_EQ(st.n_leg_rejects, 0u);
  EXPECT_GE(st.min_pnl_minus_edge, -1e-9);
}

TEST(LadderPair, PresetsOnFreshOrderCheckRows) {
  const FreshRows f = fresh_rows(0.01);
  const ParamSpec s = LadderPair::spec();
  ASSERT_EQ(s.preset_count(), 18u);
  std::printf("preset min_edge max_age cap | trades mean_points total_usd\n");
  for (std::size_t i = 0; i < s.preset_count(); ++i) {
    const Params p = s.preset(i);
    const auto st = replay_ladder(p, f.rows);
    std::printf("p%-2zu %4.0f %5.0f %5.0f | %4zu %+8.3f %9.2f\n", i, p.v[0], p.v[1], p.v[2], st.n_trades,
                st.mean_pnl_points, st.total_pnl_usd);
    EXPECT_LE(st.n_trades, f.research_n);
    if (st.n_trades) EXPECT_GE(st.min_pnl_minus_edge, -1e-9);
  }
}
