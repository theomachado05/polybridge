// Spec §8: no heap allocation on the hot path. Counts global operator new calls made while on_tick/on_fill run.
#include <gtest/gtest.h>
#include <atomic>
#include <cstdlib>
#include <new>
#include "hedgecore/library.hpp"
#include "tick_helpers.hpp"

namespace {
std::atomic<bool> g_counting{false};
std::atomic<long> g_allocs{0};
}  // namespace

void* operator new(std::size_t n) {
  if (g_counting.load(std::memory_order_relaxed)) g_allocs.fetch_add(1, std::memory_order_relaxed);
  if (void* p = std::malloc(n ? n : 1)) return p;
  throw std::bad_alloc();
}
void operator delete(void* p) noexcept { std::free(p); }
void operator delete(void* p, std::size_t) noexcept { std::free(p); }

using namespace hedgecore;
using namespace hctest;

TEST(NoAlloc, OnTickAndOnFillNeverAllocate) {
  std::vector<MarketTick> ticks;
  for (int i = 0; i < 2000; ++i) {
    const double p = 0.4 + 0.3 * std::sin(i * 0.05);
    MarketTick t = with_book(pm((i + 1) * kSec, p, 0.005, 100 + 5 * std::sin(i * 0.01), 0.01), 400, 300);
    t.no_bid = 1 - p - 0.005;
    t.no_ask = 1 - p + 0.005;
    t.p_other_venue = p + 0.05 * std::cos(i * 0.3);
    t.opt_mid = 2 + p;
    t.opt_iv = 0.3 + 0.05 * std::cos(i * 0.2);
    t.opt_implied_prob = p - 0.1 * std::cos(i * 0.1);
    t.eightk_score = (i % 400 == 0) ? 0.9 : 0.0;
    if (i % 97 == 0) t.yes_bid = NaN;  // missing fields along the way
    ticks.push_back(t);
  }
  Position pos;
  pos.shares_held = 1000;
  for (const auto& f : catalog().families) {
    AnyAlgo a = make_algo(f.id, f.spec.defaults(), pos);
    std::size_t orders = 0;
    g_allocs = 0;
    g_counting = true;
    for (const auto& t : ticks) {
      const Intent in = on_tick(a, t, t.ts_ns);
      if (in.action == Action::Order) {
        ++orders;
        on_fill(a, in.instrument, in.side * in.qty, in.instrument == Instrument::Equity ? t.under_px : 0.5);
      }
    }
    g_counting = false;
    EXPECT_EQ(g_allocs.load(), 0) << f.id;
    EXPECT_GT(orders, 0u) << f.id << " never traded, so the order path was not exercised";
  }
}

// The shared tape above sits on 1970-01-01 (an NYSE holiday), so closed_session_hedge only takes its closed-market
// path there. This tape crosses a Friday close, the weekend and the Monday open (2026-10-02..05, hourly), with the
// equity handoff on, so the YES unwind and the equity handoff leg run under the counter too.
TEST(NoAlloc, ClosedSessionHedgeAcrossCloseAndOpenNeverAllocates) {
  constexpr std::int64_t kFri1500 = 1790967600LL * kSec;
  std::vector<MarketTick> ticks;
  for (int i = 0; i < 72; ++i) {
    const double p = 0.3 + 0.2 * std::sin(i * 0.2);
    ticks.push_back(pm(kFri1500 + i * 3600LL * kSec, p, 0.005, 100 + 3 * std::sin(i * 0.1), 0.01));
  }
  Position pos;
  pos.shares_held = 1000;
  Params p = algos::ClosedSessionHedge::spec().defaults();
  p.v[algos::ClosedSessionHedge::kHandoffEquity] = 1;
  AnyAlgo a = make_algo("closed_session_hedge", p, pos);
  std::size_t yes_orders = 0, equity_orders = 0, handoffs = 0;
  g_allocs = 0;
  g_counting = true;
  for (const auto& t : ticks) {
    const Intent in = on_tick(a, t, t.ts_ns);
    if (in.action != Action::Order) continue;
    (in.instrument == Instrument::Equity ? equity_orders : yes_orders) += 1;
    handoffs += in.reason == code(Rc::Handoff);
    on_fill(a, in.instrument, in.side * in.qty, in.instrument == Instrument::Equity ? t.under_px : t.yes_ask);
  }
  g_counting = false;
  EXPECT_EQ(g_allocs.load(), 0);
  EXPECT_GT(yes_orders, 0u);
  EXPECT_GT(equity_orders, 0u);
  EXPECT_GE(handoffs, 2u);  // the YES unwind and the first equity order at the Monday open
}
