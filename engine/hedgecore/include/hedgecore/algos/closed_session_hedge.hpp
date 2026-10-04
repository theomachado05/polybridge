#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>
#include "hedgecore/algos/common.hpp"
#include "hedgecore/algos/hedge_params.hpp"

namespace hedgecore::algos {

struct ClosedSessionHedge : AlgoBase<ClosedSessionHedge> {
  static constexpr const char* id = "closed_session_hedge";
  static constexpr const char* division = "hedge";
  static constexpr const char* ui_kind = "Impact";
  static constexpr const char* idea =
      "While the stock market is closed, buy the adverse YES contract sized so a 1 pp PM move offsets the expected "
      "equity move (rate bp per pp); at the open unwind the PM leg and hand the hedge to the equity";
  static constexpr auto& event_classes = ev::kAll;
  static constexpr const char* instruments[] = {"pred_yes", "equity"};
  static constexpr BlockRef blocks[] = {
      {"signals", "ImpliedProb"}, {"gates", "Staleness"},   {"gates", "Session"},         {"sizers", "DeltaBridge"},
      {"risk", "PositionCap"},    {"risk", "NotionalCap"},  {"execution", "NoTradeBand"}, {"execution", "FeeGate"}};
  enum P { kCoverage, kRate, kRateScale, kBand, kMaxNotional, kExpMove, kHandoffEquity, kEquityBand };
  static constexpr ParamSpec kSpec{
      param("coverage", 0, 1, 0.5, {0.25, 0.5, 0.75, 1.0},
            "c: fraction of the held shares covered by the PM and equity legs combined"),
      param("rate_bp_per_pp", 0, 100, 7.52, {7.52},
            "r: bp of equity move per pp of PM move (per-market estimate, else the pooled 7.52 from 380 closures)"),
      param("rate_scale", 0, 5, 1.0, {0.5, 1.0, 1.5}, "multiplier on r (r_eff = r * scale)"),
      param("band_contracts", 0, 1e7, 50, {10.0, 50.0, 100.0},
            "no-trade band on the YES leg: trade only if |target - held| >= band contracts"),
      param("max_notional", 0, 1e9, 5000, {1000.0, 5000.0, 25000.0},
            "cap on YES contracts * YES price in $ (0 = off)"),
      param("exp_move_pp", 0, 100, 2, {2.0},
            "PM move (pp) expected over a closure; prices the fee gate's benefit; 0 disables the fee gate"),
      param("handoff_equity", 0, 1, 0, {0.0},
            "1 = after unwinding the YES leg at the open, move the hedge into the equity at round(c * N * p)"),
      param("equity_band", 0, 1e6, 10, {10.0}, "no-trade band in shares for the equity handoff leg")};
  static ParamSpec spec() noexcept { return kSpec; }

  static constexpr double kDone = 1e-9;
  static constexpr std::int64_t kBackoffBaseNs = kNsPerSec;
  static constexpr std::int64_t kBackoffMaxNs = 60 * kNsPerSec;

  HedgeCore core;
  blocks::Session session{true, true};
  blocks::DeltaBridge sizer;
  blocks::PositionCap risk_cap{};
  blocks::NotionalCap notional;
  blocks::NoTradeBand band;
  blocks::FeeGate fee_gate{1.0};
  FeeModel fees{};
  double coverage, rate_eff, exp_move;
  bool handoff_equity;
  double yes = 0;
  bool yes_bad = false;
  bool was_closed = false;
  bool handoff_due = false;
  double p_open = kNaN;
  double p_close = kNaN;
  std::int64_t sess_minute = std::numeric_limits<std::int64_t>::min();
  bool sess_closed = true;
  int yes_rejects = 0;
  int yes_last_side = 0;
  std::int64_t yes_sent_ns = 0;
  std::int64_t yes_retry_ns = std::numeric_limits<std::int64_t>::min();

  ClosedSessionHedge(const Params& p, const Position& pos) noexcept
      : core(pos, kSpec.valid(p), p.v[kEquityBand], 1.0, p.v[kRate] * p.v[kRateScale] * 1e-2, false, false),
        sizer{p.v[kCoverage], pos.shares_held},
        notional{p.v[kMaxNotional]},
        band{p.v[kBand]},
        coverage(p.v[kCoverage]),
        rate_eff(p.v[kRate] * p.v[kRateScale]),
        exp_move(p.v[kExpMove]),
        handoff_equity(p.v[kHandoffEquity] >= 0.5),
        yes(num(pos.pred_yes) ? pos.pred_yes : 0.0) {}

  double expected_gap_bp(double p) const noexcept {
    return (num(p) && num(p_close)) ? rate_eff * (p - p_close) * 100.0 : kNaN;
  }

  double raw_target(double s) const noexcept {
    if (!num(s) || s <= 0) return kNaN;
    const double n_cov = std::max(0.0, coverage * core.shares - std::max(0.0, core.hedge));
    return std::round(n_cov * s * rate_eff * 1e-2);
  }

