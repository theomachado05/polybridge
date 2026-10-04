#pragma once
// Blocks of the two micro families (ladder_pair, touch_ticket_reference). Same rules as the other blocks: no
// allocation, no virtual calls, a missing input (NaN, or Tri::Missing) fails closed and is never read as 0.
#include <cmath>
#include <cstdint>
#include <limits>
#include "hedgecore/market.hpp"
#include "hedgecore/reasons.hpp"
#include "hedgecore/util.hpp"

namespace hedgecore {

// A flag supplied upstream (the linker's nested verdict, the evidence gate's validated verdict). Missing is its own
// state: a flag nobody set is not false and not true.
enum class Tri : std::uint8_t { False = 0, True = 1, Missing = 2 };

inline constexpr std::int64_t kNoTime = std::numeric_limits<std::int64_t>::min();

// Polymarket taker fee per contract at price p: rate * p * (1 - p) (the fee schedule with exponent 1). NaN when the
// rate or the price is unknown.
inline double poly_taker_fee(double rate, double p) noexcept {
  if (!num(rate) || rate < 0 || !prob(p)) return kNaN;
  return rate * p * (1.0 - p);
}

namespace blocks {

// Passes only when the linker marked the pair nested. False and Missing both refuse.
struct NestedGuard {
  static constexpr const char* name = "NestedGuard";
  static constexpr Rc fail = Rc::NotNested;
  bool pass(Tri nested) const noexcept { return nested == Tri::True; }
};

// Every quote time must be known, not in the future, and at most max_ns old at `now`.
struct FreshnessGuard {
  static constexpr const char* name = "FreshnessGuard";
  static constexpr Rc fail = Rc::Stale;
  std::int64_t max_ns = 30 * kNsPerSec;
  bool fresh(std::int64_t quote_ns, std::int64_t now_ns) const noexcept {
    if (quote_ns == kNoTime || quote_ns > now_ns || max_ns < 0) return false;
    return static_cast<std::uint64_t>(now_ns) - static_cast<std::uint64_t>(quote_ns) <=
           static_cast<std::uint64_t>(max_ns);
  }
};

// Contracts that may still be added under a cap, given what is already held. cap <= 0 disables the cap (returns
// +inf). An unknown holding returns NaN, so the family holds instead of guessing.
struct ContractCap {
  static constexpr const char* name = "ContractCap";
  double cap = 0;
  double room(double held) const noexcept {
    if (cap <= 0) return std::numeric_limits<double>::infinity();
    if (!num(held)) return kNaN;
    return cap - held;
  }
};

// Capital locked until resolution by the ladder pairs held: per contract, (1 - rich sale price) + cheap purchase price
// + both fees, i.e. the most the pair can lose before the result. Accounting only; it caps nothing.
struct CapitalLock {
  static constexpr const char* name = "CapitalLock";
  double locked = 0;  // $
  double peak = 0;    // $
  void add(double qty, double rich_px, double cheap_px, double fees_per_contract) noexcept {
    locked += qty * ((1.0 - rich_px) + cheap_px + fees_per_contract);
    if (locked > peak) peak = locked;
  }
};

}  // namespace blocks
}  // namespace hedgecore
