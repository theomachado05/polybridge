#include <gtest/gtest.h>
#include <cmath>
#include <cstdio>
#include <map>
#include <set>
#include <string>
#include <vector>
#include "csv_reader.hpp"
#include "hedgecore/micro.hpp"
#include "tick_helpers.hpp"

using namespace hedgecore;
using namespace hctest;
using algos::TouchTicketReference;

namespace {

Params ticket_params(double ticket_cap = 100, double under_cap = 300, double event_cap = 300) {
  Params p = TouchTicketReference::spec().defaults();
  p.v[TouchTicketReference::kTicketCap] = ticket_cap;
  p.v[TouchTicketReference::kUnderlyingCap] = under_cap;
  p.v[TouchTicketReference::kEventCap] = event_cap;
  return p;
}

TicketTick ticket(double bid, double central, Tri validated, double qty = 80, std::int64_t ts = kSec) {
  TicketTick t;
  t.ts_ns = ts;
  t.bid = bid;
  t.bid_qty = qty;
  t.ask = bid + 0.02;
  t.ref_lower = central - 0.05;
  t.ref_central = central;
  t.validated = validated;
  t.underlying_short = 0;
  t.event_short = 0;
  return t;
}

}  // namespace

// (a) While validated is not True, no tick can produce a live order: random books, references, sizes, positions and
// missing fields, with validated False or Missing.
TEST(TouchTicketReference, NoLiveOrderWhileUnvalidated) {
  std::uint64_t s = 99;
  auto u = [&] {
    s = s * 6364136223846793005ULL + 1442695040888963407ULL;
    return static_cast<double>(s >> 11) / 9007199254740992.0;
  };
  std::size_t proposals = 0;
  for (const Tri v : {Tri::False, Tri::Missing}) {
    TouchTicketReference a(ticket_params(), Position{});
    for (int k = 0; k < 50000; ++k) {
      TicketTick t = ticket(u(), u(), v, 1 + 500 * u(), k * kSec);
      if (k % 11 == 0) t.ref_central = NaN;
      if (k % 13 == 0) t.underlying_short = NaN;
      if (k % 17 == 0) t.event_short = 1000 * u();
      const TicketIntent in = a.on_tick(t, k * kSec);
      ASSERT_NE(in.action, MicroAction::Order) << "tick " << k;
      if (in.action == MicroAction::Propose) {
        ++proposals;
        EXPECT_EQ(in.reason, code(Rc::Proposal));
        EXPECT_EQ(in.side, -1);
        EXPECT_DOUBLE_EQ(in.limit_px, t.bid);  // at the quoted bid
      }
    }
  }
  EXPECT_GT(proposals, 1000u);  // the proposal path really ran
  {  // a caller that records a fill against a proposal does not unlock live orders either
    TouchTicketReference c(ticket_params(0, 0, 0), Position{});
    for (int k = 0; k < 100; ++k) {
      const TicketIntent in = c.on_tick(ticket(0.60, 0.30, Tri::False), kSec);
      ASSERT_EQ(in.action, MicroAction::Propose);
      c.on_fill(in.qty, in.limit_px);
    }
  }
  TicketTick unset = ticket(0.40, 0.30, Tri::True);
  unset.validated = TicketTick{}.validated;  // the default of a tick nobody filled in
  TouchTicketReference b(ticket_params(), Position{});
  EXPECT_EQ(b.on_tick(unset, kSec).action, MicroAction::Propose);
}

