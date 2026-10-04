#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>
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
  const char* kind;
  const char* name;
};

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

namespace ev {
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

struct HedgeCore {
  bool valid = false;
  double shares = 0;
  double hedge = 0;
  double impact = 0.03;
  double p_last_order = 0;
  bool working = false;
  double work_target = 0;
  static constexpr double kDoneShares = 1e-6;
  static constexpr std::int64_t kBackoffBaseNs = kNsPerSec;
  static constexpr std::int64_t kBackoffMaxNs = 60 * kNsPerSec;
  int rejects = 0;
  int last_side = 0;
  std::int64_t last_send_ns = 0;
  std::int64_t retry_at_ns = std::numeric_limits<std::int64_t>::min();
  FeeModel fees{};
  blocks::Staleness stale{2 * kNsPerSec};
  blocks::Session session{};
  blocks::Cooldown cooldown{};
  blocks::DrawdownKill dd{};
  blocks::PositionCap cap{};
  blocks::NoTradeBand band{};
  blocks::FeeGate fee_gate{};
  blocks::Slicer slicer{};
  blocks::PassiveAggressive pa{0.0};
  blocks::TaxLotSelector lots{};
  blocks::WashSaleGuard wash{};
  Ledger ledger{};
  std::int64_t last_ts = 0;
  double seed_qty = 0;

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

  bool admit(const MarketTick& t, std::int64_t now, Intent& out) noexcept {
    if (!valid) { out = hold(Rc::InvalidParams); return false; }
    if (ledger.bad || !num(hedge)) { out = hold(Rc::InvalidState); return false; }
    const blocks::GateIn g{t, now};
    if (!stale.pass(g)) { out = hold(Rc::Stale); return false; }
    if (!session.pass(g)) { out = hold(Rc::OutOfSession); return false; }
    last_ts = t.ts_ns;
    if (seed_qty != 0 && num(under_ref(t))) {
      lots.apply_fill(seed_qty, under_ref(t), t.ts_ns);
      ledger.fill(Instrument::Equity, seed_qty, under_ref(t), 1.0);
      seed_qty = 0;
    }
    return true;
  }

  Rc fee_check(const MarketTick& t, double u, double q, double p_adv) const noexcept {
    if (impact <= 0) return Rc::None;
    if (!num(u)) return Rc::FeeUnknown;
    double hs = half_spread(t.under_bid, t.under_ask);
    if (!num(hs)) hs = fees.equity_half_spread;
    const double cost = q * (fees.equity_per_share + hs);
    const double benefit = q * u * impact * std::abs(p_adv - p_last_order);
    return fee_gate.check(benefit, cost);
  }

  Intent decide(const MarketTick& t, std::int64_t now, double p_adv, double target, double urgency, double signal,
                Rc why = Rc::Rebalance) noexcept {
    if (!num(target) || !num(p_adv)) return hold(Rc::SignalMissing, signal);
    const double u = under_ref(t);
    bool capped = false;
    target = cap.clamp(target < 0 ? 0.0 : target, capped);
    if (dd.update(num(u) ? ledger.cash + ledger.at(Instrument::Equity) * u : kNaN)) {
      working = false;
      if (!(target < hedge) || !band.pass(target - hedge)) return hold(Rc::DrawdownKill, signal);
      return send(t, now, target - hedge, urgency, signal, Rc::DrawdownKill, capped);
    }
    double delta = target - hedge;
    double rem = working ? work_target - hedge : 0.0;
    if (working && (std::abs(rem) < kDoneShares || sgn(rem) != sgn(delta))) { working = false; rem = 0.0; }
    if (working && !band.pass(delta)) { working = false; return hold(Rc::InsideBand, signal); }
    if (working) {
      const double extra = std::abs(delta) - std::abs(rem);
      if (extra > 0) {
        if (band.pass(extra) && fee_check(t, u, extra, p_adv) == Rc::None) p_last_order = p_adv;
        else { target = work_target; delta = rem; capped = false; }
      }
      work_target = target;
    } else {
      if (!band.pass(delta)) return hold(Rc::InsideBand, signal);
      const Rc fr = fee_check(t, u, std::abs(delta), p_adv);
      if (fr != Rc::None) return hold(fr, signal);
      working = true;
      work_target = target;
      p_last_order = p_adv;
    }
    return send(t, now, delta, urgency, signal, why, capped);
  }

  Intent send(const MarketTick& t, std::int64_t now, double delta, double urgency, double signal, Rc why,
              bool capped) noexcept {
    const int side = delta > 0 ? -1 : +1;
    if (side < 0 && !wash.allows(-1, t.ts_ns)) return hold(Rc::WashSale, signal);
    if (side != last_side) { rejects = 0; retry_at_ns = std::numeric_limits<std::int64_t>::min(); }
    if (now < retry_at_ns) return hold(Rc::Cooldown, signal);
    if (!cooldown.pass(blocks::GateIn{t, now})) return hold(Rc::Cooldown, signal);
    last_side = side;
    last_send_ns = now;
    bool sliced = false;
    const double qty = std::abs(slicer.clip(delta, sliced));
    const double limit = pa.limit(side, t.under_bid, t.under_ask, urgency);
    cooldown.on_order(now);
    const Rc r = capped ? Rc::PositionCapped : (sliced ? Rc::Sliced : why);
    return order(Instrument::Equity, side, qty, limit, r, signal);
  }

  void on_reject(Instrument i) noexcept {
    if (i != Instrument::Equity) return;
    cooldown.last_ns = std::numeric_limits<std::int64_t>::min();
    if (rejects < 30) ++rejects;
    if (rejects >= 2)
      retry_at_ns = last_send_ns + std::min(kBackoffMaxNs, kBackoffBaseNs << std::min(rejects - 2, 6));
  }

  void on_fill(Instrument i, double signed_qty, double px) noexcept {
    if (i != Instrument::Equity) return;
    if (!num(signed_qty) || !num(px)) { ledger.bad = true; return; }
    ledger.fill(i, signed_qty, px, 1.0);
    hedge -= signed_qty;
    rejects = 0;
    retry_at_ns = std::numeric_limits<std::int64_t>::min();
    if (working && std::abs(work_target - hedge) < kDoneShares) working = false;
    wash.record(lots.apply_fill(signed_qty, px, last_ts), last_ts);
  }
};

}
