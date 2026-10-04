#pragma once
#include <algorithm>
#include <cmath>
#include "hedgecore/market.hpp"

namespace hedgecore {

struct FeeModel {
  double equity_per_share = 0.0035;
  double equity_min_per_order = 0.0;
  double equity_half_spread = 0.01;
  double option_per_contract = 0.65;
  double option_multiplier = 100.0;
  double option_half_spread = 0.05;
  double poly_taker_rate = 0.0;
  double kalshi_coef = 0.07;
  double other_venue_half_spread = 0.01;

  constexpr double multiplier(Instrument i) const noexcept { return i == Instrument::Option ? option_multiplier : 1.0; }

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
  double unit_fee(Instrument i, Venue v, double px) const noexcept { return fee(i, v, 1.0, px); }
};

}
