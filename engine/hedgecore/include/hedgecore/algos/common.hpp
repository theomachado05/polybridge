#pragma once
// Shared pieces of the algo families: catalog metadata types, the CRTP latency wrapper, a small ledger, and
// HedgeCore, the equity-hedge pipeline that the 11 hedge families feed with their own signal and target.
// Nothing here allocates or makes a virtual call on the tick path.
#include <cmath>
#include <cstdint>
#include <string_view>
#include "hedgecore/blocks/execution.hpp"
#include "hedgecore/blocks/gates.hpp"
#include "hedgecore/blocks/risk.hpp"
#include "hedgecore/blocks/routing.hpp"
#include "hedgecore/blocks/signals.hpp"
#include "hedgecore/blocks/sizers.hpp"
#include "hedgecore/blocks/tax.hpp"
#include "hedgecore/fees.hpp"
#include "hedgecore/market.hpp"
#include "hedgecore/params.hpp"
#include "hedgecore/reasons.hpp"
#include "hedgecore/util.hpp"

namespace hedgecore {

struct BlockRef {
  const char* kind;  // signals | gates | sizers | execution | risk | tax | routing
  const char* name;
};

// UI library grouping (spec §9): signals -> Reader, sizers -> Impact, gates -> Gate, execution -> Execution,
// tax -> Tax, routing -> Routing. Risk blocks cap or stop trading, so they are shown under Gate.
constexpr const char* ui_kind_of(const char* kind) noexcept {
  const std::string_view k{kind};
  if (k == "signals") return "Reader";
  if (k == "sizers") return "Impact";
  if (k == "gates" || k == "risk") return "Gate";
  if (k == "execution") return "Execution";
  if (k == "tax") return "Tax";
  if (k == "routing") return "Routing";
  return "Other";
}

namespace ev {  // event classes (spec §4 step 1)
inline constexpr const char* kAll[] = {"macro_fed",      "elections", "tariffs_trade", "geopolitics_energy",
                                      "housing",        "fig",       "tech_regulation", "crypto",
                                      "corporate_8k",   "company_specific"};
}

inline Intent hold(Rc r, double signal = kNaN) noexcept {
  Intent i;
  i.reason = code(r);
  i.signal = signal;
  return i;
}
inline Intent order(Instrument inst, int side, double qty, double limit, Rc r, double signal,
                    Venue v = Venue::Poly) noexcept {
  Intent i;
  i.action = Action::Order;
  i.instrument = inst;
  i.side = side;
  i.qty = qty;
  i.limit_px = limit;
  i.reason = code(r);
  i.signal = signal;
  i.venue = v;
  return i;
}

// CRTP wrapper: measures the family's step() and stamps latency_ns. No virtual dispatch.
template <class D>
struct AlgoBase {
  Intent on_tick(const MarketTick& t, std::int64_t now_ns) noexcept {
    const std::int64_t t0 = mono_ns();
    Intent i = static_cast<D*>(this)->step(t, now_ns);
    i.latency_ns = mono_ns() - t0;
    return i;
  }
};

inline bool position_ok(const Position& p) noexcept {
  return num(p.equity) && num(p.pred_yes) && num(p.pred_no) && num(p.option) && num(p.shares_held) &&
         p.shares_held >= 0;
}

// Cash and signed positions from the algo's own fills, marked at the latest tick (fees are not known to the algo;
// replay() accounts for them).
struct Ledger {
  double cash = 0;
  double pos[4] = {0, 0, 0, 0};
  bool bad = false;
  void fill(Instrument i, double signed_qty, double px, double mult) noexcept {
    if (!num(signed_qty) || !num(px)) { bad = true; return; }
    cash -= signed_qty * px * mult;
    pos[static_cast<int>(i)] += signed_qty;
  }
  double& at(Instrument i) noexcept { return pos[static_cast<int>(i)]; }
  double at(Instrument i) const noexcept { return pos[static_cast<int>(i)]; }
};

// ---------------------------------------------------------------------------------------------------------------
// HedgeCore: staleness -> session -> [family signal + target] -> drawdown kill -> position cap -> no-trade band ->
// fee gate -> wash-sale guard -> cooldown -> slicer -> passive/aggressive. The hedge is a short equity position of
// `hedge` shares (Position::equity == -hedge) protecting Position::shares_held long shares.
// ---------------------------------------------------------------------------------------------------------------
struct HedgeCore {
  bool valid = false;
  double shares = 0;       // N
  double hedge = 0;        // current short hedge in shares (>= 0 normally)
  double impact = 0.03;    // expected fractional move of the stock if the adverse event resolves; 0 disables FeeGate
  double p_last_order = 0; // adverse probability at the last emitted order (Engine semantics)
  FeeModel fees{};
  blocks::Staleness stale{2 * kNsPerSec};
  blocks::Session session{};
  blocks::Cooldown cooldown{};
  blocks::DrawdownKill dd{};
  blocks::PositionCap cap{};
  blocks::NoTradeBand band{};
  blocks::FeeGate fee_gate{};
  blocks::Slicer slicer{};
  blocks::PassiveAggressive pa{0.0};  // threshold 0: marketable; families that work orders passively raise it
  blocks::TaxLotSelector lots{};
  blocks::WashSaleGuard wash{};
  Ledger ledger{};
  std::int64_t last_ts = 0;
  double seed_qty = 0;  // a pre-existing hedge enters the lot ledger at the first known price

