#pragma once
#include <cmath>
#include <cstdint>
#include <limits>
#include "hedgecore/market.hpp"
#include "hedgecore/reasons.hpp"
#include "hedgecore/util.hpp"

namespace hedgecore {

enum class Tri : std::uint8_t { False = 0, True = 1, Missing = 2 };

inline constexpr std::int64_t kNoTime = std::numeric_limits<std::int64_t>::min();

inline double poly_taker_fee(double rate, double p) noexcept {
  if (!num(rate) || rate < 0 || !prob(p)) return kNaN;
  return rate * p * (1.0 - p);
}

namespace blocks {

struct NestedGuard {
  static constexpr const char* name = "NestedGuard";
  static constexpr Rc fail = Rc::NotNested;
  bool pass(Tri nested) const noexcept { return nested == Tri::True; }
};

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

struct ContractCap {
  static constexpr const char* name = "ContractCap";
  double cap = 0;
  double room(double held) const noexcept {
    if (cap <= 0) return std::numeric_limits<double>::infinity();
    if (!num(held)) return kNaN;
    return cap - held;
  }
};

struct CapitalLock {
  static constexpr const char* name = "CapitalLock";
  double locked = 0;
  double peak = 0;
  void add(double qty, double rich_px, double cheap_px, double fees_per_contract) noexcept {
    locked += qty * ((1.0 - rich_px) + cheap_px + fees_per_contract);
    if (locked > peak) peak = locked;
  }
};

}
}