  Intent send_yes(const MarketTick& t, std::int64_t now, int side, double qty, Rc why, double signal) noexcept {
    if (side != yes_last_side) { yes_rejects = 0; yes_retry_ns = std::numeric_limits<std::int64_t>::min(); }
    if (now < yes_retry_ns) return hold(Rc::Cooldown, signal);
    yes_last_side = side;
    yes_sent_ns = now;
    return order(Instrument::PredYes, side, qty, kNaN, why, signal, t.venue);
  }

  Intent closed_step(const MarketTick& t, std::int64_t now, double p) noexcept {
    const double sig = expected_gap_bp(p);
    const double s = under_ref(t);
    double target = raw_target(s);
    if (!num(target)) return hold(Rc::SignalMissing, sig);
    risk_cap.max_abs = floor_units(std::max(0.0, coverage * core.shares - std::max(0.0, core.hedge)) * s);
    bool pcap = false, ncap = false;
    target = risk_cap.clamp(target, pcap);
    double px = t.yes_ask;
    if (!prob(px)) px = prob(t.no_bid) ? 1.0 - t.no_bid : kNaN;
    target = notional.clamp(target, px, 1.0, ncap);
    if (!num(target)) return hold(Rc::NotionalUnknown, sig);
    const double delta = target - yes;
    if (!band.pass(delta)) {
      if (ncap) return hold(Rc::NotionalCapped, sig);
      if (pcap) return hold(Rc::PositionCapped, sig);
      return hold(delta == 0 ? Rc::ZeroTarget : Rc::InsideBand, sig);
    }
    if (delta > 0 && exp_move > 0) {
      const double hs = half_spread(t.yes_bid, t.yes_ask);
      const double fee = fees.unit_fee(Instrument::PredYes, t.venue, px);
      const double q = delta;
      const Rc fr = fee_gate.check(q * 0.01 * exp_move, num(hs) && num(fee) ? q * 2.0 * (hs + fee) : kNaN);
      if (fr != Rc::None) return hold(fr, sig);
    }
    const Rc why = ncap ? Rc::NotionalCapped : (pcap ? Rc::PositionCapped : Rc::Rebalance);
    return send_yes(t, now, delta > 0 ? +1 : -1, std::abs(delta), why, sig);
  }

  Intent open_step(const MarketTick& t, std::int64_t now, double p) noexcept {
    const double sig = expected_gap_bp(p);
    if (std::abs(yes) > kDone) {
      handoff_due = true;
      return send_yes(t, now, yes > 0 ? -1 : +1, std::abs(yes), Rc::Handoff, sig);
    }
    if (!handoff_equity) return hold(Rc::OutOfSession, sig);
    if (!prob(p)) return hold(Rc::SignalMissing);
    Intent i = core.decide(t, now, p, sizer.target(p), 0.0, sig, handoff_due ? Rc::Handoff : Rc::Rebalance);
    if (i.action == Action::Order) handoff_due = false;
    return i;
  }

  Intent step(const MarketTick& t, std::int64_t now) noexcept {
    Intent out;
    if (!core.admit(t, now, out)) return out;
    if (yes_bad || !num(yes)) return hold(Rc::InvalidState);
    const double pr = blocks::ImpliedProb::read(t);
    const double p = prob(pr) ? pr : kNaN;
    const std::int64_t minute = t.ts_ns >= 0 ? t.ts_ns / (60 * kNsPerSec) : -((-t.ts_ns - 1) / (60 * kNsPerSec)) - 1;
    if (minute != sess_minute) {
      sess_closed = !session.pass(blocks::GateIn{t, now});
      sess_minute = minute;
    }
    const bool closed = sess_closed;
    if (closed) {
      if (!was_closed) p_close = num(p_open) ? p_open : p;
      if (!num(p_close)) p_close = p;
      was_closed = true;
      return closed_step(t, now, p);
    }
    was_closed = false;
    if (num(p)) p_open = p;
    return open_step(t, now, p);
  }

  void on_fill(Instrument i, double q, double px) noexcept {
    if (i == Instrument::Equity) { core.on_fill(i, q, px); return; }
    if (i != Instrument::PredYes) return;
    if (!num(q) || !num(px)) { yes_bad = true; return; }
    yes += q;
    yes_rejects = 0;
    yes_retry_ns = std::numeric_limits<std::int64_t>::min();
  }
  void on_reject(Instrument i) noexcept {
    if (i == Instrument::Equity) { core.on_reject(i); return; }
    if (i != Instrument::PredYes) return;
    if (yes_rejects < 30) ++yes_rejects;
    if (yes_rejects >= 2)
      yes_retry_ns = yes_sent_ns + std::min(kBackoffMaxNs, kBackoffBaseNs << std::min(yes_rejects - 2, 6));
  }
};

}
