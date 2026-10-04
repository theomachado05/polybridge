#pragma once
#include <cmath>
#include "hedgecore/algos/common.hpp"
#include "hedgecore/algos/hedge_params.hpp"

namespace hedgecore::algos {

#define HEDGECORE_HEDGE_CTOR_CORE(BAND, FEE)                                                                  \
  core(pos, kSpec.valid(p), (BAND), (FEE), p.v[kImpact], p.v[kSession] >= 0.5, p.v[kWash] >= 0.5)

struct HousingRates : AlgoBase<HousingRates> {
  static constexpr const char* id = "housing_rates";
  static constexpr const char* division = "hedge";
  static constexpr const char* ui_kind = "Impact";
  static constexpr const char* idea =
      "Mortgage-rate and home-price odds hedge rate-sensitive homebuilder/REIT ETFs with a linear rate beta";
  static constexpr const char* event_classes[] = {"housing"};
  static constexpr const char* instruments[] = {"etf:ITB", "etf:XHB", "etf:VNQ"};
  static constexpr BlockRef blocks[] = {
      {"signals", "ImpliedProb"},  {"signals", "EwmaVol"},        {"gates", "Staleness"}, {"gates", "Session"},
      {"gates", "Sigma"},          {"sizers", "LinearExposure"},  {"risk", "PositionCap"},
      {"execution", "NoTradeBand"}, {"execution", "FeeGate"}};
  enum P { kBeta, kMaxCov, kBand, kSigmaK, kImpact, kSession, kWash };
  static constexpr ParamSpec kSpec{
      param("beta", 0, 5, 1, {0.5, 1.0, 1.5}, "hedge fraction per unit of adverse probability"),
      param("max_cov", 0, 1, 1, {0.5, 0.75, 1.0}, "maximum hedged fraction"), hp::band(), hp::sigma_k(), hp::impact(),
      hp::session(), hp::wash()};
  static ParamSpec spec() noexcept { return kSpec; }

  HedgeCore core;
  blocks::EwmaVol vol{0.05};
  blocks::Sigma sigma;
  blocks::LinearExposure sizer;
  HousingRates(const Params& p, const Position& pos) noexcept
      : HEDGECORE_HEDGE_CTOR_CORE(p.v[kBand], 1.0), sigma{p.v[kSigmaK]},
        sizer{p.v[kBeta], 0.0, p.v[kMaxCov], pos.shares_held} {}
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

struct FigStress : AlgoBase<FigStress> {
  static constexpr const char* id = "fig_stress";
  static constexpr const char* division = "hedge";
  static constexpr const char* ui_kind = "Impact";
  static constexpr const char* idea =
      "Bank-stress, Fed and regulation odds hedge banks/insurers convexly (p^gamma), with a drawdown kill on the "
      "hedge leg";
  static constexpr const char* event_classes[] = {"fig", "macro_fed"};
  static constexpr const char* instruments[] = {"etf:KRE", "etf:XLF", "etf:KBE"};
  static constexpr BlockRef blocks[] = {
      {"signals", "ImpliedProb"},   {"gates", "Staleness"},    {"gates", "Session"},
      {"sizers", "ConvexExposure"}, {"risk", "PositionCap"},   {"risk", "DrawdownKill"},
      {"execution", "NoTradeBand"}, {"execution", "FeeGate"}};
  enum P { kCoverage, kGamma, kBand, kDdFrac, kImpact, kSession, kWash };
  static constexpr ParamSpec kSpec{
      param("coverage", 0, 1, 0.75, {0.5, 0.75, 1.0}, "c: fraction hedged at p = 1"),
      param("gamma", 0.1, 5, 1, {0.5, 1.0, 2.0}, "convexity of the response to p"), hp::band(),
      param("dd_frac", 0, 1, 0.05, {0.02, 0.05, 0.10}, "kill the hedge leg after losing this fraction of N * price"),
      hp::impact(), hp::session(), hp::wash()};
  static ParamSpec spec() noexcept { return kSpec; }

