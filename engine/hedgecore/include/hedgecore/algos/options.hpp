#pragma once
// Opportunity-division option families. An Option intent trades one unit of the family's structure (call spread,
// straddle, cash-secured put or put spread, named in `instruments`), priced by the tick's opt_mid.
#include <cmath>
#include "hedgecore/algos/opportunity.hpp"

namespace hedgecore::algos {

// ---- binary_vs_spread_arb -----------------------------------------------------------------------------------------
struct BinaryVsSpreadArb : AlgoBase<BinaryVsSpreadArb> {
  static constexpr const char* id = "binary_vs_spread_arb";
  static constexpr const char* division = "opportunity";
  static constexpr const char* ui_kind = "Reader";
  static constexpr const char* idea =
      "Buy (sell) the call spread when the PM probability of the same threshold exceeds (trails) the "
      "option-implied probability by the entry gap; exit when the gap closes";
  static constexpr auto& event_classes = ev::kAll;
  static constexpr const char* instruments[] = {"option:call_spread", "option:put_spread"};
  static constexpr BlockRef blocks[] = {
      {"signals", "ImpliedProb"}, {"signals", "OptionImpliedProb"}, {"signals", "PMvsOptionGap"},
      {"gates", "Staleness"},     {"sizers", "FixedNotional"},      {"risk", "PositionCap"}};
  enum P { kEntry, kExit, kContracts };
  static constexpr ParamSpec kSpec{
      param("entry_gap", 0, 1, 0.05, {0.03, 0.05, 0.08, 0.12}, "|PM - option prob| to enter"),
      param("exit_gap", 0, 1, 0.01, {0.0, 0.01, 0.02}, "exit once the gap on the entry side is <= this"),
      param("contracts", 1, 1e5, 5, {1.0, 5.0, 10.0}, "spreads per entry")};
  static ParamSpec spec() noexcept { return kSpec; }

  OppCore core;
  blocks::PositionCap cap;
  double entry, exit_gap;
  BinaryVsSpreadArb(const Params& p, const Position& pos) noexcept
      : core(pos, kSpec.valid(p)), cap{p.v[kContracts]}, entry(p.v[kEntry]), exit_gap(p.v[kExit]) {}
  Intent step(const MarketTick& t, std::int64_t now) noexcept {
    Intent out;
    if (!core.admit(t, now, out)) return out;
    const double gap = blocks::PMvsOptionGap::read(t);
    if (!num(gap) || !num(t.opt_mid)) return hold(Rc::SignalMissing);
    const double pos = core.led.at(Instrument::Option);
    if (pos != 0) {
      if (gap * sgn(pos) <= exit_gap + 1e-12) return order(Instrument::Option, pos > 0 ? -1 : +1, std::abs(pos), kNaN, Rc::Exit, gap);
      return hold(Rc::NoSignal, gap);
    }
    if (std::abs(gap) < entry) return hold(Rc::NoSignal, gap);
    return order(Instrument::Option, sgn(gap), cap.max_abs, kNaN, Rc::Entry, gap);
  }
  void on_fill(Instrument i, double q, double px) noexcept {
    if (i == Instrument::Option) core.fill(i, q, px, 100.0);
  }
};

// ---- vol_vs_pm_move -----------------------------------------------------------------------------------------------
struct VolVsPmMove : AlgoBase<VolVsPmMove> {
  static constexpr const char* id = "vol_vs_pm_move";
  static constexpr const char* division = "opportunity";
  static constexpr const char* ui_kind = "Reader";
  static constexpr const char* idea =
      "PM reprices but implied vol has not moved: buy the straddle. IV spikes while the PM is quiet: sell it. Exit "
      "when IV catches up or after max_hold ticks";
  static constexpr auto& event_classes = ev::kAll;
  static constexpr const char* instruments[] = {"option:straddle", "option:strangle"};
  static constexpr BlockRef blocks[] = {
      {"signals", "PMid"},    {"signals", "DeltaDp"},     {"gates", "Staleness"},
      {"sizers", "FixedNotional"}, {"risk", "PositionCap"}};
  enum P { kWindow, kPmMove, kIvStill, kContracts, kMaxHold };
  static constexpr ParamSpec kSpec{
      param("window", 1, 64, 5, {3.0, 5.0, 10.0}, "ticks over which PM and IV changes are measured"),
      param("pm_move", 0, 1, 0.04, {0.02, 0.04, 0.06}, "|dp| that counts as a PM repricing"),
      param("iv_still", 0, 5, 0.01, {0.005, 0.01, 0.02}, "|d iv| below which IV has not moved"),
      param("contracts", 1, 1e5, 5, {1.0, 5.0, 10.0}, "straddles per entry"),
      param("max_hold", 1, 1e6, 60, {60.0}, "ticks before a forced exit")};
  static ParamSpec spec() noexcept { return kSpec; }

