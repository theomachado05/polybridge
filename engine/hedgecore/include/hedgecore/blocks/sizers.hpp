#pragma once
// Sizer blocks (UI kind: Impact). Each maps a signal to a target position size (>= 0, in units of the instrument).
// NaN in, NaN out; the family turns a NaN target into a Hold.
#include <cmath>
#include "hedgecore/market.hpp"
#include "hedgecore/util.hpp"

namespace hedgecore::blocks {

// h* = round(c * N * p_adverse): hedge shares proportional to the adverse-event probability (today's Engine).
struct DeltaBridge {
  static constexpr const char* name = "DeltaBridge";
  double coverage = 0.5;  // c in [0, 1]
  double shares = 0;      // N
  double target(double p_adverse) const noexcept {
    if (!prob(p_adverse) || !num(shares)) return kNaN;
    return std::round(coverage * shares * p_adverse);
  }
};

// h* = round(N * clamp(beta * (x - x0), 0, max_cov)): linear sensitivity to a signal above a neutral level.
struct LinearExposure {
  static constexpr const char* name = "LinearExposure";
  double beta = 1.0, x0 = 0.0, max_cov = 1.0, shares = 0;
  double target(double x) const noexcept {
    if (!num(x) || !num(shares)) return kNaN;
    return std::round(shares * clampd(beta * (x - x0), 0.0, max_cov));
  }
};

// h* = round(c * N * p^gamma): convex (gamma > 1) or concave (gamma < 1) response to the adverse probability.
struct ConvexExposure {
  static constexpr const char* name = "ConvexExposure";
  double coverage = 0.5, gamma = 2.0, shares = 0;
  double target(double p) const noexcept {
    if (!prob(p) || !num(shares)) return kNaN;
    return std::round(coverage * shares * std::pow(p, gamma));
  }
};

// Contracts of a binary bought at `price` with fair probability q: Kelly f = (q - price) / (1 - price), clipped to
// [0, cap]; stake f * bankroll buys floor(stake / price) contracts.
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

// Inverse-volatility scale: clamp(target_sigma / sigma, lo, hi). A noisy signal earns a smaller position.
struct VolTarget {
  static constexpr const char* name = "VolTarget";
  double target_sigma = 0.02, lo = 0.25, hi = 2.0;
  double scale(double sigma) const noexcept {
    if (!num(sigma) || sigma < 0) return kNaN;
    if (sigma == 0) return hi;
    return clampd(target_sigma / sigma, lo, hi);
  }
};

// floor(notional / px) units.
struct FixedNotional {
  static constexpr const char* name = "FixedNotional";
  double notional = 1'000;
  double target(double px, double multiplier = 1.0) const noexcept {
    if (!num(px) || px <= 0 || !num(multiplier) || multiplier <= 0) return kNaN;
    return floor_units(notional / (px * multiplier));
  }
};

}  // namespace hedgecore::blocks