  HedgeCore core;
  blocks::ConvexExposure sizer;
  double dd_frac;
  FigStress(const Params& p, const Position& pos) noexcept
      : HEDGECORE_HEDGE_CTOR_CORE(p.v[kBand], 1.0), sizer{p.v[kCoverage], p.v[kGamma], pos.shares_held},
        dd_frac(p.v[kDdFrac]) {}
  Intent step(const MarketTick& t, std::int64_t now) noexcept {
    Intent out;
    if (!core.admit(t, now, out)) return out;
    if (core.dd.max_dd <= 0 && num(under_ref(t)))
      core.dd.max_dd = dd_frac * core.shares * under_ref(t);
    const double p = blocks::ImpliedProb::read(t);
    if (!num(p)) return hold(Rc::SignalMissing);
    return core.decide(t, now, p, sizer.target(p), 0.0, p);
  }
  void on_fill(Instrument i, double q, double px) noexcept { core.on_fill(i, q, px); }
  void on_reject(Instrument i) noexcept { core.on_reject(i); }
};

struct MacroFedHedge : AlgoBase<MacroFedHedge> {
  static constexpr const char* id = "macro_fed_hedge";
  static constexpr const char* division = "hedge";
  static constexpr const char* ui_kind = "Reader";
  static constexpr const char* idea =
      "Fed/CPI/recession odds hedge index proxies; the hedge only grows when probability momentum confirms and "
      "only shrinks when it reverses, with a cooldown between orders";
  static constexpr const char* event_classes[] = {"macro_fed"};
  static constexpr const char* instruments[] = {"etf:SPY", "etf:IWM", "etf:TLT"};
  static constexpr BlockRef blocks[] = {
      {"signals", "ImpliedProb"},  {"signals", "Momentum"},     {"gates", "Staleness"}, {"gates", "Session"},
      {"gates", "Cooldown"},       {"sizers", "DeltaBridge"},   {"risk", "PositionCap"},
      {"execution", "NoTradeBand"}, {"execution", "FeeGate"}};
  enum P { kCoverage, kMomAlpha, kCooldownS, kBand, kImpact, kSession, kWash };
  static constexpr ParamSpec kSpec{
      param("coverage", 0, 1, 0.5, {0.25, 0.5, 1.0}, "c: fraction hedged at p = 1"),
      param("mom_alpha", 0.01, 1, 0.3, {0.1, 0.3, 0.6}, "EWMA weight of the momentum signal"),
      param("cooldown_s", 0, 86400, 60, {0.0, 60.0, 300.0}, "minimum seconds between orders"), hp::band(),
      hp::impact(), hp::session(), hp::wash()};
  static ParamSpec spec() noexcept { return kSpec; }

  HedgeCore core;
  blocks::Momentum mom;
  blocks::DeltaBridge sizer;
  MacroFedHedge(const Params& p, const Position& pos) noexcept
      : HEDGECORE_HEDGE_CTOR_CORE(p.v[kBand], 1.0), mom{p.v[kMomAlpha]}, sizer{p.v[kCoverage], pos.shares_held} {
    core.cooldown.min_ns = static_cast<std::int64_t>(p.v[kCooldownS] * 1e9);
  }
  Intent step(const MarketTick& t, std::int64_t now) noexcept {
    Intent out;
    if (!core.admit(t, now, out)) return out;
    const double p = blocks::ImpliedProb::read(t);
    if (!num(p)) return hold(Rc::SignalMissing);
    const double m = mom.update(p);
    const double target = sizer.target(p);
    if (num(m) && num(target)) {
      const double delta = target - core.hedge;
      if ((delta > 0 && m <= 0) || (delta < 0 && m >= 0)) return hold(Rc::NoSignal, m);
    }
    return core.decide(t, now, p, target, 0.0, num(m) ? m : p);
  }
  void on_fill(Instrument i, double q, double px) noexcept { core.on_fill(i, q, px); }
  void on_reject(Instrument i) noexcept { core.on_reject(i); }
};

struct ElectionHedge : AlgoBase<ElectionHedge> {
  static constexpr const char* id = "election_hedge";
  static constexpr const char* division = "hedge";
  static constexpr const char* ui_kind = "Impact";
  static constexpr const char* idea =
      "Election odds above a neutral level tilt a hedge on the sector ETF the outcome hurts, linear in the excess "
      "probability";
  static constexpr const char* event_classes[] = {"elections"};
  static constexpr const char* instruments[] = {"etf:sector"};
  static constexpr BlockRef blocks[] = {
      {"signals", "ImpliedProb"},  {"signals", "EwmaVol"},        {"gates", "Staleness"}, {"gates", "Session"},
      {"gates", "Sigma"},          {"sizers", "LinearExposure"},  {"risk", "PositionCap"},
      {"execution", "NoTradeBand"}, {"execution", "FeeGate"}};
  enum P { kBeta, kNeutral, kBand, kSigmaK, kImpact, kSession, kWash };
  static constexpr ParamSpec kSpec{
      param("beta", 0, 10, 1, {0.5, 1.0, 2.0}, "hedge fraction per unit of probability above neutral"),
      param("p_neutral", 0, 1, 0.5, {0.3, 0.4, 0.5}, "probability at which no hedge is held"), hp::band(),
      hp::sigma_k(), hp::impact(), hp::session(), hp::wash()};
  static ParamSpec spec() noexcept { return kSpec; }

