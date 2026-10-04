#pragma once
// ladder_pair: one nested pair of a date (or strike) ladder. The rich rung can never be worth more than the cheap
// rung (an earlier "by" date, or a further "reach" level, resolves YES only if the other does). When the rich rung's
// best bid clears the cheap rung's best ask by both taker fees, one tick and min_edge, sell the rich rung at its bid
// and buy the cheap rung at its ask, the same quantity on both legs, and hold both to the result.
// Status: lead. See note/NOTE.md section 3: the registered fresh test was NULL; the positive result rests on a
// year check fixed after the run.
//
// Input is LadderTick, not MarketTick: two books, two fee rates, two quote times and the linker's nested flag.
#include <cmath>
#include <cstdint>
#include "hedgecore/algos/common.hpp"
#include "hedgecore/blocks/micro.hpp"

namespace hedgecore {

struct LadderTick {  // NaN / kNoTime / Tri::Missing = not available (the default for every field)
  std::int64_t ts_ns = 0;
  double bid_rich = kNaN, bid_rich_qty = kNaN;    // best YES bid and its size on the rich rung
  double ask_cheap = kNaN, ask_cheap_qty = kNaN;  // best YES ask and its size on the cheap rung
  double fee_rate_rich = kNaN, fee_rate_cheap = kNaN;  // taker fee per contract = rate * p * (1 - p)
  double tick = kNaN;                             // the coarser of the two rungs' price ticks
  std::int64_t ts_rich_ns = kNoTime, ts_cheap_ns = kNoTime;  // quote times of the two books
  Tri nested = Tri::Missing;                      // from the linker; anything but True refuses
  double event_held = kNaN;  // contracts held on the event's OTHER pairs (from the bridge), for the per-event cap
};

enum class MicroAction : std::uint8_t { Hold = 0, Order = 1, Propose = 2, Cancel = 3, Unwind = 4 };
enum class Leg : std::uint8_t { Rich = 0, Cheap = 1 };

struct LegOrder {
  int side = 0;           // +1 buy YES, -1 sell YES; 0 = no order on this leg
  double qty = 0;
  double limit_px = kNaN;  // NaN = marketable (only for an Unwind)
};

// Order: both legs together, same qty, limits at the quoted prices (fill at the quote or not at all).
// Cancel: cancel the leg still out (`cancel` names it); the other leg was rejected.
// Unwind: flatten the excess of the leg that filled more than the other (marketable).
struct PairIntent {
  MicroAction action = MicroAction::Hold;
  LegOrder rich{}, cheap{};
  Leg cancel = Leg::Rich;
  std::uint16_t reason = 0;
  double signal = kNaN;  // net edge at the quotes in points (bid - ask - both fees - one tick)
  std::int64_t latency_ns = 0;
};

namespace algos {

struct LadderPair {
  static constexpr const char* id = "ladder_pair";
  static constexpr const char* division = "micro/ladder";
  static constexpr const char* ui_kind = "Gate";
  static constexpr const char* status = "lead";
  static constexpr const char* idea =
      "One nested ladder pair: when the rich rung's bid clears the cheap rung's ask by both taker fees, one tick and "
      "min_edge, sell the rich rung at its bid and buy the cheap rung at its ask, same size, held to the result";
  static constexpr const char* event_classes[] = {"company_specific", "geopolitics_energy", "elections", "macro_fed"};
  static constexpr const char* instruments[] = {"pred_yes"};
  static constexpr BlockRef blocks[] = {
      {"gates", "NestedGuard"},     {"gates", "FreshnessGuard"}, {"execution", "FeeGate"},
      {"sizers", "SizeCap"},        {"risk", "EventCap"},        {"risk", "LegRiskGuard"},
      {"risk", "CapitalLock"},      {"gates", "Cooldown"}};
  static constexpr const char* inputs[] = {"bid_rich",       "bid_rich_qty", "ask_cheap",  "ask_cheap_qty",
                                           "fee_rate_rich",  "fee_rate_cheap", "tick",     "ts_rich_ns",
                                           "ts_cheap_ns",    "nested",       "event_held"};
  enum P { kMinEdge, kMaxAge, kCap, kEventCap, kCooldown };
  static constexpr ParamSpec kSpec{
      param("min_edge", 0, 100, 1, {1.0, 2.0, 3.0}, "points left after both taker fees and one tick to act"),
      param("max_age_s", 0, 86400, 30, {10.0, 30.0, 60.0}, "both quotes at most this many seconds old"),
      param("cap", 0, 1e7, 100, {100.0, 500.0}, "contracts per entry: the smaller displayed size, up to this"),
      param("event_cap", 0, 1e9, 1000, {1000.0}, "contracts held across the event's pairs (0 = off)"),
      param("cooldown_s", 0, 1e7, 3600, {3600.0}, "seconds between two entries on this pair (the replayed rule's gap)")};
  static ParamSpec spec() noexcept { return kSpec; }

