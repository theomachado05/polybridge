#pragma once
// Prediction-market-leg families: poly_kalshi_spread (cross-venue convergence) and no_bid_seller (sell rich NO).
#include <cmath>
#include "hedgecore/algos/common.hpp"

namespace hedgecore::algos {

// Shared admission for the non-equity families: param validity, latched bad fills, staleness.
struct OppCore {
  bool valid = false;
  Ledger led{};
  blocks::Staleness stale{2 * kNsPerSec};
  OppCore() = default;
  OppCore(const Position& p, bool params_ok) noexcept : valid(params_ok && position_ok(p)) {
    led.at(Instrument::Equity) = p.equity;
    led.at(Instrument::PredYes) = p.pred_yes;
    led.at(Instrument::PredNo) = p.pred_no;
    led.at(Instrument::Option) = p.option;
  }
  bool admit(const MarketTick& t, std::int64_t now, Intent& out) noexcept {
    if (!valid) { out = hold(Rc::InvalidParams); return false; }
    if (led.bad) { out = hold(Rc::InvalidState); return false; }
    if (!stale.pass({t, now})) { out = hold(Rc::Stale); return false; }
    return true;
  }
  void fill(Instrument i, double q, double px, double mult) noexcept { led.fill(i, q, px, mult); }
};

// NO ask on this venue, else its YES-parity equivalent 1 - yes_bid (not a missing field read as 0).
inline double no_ask_or_parity(const MarketTick& t) noexcept {
  if (prob(t.no_ask)) return t.no_ask;
  return prob(t.yes_bid) ? 1.0 - t.yes_bid : kNaN;
}

// ---- poly_kalshi_spread -------------------------------------------------------------------------------------------
struct PolyKalshiSpread : AlgoBase<PolyKalshiSpread> {
  static constexpr const char* id = "poly_kalshi_spread";
  static constexpr const char* division = "hedge/opportunity";
  static constexpr const char* ui_kind = "Reader";
  static constexpr const char* idea =
      "When this venue's YES mid is rich (cheap) against the other venue by more than half-spread + fee + entry, "
      "buy NO (YES) here and exit when the gap closes; stop if the gap flips through the entry threshold";
  static constexpr auto& event_classes = ev::kAll;
  static constexpr const char* instruments[] = {"pred_yes", "pred_no"};
  static constexpr BlockRef blocks[] = {
      {"signals", "CrossVenueGap"}, {"gates", "Staleness"},   {"gates", "Spread"},
      {"risk", "PositionCap"},      {"risk", "GapFlipKill"}, {"execution", "FeeGate"}};
  enum P { kEntry, kExit, kSize, kMaxSpread };
  static constexpr ParamSpec kSpec{
      param("entry_gap", 0, 1, 0.02, {0.01, 0.02, 0.04}, "net edge (gap - half-spread - fee) to enter"),
      param("exit_gap", 0, 1, 0.005, {0.0, 0.005, 0.01}, "exit once the gap on the entry side is <= this"),
      param("size", 1, 1e7, 500, {100.0, 500.0, 1000.0}, "contracts per entry (one clip, no pyramiding)"),
      param("max_spread", 0, 1, 0.03, {0.03, 0.05, 0.08}, "skip entries when this venue's YES spread is wider")};
  static ParamSpec spec() noexcept { return kSpec; }

  OppCore core;
  blocks::Spread spread;
  blocks::GapFlipKill kill;
  blocks::PositionCap cap;
  blocks::FeeGate fee_gate{1.0};
  FeeModel fees{};
  double entry, exit_gap;

  PolyKalshiSpread(const Params& p, const Position& pos) noexcept
      : core(pos, kSpec.valid(p)), spread{p.v[kMaxSpread]}, kill{p.v[kEntry]}, cap{p.v[kSize]},
        entry(p.v[kEntry]), exit_gap(p.v[kExit]) {}

  Intent close_leg(const MarketTick& t, Rc why, double gap) const noexcept {
    const double y = core.led.at(Instrument::PredYes), n = core.led.at(Instrument::PredNo);
    if (y != 0) return order(Instrument::PredYes, y > 0 ? -1 : +1, std::abs(y), kNaN, why, gap, t.venue);
    return order(Instrument::PredNo, n > 0 ? -1 : +1, std::abs(n), kNaN, why, gap, t.venue);
  }

