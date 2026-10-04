#pragma once
#include <array>
#include <cmath>
#include <cstdint>
#include <variant>
#include "hedgecore/types.hpp"

namespace hedgecore {

struct StalenessGate {
  std::int64_t max_ns;
  bool pass(const Tick& t, std::int64_t now_ns) const noexcept {
    if (t.ts_ns > now_ns) return false;
    const auto age = static_cast<std::uint64_t>(now_ns) - static_cast<std::uint64_t>(t.ts_ns);
    return max_ns >= 0 && age <= static_cast<std::uint64_t>(max_ns);
  }
  static constexpr Reason fail_reason = Reason::Stale;
};

struct SigmaGate {
  double k;
  double alpha;
  double var = 0.0;
  double last_p = -1.0;
  bool pass(const Tick& t, std::int64_t) noexcept;
  static constexpr Reason fail_reason = Reason::BelowSigma;
};

using Gate = std::variant<StalenessGate, SigmaGate>;

class Engine {
 public:
  explicit Engine(HedgeSpec spec);
  Decision on_tick(const Tick& t, std::int64_t now_ns);
  void on_fill(double qty) noexcept {
    if (!std::isfinite(qty)) { fill_invalid_ = true; return; }
    hedge_ += qty;
  }
  double current_hedge() const noexcept { return hedge_; }

 private:
  HedgeSpec spec_;
  std::array<Gate, 2> gates_;
  double hedge_ = 0.0;
  bool sized_once_ = false;
  double p_at_last_order_ = 0.0;
  bool fill_invalid_ = false;
  bool spec_valid_ = false;
};

}