  OppCore core;
  blocks::DeltaDp dpm, div;
  blocks::PositionCap cap;
  double pm_move, iv_still, max_hold;
  double last_iv = kNaN, iv_entry = kNaN;
  int held = 0;
  VolVsPmMove(const Params& p, const Position& pos) noexcept
      : core(pos, kSpec.valid(p)), dpm{static_cast<int>(p.v[kWindow])}, div{static_cast<int>(p.v[kWindow])},
        cap{p.v[kContracts]}, pm_move(p.v[kPmMove]), iv_still(p.v[kIvStill]), max_hold(p.v[kMaxHold]) {}
  Intent step(const MarketTick& t, std::int64_t now) noexcept {
    Intent out;
    if (!core.admit(t, now, out)) return out;
    const double p = blocks::PMid::read(t);
    const double iv = num(t.opt_iv) && t.opt_iv >= 0 ? t.opt_iv : kNaN;
    const double d1 = dpm.update(p), d2 = div.update(iv);
    if (num(iv)) last_iv = iv;
    const double pos = core.led.at(Instrument::Option);
    if (pos != 0) {
      ++held;
      const bool caught_up = num(iv) && num(iv_entry) &&
                             ((pos > 0 && iv - iv_entry >= 2 * iv_still) || (pos < 0 && iv_entry - iv >= 2 * iv_still));
      if ((held >= max_hold || caught_up) && num(t.opt_mid))
        return order(Instrument::Option, pos > 0 ? -1 : +1, std::abs(pos), kNaN, Rc::Exit, num(iv) ? iv - iv_entry : kNaN);
      return hold(Rc::NoSignal, d1);
    }
    if (!num(p) || !num(iv) || !num(t.opt_mid)) return hold(Rc::SignalMissing);
    if (!num(d1) || !num(d2)) return hold(Rc::Warmup);
    if (std::abs(d1) >= pm_move && std::abs(d2) <= iv_still)
      return order(Instrument::Option, +1, cap.max_abs, kNaN, Rc::Entry, d1);
    if (std::abs(d1) <= pm_move / 4 && d2 >= 3 * iv_still)
      return order(Instrument::Option, -1, cap.max_abs, kNaN, Rc::Entry, d2);
    return hold(Rc::NoSignal, d1);
  }
  void on_fill(Instrument i, double q, double px) noexcept {
    if (i != Instrument::Option) return;
    const bool was_flat = core.led.at(Instrument::Option) == 0;
    core.fill(i, q, px, 100.0);
    if (was_flat) { iv_entry = last_iv; held = 0; }
  }
};

// ---- eightk_opportunity -------------------------------------------------------------------------------------------
struct EightKOpportunity : AlgoBase<EightKOpportunity> {
  static constexpr const char* id = "eightk_opportunity";
  static constexpr const char* division = "opportunity";
  static constexpr const char* ui_kind = "Gate";
  static constexpr const char* idea =
      "A strong 8-K tag opens an event window; if the PM adverse probability confirms (falls after a bullish tag, "
      "rises after a bearish one) sell a cash-secured put or buy a put spread; close when the window ends";
  static constexpr const char* event_classes[] = {"corporate_8k", "company_specific"};
  static constexpr const char* instruments[] = {"option:cash_secured_put", "option:put_spread"};
  static constexpr BlockRef blocks[] = {
      {"signals", "EightKScore"}, {"signals", "ImpliedProb"}, {"signals", "DeltaDp"},
      {"gates", "Staleness"},     {"gates", "EventWindow"},   {"sizers", "FixedNotional"},
      {"risk", "PositionCap"}};
  enum P { kWindowH, kScoreThr, kConfirm, kContracts };
  static constexpr ParamSpec kSpec{
      param("window_h", 0.1, 720, 24, {1.0, 24.0, 72.0}, "hours the event window stays open after a tag"),
      param("score_thr", 0, 1, 0.5, {0.3, 0.5, 0.7}, "|8-K score| that opens the window"),
      param("pm_confirm", 0, 1, 0.01, {0.0, 0.01, 0.02}, "PM move (5 ticks) in the tag's direction required"),
      param("contracts", 1, 1e5, 1, {1.0, 5.0}, "contracts per entry")};
  static ParamSpec spec() noexcept { return kSpec; }

  OppCore core;
  blocks::EventWindow win;
  blocks::DeltaDp ddp{5};
  blocks::PositionCap cap;
  double thr, confirm, trig = 0;
  EightKOpportunity(const Params& p, const Position& pos) noexcept
      : core(pos, kSpec.valid(p)), win{static_cast<std::int64_t>(p.v[kWindowH] * 3600.0 * 1e9), p.v[kScoreThr]},
        cap{p.v[kContracts]}, thr(p.v[kScoreThr]), confirm(p.v[kConfirm]) {}
  Intent step(const MarketTick& t, std::int64_t now) noexcept {
    Intent out;
    if (!core.admit(t, now, out)) return out;
    const double s = blocks::EightKScore::read(t);
    const double dp = ddp.update(blocks::ImpliedProb::read(t));
    if (num(s) && std::abs(s) >= thr) trig = s;
    const bool open = win.pass({t, now, kNaN, kNaN, s});
    const double pos = core.led.at(Instrument::Option);
    if (pos != 0) {
      if (!open && num(t.opt_mid)) return order(Instrument::Option, pos > 0 ? -1 : +1, std::abs(pos), kNaN, Rc::Exit, trig);
      return hold(Rc::NoSignal, trig);
    }
    if (!open) return hold(Rc::OutsideEventWindow, s);
    if (!num(t.opt_mid)) return hold(Rc::SignalMissing, trig);
    if (!num(dp)) return hold(Rc::Warmup, trig);
    if (trig > 0 && dp <= -confirm) return order(Instrument::Option, -1, cap.max_abs, kNaN, Rc::Entry, trig);
    if (trig < 0 && dp >= confirm) return order(Instrument::Option, +1, cap.max_abs, kNaN, Rc::Entry, trig);
    return hold(Rc::NoSignal, dp);
  }
  void on_fill(Instrument i, double q, double px) noexcept {
    if (i == Instrument::Option) core.fill(i, q, px, 100.0);
  }
};

}  // namespace hedgecore::algos
