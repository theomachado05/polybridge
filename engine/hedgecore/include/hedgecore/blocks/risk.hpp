#pragma once
// Risk blocks (UI kind: Gate, since they cap or stop trading). Kill switches latch: once tripped, the family holds.
#include <cmath>
#include <cstdint>
#include <limits>
#include "hedgecore/market.hpp"
#include "hedgecore/reasons.hpp"
#include "hedgecore/util.hpp"

namespace hedgecore::blocks {

// |target| <= max_abs.
struct PositionCap {
  static constexpr const char* name = "PositionCap";
  double max_abs = 0;
  double clamp(double target, bool& capped) const noexcept {
    capped = false;
    if (num(target) && std::abs(target) > max_abs) { capped = true; return target > 0 ? max_abs : -max_abs; }
    return target;
  }
};

// |target| * px * multiplier <= max_notional; max_notional <= 0 disables. Unknown px returns NaN (family holds).
struct NotionalCap {
  static constexpr const char* name = "NotionalCap";
  double max_notional = 0;
  double clamp(double target, double px, double multiplier, bool& capped) const noexcept {
    capped = false;
    if (max_notional <= 0) return target;
    if (!num(px) || px <= 0 || !num(target)) return kNaN;
    const double lim = floor_units(max_notional / (px * multiplier));
    if (std::abs(target) > lim) { capped = true; return target > 0 ? lim : -lim; }
    return target;
  }
};

// Latches when peak equity - equity > max_dd ($). max_dd <= 0 disables.
struct DrawdownKill {
  static constexpr const char* name = "DrawdownKill";
  double max_dd = 0;
  double peak = -std::numeric_limits<double>::infinity();
  bool killed = false;
  bool update(double equity) noexcept {
    if (max_dd <= 0 || !num(equity)) return killed;
    if (equity > peak) peak = equity;
    if (peak - equity > max_dd) killed = true;
    return killed;
  }
};

// Armed with the sign of the cross-venue gap at entry; latches when the gap flips past -tol on the other side.
struct GapFlipKill {
  static constexpr const char* name = "GapFlipKill";
  double tol = 0.0;
  int entry_sign = 0;
  bool killed = false;
  void arm(double gap) noexcept { entry_sign = sgn(gap); }
  void disarm() noexcept { entry_sign = 0; }
  bool update(double gap) noexcept {
    if (entry_sign != 0 && num(gap) && gap * entry_sign < -tol) killed = true;
    return killed;
  }
};

// Stops trading for the rest of the UTC day once the day's loss exceeds max_loss ($); resets each day.
struct DailyLossCap {
  static constexpr const char* name = "DailyLossCap";
  double max_loss = 0;
  std::int64_t day = std::numeric_limits<std::int64_t>::min();
  double day_start = 0;
  bool tripped = false;
  bool update(std::int64_t ts_ns, double equity) noexcept {
    if (max_loss <= 0 || !num(equity)) return tripped;
    const std::int64_t d = ts_ns >= 0 ? ts_ns / kNsPerDay : -((-ts_ns + kNsPerDay - 1) / kNsPerDay);
    if (d != day) { day = d; day_start = equity; tripped = false; }
    if (day_start - equity > max_loss) tripped = true;
    return tripped;
  }
};

}  // namespace hedgecore::blocks
