#pragma once
#include <cmath>
#include "hedgecore/algos/common.hpp"
#include "hedgecore/algos/hedge_params.hpp"

namespace hedgecore::algos {

// When top-of-book imbalance is strong the microprice leads the mid: size the hedge on the microprice (pre-hedge)
// and cross; otherwise size on the mid and join. Requires real depth: the Depth gate fails closed without a book.
struct BookImbalanceHedge : AlgoBase<BookImbalanceHedge> {
  static constexpr const char* id = "book_imbalance_hedge";
  static constexpr const char* division = "hedge";
  static constexpr const char* ui_kind = "Reader";
  static constexpr const char* idea =
      "Pre-hedge on the order-book microprice when Polymarket/Kalshi depth is lopsided, before the mid moves";
  static constexpr auto& event_classes = ev::kAll;
  static constexpr const char* instruments[] = {"equity"};
  static constexpr BlockRef blocks[] = {
      {"signals", "PMid"},        {"signals", "BookImbalance"},   {"signals", "Microprice"},
      {"gates", "Staleness"},     {"gates", "Session"},           {"gates", "Depth"},
      {"sizers", "DeltaBridge"},  {"risk", "PositionCap"},        {"execution", "NoTradeBand"},
      {"execution", "FeeGate"},   {"execution", "PassiveAggressive"}};
  enum P { kLevels, kImbThr, kCoverage, kMinDepth, kBand, kImpact, kSession, kWash };
  static constexpr ParamSpec kSpec{
      param("levels", 1, 5, 3, {1.0, 3.0, 5.0}, "book levels summed for imbalance and depth"),
      param("imb_threshold", 0, 1, 0.4, {0.2, 0.4, 0.6}, "|imbalance| at which the microprice leads"),
      param("coverage", 0, 1, 0.75, {0.5, 0.75, 1.0}, "c: fraction hedged at p = 1"),
      param("min_depth", 0, 1e9, 500, {100.0, 500.0, 2000.0}, "minimum contracts on each side over `levels`"),
      param("band_shares", 0, 1e6, 10, {10.0}, "no-trade band in shares"),
      hp::impact(), hp::session(), hp::wash()};
  static ParamSpec spec() noexcept { return kSpec; }

  HedgeCore core;
  blocks::BookImbalance imb;
  blocks::Depth depth;
  blocks::DeltaBridge sizer;
  double thr;

  BookImbalanceHedge(const Params& p, const Position& pos) noexcept
      : core(pos, kSpec.valid(p), p.v[kBand], 1.0, p.v[kImpact], p.v[kSession] >= 0.5, p.v[kWash] >= 0.5),
        imb{static_cast<int>(p.v[kLevels])},
        depth{p.v[kMinDepth], static_cast<int>(p.v[kLevels])},
        sizer{p.v[kCoverage], pos.shares_held},
        thr(p.v[kImbThr]) {
    core.pa.urgency_threshold = thr;
  }

  Intent step(const MarketTick& t, std::int64_t now) noexcept {
    Intent out;
    if (!core.admit(t, now, out)) return out;
    if (!depth.pass({t, now})) return hold(Rc::ThinBook);
    const double m = blocks::PMid::read(t);
    const double ib = imb.read(t);
    if (!num(m) || !num(ib)) return hold(Rc::SignalMissing);
    const double micro = blocks::Microprice::read(t);
    const bool leads = std::abs(ib) >= thr && num(micro);
    const double p = leads ? micro : m;
    return core.decide(t, now, p, sizer.target(p), std::abs(ib), ib, leads ? Rc::Aggressive : Rc::Rebalance);
  }
  void on_fill(Instrument i, double q, double px) noexcept { core.on_fill(i, q, px); }
};

}  // namespace hedgecore::algos