  HedgeCore core;
  blocks::EwmaVol vol{0.05};
  blocks::Sigma sigma;
  blocks::LinearExposure sizer;
  ElectionHedge(const Params& p, const Position& pos) noexcept
      : HEDGECORE_HEDGE_CTOR_CORE(p.v[kBand], 1.0), sigma{p.v[kSigmaK]},
        sizer{p.v[kBeta], p.v[kNeutral], 1.0, pos.shares_held} {}
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

struct TariffTradeHedge : AlgoBase<TariffTradeHedge> {
  static constexpr const char* id = "tariff_trade_hedge";
  static constexpr const char* division = "hedge";
  static constexpr const char* ui_kind = "Reader";
  static constexpr const char* idea =
      "Tariff odds hedge trade-exposed equities convexly; the hedge grows only on z-score breakouts above the EWMA "
      "mean and shrinks only on breakdowns";
  static constexpr const char* event_classes[] = {"tariffs_trade"};
  static constexpr const char* instruments[] = {"etf:importers", "etf:exporters"};
  static constexpr BlockRef blocks[] = {
      {"signals", "ImpliedProb"},   {"signals", "MeanRevertZ"},  {"gates", "Staleness"}, {"gates", "Session"},
      {"sizers", "ConvexExposure"}, {"risk", "PositionCap"},     {"execution", "NoTradeBand"},
      {"execution", "FeeGate"}};
  enum P { kCoverage, kGamma, kZEntry, kBand, kImpact, kSession, kWash };
  static constexpr ParamSpec kSpec{
      param("coverage", 0, 1, 0.75, {0.5, 0.75, 1.0}, "c: fraction hedged at p = 1"),
      param("gamma", 0.1, 5, 1.5, {1.0, 1.5, 2.0}, "convexity of the response to p"),
      param("z_entry", 0, 10, 1, {0.0, 1.0, 2.0}, "|z| needed to grow (z >= k) or shrink (z <= -k) the hedge"),
      hp::band(), hp::impact(), hp::session(), hp::wash()};
  static ParamSpec spec() noexcept { return kSpec; }