  Intent step(const MarketTick& t, std::int64_t now) noexcept {
    Intent out;
    if (!core.admit(t, now, out)) return out;
    const double gap = blocks::CrossVenueGap::read(t);
    if (!num(gap)) return hold(Rc::SignalMissing);
    const bool holding = core.led.at(Instrument::PredYes) != 0 || core.led.at(Instrument::PredNo) != 0;
    if (holding) {
      if (kill.update(gap)) return close_leg(t, Rc::GapFlipKill, gap);
      if (kill.entry_sign == 0 || gap * kill.entry_sign <= exit_gap + 1e-12) return close_leg(t, Rc::Exit, gap);
      return hold(Rc::NoSignal, gap);
    }
    if (kill.killed) return hold(Rc::GapFlipKill, gap);
    if (!spread.pass({t, now})) return hold(Rc::SpreadTooWide, gap);
    const Instrument inst = gap > 0 ? Instrument::PredNo : Instrument::PredYes;
    const double px = gap > 0 ? no_ask_or_parity(t) : t.yes_ask;
    const double fee = fees.unit_fee(inst, t.venue, px);
    if (std::abs(gap) < entry) return hold(Rc::NoSignal, gap);
    // FeeGate: the gap beyond the entry threshold must pay this venue's half-spread plus the taker fee, i.e.
    // |gap| - half-spread - fee >= entry_gap.
    const Rc fr = fee_gate.check(std::abs(gap) - entry, half_spread(t.yes_bid, t.yes_ask) + fee);
    if (fr != Rc::None) return hold(fr, gap);
    bool capped = false;
    const double qty = cap.clamp(cap.max_abs, capped);
    kill.arm(gap);
    return order(inst, +1, qty, kNaN, Rc::Entry, gap, t.venue);
  }
  void on_fill(Instrument i, double q, double px) noexcept {
    if (i != Instrument::PredYes && i != Instrument::PredNo) return;
    core.fill(i, q, px, 1.0);
    if (core.led.at(Instrument::PredYes) == 0 && core.led.at(Instrument::PredNo) == 0) kill.disarm();
  }
  // An entry that never filled leaves the algo flat: the gap-flip stop armed for it no longer applies.
  void on_reject(Instrument) noexcept {
    if (core.led.at(Instrument::PredYes) == 0 && core.led.at(Instrument::PredNo) == 0) kill.disarm();
  }
};

// ---- no_bid_seller ------------------------------------------------------------------------------------------------
struct NoBidSeller : AlgoBase<NoBidSeller> {
  static constexpr const char* id = "no_bid_seller";
  static constexpr const char* division = "opportunity";
  static constexpr const char* ui_kind = "Routing";
  static constexpr const char* idea =
      "Sell NO into bids that are rich against a fair value (other venue, EWMA, or option-implied), Kelly-sized, "
      "routed to the venue with the best all-in price, never showing more than a fraction of displayed size";
  static constexpr auto& event_classes = ev::kAll;
  static constexpr const char* instruments[] = {"pred_no"};
  static constexpr BlockRef blocks[] = {
      {"signals", "PMid"},          {"signals", "MeanRevertZ"},   {"signals", "OptionImpliedProb"},
      {"gates", "Staleness"},       {"sizers", "KellyCapped"},    {"execution", "IcebergCap"},
      {"routing", "VenueRouter"}};
  enum P { kEdge, kKellyCap, kFairSrc, kIceberg, kBankroll };
  static constexpr ParamSpec kSpec{
      param("edge", 0, 1, 0.02, {0.01, 0.02, 0.04}, "all-in NO bid minus fair NO needed to sell"),
      param("kelly_cap", 0, 1, 0.1, {0.05, 0.1, 0.25}, "cap on the Kelly fraction of bankroll"),
      param("fair_source", 0, 2, 0, {0.0, 1.0, 2.0}, "fair YES from 0 other venue, 1 EWMA of mid, 2 options"),
      param("iceberg_frac", 0, 1, 0.5, {0.25, 0.5, 1.0}, "max fraction of displayed size per order"),
      param("bankroll", 1, 1e9, 10000, {10000.0}, "$ at risk for Kelly sizing")};
  static ParamSpec spec() noexcept { return kSpec; }

  OppCore core;
  blocks::MeanRevertZ ewma{0.1};
  blocks::KellyCapped kelly;
  blocks::IcebergCap iceberg;
  blocks::VenueRouter router{};
  double edge;
  int src;

  NoBidSeller(const Params& p, const Position& pos) noexcept
      : core(pos, kSpec.valid(p)), kelly{p.v[kKellyCap], p.v[kBankroll]}, iceberg{p.v[kIceberg]}, edge(p.v[kEdge]),
        src(static_cast<int>(p.v[kFairSrc])) {}

  Intent step(const MarketTick& t, std::int64_t now) noexcept {
    Intent out;
    if (!core.admit(t, now, out)) return out;
    double fair = kNaN;
    if (src == 0) fair = t.p_other_venue;
    else if (src == 1) fair = ewma.fair();  // judged against the past, then updated
    else fair = blocks::OptionImpliedProb::read(t);
    ewma.update(blocks::PMid::read(t));
    if (!prob(fair)) return hold(src == 1 ? Rc::Warmup : Rc::SignalMissing);
    const double fair_no = 1.0 - fair;
    const double short_no = -core.led.at(Instrument::PredNo);
    if (short_no > 0) {
      const blocks::Route rb = router.route(+1, Instrument::PredNo, t);
      if (num(rb.all_in) && fair_no - rb.all_in >= edge)
        return order(Instrument::PredNo, +1, short_no, kNaN, Rc::Exit, fair_no - rb.all_in, rb.venue);
    }
    const blocks::Route rs = router.route(-1, Instrument::PredNo, t);
    if (rs.reason == Rc::NoRoute) return hold(Rc::NoRoute);
    const double rich = rs.all_in - fair_no;
    if (!(rich >= edge)) return hold(Rc::NoSignal, rich);
    const double target = kelly.target(fair, 1.0 - rs.px);  // selling NO at b == buying YES at 1 - b
    const double delta = target - short_no;
    if (!(delta >= 1)) return hold(Rc::ZeroTarget, rich);
    bool capped = false;
    const double qty = iceberg.clip(delta, t.asks[0].qty, capped);  // YES asks are the NO bids
    if (qty < 1) return hold(Rc::IcebergCapped, rich);
    return order(Instrument::PredNo, -1, qty, kNaN, capped ? Rc::IcebergCapped : rs.reason, rich, rs.venue);
  }
  void on_fill(Instrument i, double q, double px) noexcept {
    if (i == Instrument::PredNo) core.fill(i, q, px, 1.0);
  }
};

}  // namespace hedgecore::algos