  bool valid = false;
  bool bad = false;
  blocks::NestedGuard nested{};
  blocks::FreshnessGuard fresh{};
  blocks::FeeGate fee_gate{1.0};
  blocks::PositionCap size_cap{};
  blocks::ContractCap event_cap{};
  blocks::Cooldown cooldown{};
  blocks::CapitalLock capital{};
  double min_edge = 0;  // fraction of $1

  // Pairs held to the result (matched contracts on both legs).
  double held = 0;
  // Leg-risk state. While `working`, both legs of the last entry are out.
  bool working = false;
  double want = 0;
  double filled[2] = {0, 0};
  double fill_px[2] = {0, 0};  // quantity-weighted fill price of the working entry per leg
  bool done[2] = {false, false};
  bool cancel_sent = false;
  double fee_pc = 0;           // both taker fees per contract at the entry quotes
  double excess[2] = {0, 0};   // contracts on one leg with no partner: to unwind
  bool unwind_out = false;
  bool flagged = false;        // legs filled unequally: entries stop (latched, like the other kill switches)
  std::uint32_t leg_risk_events = 0;

  LadderPair(const Params& p, const Position&) noexcept : valid(kSpec.valid(p)) {
    min_edge = p.v[kMinEdge] / 100.0;
    fresh.max_ns = static_cast<std::int64_t>(p.v[kMaxAge] * static_cast<double>(kNsPerSec));
    size_cap.max_abs = p.v[kCap];
    event_cap.cap = p.v[kEventCap];
    cooldown.min_ns = static_cast<std::int64_t>(p.v[kCooldown] * static_cast<double>(kNsPerSec));
  }

  static PairIntent hold(Rc r, double signal = kNaN) noexcept {
    PairIntent i;
    i.reason = code(r);
    i.signal = signal;
    return i;
  }

  PairIntent on_tick(const LadderTick& t, std::int64_t now_ns) noexcept {  // AlgoBase::on_tick's latency stamp
    const std::int64_t t0 = mono_ns();
    PairIntent i = step(t, now_ns);
    i.latency_ns = mono_ns() - t0;
    return i;
  }