  HedgeCore core;
  blocks::MeanRevertZ z{0.1};
  blocks::ConvexExposure sizer;
  double z_entry;
  TariffTradeHedge(const Params& p, const Position& pos) noexcept
      : HEDGECORE_HEDGE_CTOR_CORE(p.v[kBand], 1.0), sizer{p.v[kCoverage], p.v[kGamma], pos.shares_held},
        z_entry(p.v[kZEntry]) {}
  Intent step(const MarketTick& t, std::int64_t now) noexcept {
    Intent out;
    if (!core.admit(t, now, out)) return out;
    const double p = blocks::ImpliedProb::read(t);
    if (!num(p)) return hold(Rc::SignalMissing);
    const double zz = z.update(p);
    const double target = sizer.target(p);
    if (num(zz) && num(target)) {
      const double delta = target - core.hedge;
      if ((delta > 0 && zz < z_entry) || (delta < 0 && zz > -z_entry)) return hold(Rc::NoSignal, zz);
    }
    return core.decide(t, now, p, target, 0.0, num(zz) ? zz : p);
  }
  void on_fill(Instrument i, double q, double px) noexcept { core.on_fill(i, q, px); }
  void on_reject(Instrument i) noexcept { core.on_reject(i); }
};

struct EnergyGeoHedge : AlgoBase<EnergyGeoHedge> {
  static constexpr const char* id = "energy_geo_hedge";
  static constexpr const char* division = "hedge";
  static constexpr const char* ui_kind = "Gate";
  static constexpr const char* idea =
      "Conflict/OPEC odds hedge energy proxies; ignores wide, unreliable PM quotes and crosses the spread on jumps";
  static constexpr const char* event_classes[] = {"geopolitics_energy"};
  static constexpr const char* instruments[] = {"etf:XLE", "etf:USO"};
  static constexpr BlockRef blocks[] = {
      {"signals", "ImpliedProb"}, {"signals", "DeltaDp"},       {"gates", "Staleness"},
      {"gates", "Session"},       {"gates", "Spread"},          {"sizers", "DeltaBridge"},
      {"risk", "PositionCap"},    {"execution", "NoTradeBand"}, {"execution", "FeeGate"},
      {"execution", "PassiveAggressive"}};
  enum P { kCoverage, kJump, kMaxSpread, kBand, kImpact, kSession, kWash };
  static constexpr ParamSpec kSpec{
      param("coverage", 0, 1, 0.75, {0.5, 0.75, 1.0}, "c: fraction hedged at p = 1"),
      param("jump", 0, 1, 0.04, {0.02, 0.04, 0.06}, "one-tick |dp| treated as a jump (cross the spread)"),
      param("max_pm_spread", 0, 1, 0.05, {0.02, 0.05, 0.10}, "skip ticks whose YES spread is wider"), hp::band(),
      hp::impact(), hp::session(), hp::wash()};
  static ParamSpec spec() noexcept { return kSpec; }

  HedgeCore core;
  blocks::DeltaDp ddp{1};
  blocks::Spread spread;
  blocks::DeltaBridge sizer;
  EnergyGeoHedge(const Params& p, const Position& pos) noexcept
      : HEDGECORE_HEDGE_CTOR_CORE(p.v[kBand], 1.0), spread{p.v[kMaxSpread]},
        sizer{p.v[kCoverage], pos.shares_held} {
    core.pa.urgency_threshold = p.v[kJump];
  }
  Intent step(const MarketTick& t, std::int64_t now) noexcept {
    Intent out;
    if (!core.admit(t, now, out)) return out;
    if (!spread.pass({t, now})) return hold(Rc::SpreadTooWide);
    const double p = blocks::ImpliedProb::read(t);
    if (!num(p)) return hold(Rc::SignalMissing);
    const double dp = ddp.update(p);
    const double urg = num(dp) ? std::abs(dp) : 0.0;
    const bool jump = urg >= core.pa.urgency_threshold;
    return core.decide(t, now, p, sizer.target(p), urg, num(dp) ? dp : p, jump ? Rc::Aggressive : Rc::Passive);
  }
  void on_fill(Instrument i, double q, double px) noexcept { core.on_fill(i, q, px); }
  void on_reject(Instrument i) noexcept { core.on_reject(i); }
};

struct CryptoRegHedge : AlgoBase<CryptoRegHedge> {
  static constexpr const char* id = "crypto_reg_hedge";
  static constexpr const char* division = "hedge";
  static constexpr const char* ui_kind = "Impact";
  static constexpr const char* idea =
      "Crypto regulation/ETF odds hedge crypto equities; coverage is scaled by inverse PM volatility so noisy "
      "markets earn a smaller hedge";
  static constexpr const char* event_classes[] = {"crypto"};
  static constexpr const char* instruments[] = {"equity:COIN", "equity:MSTR"};
  static constexpr BlockRef blocks[] = {
      {"signals", "ImpliedProb"}, {"signals", "EwmaVol"},     {"gates", "Staleness"},
      {"gates", "Session"},       {"sizers", "VolTarget"},    {"sizers", "DeltaBridge"},
      {"risk", "PositionCap"},    {"execution", "NoTradeBand"}, {"execution", "FeeGate"}};
  enum P { kCoverage, kSigmaRef, kMaxLev, kBand, kImpact, kSession, kWash };
  static constexpr ParamSpec kSpec{
      param("coverage", 0, 1, 0.75, {0.5, 0.75, 1.0}, "base c before the volatility scale"),
      param("sigma_ref", 1e-4, 1, 0.02, {0.01, 0.02, 0.04}, "PM tick volatility at which the scale is 1"),
      param("max_lev", 0.25, 4, 1.5, {1.0, 1.5, 2.0}, "upper clamp of the volatility scale"), hp::band(),
      hp::impact(), hp::session(), hp::wash()};
  static ParamSpec spec() noexcept { return kSpec; }

