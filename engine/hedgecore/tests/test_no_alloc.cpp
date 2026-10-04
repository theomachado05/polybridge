#include <gtest/gtest.h>
#include <atomic>
#include <cstdlib>
#include <new>
#include "hedgecore/library.hpp"
#include "hedgecore/micro.hpp"
#include "tick_helpers.hpp"

namespace {
std::atomic<bool> g_counting{false};
std::atomic<long> g_allocs{0};
}

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
    if (i % 97 == 0) t.yes_bid = NaN;
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
  EXPECT_GE(handoffs, 2u);
}

TEST(NoAlloc, MicroFamiliesNeverAllocate) {
  algos::LadderPair lp(algos::LadderPair::spec().defaults(), Position{});
  algos::TouchTicketReference tt(algos::TouchTicketReference::spec().defaults(), Position{});
  std::vector<LadderTick> lt;
  std::vector<TicketTick> tk;
  for (int i = 0; i < 4000; ++i) {
    LadderTick t;
    t.ts_ns = (i + 1) * 900LL * kSec;
    t.bid_rich = 0.50 + 0.05 * std::sin(i * 0.3);
    t.ask_cheap = 0.48;
    t.bid_rich_qty = 30;
    t.ask_cheap_qty = 20 + (i % 5);
    t.fee_rate_rich = t.fee_rate_cheap = 0.02;
    t.tick = 0.01;
    t.ts_rich_ns = t.ts_cheap_ns = t.ts_ns;
    t.nested = (i % 9 == 0) ? Tri::Missing : Tri::True;
    t.event_held = 0;
    lt.push_back(t);
    TicketTick k;
    k.ts_ns = t.ts_ns;
    k.bid = 0.30 + 0.1 * std::sin(i * 0.2);
    k.bid_qty = 50;
    k.ref_central = 0.28;
    k.validated = (i % 2) ? Tri::True : Tri::False;
    k.underlying_short = k.event_short = 0;
    tk.push_back(k);
  }
  std::size_t ladder_orders = 0, ticket_orders = 0, proposals = 0;
  g_allocs = 0;
  g_counting = true;
  for (std::size_t i = 0; i < lt.size(); ++i) {
    const PairIntent in = lp.on_tick(lt[i], lt[i].ts_ns);
    if (in.action == MicroAction::Order) {
      ++ladder_orders;
      lp.on_fill(Leg::Rich, in.rich.qty, in.rich.limit_px);
      if (i % 7 == 0) lp.on_reject(Leg::Cheap);
      else lp.on_fill(Leg::Cheap, in.cheap.qty, in.cheap.limit_px);
    } else if (in.action == MicroAction::Unwind) {
      lp.on_fill(in.rich.side ? Leg::Rich : Leg::Cheap, in.rich.side ? in.rich.qty : in.cheap.qty, 0.5);
    }
    const TicketIntent ti = tt.on_tick(tk[i], tk[i].ts_ns);
    if (ti.action == MicroAction::Order) { ++ticket_orders; tt.on_fill(1, ti.limit_px); }
    proposals += ti.action == MicroAction::Propose;
  }
  g_counting = false;
  EXPECT_EQ(g_allocs.load(), 0);
  EXPECT_GT(ladder_orders, 0u);
  EXPECT_GT(ticket_orders, 0u);
  EXPECT_GT(proposals, 0u);
}
