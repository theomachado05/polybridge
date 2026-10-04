#pragma once
#include <cmath>
#include <cstdint>
#include "hedgecore/algos/common.hpp"
#include "hedgecore/algos/ladder_pair.hpp"
#include "hedgecore/blocks/micro.hpp"

namespace hedgecore {

struct TicketTick {
  std::int64_t ts_ns = 0;
  double bid = kNaN, bid_qty = kNaN;
  double ask = kNaN;
  double ref_lower = kNaN;
  double ref_central = kNaN;
  Tri validated = Tri::Missing;
  double underlying_short = kNaN;
  double event_short = kNaN;
};

struct TicketIntent {
  MicroAction action = MicroAction::Hold;
  int side = 0;
  double qty = 0;
  double limit_px = kNaN;
  std::uint16_t reason = 0;
  double signal = kNaN;
  std::int64_t latency_ns = 0;
};

namespace algos {

struct TouchTicketReference {
  static constexpr const char* id = "touch_ticket_reference";
  static constexpr const char* division = "micro/ticket";
  static constexpr const char* ui_kind = "Reader";
  static constexpr const char* status = "unvalidated";
  static constexpr const char* idea =
      "Propose selling a 'will it hit' ticket at its bid when the bid is threshold points or more above the "
      "options-derived central touch reference; proposals only until the evidence gate validates the mechanism";
  static constexpr const char* event_classes[] = {"company_specific"};
  static constexpr const char* instruments[] = {"pred_yes"};
  static constexpr BlockRef blocks[] = {{"signals", "TouchReferenceGap"}, {"gates", "Staleness"},
                                        {"gates", "EvidenceGate"},        {"sizers", "SizeCap"},
                                        {"risk", "UnderlyingCap"},        {"risk", "EventCap"}};
  static constexpr const char* inputs[] = {"bid",         "bid_qty",   "ask",
                                           "ref_lower",   "ref_central", "validated",
                                           "underlying_short", "event_short"};
  enum P { kThreshold, kTicketCap, kUnderlyingCap, kEventCap, kMaxAge };
  static constexpr ParamSpec kSpec{
      param("threshold", 0, 100, 5, {5.0}, "points the bid must sit above the central reference"),
      param("ticket_cap", 0, 1e7, 100, {100.0}, "contracts sold per ticket (0 = off)"),
      param("underlying_cap", 0, 1e9, 300, {300.0}, "contracts sold across the underlying's tickets (0 = off)"),
      param("event_cap", 0, 1e9, 300, {300.0}, "contracts sold across the event's tickets (0 = off)"),
      param("max_age_s", 0, 86400, 30, {30.0}, "the ticket quote at most this many seconds old")};
  static ParamSpec spec() noexcept { return kSpec; }

  bool valid = false;
  bool bad = false;
  double threshold_pts = 0;
  blocks::FreshnessGuard fresh{};
  blocks::ContractCap ticket_cap{}, under_cap{}, event_cap{};
  double sold = 0;

  TouchTicketReference(const Params& p, const Position&) noexcept : valid(kSpec.valid(p)) {
    threshold_pts = p.v[kThreshold];
    ticket_cap.cap = p.v[kTicketCap];
    under_cap.cap = p.v[kUnderlyingCap];
    event_cap.cap = p.v[kEventCap];
    fresh.max_ns = static_cast<std::int64_t>(p.v[kMaxAge] * static_cast<double>(kNsPerSec));
  }

  static TicketIntent hold(Rc r, double signal = kNaN) noexcept {
    TicketIntent i;
    i.reason = code(r);
    i.signal = signal;
    return i;
  }

  TicketIntent on_tick(const TicketTick& t, std::int64_t now_ns) noexcept {
    const std::int64_t t0 = mono_ns();
    TicketIntent i = step(t, now_ns);
    i.latency_ns = mono_ns() - t0;
    return i;
  }

  TicketIntent step(const TicketTick& t, std::int64_t now) noexcept {
    if (!valid) return hold(Rc::InvalidParams);
    if (bad) return hold(Rc::InvalidState);
    if (!fresh.fresh(t.ts_ns, now)) return hold(Rc::Stale);
    if (!prob(t.bid) || !(t.bid_qty > 0) || !prob(t.ref_central)) return hold(Rc::SignalMissing);
    if (prob(t.ask) && t.ask < t.bid) return hold(Rc::Invalid);
    const double sig = 100.0 * (t.bid - t.ref_central);
    if (!(sig >= threshold_pts - 1e-9)) return hold(Rc::NoSignal, sig);
    bool capped = false;
    double q = t.bid_qty;
    for (const double room : {ticket_cap.room(sold), under_cap.room(num(t.underlying_short) ? t.underlying_short + sold
                                                                                              : kNaN),
                              event_cap.room(num(t.event_short) ? t.event_short + sold : kNaN)}) {
      if (std::isnan(room)) return hold(Rc::PositionUnknown, sig);
      if (room < q) { q = room; capped = true; }
    }
    if (!(q > 0)) return hold(Rc::EventCapped, sig);
    TicketIntent o;
    o.side = -1;
    o.qty = q;
    o.limit_px = t.bid;
    o.signal = sig;
    if (t.validated == Tri::True) {
      o.action = MicroAction::Order;
      o.reason = code(capped ? Rc::PositionCapped : Rc::Entry);
    } else {
      o.action = MicroAction::Propose;
      o.reason = code(Rc::Proposal);
    }
    return o;
  }

  void on_fill(double qty, double px) noexcept {
    if (!num(qty) || !num(px) || qty < 0) { bad = true; return; }
    sold += qty;
  }
};

}
}
