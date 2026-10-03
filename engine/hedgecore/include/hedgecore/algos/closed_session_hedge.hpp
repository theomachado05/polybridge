#pragma once
// closed_session_hedge: hedge A of closed-market mode (docs/design.md, section 2, Product behaviour 4).
// While US equities are closed (nights, weekends, NYSE holidays, one-off closures, and from 13:00 ET on early-close
// days; judged on the tick's own timestamp so a replayed Saturday behaves like a Saturday) the stock cannot be traded
// but the prediction market can. The calendar is us_equity_regular_session (util.hpp), the same rules as the backend
// session clock (backend/app/closed/session.py). The family buys the
// adverse YES contract (Instrument::PredYes), sized to offset the expected equity move, and at the next regular
// session it hands off: it unwinds the YES leg first and then, when `handoff_equity` = 1, moves the hedge into the
// equity at the DeltaBridge target round(c * N * p_adverse) through the shared HedgeCore pipeline.
//
// Sizing (documented derivation):
//   * The research rate r is in bp of equity move per percentage point (pp) of PM move: across 380 closures a 1 pp
//     rise in the adverse YES went with about r = 7.52 bp of adverse open gap. The rate is per market when the backend
//     has enough of that market's closures (passed in `rate_bp_per_pp`), else the pooled figure.
//   * Expected equity loss per 1 pp adverse move: N_cov * S * r * 1e-4 dollars, with S the underlying price (the last
//     close while the market is shut) and N_cov the shares still to be covered.
//   * A YES contract pays $1 at resolution, so its value moves $0.01 per pp.
//   * Contracts that offset the loss: N_cov * S * r * 1e-4 / 0.01 = N_cov * S * r * 1e-2, rounded to whole contracts.
//     Example: N_cov = 500, S = $100, r = 7.52 -> 3,760 contracts (a 1 pp move: equity -$37.60, YES leg +$37.60).
//   * N_cov = max(0, c * N - h_eq): coverage c applies to the PM and equity legs combined, so an equity short h_eq
//     already in place (e.g. from the previous session) reduces the PM leg one for one.
//   * r_eff = rate_bp_per_pp * rate_scale (the tuned scaling of the research rate).
// Caps: PositionCap keeps the YES leg's resolution payoff (contracts * $1) at or below the covered equity value
// N_cov * S, so the hedge never turns into a net bet on the event; NotionalCap keeps contracts * YES price at or below
// max_notional. Fee gate on increments only: the protection an increment buys on an expected exp_move_pp move over the
// closure (q * 0.01 * exp_move_pp) must cover its round trip (q * 2 * (YES half-spread + taker fee)); reductions are
// risk-reducing and skip it.
//
// Contracts with the caller:
//   * Combined coverage needs every equity fill for this holding. The equity short h_eq is Position::equity at
//     construction plus every on_fill(Instrument::Equity, signed_qty, px) since. When another component fills the
//     equity leg (the staged-order book with the default handoff_equity = 0), the bridge must forward those fills to
//     this algo via on_fill("equity", ...) or rebuild the algo with the current Position::equity before each closure;
//     otherwise the next closure sizes the YES leg on the full c * N and PM + equity together exceed c * N.
//   * Intent::signal is the expected adverse open gap in bp on every path, r_eff * (p - p_close) * 100, NaN until a
//     close mark exists (or with no probability). p_close is the last in-session adverse probability before the
//     current (or, in session, the previous) closure. An algo built during a closure has no in-session mark, so its
//     p_close is the first closed tick's probability and the signal measures the move since the algo started, not
//     since the regular close. The backend closure tracker (backend/app/closed/tracker.py) is the source of truth
//     for the expected gap shown to users; this signal is diagnostic and does not size the leg.
// Nothing here allocates or makes a virtual call on the tick path.
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

  HedgeCore core;  // admission (validity, staleness) and the equity handoff leg
  blocks::Session session{true, true};  // enabled, full NYSE calendar (inverted)
  blocks::DeltaBridge sizer;
  blocks::PositionCap risk_cap{};
  blocks::NotionalCap notional;
  blocks::NoTradeBand band;
  blocks::FeeGate fee_gate{1.0};
  FeeModel fees{};
  double coverage, rate_eff, exp_move;
  bool handoff_equity;
  double yes = 0;         // held adverse YES contracts (own fills plus any pre-existing Position::pred_yes)
  bool yes_bad = false;   // a non-finite YES fill latches InvalidState
  bool was_closed = false;
  bool handoff_due = false;  // the next equity order after an unwind is tagged Handoff
  double p_open = kNaN;   // adverse probability at the last in-session tick
  double p_close = kNaN;  // adverse probability when the current closure began (closure tracker)
  // Session state is constant within a UTC minute (the session edges, early closes included, fall on whole minutes
  // and the DST offsets are whole hours), so the calendar check runs once per minute of tick time.
  std::int64_t sess_minute = std::numeric_limits<std::int64_t>::min();
  bool sess_closed = true;
  // YES-leg reject backoff, as HedgeCore's for equity: the first reject is re-sent at once, the k-th (k >= 2) waits
  // 2^(k-2) s (at most 60 s) after the rejected send. A fill or an order on the other side resets it, so rejected
  // buys during a closure never delay the handoff sell at the open.
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
  // HedgeCore's impact (expected fractional stock move if the adverse event resolves, pricing its equity fee gate) is
  // the rate's own: r_eff bp/pp * 100 pp * 1e-4 = r_eff * 1e-2.

  // Expected adverse open gap in bp implied by the PM move since the close (positive = expected equity loss).
  double expected_gap_bp(double p) const noexcept {
    return (num(p) && num(p_close)) ? rate_eff * (p - p_close) * 100.0 : kNaN;
  }

  // Contracts that offset the expected equity move per pp (see the header), before caps. NaN if S is unknown.
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
    double px = t.yes_ask;  // YES price for the notional cap: the ask, else its NO-parity 1 - no_bid
    if (!prob(px)) px = prob(t.no_bid) ? 1.0 - t.no_bid : kNaN;
    target = notional.clamp(target, px, 1.0, ncap);
    if (!num(target)) return hold(Rc::NotionalUnknown, sig);
    const double delta = target - yes;
    if (!band.pass(delta)) {  // a cap that holds the leg below its sized target is named as the reason
      if (ncap) return hold(Rc::NotionalCapped, sig);
      if (pcap) return hold(Rc::PositionCapped, sig);
      return hold(delta == 0 ? Rc::ZeroTarget : Rc::InsideBand, sig);
    }
    if (delta > 0 && exp_move > 0) {  // fee gate on increments: protection on an exp_move_pp move vs round trip
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
    const double sig = expected_gap_bp(p);  // p_close still marks the closure that just ended
    if (std::abs(yes) > kDone) {  // handoff, step 1: unwind the whole YES leg at market
      handoff_due = true;
      return send_yes(t, now, yes > 0 ? -1 : +1, std::abs(yes), Rc::Handoff, sig);
    }
    if (!handoff_equity) return hold(Rc::OutOfSession, sig);  // the family's own session is the closure
    if (!prob(p)) return hold(Rc::SignalMissing);
    // Handoff, step 2 (optional): the equity leg at the DeltaBridge target through HedgeCore (band, fee gate,
    // backoff). Later in-session moves are ordinary rebalances.
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
    if (minute != sess_minute) {  // Session gate inverted, on the tick's own ts
      sess_closed = !session.pass(blocks::GateIn{t, now});
      sess_minute = minute;
    }
    const bool closed = sess_closed;
    if (closed) {
      if (!was_closed) p_close = num(p_open) ? p_open : p;  // a closure began: mark the PM at the close
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

}  // namespace hedgecore::algos
