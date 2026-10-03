#pragma once
// FeeModel: the cost of a fill, per instrument and venue. Used by replay() and by the routing and fee-gate blocks.
// Defaults are documented assumptions, not measured: equity $0.0035/share (IBKR-style), options $0.65/contract,
// Polymarket taker 0 (most markets), Kalshi taker 0.07 * C * P * (1 - P).
#include <algorithm>
#include <cmath>
#include "hedgecore/market.hpp"

namespace hedgecore {

struct FeeModel {
  double equity_per_share = 0.0035;
  double equity_min_per_order = 0.0;
  double equity_half_spread = 0.01;      // $/share, assumed only when the tick has no under_bid/under_ask
  double option_per_contract = 0.65;
  double option_multiplier = 100.0;
  double option_half_spread = 0.05;      // $/share of premium; ticks carry only the option mid
  double poly_taker_rate = 0.0;          // fraction of notional
  double kalshi_coef = 0.07;             // fee = coef * qty * p * (1 - p)
  double other_venue_half_spread = 0.01; // the other venue is known only by its mid

  constexpr double multiplier(Instrument i) const noexcept { return i == Instrument::Option ? option_multiplier : 1.0; }

  // Fee in $ for a fill of |qty| units at px. NaN in, NaN out.
  double fee(Instrument i, Venue v, double qty, double px) const noexcept {
    const double q = std::abs(qty);
    switch (i) {
      case Instrument::Equity: return std::max(q * equity_per_share, q > 0 ? equity_min_per_order : 0.0);
      case Instrument::Option: return q * option_per_contract;
      case Instrument::PredYes:
      case Instrument::PredNo:
        if (!(px >= 0 && px <= 1)) return kNaN;
        return v == Venue::Kalshi ? kalshi_coef * q * px * (1 - px) : poly_taker_rate * q * px;
    }
    return kNaN;
  }
  // Per-unit fee (for gates that compare per-share benefit against per-share cost).
  double unit_fee(Instrument i, Venue v, double px) const noexcept { return fee(i, v, 1.0, px); }
};

}  // namespace hedgecore