TEST(TouchTicketReference, RuleCapsAndValidatedPath) {
  TouchTicketReference a(ticket_params(), Position{});
  EXPECT_EQ(a.on_tick(ticket(0.349, 0.30, Tri::False), kSec).reason, code(Rc::NoSignal));  // 4.9 points
  const TicketIntent p = a.on_tick(ticket(0.35, 0.30, Tri::False), kSec);                // 5 points
  EXPECT_EQ(p.action, MicroAction::Propose);
  EXPECT_NEAR(p.signal, 5.0, 1e-9);
  EXPECT_DOUBLE_EQ(p.qty, 80);
  TouchTicketReference b(ticket_params(), Position{});
  const TicketIntent o = b.on_tick(ticket(0.40, 0.30, Tri::True, 250), kSec);
  EXPECT_EQ(o.action, MicroAction::Order);
  EXPECT_DOUBLE_EQ(o.qty, 100);  // ticket cap
  EXPECT_EQ(o.reason, code(Rc::PositionCapped));
  TicketTick t = ticket(0.40, 0.30, Tri::True);
  t.underlying_short = 260;  // 40 left under the underlying cap
  TouchTicketReference c(ticket_params(), Position{});
  EXPECT_DOUBLE_EQ(c.on_tick(t, kSec).qty, 40);
  t.event_short = 300;
  EXPECT_EQ(c.on_tick(t, kSec).reason, code(Rc::EventCapped));
  t.event_short = NaN;
  EXPECT_EQ(c.on_tick(t, kSec).reason, code(Rc::PositionUnknown));
  TicketTick crossed = ticket(0.40, 0.30, Tri::True);
  crossed.ask = 0.39;
  EXPECT_EQ(c.on_tick(crossed, kSec).reason, code(Rc::Invalid));
  EXPECT_EQ(c.on_tick(ticket(0.40, 0.30, Tri::True, 80, kSec), 40 * kSec).reason, code(Rc::Stale));
}

// (b) Replay of research/results/s21_options_anchor/trades.csv: every market of the U-all book (all 303 stock and
// S&P markets with a seller P&L) as one tick: bid = its traded price, size = its printed size, central reference = the
// anchor S21 computed (from the U book; markets with no usable anchor get NaN), validated = False. With the caps off,
// the markets the family proposes must be exactly the 60 of S21's primary book B0.
namespace {
struct S21 {
  std::vector<TicketRow> rows;
  std::vector<std::string> market;
  std::set<std::string> b0;
};
S21 s21_rows() {
  const auto csv = read_csv(std::string(HEDGECORE_TEST_DIR) + "/../../../research/results/s21_options_anchor/trades.csv");
  std::map<std::string, double> anchor;
  S21 out;
  for (std::size_t r = 0; r < csv.rows.size(); ++r) {
    if (csv.at(r, "book") == "U") anchor[csv.at(r, "market")] = to_d(csv.at(r, "anchor"));
    if (csv.at(r, "book") == "B0") out.b0.insert(csv.at(r, "market"));
  }
  std::map<std::string, std::uint32_t> und, ev;
  for (std::size_t r = 0; r < csv.rows.size(); ++r) {
    if (csv.at(r, "book") != "U-all") continue;
    const std::string m = csv.at(r, "market");
    TicketRow row;
    row.tick.ts_ns = kSec;
    row.tick.bid = to_d(csv.at(r, "traded_price"));
    row.tick.bid_qty = to_d(csv.at(r, "printed_size"));
    row.tick.ref_central = anchor.count(m) ? anchor[m] : NaN;
    row.tick.validated = Tri::False;
    row.now_ns = kSec;
    row.ticket = static_cast<std::uint32_t>(out.market.size());
    row.underlying = und.emplace(csv.at(r, "ticker"), static_cast<std::uint32_t>(und.size())).first->second;
    row.event = ev.emplace(csv.at(r, "event"), static_cast<std::uint32_t>(ev.size())).first->second;
    row.outcome = to_d(csv.at(r, "outcome"));
    out.rows.push_back(row);
    out.market.push_back(m);
  }
  return out;
}
}  // namespace

TEST(TouchTicketReference, ReplayOfS21SelectsTheSame60Markets) {
  const S21 d = s21_rows();
  ASSERT_EQ(d.rows.size(), 303u);
  ASSERT_EQ(d.b0.size(), 60u);
  const auto st = replay_tickets(ticket_params(0, 0, 0), d.rows);
  std::set<std::string> chosen;
  for (const auto& dec : st.decisions) {
    EXPECT_EQ(dec.action, MicroAction::Propose);
    chosen.insert(d.market[dec.ticket]);
  }
  EXPECT_EQ(st.n_orders, 0u);
  EXPECT_EQ(st.n_fills, 0u);
  EXPECT_EQ(chosen, d.b0);
  const auto capped = replay_tickets(ticket_params(), d.rows);  // the default caps, for the record
  std::printf("S21 B0: %zu markets | family, caps off: %zu proposals | default caps: %zu proposals, 0 orders\n",
              d.b0.size(), st.n_proposals, capped.n_proposals);
  EXPECT_EQ(capped.n_orders, 0u);
}
