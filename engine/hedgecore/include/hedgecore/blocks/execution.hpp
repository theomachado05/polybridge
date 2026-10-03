#pragma once
// Execution blocks (UI kind: Execution): whether a desired change is worth trading, and how to work the order.
#include <cmath>
#include "hedgecore/market.hpp"
#include "hedgecore/reasons.hpp"
#include "hedgecore/util.hpp"

namespace hedgecore::blocks {

// Trade only when |delta| >= band; never a zero-quantity order, even with band = 0.
struct NoTradeBand {
  static constexpr const char* name = "NoTradeBand";
  static constexpr Rc fail = Rc::InsideBand;
  double band = 10;
  bool pass(double delta) const noexcept { return num(delta) && delta != 0 && std::abs(delta) >= band; }
};

// Trade only when the expected benefit covers ratio * cost (fee + half-spread). Unknown inputs fail as FeeUnknown.
struct FeeGate {
  static constexpr const char* name = "FeeGate";
  double ratio = 1.0;
  Rc check(double benefit, double cost) const noexcept {
    if (!num(benefit) || !num(cost)) return Rc::FeeUnknown;
    return benefit >= cost * ratio ? Rc::None : Rc::BelowFees;
  }
};

// Child order quantity cap; child_max <= 0 disables it. Preserves sign.
struct Slicer {
  static constexpr const char* name = "Slicer";
  double child_max = 0;
  double clip(double qty, bool& sliced) const noexcept {
    sliced = false;
    if (child_max > 0 && std::abs(qty) > child_max) { sliced = true; return qty > 0 ? child_max : -child_max; }
    return qty;
  }
};

// Join the near touch (buy at bid, sell at ask) unless urgency >= threshold, then cross (marketable, NaN limit).
// With no two-sided quote the order goes marketable: there is no touch to join.
struct PassiveAggressive {
  static constexpr const char* name = "PassiveAggressive";
  double urgency_threshold = 1.0;
  bool aggressive(double urgency) const noexcept { return !num(urgency) || urgency >= urgency_threshold; }
  double limit(int side, double bid, double ask, double urgency) const noexcept {
    if (aggressive(urgency) || !num(bid) || !num(ask) || bid > ask) return kNaN;
    return side > 0 ? bid : ask;
  }
};

// Never show more than frac of the displayed opposite-side size. Unknown displayed size leaves the order unchanged
// (the cap cannot be measured, and is not read as zero).
struct IcebergCap {
  static constexpr const char* name = "IcebergCap";
  double frac = 0.5;
  double clip(double qty, double displayed, bool& capped) const noexcept {
    capped = false;
    if (!num(displayed) || displayed < 0 || frac <= 0) return qty;
    const double lim = floor_units(frac * displayed);
    if (std::abs(qty) > lim) { capped = true; return qty > 0 ? lim : -lim; }
    return qty;
  }
};

}  // namespace hedgecore::blocks
