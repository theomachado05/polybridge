#pragma once
#include <cmath>
#include "hedgecore/algos/common.hpp"
#include "hedgecore/algos/hedge_params.hpp"

namespace hedgecore::algos {

// Stress regime = |dp over `window` ticks| large against EWMA vol scaled to the window. In stress the hedge crosses
// the spread unsliced; in calm it joins the touch in child slices.
struct StressLeadHedge : AlgoBase<StressLeadHedge> {
  static constexpr const char* id = "stress_lead_hedge";
  static constexpr const char* division = "hedge";
  static constexpr const char* ui_kind = "Execution";
  static constexpr const char* idea =
      "Hedge fast (cross, unsliced) when the prediction market moves sharply against its own volatility; work "
      "orders passively otherwise";
  static constexpr const char* event_classes[] = {"macro_fed", "geopolitics_energy", "fig"};
  static constexpr const char* instruments[] = {"equity", "etf"};
  static constexpr BlockRef blocks[] = {
      {"signals", "ImpliedProb"}, {"signals", "DeltaDp"},          {"signals", "EwmaVol"},
      {"gates", "Staleness"},     {"gates", "Session"},            {"sizers", "DeltaBridge"},
      {"risk", "PositionCap"},    {"execution", "NoTradeBand"},     {"execution", "FeeGate"},
      {"execution", "Slicer"},    {"execution", "PassiveAggressive"}};
  enum P { kCoverage, kWindow, kStressK, kBand, kChildMax, kImpact, kSession, kWash };
  static constexpr ParamSpec kSpec{
      param("coverage", 0, 1, 0.75, {0.5, 0.75, 1.0}, "c: fraction hedged at p = 1"),
      param("window", 1, 64, 5, {3.0, 5.0, 10.0}, "ticks over which dp is measured"),
      param("stress_k", 0, 20, 2, {1.5, 2.0, 3.0}, "stress when |dp| >= k * sigma * sqrt(window)"),
      hp::band(25),
      param("child_max", 0, 1e7, 100, {100.0, 500.0}, "calm-regime child order cap in shares"),
      hp::impact(), hp::session(), hp::wash()};
  static ParamSpec spec() noexcept { return kSpec; }

  HedgeCore core;
  blocks::DeltaDp ddp;
  blocks::EwmaVol vol{0.05};
  blocks::DeltaBridge sizer;
  double stress_k, child_max;

  StressLeadHedge(const Params& p, const Position& pos) noexcept
      : core(pos, kSpec.valid(p), p.v[kBand], 1.0, p.v[kImpact], p.v[kSession] >= 0.5, p.v[kWash] >= 0.5),
        ddp{static_cast<int>(p.v[kWindow])},
        sizer{p.v[kCoverage], pos.shares_held},
        stress_k(p.v[kStressK]),
        child_max(p.v[kChildMax]) {
    core.pa.urgency_threshold = stress_k;  // urgency = stress ratio
  }

  Intent step(const MarketTick& t, std::int64_t now) noexcept {
    Intent out;
    if (!core.admit(t, now, out)) return out;
    const double p = blocks::ImpliedProb::read(t);
    if (!num(p)) return hold(Rc::SignalMissing);
    const double dpw = ddp.update(p);
    const auto v = vol.update(p);
    double stress = 0.0;  // warm-up counts as calm
    if (num(dpw) && num(v.sigma_prev))
      stress = v.sigma_prev > 0 ? std::abs(dpw) / (v.sigma_prev * std::sqrt(static_cast<double>(ddp.window)))
                                : (dpw != 0 ? 1e9 : 0.0);
    const bool urgent = stress >= stress_k;
    core.slicer.child_max = urgent ? 0.0 : child_max;
    return core.decide(t, now, p, sizer.target(p), stress, stress, urgent ? Rc::Aggressive : Rc::Passive);
  }
  void on_fill(Instrument i, double q, double px) noexcept { core.on_fill(i, q, px); }
  void on_reject(Instrument i) noexcept { core.on_reject(i); }
};

}  // namespace hedgecore::algos
