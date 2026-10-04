#pragma once
#include <cmath>
#include "hedgecore/market.hpp"
#include "hedgecore/reasons.hpp"
#include "hedgecore/util.hpp"

namespace hedgecore::blocks {

struct NoTradeBand {
  static constexpr const char* name = "NoTradeBand";
  static constexpr Rc fail = Rc::InsideBand;
  double band = 10;
  bool pass(double delta) const noexcept { return num(delta) && delta != 0 && std::abs(delta) >= band; }
};

struct FeeGate {
  static constexpr const char* name = "FeeGate";
  double ratio = 1.0;
  Rc check(double benefit, double cost) const noexcept {
    if (!num(benefit) || !num(cost)) return Rc::FeeUnknown;
    return benefit >= cost * ratio ? Rc::None : Rc::BelowFees;
  }
};

struct Slicer {
  static constexpr const char* name = "Slicer";
  double child_max = 0;
  double clip(double qty, bool& sliced) const noexcept {
    sliced = false;
    if (child_max > 0 && std::abs(qty) > child_max) { sliced = true; return qty > 0 ? child_max : -child_max; }
    return qty;
  }
};

struct PassiveAggressive {
  static constexpr const char* name = "PassiveAggressive";
  double urgency_threshold = 1.0;
  bool aggressive(double urgency) const noexcept { return !num(urgency) || urgency >= urgency_threshold; }
  double limit(int side, double bid, double ask, double urgency) const noexcept {
    if (aggressive(urgency) || !num(bid) || !num(ask) || bid > ask) return kNaN;
    return side > 0 ? bid : ask;
  }
};

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

}