  PairIntent step(const LadderTick& t, std::int64_t now) noexcept {
    if (!valid) return hold(Rc::InvalidParams);
    if (bad) return hold(Rc::InvalidState);
    // Leg-risk guard first: an unpaired leg is flattened before anything else happens.
    if (excess[0] > 0 || excess[1] > 0) {
      if (unwind_out) return hold(Rc::LegRisk);
      PairIntent u;
      u.action = MicroAction::Unwind;
      u.reason = code(Rc::LegRisk);
      if (excess[0] > 0) u.rich = {+1, excess[0], kNaN};   // buy back rich YES sold without a partner
      if (excess[1] > 0) u.cheap = {-1, excess[1], kNaN};  // sell cheap YES bought without a partner
      unwind_out = true;
      return u;
    }
    if (working) {
      if ((done[0] != done[1]) && !cancel_sent) {
        const int open = done[0] ? 1 : 0;
        if (filled[1 - open] < want - 1e-9) {  // the finished leg came up short: cancel the other one
          PairIntent c;
          c.action = MicroAction::Cancel;
          c.cancel = static_cast<Leg>(open);
          c.reason = code(Rc::LegRisk);
          cancel_sent = true;
          return c;
        }
      }
      return hold(Rc::Working);
    }
    if (flagged) return hold(Rc::LegRisk);
    if (!nested.pass(t.nested)) return hold(Rc::NotNested);
    if (!fresh.fresh(t.ts_rich_ns, now) || !fresh.fresh(t.ts_cheap_ns, now)) return hold(Rc::Stale);
    if (!prob(t.bid_rich) || !prob(t.ask_cheap) || !(t.bid_rich_qty > 0) || !(t.ask_cheap_qty > 0) || !num(t.tick) ||
        t.tick < 0)
      return hold(Rc::SignalMissing);
    const double f_rich = poly_taker_fee(t.fee_rate_rich, t.bid_rich);
    const double f_cheap = poly_taker_fee(t.fee_rate_cheap, t.ask_cheap);
    if (!num(f_rich) || !num(f_cheap)) return hold(Rc::FeeUnknown);
    const double gross = t.bid_rich - t.ask_cheap - t.tick;
    const double edge = gross - f_rich - f_cheap;
    const double sig = 100.0 * edge;
    // FeeGate: what the quotes leave after one tick must pay both fees plus min_edge (a 1e-12 allowance for binary
    // rounding of prices given in cents).
    if (fee_gate.check(gross - min_edge + 1e-12, f_rich + f_cheap) != Rc::None) return hold(Rc::BelowFees, sig);
    if (cooldown.min_ns > 0 && cooldown.last_ns != kNoTime && now - cooldown.last_ns < cooldown.min_ns)
      return hold(Rc::Cooldown, sig);
    bool capped = false;
    double q = size_cap.clamp(std::min(t.bid_rich_qty, t.ask_cheap_qty), capped);
    const double room = event_cap.room(num(t.event_held) ? t.event_held + held : kNaN);
    if (!num(room) && !std::isinf(room)) return hold(Rc::PositionUnknown, sig);
    if (room < q) { q = room; capped = true; }
    if (!(q > 0)) return hold(Rc::EventCapped, sig);
    working = true;
    want = q;
    filled[0] = filled[1] = 0;
    fill_px[0] = fill_px[1] = 0;
    done[0] = done[1] = false;
    cancel_sent = false;
    fee_pc = f_rich + f_cheap;
    cooldown.on_order(now);
    PairIntent o;
    o.action = MicroAction::Order;
    o.rich = {-1, q, t.bid_rich};
    o.cheap = {+1, q, t.ask_cheap};
    o.reason = code(capped ? Rc::PositionCapped : Rc::Entry);
    o.signal = sig;
    return o;
  }

  // qty is the absolute quantity filled on that leg at px.
  void on_fill(Leg leg, double qty, double px) noexcept {
    const int k = static_cast<int>(leg);
    if (!num(qty) || !num(px) || qty < 0) { bad = true; return; }
    if (excess[k] > 0) {  // an unwind fill (only one leg can have an excess)
      excess[k] -= qty;
      if (excess[k] <= 1e-9) { excess[k] = 0; unwind_out = false; }
      return;
    }
    if (!working) { bad = true; return; }  // a fill for nothing we sent
    fill_px[k] = filled[k] + qty > 0 ? (fill_px[k] * filled[k] + px * qty) / (filled[k] + qty) : px;
    filled[k] += qty;
    if (filled[k] >= want - 1e-9) done[k] = true;
    settle_if_done();
  }

  // The leg's remaining quantity is dead (rejected, expired, cancelled). An unwind reject re-sends next tick.
  void on_reject(Leg leg) noexcept {
    const int k = static_cast<int>(leg);
    if (excess[k] > 0) { unwind_out = false; return; }
    if (!working) return;
    done[k] = true;
    settle_if_done();
  }

  void settle_if_done() noexcept {
    if (!(done[0] && done[1])) return;
    working = false;
    const double m = std::min(filled[0], filled[1]);
    if (m > 0) {
      held += m;
      capital.add(m, fill_px[0], fill_px[1], fee_pc);
    }
    excess[0] = filled[0] - m;
    excess[1] = filled[1] - m;
    if (excess[0] <= 1e-9) excess[0] = 0;
    if (excess[1] <= 1e-9) excess[1] = 0;
    if (excess[0] > 0 || excess[1] > 0) {  // one leg filled more than the other: a single leg was held
      flagged = true;
      ++leg_risk_events;
    }
  }
};

}  // namespace algos
}  // namespace hedgecore
