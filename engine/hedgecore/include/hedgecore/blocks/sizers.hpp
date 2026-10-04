#pragma once
#include <cmath>
#include "hedgecore/market.hpp"
#include "hedgecore/util.hpp"

namespace hedgecore::blocks {

struct DeltaBridge {
  static constexpr const char* name = "DeltaBridge";
  double coverage = 0.5;
  double shares = 0;
  double target(double p_adverse) const noexcept {
    if (!prob(p_adverse) || !num(shares)) return kNaN;
    return std::round(coverage * shares * p_adverse);
  }
};

struct LinearExposure {
  static constexpr const char* name = "LinearExposure";
  double beta = 1.0, x0 = 0.0, max_cov = 1.0, shares = 0;
  double target(double x) const noexcept {
    if (!num(x) || !num(shares)) return kNaN;
    return std::round(shares * clampd(beta * (x - x0), 0.0, max_cov));
  }
};

struct ConvexExposure {
  static constexpr const char* name = "ConvexExposure";
  double coverage = 0.5, gamma = 2.0, shares = 0;
  double target(double p) const noexcept {
    if (!prob(p) || !num(shares)) return kNaN;
    return std::round(coverage * shares * std::pow(p, gamma));
  }
};

struct KellyCapped {
  static constexpr const char* name = "KellyCapped";
  double cap = 0.1, bankroll = 10'000;
  double fraction(double q, double price) const noexcept {
    if (!prob(q) || !(price > 0 && price < 1)) return kNaN;
    return clampd((q - price) / (1 - price), 0.0, cap);
  }
  double target(double q, double price) const noexcept {
    const double f = fraction(q, price);
    return num(f) ? floor_units(f * bankroll / price) : kNaN;
  }
};

struct VolTarget {
  static constexpr const char* name = "VolTarget";
  double target_sigma = 0.02, lo = 0.25, hi = 2.0;
  double scale(double sigma) const noexcept {
    if (!num(sigma) || sigma < 0) return kNaN;
    if (sigma == 0) return hi;
    return clampd(target_sigma / sigma, lo, hi);
  }
};

struct FixedNotional {
  static constexpr const char* name = "FixedNotional";
  double notional = 1'000;
  double target(double px, double multiplier = 1.0) const noexcept {
    if (!num(px) || px <= 0 || !num(multiplier) || multiplier <= 0) return kNaN;
    return floor_units(notional / (px * multiplier));
  }
};

}
