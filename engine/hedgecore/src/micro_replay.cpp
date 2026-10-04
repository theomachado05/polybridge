#include <algorithm>
#include <cmath>
#include <unordered_map>

#include "hedgecore/micro.hpp"

namespace hedgecore {

namespace {

template <class V>
void latency_pcts(V& lat, std::int64_t& p50, std::int64_t& p99) {
  if (lat.empty()) return;
  auto q = [&](double f) {
    const auto k = static_cast<std::size_t>(f * static_cast<double>(lat.size() - 1));
    std::nth_element(lat.begin(), lat.begin() + static_cast<std::ptrdiff_t>(k), lat.end());
    return lat[k];
  };
  p50 = q(0.50);
  p99 = q(0.99);
}

// Quantity that fills at the quote: up to the quoted size, nothing without a quoted price and size.
double at_quote(double want, double px, double size) noexcept {
  if (!prob(px) || !(size > 0) || !(want > 0)) return 0;
  return std::min(want, size);
}

}  // namespace

LadderReplayStats replay_ladder(const Params& params, std::span<const LadderRow> rows) {
  LadderReplayStats st;
  st.n_rows = rows.size();
  std::unordered_map<std::uint32_t, algos::LadderPair> algo;
  std::unordered_map<std::uint32_t, double> event_held;
  std::vector<std::int64_t> lat;
  lat.reserve(rows.size());
  double sum_pts = 0;
  for (std::size_t r = 0; r < rows.size(); ++r) {
    const LadderRow& row = rows[r];
    auto it = algo.find(row.pair);
    if (it == algo.end()) it = algo.emplace(row.pair, algos::LadderPair(params, Position{})).first;
    algos::LadderPair& a = it->second;
    LadderTick t = row.tick;
    t.event_held = event_held[row.event] - a.held;  // contracts on the event's other pairs

    const PairIntent in = a.on_tick(t, row.now_ns);
    lat.push_back(in.latency_ns);

    if (in.action == MicroAction::Cancel) {  // the venue acknowledges the cancel: the open leg is dead
      a.on_reject(in.cancel);
    } else if (in.action == MicroAction::Unwind) {
      // The unpaired leg would be flattened at the opposite touch, which a LadderTick does not quote: no fill.
      if (in.rich.side != 0) a.on_reject(Leg::Rich);
      if (in.cheap.side != 0) a.on_reject(Leg::Cheap);
      ++st.n_leg_rejects;
    } else if (in.action == MicroAction::Order) {
      ++st.n_orders;
      const double held_before = a.held;
      // Each leg fills at its own quote, up to its quoted size; the remainder is rejected.
      const double q_rich = at_quote(in.rich.qty, t.bid_rich, t.bid_rich_qty);
      const double q_cheap = at_quote(in.cheap.qty, t.ask_cheap, t.ask_cheap_qty);
      if (q_rich > 0) a.on_fill(Leg::Rich, q_rich, t.bid_rich);
      if (q_rich < in.rich.qty) { ++st.n_leg_rejects; a.on_reject(Leg::Rich); }
      if (q_cheap > 0) a.on_fill(Leg::Cheap, q_cheap, t.ask_cheap);
      if (q_cheap < in.cheap.qty) { ++st.n_leg_rejects; a.on_reject(Leg::Cheap); }
      if (a.excess[0] > 0 || a.excess[1] > 0) ++st.n_leg_risk;
      const double m = a.held - held_before;
      if (m > 0) {
        event_held[row.event] += m;
        LadderTrade tr;
        tr.row = r;
        tr.pair = row.pair;
        tr.event = row.event;
        tr.t_entry_ns = row.now_ns;
        tr.qty = m;
        tr.px_rich = t.bid_rich;
        tr.px_cheap = t.ask_cheap;
        tr.fee_rich = poly_taker_fee(t.fee_rate_rich, t.bid_rich);
        tr.fee_cheap = poly_taker_fee(t.fee_rate_cheap, t.ask_cheap);
        const double cap_pc = (1.0 - tr.px_rich) + tr.px_cheap + tr.fee_rich + tr.fee_cheap;
        tr.edge_locked = tr.px_rich - tr.px_cheap - tr.fee_rich - tr.fee_cheap;
        tr.settled = num(row.result_rich) && num(row.result_cheap);
        tr.payoff = tr.settled ? (1.0 - row.result_rich) + row.result_cheap : 1.0;
        tr.pnl_points = 100.0 * (tr.payoff - cap_pc);
        tr.pnl_usd = m * (tr.payoff - cap_pc);
        tr.capital_usd = m * cap_pc;
        sum_pts += tr.pnl_points;
        st.total_pnl_usd += tr.pnl_usd;
        st.total_capital_usd += tr.capital_usd;
        const double over = tr.pnl_points - 100.0 * tr.edge_locked;
        st.min_pnl_minus_edge = std::isnan(st.min_pnl_minus_edge) ? over : std::min(st.min_pnl_minus_edge, over);
        st.trades.push_back(tr);
      }
    }
  }
  st.n_trades = st.trades.size();
  if (st.n_trades) st.mean_pnl_points = sum_pts / static_cast<double>(st.n_trades);
  latency_pcts(lat, st.p50_ns, st.p99_ns);
  return st;
}

TicketReplayStats replay_tickets(const Params& params, std::span<const TicketRow> rows) {
  TicketReplayStats st;
  st.n_rows = rows.size();
  std::unordered_map<std::uint32_t, algos::TouchTicketReference> algo;
  std::unordered_map<std::uint32_t, double> under_short, event_short;
  std::vector<std::int64_t> lat;
  lat.reserve(rows.size());
  for (std::size_t r = 0; r < rows.size(); ++r) {
    const TicketRow& row = rows[r];
    auto it = algo.find(row.ticket);
    if (it == algo.end()) it = algo.emplace(row.ticket, algos::TouchTicketReference(params, Position{})).first;
    auto& a = it->second;
    TicketTick t = row.tick;
    t.underlying_short = under_short[row.underlying] - a.sold;  // the underlying's other tickets
    t.event_short = event_short[row.event] - a.sold;

    const TicketIntent in = a.on_tick(t, row.now_ns);
    lat.push_back(in.latency_ns);
    if (in.action == MicroAction::Hold) continue;
    TicketDecision d;
    d.row = r;
    d.ticket = row.ticket;
    d.action = in.action;
    d.qty = in.qty;
    d.px = in.limit_px;
    d.signal = in.signal;
    d.reason = in.reason;
    if (in.action == MicroAction::Propose) {
      ++st.n_proposals;  // a proposal never trades
    } else if (in.action == MicroAction::Order) {
      ++st.n_orders;
      const double q = (in.limit_px == t.bid) ? at_quote(in.qty, t.bid, t.bid_qty) : 0.0;  // sell at the bid only
      if (q > 0) {
        a.on_fill(q, t.bid);
        under_short[row.underlying] += q;
        event_short[row.event] += q;
        ++st.n_fills;
        d.filled = true;
        d.qty = q;
        if (num(row.outcome)) d.pnl_points = 100.0 * (t.bid - row.outcome);
      }
    }
    st.decisions.push_back(d);
  }
  latency_pcts(lat, st.p50_ns, st.p99_ns);
  return st;
}

}  // namespace hedgecore
