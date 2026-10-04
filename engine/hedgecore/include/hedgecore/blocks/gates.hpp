#pragma once
#include <array>
#include <cmath>
#include <cstdint>
#include <limits>
#include <variant>
#include "hedgecore/market.hpp"
#include "hedgecore/reasons.hpp"
#include "hedgecore/util.hpp"

namespace hedgecore::blocks {

struct GateIn {
  const MarketTick& t;
  std::int64_t now_ns;
  double dp = kNaN;
  double sigma = kNaN;
  double trigger = kNaN;
};

struct Staleness {
  static constexpr const char* name = "Staleness";
  static constexpr Rc fail = Rc::Stale;
  std::int64_t max_ns = 2 * kNsPerSec;
  bool pass(const GateIn& g) noexcept {
    if (g.t.ts_ns > g.now_ns || max_ns < 0) return false;
    const auto age = static_cast<std::uint64_t>(g.now_ns) - static_cast<std::uint64_t>(g.t.ts_ns);
    return age <= static_cast<std::uint64_t>(max_ns);
  }
};

struct Sigma {
  static constexpr const char* name = "Sigma";
  static constexpr Rc fail = Rc::BelowSigma;
  double k = 2.0;
  bool pass(const GateIn& g) noexcept {
    if (k <= 0) return true;
    if (!num(g.sigma)) return true;
    if (!num(g.dp)) return false;
    return std::abs(g.dp) >= k * g.sigma;
  }
};

struct Spread {
  static constexpr const char* name = "Spread";
  static constexpr Rc fail = Rc::SpreadTooWide;
  double max_spread = 0.05;
  bool pass(const GateIn& g) noexcept {
    if (!prob(g.t.yes_bid) || !prob(g.t.yes_ask) || g.t.yes_bid > g.t.yes_ask) return false;
    return g.t.yes_ask - g.t.yes_bid <= max_spread + 1e-12;
  }
};

struct Depth {
  static constexpr const char* name = "Depth";
  static constexpr Rc fail = Rc::ThinBook;
  double min_qty = 100;
  int levels = 3;
  bool pass(const GateIn& g) noexcept {
    if (!num(g.t.bids[0].qty) || !num(g.t.asks[0].qty)) return false;
    double b = 0, a = 0;
    for (int i = 0; i < levels && i < kDepth && num(g.t.bids[i].qty); ++i) b += g.t.bids[i].qty;
    for (int i = 0; i < levels && i < kDepth && num(g.t.asks[i].qty); ++i) a += g.t.asks[i].qty;
    return b >= min_qty && a >= min_qty;
  }
};

struct Session {
  static constexpr const char* name = "Session";
  static constexpr Rc fail = Rc::OutOfSession;
  bool enabled = false;
  bool full_calendar = false;
  bool pass(const GateIn& g) noexcept {
    return !enabled || (full_calendar ? us_equity_regular_session(g.t.ts_ns) : us_equity_session(g.t.ts_ns));
  }
};

struct Cooldown {
  static constexpr const char* name = "Cooldown";
  static constexpr Rc fail = Rc::Cooldown;
  std::int64_t min_ns = 0;
  std::int64_t last_ns = std::numeric_limits<std::int64_t>::min();
  bool pass(const GateIn& g) noexcept {
    if (min_ns <= 0 || last_ns == std::numeric_limits<std::int64_t>::min()) return true;
    return g.now_ns - last_ns >= min_ns;
  }
  void on_order(std::int64_t now_ns) noexcept { last_ns = now_ns; }
};

struct EventWindow {
  static constexpr const char* name = "EventWindow";
  static constexpr Rc fail = Rc::OutsideEventWindow;
  std::int64_t window_ns = 3600 * kNsPerSec;
  double threshold = 0.5;
  std::int64_t opened_ns = std::numeric_limits<std::int64_t>::min();
  bool pass(const GateIn& g) noexcept {
    if (num(g.trigger) && std::abs(g.trigger) >= threshold) opened_ns = g.t.ts_ns;
    if (opened_ns == std::numeric_limits<std::int64_t>::min()) return false;
    return g.t.ts_ns >= opened_ns && g.t.ts_ns - opened_ns <= window_ns;
  }
  bool is_open(std::int64_t ts) const noexcept {
    return opened_ns != std::numeric_limits<std::int64_t>::min() && ts >= opened_ns && ts - opened_ns <= window_ns;
  }
};

using AnyGate = std::variant<Staleness, Sigma, Spread, Depth, Session, Cooldown, EventWindow>;

template <std::size_t N>
bool run_gates(std::array<AnyGate, N>& gates, const GateIn& in, Rc& failed) noexcept {
  for (auto& gate : gates) {
    const bool ok = std::visit([&](auto& g) noexcept {
      const bool p = g.pass(in);
      if (!p) failed = std::decay_t<decltype(g)>::fail;
      return p;
    }, gate);
    if (!ok) return false;
  }
  return true;
}

template <std::size_t N>
void gates_on_order(std::array<AnyGate, N>& gates, std::int64_t now_ns) noexcept {
  for (auto& gate : gates)
    if (auto* c = std::get_if<Cooldown>(&gate)) c->on_order(now_ns);
}

}
