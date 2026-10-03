#pragma once
// hedgecore: the systematic hedge algorithm behind a user-approved PolyBridge hedge.
// Pipeline per tick: validate -> staleness gate -> sigma gate -> DeltaBridge size -> risk cap -> band.
// Gates are std::variant stages (static dispatch). on_tick allocates nothing and makes no virtual calls.
#include <array>
#include <variant>
#include "hedgecore/types.hpp"

namespace hedgecore {

struct StalenessGate {
  std::int64_t max_ns;
  bool pass(const Tick& t, std::int64_t now_ns) const noexcept { return now_ns - t.ts_ns <= max_ns; }
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
  void on_fill(double qty) noexcept { hedge_ += qty; }
  double current_hedge() const noexcept { return hedge_; }

 private:
  HedgeSpec spec_;
  std::array<Gate, 2> gates_;
  double hedge_ = 0.0;
  bool sized_once_ = false;
  bool spec_valid_ = false;  // computed once in the constructor
};

}  // namespace hedgecore
