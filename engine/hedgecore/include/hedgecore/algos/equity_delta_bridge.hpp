#pragma once
#include "hedgecore/algos/common.hpp"
#include "hedgecore/algos/hedge_params.hpp"

namespace hedgecore::algos {

// Today's Engine, generalized: DeltaBridge h* = round(c * N * p_adverse) on the de-vigged implied probability,
// sigma-gated, banded and fee-gated.
struct EquityDeltaBridge : AlgoBase<EquityDeltaBridge> {
  static constexpr const char* id = "equity_delta_bridge";
  static constexpr const char* division = "hedge";
  static constexpr const char* ui_kind = "Impact";
  static constexpr const char* idea =
      "Short c * N * p_adverse shares of the held stock, re-sized when the prediction market moves enough to beat fees";
  static constexpr auto& event_classes = ev::kAll;
  static constexpr const char* instruments[] = {"equity"};
  static constexpr BlockRef blocks[] = {
      {"signals", "ImpliedProb"}, {"signals", "EwmaVol"},      {"gates", "Staleness"},
      {"gates", "Session"},       {"gates", "Sigma"},          {"sizers", "DeltaBridge"},
      {"risk", "PositionCap"},    {"execution", "NoTradeBand"}, {"execution", "FeeGate"},
      {"tax", "TaxLotSelector"},  {"tax", "WashSaleGuard"}};
  enum P { kCoverage, kBand, kSigmaK, kFeeRatio, kImpact, kSession, kWash };
  static constexpr ParamSpec kSpec{
      param("coverage", 0, 1, 0.5, {0.25, 0.5, 0.75, 1.0}, "c: fraction of the position hedged at p = 1"),
      param("band_shares", 0, 1e6, 10, {5.0, 10.0, 25.0, 50.0}, "no-trade band in shares"),
      hp::sigma_k(),
      param("fee_ratio", 0, 100, 1, {0.5, 1.0, 2.0}, "trade only if benefit >= ratio * (fee + half-spread)"),
      hp::impact(), hp::session(), hp::wash()};
  static ParamSpec spec() noexcept { return kSpec; }

  HedgeCore core;
  blocks::EwmaVol vol{0.05};
  blocks::Sigma sigma;
  blocks::DeltaBridge sizer;

  EquityDeltaBridge(const Params& p, const Position& pos) noexcept
      : core(pos, kSpec.valid(p), p.v[kBand], p.v[kFeeRatio], p.v[kImpact], p.v[kSession] >= 0.5, p.v[kWash] >= 0.5),
        sigma{p.v[kSigmaK]},
        sizer{p.v[kCoverage], pos.shares_held} {}

  Intent step(const MarketTick& t, std::int64_t now) noexcept {
    Intent out;
    if (!core.admit(t, now, out)) return out;
    const double p = blocks::ImpliedProb::read(t);
    if (!num(p)) return hold(Rc::SignalMissing);
    const auto v = vol.update(p);
    if (!sigma.pass({t, now, v.dp, v.sigma_prev})) return hold(Rc::BelowSigma, p);
    return core.decide(t, now, p, sizer.target(p), 0.0, p);
  }
  void on_fill(Instrument i, double q, double px) noexcept { core.on_fill(i, q, px); }
  void on_reject(Instrument i) noexcept { core.on_reject(i); }
};

}  // namespace hedgecore::algos
