#pragma once
// Gate blocks (UI kind: Gate). Each gate answers pass(GateIn) and names its failure reason. Gates fail closed when the
// field they check is missing (NaN): an unknown spread is not a tight spread. AnyGate is a std::variant so a family
// can hold a fixed array of gates and run them with static dispatch (no virtual calls, no allocation).
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
  double dp = kNaN;          // latest one-step change of the family's probability signal
  double sigma = kNaN;       // its volatility before this change
  double trigger = kNaN;     // event trigger value (EventWindow)
};

struct Staleness {
  static constexpr const char* name = "Staleness";
  static constexpr Rc fail = Rc::Stale;
  std::int64_t max_ns = 2 * kNsPerSec;
  // Fails for future-dated ticks and age > max_ns; overflow-safe (unsigned difference only when ts <= now).
  bool pass(const GateIn& g) noexcept {
    if (g.t.ts_ns > g.now_ns || max_ns < 0) return false;
    const auto age = static_cast<std::uint64_t>(g.now_ns) - static_cast<std::uint64_t>(g.t.ts_ns);
    return age <= static_cast<std::uint64_t>(max_ns);
  }
};

// Passes when |dp| >= k * sigma. Warm-up (sigma unknown) passes so the initial position can be sized; a missing dp
// fails. k <= 0 disables the gate.
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

// YES spread on this venue must be <= max_spread (probability points).
struct Spread {
  static constexpr const char* name = "Spread";
  static constexpr Rc fail = Rc::SpreadTooWide;
  double max_spread = 0.05;
  bool pass(const GateIn& g) noexcept {
    if (!prob(g.t.yes_bid) || !prob(g.t.yes_ask) || g.t.yes_bid > g.t.yes_ask) return false;
    return g.t.yes_ask - g.t.yes_bid <= max_spread + 1e-12;
  }
};

// Minimum liquidity: both sides of the YES book must show >= min_qty over the top `levels`.
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

// US equity regular hours (09:30-16:00 ET, Mon-Fri). Disabled when enabled == false (replay on daily bars).
struct Session {
  static constexpr const char* name = "Session";
  static constexpr Rc fail = Rc::OutOfSession;
  bool enabled = false;
  // false: us_equity_session (rule-7.2 holidays, 16:00 close every day). true: us_equity_regular_session (also
  // one-off closures and 13:00 early closes, matching the backend session clock). Opt-in per family.
  bool full_calendar = false;
  bool pass(const GateIn& g) noexcept {
    return !enabled || (full_calendar ? us_equity_regular_session(g.t.ts_ns) : us_equity_session(g.t.ts_ns));
  }
};

// At least min_ns between orders. The family calls on_order(now) when it emits one.
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

// Opens when |trigger| >= threshold and stays open for window_ns of tick time; passes only while open.
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

// Runs gates in order; on the first failure writes its reason and returns false.
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

}  // namespace hedgecore::blocks