  HedgeCore() = default;
  HedgeCore(const Position& p, bool params_ok, double band_shares, double fee_ratio, double impact_, bool session_on,
            bool wash_on) noexcept {
    valid = params_ok && position_ok(p);
    shares = p.shares_held;
    hedge = -p.equity;
    cap.max_abs = shares;
    band.band = band_shares;
    fee_gate.ratio = fee_ratio;
    impact = impact_;
    session.enabled = session_on;
    wash.enabled = wash_on;
    lots.mode = blocks::TaxLotSelector::HIFO;
    if (p.equity != 0 && num(p.equity)) seed_qty = p.equity;
  }

  // Step 1: validity, staleness, session. Returns false with `out` set to the Hold.
  bool admit(const MarketTick& t, std::int64_t now, Intent& out) noexcept {
    if (!valid) { out = hold(Rc::InvalidParams); return false; }
    if (ledger.bad || !num(hedge)) { out = hold(Rc::InvalidState); return false; }
    const blocks::GateIn g{t, now};
    if (!stale.pass(g)) { out = hold(Rc::Stale); return false; }
    if (!session.pass(g)) { out = hold(Rc::OutOfSession); return false; }
    last_ts = t.ts_ns;
    if (seed_qty != 0 && num(under_ref(t))) { lots.apply_fill(seed_qty, under_ref(t), t.ts_ns); seed_qty = 0; }
    return true;
  }

  // Step 2: the family's target (short shares) for adverse probability p_adv.
  Intent decide(const MarketTick& t, std::int64_t now, double p_adv, double target, double urgency, double signal,
                Rc why = Rc::Rebalance) noexcept {
    if (!num(target) || !num(p_adv)) return hold(Rc::SignalMissing, signal);
    const double u = under_ref(t);
    if (dd.update(num(u) ? ledger.cash + ledger.at(Instrument::Equity) * u : kNaN)) return hold(Rc::DrawdownKill, signal);
    bool capped = false;
    target = cap.clamp(target < 0 ? 0.0 : target, capped);
    const double delta = target - hedge;
    if (!band.pass(delta)) return hold(Rc::InsideBand, signal);
    if (impact > 0) {
      if (!num(u)) return hold(Rc::FeeUnknown, signal);
      double hs = half_spread(t.under_bid, t.under_ask);
      if (!num(hs)) hs = fees.equity_half_spread;
      const double q = std::abs(delta);
      const double cost = q * (fees.equity_per_share + hs);
      const double benefit = q * u * impact * std::abs(p_adv - p_last_order);
      const Rc fr = fee_gate.check(benefit, cost);
      if (fr != Rc::None) return hold(fr, signal);
    }
    const int side = delta > 0 ? -1 : +1;  // sell to add to the short hedge
    if (side < 0 && !wash.allows(-1, t.ts_ns)) return hold(Rc::WashSale, signal);
    if (!cooldown.pass(blocks::GateIn{t, now})) return hold(Rc::Cooldown, signal);
    bool sliced = false;
    const double qty = std::abs(slicer.clip(delta, sliced));
    const double limit = pa.limit(side, t.under_bid, t.under_ask, urgency);
    p_last_order = p_adv;
    cooldown.on_order(now);
    const Rc r = capped ? Rc::PositionCapped : (sliced ? Rc::Sliced : why);
    return order(Instrument::Equity, side, qty, limit, r, signal);
  }

  void on_fill(Instrument i, double signed_qty, double px) noexcept {
    if (i != Instrument::Equity) return;
    if (!num(signed_qty) || !num(px)) { ledger.bad = true; return; }
    ledger.fill(i, signed_qty, px, 1.0);
    hedge -= signed_qty;
    wash.record(lots.apply_fill(signed_qty, px, last_ts), last_ts);
  }
};

}  // namespace hedgecore