  HedgeCore core;
  blocks::EwmaVol vol{0.05};
  blocks::VolTarget vt;
  double coverage;
  CryptoRegHedge(const Params& p, const Position& pos) noexcept
      : HEDGECORE_HEDGE_CTOR_CORE(p.v[kBand], 1.0), vt{p.v[kSigmaRef], 0.25, p.v[kMaxLev]},
        coverage(p.v[kCoverage]) {}
  Intent step(const MarketTick& t, std::int64_t now) noexcept {
    Intent out;
    if (!core.admit(t, now, out)) return out;
    const double p = blocks::ImpliedProb::read(t);
    if (!num(p)) return hold(Rc::SignalMissing);
    const auto v = vol.update(p);
    const double scale = num(v.sigma) ? vt.scale(v.sigma) : 1.0;
    const blocks::DeltaBridge sizer{clampd(coverage * scale, 0.0, 1.0), core.shares};
    return core.decide(t, now, p, sizer.target(p), 0.0, scale);
  }
  void on_fill(Instrument i, double q, double px) noexcept { core.on_fill(i, q, px); }
  void on_reject(Instrument i) noexcept { core.on_reject(i); }
};

struct TechRegHedge : AlgoBase<TechRegHedge> {
  static constexpr const char* id = "tech_reg_hedge";
  static constexpr const char* division = "hedge";
  static constexpr const char* ui_kind = "Execution";
  static constexpr const char* idea =
      "Antitrust/AI-regulation odds hedge mega-cap names on the PM microprice, worked in child slices to limit "
      "impact in large positions";
  static constexpr const char* event_classes[] = {"tech_regulation", "company_specific"};
  static constexpr const char* instruments[] = {"equity:megacap_tech"};
  static constexpr BlockRef blocks[] = {
      {"signals", "Microprice"},  {"signals", "PMid"},          {"gates", "Staleness"},
      {"gates", "Session"},       {"sizers", "DeltaBridge"},    {"risk", "PositionCap"},
      {"execution", "NoTradeBand"}, {"execution", "FeeGate"},   {"execution", "Slicer"}};
  enum P { kCoverage, kChildMax, kBand, kFeeRatio, kImpact, kSession, kWash };
  static constexpr ParamSpec kSpec{
      param("coverage", 0, 1, 0.5, {0.25, 0.5, 1.0}, "c: fraction hedged at p = 1"),
      param("child_max", 0, 1e7, 200, {50.0, 200.0, 1000.0}, "child order cap in shares"), hp::band(),
      param("fee_ratio", 0, 100, 1, {0.5, 1.0, 2.0}, "trade only if benefit >= ratio * cost"), hp::impact(),
      hp::session(), hp::wash()};
  static ParamSpec spec() noexcept { return kSpec; }

  HedgeCore core;
  blocks::DeltaBridge sizer;
  TechRegHedge(const Params& p, const Position& pos) noexcept
      : HEDGECORE_HEDGE_CTOR_CORE(p.v[kBand], p.v[kFeeRatio]), sizer{p.v[kCoverage], pos.shares_held} {
    core.slicer.child_max = p.v[kChildMax];
  }
  Intent step(const MarketTick& t, std::int64_t now) noexcept {
    Intent out;
    if (!core.admit(t, now, out)) return out;
    const double micro = blocks::Microprice::read(t);
    const double p = num(micro) ? micro : blocks::PMid::read(t);
    if (!num(p)) return hold(Rc::SignalMissing);
    return core.decide(t, now, p, sizer.target(p), 0.0, p);
  }
  void on_fill(Instrument i, double q, double px) noexcept { core.on_fill(i, q, px); }
  void on_reject(Instrument i) noexcept { core.on_reject(i); }
};

#undef HEDGECORE_HEDGE_CTOR_CORE

}
