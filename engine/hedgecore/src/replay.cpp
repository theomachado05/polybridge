#include "hedgecore/replay.hpp"

#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <string>

namespace hedgecore {

namespace {
bool here(Venue v, const MarketTick& t) noexcept { return v == t.venue; }
double pm_px(double x) noexcept { return prob(x) ? x : kNaN; }
}  // namespace

double touch_price(Instrument inst, int side, Venue venue, const MarketTick& t, const FeeModel& fm) noexcept {
  switch (inst) {
    case Instrument::Equity: {
      const double q = side > 0 ? t.under_ask : t.under_bid;
      if (num(q) && q > 0) return q;
      const double u = under_ref(t);
      return num(u) ? u + side * fm.equity_half_spread : kNaN;
    }
    case Instrument::PredYes:
      if (here(venue, t)) {
        const double q = side > 0 ? t.yes_ask : t.yes_bid;
        if (prob(q)) return q;
        const double par = side > 0 ? t.no_bid : t.no_ask;  // YES ask == 1 - NO bid
        return prob(par) ? 1.0 - par : kNaN;
      }
      return prob(t.p_other_venue) ? pm_px(t.p_other_venue + side * fm.other_venue_half_spread) : kNaN;
    case Instrument::PredNo:
      if (here(venue, t)) {
        const double q = side > 0 ? t.no_ask : t.no_bid;
        if (prob(q)) return q;
        const double par = side > 0 ? t.yes_bid : t.yes_ask;
        return prob(par) ? 1.0 - par : kNaN;
      }
      return prob(t.p_other_venue) ? pm_px(1.0 - t.p_other_venue + side * fm.other_venue_half_spread) : kNaN;
    case Instrument::Option:
      return (num(t.opt_mid) && t.opt_mid >= 0) ? std::max(0.0, t.opt_mid + side * fm.option_half_spread) : kNaN;
  }
  return kNaN;
}

double mark_price(Instrument inst, Venue venue, const MarketTick& t) noexcept {
  switch (inst) {
    case Instrument::Equity: return under_ref(t);
    case Instrument::PredYes: {
      if (!here(venue, t)) return prob(t.p_other_venue) ? t.p_other_venue : kNaN;
      return blocks::ImpliedProb::read(t);
    }
    case Instrument::PredNo: {
      if (!here(venue, t)) return prob(t.p_other_venue) ? 1.0 - t.p_other_venue : kNaN;
      const double y = blocks::ImpliedProb::read(t);
      return num(y) ? 1.0 - y : kNaN;
    }
    case Instrument::Option: return (num(t.opt_mid) && t.opt_mid >= 0) ? t.opt_mid : kNaN;
  }
  return kNaN;
}

ReplayStats replay_algo(AnyAlgo& algo, const Position& pos, std::span<const MarketTick> ticks, const FeeModel& fm) {
  ReplayStats st;
  st.n_ticks = ticks.size();
  double book[4][2] = {};  // [instrument][venue]
  double mark[4][2];
  for (auto& r : mark) r[0] = r[1] = kNaN;
  double cash = 0;
  const double init[4] = {pos.equity, pos.pred_yes, pos.pred_no, pos.option};
  bool init_done[4] = {init[0] == 0, init[1] == 0, init[2] == 0, init[3] == 0};

  bool has_pending = false;
  Intent pending{};

  std::vector<std::int64_t> lat;
  lat.reserve(ticks.size());
  std::vector<double> d_unhedged, d_hedged;
  double peak = 0, prev_u = kNaN, prev_eq_u = 0;

  auto fill = [&](Instrument inst, int side, double qty, double px, Venue v) {
    const int ii = static_cast<int>(inst), vi = static_cast<int>(v);
    const double mult = fm.multiplier(inst);
    const double f = fm.fee(inst, v, qty, px);
    const double fee = num(f) ? f : 0.0;
    cash -= side * qty * px * mult + fee;
    book[ii][vi] += side * qty;
    if (!num(mark[ii][vi])) mark[ii][vi] = px;
    st.fees += fee;
    st.turnover += qty * px * mult;
    ++st.n_fills;
    on_fill(algo, inst, side * qty, px);
  };

  for (const MarketTick& t : ticks) {
    for (int i = 0; i < 4; ++i)
      for (int v = 0; v < 2; ++v) {
        const double m = mark_price(static_cast<Instrument>(i), static_cast<Venue>(v), t);
        if (num(m)) mark[i][v] = m;
      }
    const int hv = static_cast<int>(t.venue);
    for (int i = 0; i < 4; ++i)  // pre-existing positions enter the book at their first known mark (value 0 at start)
      if (!init_done[i] && num(mark[i][hv])) {
        book[i][hv] += init[i];
        cash -= init[i] * mark[i][hv] * fm.multiplier(static_cast<Instrument>(i));
        init_done[i] = true;
      }

    if (has_pending) {  // a resting passive limit fills at its limit only if this tick trades through it
      has_pending = false;
      const double opp = touch_price(pending.instrument, pending.side, pending.venue, t, fm);
      const bool through = num(opp) && (pending.side > 0 ? opp <= pending.limit_px : opp >= pending.limit_px);
      if (through) fill(pending.instrument, pending.side, pending.qty, pending.limit_px, pending.venue);
      else { ++st.n_rejected; on_reject(algo, pending.instrument); }
    }

    const std::int64_t t0 = mono_ns();
    const Intent in = on_tick(algo, t, t.ts_ns);
    lat.push_back(mono_ns() - t0);

    if (in.action == Action::Order) {
      ++st.n_orders;
      const double px = touch_price(in.instrument, in.side, in.venue, t, fm);
      const bool ok_qty = num(in.qty) && in.qty > 0 && (in.side == 1 || in.side == -1);
      if (!ok_qty || !num(px)) {
        ++st.n_rejected;
        on_reject(algo, in.instrument);
      } else if (!num(in.limit_px) || (in.side > 0 ? px <= in.limit_px : px >= in.limit_px)) {
        fill(in.instrument, in.side, in.qty, px, in.venue);  // marketable (or a limit that is already through)
      } else {
        pending = in;
        has_pending = true;
      }
    }

    double eq = cash;
    for (int i = 0; i < 4; ++i)
      for (int v = 0; v < 2; ++v)
        if (book[i][v] != 0 && num(mark[i][v])) eq += book[i][v] * mark[i][v] * fm.multiplier(static_cast<Instrument>(i));
    peak = std::max(peak, eq);
    st.max_dd = std::max(st.max_dd, peak - eq);
    st.pnl = eq;

    const double u = under_ref(t);
    if (pos.shares_held > 0 && num(u)) {
      if (num(prev_u)) {
        const double du = pos.shares_held * (u - prev_u);
        d_unhedged.push_back(du);
        d_hedged.push_back(du + (eq - prev_eq_u));
      }
      prev_u = u;
      prev_eq_u = eq;
    }
  }
  if (has_pending) ++st.n_rejected;

  if (!lat.empty()) {
    auto q = [&](double f) {
      const auto k = static_cast<std::size_t>(f * static_cast<double>(lat.size() - 1));
      std::nth_element(lat.begin(), lat.begin() + static_cast<std::ptrdiff_t>(k), lat.end());
      return lat[k];
    };
    st.p50_ns = q(0.50);
    st.p99_ns = q(0.99);
  }
  if (d_unhedged.size() >= 2) {
    auto var = [](const std::vector<double>& x) {
      double m = 0;
      for (double v : x) m += v;
      m /= static_cast<double>(x.size());
      double s = 0;
      for (double v : x) s += (v - m) * (v - m);
      return s / static_cast<double>(x.size());
    };
    const double vu = var(d_unhedged);
    if (vu > 0) st.hedge_var_reduction = 1.0 - var(d_hedged) / vu;
  }
  return st;
}

ReplayStats replay(std::string_view family, const Params& params, const Position& pos,
                   std::span<const MarketTick> ticks, const FeeModel& fees) {
  AnyAlgo a = make_algo(family, params, pos);
  ReplayStats s = replay_algo(a, pos, ticks, fees);
  s.params = params;
  return s;
}

std::vector<ReplayStats> replay_grid(std::string_view family, const Position& pos, std::span<const MarketTick> ticks,
                                     const FeeModel& fees) {
  const FamilyInfo* f = find_family(family);
  if (!f) throw std::invalid_argument("unknown algo family: " + std::string(family));
  std::vector<ReplayStats> out;
  out.reserve(f->preset_count);
  for (std::size_t i = 0; i < f->preset_count; ++i) {
    const Params p = f->spec.preset(i);
    ReplayStats s = replay(family, p, pos, ticks, fees);
    s.preset_index = i;
    out.push_back(s);
  }
  return out;
}

}  // namespace hedgecore
